"""Solve and check the equations a numerical problem reduces to. The model never does arithmetic.

A 2B model sets up the problem (unknowns, equations, given quantities with units); SymPy solves
it here and substitutes the answer back. Model text is read by our own small parser, never by
`sympify`/`parse_expr` (they call `eval`), and every input is size-capped before SymPy sees it.
Solving runs in a worker process with a hard timeout, so a runaway input cannot freeze the
server: a whitelist stops code injection, but not `(x+1)^9 * (x+2)^9 = 0`.

Units are checked only when the problem gives them ("40 m/s"). A unit on a unitless answer
("rupees", "cm" in a geometry problem worked without units) is only a display label.
"""

import asyncio
import logging
import multiprocessing
import multiprocessing.pool
import re
import threading
from dataclasses import dataclass, field, replace

import sympy
from sympy.physics import units as u
from sympy.physics.units import Quantity, convert_to
from sympy.polys.polyerrors import PolynomialError

from .config import settings

log = logging.getLogger(__name__)

# Units a Class 8-10 numerical uses. Temperature is left out: °C ↔ K is an offset, not a factor.
UNITS: dict[str, sympy.Expr] = {
    "mm": u.millimeter, "cm": u.centimeter, "m": u.meter, "km": u.kilometer,
    "s": u.second, "min": u.minute, "h": u.hour, "hr": u.hour,
    "mg": u.milligram, "g": u.gram, "kg": u.kilogram,
    "N": u.newton, "J": u.joule, "kJ": 1000 * u.joule, "W": u.watt, "Pa": u.pascal,
    "L": u.liter, "mL": u.milliliter,
}  # fmt: skip
# The model often spells units out ("1 hour", "5 metres"); singular and plural both count.
_SPELLED = {
    "millimetre": "mm", "centimetre": "cm", "metre": "m", "kilometre": "km",
    "millimeter": "mm", "centimeter": "cm", "meter": "m", "kilometer": "km",
    "second": "s", "minute": "min", "hour": "h", "gram": "g", "kilogram": "kg",
    "newton": "N", "joule": "J", "watt": "W", "litre": "L", "liter": "L",
}  # fmt: skip
UNITS |= {name + plural: UNITS[short] for name, short in _SPELLED.items() for plural in ("", "s")}
SI_BASE = [u.meter, u.kilogram, u.second, u.ampere, u.kelvin, u.mole, u.candela]
FUNCTIONS = {"sqrt": sympy.sqrt}

# Typed or printed maths symbols → the plain operators the parser reads.
_SYMBOLS = str.maketrans({"×": "*", "·": "*", "÷": "/", "−": "-", "–": "-", "—": "-",
                          "²": "^2", "³": "^3", "√": "sqrt"})  # fmt: skip
_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?|\.\d+)|([A-Za-z][A-Za-z0-9_]*)|(\*\*|[-+*/^()]))")


class MathParseError(ValueError):
    """Text the parser refuses: unknown names, bad syntax, or over a size limit."""


@dataclass(frozen=True)
class Limits:
    max_chars: int
    max_digits: int
    max_exponent: int
    max_degree: int
    max_unknowns: int

    @classmethod
    def from_settings(cls) -> "Limits":
        return cls(
            max_chars=settings.math_max_chars,
            max_digits=settings.math_max_digits,
            max_exponent=settings.math_max_exponent,
            max_degree=settings.math_max_degree,
            max_unknowns=settings.math_max_unknowns,
        )


@dataclass(frozen=True)
class Problem:
    """What the setup call returns. `asked` defaults to the unknowns ("x, x+2, x+4" is common)."""

    unknowns: tuple[str, ...]
    equations: tuple[str, ...]
    knowns: tuple[tuple[str, str], ...] = ()  # ("v", "40 m/s")
    asked: tuple[str, ...] = ()
    answer_unit: str = ""


@dataclass(frozen=True)
class Answer:
    asked: str  # the expression asked for, as the model wrote it
    exact: str  # SymPy value in `unit`, for comparing with a gold answer
    unit: str
    display: str  # "5 m/s²", "7/3 ≈ 2.33"


