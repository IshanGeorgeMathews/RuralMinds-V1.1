import pytest

from ruralminds import mathcheck
from ruralminds.mathcheck import Limits, MathParseError, Problem, Solver, solve_problem

LIMITS = Limits(max_chars=200, max_digits=12, max_exponent=10, max_degree=3, max_unknowns=4)


def solved(problem: Problem) -> list[str]:
    solution = solve_problem(problem, LIMITS)
    assert solution.status == "solved", solution.detail
    assert len(solution.solutions) == 1
    return [answer.display for answer in solution.solutions[0]]


# Problems from the Class 8 books (Maths Pt1 ch 2 p 41, Science Pt1 ch 8-9), hand-solved.
@pytest.mark.parametrize(
    ("problem", "expected"),
    [
        # Worked example: 10x + 70 = 100
        (Problem(("x",), ("10x + 70 = 100",)), ["3"]),
        # Perimeter 80 m, length one metre more than twice the breadth
        (Problem(("b", "l"), ("2(l + b) = 80", "l = 2b + 1"), answer_unit="m"), ["13 m", "27 m"]),
        # Two angles on a line, one 50° more than the other: the smaller one
        (Problem(("x",), ("x + (x + 50) = 180",), answer_unit="°"), ["65 °"]),
        # Book 4 more than a pen, pencil 2 less; 5 books + 2 pens + 3 pencils = 74
        (
            Problem(("p",), ("5(p + 4) + 2p + 3(p - 2) = 74",), asked=("p + 4", "p", "p - 2")),
            ["10", "6", "4"],
        ),
        # Three consecutive odd numbers summing to 33
        (Problem(("x",), ("x + (x + 2) + (x + 4) = 33",), asked=("x", "x+2", "x+4")),
         ["9", "11", "13"]),
        # Calendar square of four numbers summing to 80
        (Problem(("n",), ("n + (n + 1) + (n + 7) + (n + 8) = 80",),
                 asked=("n", "n + 1", "n + 7", "n + 8")), ["16", "17", "23", "24"]),
        # Car from rest to 40 m/s in 8 s: acceleration
        (Problem(("a",), ("v = u + a t",), knowns=(("u", "0 m/s"), ("v", "40 m/s"), ("t", "8 s")),
                 answer_unit="m/s^2"), ["5 m/s²"]),
        # 15 m/s for 30 s: displacement
        (Problem(("d",), ("d = v t",), knowns=(("v", "15 m/s"), ("t", "30 s")), answer_unit="m"),
         ["450 m"]),
        # Classroom 5 m by 4 m: area
        (Problem(("A",), ("A = l b",), knowns=(("l", "5 m"), ("b", "4 m")), answer_unit="m^2"),
         ["20 m²"]),
    ],
)  # fmt: skip
def test_book_problems(problem: Problem, expected: list[str]) -> None:
    assert solved(problem) == expected


def test_units_convert_and_mismatch_is_caught() -> None:
    speed = Problem(
        ("v",), ("v = d / t",), knowns=(("d", "72 km"), ("t", "1 h")), answer_unit="m/s"
    )
    assert solved(speed) == ["20 m/s"]
    spelled = Problem(
        ("v",),
        ("v = d / t",),
        knowns=(("d", "72 km"), ("t", "1 hour")),
        answer_unit="metres/second",
    )
    assert solved(spelled) == ["20 metres/second"]
    wrong = Problem(("v",), ("v = d / t",), knowns=(("d", "72 km"), ("t", "1 h")), answer_unit="kg")
    assert solve_problem(wrong, LIMITS).status == "unit_mismatch"


def test_printed_symbols_and_implicit_multiplication() -> None:
    # What the book prints (and OCR may return): ×, ÷, −, ², and "3x"
    assert solved(Problem(("x",), ("x = (100 − 70) ÷ 10",))) == ["3"]
    assert solved(Problem(("x",), ("3x + 2 = 2 × 7",))) == ["4"]
    a, b = mathcheck.sympy.symbols("a b")
    identity = mathcheck.parse("(a + b)(a − b)", {"a": a, "b": b}, LIMITS)
    assert mathcheck.sympy.expand(identity) == a**2 - b**2
    assert mathcheck.parse("a²", {"a": a}, LIMITS) == a**2


def test_numbers_are_exact_and_shown_simply() -> None:
    assert mathcheck.format_number(mathcheck.parse("5/2", {}, LIMITS)) == "2.5"
    assert mathcheck.format_number(mathcheck.parse("7/3", {}, LIMITS)) == "7/3 ≈ 2.33"
    assert mathcheck.parse("0.1 + 0.2", {}, LIMITS) == mathcheck.parse("3/10", {}, LIMITS)


def test_quadratic_gives_both_roots() -> None:
    solution = solve_problem(Problem(("x",), ("x^2 - 5x + 6 = 0",)), LIMITS)
    assert solution.status == "solved"
    assert sorted(answers[0].display for answers in solution.solutions) == ["2", "3"]


