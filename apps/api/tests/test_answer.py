import asyncio
from collections.abc import AsyncIterator

import pytest

from ruralminds.answer import (
    SENTINEL,
    AnswerQueue,
    AskRequest,
    Turn,
    _release_tokens,
    build_messages,
    check_gate,
    pack_sources,
    validate_markers,
)
from ruralminds.config import settings
from ruralminds.retrieve import RetrievedChunk


def _hit(chunk_id: int, tokens: int = 200, fts: int | None = 1, sim: float | None = 0.6):
    return RetrievedChunk(
        chunk_id,
        "b",
        "en",
        1,
        "Early Human Life",
        11,
        11,
        f"text {chunk_id}",
        tokens,
        score=0.03,
        fts_rank=fts,
        vec_rank=1,
        similarity=sim,
    )


# ---------- gate (layer 1) ----------
def test_gate_passes_with_keyword_hit_even_if_similarity_is_low() -> None:
    assert check_gate([_hit(1, sim=0.3)]).passed


def test_gate_refuses_with_no_keyword_hit_and_low_similarity() -> None:
    gate = check_gate([_hit(1, fts=None, sim=settings.refusal_threshold - 0.01)])
    assert not gate.passed and gate.reason == "gate"


def test_gate_passes_cross_lingual_on_strong_similarity() -> None:
    assert check_gate([_hit(1, fts=None, sim=settings.refusal_threshold + 0.01)]).passed


def test_gate_refuses_when_nothing_retrieved() -> None:
    assert not check_gate([]).passed


def test_rewritten_question_skips_the_gate_but_not_an_empty_search() -> None:
    weak = [_hit(1, fts=None, sim=settings.refusal_threshold - 0.1)]
    assert not check_gate(weak).passed
    assert check_gate(weak, rewritten=True).passed  # the model decides (NOT_IN_TEXTBOOK)
    assert not check_gate([], rewritten=True).passed


# ---------- packing ----------
def test_pack_respects_token_budget_but_keeps_best_chunk() -> None:
    assert [h.chunk_id for h in pack_sources([_hit(1, 300), _hit(2, 300), _hit(3, 100)], 450)] == [
        1,
        3,
    ]
    assert [h.chunk_id for h in pack_sources([_hit(1, 2000)], 450)] == [1]


# ---------- markers (layer 2) ----------
def test_invalid_marker_is_dropped_and_valid_kept() -> None:
    text, cited = validate_markers("Rock shelters [S1]. Caves [S9].", source_count=3)
    assert text == "Rock shelters [S1]. Caves."
    assert cited == [1]


def test_lenient_marker_forms_are_normalised() -> None:
    text, cited = validate_markers("A [S1, S3]. B [s2]. C [Source 2].", source_count=3)
    assert "[S1][S3]" in text and cited == [1, 3, 2]


def test_no_valid_marker_means_no_citations() -> None:
    assert validate_markers("An answer from memory.", source_count=3)[1] == []


# ---------- prompt ----------
def test_messages_put_fixed_system_prompt_first_and_strip_old_markers() -> None:
    request = AskRequest("Why?", "en", "en", history=[Turn("Q1", "Old answer [S2].")])
    messages = build_messages(request, [_hit(1)])
    assert messages[0]["role"] == "system" and "NOT_IN_TEXTBOOK" in messages[0]["content"]
    assert "[S2]" not in messages[2]["content"]
    assert messages[-1]["content"].startswith("Sources:\n[S1] text 1")
    assert "11" not in messages[-1]["content"]  # page numbers never reach the model


# ---------- streaming ----------
async def _pieces(*pieces: str) -> AsyncIterator[str]:
    for piece in pieces:
        yield piece


async def _collect(*pieces: str) -> tuple[list[str], str]:
    parts: list[str] = []
    shown = [p async for p in _release_tokens(_pieces(*pieces), parts)]
    return shown, "".join(parts)


def test_sentinel_never_reaches_the_screen() -> None:
    shown, full = asyncio.run(_collect("NOT", "_IN", "_TEXT", "BOOK"))
    assert shown == [] and full == SENTINEL


def test_normal_answer_streams_from_first_safe_piece() -> None:
    shown, _ = asyncio.run(_collect("N", "ile ", "river [S1]."))
    assert shown == ["Nile ", "river [S1]."]


# ---------- queue ----------
def test_queue_is_first_come_first_served_with_direct_handoff() -> None:
    async def scenario() -> list[int]:
        queue = AnswerQueue(slots=1, max_waiting=5)
        first, second, third = queue.join(), queue.join(), queue.join()
        assert first.admitted.is_set() and not second.admitted.is_set()
        positions = [queue.position(second), queue.position(third)]
        queue.leave(first)  # the slot goes straight to the next in line
        assert second.admitted.is_set() and queue.position(third) == 1
        queue.leave(second)
        queue.leave(third)
        return positions + [queue.waiting, int(queue.busy())]

    assert asyncio.run(scenario()) == [1, 2, 0, 0]