@dataclass(frozen=True)
class Solution:
    # solved | parse_error | too_complex | no_solution | many_solutions | unit_mismatch
    # | check_failed | timeout | error
    status: str
    solutions: tuple[tuple[Answer, ...], ...] = field(default=())
    detail: str = ""
    # Worked lines ("3x + 6 = 33", "3x = 27", "x = 9") so the model narrates, never calculates.
    # Empty when the problem has more than one equation or unknown.
    steps: tuple[str, ...] = ()


def _tokens(text: str, limits: Limits) -> list[str]:
    text = text.translate(_SYMBOLS).replace("**", "^")
    if len(text) > limits.max_chars:
        raise MathParseError(f"longer than {limits.max_chars} characters")
    tokens, pos = [], 0
    while pos < len(text.rstrip()):
        match = _TOKEN.match(text, pos)
        if not match:
            raise MathParseError(f"cannot read {text[pos : pos + 10]!r}")
        number, name, op = match.groups()
        if number and len(number.replace(".", "")) > limits.max_digits:
            raise MathParseError(f"number longer than {limits.max_digits} digits")
        token = number or name or op
        # "3x", "2(x + 1)", "(a + b)(a - b)": implicit multiplication, but not "sqrt(".
        if tokens and _ends_value(tokens[-1]) and (number or name or op == "("):
            tokens.append("*")
        tokens.append(token)
        pos = match.end()
    return tokens


def _ends_value(token: str) -> bool:
    return (
        token == ")"
        or token[0].isdigit()
        or token[0] == "."
        or (token[0].isalpha() and token not in FUNCTIONS)
    )


class _Parser:
    """Recursive descent: expr → term (± term)*, term → unary (*/ unary)*, power is right-assoc."""

    def __init__(self, tokens: list[str], names: dict[str, sympy.Expr], limits: Limits) -> None:
        self.tokens, self.names, self.limits, self.pos = tokens, names, limits, 0

    def parse(self) -> sympy.Expr:
        value = self._expr()
        if self.pos != len(self.tokens):
            raise MathParseError(f"unexpected {self.tokens[self.pos]!r}")
        return value

    def _peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _take(self, expected: str | None = None) -> str:
        token = self._peek()
        if token is None or (expected is not None and token != expected):
            raise MathParseError(f"expected {expected or 'more'}")
        self.pos += 1
        return token

    def _expr(self) -> sympy.Expr:
        value = self._term()
        while self._peek() in ("+", "-"):
            value = value + self._term() if self._take() == "+" else value - self._term()
        return value

    def _term(self) -> sympy.Expr:
        value = self._unary()
        while self._peek() in ("*", "/"):
            value = value * self._unary() if self._take() == "*" else value / self._unary()
        return value

    def _unary(self) -> sympy.Expr:
        if self._peek() in ("+", "-"):
            return -self._unary() if self._take() == "-" else self._unary()
        return self._power()

    def _power(self) -> sympy.Expr:
        base = self._atom()
        if self._peek() != "^":
            return base
        self._take()
        exponent = self._unary()
        if not exponent.is_Rational or abs(exponent) > self.limits.max_exponent:
            raise MathParseError(f"exponent must be a number up to {self.limits.max_exponent}")
        return base**exponent

    def _atom(self) -> sympy.Expr:
        token = self._take()
        if token == "(":
            value = self._expr()
            self._take(")")
            return value
        if token[0].isdigit() or token[0] == ".":
            return sympy.Rational(token)  # exact: 0.05 stays 1/20
        if token in FUNCTIONS:
            self._take("(")
            value = self._expr()
            self._take(")")
            return FUNCTIONS[token](value)
        if token in self.names:
            return self.names[token]
        raise MathParseError(f"unknown name {token!r}")


def parse(text: str, names: dict[str, sympy.Expr], limits: Limits) -> sympy.Expr:
    return _Parser(_tokens(text, limits), names, limits).parse()


def parse_quantity(text: str, limits: Limits) -> sympy.Expr:
    """'40 m/s' → 40*meter/second. The number comes first; the rest must be units."""
    match = re.fullmatch(r"\s*([-+]?(?:\d+(?:\.\d+)?|\.\d+))\s*(.*?)\s*", text)
    if not match:
        raise MathParseError(f"not a quantity: {text!r}")
    number = parse(match.group(1), {}, limits)
    unit_text = match.group(2)
    return number * parse(unit_text, UNITS, limits) if unit_text else number


