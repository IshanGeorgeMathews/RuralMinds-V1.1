"""PDF page text: use the text layer when it is real text, otherwise OCR with Tesseract.

SCERT Malayalam-medium PDFs use legacy ASCII (ML-TT) fonts: the text layer exists but is
Latin gibberish, so "has text" is not enough. We measure how much of the page is in the
script we expect and send anything below the threshold to OCR.
"""

import logging
import os
import re
import subprocess
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import pypdfium2 as pdfium

from .textnorm import normalize

log = logging.getLogger(__name__)

MIN_TEXT_CHARS = 40
_RULE_LINE = re.compile(r"^[0-9 ]{8,}$")  # decorative rule glyphs extract as "1234567890..."
_NUMBER_ONLY = re.compile(r"^\d{1,4}$")
# Running headers/footers repeated on every page. They carry no content, but they cost
# prompt tokens on every retrieved chunk (worst in Malayalam). OCR misreads them in many
# ways, hence the loose Malayalam patterns.
_RUNNING_HEADER = re.compile(
    r"^(1 0|social science|standard v[il1]{2,3}"
    r"|സ്റ്റാൻഡേർഡ്\s*v[il1]{2,3}"
    r"|സാമ\S{0,8}ശാസ\S{0,8}"  # സാമൂഹ്യശാസ്ത്രം (Social Science) and its OCR variants
    r"|\d{1,3}\s+[A-Z][A-Z' ]+|[A-Z][A-Z' ]+\s+\d{1,3})$",  # "12 EARLY HUMAN LIFE"
    re.IGNORECASE,
)
MIN_LINE_LETTERS = 3  # OCR fragments like "Ws", "(2. °", "മ 9"
TITLE_MATCH = 0.8
_INVISIBLE = dict.fromkeys(map(ord, "\ufffe\u00ad\ufeff"))


@dataclass
class PageText:
    pdf_page: int  # 1-based
    text: str
    method: str  # "text" | "ocr"
    script_ratio: float


def script_ratio(text: str, medium: str) -> float:
    """Share of letters that belong to the book's script (Malayalam or Latin)."""
    letters = [ch for ch in text if ch.isalpha()]
    if medium == "ml":
        if not letters:
            return 0.0
        return sum("\u0d00" <= ch <= "\u0d7f" for ch in letters) / len(letters)
    # English: legacy/custom fonts produce control characters and symbols, not letters.
    visible = [ch for ch in text if not ch.isspace()]
    if not visible:
        return 0.0
    return sum(ch.isascii() and ch.isalpha() for ch in visible) / len(visible)


def clean_text(raw: str) -> str:
    """Normalise and drop junk lines; keep one line per extracted line."""
    text = normalize(raw.translate(_INVISIBLE)).replace("\r", "")
    kept = []
    for line in text.split("\n"):
        line = " ".join(line.split())
        if _is_junk_line(line):
            continue
        kept.append(line)
    return "\n".join(kept)


def _is_junk_line(line: str) -> bool:
    if not line or _RULE_LINE.match(line) or _NUMBER_ONLY.match(line):
        return True
    if _RUNNING_HEADER.match(line):
        return True
    return sum(ch.isalpha() for ch in line) < MIN_LINE_LETTERS


def drop_running_titles(text: str, titles: list[str]) -> str:
    """Remove lines that are a chapter title (plus page number), allowing for OCR misreads.

    Done per book at ingest because clean_text does not know the chapter titles.
    """
    wanted = [title.casefold() for title in titles]
    kept = []
    for line in text.split("\n"):
        bare = re.sub(r"\d+", "", line).strip().casefold()
        is_title = any(
            len(bare) <= 2 * len(title)
            and SequenceMatcher(None, bare, title).ratio() >= TITLE_MATCH
            for title in wanted
        )
        if not is_title:
            kept.append(line)
    return "\n".join(kept)


def needs_ocr(text: str, medium: str, min_ratio: float) -> bool:
    return len(text) < MIN_TEXT_CHARS or script_ratio(text, medium) < min_ratio


def render_pgm(page: pdfium.PdfPage, dpi: int) -> bytes:
    """Render a page to an 8-bit greyscale PGM that Tesseract reads from stdin."""
    bitmap = page.render(scale=dpi / 72, grayscale=True)
    width, height, stride = bitmap.width, bitmap.height, bitmap.stride
    buffer = bytes(bitmap.buffer)
    rows = b"".join(buffer[y * stride : y * stride + width] for y in range(height))
    return f"P5 {width} {height} 255\n".encode() + rows


def run_tesseract(image: bytes, lang: str, tesseract_cmd: str) -> str:
    # One thread per process: we already run several pages in parallel.
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
    result = subprocess.run(
        [tesseract_cmd, "stdin", "stdout", "-l", lang],
        input=image,
        capture_output=True,
        env=env,
        check=True,
    )
    return result.stdout.decode("utf-8", errors="replace")


def _ocr_cache_path(cache_dir: Path, pdf_page: int) -> Path:
    return cache_dir / f"{pdf_page:04d}.txt"


def _ocr_pages(
    pdf: pdfium.PdfDocument,
    page_numbers: list[int],
    lang: str,
    cache_dir: Path,
    dpi: int,
    workers: int,
    tesseract_cmd: str,
) -> dict[int, str]:
    """OCR pages in parallel, reusing cached results. Rendering stays on this thread
    because pdfium is not thread-safe; only the Tesseract subprocesses run in the pool."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    results: dict[int, str] = {}
    todo = []
    for number in page_numbers:
        cached = _ocr_cache_path(cache_dir, number)
        if cached.exists():
            results[number] = cached.read_text(encoding="utf-8")
        else:
            todo.append(number)
    batch_size = max(1, workers * 2)  # bounds memory: each rendered page is ~9 MB
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, len(todo), batch_size):
            batch = todo[start : start + batch_size]
            images = [render_pgm(pdf[number - 1], dpi) for number in batch]
            texts = pool.map(lambda image: run_tesseract(image, lang, tesseract_cmd), images)
            for number, text in zip(batch, texts, strict=True):
                _ocr_cache_path(cache_dir, number).write_text(text, encoding="utf-8")
                results[number] = text
            log.info("OCR %d/%d pages", min(start + batch_size, len(todo)), len(todo))
    return results


def extract_pages(
    pdf_path: Path,
    page_numbers: Iterable[int],
    medium: str,
    ocr_lang: str,
    cache_dir: Path,
    *,
    min_ratio: float,
    dpi: int,
    workers: int,
    tesseract_cmd: str,
) -> list[PageText]:
    """Return cleaned text for each requested 1-based page, OCR-ing where needed."""
    pdf = pdfium.PdfDocument(pdf_path)
    layer = {n: clean_text(pdf[n - 1].get_textpage().get_text_range()) for n in page_numbers}
    to_ocr = [n for n, text in layer.items() if needs_ocr(text, medium, min_ratio)]
    ocr_text = _ocr_pages(pdf, to_ocr, ocr_lang, cache_dir, dpi, workers, tesseract_cmd)
    pages = []
    for number, text in layer.items():
        if number in ocr_text:
            text, method = clean_text(ocr_text[number]), "ocr"
        else:
            method = "text"
        pages.append(PageText(number, text, method, round(script_ratio(text, medium), 3)))
    return pages
