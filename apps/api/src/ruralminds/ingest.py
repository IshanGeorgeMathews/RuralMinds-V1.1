"""Ingest a book from apps/api/books.toml: PDF -> page text (or OCR) -> chunks -> vectors.

    python -m ruralminds.ingest --book ss8-pt1-en [--force]

Everything for one book is written in a single transaction, so a power cut mid-ingest
leaves the previous version intact rather than half a book.
"""

import argparse
import asyncio
import hashlib
import logging
import sqlite3
import tomllib
from dataclasses import dataclass
from pathlib import Path

import httpx
import pypdfium2 as pdfium

from .chunker import Chunk, PageInput, chunk_pages
from .config import settings
from .db import connect, init_schema, serialize_vector
from .llm import EMBED_TIMEOUT, count_tokens, embed
from .pages import PageText, drop_running_titles, extract_pages

log = logging.getLogger("ruralminds.ingest")


@dataclass
class Chapter:
    no: int
    title: str
    start: int


@dataclass
class Book:
    id: str
    title: str
    board: str
    medium: str
    grade: int
    subject: str
    path: Path
    licence: str
    ocr_lang: str
    page_offset: int
    last_page: int
    chapters: list[Chapter]

    def chapter_for(self, pdf_page: int) -> Chapter | None:
        """The last chapter starting on or before this page (chapters are sorted)."""
        if pdf_page > self.last_page:
            return None
        started = [c for c in self.chapters if c.start <= pdf_page]
        return started[-1] if started else None

    def content_pages(self) -> range:
        return range(self.chapters[0].start, self.last_page + 1)


def load_books(manifest: Path) -> dict[str, Book]:
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    books = {}
    for raw in data["book"]:
        chapters = sorted((Chapter(**c) for c in raw.pop("chapters")), key=lambda c: c.start)
        books[raw["id"]] = Book(**{**raw, "path": Path(raw["path"]), "chapters": chapters})
    return books


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_page_inputs(book: Book, pages: list[PageText]) -> list[PageInput]:
    titles = [chapter.title for chapter in book.chapters]
    inputs = []
    for page in pages:
        chapter = book.chapter_for(page.pdf_page)
        if chapter is not None:
            printed = page.pdf_page + book.page_offset
            text = drop_running_titles(page.text, titles)
            inputs.append(PageInput(printed, chapter.no, chapter.title, text))
    return inputs


async def embed_chunks(chunks: list[Chunk]) -> tuple[list[list[float]], list[int]]:
    vectors: list[list[float]] = []
    token_counts: list[int] = []
    async with httpx.AsyncClient(timeout=EMBED_TIMEOUT) as client:
        for start in range(0, len(chunks), settings.embed_batch_size):
            batch = [c.text for c in chunks[start : start + settings.embed_batch_size]]
            vectors.extend(await embed(batch, client))
            token_counts.extend([await count_tokens(text, client) for text in batch])
            log.info("embedded %d/%d chunks", len(vectors), len(chunks))
    return vectors, token_counts


def _replace_document(conn: sqlite3.Connection, book: Book, sha: str, page_count: int) -> int:
    """Insert or refresh the document row, removing its old pages, chunks and vectors."""
    row = conn.execute("SELECT id FROM documents WHERE book_id = ?", (book.id,)).fetchone()
    values = (
        book.title,
        book.board,
        book.medium,
        book.grade,
        book.subject,
        str(book.path),
        sha,
        page_count,
        book.licence,
    )
    if row is None:
        cursor = conn.execute(
            "INSERT INTO documents (title, board, medium, grade, subject, file_path, sha256,"
            " page_count, licence, book_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (*values, book.id),
        )
        return int(cursor.lastrowid)
    doc_id = int(row["id"])
    conn.execute(
        "DELETE FROM chunk_vectors WHERE chunk_id IN (SELECT id FROM chunks WHERE document_id = ?)",
        (doc_id,),
    )
    conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
    conn.execute("DELETE FROM pages WHERE document_id = ?", (doc_id,))
    conn.execute(
        "UPDATE documents SET title=?, board=?, medium=?, grade=?, subject=?, file_path=?,"
        " sha256=?, page_count=?, licence=?, ingested_at=datetime('now') WHERE id=?",
        (*values, doc_id),
    )
    # A changed book invalidates teacher-approved answers built on the old text.
    conn.execute(
        "UPDATE answer_cache SET status='needs_review', updated_at=datetime('now')"
        " WHERE book_id = ? AND doc_sha256 != ?",
        (book.id, sha),
    )
    return doc_id