def answer_unit_for(unit: str, question: str, limits: Limits) -> str:
    """The model's answer unit, kept only if it is a real unit or a word from the question.

    A small model fills the unit line even for plain numbers ("degree/none" on a sum of odd
    numbers), so a label like "rupees" must come from the question itself.
    """
    unit = unit.strip()
    if not unit:
        return ""
    try:
        parse(unit, UNITS, limits)
        return unit
    except MathParseError:
        pass
    words = re.findall(r"[a-z]+", question.casefold())
    return unit if unit.casefold() in words else ""


def _equation(text: str, names: dict[str, sympy.Expr], limits: Limits) -> sympy.Eq:
    sides = text.split("=")
    if len(sides) != 2:
        raise MathParseError(f"an equation needs exactly one '=': {text!r}")
    return sympy.Eq(parse(sides[0], names, limits), parse(sides[1], names, limits), evaluate=False)


def _check_degree(equations: list[sympy.Eq], unknowns: list[sympy.Symbol], limit: int) -> None:
    for equation in equations:
        try:
            degree = sympy.Poly(equation.lhs - equation.rhs, *unknowns).total_degree()
        except PolynomialError:
            continue  # not a polynomial (e.g. 1/x): left to the timeout
        if degree > limit:
            raise MathParseError(f"degree {degree} is above {limit}")


def _strip_units(value: sympy.Expr) -> sympy.Expr:
    return value.subs({quantity: 1 for quantity in value.atoms(Quantity)})


def _in_unit(value: sympy.Expr, unit: sympy.Expr) -> sympy.Expr | None:
    """The number of `unit`s in `value`, or None when the dimensions differ."""
    ratio = sympy.simplify(convert_to(value / unit, SI_BASE))
    return None if ratio.atoms(Quantity) else ratio


def format_number(value: sympy.Expr) -> str:
    """9 → '9'; 5/2 → '2.5'; 7/3 → '7/3 ≈ 2.33'; sqrt(2) → 'sqrt(2) ≈ 1.41'."""
    if value.is_Integer:
        return str(value)
    if value.is_Rational:
        denominator = int(value.q)
        for prime in (2, 5):
            while denominator % prime == 0:
                denominator //= prime
        if denominator == 1:  # a terminating decimal: show it exactly
            return format(sympy.Float(value, 30), "f").rstrip("0").rstrip(".")
    return f"{value} ≈ {float(value):.2f}"


def pretty_unit(unit: str) -> str:
    return unit.replace("**", "^").replace("^2", "²").replace("^3", "³")


def _answer(asked: str, value: sympy.Expr, unit_text: str, limits: Limits) -> Answer:
    if not value.atoms(Quantity):  # unitless: any unit is only a label
        shown = f"{format_number(value)} {pretty_unit(unit_text)}".strip()
        return Answer(asked, str(value), unit_text, shown)
    if not unit_text:  # has units but none was asked for: keep SymPy's own form
        shown = sympy.sstr(value, abbrev=True)
        return Answer(asked, shown, "", pretty_unit(shown))
    number = _in_unit(value, parse(unit_text, UNITS, limits))
    if number is None:
        raise ArithmeticError(f"{asked} is not in {unit_text}")
    shown = f"{format_number(number)} {pretty_unit(unit_text)}"
    return Answer(asked, str(number), unit_text, shown)


def _holds(equation: sympy.Eq, solution: dict[sympy.Symbol, sympy.Expr]) -> bool:
    difference = equation.lhs.subs(solution) - equation.rhs.subs(solution)
    return sympy.simplify(convert_to(difference, SI_BASE)) == 0


def _real(solution: dict[sympy.Symbol, sympy.Expr]) -> bool:
    return all(_strip_units(value).is_real for value in solution.values())


