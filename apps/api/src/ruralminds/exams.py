"""Exam revision: a question bank per book and chapter, and exam portions that show approved
questions to classes as revision chips until the exam (W5 part 2, 20 Oct).

A real week: one teacher has 8A and 8B on the English Class 8 book (exam 30 Oct, chapters
1-4), 8C on the Malayalam book and 9A on the Class 9 book. The bank is per book, so 8A and
8B share one set of approved questions and 8C/9A get their own; a portion only picks the
classes, chapters and dates. A chip tap serves the approved answer by id: no model call, no
dependence on the cache key (history, answer-language setting or mode detection would miss).

Answers come from the normal pipeline (cited), reworded by the teacher (citations kept), or
written by the teacher with no page citation, labelled as the teacher's own (DECISIONS 20 Oct).
"""

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import date

from . import cache
from .answer import AnswerQueue, AskRequest, answer_stream

log = logging.getLogger("ruralminds.exams")

ANSWER_KEYS = ("text", "example", "check", "answers", "citations")


class ExamError(ValueError):
    """A request the teacher can fix; the message is an i18n key."""


@dataclass
class PortionIn:
    title: str
    document_id: int
    chapters: list[int]
    class_ids: list[int]
    visible_from: str  # YYYY-MM-DD
    exam_on: str
    drafts_per_chapter: int = 6


def today() -> str:
    """The server's date: chips appear and expire by it (shown to the teacher, since an offline
    laptop's clock can drift)."""
    return date.today().isoformat()


# ---------- portions ----------
def check_portion(conn: sqlite3.Connection, data: PortionIn, my_classes: list[int]) -> None:
    book = conn.execute("SELECT id FROM documents WHERE id = ?", (data.document_id,)).fetchone()
    if book is None:
        raise ExamError("book.not_found")
    known = {
        row[0]
        for row in conn.execute(
            "SELECT chapter_no FROM book_chapters WHERE document_id = ?", (data.document_id,)
        )
    }
    if not data.chapters or not set(data.chapters) <= known:
        raise ExamError("exam.bad_chapters")
    if not data.class_ids or not set(data.class_ids) <= set(my_classes):
        raise ExamError("exam.bad_classes")
    with_book = {
        row[0]
        for row in conn.execute(
            "SELECT class_id FROM class_books WHERE document_id = ?", (data.document_id,)
        )
    }
    if not set(data.class_ids) <= with_book:
        raise ExamError("exam.class_without_book")  # e.g. a Malayalam-medium class
    try:
        start, end = date.fromisoformat(data.visible_from), date.fromisoformat(data.exam_on)
    except ValueError as error:
        raise ExamError("exam.bad_dates") from error
    if start > end:
        raise ExamError("exam.bad_dates")


def save_portion(
    conn: sqlite3.Connection, data: PortionIn, user_id: int, portion_id: int | None = None
) -> int:
    fields = (
        data.title.strip(),
        data.document_id,
        json.dumps(sorted(set(data.chapters))),
        data.visible_from,
        data.exam_on,
        data.drafts_per_chapter,
    )
    with conn:
        if portion_id is None:
            portion_id = conn.execute(
                "INSERT INTO exam_portions (title, document_id, chapters, visible_from, exam_on,"
                " drafts_per_chapter, created_by) VALUES (?,?,?,?,?,?,?)",
                (*fields, user_id),
            ).lastrowid
        else:
            conn.execute(
                "UPDATE exam_portions SET title = ?, document_id = ?, chapters = ?,"
                " visible_from = ?, exam_on = ?, drafts_per_chapter = ? WHERE id = ?",
                (*fields, portion_id),
            )
            conn.execute("DELETE FROM exam_portion_classes WHERE portion_id = ?", (portion_id,))
        conn.executemany(
            "INSERT INTO exam_portion_classes (portion_id, class_id) VALUES (?, ?)",
            [(portion_id, class_id) for class_id in dict.fromkeys(data.class_ids)],
        )
    return int(portion_id)


