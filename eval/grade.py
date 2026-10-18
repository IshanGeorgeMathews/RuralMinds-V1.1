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
guidance, clarity for a 13-year-old, tone. Check-my-understanding items add mistake_found,
mistake_located (MRBench mistake identification / location) and false_correction.
Judge scores are only reported when kappa against the human grader is >= 0.6 (DECISIONS 17 Oct).
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
from ruralminds.config import settings
from ruralminds.db import connect

CRITERIA = {
    "correct": [0, 1, 2],
    "faithful": [0, 1, 2],
    "relevant": [1, 2, 3],
    "guidance": [1, 2, 3],
    "clarity": [1, 2, 3],
    "tone": [1, 2, 3],
}
CHECK_CRITERIA = {"mistake_found": [0, 1], "mistake_located": [0, 1], "false_correction": [0, 1]}
ALL_CRITERIA = CRITERIA | CHECK_CRITERIA
INFO = ["id", "arm", "style", "expected", "category", "question", "key_facts", "answer", "sources"]
JUDGE_PROMPT = Path(__file__).parent / "prompts" / "judge_v1.md"
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


def export(result_file: Path, sample: int | None, out: Path) -> int:
    results = json.loads(result_file.read_text(encoding="utf-8"))["results"]
    rows = gradable(results)
    rows = stratified_sample(rows, sample) if sample else rows
    conn = connect(settings.db_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(INFO + list(ALL_CRITERIA))
        for row in rows:
            info = {**row, "answer": answer_text(row), "sources": sources_text(conn, row)}
            writer.writerow([info.get(k) or "" for k in INFO] + [""] * len(ALL_CRITERIA))
    return len(rows)


# ---------- judge ----------
def judge_messages(row: dict) -> list[dict[str, str]]:
    prompt = JUDGE_PROMPT.read_text(encoding="utf-8").split("\n---\n", 1)[1].strip()
    check = (
        "\n(The student's message is a claim to check.)" if row.get("category") == "check" else ""
    )
    content = (
        f"Student's message: {row['question']}{check}\nKey facts the answer should give: "
        f"{row['key_facts']}\n\nSources:\n{row['sources']}\n\nAnswer to grade:\n{row['answer']}"
    )
    return [{"role": "system", "content": prompt}, {"role": "user", "content": content}]


def parse_scores(reply: str) -> dict[str, int]:
    """First JSON object in the reply, keeping only known criteria with in-range values."""
    match = re.search(r"\{.*?\}", reply, re.DOTALL)
    try:
        raw = json.loads(match.group()) if match else {}
    except json.JSONDecodeError:
        return {}
    return {
        k: int(v)
        for k, v in raw.items()
        if k in ALL_CRITERIA and isinstance(v, int | float) and int(v) in ALL_CRITERIA[k]
    }


def judge(sheet: Path, judge_url: str, out: Path) -> int:
    rows = read_sheet(sheet)
    with httpx.Client(timeout=300) as client:
        for row in rows:
            payload = {"messages": judge_messages(row), "temperature": 0.0, "max_tokens": 120}
            reply = client.post(f"{judge_url}/v1/chat/completions", json=payload)
            reply.raise_for_status()
            scores = parse_scores(reply.json()["choices"][0]["message"]["content"])
            row.update({k: str(v) for k, v in scores.items()})
    write_sheet(rows, out)
    return len(rows)


# ---------- agreement and summary ----------
def read_sheet(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_sheet(rows: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INFO + list(ALL_CRITERIA))
        writer.writeheader()
        writer.writerows({k: row.get(k, "") for k in INFO + list(ALL_CRITERIA)} for row in rows)


def agreement(human: list[dict], machine: list[dict]) -> dict[str, dict]:
    by_id = {row["id"]: row for row in machine}
    report = {}
    for name, labels in ALL_CRITERIA.items():
        pairs = [
            (int(h[name]), int(by_id[h["id"]][name]))
            for h in human
            if h.get(name, "").strip() and by_id.get(h["id"], {}).get(name, "").strip()
        ]
        if not pairs:
            continue
        first, second = zip(*pairs, strict=True)
        kappa = weighted_kappa(list(first), list(second), labels)
        report[name] = {
            "n": len(pairs),
            "weighted_kappa": kappa,
            "exact_agreement": round(sum(a == b for a, b in pairs) / len(pairs), 3),
            "judge_usable": kappa is not None and kappa >= KAPPA_FLOOR,
        }
    return report


def summary(rows: list[dict]) -> dict[str, dict]:
    """Mean score per criterion, scaled to 0-1 so criteria with different ranges compare."""
    report = {}
    for name, labels in ALL_CRITERIA.items():
        low, high = labels[0], labels[-1]
        values = [(int(r[name]) - low) / (high - low) for r in rows if r.get(name, "").strip()]
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
    jud.add_argument("--out", type=Path, required=True)
    agr = sub.add_parser("agreement")
    agr.add_argument("human", type=Path)
    agr.add_argument("judge", type=Path)
    summ = sub.add_parser("summary")
    summ.add_argument("sheet", type=Path)
    args = parser.parse_args()
    if args.action == "export":
        print(export(args.result, args.sample, args.out), "rows ->", args.out)
    elif args.action == "judge":
        print(judge(args.sheet, args.judge_url, args.out), "rows judged ->", args.out)
    elif args.action == "agreement":
        print(json.dumps(agreement(read_sheet(args.human), read_sheet(args.judge)), indent=2))
    else:
        print(json.dumps(summary(read_sheet(args.sheet)), indent=2))


if __name__ == "__main__":
    main()
