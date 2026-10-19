"""Grading helpers: judge replies parsed safely, samples cover every kind, agreement and means."""

from eval.grade import (
    agreement,
    calibration_half,
    grade_value,
    judged_row,
    parse_scores,
    read_sheet,
    stratified_sample,
    summary,
)


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


def test_unparsed_judge_reply_never_keeps_the_human_grade() -> None:
    human_row = {"id": "x", "question": "q", "correct": "2", "flawed": "1", "tone": "3"}
    judged = judged_row(human_row, "sorry, I cannot grade this")
    assert judged["correct"] == "" and judged["flawed"] == "" and judged["tone"] == ""
    judged = judged_row(human_row, '{"correct": 1}')
    assert judged["correct"] == "1" and judged["flawed"] == ""
    assert human_row["correct"] == "2"  # the human sheet is not modified


def test_human_sheet_layout_is_read(tmp_path) -> None:
    sheet = tmp_path / "human.csv"
    sheet.write_text("id,relevant,mistakes_found,Note\nx,0,1,off topic\n", encoding="utf-8-sig")
    row = read_sheet(sheet)[0]
    assert row["flawed"] == "1"  # the grader's flag column
    assert grade_value(row["relevant"], [1, 2, 3]) == 1  # out of range: clamped
    assert grade_value("", [1, 2, 3]) is None


def test_judge_usable_needs_every_gate_criterion() -> None:
    human = [
        {"id": str(n), "correct": str(n % 3), "faithful": "2", "flawed": str(n % 2)}
        for n in range(6)
    ]
    report = agreement(human, [dict(row) for row in human])
    assert report["correct"]["passes"] and report["flawed"]["passes"]
    assert report["judge_usable"]["usable"]
    report = agreement(human, [{**row, "flawed": str(1 - int(row["flawed"]))} for row in human])
    assert not report["judge_usable"]["usable"]


def test_reasoning_judge_reply_uses_the_final_verdict() -> None:
    reply = '<think>format is {"correct": 0}</think>Example {"correct": 1}. Verdict: {"correct": 2}'
    assert parse_scores(reply) == {"correct": 2}


def test_calibration_halves_are_stable_and_both_used() -> None:
    ids = [f"item-{n}" for n in range(40)]
    halves = [calibration_half(i) for i in ids]
    assert set(halves) == {"select", "confirm"}
    assert halves == [calibration_half(i) for i in ids]
