"""Answer-quality grading: a human sheet, a local judge model, and their agreement.

    # 1. a grading sheet from a result file (dev: a stratified sample for calibration)
    uv run python -m eval.grade export eval/results/<run>.json --sample 60 --out data/eval-private/grade_human.csv
    # 2. the same rows graded by a local judge (Qwen3-4B on its own llama-server, Gemma stopped)
    uv run python -m eval.grade judge data/eval-private/grade_human.csv --judge-url http://127.0.0.1:8083 --out data/eval-private/grade_judge.csv
    # 3. agreement (quadratic-weighted kappa per criterion) and mean scores with 95% intervals
    uv run python -m eval.grade agreement data/eval-private/grade_human.csv data/eval-private/grade_judge.csv
    uv run python -m eval.grade summary data/eval-private/grade_judge.csv

Criteria (anchors in eval/prompts/judge_v1.md): correct 0-2 against the item's key facts;
faithful 0-2, the RAGAS idea of claims supported by the cited sources, graded per answer;
relevant 1-3; and three tutor criteria adapted from MRBench (Maurya et al., NAACL 2025):
guidance, clarity for a 13-year-old, tone; and flawed (0/1), the human grader's "a teacher
would want something fixed" flag. Check-my-understanding items add mistake_found,
mistake_located (MRBench mistake identification / location) and false_correction.
The judge is used only if kappa against the human grader is >= 0.6 on correct, faithful and
flawed (DECISIONS 19 Oct, fixed before any judge score was seen).
Sheets contain textbook text (cited sources): they live in data/eval-private/ only.
"""

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

import httpx

from eval.metrics import mean_with_ci, weighted_kappa
from eval.review_sheet import indexed_text
from eval.split import ITEM_FILES, load
from ruralminds.config import settings
from ruralminds.db import connect

CRITERIA = {
    "correct": [0, 1, 2],
    "faithful": [0, 1, 2],
    "relevant": [1, 2, 3],
    "guidance": [1, 2, 3],
    "clarity": [1, 2, 3],
    "tone": [1, 2, 3],
    "flawed": [0, 1],
}
CHECK_CRITERIA = {"mistake_found": [0, 1], "mistake_located": [0, 1], "false_correction": [0, 1]}
ALL_CRITERIA = CRITERIA | CHECK_CRITERIA
GATE_CRITERIA = ("correct", "faithful", "flawed")
# The human sheet of 19 Oct named the flag column "mistakes_found" (not the check criterion).
COLUMN_ALIASES = {"mistakes_found": "flawed"}
INFO = [
    "id",
    "arm",
    "style",
    "expected",
    "category",
    "history",
    "question",
    "key_facts",
    "answer",
    "sources",
]
JUDGE_PROMPT = Path(__file__).parent / "prompts" / "judge_v2.md"
KAPPA_FLOOR = 0.6


# ---------- export ----------
def gradable(results: list[dict]) -> list[dict]:
    """Answers a student actually saw (refusals are scored automatically, not graded)."""
    return [r for r in results if not r["refused"] and r.get("answer")]


def stratified_sample(rows: list[dict], size: int) -> list[dict]:
    """Round-robin over (arm, style) groups in a seeded order: every kind of item gets graded."""
    groups: dict[tuple, list[dict]] = {}
    for row in sorted(rows, key=lambda r: hashlib.sha256(f"grade:{r['id']}".encode()).hexdigest()):
        groups.setdefault((row.get("arm"), row.get("style")), []).append(row)
    picked: list[dict] = []
    while len(picked) < size and any(groups.values()):
        for key in sorted(groups, key=str):
            if groups[key] and len(picked) < size:
                picked.append(groups[key].pop(0))
    return picked


def answer_text(result: dict) -> str:
    parts = [result.get("answer") or ""]
    for label, key in (("EXAMPLE", "example"), ("CHECK", "check"), ("ANSWERS", "quiz_answers")):
        if result.get(key):
            parts.append(f"{label}: {result[key]}")
    return "\n".join(parts)


def sources_text(conn, result: dict) -> str:
    pages = sorted(
        {p for _, start, end in result.get("citations", []) for p in range(start, end + 1)}
    )
    return indexed_text(conn, result["book_id"], pages) if pages else "(no citation)"


