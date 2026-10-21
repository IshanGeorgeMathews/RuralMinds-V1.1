"""The "Solve step by step" chip: the model sets a problem up, SymPy solves it, the model explains.

    setup call (grammar: KIND / UNKNOWNS / KNOWN / EQUATION / ASKED / UNIT lines)
    -> mathcheck solves and writes the worked lines -> explain call (grammar: every worked line
    is fixed text, the model adds one sentence under each) -> number check -> answer card

A 2B model drops brackets and invents arithmetic when asked to copy working (prompt trial,
20 Oct), so it never writes a maths line: the grammar inserts SymPy's lines as fixed text.
Anything that does not solve cleanly falls back to a method explanation with no final number.
"""

import re
from dataclasses import dataclass, field

import httpx

from . import mathcheck
from .llm import complete
from .mathcheck import Limits, Problem, Solution
from .retrieve import RetrievedChunk
from .tutor import load_prompt

SETUP_PROMPT = "maths_setup_v3"
EXPLAIN_PROMPT = "system_v3_numerical"
# A journey in three parts needs ~10 KNOWN lines and 4 equations: 120 tokens cut such a setup
# off mid-equation (user test, 20 Oct).
SETUP_MAX_TOKENS = 220
EXPLAIN_MAX_TOKENS = 400  # the forced working lines count too

# KNOWN holds only a number and a unit, so "b = p + 4" must be written as an EQUATION, and an
# equation holds only the characters the maths parser reads (the model once wrote a "(Note: …)").
SETUP_GRAMMAR = r"""
root ::= "KIND: not_numerical" | "KIND: " kind "\n" "UNKNOWNS: " names "\n" known{0,10} equation{1,6} "ASKED: " text "\n" "UNIT:" (" " unit)? "\n"
kind ::= "numeric" | "algebraic"
names ::= name (", " name){0,5}
name ::= [A-Za-z] [A-Za-z0-9_]{0,7}
known ::= "KNOWN: " name " = " "-"? [0-9]{1,12} ("." [0-9]{1,6})? (" " unit)? "\n"
unit ::= [A-Za-z] [A-Za-z/^0-9]{0,11}
equation ::= "EQUATION: " [A-Za-z0-9_ +*/^().=-]{1,120} "\n"
text ::= [^\n]{1,60}
"""
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
# Names as mathcheck's parser reads them: "3x" is 3 times x, "x2" is one name.
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_MARKERS = re.compile(r"\[[^\]]*\]")


class SetupError(ValueError):
    """The setup reply could not be read (the grammar makes this rare)."""


@dataclass(frozen=True)
class Setup:
    # solved | not_numerical | setup_unreadable | a mathcheck status (no_solution, timeout, ...)
    status: str
    problem: Problem | None = None
    solution: Solution | None = None
    lines: tuple[str, ...] = ()


@dataclass
class Card:
    idea: str
    steps: list[dict[str, str]]  # {"line": SymPy's line, "why": the model's sentence}
    try_problem: str
    dropped: int = 0  # sentences removed because they held a number from nowhere
    answers: list[str] = field(default_factory=list)


def parse_setup(raw: str) -> Problem | None:
    """The setup lines as a Problem; None when the model says there is nothing to calculate."""
    fields: dict[str, list[str]] = {}
    for line in raw.strip().splitlines():
        key, colon, value = line.partition(":")
        if colon:
            fields.setdefault(key.strip(), []).append(value.strip())
    if fields.get("KIND", [""])[0] == "not_numerical":
        return None
    if not fields.get("UNKNOWNS") or not fields.get("EQUATION") or not fields.get("ASKED"):
        raise SetupError(f"missing lines in {raw!r}")
    knowns = []
    for known in fields.get("KNOWN", []):
        name, equals, value = known.partition("=")
        if not equals:
            raise SetupError(f"bad KNOWN line {known!r}")
        knowns.append((name.strip(), value.strip()))
    equations = tuple(fields["EQUATION"])
    return Problem(
        unknowns=_unknowns_in_use(_split(fields["UNKNOWNS"][0]), equations, knowns),
        equations=equations,
        knowns=tuple(knowns),
        asked=_split(fields["ASKED"][0]),
        answer_unit=fields.get("UNIT", [""])[0],
    )


def _split(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.split(",") if part.strip())


def _unknowns_in_use(
    declared: tuple[str, ...], equations: tuple[str, ...], knowns: list[tuple[str, str]]
) -> tuple[str, ...]:
    """The unknowns are the names the equations use that are not given, declared or not.
    The model writes "d = d1 + d2" with only d1, d2 declared, and declares names it never uses
    ("d4, d5"), which would leave free unknowns and no answer (user test, 20 Oct). A stray word
    in an equation (a unit) still becomes an unknown and leaves it unsolved: a safe failure."""
    given = {name for name, _ in knowns} | set(mathcheck.FUNCTIONS)
    used = dict.fromkeys(
        name for equation in equations for name in _NAME.findall(equation) if name not in given
    )
    return tuple(name for name in declared if name in used) + tuple(
        name for name in used if name not in declared
    )


