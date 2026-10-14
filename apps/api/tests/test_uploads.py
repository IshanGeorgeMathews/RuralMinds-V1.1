import asyncio
import io
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from ruralminds import uploads
from ruralminds.config import settings
from ruralminds.db import connect, init_schema, serialize_vector
from ruralminds.uploads import UploadError


def make_pdf(pages: int = 3) -> bytes:
    document = pdfium.PdfDocument.new()
    for _ in range(pages):
        document.new_page(200, 300)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


async def _stream(data: bytes, piece: int = 100):
    for start in range(0, len(data), piece):
        yield data[start : start + piece]


def receive(conn, job_id: int, data: bytes):
    return asyncio.run(uploads.receive_file(conn, job_id, _stream(data)))


@pytest.fixture
def conn(tmp_path: Path, monkeypatch):
    for name in ("books_dir", "uploads_dir", "ocr_cache_dir", "page_cache_dir"):
        monkeypatch.setattr(settings, name, tmp_path / name)
    monkeypatch.setattr(settings, "min_free_disk_gb", 0.0)
    connection = connect(":memory:")
    init_schema(connection)
    connection.execute("INSERT INTO classes (id, grade, section, medium) VALUES (1, 8, 'A', 'en')")
    yield connection
    connection.close()


def test_valid_pdf_is_stored_under_its_hash(conn) -> None:
    job = uploads.create_job(conn, "book.pdf", user_id=None)
    info = receive(conn, job, make_pdf(3))
    assert info.page_count == 3
    row = conn.execute("SELECT status, sha256 FROM ingest_jobs WHERE id = ?", (job,)).fetchone()
    assert row["status"] == "awaiting_details"
    assert (settings.books_dir / f"{row['sha256']}.pdf").exists()
    assert not list(settings.uploads_dir.glob("*.part"))


def test_oversized_upload_stops_and_leaves_nothing(conn, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    job = uploads.create_job(conn, "big.pdf", user_id=None)
    with pytest.raises(UploadError, match="upload.too_big"):
        receive(conn, job, b"%PDF-" + b"x" * (1024 * 1024 + 10))
    assert not list(settings.uploads_dir.glob("*.part"))
    assert not list(settings.books_dir.glob("*.pdf"))


@pytest.mark.parametrize(
    ("data", "key"),
    [
        (b"PK\x03\x04 a zip file", "upload.not_pdf"),
        (make_pdf(3)[:400], "upload.corrupt"),  # cut off mid-transfer (power cut)
    ],
)
def test_bad_files_are_rejected(conn, data: bytes, key: str) -> None:
    job = uploads.create_job(conn, "x.pdf", user_id=None)
    with pytest.raises(UploadError, match=key):
        receive(conn, job, data)
    assert not list(settings.books_dir.glob("*.pdf"))


def test_too_many_pages(conn, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_pages", 2)
    job = uploads.create_job(conn, "x.pdf", user_id=None)
    with pytest.raises(UploadError, match="upload.too_many_pages"):
        receive(conn, job, make_pdf(3))


def test_same_book_twice_is_refused(conn) -> None:
    data = make_pdf(2)
    receive(conn, uploads.create_job(conn, "a.pdf", user_id=None), data)
    with pytest.raises(UploadError, match="upload.duplicate"):
        receive(conn, uploads.create_job(conn, "b.pdf", user_id=None), data)


def _details(**changes) -> dict:
    details = {
        "title": "Science",
        "grade": 8,
        "subject": "science",
        "medium": "en",
        "board": "SCERT-KL",
        "page_offset": 0,
        "last_page": None,
        "chapters": [{"no": 1, "title": "One", "start": 1}, {"no": 2, "title": "Two", "start": 2}],
        "class_ids": [1],
    }
    return details | changes


def test_details_are_validated_against_the_pdf(conn) -> None:
    job = uploads.create_job(conn, "a.pdf", user_id=None)
    receive(conn, job, make_pdf(3))
    bad = _details(
        chapters=[{"no": 1, "title": "One", "start": 3}, {"no": 1, "title": "Two", "start": 9}],
        class_ids=[42],
    )
    errors = uploads.set_details(conn, job, bad)
    assert {"upload.chapter_page_range", "upload.chapter_numbers", "upload.unknown_class"} <= set(
        errors
    )
    assert uploads.set_details(conn, job, _details()) == []
    status = conn.execute("SELECT status FROM ingest_jobs WHERE id = ?", (job,)).fetchone()[0]
    assert status == "queued"


def test_interrupted_ingest_is_queued_again(conn) -> None:
    job = uploads.create_job(conn, "a.pdf", user_id=None)
    conn.execute("UPDATE ingest_jobs SET status = 'ingesting', attempts = 1 WHERE id = ?", (job,))
    uploads.recover_interrupted(conn)
    row = conn.execute("SELECT status FROM ingest_jobs WHERE id = ?", (job,)).fetchone()
    assert row["status"] == "queued"
    conn.execute("UPDATE ingest_jobs SET status = 'ingesting', attempts = 3 WHERE id = ?", (job,))
    uploads.recover_interrupted(conn)
    row = conn.execute("SELECT status FROM ingest_jobs WHERE id = ?", (job,)).fetchone()
    assert row["status"] == "failed"


def test_janitor_removes_orphans_and_keeps_live_files(conn) -> None:
    job = uploads.create_job(conn, "a.pdf", user_id=None)
    receive(conn, job, make_pdf(2))
    sha = conn.execute("SELECT sha256 FROM ingest_jobs WHERE id = ?", (job,)).fetchone()[0]
    orphan = settings.books_dir / f"{'0' * 64}.pdf"
    orphan.write_bytes(b"%PDF-")
    stray_part = settings.uploads_dir / "999.part"
    stray_part.write_bytes(b"half")
    not_ours = settings.books_dir / "notes.pdf"  # a name we never generate: left alone
    not_ours.write_bytes(b"%PDF-")
    (settings.ocr_cache_dir / ("f" * 16)).mkdir(parents=True)
    (settings.ocr_cache_dir / sha[:16]).mkdir()
    uploads.janitor(conn)
    assert (settings.books_dir / f"{sha}.pdf").exists()
    assert (settings.ocr_cache_dir / sha[:16]).exists()
    assert not orphan.exists() and not stray_part.exists()
    assert not (settings.ocr_cache_dir / ("f" * 16)).exists()
    assert not_ours.exists()


def test_delete_book_leaves_no_search_rows(conn) -> None:
    conn.execute(
        "INSERT INTO documents (id, book_id, title, board, medium, grade, subject, file_path,"
        " sha256, page_count) VALUES (5, 'up-x', 't', 'SCERT-KL', 'en', 8, 'science', 'p', ?, 1)",
        ("a" * 64,),
    )
    cursor = conn.execute(
        "INSERT INTO chunks (document_id, ordinal, chapter_no, chapter_title, page_start,"
        " page_end, text) VALUES (5, 0, 1, 'c', 1, 1, 'photosynthesis in leaves')"
    )
    conn.execute(
        "INSERT INTO chunk_vectors VALUES (?,?,?,?,?,?)",
        (cursor.lastrowid, serialize_vector([1.0] + [0.0] * 1023), "en", "science", 1, 5),
    )
    conn.execute("INSERT INTO class_books VALUES (1, 5)")
    conn.commit()
    assert uploads.delete_book(conn, 5)
    for table in ("documents", "chunks", "chunk_vectors", "class_books"):
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    hits = conn.execute("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'photosynthesis'")
    assert hits.fetchall() == []
