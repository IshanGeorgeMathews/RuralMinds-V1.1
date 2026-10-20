import asyncio

import pytest

from ruralminds import answer, mathcheck, numerical
from ruralminds.answer import AskRequest, Clock, check_gate
from ruralminds.db import connect, init_schema
from ruralminds.mathcheck import Limits, Problem
from ruralminds.retrieve import RetrievedChunk

LIMITS = Limits(max_chars=200, max_digits=12, max_exponent=10, max_degree=3, max_unknowns=4)
QUESTION = "What is the acceleration of a car which started from rest and reached 40 m/s in 8 s?"
SETUP_REPLY = """KIND: numeric
UNKNOWNS: a
KNOWN: u = 0 m/s
KNOWN: v = 40 m/s
KNOWN: t = 8 s
EQUATION: a = (v - u) / t
ASKED: a
UNIT: m/s^2
"""
LINES = ("a = (v - u)/t", "a = (40 - 0)/8", "a = 5 m/s²")


def explain_reply(idea: str = "**Acceleration** is the change in velocity per second [S1].") -> str:
    return (
        f"IDEA: {idea}\n"
        "1. a = (v - u)/t\nWe write the rule for acceleration.\n"
        "2. a = (40 - 0)/8\nThe car starts from rest, so u is 0.\n"
        "3. a = 5 m/s²\nWe divide to get the acceleration.\n"
        "TRY: A cycle reaches 6 m/s from rest in 3 s. What is its acceleration?"
    )


def test_parse_setup_reads_the_lines() -> None:
    problem = numerical.parse_setup(SETUP_REPLY)
    assert problem == Problem(
        unknowns=("a",),
        equations=("a = (v - u) / t",),
        knowns=(("u", "0 m/s"), ("v", "40 m/s"), ("t", "8 s")),
        asked=("a",),
        answer_unit="m/s^2",
    )
    assert numerical.parse_setup("KIND: not_numerical") is None
    with pytest.raises(numerical.SetupError):
        numerical.parse_setup("KIND: algebraic\nUNKNOWNS: x\n")


def test_explain_grammar_fixes_each_working_line_as_text() -> None:
    grammar = numerical.explain_grammar(('x = "odd" \\ 2', "x = 9"))
    assert '"1. x = \\"odd\\" \\\\ 2" "\\n" sentence' in grammar  # quotes and \ escaped
    assert '"2. x = 9" "\\n" sentence' in grammar
    assert "[^\\n$\\\\]" in grammar  # no LaTeX in sentences


def test_sentences_with_numbers_from_nowhere_are_dropped() -> None:
    reply = explain_reply().replace("We divide to get", "We divide 40 by 8 to get 6, so")
    card = numerical.read_explanation(reply, QUESTION, LINES)
    assert [step["line"] for step in card.steps] == list(LINES)
    assert card.steps[1]["why"] == "The car starts from rest, so u is 0."
    assert card.steps[2]["why"] == ""  # "6" is in neither the question nor the working
    assert card.dropped == 1
    assert card.try_problem.startswith("A cycle")  # new numbers are allowed only here


def test_marker_numbers_do_not_count_as_calculations() -> None:
    card = numerical.read_explanation(explain_reply(), QUESTION, LINES)
    assert card.idea.endswith("[S1].") and card.dropped == 0


def _hit() -> RetrievedChunk:
    return RetrievedChunk(1, "sci8", "en", 9, "Motion", 129, 129, "Acceleration = (v - u)/t", 20)


def _run_solve(monkeypatch, setup_reply: str, explain: str, language: str = "en") -> list[dict]:
    calls: list[str] = []

    async def fake_complete(messages, client, max_tokens, grammar=None):
        calls.append("setup")
        return setup_reply

    async def fake_stream(messages, client, max_tokens=None, grammar=None):
        calls.append("explain" if grammar else "tutor")
        for piece in (explain[:10], explain[10:]):
            yield piece

    async def in_process(problem):  # the worker process is tested in test_mathcheck
        return mathcheck.solve_problem(problem, LIMITS)

    monkeypatch.setattr(numerical, "complete", fake_complete)
    monkeypatch.setattr(answer, "chat_stream", fake_stream)
    monkeypatch.setattr(numerical.mathcheck, "solve", in_process)
    conn = connect(":memory:")
    init_schema(conn)
    request = AskRequest(QUESTION, language, "en", subject="science", document_id=1, mode="solve")

    async def collect() -> list[dict]:
        stream = answer._solve(conn, None, request, check_gate([_hit()]), [_hit()], Clock())
        return [item async for item in stream]

    events = asyncio.run(collect())
    events[-1]["calls"] = calls
    return events


def test_solved_problem_becomes_a_checked_card(monkeypatch) -> None:
    events = _run_solve(monkeypatch, SETUP_REPLY, explain_reply())
    final = events[-1]
    assert [e["event"] for e in events[:-1]] == ["progress", "token", "token"]
    assert final["event"] == "done" and final["calls"] == ["setup", "explain"]
    data = final["data"]
    assert data["math_status"] == "solved"
    assert data["card"]["answers"] == ["5 m/s²"]
    assert [step["line"] for step in data["card"]["steps"]] == list(LINES)
    assert data["math"]["answers"] == [{"asked": "a", "exact": "5", "unit": "m/s^2"}]
    assert data["citations"][0]["page_start"] == 129
    assert "**Answer: 5 m/s²**" in data["text"]


