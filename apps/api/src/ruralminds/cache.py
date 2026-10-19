"""Teacher-approved answers, served instantly on an exact (normalised) question match.

Exact match only, never "similar" questions: a semantic cache returns confident answers to
questions nobody approved (DECISIONS 2026-10-11). The key includes the book's sha256, so a
replaced book never serves answers written for the old text.
"""

import hashlib
import json
import re
import sqlite3

from .textnorm import normalize

_TRAILING_PUNCT = re.compile(r"[\s?.!।]+$")


def normalise_question(question: str) -> str:
    """Case, spacing and the final question mark do not change the question."""
    text = " ".join(normalize(question).casefold().split())
    return _TRAILING_PUNCT.sub("", text)


def cache_key(question: str, language: str, book_sha: str, chapter_no: int | None) -> str:
    parts = [normalise_question(question), language, book_sha, chapter_no]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def _book(conn: sqlite3.Connection, document_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT book_id, sha256, subject FROM documents WHERE id = ?", (document_id,)
    ).fetchone()


def lookup(
    conn: sqlite3.Connection, question: str, language: str, document_id: int, chapter_no: int | None
) -> dict | None:
    book = _book(conn, document_id)
    if book is None:
        return None
    row = conn.execute(
        "SELECT answer_json FROM answer_cache WHERE cache_key = ? AND status = 'approved'",
        (cache_key(question, language, book["sha256"], chapter_no),),
    ).fetchone()
    return json.loads(row["answer_json"]) if row else None


def approve(
    conn: sqlite3.Connection,
    question: str,
    language: str,
    document_id: int,
    chapter_no: int | None,
    answer: dict,
) -> None:
    """Store (or re-approve) a teacher-checked answer: {"text": ..., "citations": [...]}."""
    book = _book(conn, document_id)
    if book is None:
        raise ValueError("unknown book")
    key = cache_key(question, language, book["sha256"], chapter_no)
    with conn:
        conn.execute(
            "INSERT INTO answer_cache (cache_key, question, normalised_q, language, subject,"
            " chapter_no, book_id, doc_sha256, answer_json, status)"
            " VALUES (?,?,?,?,?,?,?,?,?,'approved')"
            " ON CONFLICT (cache_key) DO UPDATE SET answer_json = excluded.answer_json,"
            " status = 'approved', updated_at = datetime('now')",
            (
                key,
                question,
                normalise_question(question),
                language,
                book["subject"],
                chapter_no,
                book["book_id"],
                book["sha256"],
                json.dumps(answer, ensure_ascii=False),
            ),
        )


def withdraw(
    conn: sqlite3.Connection, question: str, language: str, document_id: int, chapter_no: int | None
) -> None:
    """A teacher took back an approved answer: it stops answering typed questions too."""
    book = _book(conn, document_id)
    if book is None:
        return
    with conn:
        conn.execute(
            "UPDATE answer_cache SET status = 'rejected', updated_at = datetime('now')"
            " WHERE cache_key = ? AND status = 'approved'",
            (cache_key(question, language, book["sha256"], chapter_no),),
        )


def set_status(conn: sqlite3.Connection, entry_id: int, status: str) -> bool:
    with conn:
        cursor = conn.execute(
            "UPDATE answer_cache SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, entry_id),
        )
    return cursor.rowcount == 1
