"""One student question -> streamed, cited answer or a polite refusal.

    admin controls -> mode (explain / simpler / example / story / quiz / summary)
    -> chapter notes or teacher-approved cache -> search text in the book's language
    -> retrieve -> gate (layer 1) -> pack sources -> tutor prompt -> llama-server stream
    -> sentinel / marker check (layer 2) -> sections + citations from the database -> label

The "Solve step by step" chip (mode "solve") takes the same path up to the sources, then
numerical.py: the model sets the problem up, SymPy solves it and the model explains the lines.

The model only ever sees sources as [S1]..[Sn]; chapter and page numbers come from our own
tables, so the model cannot invent a page. Every request emits a `gate` record with the inputs
to the refusal decision so the threshold can be calibrated on the eval dev split.
"""

import asyncio
import logging
import re
import sqlite3
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field, replace

import httpx

from . import numerical, tutor
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
    # The eval keeps a refused answer's model text to see why it was refused (e.g. Hindi);
    # phones never receive it.
    debug: bool = False


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
    # gate | time_sensitive | not_in_textbook (model's sentinel) | admits_missing | wrong_script
    # | no_valid_citation
    reason: str | None = None
    search_query: str | None = None  # what was searched (after removing request words / rewriting)
    # Every candidate's location and ranks, so the eval can compute recall@k from the event.
    retrieved: list[dict[str, object]] = field(default_factory=list)


def event(name: str, **data: object) -> dict[str, object]:
    return {"event": name, "data": data}


def system_prompt(language: str) -> str:
    return load_prompt(f"{PROMPT_VERSION}_{language}")


def check_gate(hits: list[RetrievedChunk], rewritten: bool = False) -> Gate:
    """Layer 1: refuse without calling the model when retrieval clearly found nothing.

    Cosine similarity alone cannot separate on- from off-topic here (both sit around 0.44),
    but an off-topic question rarely shares a keyword with the book, so we need both signals
    to be weak. A question that was rewritten into the book's language (Manglish, or English
    on a Malayalam book) skips this layer: the rewrite loses words, and on dev the gate's only
    effect on such questions was 2 false refusals; the model's own NOT_IN_TEXTBOOK refuses the
    off-book ones. A stricter keyword rule (>= 2 matched terms) was measured and rejected:
    it refused 7/14 must-refuse dev items the model already refuses, and 4/90 answerable ones.
    """
    similarities = [hit.similarity for hit in hits if hit.similarity is not None]
    top_similarity = max(similarities, default=None)
    keyword_hit = any(hit.fts_rank is not None for hit in hits)
    strong_vector = top_similarity is not None and top_similarity >= settings.refusal_threshold
    passed = bool(hits) and (keyword_hit or strong_vector or rewritten)
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


class Ticket:
    """One phone's place in the answer queue."""

    def __init__(self) -> None:
        self.admitted = asyncio.Event()


class AnswerQueue:
    """Admits as many answers as llama-server has slots; the rest wait in line, first come
    first served. A finished answer hands its slot straight to the next ticket, and `leave`
    is the single exit for every path (answered, refused, phone gone while waiting or after
    admission), so a slot can never leak (W5, 19 Oct)."""

    def __init__(self, slots: int, max_waiting: int, max_wait_s: float | None = None) -> None:
        self._free = slots
        self._line: deque[Ticket] = deque()
        self._max_waiting = max_waiting
        self._max_wait_s = max_wait_s
        # Seconds between finished answers while others waited: the measured service rate.
        # Two slots share one GPU (bench 19 Oct), so slots x answer time would overstate it.
        self._gaps: deque[float] = deque(maxlen=8)
        self._last_busy_finish: float | None = None

    @property
    def waiting(self) -> int:
        return len(self._line)

    def busy(self) -> bool:
        return self._free == 0

    def position(self, ticket: Ticket) -> int:
        return self._line.index(ticket) + 1 if ticket in self._line else 0

    def eta_s(self, position: int) -> int | None:
        """Predicted wait for a place in line; None until a few answers were timed."""
        if position <= 0 or len(self._gaps) < 3:
            return None
        return round(position * sum(self._gaps) / len(self._gaps))

    def full(self) -> bool:
        """Turn a new question away: the line is at its cap, or the predicted wait for one
        more place exceeds max_wait_s (a student would rather read notes than wait longer)."""
        if self.waiting >= self._max_waiting:
            return True
        eta = self.eta_s(self.waiting + 1) if self.busy() else None
        return self._max_wait_s is not None and eta is not None and eta > self._max_wait_s

    def join(self) -> Ticket:
        ticket = Ticket()
        if self._free > 0 and not self._line:
            self._free -= 1
            ticket.admitted.set()
        else:
            self._line.append(ticket)
        return ticket

    async def wait(self, ticket: Ticket, seconds: float) -> bool:
        """Wait up to `seconds` for a slot; True once admitted. Holds nothing while waiting."""
        try:
            await asyncio.wait_for(ticket.admitted.wait(), seconds)
        except TimeoutError:
            pass
        return ticket.admitted.is_set()

    def leave(self, ticket: Ticket) -> None:
        if not ticket.admitted.is_set():
            if ticket in self._line:
                self._line.remove(ticket)
            return
        self._time_finish()
        if self._line:
            self._line.popleft().admitted.set()  # hand the slot over directly
        else:
            self._free += 1

    def _time_finish(self) -> None:
        now = time.perf_counter()
        if self._line and self._last_busy_finish is not None:
            self._gaps.append(now - self._last_busy_finish)
        self._last_busy_finish = now if self._line else None


