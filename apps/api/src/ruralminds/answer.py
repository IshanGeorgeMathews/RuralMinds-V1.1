"""One student question -> streamed, cited answer or a polite refusal.

    admin controls -> mode (explain / simpler / example / story / quiz / summary)
    -> chapter notes or teacher-approved cache -> search text in the book's language
    -> retrieve -> gate (layer 1) -> pack sources -> tutor prompt -> llama-server stream
    -> sentinel / marker check (layer 2) -> sections + citations from the database -> label

The model only ever sees sources as [S1]..[Sn]; chapter and page numbers come from our own
tables, so the model cannot invent a page. Every request emits a `gate` record with the inputs
to the refusal decision so the threshold can be calibrated on the eval dev split.
"""

import asyncio
import logging
import re
import sqlite3
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field, replace

import httpx

from . import tutor
from .cache import lookup as lookup_approved
from .cache import normalise_question
from .config import settings
from .controls import ask_blocked, load_controls
from .llm import chat_stream, complete
from .notes import notes_answer
from .retrieve import Filters, RetrievedChunk, retrieve
from .textnorm import normalize
from .tutor import load_prompt

log = logging.getLogger("ruralminds.answer")

SENTINEL = "NOT_IN_TEXTBOOK"
PROMPT_VERSION = "system_v2_tutor"
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
    document_id: int | None = None  # the book being asked about; None = eval across a medium
    class_id: int = 0  # only for class-level counts; 0 = teacher or eval. Never a student id.
    use_cache: bool = True  # the eval turns it off so it measures the model, not the cache
    mode: str | None = None  # a quick-action chip; None = detect from the question


@dataclass
class Clock:
    started: float = field(default_factory=time.perf_counter)
    first_token: float | None = None

    def ms(self, moment: float | None) -> int | None:
        return None if moment is None else round((moment - self.started) * 1000)


@dataclass
class Gate:
    top_similarity: float | None
    keyword_hit: bool
    top_rrf: float | None
    candidates: int
    passed: bool
    reason: str | None = None  # gate | not_in_textbook | no_valid_citation | model_error
    search_query: str | None = None  # what was searched (after removing request words / rewriting)
    # Every candidate's location and ranks, so the eval can compute recall@k from the event.
    retrieved: list[dict[str, object]] = field(default_factory=list)


def event(name: str, **data: object) -> dict[str, object]:
    return {"event": name, "data": data}


