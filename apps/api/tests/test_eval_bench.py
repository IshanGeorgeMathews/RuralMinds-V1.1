"""The bench's arithmetic: goodput, token rates from llama-server counters, resource windows."""

from pathlib import Path

from eval.bench import (
    QuestionDeck,
    arrival_times,
    resource_summary,
    summarise_level,
    token_rates,
)


def test_goodput_counts_fast_answers_and_fast_refusals_only() -> None:
    results = [
        {"event": "done", "ttft_s": 4.0, "total_s": 20.0, "token_events": 50},  # good
        {"event": "done", "ttft_s": 18.0, "total_s": 40.0, "token_events": 50},  # first word late
        {"event": "refused", "ttft_s": None, "total_s": 3.0, "token_events": 0},  # good
        {"event": "busy", "ttft_s": None, "total_s": 0.1, "token_events": 0},  # never good
    ]
    level = summarise_level(results, wall=60.0, slo=15.0)
    assert level["goodput"] == 0.5
    assert level["shed"] == 1 and level["goodput_admitted"] == round(2 / 3, 3)
    assert level["answers_per_min"] == 2.0
    assert level["events"] == {"busy": 1, "done": 2, "refused": 1}
    assert level["ttft_s"]["p50"] == 4.0


def test_token_rates_use_counter_differences() -> None:
    before = {"tokens_predicted_total": 100, "tokens_predicted_seconds_total": 10}
    after = {"tokens_predicted_total": 400, "tokens_predicted_seconds_total": 25}
    rates = token_rates(before, after)
    assert rates["decode_tokens_per_s"] == 20.0
    assert rates["prompt_tokens_per_s"] is None  # counter missing: --metrics off or old server


def test_resource_summary_averages_inside_the_window(tmp_path: Path) -> None:
    sheet = tmp_path / "resources.csv"
    sheet.write_text(
        "time,cpu_percent,discharge_w\n"
        "2026-10-18T19:00:00,10,5\n"
        "2026-10-18T19:00:02,30,7\n"
        "2026-10-18T19:00:04,90,\n"
        "2026-10-18T19:10:00,99,99\n",
        encoding="utf-8",
    )
    summary = resource_summary(sheet, ["2026-10-18T19:00:00", "2026-10-18T19:00:05"])
    assert summary == {"samples": 3, "cpu_percent": 43.33, "discharge_w": 6.0}


def test_deck_never_repeats_until_empty_then_counts_repeats() -> None:
    deck = QuestionDeck([{"question": f"q{n}"} for n in range(5)])
    drawn = [deck.draw()["question"] for _ in range(5)]
    assert sorted(drawn) == [f"q{n}" for n in range(5)] and deck.repeats == 0
    deck.draw()
    assert deck.repeats == 1
    again = QuestionDeck([{"question": f"q{n}"} for n in range(5)])
    assert [again.draw()["question"] for _ in range(5)] == drawn  # seeded order


def test_open_loop_arrivals_are_seeded_and_near_the_rate() -> None:
    times = arrival_times(rate_per_min=4, duration_s=3600, seed="t")
    assert times == arrival_times(4, 3600, "t")
    assert all(0 <= t < 3600 for t in times) and times == sorted(times)
    assert 200 <= len(times) <= 280  # 240 expected in an hour at 4 per minute
