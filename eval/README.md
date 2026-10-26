# Evaluation

Every number RuralMinds quotes comes from a run in this folder, listed with its file and validity in [`docs/workstreams/evaluation-register.md`](../docs/workstreams/evaluation-register.md).

## What is in the repository

| Path | What |
|---|---|
| `datasets/v2/` | Eval v2: 342 items (Social Science EN 103, Science EN 71, Social Science ML 52, Manglish 40, refusal 39, intents 37), drafted with an AI assistant and reviewed one by one by the team; 336 are marked verified (6 refusal items are not). With the 18 private IndicQuest items below, that makes the 354 verified items of the frozen split. Each item has gold pages and short key facts. `split_manifest.json` freezes the 107 dev / 247 test split with a sha256 per file. |
| `datasets/num/` | 51 items for the "Solve step by step" chip, gold answers solved by hand: the 38 original items plus 13 fresh test problems (`num-t01`–`t13`) written after the agreement guard was built; 47 are checked by the team (`num-u02`, ambiguous wording, and `num-n01`–`n03` are not). Split frozen in `split_manifest.json`. |
| `samples/` | The first draft sets from 12–14 Oct (see `samples/README.md`). |
| `results/` | One JSON file per run: settings, per-item answers, pages and timings, and summary metrics. |
| `prompts/` | Prompts used only by the eval (judges, the model-alone numerical arm). |

## What stays local (`data/eval-private/`, git-ignored)

- 18 refusal items from IndicQuest (`refusal_indicquest.jsonl`), until their licence is confirmed. `eval.split verify` reads this file. Note: the question text of the IndicQuest items that were run also appears in three result files (`baseline-v2-test-…-1709`, `baseline-v2-dev-…-1950`, `m6-dev-…-2313`).
- Human grading and review sheets (`grade_*.csv`, `review_*.csv`).
- The v1 draft sets at the top of `datasets/` (`datasets/*.jsonl`).

## Rules

- Run `uv run python -m eval.split verify` before any reported run.
- Tune on the dev split only. The test split is read once for the baseline (19 Oct) and once for the final run.
- Restart the chat server before a measured run (its prompt cache speeds up repeats), and keep nothing else open on the laptop.
- Answer quality comes from human grades only. The AI judges failed the agreement rule fixed in advance (kappa ≥ 0.6).

## Commands

```powershell
uv run python -m eval.split verify
uv run python -m eval.run --testset eval/datasets/v2/ss_en.jsonl eval/datasets/v2/sci_en.jsonl eval/datasets/v2/ss_ml.jsonl eval/datasets/v2/manglish.jsonl eval/datasets/v2/refusal.jsonl eval/datasets/v2/intents.jsonl --split dev --label my-run
uv run python -m eval.bench --levels 1 2 4 8 --label my-bench      # load bench (--rates for random arrivals)
uv run python -m eval.bench --retrieval                            # whole-book vs chapter search time
uv run python -m eval.numerical run --split dev --label my-run     # numericals: solve, setup, alone arms
uv run python -m eval.grade export eval/results/<run>.json --sample 40 --out data/eval-private/<sheet>.csv
```