@pytest.mark.parametrize(
    ("setup_reply", "language", "status", "calls"),
    [
        ("KIND: not_numerical", "en", "not_numerical", ["setup", "tutor"]),
        ("KIND: algebraic\nUNKNOWNS: x\n", "en", "setup_unreadable", ["setup", "tutor"]),
        (  # x + y = 10 with two unknowns: no single answer to show
            "KIND: algebraic\nUNKNOWNS: x, y\nEQUATION: x + y = 10\nASKED: x, y\nUNIT:\n",
            "en",
            "many_solutions",
            ["setup", "tutor"],
        ),
        (SETUP_REPLY, "ml", "language_not_supported", ["tutor"]),
    ],
)
def test_anything_unsolved_falls_back_to_the_method_without_a_number(
    monkeypatch, setup_reply: str, language: str, status: str, calls: list[str]
) -> None:
    tutor_answer = (
        "പ്രവേഗത്തിലെ മാറ്റത്തെ സമയം കൊണ്ട് ഹരിക്കുക [S1]."  # the language check still applies
        if language == "ml"
        else "Divide the change in velocity by the time [S1]."
    )
    events = _run_solve(monkeypatch, setup_reply, tutor_answer, language)
    final = events[-1]
    assert final["event"] == "done" and final["calls"] == calls
    assert final["data"]["math_status"] == status
    assert "card" not in final["data"]
    # Not streamed: only progress steps before the checked answer, so nothing is ever erased.
    steps = [e["data"]["step"] for e in events[:-1]]
    assert steps == (["method"] if language == "ml" else ["solving", "method"])


def test_unchecked_method_answer_is_refused_without_showing_any_text(monkeypatch) -> None:
    events = _run_solve(monkeypatch, "KIND: not_numerical", "Divide distance by time.")
    assert [e["event"] for e in events] == ["progress", "progress", "refused"]


def test_names_used_in_equations_become_unknowns() -> None:
    setup = (
        "KIND: numeric\nUNKNOWNS: d\nKNOWN: v1 = 20 m/s\nKNOWN: t1 = 30 s\nKNOWN: t2 = 20 s\n"
        "EQUATION: d1 = v1 / 2 * t1\nEQUATION: d2 = 3x + v1 * t2\nEQUATION: d = d1 + d2\n"
        "ASKED: d\nUNIT: m\n"
    )
    problem = numerical.parse_setup(setup)
    # d1, d2 were never declared; "3x" is 3 times x, so x is a name too (and v1, t1 are given).
    assert problem.unknowns == ("d", "d1", "d2", "x")


def test_declared_unknowns_that_no_equation_uses_are_dropped() -> None:
    # The user's 3-part journey (20 Oct): "d4, d5" declared and never used left free unknowns.
    setup = (
        "KIND: numeric\nUNKNOWNS: d1, d2, d3, d4, d5\nKNOWN: u = 0 m/s\nKNOWN: v1 = 20 m/s\n"
        "KNOWN: t1 = 5 s\nKNOWN: v2 = 100 m/s\nKNOWN: t2 = 10 s\nKNOWN: v3 = 0 m/s\n"
        "KNOWN: t3 = 20 minutes\nEQUATION: d1 = (u + v1) / 2 * t1\n"
        "EQUATION: d2 = (v1 + v2) / 2 * t2\nEQUATION: d3 = (v2 + v3) / 2 * t3\n"
        "EQUATION: d = d1 + d2 + d3\nASKED: d\nUNIT: m\n"
    )
    problem = numerical.parse_setup(setup)
    assert problem.unknowns == ("d1", "d2", "d3", "d")
    solution = mathcheck.solve_problem(problem, LIMITS)
    assert [a.display for a in solution.solutions[0]] == ["60650 m"]  # 50 + 600 + 60000


def test_setup_grammar_keeps_comments_out_of_equations() -> None:
    assert "[A-Za-z0-9_ +*/^().=-]{1,120}" in numerical.SETUP_GRAMMAR


def test_several_answers_are_named(monkeypatch) -> None:
    setup = (
        "KIND: algebraic\nUNKNOWNS: l, b\nEQUATION: 2l + 2b = 80\nEQUATION: l = 2b + 1\n"
        "ASKED: l, b\nUNIT: m\n"
    )
    explain = (
        "IDEA: The **perimeter** is twice length plus breadth [S1].\n"
        "1. 2l + 2b = 80\nThe perimeter rule.\n2. l = 2b + 1\nThe length rule.\n"
        "3. l = 27 m, b = 13 m\nSolving both together.\nTRY: Another rectangle."
    )
    data = _run_solve(monkeypatch, setup, explain)[-1]["data"]
    assert data["card"]["answers"] == ["l = 27 m", "b = 13 m"]


def test_solved_answer_without_a_citation_is_refused(monkeypatch) -> None:
    final = _run_solve(monkeypatch, SETUP_REPLY, explain_reply(idea="Acceleration is speed."))[-1]
    assert final["event"] == "refused" and final["data"]["reason"] == "no_valid_citation"
