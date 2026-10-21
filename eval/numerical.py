"""Bench for the "Solve step by step" chip (docs/workstreams/maths-and-numericals.md §5).

    uv run python -m eval.numerical freeze           # once: writes `split` + the manifest
    uv run python -m eval.numerical verify           # test items unchanged since the freeze?
    RURALMINDS_DB_PATH=data/eval-run.db uv run python -m eval.numerical run --split dev --label x

Arms, on the same items:
- solve: the real answer path with the chip on (setup -> SymPy -> explain), in-process.
- alone: the same model solves the problem itself (eval prompt numerical_alone_v1): no
  calculator, no book. The difference between the two is what the calculator adds.
- setup: the setup call + SymPy only, for Maths items (no Maths book is indexed yet).

Outcome per solve/setup item: checked_right | checked_wrong (a ✓ on a wrong answer: the number
that matters most) | unsolved (the safe message) | refused | answered_plain | error.
Gold answers are solved by hand, never by SymPy (that would be circular); `verified` marks the
items a reviewer has checked. Timings are reported but valid only on a quiet machine.
"""

import argparse
import asyncio
import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path

import httpx
import sympy
from sympy.physics.units import Quantity, convert_to

from eval.metrics import percentile, rate
from eval.run import book_for, check_safe_to_run, require_quiet
from ruralminds import mathcheck, numerical
from ruralminds.answer import AnswerQueue, AskRequest, answer_stream
from ruralminds.config import settings
from ruralminds.db import connect
from ruralminds.llm import complete

ITEMS = Path("eval/datasets/num/numerical.jsonl")
MANIFEST = Path("eval/datasets/num/split_manifest.json")
ALONE_PROMPT = Path("eval/prompts/numerical_alone_v1.md")
SEED = "ruralminds-num-v1"
DEV_SHARE = 0.3
FINGERPRINT_KEYS = ("id", "question", "gold", "expected", "arms")
LIMITS = mathcheck.Limits(
    max_chars=200, max_digits=15, max_exponent=10, max_degree=3, max_unknowns=6
)
EXACT = 1e-9
TOLERANCE = {"solve": EXACT, "setup": EXACT, "alone": 1e-3}  # SymPy is exact; the model rounds
_FINAL = re.compile(r"FINAL:\s*(.*)", re.IGNORECASE)
# A number not inside a name ("t1") or a power ("m^2"), and the unit word right after it.
_VALUE = re.compile(r"(?<![\w.^])(-?\d+(?:\.\d+)?)(?:\s*([A-Za-z°][A-Za-z/^0-9²³°]*))?")
ALONE_MAX_TOKENS = 800  # at 400 a three-part journey ran out before its FINAL line (21 Oct)


# ---------- items and the frozen split ----------
def load_items(path: Path = ITEMS) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def split_of(item: dict) -> str:
    """Forced dev for items we tuned on; otherwise ~30% dev by a seeded hash (nobody picks)."""
    if item.get("forced_split"):
        return item["forced_split"]
    digest = hashlib.sha256(f"{SEED}:{item['id']}".encode()).digest()
    return "dev" if digest[0] / 256 < DEV_SHARE else "test"


