"""The second opinion behind the "✓ checked" badge on a solved problem.

SymPy's arithmetic is exact, but it solves whatever equations the setup call wrote, and a wrong
setup gets a ✓ too: on 21 Oct "90 km/h in m/s" was converted twice (6.94 m/s instead of 25).
So the same model also solves the problem on its own, ending with a FINAL line, and the answer
is shown only when the two agree. Agreement is judged here, and the bench (eval/numerical.py)
uses the same functions to score answers against gold, so both read numbers the same way.
On the 21 Oct runs, replayed offline, this rule removed both wrong ✓ and kept every right one on
test; on dev it removed one right ✓ (a long journey the model alone got slightly wrong).
"""

import re

import httpx
import sympy
from sympy.physics.units import Quantity, convert_to

from . import mathcheck
from .llm import complete
from .tutor import load_prompt

CHECK_PROMPT = "maths_check_v1"
# At 400 tokens a three-part journey ran out before its FINAL line (bench, 21 Oct).
CHECK_MAX_TOKENS = 800
EXACT = 1e-9
ROUNDING = 1e-3  # the model rounds ("7.33" for 22/3); SymPy never does
# Wider than the app's caps: gold answers and the model's FINAL lines are read, not solved.
LIMITS = mathcheck.Limits(
    max_chars=200, max_digits=15, max_exponent=10, max_degree=3, max_unknowns=6
)
_FINAL = re.compile(r"FINAL:\s*(.*)", re.IGNORECASE)
# A number not inside a name ("t1") or a power ("m^2"), and the unit word right after it.
_VALUE = re.compile(r"(?<![\w.^])(-?\d+(?:\.\d+)?)(?:\s*([A-Za-z°][A-Za-z/^0-9²³°]*))?")


def quantity(value: str, unit: str) -> sympy.Expr | None:
    """'5', 'm/s^2' -> 5*meter/second**2; a label unit ('rupees', '°') is dropped."""
    try:
        number = mathcheck.parse(value, mathcheck.UNITS, LIMITS)
    except mathcheck.MathParseError:
        return None
    try:
        return number * mathcheck.parse(unit, mathcheck.UNITS, LIMITS) if unit.strip() else number
    except mathcheck.MathParseError:
        return number


def same_value(got: sympy.Expr, want: sympy.Expr, tolerance: float) -> bool:
    """Equal within tolerance, converting units when both carry them (20 m/s = 72 km/h)."""
    if got.atoms(Quantity) and want.atoms(Quantity):
        ratio = sympy.simplify(convert_to(got / want, mathcheck.SI_BASE))
        if ratio.atoms(Quantity) or not ratio.is_number:
            return False  # different dimensions: a wrong unit is a wrong answer
        return abs(float(ratio) - 1) <= tolerance
    # A unit on one side only (a label, or a maths answer): compare the numbers.
    got_number, want_number = (float(mathcheck._strip_units(x)) for x in (got, want))
    return abs(got_number - want_number) <= tolerance * max(1.0, abs(want_number))


def matches(
    answers: list[tuple[str, str]], wanted: list[dict], tolerance: float, allow_extra: bool = False
) -> bool:
    """Every wanted value found once among the answers (order does not matter). Extra values
    count as wrong unless allowed: a FINAL sentence may name other numbers ("Car 1 arrives
    first: 3 s vs 4 s"). Rounding is allowed only on a number written with decimals: "3999"
    for 4000 is wrong, "7.33" for 22/3 is rounded (bench audit, 21 Oct)."""
    got = [(quantity(value, unit), tolerance if "." in value else EXACT) for value, unit in answers]
    if any(g is None for g, _ in got) or len(got) < len(wanted):
        return False
    if len(got) > len(wanted) and not allow_extra:
        return False
    left = list(got)
    for item in wanted:
        expected = quantity(item["value"], item["unit"])
        hit = next((g for g in left if same_value(g[0], expected, g[1])), None)
        if hit is None:
            return False
        left.remove(hit)
    return True


def plain(text: str) -> str:
    """The model writes FINAL lines in LaTeX ('$0.0001 \\, \\text{m}^3$') and with thousands
    commas ('60,000 m'): reduce them to plain text before reading the numbers."""
    text = re.sub(r"\\(?:text|mathrm)\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\[,;! ]", " ", text).replace("$", "")
    text = re.sub(r"\\[A-Za-z]+", " ", text).replace("{", "").replace("}", "")
    return re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)


def final_lines(text: str) -> list[str]:
    return _FINAL.findall(text or "")


def final_answers(text: str) -> list[tuple[str, str]] | None:
    """Every number (with the unit after it) on the model's last 'FINAL:' line, whatever its
    form: 't1 = 3 s, t2 = 4 s', 'Volume = 0.0001 m^3', 'Q takes less time (15 s vs 20 s)'.
    None when there is no FINAL line (e.g. the answer ran out of tokens) or it says none."""
    found = final_lines(text)
    if not found or found[-1].strip().lower().startswith("none"):
        return None
    answers = [(number, unit or "") for number, unit in _VALUE.findall(plain(found[-1]))]
    return answers or None


async def second_opinion(client: httpx.AsyncClient, question: str) -> str:
    """The model solves the problem by itself (no calculator, no book), ending with FINAL."""
    messages = [
        {"role": "system", "content": load_prompt(CHECK_PROMPT)},
        {"role": "user", "content": question},
    ]
    return await complete(messages, client, CHECK_MAX_TOKENS)


def agrees(calculator: list[tuple[str, str]], opinion: str) -> bool:
    """True when every value the calculator would show is also in the model's own FINAL line.
    No FINAL line (the model ran out of tokens or found nothing to calculate) is not agreement."""
    said = final_answers(opinion)
    if said is None:
        return False
    wanted = [{"value": value, "unit": unit} for value, unit in calculator]
    return matches(said, wanted, ROUNDING, allow_extra=True)
