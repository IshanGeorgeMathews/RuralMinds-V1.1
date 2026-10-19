"""Teacher routes: upload and manage books, try the AI, approve answers, see class activity."""

import asyncio
import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import cache, exams, stats, uploads
from .api_common import AskIn, book_row, chapters, class_label, db, stream_answer
from .auth import User, require_role
from .config import settings

router = APIRouter(prefix="/api/teacher", tags=["teacher"])
Conn = Annotated[sqlite3.Connection, Depends(db)]
# The admin can do everything a teacher can (from the server machine).
Teacher = Annotated[User, Depends(require_role("teacher", "admin"))]


def my_class_ids(conn: sqlite3.Connection, user: User) -> list[int]:
    if user.role == "admin":
        return [row[0] for row in conn.execute("SELECT id FROM classes")]
    rows = conn.execute("SELECT class_id FROM teacher_classes WHERE user_id = ?", (user.id,))
    return [row[0] for row in rows]


@router.get("/overview")
async def overview(user: Teacher, conn: Conn) -> dict:
    """Everything the teacher screen needs in one request (slow Wi-Fi: fewer round trips)."""
    classes = [dict(row) for row in conn.execute("SELECT * FROM classes ORDER BY grade, section")]
    mine = set(my_class_ids(conn, user))
    for klass in classes:
        klass["label"] = class_label(klass)
        klass["mine"] = klass["id"] in mine
    books = []
    for row in conn.execute("SELECT * FROM documents ORDER BY grade, subject, title"):
        allocated = conn.execute(
            "SELECT class_id FROM class_books WHERE document_id = ?", (row["id"],)
        ).fetchall()
        books.append(
            {
                "id": row["id"],
                "title": row["title"],
                "subject": row["subject"],
                "medium": row["medium"],
                "grade": row["grade"],
                "status": row["status"],
                "page_count": row["page_count"],
                "class_ids": [r[0] for r in allocated],
                "chapters": chapters(conn, row["id"]),
            }
        )
    limits = {"max_upload_mb": settings.max_upload_mb, "max_pages": settings.max_pages}
    return {
        "classes": classes,
        "books": books,
        "jobs": _jobs(conn),
        "limits": limits,
        "subjects": uploads.SUBJECTS,
        "boards": uploads.BOARDS,
    }


def _jobs(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, status, filename, bytes, page_count, attempts, error, document_id,"
        " created_at, updated_at FROM ingest_jobs WHERE status != 'ready' ORDER BY id DESC"
    ).fetchall()
    return [dict(row) for row in rows]


# ---------- uploads ----------
class UploadIn(BaseModel):
    filename: str = Field(min_length=1, max_length=200)


class ChapterIn(BaseModel):
    no: int = Field(ge=1, le=99)
    title: str = Field(min_length=1, max_length=120)
    start: int = Field(ge=1)


class DetailsIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    grade: int = Field(ge=1, le=12)
    subject: str
    medium: Literal["en", "ml"]
    board: str = "SCERT-KL"
    page_offset: int = Field(default=0, ge=-500, le=500)
    last_page: int | None = Field(default=None, ge=1)
    licence: str = Field(default="", max_length=200)
    chapters: list[ChapterIn] = Field(min_length=1, max_length=uploads.MAX_CHAPTERS)
    class_ids: list[int] = Field(default_factory=list, max_length=100)


@router.post("/uploads")
async def start_upload(body: UploadIn, user: Teacher, conn: Conn) -> dict:
    return {"job_id": uploads.create_job(conn, body.filename, user.id)}


@router.put("/uploads/{job_id}/file")
async def upload_file(job_id: int, request: Request, user: Teacher, conn: Conn) -> dict:
    if request.headers.get("content-type") != "application/pdf":
        raise HTTPException(415, detail="upload.not_pdf")
    try:
        info = await uploads.receive_file(conn, job_id, request.stream())
    except uploads.UploadError as error:
        raise HTTPException(422, detail=str(error)) from error
    return {"page_count": info.page_count, "bookmarks": info.bookmarks}