def portions_for(conn: sqlite3.Connection, my_classes: list[int]) -> list[dict]:
    """Every portion that includes one of these classes, with review progress per chapter."""
    marks = ",".join("?" * len(my_classes)) or "NULL"
    rows = conn.execute(
        "SELECT DISTINCT p.*, d.title AS book_title, d.medium FROM exam_portions p"
        " JOIN documents d ON d.id = p.document_id"
        f" JOIN exam_portion_classes pc ON pc.portion_id = p.id WHERE pc.class_id IN ({marks})"
        " ORDER BY p.exam_on, p.id",
        my_classes,
    ).fetchall()
    return [_portion_view(conn, row) for row in rows]


def _portion_view(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    chapters = json.loads(row["chapters"])
    classes = conn.execute(
        "SELECT c.id, c.grade, c.section FROM exam_portion_classes pc"
        " JOIN classes c ON c.id = pc.class_id WHERE pc.portion_id = ? ORDER BY c.grade, c.section",
        (row["id"],),
    ).fetchall()
    return {
        "id": row["id"],
        "title": row["title"],
        "document_id": row["document_id"],
        "book_title": row["book_title"],
        "medium": row["medium"],
        "chapters": chapters,
        "visible_from": row["visible_from"],
        "exam_on": row["exam_on"],
        "drafts_per_chapter": row["drafts_per_chapter"],
        "classes": [dict(c) for c in classes],
        "progress": bank_counts(conn, row["document_id"], chapters),
        "suggested": suggested_progress(conn, row, chapters),
    }


def suggested_progress(conn: sqlite3.Connection, row: sqlite3.Row, chapters: list[int]) -> dict:
    """How far the idle-time worker is with this exam's suggested questions, for the
    teacher's progress line: wanted, ready to check (or done), being prepared."""
    marks = ",".join("?" * len(chapters)) or "NULL"
    ready, preparing = conn.execute(
        "SELECT sum(status IN ('draft', 'approved')), sum(status = 'pending')"
        " FROM revision_questions WHERE source = 'drafted' AND document_id = ?"
        f" AND chapter_no IN ({marks})",
        (row["document_id"], *chapters),
    ).fetchone()
    return {
        "wanted": row["drafts_per_chapter"] * len(chapters),
        "ready": ready or 0,
        "preparing": preparing or 0,
    }


def bank_counts(conn: sqlite3.Connection, document_id: int, chapters: list[int]) -> dict:
    marks = ",".join("?" * len(chapters)) or "NULL"
    rows = conn.execute(
        "SELECT status, count(*) AS n FROM revision_questions"
        f" WHERE document_id = ? AND chapter_no IN ({marks}) GROUP BY status",
        (document_id, *chapters),
    ).fetchall()
    return {row["status"]: row["n"] for row in rows}


def delete_portion(conn: sqlite3.Connection, portion_id: int) -> None:
    """The questions stay in the bank: they are the book's, not this exam's."""
    with conn:
        conn.execute("DELETE FROM exam_portions WHERE id = ?", (portion_id,))


# ---------- the question bank ----------
def add_question(
    conn: sqlite3.Connection,
    document_id: int,
    chapter_no: int,
    question: str,
    user_id: int | None,
    source: str = "teacher",
    written_answer: str | None = None,
) -> int:
    """A teacher's question (or a drafted one). With the teacher's own answer it is approved at
    once; otherwise it waits for the pipeline (status pending)."""
    book = conn.execute(
        "SELECT sha256, medium FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    if book is None:
        raise ExamError("book.not_found")
    normalised = cache.normalise_question(question)
    if not normalised:
        raise ExamError("exam.empty_question")
    written = (written_answer or "").strip()
    answer = json.dumps({"text": written, "citations": []}, ensure_ascii=False) if written else None
    with conn:
        cursor = conn.execute(
            "INSERT INTO revision_questions (document_id, doc_sha256, chapter_no, language,"
            " question, normalised_q, source, status, answer_json, answer_kind, created_by,"
            " approved_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT (document_id, chapter_no, normalised_q) DO NOTHING",
            (
                document_id,
                book["sha256"],
                chapter_no,
                book["medium"],
                question.strip(),
                normalised,
                source,
                "approved" if written else "pending",
                answer,
                "written" if written else None,
                user_id,
                user_id if written else None,
            ),
        )
    if cursor.rowcount == 0:
        raise ExamError("exam.duplicate_question")
    return int(cursor.lastrowid)


def bank(conn: sqlite3.Connection, document_id: int, chapter_no: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, chapter_no, question, source, status, answer_json, answer_kind, updated_at"
        " FROM revision_questions WHERE document_id = ? AND chapter_no = ?"
        " ORDER BY CASE status WHEN 'draft' THEN 0 WHEN 'pending' THEN 1 WHEN 'failed' THEN 2"
        " WHEN 'not_in_book' THEN 3 WHEN 'approved' THEN 4 ELSE 5 END, id",
        (document_id, chapter_no),
    ).fetchall()
    views = []
    for row in rows:
        view = dict(row)
        answer_json = view.pop("answer_json")
        views.append(view | {"answer": json.loads(answer_json) if answer_json else None})
    return views


def question_row(conn: sqlite3.Connection, question_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM revision_questions WHERE id = ?", (question_id,)).fetchone()
    if row is None:
        raise ExamError("exam.not_found")
    return row


def approve(
    conn: sqlite3.Connection, question_id: int, user_id: int, edited_text: str | None = None
) -> None:
    """Approve as is, or with the teacher's rewording (citations stay attached). A cited answer
    also goes into the exact-match cache, so a student who types the same question gets it."""
    row = question_row(conn, question_id)
    has_answer = row["status"] in ("draft", "approved", "rejected") and row["answer_json"]
    if not has_answer:
        # The book did not answer it (or the model failed): only the teacher's own text can.
        if not (edited_text or "").strip():
            raise ExamError("exam.no_answer_yet")
        answer, kind = {"text": edited_text.strip(), "citations": []}, "written"
    else:
        answer = json.loads(row["answer_json"])
        kind = row["answer_kind"] or "generated"
        if edited_text is not None and edited_text.strip() != answer.get("text", "").strip():
            answer["text"] = edited_text.strip()
            kind = "written" if kind == "written" else "edited"
    with conn:
        conn.execute(
            "UPDATE revision_questions SET status = 'approved', answer_json = ?, answer_kind = ?,"
            " approved_by = ?, updated_at = datetime('now') WHERE id = ?",
            (json.dumps(answer, ensure_ascii=False), kind, user_id, question_id),
        )
    if answer.get("citations") and kind != "written":
        cache.approve(
            conn, row["question"], row["language"], row["document_id"], row["chapter_no"], answer
        )


def reject(conn: sqlite3.Connection, question_id: int) -> None:
    """Withdraw: the chip disappears, and its cached copy stops answering typed questions."""
    row = question_row(conn, question_id)
    with conn:
        conn.execute(
            "UPDATE revision_questions SET status = 'rejected', updated_at = datetime('now')"
            " WHERE id = ?",
            (question_id,),
        )
    cache.withdraw(conn, row["question"], row["language"], row["document_id"], row["chapter_no"])


def retry(conn: sqlite3.Connection, question_id: int) -> None:
    question_row(conn, question_id)
    with conn:
        conn.execute(
            "UPDATE revision_questions SET status = 'pending', answer_json = NULL,"
            " answer_kind = NULL, updated_at = datetime('now')"
            " WHERE id = ? AND status IN ('pending', 'failed', 'not_in_book', 'rejected', 'draft')",
            (question_id,),
        )


# ---------- answering a question through the normal pipeline ----------
async def answer_question(
    conn: sqlite3.Connection, client, queue: AnswerQueue, question_id: int
) -> str:
    """Run the pending question through the same pipeline and queue as a student's (fair:
    it waits its turn), and store the result as a draft for the teacher. Returns the status."""
    row = question_row(conn, question_id)
    book = conn.execute(
        "SELECT medium, subject FROM documents WHERE id = ?", (row["document_id"],)
    ).fetchone()
    request = AskRequest(
        question=row["question"],
        language=row["language"],
        medium=book["medium"],
        subject=book["subject"],
        chapter_no=row["chapter_no"],
        document_id=row["document_id"],
        use_cache=False,
        mode="explain",  # a revision answer, whatever words the question uses
    )
    final: dict = {}
    async for item in answer_stream(conn, client, queue, request):
        if item["event"] != "queued" and item["event"] != "token":
            final = item
    status, answer = _result(final)
    with conn:
        conn.execute(
            "UPDATE revision_questions SET status = ?, answer_json = ?, answer_kind = ?,"
            " updated_at = datetime('now') WHERE id = ? AND status = 'pending'",
            (status, answer, "generated" if status == "draft" else None, question_id),
        )
    return status


def _result(final: dict) -> tuple[str, str | None]:
    data = final.get("data", {})
    if final.get("event") == "done":
        answer = {key: data.get(key, "" if key != "citations" else []) for key in ANSWER_KEYS}
        return "draft", json.dumps(answer, ensure_ascii=False)
    if final.get("event") == "refused":
        return "not_in_book", json.dumps({"reason": data.get("reason")})
    return "failed", None  # busy, error, blocked: the teacher can retry


# ---------- students ----------
def student_revision(conn: sqlite3.Connection, class_id: int | None, on: str) -> list[dict]:
    """Active exams for this class, each with its approved questions (no answers yet: the
    phone asks for one only after the student has tried; attempt-first)."""
    if not class_id:
        return []
    rows = conn.execute(
        "SELECT p.id, p.title, p.document_id, p.chapters, p.exam_on FROM exam_portions p"
        " JOIN exam_portion_classes pc ON pc.portion_id = p.id"
        " WHERE pc.class_id = ? AND p.visible_from <= ? AND p.exam_on >= ? ORDER BY p.exam_on",
        (class_id, on, on),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "document_id": row["document_id"],
            "exam_on": row["exam_on"],
            "today": on,
            "questions": _approved(conn, row["document_id"], json.loads(row["chapters"])),
        }
        for row in rows
    ]


def _approved(conn: sqlite3.Connection, document_id: int, chapters: list[int]) -> list[dict]:
    marks = ",".join("?" * len(chapters)) or "NULL"
    rows = conn.execute(
        "SELECT q.id, q.chapter_no, q.question FROM revision_questions q"
        " JOIN documents d ON d.id = q.document_id AND d.sha256 = q.doc_sha256"
        f" WHERE q.document_id = ? AND q.status = 'approved' AND q.chapter_no IN ({marks})"
        " ORDER BY q.chapter_no, q.id",
        (document_id, *chapters),
    ).fetchall()
    return [dict(row) for row in rows]


def student_answer(
    conn: sqlite3.Connection, class_id: int | None, question_id: int, on: str
) -> dict | None:
    """The approved answer, only for a question in an exam this class is revising now, on the
    book version it was checked against. Logged as a class-level 'cached' answer."""
    if not class_id:
        return None
    row = conn.execute(
        "SELECT q.answer_json, q.answer_kind, q.document_id, q.chapter_no, q.language"
        " FROM revision_questions q"
        " JOIN documents d ON d.id = q.document_id AND d.sha256 = q.doc_sha256"
        " JOIN exam_portions p ON p.document_id = q.document_id"
        " JOIN exam_portion_classes pc ON pc.portion_id = p.id AND pc.class_id = ?"
        " WHERE q.id = ? AND q.status = 'approved' AND p.visible_from <= ? AND p.exam_on >= ?"
        " AND EXISTS (SELECT 1 FROM json_each(p.chapters) WHERE value = q.chapter_no)",
        (class_id, question_id, on, on),
    ).fetchone()
    if row is None:
        return None
    with conn:
        conn.execute(
            "INSERT INTO answer_log (class_id, document_id, chapter_no, language, outcome)"
            " VALUES (?,?,?,?,'cached')",
            (class_id, row["document_id"], row["chapter_no"], row["language"]),
        )
    label = "teacher_written" if row["answer_kind"] == "written" else "teacher_approved"
    return {**json.loads(row["answer_json"]), "label": label}
