"""One student question -> streamed, cited answer or a polite refusal.

    retrieve -> gate (layer 1) -> pack sources -> prompt -> llama-server stream
    -> sentinel / marker check (layer 2) -> citations from the database -> label

The model only ever sees sources as [S1]..[Sn]; chapter and page numbers come from our own
tables, so the model cannot invent a page. Every request emits a `gate` record with the inputs
to the refusal decision so the threshold can be calibrated on the eval dev split.
"""

import asyncio
import logging
import re
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field, replace
from functools import cache
from pathlib import Path

import httpx

from .config import settings
from .llm import chat_stream
from .retrieve import Filters, RetrievedChunk, retrieve
from .textnorm import normalize

log = logging.getLogger("ruralminds.answer")

SENTINEL = "NOT_IN_TEXTBOOK"
PROMPT_VERSION = "system_v1_social"
CANDIDATE_POOL = 6  # retrieved before packing to the token budget
# [S1], [S1, S3], [S1; 2], [Source 1]: small models are inconsistent, so parse leniently.
_MARKER = re.compile(
    r"\[\s*S(?:ource)?\s*\d+(?:\s*[,;]\s*(?:S(?:ource)?\s*)?\d+)*\s*\]", re.IGNORECASE
)
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?।])")


@dataclass
class Turn:
    question: str
    answer: str


@dataclass
class AskRequest:
    question: str
    language: str  # answer language: "en" | "ml"
    medium: str  # which book to search; differs from language only for cross-lingual eval
    subject: str = "social_science"
    chapter_no: int | None = None
    history: list[Turn] = field(default_factory=list)


@dataclass
class Gate:
    top_similarity: float | None
    keyword_hit: bool
    top_rrf: float | None
    candidates: int
    passed: bool
    reason: str | None = None  # gate | not_in_textbook | no_valid_citation | model_error
    # Every candidate's location and ranks, so the eval can compute recall@k from the event.
    retrieved: list[dict[str, object]] = field(default_factory=list)


def event(name: str, **data: object) -> dict[str, object]:
    return {"event": name, "data": data}


@cache
def system_prompt(language: str) -> str:
    """Prompt file body after the '---' line; the version line stays out of the prompt."""
    path = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}_{language}.md"
    return path.read_text(encoding="utf-8").split("\n---\n", 1)[1].strip()


def check_gate(hits: list[RetrievedChunk]) -> Gate:
    """Layer 1: refuse without calling the model when retrieval clearly found nothing.

    Cosine similarity alone cannot separate on- from off-topic here (both sit around 0.44),
    but an off-topic question rarely shares a keyword with the book, so we need both signals
    to be weak. Cross-lingual questions never get keyword hits and rely on similarity alone.
    """
    similarities = [hit.similarity for hit in hits if hit.similarity is not None]
    top_similarity = max(similarities, default=None)
    keyword_hit = any(hit.fts_rank is not None for hit in hits)
    strong_vector = top_similarity is not None and top_similarity >= settings.refusal_threshold
    passed = bool(hits) and (keyword_hit or strong_vector)
    return Gate(
        top_similarity=round(top_similarity, 4) if top_similarity is not None else None,
        keyword_hit=keyword_hit,
        top_rrf=round(hits[0].score, 5) if hits else None,
        candidates=len(hits),
        passed=passed,
        reason=None if passed else "gate",
        retrieved=[
            {
                "book_id": hit.book_id,
                "chapter_no": hit.chapter_no,
                "page_start": hit.page_start,
                "page_end": hit.page_end,
                "fts_rank": hit.fts_rank,
                "vec_rank": hit.vec_rank,
                "similarity": round(hit.similarity, 4) if hit.similarity is not None else None,
            }
            for hit in hits
        ],
    )


def pack_sources(hits: list[RetrievedChunk], budget: int) -> list[RetrievedChunk]:
    """Greedy in rank order up to the token budget; always keep the best chunk.

    Malayalam chunks cost ~30% more tokens than English ones, so a fixed top-k would blow
    the prefill budget (and latency) for Malayalam.
    """
    packed: list[RetrievedChunk] = []
    used = 0
    for hit in hits[: settings.final_top_k]:
        if packed and used + hit.token_count > budget:
            continue
        packed.append(hit)
        used += hit.token_count
    return packed


def build_messages(request: AskRequest, sources: list[RetrievedChunk]) -> list[dict[str, str]]:
    """System prompt first and unchanged, so llama-server can reuse its cached prefix."""
    messages = [{"role": "system", "content": system_prompt(request.language)}]
    for turn in request.history[-settings.history_turns :]:
        messages.append({"role": "user", "content": turn.question})
        # Old markers point at old sources; drop them so they cannot be confused with new ones.
        messages.append({"role": "assistant", "content": _MARKER.sub("", turn.answer).strip()})
    numbered = "\n\n".join(f"[S{n}] {hit.text}" for n, hit in enumerate(sources, start=1))
    messages.append(
        {"role": "user", "content": f"Sources:\n{numbered}\n\nQuestion: {request.question}"}
    )
    return messages