@router.post("/uploads/{job_id}/details")
async def upload_details(
    job_id: int, body: DetailsIn, request: Request, user: Teacher, conn: Conn
) -> dict:
    errors = uploads.set_details(conn, job_id, body.model_dump())
    if errors:
        raise HTTPException(422, detail=errors)
    request.app.state.jobs.wake()
    return {"status": "queued"}


@router.post("/uploads/{job_id}/retry")
async def retry_upload(job_id: int, request: Request, user: Teacher, conn: Conn) -> dict:
    with conn:
        cursor = conn.execute(
            "UPDATE ingest_jobs SET status = 'queued', attempts = 0, error = NULL,"
            " updated_at = datetime('now') WHERE id = ? AND status = 'failed' AND metadata IS NOT NULL",
            (job_id,),
        )
    if cursor.rowcount != 1:
        raise HTTPException(409, detail="upload.wrong_state")
    request.app.state.jobs.wake()
    return {"status": "queued"}


@router.delete("/uploads/{job_id}", status_code=204)
async def cancel_upload(job_id: int, user: Teacher, conn: Conn) -> None:
    if not uploads.delete_job(conn, job_id):
        raise HTTPException(409, detail="upload.wrong_state")


# ---------- books ----------
class PublishIn(BaseModel):
    published: bool


class ClassesIn(BaseModel):
    class_ids: list[int] = Field(max_length=100)


@router.post("/books/{doc_id}/publish")
async def publish(doc_id: int, body: PublishIn, user: Teacher, conn: Conn) -> dict:
    book_row(conn, doc_id)
    status = "published" if body.published else "ready"
    with conn:
        conn.execute("UPDATE documents SET status = ? WHERE id = ?", (status, doc_id))
    return {"status": status}


@router.post("/books/{doc_id}/classes")
async def set_classes(doc_id: int, body: ClassesIn, user: Teacher, conn: Conn) -> dict:
    book_row(conn, doc_id)
    known = {row[0] for row in conn.execute("SELECT id FROM classes")}
    if not set(body.class_ids) <= known:
        raise HTTPException(422, detail="upload.unknown_class")
    with conn:
        uploads.allocate(conn, doc_id, body.class_ids)
    return {"class_ids": body.class_ids}


@router.delete("/books/{doc_id}", status_code=204)
async def delete_book(doc_id: int, user: Teacher, conn: Conn) -> None:
    if not uploads.delete_book(conn, doc_id):
        raise HTTPException(404, detail="book.not_found")


# ---------- try the AI, approve, unanswered ----------
@router.post("/ask")
async def try_ask(body: AskIn, request: Request, user: Teacher, conn: Conn) -> StreamingResponse:
    """Same pipeline as students, on any book (published or not); logged as class 0."""
    return stream_answer(request, body, book_row(conn, body.document_id), class_id=0)


class ApproveIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    language: Literal["en", "ml"]
    document_id: int
    chapter_no: int | None = None
    text: str = Field(min_length=1, max_length=4000)
    example: str = Field(default="", max_length=2000)
    check: str = Field(default="", max_length=1000)
    answers: str = Field(default="", max_length=2000)
    citations: list[dict] = Field(max_length=10)


@router.post("/approve")
async def approve(body: ApproveIn, user: Teacher, conn: Conn) -> dict:
    book_row(conn, body.document_id)
    answer = body.model_dump(include={"text", "example", "check", "answers", "citations"})
    cache.approve(conn, body.question, body.language, body.document_id, body.chapter_no, answer)
    return {"status": "approved"}


@router.get("/approved")
async def approved(user: Teacher, conn: Conn) -> list[dict]:
    rows = conn.execute(
        "SELECT id, question, language, chapter_no, book_id, status, updated_at FROM answer_cache"
        " WHERE status IN ('approved', 'needs_review') ORDER BY updated_at DESC LIMIT 200"
    ).fetchall()
    return [dict(row) for row in rows]


@router.post("/approved/{entry_id}/reject")
async def reject(entry_id: int, user: Teacher, conn: Conn) -> dict:
    if not cache.set_status(conn, entry_id, "rejected"):
        raise HTTPException(404, detail="cache.not_found")
    return {"status": "rejected"}


