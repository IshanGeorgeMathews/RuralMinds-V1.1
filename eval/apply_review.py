"""Apply a reviewer's verdicts from a review sheet to an eval item file.

    uv run python -m eval.apply_review --items eval/datasets/v2/ss_en.jsonl \
        --sheet data/eval-private/review_ss_en.csv

Verdicts (first letter is enough, any case): ok -> verified; drop -> status "dropped" (kept in the
file so ids stay stable, skipped by the eval); fix -> stays unverified and its note is printed so
the item can be corrected, then reviewed again. Rows left blank change nothing.
"""

import argparse
import csv
import json
from pathlib import Path

VERDICT_COLUMN = 1  # column B of every review sheet
NOTE_COLUMN = 2


def read_verdicts(sheet: Path) -> dict[str, tuple[str, str]]:
    """id -> (verdict, note). utf-8-sig: the sheets carry a BOM so Excel shows Malayalam."""
    with sheet.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))[1:]
    verdicts = {}
    for row in rows:
        if len(row) <= NOTE_COLUMN or not row[0].strip():
            continue
        verdict = row[VERDICT_COLUMN].strip().lower()[:1]
        if verdict:
            verdicts[row[0].strip()] = (verdict, row[NOTE_COLUMN].strip())
    return verdicts


def apply(items: list[dict], verdicts: dict[str, tuple[str, str]]) -> list[str]:
    """Update items in place; return the fix notes to act on."""
    fixes = []
    for item in items:
        verdict, note = verdicts.get(item["id"], ("", ""))
        if verdict == "o":
            item["verified"] = True
            item.pop("status", None)
        elif verdict == "d":
            item["verified"] = False
            item["status"] = "dropped"
        elif verdict == "f":
            item["verified"] = False
            item.pop("status", None)
            fixes.append(f"{item['id']}: {note or '(no note)'}")
    return fixes


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply review verdicts to an eval item file")
    parser.add_argument("--items", type=Path, required=True)
    parser.add_argument("--sheet", type=Path, required=True)
    args = parser.parse_args()
    lines = args.items.read_text(encoding="utf-8").splitlines()
    items = [json.loads(line) for line in lines if line]
    verdicts = read_verdicts(args.sheet)
    unknown = sorted(set(verdicts) - {item["id"] for item in items})
    if unknown:
        raise SystemExit(f"sheet has ids not in {args.items}: {unknown[:5]}")
    fixes = apply(items, verdicts)
    text = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items)
    args.items.write_text(text, encoding="utf-8")
    verified = sum(item.get("verified", False) for item in items)
    dropped = sum(item.get("status") == "dropped" for item in items)
    print(f"{len(verdicts)} verdicts: {verified} verified, {dropped} dropped, {len(fixes)} to fix")
    for fix in fixes:
        print("FIX", fix)


if __name__ == "__main__":
    main()
