"""Idle-time work for exam revision (W5 part 2, step 3): draft suggested questions for the
chapters of upcoming exams, then answer them through the normal pipeline, for the teacher
to review. Students always come first: a step starts only when answering is not paused,
nothing waits in the answer queue, no llama-server slot is busy, and no student has asked
for `revision_idle_s`. One step is one model call, so a student who arrives during it waits
behind at most one answer.
"""

import asyncio
import json
import logging
import re
import sqlite3
import time
from typing import NamedTuple

import httpx

from . import exams
from .answer import AnswerQueue
from .config import settings
from .controls import load_controls
from .llm import complete
from .tutor import load_prompt

log = logging.getLogger("ruralminds.revision")

_LANGUAGE = {"en": "English", "ml": "Malayalam (Malayalam script)"}
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)]|Q\d*[.:)])\s*", re.IGNORECASE)
MATERIAL_CHARS = 3500  # enough key points or text for a chapter, and a short prompt
MAX_TRIES = 3  # drafted questions per wanted one, counting those the book could not answer
NO_EXAM = "9999-12-31"  # sorts after every real exam date


class Shortfall(NamedTuple):
    document_id: int
    chapter: int
    missing: int
    exam_on: str  # the soonest exam that needs this chapter


class Pending(NamedTuple):
    question_id: int
    source: str
    exam_on: str


def chapter_shortfalls(conn: sqlite3.Connection, on: str) -> list[Shortfall]:
    """(book, chapter, how many more) for chapters of exams not yet over. The number wanted
    is the largest any exam on that chapter asks for; questions the book could not answer
    (set aside) do not count, but the total tries are capped so a weak chapter cannot loop."""
    wanted: dict[tuple[int, int], int] = {}
    soonest: dict[tuple[int, int], str] = {}
    for row in conn.execute(
        "SELECT document_id, chapters, drafts_per_chapter, exam_on FROM exam_portions"
        " WHERE exam_on >= ?",
        (on,),
    ):
        for chapter in json.loads(row["chapters"]):
            key = (row["document_id"], chapter)
            wanted[key] = max(wanted.get(key, 0), row["drafts_per_chapter"])
            soonest[key] = min(soonest.get(key, row["exam_on"]), row["exam_on"])
    shortfalls = []
    # The exam that comes first gets its questions first (a test tomorrow beats one next week).
    for (document_id, chapter), count in sorted(
        wanted.items(), key=lambda kv: (soonest[kv[0]], kv[0])
    ):
        usable, tried = conn.execute(
            "SELECT sum(status != 'rejected'), count(*) FROM revision_questions"
            " WHERE document_id = ? AND chapter_no = ? AND source = 'drafted'",
            (document_id, chapter),
        ).fetchone()
        missing = count - (usable or 0)
        if missing > 0 and tried < count * MAX_TRIES:
            gap = Shortfall(document_id, chapter, missing, soonest[(document_id, chapter)])
            shortfalls.append(gap)
    return shortfalls


def next_pending(conn: sqlite3.Connection, busy: set[int]) -> Pending | None:
    """The next question waiting for an answer: the teacher's own first, then those of the
    soonest exam, oldest first."""
    for row in conn.execute(
        "SELECT q.id, q.source, (SELECT min(p.exam_on) FROM exam_portions p"
        "  WHERE p.document_id = q.document_id"
        "  AND EXISTS (SELECT 1 FROM json_each(p.chapters) WHERE value = q.chapter_no))"
        " AS exam_on FROM revision_questions q JOIN documents d ON d.id = q.document_id"
        " WHERE q.status = 'pending' AND d.sha256 = q.doc_sha256"
        " ORDER BY q.source = 'drafted', exam_on IS NULL, exam_on, q.id"
    ):
        if row["id"] not in busy:
            return Pending(int(row["id"]), row["source"], row["exam_on"] or NO_EXAM)
    return None


def answer_first(pending: Pending | None, shortfalls: list[Shortfall]) -> bool:
    """Answer a waiting question, or draft new ones? A teacher's own question always comes
    first; otherwise whichever serves the sooner exam (a test today beats one next week)."""
    if pending is None:
        return False
    if pending.source == "teacher" or not shortfalls:
        return True
    return pending.exam_on <= shortfalls[0].exam_on