@router.get("/unanswered")
async def unanswered(user: Teacher, conn: Conn) -> list[dict]:
    ids = my_class_ids(conn, user)
    marks = ",".join("?" * len(ids)) or "NULL"
    rows = conn.execute(
        "SELECT u.id, u.question, u.language, u.chapter_no, u.reason, u.created_at,"
        " u.last_asked, u.times_asked, u.document_id, c.grade, c.section FROM unanswered u"
        f" JOIN classes c ON c.id = u.class_id WHERE u.class_id IN ({marks})"
        " ORDER BY u.times_asked DESC, u.last_asked DESC LIMIT 200",
        ids,
    ).fetchall()
    return [dict(row) | {"class": class_label(row)} for row in rows]


@router.delete("/unanswered/{entry_id}", status_code=204)
async def dismiss(entry_id: int, user: Teacher, conn: Conn) -> None:
    with conn:
        conn.execute("DELETE FROM unanswered WHERE id = ?", (entry_id,))


@router.get("/activity")
async def activity(user: Teacher, conn: Conn, days: int = 14) -> dict:
    ids = my_class_ids(conn, user)
    return {
        "days": days,
        "min_group": stats.MIN_GROUP,
        "rows": stats.class_activity(conn, ids, max(1, min(days, 90))),
    }


# ---------- chapter study notes ----------
class NotesStatusIn(BaseModel):
    approved: bool


@router.post("/notes/{doc_id}/{chapter_no}")
async def set_notes_status(
    doc_id: int, chapter_no: int, body: NotesStatusIn, user: Teacher, conn: Conn
) -> dict:
    status = "approved" if body.approved else "draft"
    with conn:
        cursor = conn.execute(
            "UPDATE chapter_notes SET status = ? WHERE document_id = ? AND chapter_no = ?",
            (status, doc_id, chapter_no),
        )
    if cursor.rowcount == 0:
        raise HTTPException(404, detail="notes.not_ready")
    return {"status": status}


class RegenerateIn(BaseModel):
    chapter_no: int | None = None


@router.post("/notes/{doc_id}/regenerate")
async def regenerate_notes(doc_id: int, body: RegenerateIn, user: Teacher, conn: Conn) -> dict:
    """Runs in its own low-priority process (like uploads); approved notes are kept."""
    book = book_row(conn, doc_id)
    uploads.start_notes_process(book["book_id"], doc_id, force=True, chapter=body.chapter_no)
    return {"status": "started"}


# ---------- exam revision (W5 part 2) ----------
class PortionBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    document_id: int
    chapters: list[int] = Field(min_length=1, max_length=30)
    class_ids: list[int] = Field(min_length=1, max_length=40)
    visible_from: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    exam_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    drafts_per_chapter: int = Field(default=6, ge=0, le=20)


class QuestionBody(BaseModel):
    document_id: int
    chapter_no: int
    question: str = Field(min_length=3, max_length=500)
    # The teacher's own answer: approved at once, labelled as hers, with no page citation.
    answer: str = Field(default="", max_length=4000)


class ApproveQuestionBody(BaseModel):
    text: str | None = Field(default=None, max_length=4000)  # the teacher's rewording


def _exam_error(error: exams.ExamError) -> HTTPException:
    return HTTPException(400, detail=str(error))


def _my_book(conn: sqlite3.Connection, user: User, document_id: int) -> None:
    """A teacher works on the banks of books her classes use (the admin on every book)."""
    book_row(conn, document_id)
    if user.role == "admin":
        return
    ids = my_class_ids(conn, user)
    marks = ",".join("?" * len(ids)) or "NULL"
    found = conn.execute(
        f"SELECT 1 FROM class_books WHERE document_id = ? AND class_id IN ({marks})",
        (document_id, *ids),
    ).fetchone()
    if found is None:
        raise HTTPException(403, detail="auth.forbidden")