async def answer_stream(
    conn: sqlite3.Connection, client: httpx.AsyncClient, queue: AnswerQueue, request: AskRequest
) -> AsyncIterator[dict[str, object]]:
    """Events: queued{position} | progress{step} | token{text} | done | notes | refused | blocked
    | busy | error. `progress` comes only from the solve chip (its setup call writes nothing)."""
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
    if tutor.time_sensitive(request.question):
        gate = Gate(None, False, None, 0, passed=False, reason="time_sensitive")
        yield _refuse(conn, request, gate, clock, message_key="refusal.time_sensitive")
        return
    async for item in _answer_from_book(conn, client, queue, request, clock):
        yield item


async def _answer_from_book(
    conn: sqlite3.Connection,
    client: httpx.AsyncClient,
    queue: AnswerQueue,
    request: AskRequest,
    clock: Clock,
) -> AsyncIterator[dict[str, object]]:
    """Search, gate, then generate. The queue slot is taken just before the first model call:
    before the search rewrite for a question in another language (the rewrite is a model call
    too), otherwise after the gate, so refusals stay instant under load. The finally block is
    the one exit that gives the place in line or the slot back, whatever happens."""
    rewritten = tutor.question_language(request.question) != request.medium
    ticket: Ticket | None = None
    try:
        if rewritten:
            ticket = queue.join() if not queue.full() else None
            if ticket is None:
                yield event("busy", message_key="error.busy")
                return
            async for item in _wait_for_slot(queue, ticket):
                yield item
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
        gate = replace(check_gate(hits, rewritten), search_query=search_text)
        if not gate.passed:
            final = _refuse(conn, request, gate, clock)
        else:
            if ticket is None:
                ticket = queue.join() if not queue.full() else None
                if ticket is None:
                    yield event("busy", message_key="error.busy")
                    return
                async for item in _wait_for_slot(queue, ticket):
                    yield item
            sources = pack_sources(hits, settings.max_context_tokens)
            answering = (
                _solve(conn, client, request, gate, sources, clock)
                if request.mode == "solve"
                else _generate(conn, client, request, gate, sources, clock)
            )
            async for item in answering:
                if item["event"] in ("token", "progress"):
                    yield item
                else:
                    final = item
    finally:
        if ticket is not None:
            queue.leave(ticket)
    yield final  # after the slot is free: a slow phone never holds it


async def _generate(
    conn: sqlite3.Connection,
    client: httpx.AsyncClient,
    request: AskRequest,
    gate: Gate,
    sources: list[RetrievedChunk],
    clock: Clock,
    stream: bool = True,
) -> AsyncIterator[dict[str, object]]:
    """The tutor answer: token events (unless stream is False), then one final done / refused /
    error event. Unstreamed, the first word is logged as None: the student saw no text early."""
    parts: list[str] = []
    try:
        async for piece in _release_tokens(_chat(client, request, sources), parts):
            if stream:
                clock.first_token = clock.first_token or time.perf_counter()
                yield event("token", text=piece)
    except httpx.HTTPError:
        log.exception("llama-server request failed")
        _log(conn, request, "error", clock)
        yield event("error", message_key="error.model")
        return
    yield _finish(conn, request, gate, sources, "".join(parts), clock)


async def _solve(
    conn: sqlite3.Connection,
    client: httpx.AsyncClient,
    request: AskRequest,
    gate: Gate,
    sources: list[RetrievedChunk],
    clock: Clock,
) -> AsyncIterator[dict[str, object]]:
    """ "Solve step by step": set up, solve with SymPy, explain the worked lines. Anything that
    does not solve cleanly (or a Malayalam answer, not built yet) gets the tutor's method
    explanation instead, with no final number; `math_status` says why, for the eval."""
    try:
        if request.language == "en":
            # The setup call shows nothing on screen: tell the phone what is happening.
            yield event("progress", step="solving")
            setup = await numerical.set_up(client, request.question)
        else:  # step-by-step solving is English-only for now; Malayalam gets the method
            setup = numerical.Setup("language_not_supported")
        if setup.status != "solved":
            # Not streamed: the method answer is shown only once it passed every check, so
            # nothing appears and is then erased (user test, 20 Oct: 3 such refusals).
            yield event("progress", step="method")
            async for item in _generate(conn, client, request, gate, sources, clock, False):
                if item["event"] == "done":
                    item["data"]["math_status"] = setup.status
                yield item
            return
        parts: list[str] = []
        messages = numerical.explain_messages(
            request.question, sources, setup.lines, request.language
        )
        grammar = numerical.explain_grammar(setup.lines)
        async for piece in chat_stream(messages, client, numerical.EXPLAIN_MAX_TOKENS, grammar):
            clock.first_token = clock.first_token or time.perf_counter()
            parts.append(piece)
            yield event("token", text=piece)
    except httpx.HTTPError:
        log.exception("llama-server request failed")
        _log(conn, request, "error", clock)
        yield event("error", message_key="error.model")
        return
    yield _finish_solved(conn, request, gate, sources, setup, "".join(parts), clock)