def history_text(turns: list[dict]) -> str:
    """Earlier turns of a follow-up item: without them a follow-up cannot be graded."""
    return "\n".join(f"Student: {t['question']}\nApp: {t['answer']}" for t in turns)


def item_histories() -> dict[str, str]:
    histories = {}
    for path in ITEM_FILES:
        if path.exists():
            for item in load(path):
                if item.get("history"):
                    histories[item["id"]] = history_text(item["history"])
    return histories


def export(result_file: Path, sample: int | None, out: Path) -> int:
    results = json.loads(result_file.read_text(encoding="utf-8"))["results"]
    rows = gradable(results)
    rows = stratified_sample(rows, sample) if sample else rows
    histories = item_histories()
    conn = connect(settings.db_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(INFO + list(ALL_CRITERIA))
        for row in rows:
            info = {
                **row,
                "history": histories.get(row["id"], ""),
                "answer": answer_text(row),
                "sources": sources_text(conn, row),
            }
            writer.writerow([info.get(k) or "" for k in INFO] + [""] * len(ALL_CRITERIA))
    return len(rows)


# ---------- judge ----------
def judge_messages(row: dict) -> list[dict[str, str]]:
    prompt = JUDGE_PROMPT.read_text(encoding="utf-8").split("\n---\n", 1)[1].strip()
    check = (
        "\n(The student's message is a claim to check.)" if row.get("category") == "check" else ""
    )
    earlier = f"Earlier in this chat:\n{row['history']}\n\n" if row.get("history") else ""
    content = (
        f"{earlier}Student's message: {row['question']}{check}\nKey facts the answer should give: "
        f"{row['key_facts']}\n\nSources:\n{row['sources']}\n\nAnswer to grade:\n{row['answer']}"
    )
    return [{"role": "system", "content": prompt}, {"role": "user", "content": content}]


def parse_scores(reply: str) -> dict[str, int]:
    """Last JSON object in the reply (after any <think> block), keeping only known criteria
    with in-range values. Reasoning judges may quote example JSON before their verdict."""
    reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL)
    found = re.findall(r"\{[^{}]*\}", reply)
    try:
        raw = json.loads(found[-1]) if found else {}
    except json.JSONDecodeError:
        return {}
    return {
        k: int(v)
        for k, v in raw.items()
        if k in ALL_CRITERIA and isinstance(v, int | float) and int(v) in ALL_CRITERIA[k]
    }


def judged_row(row: dict, reply: str) -> dict:
    """The judge's scores only. Every criterion is blanked first: a reply that fails to parse
    must leave an empty cell, never the human grade the sheet was read from (that would make
    agreement compare the grader with themselves)."""
    judged = {**row, **dict.fromkeys(ALL_CRITERIA, "")}
    judged.update({k: str(v) for k, v in parse_scores(reply).items()})
    return judged


def judge(
    sheet: Path, judge_url: str, out: Path, model: str | None = None, max_tokens: int = 160
) -> dict[str, int]:
    """Saves after every row and resumes from `out`: a long Malayalam prompt can take minutes
    on the iGPU, and a crash must not lose the rows already judged. `model` names the judge
    on a server that hosts several (Ollama); reasoning judges need a larger max_tokens."""
    done = {row["id"]: row for row in read_sheet(out)} if out.exists() else {}
    rows = []
    histories = item_histories()  # sheets exported before 19 Oct have no history column
    with httpx.Client(timeout=1200) as client:
        for row in read_sheet(sheet):
            if row["id"] in done:
                rows.append(done[row["id"]])
                continue
            row["history"] = row.get("history") or histories.get(row["id"], "")
            payload = {
                "messages": judge_messages(row),
                "temperature": 0.0,
                "max_tokens": max_tokens,
            } | ({"model": model} if model else {})
            reply = client.post(f"{judge_url}/v1/chat/completions", json=payload)
            reply.raise_for_status()
            rows.append(judged_row(row, reply.json()["choices"][0]["message"]["content"]))
            write_sheet(rows, out)
    return {name: sum(not r[name] for r in rows) for name in CRITERIA} | {"rows": len(rows)}