def _answer_later(request: Request, question_id: int) -> None:
    """Answer through the normal queue in the background; the teacher's list shows 'pending'
    until it is done. Tasks are kept referenced so they are not garbage-collected mid-way."""
    state = request.app.state
    task = asyncio.create_task(
        exams.answer_question(state.db, state.http, state.queue, question_id)
    )
    state.tasks.add(task)
    task.add_done_callback(state.tasks.discard)


@router.get("/exams")
async def exam_portions(user: Teacher, conn: Conn) -> dict:
    return {"today": exams.today(), "portions": exams.portions_for(conn, my_class_ids(conn, user))}


@router.post("/exams")
async def create_portion(body: PortionBody, user: Teacher, conn: Conn) -> dict:
    data = exams.PortionIn(**body.model_dump())
    try:
        exams.check_portion(conn, data, my_class_ids(conn, user))
    except exams.ExamError as error:
        raise _exam_error(error) from error
    return {"id": exams.save_portion(conn, data, user.id)}


@router.put("/exams/{portion_id}")
async def update_portion(portion_id: int, body: PortionBody, user: Teacher, conn: Conn) -> dict:
    _my_portion(conn, user, portion_id)
    data = exams.PortionIn(**body.model_dump())
    try:
        exams.check_portion(conn, data, my_class_ids(conn, user))
    except exams.ExamError as error:
        raise _exam_error(error) from error
    return {"id": exams.save_portion(conn, data, user.id, portion_id)}


@router.delete("/exams/{portion_id}", status_code=204)
async def delete_portion(portion_id: int, user: Teacher, conn: Conn) -> None:
    _my_portion(conn, user, portion_id)
    exams.delete_portion(conn, portion_id)


def _my_portion(conn: sqlite3.Connection, user: User, portion_id: int) -> None:
    ids = my_class_ids(conn, user)
    marks = ",".join("?" * len(ids)) or "NULL"
    found = conn.execute(
        f"SELECT 1 FROM exam_portion_classes WHERE portion_id = ? AND class_id IN ({marks})",
        (portion_id, *ids),
    ).fetchone()
    if found is None:
        raise HTTPException(404, detail="exam.not_found")


@router.get("/revision/{document_id}/{chapter_no}")
async def revision_bank(document_id: int, chapter_no: int, user: Teacher, conn: Conn) -> list:
    _my_book(conn, user, document_id)
    return exams.bank(conn, document_id, chapter_no)


@router.post("/revision")
async def add_revision_question(
    body: QuestionBody, request: Request, user: Teacher, conn: Conn
) -> dict:
    _my_book(conn, user, body.document_id)
    try:
        question_id = exams.add_question(
            conn,
            body.document_id,
            body.chapter_no,
            body.question,
            user.id,
            written_answer=body.answer or None,
        )
    except exams.ExamError as error:
        raise _exam_error(error) from error
    if not body.answer.strip():
        _answer_later(request, question_id)
    return {"id": question_id}


def _my_question(conn: sqlite3.Connection, user: User, question_id: int) -> None:
    try:
        row = exams.question_row(conn, question_id)
    except exams.ExamError as error:
        raise HTTPException(404, detail=str(error)) from error
    _my_book(conn, user, row["document_id"])


@router.post("/revision/{question_id}/approve")
async def approve_revision(
    question_id: int, body: ApproveQuestionBody, user: Teacher, conn: Conn
) -> dict:
    _my_question(conn, user, question_id)
    try:
        exams.approve(conn, question_id, user.id, body.text)
    except exams.ExamError as error:
        raise _exam_error(error) from error
    return {"status": "approved"}


@router.post("/revision/{question_id}/reject")
async def reject_revision(question_id: int, user: Teacher, conn: Conn) -> dict:
    _my_question(conn, user, question_id)
    exams.reject(conn, question_id)
    return {"status": "rejected"}


@router.post("/revision/{question_id}/retry")
async def retry_revision(question_id: int, request: Request, user: Teacher, conn: Conn) -> dict:
    _my_question(conn, user, question_id)
    exams.retry(conn, question_id)
    _answer_later(request, question_id)
    return {"status": "pending"}
