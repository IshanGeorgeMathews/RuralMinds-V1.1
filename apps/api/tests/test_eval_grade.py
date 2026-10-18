"""Grading helpers: judge replies parsed safely, samples cover every kind, agreement and means."""

from eval.grade import agreement, parse_scores, stratified_sample, summary


def test_parse_scores_keeps_known_in_range_values_only() -> None:
    reply = 'Here: {"correct": 2, "faithful": 5, "tone": 3, "extra": 1} thanks'
    assert parse_scores(reply) == {"correct": 2, "tone": 3}
    assert parse_scores("no json at all") == {}
    assert parse_scores("{broken json") == {}


def test_sample_takes_from_every_arm_and_style() -> None:
    rows = [{"id": f"a{n}", "arm": "ss-en", "style": "lookup"} for n in range(20)]
    rows += [{"id": f"b{n}", "arm": "ss-ml", "style": "reasoning"} for n in range(2)]
    picked = stratified_sample(rows, 4)
    assert len(picked) == 4
    assert {r["arm"] for r in picked} == {"ss-en", "ss-ml"}
    assert stratified_sample(rows, 4) == picked  # seeded


def test_agreement_and_summary() -> None:
    human = [{"id": "x", "correct": "2", "tone": "3"}, {"id": "y", "correct": "0", "tone": ""}]
    judge = [{"id": "x", "correct": "2", "tone": "2"}, {"id": "y", "correct": "0", "tone": "3"}]
    report = agreement(human, judge)
    assert report["correct"]["n"] == 2 and report["correct"]["exact_agreement"] == 1.0
    assert report["tone"]["n"] == 1  # blank human grades are skipped
    means = summary(human)
    assert means["correct"]["mean"] == 0.5  # (1.0 + 0.0) / 2 on the 0-1 scale