def system_prompt(language: str) -> str:
    return load_prompt(f"{PROMPT_VERSION}_{language}")


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
    task = tutor.instruction(request.mode or "explain")
    messages.append(
        {
            "role": "user",
            "content": f"Sources:\n{numbered}\n\nTask: {task}\nQuestion: {request.question}",
        }
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
    """Events: queued{position} | token{text} | done | notes | refused | blocked | busy | error."""
    clock = Clock()
    question = normalize(request.question).strip()[: settings.max_question_chars]
    if not question:
        yield event("refused", reason="empty", message_key="refusal.empty")
        return
    blocked = ask_blocked(load_controls(conn), request.language, request.class_id or None)
    if blocked:
        yield event("blocked", message_key=blocked)
        return
    request = _with_mode(replace(request, question=question))
    ready = _ready_answer(conn, request)
    if ready is not None:
        _log(conn, request, "cached", clock)
        yield ready
        return
    search_text = await _search_text(conn, client, request)
    filters = Filters(request.medium, request.subject, request.chapter_no, request.document_id)
    try:
        hits = await retrieve(conn, search_text, filters, CANDIDATE_POOL)
    except httpx.HTTPError:
        # Search embeds the question; if the embedding server is down, say so instead of
        # dropping the stream (the phone would then blame its own Wi-Fi).
        log.exception("embedding server request failed")
        _log(conn, request, "error", clock)
        yield event("error", message_key="error.model")
        return
    gate = replace(check_gate(hits), search_query=search_text)
    if not gate.passed:
        yield _refuse(conn, request, gate, clock)
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
            messages = build_messages(request, sources)
            stream = chat_stream(messages, client, tutor.MAX_TOKENS.get(request.mode or "", None))
            async for piece in _release_tokens(stream, parts):
                clock.first_token = clock.first_token or time.perf_counter()
                yield event("token", text=piece)
        except httpx.HTTPError:
            log.exception("llama-server request failed")
            _log(conn, request, "error", clock)
            yield event("error", message_key="error.model")
            return
    yield _finish(conn, request, gate, sources, "".join(parts), clock)


def _with_mode(request: AskRequest) -> AskRequest:
    """A chip sets the mode; otherwise read it from the question. "Summarise chapter 2"
    also narrows the search to chapter 2."""
    mode = request.mode if request.mode in tutor.MODES else tutor.detect_mode(request.question)
    chapter = request.chapter_no
    if mode == "summary" and chapter is None:
        chapter = tutor.chapter_in(request.question)
    return replace(request, mode=mode, chapter_no=chapter)


def _ready_answer(conn: sqlite3.Connection, request: AskRequest) -> dict[str, object] | None:
    """Answers that need no model call: chapter study notes, then teacher-approved answers."""
    if request.mode == "summary" and request.document_id and request.chapter_no:
        # Notes are made in the book's language; another language falls back to those.
        for language in dict.fromkeys([request.language, request.medium]):
            notes = notes_answer(conn, request.document_id, request.chapter_no, language)
            if notes is not None:
                return event("notes", **notes)
    cached = _cached_answer(conn, request)
    if cached is not None:
        return event("done", **cached, label="teacher_approved")
    return None


async def _search_text(
    conn: sqlite3.Connection, client: httpx.AsyncClient, request: AskRequest
) -> str:
    """Search in the book's language: a Manglish or other-language question is rewritten first,
    because keywords can only match text written in the same script."""
    topic = _retrieval_query(request)
    if len(topic.split()) < 2 and request.chapter_no and request.document_id:
        # "Quiz me on this chapter" leaves no topic words: search for the chapter itself.
        row = conn.execute(
            "SELECT title FROM book_chapters WHERE document_id = ? AND chapter_no = ?",
            (request.document_id, request.chapter_no),
        ).fetchone()
        if row is not None:
            return f"{row['title']} {topic}".strip()  # titles are in the book's language
    if tutor.question_language(request.question) == request.medium:
        return topic
    return await _rewrite_for_search(client, topic, request.medium) or topic


_REWRITES: dict[tuple[str, str], str] = {}
_MAX_REWRITES = 500


async def _rewrite_for_search(client: httpx.AsyncClient, text: str, medium: str) -> str | None:
    key = (text, medium)
    if key in _REWRITES:
        return _REWRITES[key]
    language = "Malayalam (Malayalam script)" if medium == "ml" else "English"
    messages = [
        {"role": "system", "content": load_prompt("rewrite_v1")},
        {"role": "user", "content": f"Language: {language}\nQuestion: {text}"},
    ]
    try:
        reply = await complete(messages, client, max_tokens=80)
    except httpx.HTTPError:
        log.warning("search rewrite failed; searching with the original words")
        return None
    rewritten = normalize(reply.splitlines()[0] if reply else "").strip().strip('"')
    if not rewritten or SENTINEL in rewritten:
        return None
    if len(_REWRITES) >= _MAX_REWRITES:
        _REWRITES.clear()
    _REWRITES[key] = rewritten
    return rewritten


def _cached_answer(conn: sqlite3.Connection, request: AskRequest) -> dict | None:
    """Only a first question can match: a follow-up depends on the conversation before it."""
    if request.document_id is None or request.history or not request.use_cache:
        return None
    return lookup_approved(
        conn, request.question, request.language, request.document_id, request.chapter_no
    )


def _retrieval_query(request: AskRequest) -> str:
    """The topic of the question, without request words ("explain as a story", "simpler").
    A follow-up like "Why?" or "Give an example" has no topic of its own, so the latest earlier
    question that does name a topic is searched too ("as a story, I didn't understand" names
    none, so it is skipped)."""
    topic = tutor.topic_query(request.question)
    earlier = (tutor.topic_query(turn.question) for turn in reversed(request.history))
    previous = next((text for text in earlier if len(text.split()) >= 2), "")
    return f"{previous} {topic}".strip() or request.question


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
    clock: Clock,
) -> dict[str, object]:
    """Layer 2: the model's own "not in the sources" signal, then marker validation."""
    if SENTINEL in raw_text:
        gate = replace(gate, passed=False, reason="not_in_textbook")
        return _refuse(conn, request, gate, clock)
    parts = tutor.split_sections(raw_text)
    if tutor.admits_missing(parts.explanation) or tutor.wrong_script(
        parts.explanation, request.language
    ):
        gate = replace(gate, passed=False, reason="not_in_textbook")
        return _refuse(conn, request, gate, clock)
    text, cited = validate_markers(parts.explanation, len(sources))
    answers, cited_in_answers = validate_markers(parts.answers, len(sources))
    cited = list(dict.fromkeys(cited + cited_in_answers))
    if not cited:
        gate = replace(gate, passed=False, reason="no_valid_citation")
        return _refuse(conn, request, gate, clock)
    _log(conn, request, "answered", clock)
    return event(
        "done",
        text=text,
        # Not from the book, so it never carries a source marker (shown in its own box).
        example=_MARKER.sub("", parts.example).strip(),
        check=_MARKER.sub("", parts.check).strip(),
        answers=answers,
        mode=request.mode,
        language=request.language,
        citations=[citation(n, sources[n - 1]) for n in cited],
        label="ai_explanation",
        prompt_version=f"{PROMPT_VERSION}_{request.language}",
        gate=asdict(gate),
    )