def store_book(
    conn: sqlite3.Connection,
    book: Book,
    sha: str,
    page_count: int,
    pages: list[PageText],
    chunks: list[Chunk],
    vectors: list[list[float]],
    token_counts: list[int],
) -> None:
    with conn:  # one transaction: all or nothing
        doc_id = _replace_document(conn, book, sha, page_count)
        for page in pages:
            chapter = book.chapter_for(page.pdf_page)
            conn.execute(
                "INSERT INTO pages VALUES (?,?,?,?,?,?,?)",
                (
                    doc_id,
                    page.pdf_page,
                    page.pdf_page + book.page_offset,
                    chapter.no if chapter else None,
                    page.method,
                    len(page.text),
                    page.script_ratio,
                ),
            )
        for ordinal, (chunk, vector, tokens) in enumerate(
            zip(chunks, vectors, token_counts, strict=True)
        ):
            cursor = conn.execute(
                "INSERT INTO chunks (document_id, ordinal, chapter_no, chapter_title, page_start,"
                " page_end, text, token_count) VALUES (?,?,?,?,?,?,?,?)",
                (
                    doc_id,
                    ordinal,
                    chunk.chapter_no,
                    chunk.chapter_title,
                    chunk.page_start,
                    chunk.page_end,
                    chunk.text,
                    tokens,
                ),
            )
            conn.execute(
                "INSERT INTO chunk_vectors VALUES (?,?,?,?,?)",
                (
                    cursor.lastrowid,
                    serialize_vector(vector),
                    book.medium,
                    book.subject,
                    chunk.chapter_no,
                ),
            )


def _already_ingested(conn: sqlite3.Connection, book_id: str, sha: str) -> bool:
    row = conn.execute("SELECT sha256 FROM documents WHERE book_id = ?", (book_id,)).fetchone()
    return row is not None and row["sha256"] == sha


async def ingest(book: Book, force: bool = False) -> None:
    conn = connect(settings.db_path)
    init_schema(conn)
    sha = file_sha256(book.path)
    if not force and _already_ingested(conn, book.id, sha):
        log.info("%s unchanged (sha %s), skipping; use --force to rebuild", book.id, sha[:12])
        return
    page_count = len(pdfium.PdfDocument(book.path))
    pages = extract_pages(
        book.path,
        book.content_pages(),
        book.medium,
        book.ocr_lang,
        settings.ocr_cache_dir / sha[:16],
        min_ratio=settings.min_script_ratio,
        dpi=settings.ocr_dpi,
        workers=settings.ocr_workers,
        tesseract_cmd=settings.tesseract_cmd,
    )
    chunks = chunk_pages(
        build_page_inputs(book, pages), settings.chunk_target_chars, settings.chunk_max_chars
    )
    vectors, token_counts = await embed_chunks(chunks)
    store_book(conn, book, sha, page_count, pages, chunks, vectors, token_counts)
    _report(book, pages, chunks, token_counts)


def _report(book: Book, pages: list[PageText], chunks: list[Chunk], tokens: list[int]) -> None:
    ocr_pages = sum(p.method == "ocr" for p in pages)
    weak = [p.pdf_page for p in pages if p.script_ratio < settings.min_script_ratio]
    print(
        f"{book.id}: {len(pages)} pages ({ocr_pages} OCR), {len(chunks)} chunks, "
        f"tokens min/avg/max {min(tokens)}/{sum(tokens) // len(tokens)}/{max(tokens)}"
    )
    print(f"  pages below script ratio {settings.min_script_ratio}: {weak or 'none'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest textbooks listed in books.toml")
    parser.add_argument("--book", action="append", help="book id (repeatable); default: all")
    parser.add_argument("--force", action="store_true", help="rebuild even if unchanged")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    books = load_books(settings.books_file)
    for book_id in args.book or list(books):
        if book_id not in books:
            parser.error(f"unknown book id {book_id!r}; known: {', '.join(books)}")
        asyncio.run(ingest(books[book_id], force=args.force))


if __name__ == "__main__":
    main()
