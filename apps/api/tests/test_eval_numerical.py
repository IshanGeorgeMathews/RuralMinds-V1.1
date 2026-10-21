import pytest

from eval import numerical as bench


def g(value: str, unit: str = "") -> dict:
    return {"value": value, "unit": unit}


@pytest.mark.parametrize(
    ("answers", "gold", "right"),
    [
        ([("5", "m/s^2")], [g("5", "m/s^2")], True),
        ([("20", "m/s")], [g("72", "km/h")], True),  # same speed, other unit
        ([("5", "m/s")], [g("5", "m/s^2")], False),  # wrong unit is a wrong answer
        ([("1/10000", "m^3")], [g("0.0001", "m^3")], True),  # SymPy's exact form
        ([("4", "s"), ("3", "s")], [g("3", "s"), g("4", "s")], True),  # order does not matter
        ([("3", "s")], [g("3", "s"), g("4", "s")], False),  # one value missing
        ([("3", "s"), ("4", "s"), ("7", "s")], [g("3", "s"), g("4", "s")], False),  # extra value
        ([("27", "metres"), ("13", "metres")], [g("27"), g("13")], True),  # maths gold: numbers
        ([("10", "rupees")], [g("10")], True),  # a label unit is dropped
        ([("4.9", "m/s")], [g("5", "m/s")], False),
    ],
)
def test_answers_are_compared_with_gold_by_value_and_unit(answers, gold, right) -> None:
    assert bench.matches(answers, gold, bench.TOLERANCE["solve"]) is right


def test_the_model_alone_may_round_a_little() -> None:
    assert bench.matches([("7.33", "")], [g("22/3")], bench.TOLERANCE["alone"])
    assert not bench.matches([("7.3", "")], [g("22/3")], bench.TOLERANCE["alone"])


@pytest.mark.parametrize(
    ("text", "answers"),
    [
        ("a = 40/8\nFINAL: 5 m/s^2", [("5", "m/s^2")]),
        ("…\nFINAL: t1 = 3 s, t2 = 4 s.", [("3", "s"), ("4", "s")]),
        ("FINAL: 9, 11, 13", [("9", ""), ("11", ""), ("13", "")]),
        ("FINAL: 2 m/s²", [("2", "m/s²")]),
        ("FINAL: none", None),
        # Seen in the 21 Oct run: LaTeX, a sentence, a thousands comma.
        ("FINAL: Volume = $0.0001 \\, \\text{m}^3$", [("0.0001", "m^3")]),
        ("FINAL: Cyclist Q takes less time (15 s vs 20 s)", [("15", "s"), ("20", "s")]),
        ("FINAL: 60,650 m", [("60650", "m")]),
        ("The answer is 5.", None),  # no FINAL line: not scored as right
    ],
)
def test_final_line_of_the_model_alone(text: str, answers) -> None:
    assert bench.final_answers(text) == answers


def test_extra_numbers_are_allowed_only_for_the_model_alone() -> None:
    said = bench.final_answers("FINAL: Car 1 arrives first: 3 s vs 4 s")
    gold = [g("3", "s"), g("4", "s")]
    assert bench.matches(said, gold, bench.TOLERANCE["alone"], allow_extra=True)
    assert not bench.matches(said, gold, bench.TOLERANCE["solve"])


