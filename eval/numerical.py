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

from eval.metrics import percentile, rate
from eval.run import book_for, check_safe_to_run, require_quiet
from ruralminds import agreement, numerical
from ruralminds.answer import AnswerQueue, AskRequest, answer_stream
from ruralminds.config import settings
from ruralminds.db import connect

ITEMS = Path("eval/datasets/num/numerical.jsonl")
MANIFEST = Path("eval/datasets/num/split_manifest.json")
SEED = "ruralminds-num-v1"
DEV_SHARE = 0.3
FINGERPRINT_KEYS = ("id", "question", "gold", "expected", "arms")
EXACT = agreement.EXACT
TOLERANCE = {"solve": EXACT, "setup": EXACT, "alone": agreement.ROUNDING}  # the model rounds


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


# ---------- comparing answers with gold: the app's own rules (ruralminds/agreement.py) ----------
quantity, same_value, matches = agreement.quantity, agreement.same_value, agreement.matches
final_answers = agreement.final_answers


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
        "raw_text": data.get("raw_text"), "math": data.get("math"),
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
    """The model on its own: the same call the app makes for its second opinion."""
    start = time.perf_counter()
    text = await agreement.second_opinion(client, item["question"])
    return {
        "arm": "alone", "outcome": alone_outcome(text, item), "answers": final_answers(text),
        "text": text, "total_s": round(time.perf_counter() - start, 2),
    }  # fmt: skip


def alone_outcome(text: str, item: dict) -> str:
    """right | wrong | no_final. A comparison question is also right when the FINAL line names
    the right choice ("Car 1 reaches first") and not the other one, even without the times."""
    finals = agreement.final_lines(text)
    choice = item.get("gold_choice")
    if choice and finals:
        line = agreement.plain(finals[-1])
        if re.search(choice["right"], line, re.IGNORECASE) and not re.search(
            choice["wrong"], line, re.IGNORECASE
        ):
            return "right"
    answers = final_answers(text)
    if answers is None:
        # A FINAL line with no number ("Anil's scooter is faster") is an answer, just a wrong one.
        return (
            "wrong" if finals and not finals[-1].strip().lower().startswith("none") else "no_final"
        )
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
        "explain_prompt": numerical.EXPLAIN_PROMPT, "alone_prompt": agreement.CHECK_PROMPT,
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