# ---------- agreement and summary ----------
def read_sheet(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [
            {COLUMN_ALIASES.get(k, k): v for k, v in row.items()} for row in csv.DictReader(handle)
        ]


def grade_value(value: str, labels: list[int]) -> int | None:
    """A grade as an int on the criterion's scale; out-of-range grades are clamped to it
    (one human relevant=0 on 19 Oct, read as 1 per DECISIONS)."""
    if not (value or "").strip():
        return None
    return min(max(int(value), labels[0]), labels[-1])


def write_sheet(rows: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INFO + list(ALL_CRITERIA))
        writer.writeheader()
        writer.writerows({k: row.get(k, "") for k in INFO + list(ALL_CRITERIA)} for row in rows)


def calibration_half(row_id: str) -> str:
    """Seeded split of the calibration rows: judges are compared on `select`, and only the
    chosen judge's kappa on `confirm` is reported, so choosing does not inflate it."""
    digest = hashlib.sha256(f"judge-half:{row_id}".encode()).hexdigest()
    return "select" if int(digest, 16) % 2 == 0 else "confirm"


def agreement(human: list[dict], machine: list[dict], half: str = "all") -> dict[str, dict]:
    if half != "all":
        human = [row for row in human if calibration_half(row["id"]) == half]
    by_id = {row["id"]: row for row in machine}
    report: dict[str, dict] = {}
    for name, labels in ALL_CRITERIA.items():
        pairs = [
            (grade_value(h.get(name, ""), labels), grade_value(m.get(name, ""), labels))
            for h in human
            if (m := by_id.get(h["id"])) is not None
        ]
        pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
        if not pairs:
            continue
        first, second = zip(*pairs, strict=True)
        kappa = weighted_kappa(list(first), list(second), labels)
        report[name] = {
            "n": len(pairs),
            "weighted_kappa": kappa,
            "exact_agreement": round(sum(a == b for a, b in pairs) / len(pairs), 3),
            "passes": kappa is not None and kappa >= KAPPA_FLOOR,
        }
    report["judge_usable"] = {
        "rule": f"kappa >= {KAPPA_FLOOR} on {', '.join(GATE_CRITERIA)}",
        "usable": all(report.get(name, {}).get("passes") for name in GATE_CRITERIA),
    }
    return report


def summary(rows: list[dict]) -> dict[str, dict]:
    """Mean score per criterion, scaled to 0-1 so criteria with different ranges compare."""
    report = {}
    for name, labels in ALL_CRITERIA.items():
        low, high = labels[0], labels[-1]
        grades = [grade_value(r.get(name, ""), labels) for r in rows]
        values = [(g - low) / (high - low) for g in grades if g is not None]
        if values:
            report[name] = mean_with_ci(values)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Grade answer quality (human sheet, local judge)")
    sub = parser.add_subparsers(dest="action", required=True)
    exp = sub.add_parser("export")
    exp.add_argument("result", type=Path)
    exp.add_argument("--sample", type=int)
    exp.add_argument("--out", type=Path, required=True)
    jud = sub.add_parser("judge")
    jud.add_argument("sheet", type=Path)
    jud.add_argument("--judge-url", required=True)
    jud.add_argument("--judge-model", help="model name on a multi-model server (Ollama)")
    jud.add_argument("--max-tokens", type=int, default=160)
    jud.add_argument("--out", type=Path, required=True)
    agr = sub.add_parser("agreement")
    agr.add_argument("human", type=Path)
    agr.add_argument("judge", type=Path)
    agr.add_argument("--half", choices=["all", "select", "confirm"], default="all")
    summ = sub.add_parser("summary")
    summ.add_argument("sheet", type=Path)
    args = parser.parse_args()
    if args.action == "export":
        print(export(args.result, args.sample, args.out), "rows ->", args.out)
    elif args.action == "judge":
        missing = judge(args.sheet, args.judge_url, args.out, args.judge_model, args.max_tokens)
        print("missing grades per criterion:", missing)
        print("judged ->", args.out)
    elif args.action == "agreement":
        report = agreement(read_sheet(args.human), read_sheet(args.judge), args.half)
        print(json.dumps(report, indent=2))
    else:
        print(json.dumps(summary(read_sheet(args.sheet)), indent=2))


if __name__ == "__main__":
    main()