def _finish_solved(
    conn: sqlite3.Connection,
    request: AskRequest,
    gate: Gate,
    sources: list[RetrievedChunk],
    setup: numerical.Setup,
    raw_text: str,
    clock: Clock,
) -> dict[str, object]:
    """Like _finish: the method must be cited, or the answer is refused (rule 2)."""
    card = numerical.read_explanation(raw_text, request.question, setup.lines)
    card.idea, cited = validate_markers(card.idea, len(sources))
    for step in card.steps:
        step["why"], cited_here = validate_markers(step["why"], len(sources))
        cited += [n for n in cited_here if n not in cited]
    if not cited:
        gate = replace(gate, passed=False, reason="no_valid_citation")
        return _refuse(conn, request, gate, clock, raw_text)
    answers = setup.solution.solutions[0]
    # Several answers ("27 metres, 13 metres") need their names to say which is which.
    card.answers = [
        f"{answer.asked} = {answer.display}" if len(answers) > 1 else answer.display
        for answer in answers
    ]
    _log(conn, request, "answered", clock)
    return event(
        "done",
        text=numerical.card_text(card),
        card=asdict(card),
        mode=request.mode,
        language=request.language,
        citations=[citation(n, sources[n - 1]) for n in cited],
        label="ai_explanation",
        prompt_version=f"{numerical.EXPLAIN_PROMPT}_{request.language}",
        gate=asdict(gate),
        math_status="solved",
        # For the eval: what was solved and SymPy's exact values, compared with gold answers.
        math={
            "equations": list(setup.problem.equations),
            "knowns": [list(known) for known in setup.problem.knowns],
            "answers": [{"asked": a.asked, "exact": a.exact, "unit": a.unit} for a in answers],
        },
    )


async def _wait_for_slot(queue: AnswerQueue, ticket: Ticket) -> AsyncIterator[dict[str, object]]:
    """Every 3 s while waiting: the live place in line and a wait estimate (also keeps the
    phone's connection alive). Nothing is held while waiting."""
    while not ticket.admitted.is_set():
        position = queue.position(ticket)
        yield event("queued", position=position, eta_s=queue.eta_s(position))
        await queue.wait(ticket, settings.queue_update_s)


def _chat(
    client: httpx.AsyncClient, request: AskRequest, sources: list[RetrievedChunk]
) -> AsyncIterator[str]:
    messages = build_messages(request, sources)
    return chat_stream(messages, client, tutor.MAX_TOKENS.get(request.mode or "", None))


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
    parts = tutor.split_sections(raw_text)
    reason = _model_refusal(raw_text, parts, request.language)
    if reason is not None:
        return _refuse(conn, request, replace(gate, passed=False, reason=reason), clock, raw_text)
    text, cited = validate_markers(parts.explanation, len(sources))
    answers, cited_in_answers = validate_markers(parts.answers, len(sources))
    cited = list(dict.fromkeys(cited + cited_in_answers))
    if not cited:
        gate = replace(gate, passed=False, reason="no_valid_citation")
        return _refuse(conn, request, gate, clock, raw_text)
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


def _model_refusal(raw_text: str, parts: tutor.Sections, language: str) -> str | None:
    """Why the model's answer must not be shown, kept apart so each cause can be counted:
    its own sentinel, an admission that the sources lack the answer (the rest would be its own
    knowledge), or an answer mostly in another script (e.g. Hindi for a Malayalam question)."""
    if SENTINEL in raw_text:
        return "not_in_textbook"
    if tutor.admits_missing(parts.explanation):
        return "admits_missing"
    if tutor.wrong_script(parts.explanation, language):
        return "wrong_script"
    return None


def _refuse(
    conn: sqlite3.Connection,
    request: AskRequest,
    gate: Gate,
    clock: Clock,
    raw_text: str | None = None,
    message_key: str = "refusal.not_found",
) -> dict[str, object]:
    if request.class_id:  # students only: teacher tests and the eval stay out of the inbox
        _save_unanswered(conn, request, gate)
    _log(conn, request, "refused", clock)
    extra = {"raw_text": raw_text} if request.debug and raw_text else {}
    return event(
        "refused",
        reason=gate.reason,
        message_key=message_key,
        gate=asdict(gate),
        **extra,
    )


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
