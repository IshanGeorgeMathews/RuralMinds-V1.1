"""Print an eval result file as compact tables (one row per group, 95% intervals in brackets).

uv run python -m eval.report eval/results/baseline-v2-dev-gemma4-e2b-20261018-1855.json
uv run python -m eval.report <before.json> <after.json>     # side by side, per group
"""

import argparse
import json
from pathlib import Path

COLUMNS = [
    ("items", lambda s: s["items"]),
    ("hit@3", lambda s: _rate(s["retrieval"]["hit_at_3"])),
    ("MRR", lambda s: _mean(s["retrieval"]["mrr"])),
    ("answered", lambda s: _rate(s["answered_when_answerable"])),
    ("cited ok", lambda s: _rate(s["citation_supported"])),
    ("refuse recall", lambda s: _rate(s["refusal"]["recall"])),
    ("false refusal", lambda s: _rate(s["refusal"]["false_refusal_rate"])),
    ("intent", lambda s: _rate(s.get("intent_correct"))),
    ("right chapter", lambda s: _rate(s.get("chapter_correct"))),
    ("3rd script", lambda s: _rate(s.get("third_script"))),
    ("1st word p50/p95", lambda s: f"{s['ttft_s']['p50']}/{s['ttft_s']['p95']}"),
]


def _rate(value: dict | None) -> str:
    if not value or not value.get("n"):
        return "-"
    low, high = value["ci95"]
    return f"{value['hits']}/{value['n']} [{low:.2f}-{high:.2f}]"


def _mean(value: dict | None) -> str:
    return "-" if not value or value.get("mean") is None else f"{value['mean']:.2f}"


def table(summary: dict, title: str) -> str:
    rows = [[name for name, _ in COLUMNS]]
    rows += [[group] + [str(get(stats)) for _, get in COLUMNS] for group, stats in summary.items()]
    rows[0] = [title] + rows[0]
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return "\n".join(
        "  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)) for row in rows
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Show eval result files as tables")
    parser.add_argument("results", type=Path, nargs="+")
    args = parser.parse_args()
    for path in args.results:
        report = json.loads(path.read_text(encoding="utf-8"))
        print(
            f"\n== {path.name}  model={Path(report.get('model_path') or '').name or '?'}"
            f"  split={report.get('split')}  prompt={report.get('prompt_version')}"
        )
        for key, title in (
            ("summary", "group"),
            ("by_style", "style"),
            ("by_expected", "expected"),
        ):
            if key in report:
                print(table(report[key], title), "\n")


if __name__ == "__main__":
    main()
