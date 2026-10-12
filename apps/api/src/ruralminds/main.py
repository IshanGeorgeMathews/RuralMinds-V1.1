import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .answer import AnswerQueue, AskRequest, Turn, answer_stream
from .config import settings
from .db import connect, init_schema


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.db = connect(settings.db_path)
    init_schema(app.state.db)
    app.state.http = httpx.AsyncClient()
    app.state.queue = AnswerQueue(settings.llm_parallel, settings.max_queue)
    yield
    await app.state.http.aclose()
    app.state.db.close()


app = FastAPI(title="RuralMinds API", version="0.1.0", lifespan=lifespan)


@app.get("/health", tags=["operations"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "ruralminds-api"}


class TurnIn(BaseModel):
    question: str = Field(max_length=2000)
    answer: str = Field(max_length=4000)


class AskIn(BaseModel):
    """No student identifier of any kind: history lives on the phone and is sent each time."""

    question: str = Field(min_length=1, max_length=2000)
    language: Literal["en", "ml"] = "en"
    medium: Literal["en", "ml"] | None = None  # defaults to the answer language
    subject: str = "social_science"
    chapter_no: int | None = None
    history: list[TurnIn] = Field(default_factory=list, max_length=6)


def _sse(item: dict[str, object]) -> str:
    return f"event: {item['event']}\ndata: {json.dumps(item['data'], ensure_ascii=False)}\n\n"


@app.post("/api/ask", tags=["student"])
async def ask(body: AskIn, request: Request) -> StreamingResponse:
    ask_request = AskRequest(
        question=body.question,
        language=body.language,
        medium=body.medium or body.language,
        subject=body.subject,
        chapter_no=body.chapter_no,
        history=[Turn(turn.question, turn.answer) for turn in body.history],
    )
    state = request.app.state
    events = answer_stream(state.db, state.http, state.queue, ask_request)
    return StreamingResponse(
        (_sse(item) async for item in events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