def _setup(problem: Problem, limits: Limits) -> tuple[list[sympy.Eq], list[sympy.Symbol], dict]:
    if not 1 <= len(problem.unknowns) <= limits.max_unknowns:
        raise MathParseError(f"needs 1 to {limits.max_unknowns} unknowns")
    if len(problem.equations) > limits.max_unknowns:
        raise MathParseError("too many equations")
    unknowns = [sympy.Symbol(name) for name in problem.unknowns]
    names: dict[str, sympy.Expr] = {str(symbol): symbol for symbol in unknowns}
    for name, quantity in problem.knowns:
        if name in names or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
            raise MathParseError(f"bad known name {name!r}")
        names[name] = parse_quantity(quantity, limits)
    equations = [_equation(text, names, limits) for text in problem.equations]
    _check_degree(equations, unknowns, limits.max_degree)
    return equations, unknowns, names


def _answers(problem: Problem, names: dict, found: list[dict], limits: Limits) -> Solution:
    try:
        solutions = tuple(
            tuple(
                _answer(
                    text, parse(text, names, limits).subs(solution), problem.answer_unit, limits
                )
                for text in problem.asked or problem.unknowns
            )
            for solution in found
        )
    except MathParseError as error:
        return Solution("parse_error", detail=str(error))
    except ArithmeticError as error:
        return Solution("unit_mismatch", detail=str(error))
    return Solution("solved", solutions)


def solve_problem(problem: Problem, limits: Limits) -> Solution:
    """Runs in the worker process. Every failure is a status, never an exception."""
    try:
        equations, unknowns, names = _setup(problem, limits)
        found = sympy.solve(equations, unknowns, dict=True)
    except MathParseError as error:
        status = "too_complex" if "degree" in str(error) else "parse_error"
        return Solution(status, detail=str(error))
    except (NotImplementedError, TypeError, ValueError, ArithmeticError, PolynomialError) as error:
        return Solution("error", detail=f"solve failed: {error}")
    # Free unknowns first: "x = 10 - y" is not known to be real, so the next filter would drop it.
    if any(set(solution) != set(unknowns) for solution in found):
        return Solution("many_solutions", detail="some unknowns are left free")
    found = [solution for solution in found if _real(solution)]
    if not found:
        return Solution("no_solution")
    if not all(_holds(equation, solution) for equation in equations for solution in found):
        return Solution("check_failed", detail="an answer does not satisfy the equations")
    solution = _answers(problem, names, found, limits)
    if solution.status != "solved" or len(found) != 1 or len(unknowns) != 1:
        return solution
    unknown, value = unknowns[0], found[0][unknowns[0]]
    try:
        answer = _answer(str(unknown), value, problem.answer_unit, limits)
    except ArithmeticError:  # the unit was asked of another expression, not of the unknown
        number = _strip_units(value)
        answer = Answer(str(unknown), str(number), "", format_number(number))
    return replace(solution, steps=worked_steps(problem, answer, limits))


def _pretty(text: str, implicit: bool = True) -> str:
    """Maths the way the book prints it: '3x + 6', 'a × t', 'x²'."""
    text = text.translate(_SYMBOLS).replace("**", "^")
    if implicit:
        text = re.sub(r"(\d)\s*\*\s*(?=[A-Za-z(])", r"\1", text)
    return pretty_unit(re.sub(r"\s*\*\s*", " × ", text))


def show(expr: sympy.Expr, implicit: bool = True, order: str | None = None) -> str:
    # order="none" keeps "(v - u)/t"; the default order keeps "3x + 6" for polynomials.
    return _pretty(sympy.sstr(expr, order=order), implicit)


def _as_written(text: str, limits: Limits, implicit: bool = True) -> str:
    """The model's own expression, tidied: 'a t' → 'a × t', '10*x' → '10x'."""
    joined = "".join(_tokens(text, limits))
    return _pretty(re.sub(r"(?<=[\w)])([-+=])", r" \1 ", joined), implicit)


def _linear_steps(problem: Problem, unknown: sympy.Symbol, limits: Limits) -> list[str]:
    """'x + (x + 2) + (x + 4) = 33' → '3x + 6 = 33' → '3x = 27'. Raises ValueError if not linear."""
    text = problem.equations[0]
    equation = _equation(text, {str(unknown): unknown}, limits)
    left, right = sympy.expand(equation.lhs), sympy.expand(equation.rhs)
    coefficient, constant = sympy.Poly(left - right, unknown).all_coeffs()
    written = " = ".join(_as_written(side, limits) for side in text.split("="))
    return [
        written,
        f"{show(left)} = {show(right)}",
        f"{show(coefficient * unknown)} = {show(-constant)}",
    ]