def fingerprint(items: list[dict]) -> str:
    test = [
        {key: item.get(key) for key in FINGERPRINT_KEYS}
        for item in items
        if item["split"] == "test"
    ]
    return hashlib.sha256(json.dumps(test, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def freeze() -> None:
    items = [{**item, "split": split_of(item)} for item in load_items()]
    ITEMS.write_text(
        "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8"
    )
    counts = {name: sum(i["split"] == name for i in items) for name in ("dev", "test")}
    MANIFEST.write_text(
        json.dumps({"seed": SEED, "counts": counts, "test_sha256": fingerprint(items)}, indent=1)
    )
    print(counts)


def verify() -> bool:
    """True when the test items are exactly as frozen."""
    return json.loads(MANIFEST.read_text())["test_sha256"] == fingerprint(load_items())


# ---------- comparing answers with gold ----------
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


def same_value(got: sympy.Expr, gold: sympy.Expr, tolerance: float) -> bool:
    """Equal within tolerance, converting units when both carry them (20 m/s = 72 km/h)."""
    if got.atoms(Quantity) and gold.atoms(Quantity):
        ratio = sympy.simplify(convert_to(got / gold, mathcheck.SI_BASE))
        if ratio.atoms(Quantity) or not ratio.is_number:
            return False  # different dimensions: a wrong unit is a wrong answer
        return abs(float(ratio) - 1) <= tolerance
    # A unit on one side only (a label, or a maths answer): compare the numbers.
    got_number, gold_number = (float(mathcheck._strip_units(x)) for x in (got, gold))
    return abs(got_number - gold_number) <= tolerance * max(1.0, abs(gold_number))


def matches(
    answers: list[tuple[str, str]], gold: list[dict], tolerance: float, allow_extra: bool = False
) -> bool:
    """Every gold value found once among the answers (order does not matter). Extra values count
    as wrong, except for the model alone, whose FINAL sentence may name other numbers ("Car 1
    arrives first: 3 s vs 4 s"): lenient on the baseline, so any gain we report is not inflated."""
    # Rounding is allowed only on a number written with decimals: "3999" for 4000 is wrong, but
    # "7.33" for 22/3 is rounded (bench audit, 21 Oct).
    got = [(quantity(value, unit), tolerance if "." in value else EXACT) for value, unit in answers]
    if any(g is None for g, _ in got) or len(got) < len(gold):
        return False
    if len(got) > len(gold) and not allow_extra:
        return False
    left = list(got)
    for item in gold:
        expected = quantity(item["value"], item["unit"])
        hit = next((g for g in left if same_value(g[0], expected, g[1])), None)
        if hit is None:
            return False
        left.remove(hit)
    return True


def _plain(text: str) -> str:
    """The model writes FINAL lines in LaTeX ('$0.0001 \\, \\text{m}^3$') and with thousands
    commas ('60,000 m'): reduce them to plain text before reading the numbers."""
    text = re.sub(r"\\(?:text|mathrm)\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\[,;! ]", " ", text).replace("$", "")
    text = re.sub(r"\\[A-Za-z]+", " ", text).replace("{", "").replace("}", "")
    return re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)


def final_answers(text: str) -> list[tuple[str, str]] | None:
    """Every number (with the unit after it) on the model's last 'FINAL:' line, whatever its
    form: 't1 = 3 s, t2 = 4 s', 'Volume = 0.0001 m^3', 'Q takes less time (15 s vs 20 s)'.
    None when there is no FINAL line (e.g. the answer ran out of tokens) or it says none."""
    found = _FINAL.findall(text or "")
    if not found or found[-1].strip().lower().startswith("none"):
        return None
    answers = [(number, unit or "") for number, unit in _VALUE.findall(_plain(found[-1]))]
    return answers or None


# ---------- the three arms ----------
async def run_solve(conn, client: httpx.AsyncClient, item: dict) -> dict:
    document_id, subject = book_for(conn, item, "en")
    request = AskRequest(
        item["question"], item["lang"], "en", subject=subject, document_id=document_id,
        use_cache=False, mode="solve", debug=True,
    )  # fmt: skip
    start, first_shown, final = time.perf_counter(), None, {}
    async for event in answer_stream(conn, client, AnswerQueue(1, 1), request):
        if event["event"] == "token":
            first_shown = first_shown or time.perf_counter() - start
        elif event["event"] != "progress":
            final = event
    total = time.perf_counter() - start
    data = final.get("data", {})
    answers = [(a["exact"], a["unit"]) for a in data.get("math", {}).get("answers", [])]
    outcome = solve_outcome(final.get("event"), data, answers, item)
    return {
        "arm": "solve", "outcome": outcome, "math_status": data.get("math_status"),
        "reason": data.get("reason"), "answers": answers, "text": data.get("text"),
        "raw_text": data.get("raw_text"),
        "cited_pages": [c["page_start"] for c in data.get("citations", [])],
        # Not streamed (unsolved, refused): the student first sees anything at the end.
        "first_shown_s": round(first_shown or total, 2), "total_s": round(total, 2),
    }  # fmt: skip


def solve_outcome(event: str | None, data: dict, answers: list, item: dict) -> str:
    if event in (None, "error", "busy", "blocked"):
        return "error"
    if event == "refused":
        return "refused"
    if data.get("unsolved"):
        return "unsolved"
    if data.get("math_status") == "solved":
        right = matches(answers, item["gold"], TOLERANCE["solve"])
        return "checked_right" if right else "checked_wrong"
    return "answered_plain"


async def run_setup(client: httpx.AsyncClient, item: dict) -> dict:
    start = time.perf_counter()
    setup = await numerical.set_up(client, item["question"])
    answers = []
    if setup.status == "solved":
        answers = [(a.exact, a.unit) for a in setup.solution.solutions[0]]
        right = matches(answers, item["gold"], TOLERANCE["setup"])
        outcome = "checked_right" if right else "checked_wrong"
    else:
        outcome = "unsolved"
    return {
        "arm": "setup", "outcome": outcome, "math_status": setup.status, "answers": answers,
        "equations": list(setup.problem.equations) if setup.problem else None,
        "total_s": round(time.perf_counter() - start, 2),
    }  # fmt: skip


async def run_alone(client: httpx.AsyncClient, item: dict) -> dict:
    prompt = ALONE_PROMPT.read_text(encoding="utf-8").split("\n---\n", 1)[1].strip()
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": item["question"]},
    ]
    start = time.perf_counter()
    text = await complete(messages, client, ALONE_MAX_TOKENS)
    return {
        "arm": "alone", "outcome": alone_outcome(text, item), "answers": final_answers(text),
        "text": text, "total_s": round(time.perf_counter() - start, 2),
    }  # fmt: skip


