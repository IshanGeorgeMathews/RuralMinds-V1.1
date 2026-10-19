"""The eval's metric definitions: each one checked against a hand-worked example."""

import pytest

from eval.metrics import (
    cohen_kappa,
    hit_at,
    mean_with_ci,
    ndcg_at,
    percentile,
    recall_at,
    reciprocal_rank,
    refusal_report,
    wilson_interval,
)


def test_wilson_interval_for_eight_out_of_eight_is_wide() -> None:
    low, high = wilson_interval(8, 8)
    assert low == pytest.approx(0.676, abs=0.001)
    assert high == 1.0


def test_wilson_interval_matches_textbook_value() -> None:
    # 81/263: the worked example in Wilson (1927) / Newcombe (1998), 0.2553 to 0.3662
    low, high = wilson_interval(81, 263)
    assert low == pytest.approx(0.255, abs=0.001)
    assert high == pytest.approx(0.366, abs=0.001)


def test_wilson_interval_empty_is_none() -> None:
    assert wilson_interval(0, 0) is None


def test_bootstrap_interval_stays_inside_the_data_range() -> None:
    scores = [1.0] * 6 + [0.5, 0.0]
    result = mean_with_ci(scores)
    low, high = result["ci95"]
    assert 0.0 <= low < result["mean"] < high <= 1.0
    assert mean_with_ci(scores) == result  # seeded: same interval every run


def test_percentile_is_nearest_rank() -> None:
    values = [1, 2, 3, 4, 5, 6, 7, 8]
    assert percentile(values, 0.5) == 4  # not 5: the old int(p*n) index overshot
    assert percentile(values, 0.95) == 8
    assert percentile([], 0.5) is None


RANKED = [(20, 21), (8, 8), (11, 12), (8, 9), (30, 30)]


def test_hit_and_reciprocal_rank_use_first_covering_chunk() -> None:
    assert not hit_at([8], RANKED, 1)
    assert hit_at([8], RANKED, 3)
    assert reciprocal_rank([8], RANKED) == 0.5
    assert reciprocal_rank([99], RANKED) == 0.0


def test_recall_counts_each_gold_page_once() -> None:
    # Pages 8 and 9: chunk 2 covers 8, chunk 4 covers 8 again and 9.
    assert recall_at([8, 9], RANKED, 3) == 0.5
    assert recall_at([8, 9], RANKED, 5) == 1.0


def test_ndcg_perfect_and_partial() -> None:
    assert ndcg_at([20], RANKED, 5) == pytest.approx(1.0)
    assert ndcg_at([8], RANKED, 5) == pytest.approx(1 / 1.5849625, abs=1e-6)  # rank 2
    assert ndcg_at([99], RANKED, 5) == 0.0


def test_refusal_report_counts_both_error_types() -> None:
    pairs = [(False, True), (False, True), (False, False), (True, True), (True, False)]
    report = refusal_report(pairs)
    assert report["counts"] == {
        "true_refusals": 2,
        "false_refusals": 1,
        "missed_refusals": 1,
        "answered_ok": 1,
    }
    assert report["precision"]["rate"] == pytest.approx(0.667, abs=0.001)
    assert report["recall"]["rate"] == pytest.approx(0.667, abs=0.001)
    assert report["false_refusal_rate"]["rate"] == 0.5


def test_cohen_kappa() -> None:
    assert cohen_kappa([1, 1, 0, 0], [1, 1, 0, 0]) == 1.0
    assert cohen_kappa([1, 0, 1, 0], [0, 1, 0, 1]) == -1.0
    # 20 items, 16 agreements, both say "y" half the time: (0.8 - 0.5) / (1 - 0.5) = 0.6
    first = ["y"] * 10 + ["n"] * 10
    second = ["y"] * 8 + ["n"] * 2 + ["y"] * 2 + ["n"] * 8
    assert cohen_kappa(first, second) == pytest.approx(0.6)


def test_notes_answer_counts_as_answered_with_point_citations() -> None:
    from eval.run import score

    item = {
        "id": "k1",
        "lang": "en",
        "question": "must-learn concepts in chapter 2?",
        "answerable": True,
        "gold_pages": [26],
        "expected_mode": ["notes", "concepts"],
        "expected_chapter": 2,
    }
    notes = {
        "event": "notes",
        "data": {
            "chapter_no": 2,
            "points": [{"text": "burnt bricks", "page_start": 26, "page_end": 26}],
        },
    }
    result = score(item, notes, ttft=None, total=0.1)
    assert not result["refused"] and result["refusal_correct"]
    assert result["citation_supported"] and result["intent_correct"] and result["chapter_correct"]


def test_wrong_mode_and_chapter_are_scored() -> None:
    from eval.run import score

    item = {
        "id": "k2",
        "lang": "en",
        "question": "key points of the Motion chapter",
        "answerable": True,
        "gold_pages": [118],
        "expected_mode": "notes",
        "expected_chapter": 9,
    }
    done = {
        "event": "done",
        "data": {
            "mode": "explain",
            "citations": [{"chapter_no": 10, "page_start": 136, "page_end": 136}],
        },
    }
    result = score(item, done, ttft=1.0, total=2.0)
    assert result["intent_correct"] is False and result["chapter_correct"] is False


def test_weighted_kappa_penalises_far_disagreements_more() -> None:
    from eval.metrics import weighted_kappa

    assert weighted_kappa([1, 2, 3, 3], [1, 2, 3, 3], [1, 2, 3]) == 1.0
    near = weighted_kappa([1, 2, 3, 2, 1, 3], [1, 2, 3, 3, 2, 3], [1, 2, 3])
    far = weighted_kappa([1, 2, 3, 2, 1, 3], [1, 2, 3, 3, 3, 3], [1, 2, 3])
    assert near > far
    # Hand-worked: scores (1,1),(2,3),(3,3): observed weighted disagreement 0.25 over 3 items;
    # chance = sum w_ij * row_i * col_j / n = (2 + 0.75 + 1) / 3 = 1.25
    # -> kappa = 1 - 0.25 / 1.25 = 0.8
    assert weighted_kappa([1, 2, 3], [1, 3, 3], [1, 2, 3]) == 0.8


def test_third_script_is_scored_on_shown_answers_only() -> None:
    from eval.run import score

    item = {"id": "s1", "lang": "ml", "question": "q", "answerable": True, "gold_pages": [59]}
    shown = {"event": "done", "data": {"text": "രണ്ട് സഭകൾ 구성 ചെയ്യുന്നു", "citations": []}}
    assert score(item, shown, ttft=1.0, total=2.0)["third_script"] is True
    clean = {"event": "done", "data": {"text": "രണ്ട് സഭകൾ (Lok Sabha)", "citations": []}}
    assert score(item, clean, ttft=1.0, total=2.0)["third_script"] is False
    refused = {"event": "refused", "data": {"reason": "gate"}}
    assert "third_script" not in score(item, refused, ttft=None, total=1.0)