def validate_markers(text: str, source_count: int) -> tuple[str, list[int]]:
    """Keep only markers that point at a real source; return cleaned text + cited numbers."""
    cited: list[int] = []

    def rewrite(match: re.Match[str]) -> str:
        numbers = [int(n) for n in re.findall(r"\d+", match.group())]
        valid = [n for n in dict.fromkeys(numbers) if 1 <= n <= source_count]
        cited.extend(n for n in valid if n not in cited)
        return "".join(f"[S{n}]" for n in valid)

    cleaned = _SPACE_BEFORE_PUNCT.sub(r"\1", _MARKER.sub(rewrite, text)).strip()
    return cleaned, cited


def citation(number: int, hit: RetrievedChunk) -> dict[str, object]:
    return {
        "marker": f"S{number}",
        "book_id": hit.book_id,
        "chapter_no": hit.chapter_no,
        "chapter_title": hit.chapter_title,
        "page_start": hit.page_start,
        "page_end": hit.page_end,
    }


class AnswerQueue:
    """Admits as many answers as llama-server has slots; the rest wait in line (bounded)."""

    def __init__(self, slots: int, max_waiting: int) -> None:
        self._slots = asyncio.Semaphore(slots)
        self._max_waiting = max_waiting
        self.waiting = 0

    def full(self) -> bool:
        return self.waiting >= self._max_waiting

    async def __aenter__(self) -> None:
        self.waiting += 1
        try:
            await self._slots.acquire()
        finally:
            self.waiting -= 1

    async def __aexit__(self, *exc_info: object) -> None:
        self._slots.release()

    def busy(self) -> bool:
        return self._slots.locked()


async def answer_stream(
    conn: sqlite3.Connection, client: httpx.AsyncClient, queue: AnswerQueue, request: AskRequest
) -> AsyncIterator[dict[str, object]]:
    """Events: queued{position} | token{text} | done{...} | refused{...} | busy | error."""
    question = normalize(request.question).strip()[: settings.max_question_chars]
    if not question:
        yield event("refused", reason="empty", message_key="refusal.empty")
        return
    request = replace(request, question=question)
    filters = Filters(request.medium, request.subject, request.chapter_no)
    hits = await retrieve(conn, _retrieval_query(request), filters, CANDIDATE_POOL)
    gate = check_gate(hits)
    if not gate.passed:
        yield _refuse(conn, request, gate)
        return
    sources = pack_sources(hits, settings.max_context_tokens)
    if queue.full():
        yield event("busy", message_key="error.busy")
        return
    if queue.busy():
        yield event("queued", position=queue.waiting + 1)
    parts: list[str] = []
    async with queue:
        try:
            stream = chat_stream(build_messages(request, sources), client)
            async for piece in _release_tokens(stream, parts):
                yield event("token", text=piece)
        except httpx.HTTPError:
            log.exception("llama-server request failed")
            yield event("error", message_key="error.model")
            return
    yield _finish(conn, request, gate, sources, "".join(parts))


def _retrieval_query(request: AskRequest) -> str:
    """A follow-up like "Why?" retrieves nothing alone; search with the previous question too."""
    if request.history:
        return f"{request.history[-1].question} {request.question}"
    return request.question


async def _release_tokens(stream: AsyncIterator[str], parts: list[str]) -> AsyncIterator[str]:
    """Pass pieces through, but hold back anything that could still become the sentinel,
    so a refusal never flashes "NOT_IN_TEXTBOOK" on the student's screen."""
    released = False
    async for piece in stream:
        parts.append(piece)
        if released:
            yield piece
            continue
        so_far = "".join(parts).lstrip()
        if SENTINEL.startswith(so_far) or so_far.startswith(SENTINEL):
            continue
        released = True
        yield "".join(parts)


def _finish(
    conn: sqlite3.Connection,
    request: AskRequest,
    gate: Gate,
    sources: list[RetrievedChunk],
    raw_text: str,
) -> dict[str, object]:
    """Layer 2: the model's own "not in the sources" signal, then marker validation."""
    if SENTINEL in raw_text:
        return _refuse(conn, request, replace(gate, passed=False, reason="not_in_textbook"))
    text, cited = validate_markers(raw_text, len(sources))
    if not cited:
        return _refuse(conn, request, replace(gate, passed=False, reason="no_valid_citation"))
    _count_usage(conn, request, refused=False)
    return event(
        "done",
        text=text,
        citations=[citation(n, sources[n - 1]) for n in cited],
        label="ai_explanation",
        prompt_version=f"{PROMPT_VERSION}_{request.language}",
        gate=asdict(gate),
    )


def _refuse(conn: sqlite3.Connection, request: AskRequest, gate: Gate) -> dict[str, object]:
    with conn:
        conn.execute(
            "INSERT INTO unanswered (question, language, subject, chapter_no, best_score, reason)"
            " VALUES (?,?,?,?,?,?)",
            (
                request.question,
                request.language,
                request.subject,
                request.chapter_no,
                gate.top_similarity,
                gate.reason,
            ),
        )
    _count_usage(conn, request, refused=True)
    return event("refused", reason=gate.reason, message_key="refusal.not_found", gate=asdict(gate))


def _count_usage(conn: sqlite3.Connection, request: AskRequest, refused: bool) -> None:
    """Aggregate counts only: no question text, no student, no device."""
    with conn:
        conn.execute(
            "INSERT INTO usage_daily (day, language, subject, questions, refusals)"
            " VALUES (date('now', 'localtime'), ?, ?, 1, ?)"
            " ON CONFLICT (day, language, subject) DO UPDATE SET"
            " questions = questions + 1, refusals = refusals + excluded.refusals",
            (request.language, request.subject, int(refused)),
        )
