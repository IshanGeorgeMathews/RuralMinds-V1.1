"""Teacher uploads: validated, safe across power cuts, and never leaving files behind.

Each step leaves the job in a state the server can resume or clean up:

  1. create_job      -> awaiting_file
  2. receive_file    -> streamed to data/uploads/<job>.part under a size cap while hashing,
                        checked to be a real PDF, fsynced, then renamed to data/books/<sha>.pdf
                     -> awaiting_details (page count + bookmarks go back to the form)
  3. set_details     -> queued (title, class, medium, chapters, ...)
  4. JobRunner       -> ingesting: `python -m ruralminds.ingest --job N` in its own process at
                        lower priority, one at a time, so OCR cannot crash or starve the API
                     -> ready | failed (retried up to max_ingest_attempts)
  5. publish         -> students can see it

A rename is atomic, so data/books never holds half a file. The janitor (startup + hourly)
removes .part files, PDFs and OCR caches that no book or live job refers to.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium

from .config import settings
from .db import connect, init_schema
from .ingest import Book, Chapter, ingest_book
from .pagepng import PDFIUM_LOCK

log = logging.getLogger("ruralminds.uploads")

SUBJECTS = ("social_science", "science", "maths", "english", "malayalam", "ict", "other")
BOARDS = ("SCERT-KL", "NCERT", "OTHER")
MAX_CHAPTERS = 60
KEEP_FAILED_DAYS = 7
_SHA_PDF = re.compile(r"^[0-9a-f]{64}\.pdf$")
_OCR_DIR = re.compile(r"^[0-9a-f]{16}$")
_LIVE = ("awaiting_file", "awaiting_details", "queued", "ingesting", "ready")


class UploadError(Exception):
    """A problem the teacher can fix; the message is an i18n key such as upload.too_big."""


@dataclass
class PdfInfo:
    page_count: int
    bookmarks: list[dict[str, object]]  # [{"title": ..., "page": 1-based}], may be empty


# ---------- steps 1-3 (API process) ----------
def create_job(conn: sqlite3.Connection, filename: str, user_id: int) -> int:
    with conn:
        cursor = conn.execute(
            "INSERT INTO ingest_jobs (filename, created_by) VALUES (?, ?)",
            (Path(filename).name[:200] or "book.pdf", user_id),
        )
    return int(cursor.lastrowid)


def _job(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM ingest_jobs WHERE id = ?", (job_id,)).fetchone()


def _set_job(conn: sqlite3.Connection, job_id: int, **values: object) -> None:
    columns = ", ".join(f"{name} = ?" for name in values)
    with conn:
        conn.execute(
            f"UPDATE ingest_jobs SET {columns}, updated_at = datetime('now') WHERE id = ?",
            (*values.values(), job_id),
        )


def check_disk(directory: Path, incoming_bytes: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(directory).free
    if free - incoming_bytes < settings.min_free_disk_gb * 1024**3:
        raise UploadError("upload.disk_full")


async def receive_file(
    conn: sqlite3.Connection, job_id: int, body: AsyncIterator[bytes]
) -> PdfInfo:
    """Stream the PDF to disk. The size cap is enforced on bytes actually received, not on the
    Content-Length header, so a wrong or missing header cannot fill the disk."""
    job = _job(conn, job_id)
    if job is None or job["status"] != "awaiting_file":
        raise UploadError("upload.wrong_state")
    limit = settings.max_upload_mb * 1024 * 1024
    check_disk(settings.books_dir, limit)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    part = settings.uploads_dir / f"{job_id}.part"
    digest, size = hashlib.sha256(), 0
    try:
        with part.open("wb") as handle:
            async for piece in body:
                size += len(piece)
                if size > limit:
                    raise UploadError("upload.too_big")
                digest.update(piece)
                handle.write(piece)
            handle.flush()
            os.fsync(handle.fileno())  # on disk before we call it received
        info = await asyncio.to_thread(inspect_pdf, part)
        sha = digest.hexdigest()
        _check_duplicate(conn, sha, job_id)
        settings.books_dir.mkdir(parents=True, exist_ok=True)
        os.replace(part, settings.books_dir / f"{sha}.pdf")
    finally:
        part.unlink(missing_ok=True)
    _set_job(
        conn, job_id, status="awaiting_details", sha256=sha, bytes=size, page_count=info.page_count
    )
    return info


def inspect_pdf(path: Path) -> PdfInfo:
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise UploadError("upload.not_pdf")
    # pdfium is not thread-safe: share the page renderer's lock (a clash can crash the process).
    with PDFIUM_LOCK:
        return _inspect(path)


def _inspect(path: Path) -> PdfInfo:
    try:
        pdf = pdfium.PdfDocument(path)
    except pdfium.PdfiumError as exc:
        raise UploadError("upload.corrupt") from exc
    try:
        page_count = len(pdf)
        if page_count == 0:
            raise UploadError("upload.corrupt")
        if page_count > settings.max_pages:
            raise UploadError("upload.too_many_pages")
        pdf[page_count - 1].get_textpage()  # a cut-off file fails on its last page
        bookmarks = []
        for item in pdf.get_toc(max_depth=1):
            dest = item.get_dest()
            if dest is not None and len(bookmarks) < MAX_CHAPTERS:
                bookmarks.append({"title": item.get_title(), "page": dest.get_index() + 1})
        return PdfInfo(page_count, bookmarks)
    except pdfium.PdfiumError as exc:
        raise UploadError("upload.corrupt") from exc
    finally:
        pdf.close()  # Windows cannot rename a file that is still open


def _check_duplicate(conn: sqlite3.Connection, sha: str, job_id: int) -> None:
    in_library = conn.execute("SELECT 1 FROM documents WHERE sha256 = ?", (sha,)).fetchone()
    placeholders = ",".join("?" * len(_LIVE))
    in_progress = conn.execute(
        f"SELECT 1 FROM ingest_jobs WHERE sha256 = ? AND id != ? AND status IN ({placeholders})",
        (sha, job_id, *_LIVE),
    ).fetchone()
    if in_library or in_progress:
        raise UploadError("upload.duplicate")


def validate_details(conn: sqlite3.Connection, details: dict, page_count: int) -> list[str]:
    """All problems at once (i18n keys), so the teacher can fix the form in one go."""
    errors = []
    chapters = details["chapters"]
    starts = [chapter["start"] for chapter in chapters]
    if details["subject"] not in SUBJECTS:
        errors.append("upload.bad_subject")
    if details["board"] not in BOARDS:
        errors.append("upload.bad_board")
    if not 1 <= len(chapters) <= MAX_CHAPTERS:
        errors.append("upload.chapters_count")
    if any(not 1 <= start <= page_count for start in starts):
        errors.append("upload.chapter_page_range")
    if starts != sorted(set(starts)):
        errors.append("upload.chapter_order")
    if len({chapter["no"] for chapter in chapters}) != len(chapters):
        errors.append("upload.chapter_numbers")
    last_page = details.get("last_page") or page_count
    if not 1 <= last_page <= page_count or (starts and last_page < max(starts)):
        errors.append("upload.last_page_range")
    known = {row[0] for row in conn.execute("SELECT id FROM classes")}
    if not set(details["class_ids"]) <= known:
        errors.append("upload.unknown_class")
    return errors


def set_details(conn: sqlite3.Connection, job_id: int, details: dict) -> list[str]:
    job = _job(conn, job_id)
    if job is None or job["status"] not in ("awaiting_details", "failed"):
        return ["upload.wrong_state"]
    errors = validate_details(conn, details, job["page_count"])
    if not errors:
        details = {**details, "last_page": details.get("last_page") or job["page_count"]}
        _set_job(
            conn,
            job_id,
            status="queued",
            metadata=json.dumps(details, ensure_ascii=False),
            attempts=0,
            error=None,
        )
    return errors


def book_from_job(job: sqlite3.Row) -> Book:
    meta = json.loads(job["metadata"])
    chapters = [Chapter(c["no"], c["title"], c["start"]) for c in meta["chapters"]]
    return Book(
        id=f"up-{job['sha256'][:12]}",
        title=meta["title"],
        board=meta["board"],
        medium=meta["medium"],
        grade=meta["grade"],
        subject=meta["subject"],
        path=settings.books_dir / f"{job['sha256']}.pdf",
        licence=meta.get("licence") or "",
        ocr_lang="mal+eng" if meta["medium"] == "ml" else "eng",
        page_offset=meta.get("page_offset", 0),
        last_page=meta["last_page"],
        chapters=sorted(chapters, key=lambda chapter: chapter.start),
        status="ready",  # students see it only after the teacher tries it and publishes
    )


# ---------- step 4: the ingest process ----------
@contextmanager
def ingest_lock() -> Iterator[None]:
    """One ingest at a time across processes. The OS drops the lock if the process dies,
    so a power cut or crash can never leave it stuck."""
    path = settings.uploads_dir / "ingest.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX)
            yield


async def run_job(job_id: int) -> int:
    """Body of `python -m ruralminds.ingest --job N`. Safe to run twice: a book that is already
    stored with this sha is not ingested again, only finished off."""
    conn = connect(settings.db_path)
    init_schema(conn)
    with ingest_lock():
        job = _job(conn, job_id)
        if job is None or job["status"] != "ingesting":
            return 0
        book = book_from_job(job)
        try:
            existing = conn.execute(
                "SELECT id FROM documents WHERE book_id = ? AND sha256 = ?",
                (book.id, job["sha256"]),
            ).fetchone()
            doc_id = existing["id"] if existing else await ingest_book(conn, book, job["sha256"])
        except Exception as exc:  # report any failure to the teacher instead of dying silently
            log.exception("ingest job %d failed", job_id)
            _set_job(conn, job_id, error=f"{type(exc).__name__}: {exc}"[:500])
            return 1
        with conn:
            allocate(conn, doc_id, json.loads(job["metadata"])["class_ids"])
            conn.execute(
                "UPDATE ingest_jobs SET status = 'ready', document_id = ?, error = NULL,"
                " updated_at = datetime('now') WHERE id = ?",
                (doc_id, job_id),
            )
    # The book is usable now. Study notes need the chat model and take a long time, so they
    # run in their own process: the next upload in the queue does not wait for them.
    start_notes_process(book.id, doc_id)
    return 0


def start_notes_process(
    book_id: str, doc_id: int, force: bool = False, chapter: int | None = None
) -> None:
    """Fire and forget, at lower priority; progress goes to logs/notes-<id>.log."""
    command = [sys.executable, "-m", "ruralminds.notes", "--book", book_id]
    command += ["--force"] if force else []
    command += ["--chapter", str(chapter)] if chapter is not None else []
    logs = Path("logs")
    logs.mkdir(exist_ok=True)
    with (logs / f"notes-{doc_id}.log").open("ab") as output:
        subprocess.Popen(
            command,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0),
        )


def allocate(conn: sqlite3.Connection, doc_id: int, class_ids: list[int]) -> None:
    """Replace a book's class allocation. Caller owns the transaction."""
    conn.execute("DELETE FROM class_books WHERE document_id = ?", (doc_id,))
    conn.executemany(
        "INSERT INTO class_books (class_id, document_id) VALUES (?, ?)",
        [(class_id, doc_id) for class_id in dict.fromkeys(class_ids)],
    )


