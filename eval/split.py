"""Freeze (and later verify) the dev/test split of the eval v2 item files.

    uv run python -m eval.split freeze   # once; writes `split` into every item + the manifest
    uv run python -m eval.split verify   # before any reported run: test items unchanged?

Rules (DECISIONS 2026-10-18):
- Parallel versions stay together: an English item, its Malayalam version and its Manglish twins
  form one group (`parallel_of`), so we never tune on a question and "test" on its translation.
- Groups asking a fact the v1 prompts/threshold were tuned on go to dev (FORCED_DEV).
- Otherwise ~30% of the groups in each stratum (file, style, expected, category) go to dev,
  chosen by a seeded hash: deterministic, and nobody picks which items land in test.
- The manifest stores a sha256 over the test items; `verify` fails if any of them changed.
"""

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

ITEM_FILES = [
    Path("eval/datasets/v2") / name
    for name in (
        "ss_en.jsonl",
        "sci_en.jsonl",
        "ss_ml.jsonl",
        "manglish.jsonl",
        "refusal.jsonl",
        "intents.jsonl",
    )
] + [Path("data/eval-private/refusal_indicquest.jsonl")]  # licence unconfirmed: kept local
MANIFEST = Path("eval/datasets/v2/split_manifest.json")
SEED = "ruralminds-eval-v2"
DEV_SHARE = 0.3
# Facts the v1 dev questions (bakeoff, tutor, final_check, manglish) were tuned on.
FORCED_DEV = {
    "ss-en-001",
    "ss-en-007",
    "ss-en-013",
    "ss-en-015",
    "ss-en-020",
    "ss-en-021",
    "ss-en-035",
    "ss-en-040",
    "ss-en-077",
    "intent-037",
}
FINGERPRINT_KEYS = ("id", "question", "gold_pages", "answerable", "expected", "history")


def group_of(item: dict) -> str:
    return item.get("parallel_of") or item["id"]


def stratum(item: dict, source: str) -> tuple:
    return (source, item.get("style"), item.get("expected"), item.get("category"))


def assign(files: dict[str, list[dict]]) -> dict[str, str]:
    """group -> 'dev' | 'test'. A group's stratum is that of its root item (the one it names)."""
    roots = {item["id"]: (item, name) for name, items in files.items() for item in items}
    strata: dict[tuple, list[str]] = defaultdict(list)
    for group in sorted({group_of(i) for items in files.values() for i in items}):
        root, name = roots.get(group, (None, None))
        if root is None:  # parallel item whose root is missing: its own stratum
            root, name = next(
                (i, n) for n, items in files.items() for i in items if group_of(i) == group
            )
        strata[stratum(root, name)].append(group)
    split = {}
    for groups in strata.values():
        ordered = sorted(groups, key=lambda g: hashlib.sha256(f"{SEED}:{g}".encode()).hexdigest())
        wanted = round(DEV_SHARE * len(groups))
        forced = [g for g in ordered if g in FORCED_DEV]
        dev = set(forced) | set(
            [g for g in ordered if g not in FORCED_DEV][: max(0, wanted - len(forced))]
        )
        split.update({g: "dev" if g in dev else "test" for g in groups})
    return split


def fingerprint(items: list[dict]) -> str:
    """sha256 over the test items' identity and content, independent of file order."""
    rows = sorted(
        json.dumps({k: i.get(k) for k in FINGERPRINT_KEYS}, ensure_ascii=False, sort_keys=True)
        for i in items
        if i.get("split") == "test" and i.get("status") != "dropped"
    )
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def freeze() -> dict:
    files = {path.as_posix(): load(path) for path in ITEM_FILES}
    split = assign(files)
    manifest = {"seed": SEED, "dev_share": DEV_SHARE, "forced_dev": sorted(FORCED_DEV), "files": {}}
    for name, items in files.items():
        for item in items:
            item["split"] = split[group_of(item)]
        Path(name).write_text(
            "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8"
        )
        live = [i for i in items if i.get("status") != "dropped"]
        manifest["files"][name] = {
            "dev": sum(i["split"] == "dev" for i in live),
            "test": sum(i["split"] == "test" for i in live),
            "test_sha256": fingerprint(items),
        }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify() -> list[str]:
    """Names of files whose test items differ from the frozen manifest."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return [
        name
        for name, frozen in manifest["files"].items()
        if fingerprint(load(Path(name))) != frozen["test_sha256"]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze or verify the eval v2 dev/test split")
    parser.add_argument("action", choices=["freeze", "verify"])
    args = parser.parse_args()
    if args.action == "freeze":
        if MANIFEST.exists():
            raise SystemExit(
                f"{MANIFEST} exists: the split is already frozen (delete it only by decision)"
            )
        print(json.dumps(freeze()["files"], indent=2))
    else:
        changed = verify()
        raise SystemExit(f"test items changed in: {changed}" if changed else 0)


if __name__ == "__main__":
    main()