def _formula_steps(
    problem: Problem, unknown: sympy.Symbol, answer: Answer, limits: Limits
) -> list[str]:
    """'v = u + a t' → 'a = (v - u)/t' → 'a = (40 - 0)/8'. Numbers are shown without units."""
    left_text, right_text = problem.equations[0].split("=")
    lines = [f"{_as_written(left_text, limits)} = {_as_written(right_text, limits)}"]
    if left_text.strip() == str(unknown):  # already "d = v × t": substitute into it as written
        formula = _as_written(right_text, limits, implicit=False)
    else:
        names = {name: sympy.Symbol(name) for name, _ in problem.knowns} | {str(unknown): unknown}
        rearranged = sympy.solve(_equation(problem.equations[0], names, limits), unknown)
        if len(rearranged) != 1:
            return lines
        lines.append(f"{unknown} = {show(rearranged[0], order='none')}")
        # Explicit ×: with implicit multiplication "2l" would become "25" once l is replaced by 5.
        formula = show(rearranged[0], implicit=False, order="none")
    numbers = {}
    for name, quantity in problem.knowns:
        number = format_number(_strip_units(parse_quantity(quantity, limits)))
        numbers[name] = f"({number})" if number.startswith("-") else number
    substituted = re.sub(r"[A-Za-z][A-Za-z0-9_]*", lambda m: numbers.get(m[0], m[0]), formula)
    # "72 km in 1 h" asked in m/s: "v = 72/1" then "v = 20 m/s" would look wrong, so the line
    # is shown only when its own numbers give the answer.
    if parse(substituted, {}, limits) == parse(answer.exact, {}, limits):
        lines.append(f"{unknown} = {substituted}")
    return lines


def worked_steps(problem: Problem, answer: Answer, limits: Limits) -> tuple[str, ...]:
    """Worked lines for one equation in one unknown, ending with the answer; else ()."""
    if len(problem.equations) != 1:
        return ()
    unknown = sympy.Symbol(problem.unknowns[0])
    try:
        if problem.knowns:
            lines = _formula_steps(problem, unknown, answer, limits)
        else:
            lines = _linear_steps(problem, unknown, limits)
    except (MathParseError, ValueError, PolynomialError, NotImplementedError):
        return ()  # e.g. a quadratic: explained from the equation and its answers instead
    lines.append(f"{unknown} = {answer.display}")
    return tuple(line for index, line in enumerate(lines) if index == 0 or line != lines[index - 1])


class Solver:
    """One warm worker process. A solve that runs past the timeout kills the process; the next
    solve starts a fresh one. One solve at a time: normal solves take milliseconds."""

    def __init__(self, timeout_s: float, limits: Limits) -> None:
        self.timeout_s, self.limits = timeout_s, limits
        self._pool: multiprocessing.pool.Pool | None = None
        self._lock = threading.Lock()

    def _get_pool(self) -> multiprocessing.pool.Pool:
        if self._pool is None:
            self._pool = multiprocessing.get_context("spawn").Pool(1)
        return self._pool

    def warm(self) -> None:
        """Start the worker and import SymPy in it now, not on a student's first question."""
        with self._lock:
            self._get_pool().apply(format_number, (sympy.Integer(1),))

    def solve(self, problem: Problem) -> Solution:
        """Blocking; call through asyncio.to_thread from request handlers."""
        with self._lock:
            pool = self._get_pool()
            try:
                return pool.apply_async(solve_problem, (problem, self.limits)).get(self.timeout_s)
            except multiprocessing.TimeoutError:
                log.warning("math solve timed out after %.1f s: %r", self.timeout_s, problem)
                self.close()
                return Solution("timeout", detail=f"over {self.timeout_s} s")

    def close(self) -> None:
        if self._pool is not None:
            self._pool.terminate()
            self._pool = None


_solver: Solver | None = None


async def solve(problem: Problem) -> Solution:
    global _solver
    if _solver is None:
        _solver = Solver(settings.math_timeout_s, Limits.from_settings())
    return await asyncio.to_thread(_solver.solve, problem)