def working_lines(problem: Problem, solution: Solution) -> tuple[str, ...]:
    """SymPy's worked lines; for several equations, the equations and then the answers."""
    if solution.steps:
        return solution.steps
    answers = ", ".join(f"{answer.asked} = {answer.display}" for answer in solution.solutions[0])
    return (*problem.equations, answers)


async def set_up(client: httpx.AsyncClient, question: str) -> Setup:
    """One short model call, then SymPy. Every failure is a status the caller falls back on."""
    messages = [
        {"role": "system", "content": load_prompt(SETUP_PROMPT)},
        {"role": "user", "content": f"Problem: {question}"},
    ]
    raw = await complete(messages, client, SETUP_MAX_TOKENS, grammar=SETUP_GRAMMAR)
    try:
        problem = parse_setup(raw)
    except SetupError:
        return Setup("setup_unreadable")
    if problem is None:
        return Setup("not_numerical")
    limits = Limits.from_settings()
    unit = mathcheck.answer_unit_for(problem.answer_unit, question, limits)
    problem = Problem(problem.unknowns, problem.equations, problem.knowns, problem.asked, unit)
    solution = await mathcheck.solve(problem)
    # Two answers (a quadratic) are not shown as one checked result yet.
    if solution.status != "solved" or len(solution.solutions) != 1:
        status = solution.status if solution.status != "solved" else "several_answers"
        return Setup(status, problem, solution)
    return Setup("solved", problem, solution, working_lines(problem, solution))


def _gbnf_literal(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def explain_grammar(lines: tuple[str, ...]) -> str:
    """Each worked line is fixed text in the reply: the model reads it but cannot change it."""
    steps = " ".join(
        f'{_gbnf_literal(f"{n}. {line}")} "\\n" sentence "\\n"' for n, line in enumerate(lines, 1)
    )
    # No $ or \ in sentences: the model once wrote LaTeX, which a phone shows raw.
    return (
        f'root ::= "IDEA: " sentence "\\n" {steps} "TRY: " sentence\n'
        "sentence ::= [^\\n$\\\\]{1,300}\n"
    )


def explain_messages(
    question: str, sources: list[RetrievedChunk], lines: tuple[str, ...], language: str
) -> list[dict[str, str]]:
    numbered = "\n\n".join(f"[S{n}] {hit.text}" for n, hit in enumerate(sources, start=1))
    working = "\n".join(f"{n}. {line}" for n, line in enumerate(lines, 1))
    return [
        {"role": "system", "content": load_prompt(f"{EXPLAIN_PROMPT}_{language}")},
        {
            "role": "user",
            "content": f"Sources:\n{numbered}\n\nQuestion: {question}\nChecked working:\n{working}",
        },
    ]


def _numbers(text: str) -> set[str]:
    return {number.rstrip("0").rstrip(".") if "." in number else number
            for number in _NUMBER.findall(_MARKERS.sub("", text))}  # fmt: skip


def read_explanation(raw: str, question: str, lines: tuple[str, ...]) -> Card:
    """The model's sentences beside SymPy's lines. A sentence with a number that is in neither
    the question nor the working is the model calculating on its own: it is removed."""
    allowed = _numbers(question) | set().union(*(_numbers(line) for line in lines))
    reply = raw.splitlines()
    card = Card(idea="", steps=[], try_problem="")

    def keep(sentence: str) -> str:
        if _numbers(sentence) <= allowed:
            return sentence.strip()
        card.dropped += 1
        return ""

    for row in reply:
        if row.startswith("IDEA:"):
            card.idea = keep(row.removeprefix("IDEA:"))
        elif row.startswith("TRY:"):  # a new problem: its numbers are new on purpose
            card.try_problem = row.removeprefix("TRY:").strip()
    for n, line in enumerate(lines, 1):
        at = reply.index(f"{n}. {line}") if f"{n}. {line}" in reply else -1
        why = reply[at + 1] if 0 <= at < len(reply) - 1 else ""
        card.steps.append({"line": line, "why": keep(why)})
    return card


def card_text(card: Card) -> str:
    """Plain-text form of the card: shown by older screens and kept as chat history."""
    steps = "\n".join(
        f"{n}. {step['why']}\n   {step['line']}".rstrip() for n, step in enumerate(card.steps, 1)
    )
    answers = ", ".join(card.answers)
    return f"{card.idea}\n\n{steps}\n\n**Answer: {answers}**".strip()
