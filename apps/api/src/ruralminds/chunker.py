"""Split chapter text into retrieval chunks that remember their printed pages.

Unit of work is the sentence, tagged with the page it came from, so a chunk that spans a
page break still knows page_start and page_end. Chunks never cross a chapter boundary.
SCERT layouts mix boxes and side notes into the text stream; we cannot reliably detect
activity boxes from the text layer, so splitting is by sentence size only (best effort).
"""

import re
from dataclasses import dataclass

_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")
MIN_CHUNK_CHARS = 120


@dataclass
class PageInput:
    printed_page: int
    chapter_no: int
    chapter_title: str
    text: str


@dataclass
class Chunk:
    chapter_no: int
    chapter_title: str
    page_start: int
    page_end: int
    text: str


def split_sentences(text: str, max_chars: int) -> list[str]:
    """Sentence split; very long runs (lists, OCR without full stops) are cut on spaces."""
    sentences = []
    for sentence in _SENTENCE_END.split(" ".join(text.split())):
        while len(sentence) > max_chars:
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            sentences.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            sentences.append(sentence)
    return sentences


def _chapter_chunks(pages: list[PageInput], target: int, max_chars: int) -> list[Chunk]:
    tagged = [(p.printed_page, s) for p in pages for s in split_sentences(p.text, max_chars)]
    chunks: list[Chunk] = []
    current: list[tuple[int, str]] = []
    for page, sentence in tagged:
        size = sum(len(s) + 1 for _, s in current)
        if current and size + len(sentence) > target:
            chunks.append(_make_chunk(pages[0], current))
            # One sentence of overlap keeps context for facts split across chunks.
            current = current[-1:] if len(current[-1][1]) < target // 3 else []
        current.append((page, sentence))
    if current:
        tail = _make_chunk(pages[0], current)
        if chunks and len(tail.text) < MIN_CHUNK_CHARS:
            last = chunks[-1]
            last.text, last.page_end = f"{last.text} {tail.text}", tail.page_end
        else:
            chunks.append(tail)
    return chunks


def _make_chunk(first: PageInput, sentences: list[tuple[int, str]]) -> Chunk:
    return Chunk(
        chapter_no=first.chapter_no,
        chapter_title=first.chapter_title,
        page_start=sentences[0][0],
        page_end=sentences[-1][0],
        text=" ".join(s for _, s in sentences),
    )


def chunk_pages(pages: list[PageInput], target: int, max_chars: int) -> list[Chunk]:
    """Chunk pages in reading order, chapter by chapter."""
    chunks: list[Chunk] = []
    chapter: list[PageInput] = []
    for page in pages:
        if chapter and page.chapter_no != chapter[0].chapter_no:
            chunks.extend(_chapter_chunks(chapter, target, max_chars))
            chapter = []
        if page.text.strip():
            chapter.append(page)
    if chapter:
        chunks.extend(_chapter_chunks(chapter, target, max_chars))
    return chunks