def _refuse(
    conn: sqlite3.Connection, request: AskRequest, gate: Gate, clock: Clock
) -> dict[str, object]:
    if request.class_id:  # students only: teacher tests and the eval stay out of the inbox
        _save_unanswered(conn, request, gate)
    _log(conn, request, "refused", clock)
    return event("refused", reason=gate.reason, message_key="refusal.not_found", gate=asdict(gate))


def _save_unanswered(conn: sqlite3.Connection, request: AskRequest, gate: Gate) -> None:
    """One inbox row per question per class and book; asking again only raises the count."""
    with conn:
        conn.execute(
            "INSERT INTO unanswered (question, language, subject, chapter_no, best_score, reason,"
            " class_id, document_id, normalised_q, last_asked)"
            " VALUES (?,?,?,?,?,?,?,?,?, datetime('now'))"
            " ON CONFLICT (class_id, document_id, normalised_q) DO UPDATE SET"
            " times_asked = times_asked + 1, last_asked = excluded.last_asked,"
            " reason = excluded.reason",
            (
                request.question,
                request.language,
                request.subject,
                request.chapter_no,
                gate.top_similarity,
                gate.reason,
                request.class_id,
                request.document_id,
                normalise_question(request.question),
            ),
        )


def _log(conn: sqlite3.Connection, request: AskRequest, outcome: str, clock: Clock) -> None:
    """Class-level counts and timings only: no student, no device, no question text."""
    with conn:
        conn.execute(
            "INSERT INTO answer_log (class_id, document_id, chapter_no, language, outcome,"
            " ttft_ms, total_ms) VALUES (?,?,?,?,?,?,?)",
            (
                request.class_id,
                request.document_id,
                request.chapter_no,
                request.language,
                outcome,
                clock.ms(clock.first_token),
                clock.ms(time.perf_counter()),
            ),
        )
