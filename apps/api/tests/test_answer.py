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
def test_queue_counts_waiters_and_caps_them() -> None:
    async def scenario() -> tuple[int, bool]:
        queue = AnswerQueue(slots=1, max_waiting=1)
        await queue.__aenter__()
        waiter = asyncio.create_task(queue.__aenter__())
        await asyncio.sleep(0)
        seen = (queue.waiting, queue.full())
        await queue.__aexit__(None, None, None)
        await waiter
        await queue.__aexit__(None, None, None)
        return seen

    assert asyncio.run(scenario()) == (1, True)


@pytest.mark.parametrize("language", ["en", "ml"])
def test_prompt_files_exist_with_version_line(language: str) -> None:
    from ruralminds.answer import system_prompt

    assert "NOT_IN_TEXTBOOK" in system_prompt(language)
    assert not system_prompt(language).startswith("version:")