def alone_outcome(text: str, item: dict) -> str:
    """right | wrong | no_final. A comparison question is also right when the FINAL line names
    the right choice ("Car 1 reaches first") and not the other one, even without the times."""
    finals = _FINAL.findall(text or "")
    choice = item.get("gold_choice")
    if choice and finals:
        line = _plain(finals[-1])
        if re.search(choice["right"], line, re.IGNORECASE) and not re.search(
            choice["wrong"], line, re.IGNORECASE
        ):
            return "right"
    answers = final_answers(text)
    if answers is None:
        return "no_final"
    right = matches(answers, item["gold"], TOLERANCE["alone"], allow_extra=True)
    return "right" if right else "wrong"


def rescore(path: Path) -> Path:
    """Score a saved run again with the current rules (no model calls): the answers and texts
    are in the file. The new file says it was rescored, and the old one is kept."""
    report = json.loads(path.read_text(encoding="utf-8"))
    items = {item["id"]: item for item in load_items()}
    for row in report["results"]:
        item = {**row, **items.get(row["id"], {})}
        if row["arm"] == "alone":
            row["outcome"] = alone_outcome(row.get("text") or "", item)
        elif row["outcome"] in ("checked_right", "checked_wrong"):
            right = matches([tuple(a) for a in row["answers"]], item["gold"], TOLERANCE[row["arm"]])
            row["outcome"] = "checked_right" if right else "checked_wrong"
    report["summary"] = summarise(report["results"])
    report["rescored_at"] = datetime.now().isoformat(timespec="seconds")
    out = path.with_name(path.stem + "-rescored.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


# ---------- summary ----------
def summarise(results: list[dict]) -> dict:
    report: dict[str, dict] = {}
    for arm in ("solve", "setup", "alone"):
        rows = [r for r in results if r["arm"] == arm]
        numeric = [r for r in rows if r["expected"] == "solve"]
        if not rows:
            continue
        counts = {
            o: sum(r["outcome"] == o for r in numeric)
            for o in sorted({r["outcome"] for r in numeric})
        }
        right = counts.get("checked_right", 0) + counts.get("right", 0)
        wrong_checked = counts.get("checked_wrong", 0)
        report[arm] = {
            "items": len(numeric),
            "outcomes": counts,
            "right": rate(right, len(numeric)),
            # Of the answers shown with a ✓, how many were wrong: the safety number.
            "wrong_among_checked": rate(wrong_checked, right + wrong_checked)
            if arm != "alone"
            else None,
        }
        if arm == "solve":
            plain = [r for r in rows if r["expected"] == "explain"]
            report[arm]["not_numerical_answered_plainly"] = rate(
                sum(r["outcome"] == "answered_plain" for r in plain), len(plain)
            )
            for key in ("first_shown_s", "total_s"):
                values = [r[key] for r in rows]
                report[arm][key] = {f"p{p}": percentile(values, p / 100) for p in (50, 95)}
    return report


# ---------- running ----------
def checkpoint(label: str, split: str) -> Path:
    return Path("eval/results") / f"num-{label}-{split}.partial.jsonl"


async def run_arm(conn, client: httpx.AsyncClient, item: dict, arm: str) -> dict:
    if arm == "solve":
        return await run_solve(conn, client, item)
    if arm == "setup":
        return await run_setup(client, item)
    return await run_alone(client, item)


async def run(split: str, label: str, arms: set[str], minutes: float) -> dict | None:
    """Every result is appended to a checkpoint file as soon as it exists, and a run skips what
    the checkpoint already holds: a run stopped part-way (the laptop ran out of memory on 20 Oct
    and the background job was killed) resumes instead of starting over. With `minutes`, it stops
    by itself after that long and returns None; running the same command again carries on."""
    items = [i for i in load_items() if i["split"] == split]
    path = checkpoint(label, split)
    results = (
        [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        if path.exists()
        else []
    )
    done = {(r["id"], r["arm"]) for r in results}
    todo = [
        (item, arm)
        for item in items
        for arm in item["arms"]
        if arm in arms and (item["id"], arm) not in done
    ]
    deadline = time.monotonic() + minutes * 60 if minutes else None
    conn = connect(settings.db_path)
    async with httpx.AsyncClient() as client:
        await require_quiet(client)
        props = (await client.get(f"{settings.llm_url}/props")).json()
        await numerical.mathcheck.start()
        await run_alone(client, {"question": "What is 2 + 2?", "gold": []})  # GPU warm-up
        for index, (item, arm) in enumerate(todo):
            if deadline and time.monotonic() > deadline:
                print(f"time budget used: {len(todo) - index} left; run the same command to resume")
                numerical.mathcheck.stop()
                return None
            result = {**item, **await run_arm(conn, client, item, arm)}
            with path.open("a", encoding="utf-8") as saved:
                saved.write(json.dumps(result, ensure_ascii=False) + "\n")
            results.append(result)
            print(
                f"{item['id']:9} {arm:6} {result['outcome']:15} {result.get('math_status') or ''}",
                flush=True,
            )
        numerical.mathcheck.stop()
    return {
        "label": label, "run_at": datetime.now().isoformat(timespec="seconds"),
        "split": split, "items_file": str(ITEMS), "db_path": str(settings.db_path),
        "model_path": props.get("model_path"), "setup_prompt": numerical.SETUP_PROMPT,
        "explain_prompt": numerical.EXPLAIN_PROMPT, "alone_prompt": ALONE_PROMPT.name,
        "verified_items": sum(bool(i.get("verified")) for i in items), "items": len(items),
        # Resumed runs restart the warm-up but not the server: timings stay indicative.
        "resumed": len(done) > 0, "summary": summarise(results), "results": results,
    }  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze")
    sub.add_parser("verify")
    again = sub.add_parser("rescore")
    again.add_argument("result_file", type=Path)
    go = sub.add_parser("run")
    go.add_argument("--split", choices=("dev", "test"), required=True)
    go.add_argument("--label", required=True)
    go.add_argument("--arms", default="solve,setup,alone")
    go.add_argument("--minutes", type=float, default=0, help="stop after this long; 0 = no limit")
    args = parser.parse_args()
    if args.command == "freeze":
        freeze()
    elif args.command == "verify":
        print("unchanged" if verify() else "CHANGED")
    elif args.command == "rescore":
        print("written", rescore(args.result_file))
    else:
        check_safe_to_run(None, allow_live_db=False)
        if args.split == "test" and not verify():
            raise SystemExit("frozen numerical test items changed: no test run")
        arms = set(args.arms.split(","))
        report = asyncio.run(run(args.split, args.label, arms, args.minutes))
        if report is None:
            raise SystemExit(3)  # stopped on its time budget: run again to resume
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        out = Path("eval/results") / f"num-{args.label}-{args.split}-{stamp}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        checkpoint(args.label, args.split).unlink()  # everything is in the result file now
        print(json.dumps(report["summary"], ensure_ascii=False, indent=1), f"\nwritten {out}")


if __name__ == "__main__":
    main()
