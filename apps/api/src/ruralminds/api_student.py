"""Sign-in (all roles) and the student routes: my books, ask, open a cited page."""

import asyncio
import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import auth, exams
from .api_common import AskIn, book_row, chapters, db, stream_answer
from .auth import User, require_role
from .notes import notes_answer
from .pagepng import page_png

router = APIRouter()
Conn = Annotated[sqlite3.Connection, Depends(db)]


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)


def _me(conn: sqlite3.Connection, user: User) -> dict[str, object]:
    klass = None
    if user.class_id is not None:
        row = conn.execute("SELECT * FROM classes WHERE id = ?", (user.class_id,)).fetchone()
        klass = dict(row) if row else None
    return {"username": user.username, "role": user.role, "class": klass}


@router.post("/api/login", tags=["auth"])
async def login(body: LoginIn, request: Request, response: Response, conn: Conn) -> dict:
    throttle: auth.LoginThrottle = request.app.state.throttle
    if throttle.blocked(body.username):
        raise HTTPException(429, detail="auth.throttled")
    # scrypt takes ~50 ms of CPU: run it off the event loop so answers keep streaming. Only the
    # hash goes to the thread; the shared sqlite connection is never used from two threads.
    row = auth.find_login(conn, body.username)
    user = await asyncio.to_thread(auth.check_login, row, body.password)
    if user is None:
        throttle.failed(body.username)
        raise HTTPException(401, detail="auth.invalid")
    if user.role == "admin" and not auth.is_local(request):
        raise HTTPException(403, detail="auth.admin_local_only")
    throttle.succeeded(body.username)
    token = auth.create_session(conn, user)
    # No max_age: a session cookie, so closing the browser on a shared phone forgets it.
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite="strict", path="/")
    return _me(conn, user)


@router.post("/api/logout", tags=["auth"], status_code=204)
async def logout(request: Request, response: Response, conn: Conn) -> None:
    token = request.cookies.get(auth.COOKIE)
    if token:
        auth.end_session(conn, token)
    response.delete_cookie(auth.COOKIE, path="/")


@router.get("/api/me", tags=["auth"])
async def me(request: Request, conn: Conn) -> dict:
    user = auth.current_user(request)
    if user is None:
        raise HTTPException(401, detail="auth.required")
    return _me(conn, user)


def student_books(conn: sqlite3.Connection, class_id: int | None) -> list[sqlite3.Row]:
    if class_id is None:
        return []
    return conn.execute(
        "SELECT d.* FROM documents d JOIN class_books cb ON cb.document_id = d.id"
        " JOIN classes c ON c.id = cb.class_id"
        " WHERE cb.class_id = ? AND d.status = 'published' AND c.enabled = 1"
        " ORDER BY d.subject, d.title",
        (class_id,),
    ).fetchall()


Student = Annotated[User, Depends(require_role("student"))]


@router.get("/api/catalog", tags=["student"])
async def catalog(user: Student, conn: Conn) -> dict:
    books = [
        {
            "id": row["id"],
            "title": row["title"],
            "subject": row["subject"],
            "medium": row["medium"],
            "grade": row["grade"],
            "chapters": chapters(conn, row["id"]),
        }
        for row in student_books(conn, user.class_id)
    ]
    return {"books": books}


@router.post("/api/ask", tags=["student"])
async def ask(body: AskIn, request: Request, user: Student, conn: Conn) -> StreamingResponse:
    allowed = {row["id"] for row in student_books(conn, user.class_id)}
    if body.document_id not in allowed:
        raise HTTPException(403, detail="book.not_allowed")
    return stream_answer(request, body, book_row(conn, body.document_id), user.class_id or 0)


@router.get("/api/revision", tags=["student"])
async def revision(user: Student, conn: Conn) -> list[dict]:
    """This class's exams being revised now, with their approved questions (no answers)."""
    allowed = {row["id"] for row in student_books(conn, user.class_id)}
    active = exams.student_revision(conn, user.class_id, exams.today())
    return [portion for portion in active if portion["document_id"] in allowed]


@router.post("/api/revision/{question_id}/answer", tags=["student"])
async def revision_answer(question_id: int, user: Student, conn: Conn) -> dict:
    """Asked only after the student tried (attempt-first). No model call: approved text."""
    answer = exams.student_answer(conn, user.class_id, question_id, exams.today())
    if answer is None:
        raise HTTPException(404, detail="exam.not_found")
    return answer


@router.get("/api/notes/{doc_id}/{chapter_no}", tags=["student"])
async def chapter_notes(
    doc_id: int,
    chapter_no: int,
    user: Annotated[User, Depends(require_role("student", "teacher", "admin"))],
    conn: Conn,
    language: str | None = None,
) -> dict:
    """Study notes for one chapter, in the asked language if made, else the book's language."""
    if user.role == "student" and doc_id not in {
        row["id"] for row in student_books(conn, user.class_id)
    }:
        raise HTTPException(403, detail="book.not_allowed")
    book = book_row(conn, doc_id)
    for wanted in dict.fromkeys([language or book["medium"], book["medium"]]):
        notes = notes_answer(conn, doc_id, chapter_no, wanted)
        if notes is not None:
            return notes
    raise HTTPException(404, detail="notes.not_ready")


@router.get("/api/page/{doc_id}/{printed_page}.png", tags=["student"])
async def page_image(
    doc_id: int,
    printed_page: int,
    user: Annotated[User, Depends(require_role("student", "teacher", "admin"))],
    conn: Conn,
) -> FileResponse:
    if user.role == "student" and doc_id not in {
        row["id"] for row in student_books(conn, user.class_id)
    }:
        raise HTTPException(403, detail="book.not_allowed")
    book = book_row(conn, doc_id)
    page = conn.execute(
        "SELECT pdf_page FROM pages WHERE document_id = ? AND printed_page = ?",
        (doc_id, printed_page),
    ).fetchone()
    if page is None:
        raise HTTPException(404, detail="page.not_found")
    pdf_path = Path(book["file_path"])
    path = await asyncio.to_thread(page_png, doc_id, pdf_path, page["pdf_page"])
    return FileResponse(
        path, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"}
    )