def test_phone_gone_while_waiting_leaves_the_line_and_keeps_the_slot_count() -> None:
    async def scenario() -> None:
        queue = AnswerQueue(slots=1, max_waiting=5)
        holder, gone, behind = queue.join(), queue.join(), queue.join()
        queue.leave(gone)  # disconnected before its turn
        assert queue.position(behind) == 1 and queue.waiting == 1
        queue.leave(holder)
        assert behind.admitted.is_set()
        queue.leave(behind)
        assert not queue.busy()  # one slot, free again: nothing leaked

    asyncio.run(scenario())


def test_slot_handed_to_a_phone_that_is_gone_comes_back() -> None:
    async def scenario() -> None:
        queue = AnswerQueue(slots=1, max_waiting=5)
        holder, gone = queue.join(), queue.join()
        queue.leave(holder)  # hands over to `gone`, which never uses it
        assert gone.admitted.is_set() and queue.busy()
        queue.leave(gone)
        assert not queue.busy()

    asyncio.run(scenario())


def test_queue_turns_away_at_the_cap_and_on_a_long_predicted_wait() -> None:
    async def scenario() -> None:
        queue = AnswerQueue(slots=1, max_waiting=2, max_wait_s=60)
        holder = queue.join()
        assert not queue.full() and queue.eta_s(1) is None  # no timings yet: no estimate
        queue.join(), queue.join()
        assert queue.full()  # the cap
        queue._gaps.extend([40.0, 40.0, 40.0])  # answers finishing 40 s apart
        assert queue.eta_s(1) == 40
        queue._max_waiting = 10
        assert queue.full()  # a third place would wait ~120 s > 60 s
        queue.leave(holder)

    asyncio.run(scenario())


def test_closing_the_stream_while_waiting_gives_the_place_back(monkeypatch) -> None:
    from ruralminds import answer

    async def never_called(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("searched without a slot")

    monkeypatch.setattr(answer, "_search_text", never_called)
    monkeypatch.setattr(settings, "queue_update_s", 0.01)

    async def scenario() -> None:
        queue = AnswerQueue(slots=1, max_waiting=5)
        holder = queue.join()
        request = AskRequest("ഹാരപ്പ എന്താണ്?", "ml", "en")  # Malayalam on an English book
        stream = answer._answer_from_book(None, None, queue, request, answer.Clock())
        first = await stream.__anext__()
        assert first["event"] == "queued" and first["data"]["position"] == 1
        await stream.aclose()  # the phone went away
        assert queue.waiting == 0
        queue.leave(holder)
        assert not queue.busy()

    asyncio.run(scenario())


@pytest.mark.parametrize("language", ["en", "ml"])
def test_prompt_files_exist_with_version_line(language: str) -> None:
    from ruralminds.answer import system_prompt

    assert "NOT_IN_TEXTBOOK" in system_prompt(language)
    assert not system_prompt(language).startswith("version:")


# ---------- layer 2: each refusal cause is counted separately ----------
def _finish_with(raw_text: str, language: str = "en", debug: bool = False) -> dict:
    from ruralminds.answer import Clock, _finish
    from ruralminds.db import connect, init_schema

    conn = connect(":memory:")
    init_schema(conn)
    request = AskRequest("q", language, language, document_id=1, debug=debug)
    return _finish(conn, request, check_gate([_hit(1)]), [_hit(1)], raw_text, Clock())


@pytest.mark.parametrize(
    ("raw_text", "language", "reason"),
    [
        (SENTINEL, "en", "not_in_textbook"),
        ("The sources do not mention the boiling point of water.", "en", "admits_missing"),
        ("हड़प्पा के नगरों में ढकी हुई नालियाँ थीं और सड़कें सीधी थीं [S1].", "ml", "wrong_script"),
        ("Harappan cities had covered drains.", "en", "no_valid_citation"),
    ],
)
def test_each_refusal_cause_has_its_own_reason(raw_text: str, language: str, reason: str) -> None:
    result = _finish_with(raw_text, language)
    assert result["event"] == "refused" and result["data"]["reason"] == reason


def test_refused_text_goes_to_the_eval_never_to_phones() -> None:
    hindi = "हड़प्पा के नगरों में ढकी हुई नालियाँ थीं और सड़कें सीधी थीं [S1]."
    assert "raw_text" not in _finish_with(hindi, "ml")["data"]
    assert _finish_with(hindi, "ml", debug=True)["data"]["raw_text"] == hindi