def recover_interrupted(conn: sqlite3.Connection) -> None:
    """At startup: a job that was ingesting when the power went is queued again (or failed
    after too many attempts); an upload that never finished is marked failed."""
    with conn:
        conn.execute(
            "UPDATE ingest_jobs SET status = CASE WHEN attempts >= ? THEN 'failed' ELSE 'queued'"
            " END, error = COALESCE(error, 'interrupted'), updated_at = datetime('now')"
            " WHERE status = 'ingesting'",
            (settings.max_ingest_attempts,),
        )
        conn.execute(
            "UPDATE ingest_jobs SET status = 'failed', error = 'upload.interrupted',"
            " updated_at = datetime('now') WHERE status = 'awaiting_file'"
            " AND created_at < datetime('now', ?)",
            (f"-{settings.stale_upload_hours} hours",),
        )


class JobRunner:
    """Runs queued jobs one by one in a child process; wakes up when a job is queued."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        recover_interrupted(self.conn)
        janitor(self.conn)
        self._task = asyncio.create_task(self._loop())

    def wake(self) -> None:
        self._wake.set()

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        last_janitor = time.monotonic()
        while True:
            row = self.conn.execute(
                "SELECT id, attempts FROM ingest_jobs WHERE status = 'queued' ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=60)
                self._wake.clear()
                if time.monotonic() - last_janitor > 3600:
                    janitor(self.conn)
                    last_janitor = time.monotonic()
                continue
            await self._run(row["id"], row["attempts"] + 1)

    async def _run(self, job_id: int, attempt: int) -> None:
        _set_job(self.conn, job_id, status="ingesting", attempts=attempt)
        code = await asyncio.to_thread(_run_child, job_id)
        if code == 0:
            return
        retry = attempt < settings.max_ingest_attempts
        _set_job(self.conn, job_id, status="queued" if retry else "failed")


def _run_child(job_id: int) -> int:
    logs = Path("logs")
    logs.mkdir(exist_ok=True)
    # Lower priority on Windows so students' answers stay fast while a book is processed.
    flags = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
    with (logs / f"ingest-job-{job_id}.log").open("ab") as output:
        child = subprocess.Popen(
            [sys.executable, "-m", "ruralminds.ingest", "--job", str(job_id)],
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        return child.wait()


# ---------- deleting and cleaning ----------
def delete_book(conn: sqlite3.Connection, doc_id: int) -> bool:
    """Remove a book and everything derived from it. Database first (one transaction), files
    after; if the power goes in between, the janitor removes the orphaned files later."""
    doc = conn.execute("SELECT book_id, sha256 FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None:
        return False
    with conn:
        # vec0 is a virtual table: ON DELETE CASCADE does not reach it.
        conn.execute(
            "DELETE FROM chunk_vectors WHERE chunk_id IN"
            " (SELECT id FROM chunks WHERE document_id = ?)",
            (doc_id,),
        )
        conn.execute(
            "UPDATE answer_cache SET status = 'rejected', updated_at = datetime('now')"
            " WHERE book_id = ?",
            (doc["book_id"],),
        )
        conn.execute(
            "DELETE FROM ingest_jobs WHERE document_id = ? OR sha256 = ?", (doc_id, doc["sha256"])
        )
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))  # cascades the rest
    shutil.rmtree(settings.page_cache_dir / str(doc_id), ignore_errors=True)
    janitor(conn)
    return True


def delete_job(conn: sqlite3.Connection, job_id: int) -> bool:
    """Cancel an upload that has not become a book. A running ingest cannot be cancelled."""
    job = _job(conn, job_id)
    if job is None or job["status"] in ("ingesting", "ready"):
        return False
    with conn:
        conn.execute("DELETE FROM ingest_jobs WHERE id = ?", (job_id,))
    janitor(conn)
    return True


def janitor(conn: sqlite3.Connection) -> list[Path]:
    """Delete files nothing refers to. Only touches files whose names we generate."""
    with conn:
        conn.execute(
            "DELETE FROM ingest_jobs WHERE status IN ('failed', 'awaiting_details')"
            " AND updated_at < datetime('now', ?)",
            (f"-{KEEP_FAILED_DAYS} days",),
        )
        trim_logs(conn)
    shas = {row[0] for row in conn.execute("SELECT sha256 FROM documents")}
    shas |= {
        row[0] for row in conn.execute("SELECT sha256 FROM ingest_jobs WHERE sha256 IS NOT NULL")
    }
    waiting = {
        str(row[0])
        for row in conn.execute("SELECT id FROM ingest_jobs WHERE status = 'awaiting_file'")
    }
    removed = []
    stale = time.time() - settings.stale_upload_hours * 3600
    for part in _listing(settings.uploads_dir, "*.part"):
        if part.stem not in waiting or part.stat().st_mtime < stale:
            removed.append(part)
    for pdf in _listing(settings.books_dir, "*.pdf"):
        if _SHA_PDF.match(pdf.name) and pdf.stem not in shas:
            removed.append(pdf)
    prefixes = {sha[:16] for sha in shas}
    for folder in _listing(settings.ocr_cache_dir, "*"):
        if folder.is_dir() and _OCR_DIR.match(folder.name) and folder.name not in prefixes:
            removed.append(folder)
    for path in removed:
        log.info("janitor: removing %s", path)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    return removed


def trim_logs(conn: sqlite3.Connection) -> None:
    """Keep the teacher inbox and the usage log bounded. Caller owns the transaction."""
    conn.execute(
        "DELETE FROM unanswered WHERE COALESCE(last_asked, created_at) < datetime('now', ?)",
        (f"-{settings.unanswered_keep_days} days",),
    )
    conn.execute(  # newest N per class (by last asked) survive
        "DELETE FROM unanswered WHERE id IN (SELECT id FROM (SELECT id, row_number() OVER"
        " (PARTITION BY class_id ORDER BY COALESCE(last_asked, created_at) DESC) AS rank"
        " FROM unanswered) WHERE rank > ?)",
        (settings.unanswered_keep_per_class,),
    )
    conn.execute(
        "DELETE FROM answer_log WHERE day < date('now', 'localtime', ?)",
        (f"-{settings.answer_log_keep_days} days",),
    )


def _listing(directory: Path, pattern: str) -> list[Path]:
    return sorted(directory.glob(pattern)) if directory.is_dir() else []


def disk_report() -> dict[str, int]:
    """Bytes used by each data folder plus free space, for the admin overview."""
    folders = {
        "database": [settings.db_path],
        "books": [settings.books_dir],
        "ocr_cache": [settings.ocr_cache_dir],
        "page_images": [settings.page_cache_dir],
    }
    report = {name: sum(_size(path) for path in paths) for name, paths in folders.items()}
    report["free"] = shutil.disk_usage(settings.db_path.parent).free
    return report


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    return 0