@pytest.mark.parametrize(
    "text",
    [
        "__import__('os').system('dir')",  # code: names are never evaluated
        "x.__class__",
        "open(x)",  # only sqrt is a function
        "2^(10^10)",  # exponent over the cap
        "x^y",  # exponent must be a number
        "1234567890123 * x",  # number over the digit cap
        "x + " * 60 + "x",  # longer than max_chars
        "x = 1; y",
    ],
)
def test_parser_refuses_unsafe_or_oversized_input(text: str) -> None:
    with pytest.raises(MathParseError):
        mathcheck.parse(text, {"x": mathcheck.sympy.Symbol("x")}, LIMITS)


def test_failures_are_statuses() -> None:
    assert solve_problem(Problem(("x",), ("x + 1 = x + 2",)), LIMITS).status == "no_solution"
    assert solve_problem(Problem(("x", "y"), ("x + y = 10",)), LIMITS).status == "many_solutions"
    assert solve_problem(Problem(("x",), ("x^2 = -4",)), LIMITS).status == "no_solution"
    assert solve_problem(Problem(("x",), ("x^4 = 16",)), LIMITS).status == "too_complex"
    assert solve_problem(Problem(("x",), ("x + 1",)), LIMITS).status == "parse_error"
    assert solve_problem(Problem(("x",), ("x = q",)), LIMITS).status == "parse_error"


def test_solver_times_out_and_recovers() -> None:
    solver = Solver(timeout_s=60, limits=LIMITS)
    try:
        solver.warm()  # pays for the worker start and the SymPy import
        solver.timeout_s = 0.001
        slow = Problem(("x",), ("x^3 + 7x^2 - 3x + 11 = 0",))
        assert solver.solve(slow).status == "timeout"
        solver.timeout_s = 60
        assert solver.solve(Problem(("x",), ("2x = 8",))).solutions[0][0].display == "4"
    finally:
        solver.close()


@pytest.mark.parametrize(
    ("problem", "steps"),
    [
        (
            Problem(("x",), ("x + (x + 2) + (x + 4) = 33",), asked=("x", "x + 2", "x + 4")),
            ("x + (x + 2) + (x + 4) = 33", "3x + 6 = 33", "3x = 27", "x = 9"),
        ),
        (
            Problem(
                ("a",),
                ("v = u + a t",),
                knowns=(("u", "0 m/s"), ("v", "40 m/s"), ("t", "8 s")),
                answer_unit="m/s^2",
            ),
            ("v = u + a × t", "a = (v - u)/t", "a = (40 - 0)/8", "a = 5 m/s²"),
        ),
        (
            Problem(("A",), ("A = 2l b",), knowns=(("l", "5 m"), ("b", "4 m")), answer_unit="m^2"),
            ("A = 2l × b", "A = 2 × 5 × 4", "A = 40 m²"),
        ),
        # Units converted on the way: "v = 72/1" would contradict "20 m/s", so it is left out.
        (
            Problem(("v",), ("v = d/t",), knowns=(("d", "72 km"), ("t", "1 h")), answer_unit="m/s"),
            ("v = d/t", "v = 20 m/s"),
        ),
        # Two answers or two equations: no worked lines; the model explains the equations.
        (Problem(("x",), ("x^2 - 5x + 6 = 0",)), ()),
        (Problem(("b", "l"), ("2(l + b) = 80", "l = 2b + 1")), ()),
    ],
)
def test_worked_steps_are_computed_not_written_by_the_model(
    problem: Problem, steps: tuple[str, ...]
) -> None:
    assert solve_problem(problem, LIMITS).steps == steps


@pytest.mark.parametrize(
    ("unit", "question", "kept"),
    [
        ("m/s^2", "What is the acceleration of the car?", "m/s^2"),  # a real unit
        ("rupees", "The total price is 74 rupees. What is each price?", "rupees"),
        ("metres", "The perimeter is 80 metres.", "metres"),
        ("degree/none", "The sum of three consecutive odd numbers is 33.", ""),  # made up
        ("years", "The sum of three consecutive odd numbers is 33.", ""),
        ("", "Anything", ""),
    ],
)
def test_answer_unit_comes_from_units_or_the_question(unit: str, question: str, kept: str) -> None:
    assert mathcheck.answer_unit_for(unit, question, LIMITS) == kept


@pytest.mark.parametrize("name", ["s", "m", "g", "h", "d"])
def test_unknowns_named_like_units_still_solve(name: str) -> None:
    # Bench, 21 Oct: "s = v * t" gave no solution, because SymPy's unit second is also "s".
    problem = Problem(
        (name,), (f"{name} = v * t",), knowns=(("v", "20 m/s"), ("t", "2 minutes")), answer_unit="m"
    )
    assert solved(problem) == ["2400 m"]
