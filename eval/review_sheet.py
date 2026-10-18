"""Review sheets for eval items: one row per item, with the text the retriever actually sees.

Sheets show the indexed chunk text of the gold pages (OCR text where the PDF text layer was
junk), not the PDF text layer: a reviewer must judge whether the *search* can find the answer.
They contain textbook text, so they are written to data/eval-private/ (git-ignored) only.
"""

import csv
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

BASE_COLUMNS = ["id", "verdict (ok/fix/drop)", "fix note"]
TAIL_COLUMNS = [
    "style",
    "expected",
    "gold_pages",
    "question",
    "key_facts",
    "indexed text of gold pages",
]
NO_TEXT = "(nothing indexed for these pages: OCR or ingestion lost them)"


def indexed_text(conn: sqlite3.Connection, book_id: str, pages: Iterable[int]) -> str:
    """Every chunk of the book that overlaps any of the pages, in reading order, once each."""
    pages = sorted(set(pages))
    if not pages:
        return ""
    rows = conn.execute(
        "SELECT c.page_start, c.page_end, c.text FROM chunks c JOIN documents d"
        " ON d.id = c.document_id WHERE d.book_id = ? AND c.page_end >= ? AND c.page_start <= ?"
        " ORDER BY c.ordinal",
        (book_id, pages[0], pages[-1]),
    ).fetchall()
    chunks = [
        f"[p{start}-{end}] {' '.join(text.split())}"
        for start, end, text in rows
        if any(start <= page <= end for page in pages)
    ]
    return "\n\n".join(chunks) or NO_TEXT


def write_sheet(
    path: Path,
    items: Sequence[dict],
    conn: sqlite3.Connection,
    extra_columns: Sequence[str] = (),
    extra_values: Callable[[dict], list[str]] = lambda item: [],
) -> None:
    """utf-8-sig: Excel only shows Malayalam correctly when the file starts with a BOM."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([*BASE_COLUMNS, *extra_columns, *TAIL_COLUMNS])
        for item in items:
            writer.writerow(
                [
                    item["id"],
                    "",
                    "",
                    *extra_values(item),
                    item.get("style", ""),
                    item.get("expected", ""),
                    " ".join(map(str, item.get("gold_pages", []))),
                    item["question"],
                    item.get("key_facts", ""),
                    indexed_text(conn, item["book_id"], item.get("gold_pages", [])),
                ]
            )