def test_a_stopped_run_resumes_from_its_checkpoint(tmp_path, monkeypatch) -> None:
    import asyncio

    items = [
        {"id": "a", "split": "dev", "arms": ["alone"], "expected": "solve", "gold": [g("4")]},
        {"id": "b", "split": "dev", "arms": ["alone"], "expected": "solve", "gold": [g("6")]},
    ]
    asked: list[str] = []

    async def fake_run_alone(client, item):
        asked.append(item.get("id", "warm-up"))
        return {"arm": "alone", "outcome": "right", "answers": [], "text": "", "total_s": 0.1}

    async def quiet(client):
        return None

    class Props:
        def json(self):
            return {"model_path": "m"}

    async def fake_get(self, url):
        return Props()

    async def no_worker():
        return None

    monkeypatch.setattr(bench, "load_items", lambda: items)
    monkeypatch.setattr(bench, "checkpoint", lambda label, split: tmp_path / "run.partial.jsonl")
    monkeypatch.setattr(bench, "run_alone", fake_run_alone)
    monkeypatch.setattr(bench, "require_quiet", quiet)
    monkeypatch.setattr(bench.httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(bench.numerical.mathcheck, "start", no_worker)
    monkeypatch.setattr(bench, "connect", lambda path: None)
    (tmp_path / "run.partial.jsonl").write_text(
        '{"id": "a", "arm": "alone", "outcome": "right", "expected": "solve"}\n', encoding="utf-8"
    )
    report = asyncio.run(bench.run("dev", "t", {"alone"}, minutes=0))
    assert asked == ["warm-up", "b"]  # "a" was already in the checkpoint
    assert report["resumed"] and report["summary"]["alone"]["right"]["hits"] == 2


def test_superscript_units_from_the_model_are_read() -> None:
    assert bench.matches([("2", "m/s²")], [g("2", "m/s^2")], bench.TOLERANCE["alone"])


@pytest.mark.parametrize(
    ("event", "data", "answers", "outcome"),
    [
        ("done", {"math_status": "solved"}, [("5", "m/s^2")], "checked_right"),
        ("done", {"math_status": "solved"}, [("6", "m/s^2")], "checked_wrong"),
        ("done", {"unsolved": True, "math_status": "parse_error"}, [], "unsolved"),
        ("done", {"math_status": "not_numerical"}, [], "answered_plain"),
        ("refused", {"reason": "no_valid_citation"}, [], "refused"),
        ("error", {}, [], "error"),
    ],
)
def test_solve_outcomes(event, data, answers, outcome) -> None:
    item = {"gold": [g("5", "m/s^2")]}
    assert bench.solve_outcome(event, data, answers, item) == outcome


def test_split_is_seeded_and_tuned_items_stay_in_dev() -> None:
    assert bench.split_of({"id": "num-b01", "forced_split": "dev"}) == "dev"
    first = [bench.split_of({"id": f"num-z{n:02}"}) for n in range(40)]
    assert first == [bench.split_of({"id": f"num-z{n:02}"}) for n in range(40)]
    assert 0 < first.count("dev") < 40


def test_item_file_is_well_formed() -> None:
    items = bench.load_items()
    assert len({item["id"] for item in items}) == len(items)
    for item in items:
        assert set(item["arms"]) <= {"solve", "setup", "alone"}
        assert item["expected"] in ("solve", "explain")
        if item["expected"] == "solve":
            assert item["gold"] and all(
                bench.quantity(x["value"], x["unit"]) is not None for x in item["gold"]
            )
        if "solve" in item["arms"]:
            assert item.get("book_id")


def test_a_whole_number_must_be_exact_but_decimals_may_round() -> None:
    # Audit, 21 Oct: "3999 m" for 4000 m had been scored right by the rounding tolerance.
    assert not bench.matches([("3999", "m")], [g("4000", "m")], bench.TOLERANCE["alone"])
    assert bench.matches([("7.33", "m")], [g("22/3", "m")], bench.TOLERANCE["alone"])


def test_a_comparison_is_right_when_the_right_choice_is_named() -> None:
    item = {
        "gold": [g("3", "s"), g("4", "s")],
        "gold_choice": {"right": r"\bcar\s*1\b", "wrong": r"\bcar\s*2\b"},
    }
    assert bench.alone_outcome("…\nFINAL: Car 1 reaches first", item) == "right"
    assert bench.alone_outcome("…\nFINAL: Car 2 reaches first", item) == "wrong"
    assert bench.alone_outcome("…\nFINAL: Car 1 or car 2, both", item) != "right"
    assert bench.alone_outcome("…\nFINAL: 3 s and 4 s", item) == "right"
