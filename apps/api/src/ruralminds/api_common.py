"""Pieces shared by the student, teacher and admin routers."""

import json
import sqlite3
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import tutor
from .answer import AskRequest, Turn, answer_stream


class TurnIn(BaseModel):
    question: str = Field(max_length=2000)
    answer: str = Field(max_length=4000)


class AskIn(BaseModel):
    """No student identifier of any kind: history lives on the phone and is sent each time."""

    question: str = Field(min_length=1, max_length=2000)
    # The student's "Answer in" setting. The UI language is separate and never sent.
    answer_language: Literal["auto", "en", "ml"] = "auto"
    mode: Literal["explain", "simpler", "example", "story", "quiz", "summary"] | None = None
    document_id: int
    chapter_no: int | None = None
    history: list[TurnIn] = Field(default_factory=list, max_length=6)


def db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


def book_row(conn: sqlite3.Connection, doc_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if row is None:
        raise HTTPException(404, detail="book.not_found")
    return row


def _sse(item: dict[str, object]) -> str:
    return f"event: {item['event']}\ndata: {json.dumps(item['data'], ensure_ascii=False)}\n\n"


def stream_answer(
    request: Request, body: AskIn, book: sqlite3.Row, class_id: int
) -> StreamingResponse:
    ask = AskRequest(
        question=body.question,
        language=tutor.answer_language(body.answer_language, body.question),
        medium=book["medium"],
        subject=book["subject"],
        chapter_no=body.chapter_no,
        history=[Turn(turn.question, turn.answer) for turn in body.history],
        document_id=book["id"],
        class_id=class_id,
        mode=body.mode,
    )
    state = request.app.state
    events: AsyncIterator[dict[str, object]] = answer_stream(state.db, state.http, state.queue, ask)
    return StreamingResponse(
        (_sse(item) async for item in events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def chapters(conn: sqlite3.Connection, doc_id: int) -> list[dict[str, object]]:
    """Chapters with their printed page range and which languages have study notes."""
    rows = conn.execute(
        "SELECT bc.chapter_no AS no, bc.title, bc.printed_start AS page,"
        " (SELECT max(c.page_end) FROM chunks c WHERE c.document_id = bc.document_id"
        "  AND c.chapter_no = bc.chapter_no) AS last_page,"
        " (SELECT group_concat(n.language || ':' || n.status) FROM chapter_notes n"
        "  WHERE n.document_id = bc.document_id AND n.chapter_no = bc.chapter_no) AS notes"
        " FROM book_chapters bc WHERE bc.document_id = ? ORDER BY bc.chapter_no",
        (doc_id,),
    ).fetchall()
    result = []
    for row in rows:
        notes = dict(item.split(":", 1) for item in (row["notes"] or "").split(",") if item)
        result.append({**dict(row), "notes": notes})
    return result


def class_label(row: sqlite3.Row | dict) -> str:
    return f"{row['grade']}{row['section']}"