def material(conn: sqlite3.Connection, document_id: int, chapter: int, language: str) -> str:
    """The chapter's study-note key points if made, otherwise its first pages of text."""
    notes = conn.execute(
        "SELECT points FROM chapter_notes WHERE document_id = ? AND chapter_no = ?"
        " ORDER BY language = ? DESC LIMIT 1",
        (document_id, chapter, language),
    ).fetchone()
    if notes is not None:
        points = [point["text"] for point in json.loads(notes["points"])]
        if points:
            return "\n".join(f"- {text}" for text in points)[:MATERIAL_CHARS]
    rows = conn.execute(
        "SELECT text FROM chunks WHERE document_id = ? AND chapter_no = ? ORDER BY ordinal",
        (document_id, chapter),
    ).fetchall()
    return "\n\n".join(row["text"] for row in rows)[:MATERIAL_CHARS]


def parse_questions(reply: str) -> list[str]:
    questions = []
    for line in reply.splitlines():
        text = _BULLET.sub("", line).strip().strip('"')
        if len(text) >= 8 and text.endswith("?"):
            questions.append(text)
    return questions


async def draft_chapter(
    conn: sqlite3.Connection,
    client: httpx.AsyncClient,
    queue: AnswerQueue,
    document_id: int,
    chapter: int,
    missing: int,
) -> int:
    """Ask the model for questions on one chapter and add the new ones; returns how many."""
    book = conn.execute("SELECT medium FROM documents WHERE id = ?", (document_id,)).fetchone()
    text = material(conn, document_id, chapter, book["medium"])
    if not text.strip():
        return 0
    messages = [
        {"role": "system", "content": load_prompt("exam_questions_v1")},
        {
            "role": "user",
            "content": f"Language: {_LANGUAGE[book['medium']]}\nQuestions wanted: {missing}\n\n"
            f"Textbook material:\n{text}",
        },
    ]
    ticket = queue.join()
    try:
        if not ticket.admitted.is_set():
            return 0  # a student arrived first: try again when the server is free
        reply = await complete(messages, client, max_tokens=60 * missing + 40)
    finally:
        queue.leave(ticket)
    added = 0
    for question in parse_questions(reply):
        if added >= missing:
            break
        try:
            exams.add_question(conn, document_id, chapter, question, None, source="drafted")
            added += 1
        except exams.ExamError:
            continue  # already in the bank
    return added


class RevisionWorker:
    """Started with the API (unless disabled for tests and the bench)."""

    def __init__(self, state) -> None:
        self.state = state
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(settings.revision_poll_s)
            try:
                await self.step()
            except (httpx.HTTPError, sqlite3.Error, KeyError, ValueError):
                log.exception("revision worker step failed; trying again later")

    async def step(self) -> str | None:
        """One unit of work if the server is idle: answer a waiting question, else draft."""
        state = self.state
        if not await self._idle():
            return None
        pending = next_pending(state.db, state.answering)
        shortfalls = chapter_shortfalls(state.db, exams.today())
        if answer_first(pending, shortfalls):
            question_id = pending.question_id
            state.answering.add(question_id)
            try:
                status = await exams.answer_question(state.db, state.http, state.queue, question_id)
            finally:
                state.answering.discard(question_id)
            set_aside_unanswerable_draft(state.db, question_id, status)
            return "answered"
        for gap in shortfalls:
            if await draft_chapter(
                state.db, state.http, state.queue, gap.document_id, gap.chapter, gap.missing
            ):
                return "drafted"
        return None

    async def _idle(self) -> bool:
        state = self.state
        if not load_controls(state.db).answering_enabled:
            return False  # the admin paused the model: that includes this
        if state.queue.busy() or state.queue.waiting:
            return False
        if time.monotonic() - state.last_ask < settings.revision_idle_s:
            return False
        try:
            slots = (await state.http.get(f"{settings.llm_url}/slots", timeout=5)).json()
        except (httpx.HTTPError, ValueError):
            return False
        return not any(slot.get("is_processing") for slot in slots)


def set_aside_unanswerable_draft(conn: sqlite3.Connection, question_id: int, status: str) -> None:
    """A suggested question the book cannot answer is a bad suggestion: hide it from review
    (a teacher's own such question stays, so she can write the answer)."""
    if status == "not_in_book":
        with conn:
            conn.execute(
                "UPDATE revision_questions SET status = 'rejected' WHERE id = ? AND source = 'drafted'",
                (question_id,),
            )
