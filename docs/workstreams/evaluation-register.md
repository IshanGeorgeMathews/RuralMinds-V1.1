# Evaluation register (all areas except exam revision)

Every number RuralMinds may quote must appear here with its file. "Valid" means the run met the measurement rules below; "indicative" means valid but too small to claim more than a direction. Exam revision has its own measurements in [exam-revision.md](exam-revision.md).

## Measurement rules (agreed 17–19 Oct)

- **Datasets.** Eval v2: 354 verified items (Social Science EN 103, Science EN 71, Social Science ML 52, Manglish 40, refusal 39 + 18 private IndicQuest, intents 37), frozen split 107 dev / 247 test (`eval/split.py`, `split_manifest.json`; `python -m eval.split verify` before any reported run). Items are labelled by style (lookup / reasoning / applied / compare) and expected outcome (answer / partial / refuse). Cross-book questions are out of scope.
- **Dev for tuning, test read twice only:** baseline (done 19 Oct) and final.
- **Metrics:** hit@k, recall@k, MRR, nDCG@5 (page overlap); refusal precision/recall/F1 (positive = should refuse) and false-refusal rate; first-word (TTFT) and total time p50/p95/p99; serving: answers/min, goodput (first word within 15 s), shed requests. Rates carry Wilson 95% intervals, means a seeded bootstrap interval (`eval/metrics.py`).
- **Answer quality comes from human grades only.** Three judges failed the pre-registered kappa ≥ 0.6 rule (below); a judge may only point the grader at rows to re-check.
- **Clean runs:** restart the chat server (its prompt cache otherwise speeds up repeats), nothing else open on the machine, plugged in unless measuring battery.

## A. Done

### A1. Model and runtime (12–13 Oct)

| What | Result | File / source | Validity |
|---|---|---|---|
| Gemma 4 E2B prefill, CPU vs Vulkan iGPU (llama-bench pp512) | 53 vs 146 tok/s; flash attention on → 35–46 tok/s | DECISIONS 12 Oct | valid (tool benchmark) |
| Context budget 600 vs 900 tokens, first word | 4.7–10.7 s vs 14–23 s | DECISIONS 12 Oct | indicative (single runs, memory pressure) |
| Bake-off Gemma 4 E2B vs Qwen3-4B, 20 dev items (10 EN, 10 ML) | EN tied (8/8 answered, 7/8 cited); ML Gemma 8/8 answered + 8/8 cited vs Qwen 7/8 + 7/8 | `bakeoff-*-20261012-*.json` | indicative; winner Gemma, recorded in DECISIONS (13 Oct line, written 20 Oct) |

### A2. Retrieval

| What | Result | File | Validity |
|---|---|---|---|
| Whole book vs one chapter search time (30 dev questions) | p50 177 vs 164 ms, p95 264 vs 257 ms → no whole-book limit | `retrieval-timing-20261018-1953.json` | valid |
| **Test baseline, all arms** (19 Oct) | hit@3 185/210 (0.83–0.92), MRR 0.80 | `baseline-v2-test-gemma4-e2b-20261019-1709.json` | **valid — the "before"** |
| … by arm | SS EN 66/71; Science EN 46/50; SS ML 35/38; Manglish→EN book 8/12, →ML book 8/12 | same | valid; Manglish indicative (n=12 each) |
| Dev baseline | hit@3 81/93 (0.79–0.93), MRR 0.82 | `baseline-v2-dev-gemma4-e2b-20261018-1950.json` | valid (dev) |
| Manglish rewrite before/after (13 Oct, 20 draft items) | EN book recall@3 4/8 → 7/8; ML book 5/8 → 5/8 | `manglish-*.json`, `v2tutor-manglish-*.json` | indicative; timings invalid (notes generating) |

### A3. Answering and citations

| What | Result | File | Validity |
|---|---|---|---|
| Test baseline: answered when the book has it | 197/210 (0.90–0.96) | test baseline | valid |
| Test baseline: citation points at the gold page | 164/210 (0.72–0.83); SS ML 27/38 is the weakest | test baseline | valid |
| Tutor prompt v2 (14 Oct, 10 items, idle model) | 8/8 answered with a supported citation; first word p50 5.6 s EN / 13.8 s ML | `tutor-final-gemma-quiet-*.json` | indicative |
| "First sentence must be cited" rule, replayed on saved answers | would have refused 4 good answers → dropped | DECISIONS 13 Oct | valid (replay) |
| **Human grading, 60 dev answers** (one grader) | correct 0.90 (0.84–0.95), faithful 0.91 (0.85–0.96), relevant/guidance/clarity/tone 0.78–0.81; 17/60 flagged | `data/eval-private/grade_human_dev.csv` (private) | valid (dev, one grader) |
| Grader's findings by stage (19 Oct) | retrieval missed the page: 4; retrieval right but answer wrong (missing name, inverted fact, stray script): 3; style (EXAMPLE box, answer not first, "what" instead of "why"): ~7 | DECISIONS 19 Oct, chat review | qualitative |

### A4. Refusal

| What | Result | File | Validity |
|---|---|---|---|
| Test baseline refusal recall / false refusals | 32/37 (0.72–0.94) / 13/210 (0.04–0.10) | test baseline | valid |
| Dev: who refuses | all 11 correct dev refusals were the model's NOT_IN_TEXTBOOK; the keyword gate refused 0/14 and caused 2 false refusals | `baseline-v2-dev-rerun-*-2029.json` | valid (dev) |
| Gate rules calibrated offline (104 dev items) | stricter "≥2 matched words" → 7/14 extra refusals the model already makes, 4/90 false refusals → rejected; skip gate for rewritten questions → 0/90 false refusals | DECISIONS 19 Oct (M6) | valid (dev) |
| M6 end-to-end (30 dev refusal/Manglish items) | must-refuse 11/14 → 13/14; false refusals 3/16 → 2/16 | `m6-dev-refusal-manglish-20261019-2313.json` | indicative (n=30, battery) |
| Time-sensitive rule on all 109 dev items | fires on exactly 1 (the intended "CM now") | DECISIONS 19 Oct | valid (dev) |

### A5. Languages

| What | Result | File | Validity |
|---|---|---|---|
| Malayalam vs English first word (test) | SS ML p50 10.6 s vs SS EN 8.0 s | test baseline | valid |
| Manglish first word (test) | p50 12.9–14.5 s, p95 ~17.5 s | test baseline | valid |
| Third-script letters in answers (dev, offline recount) | 2/93 (Korean word, Telugu word); Hindi not reproduced | DECISIONS 19 Oct | valid (dev); now an eval column `third_script` |

### A6. Topic-less requests (intents)

| What | Result | File | Validity |
|---|---|---|---|
| Intent routing (test) | 5/26 routed to the expected mode | test baseline | valid, but measures a label |
| "Important points of chapter N" | right chapter 1/6 | test baseline | indicative |
| Check-my-understanding (dev) | planted mistakes corrected 5/5 even without a "check" mode | dev baseline | indicative |

### A7. Judges for answer quality (all failed the pre-registered rule)

| Judge | Agreement with the human grader | Result |
|---|---|---|
| Qwen3-4B local | kappa correct −0.08, faithful 0.53, flawed 0.23 (first 20 rows) | too lenient — not used |
| gpt-oss:120b (Ollama cloud, eval-only exception) | confirm half: 0.36 / 0.35 / 0.13 | stricter than the grader; caught real errors she passed — second reader only |
| gemma4:31b (Ollama cloud) | select half: 0.41 / 0.35 / 0.31 | not chosen |

### A8. Serving, load and power

| What | Result | File | Validity |
|---|---|---|---|
| **Bench on battery, clean machine** (19 Oct 22:50) | 1/2/4/8 phones: 2.3/3.0/3.1/2.6 answers/min; within 15 s 2/2, 4/4, 2/8, 0/16; random arrivals 2/min → 5/5, 4/min → 7/24 | `bench-gemma4-e2b-np2-battery-20261019-2250.json` | **valid baseline**; 2/min row thin (5 arrivals) |
| Power on battery under load | 11–13 W, ~0.07–0.08 Wh per answer | same + `logs/resources-battery-20261019.csv` | indicative (Windows' smoothed discharge rate) |
| Memory pressure check | 0.7 GB free RAM halved generation (7.5 vs 13.7 tok/s) | DECISIONS 19 Oct | valid finding |
| Benches at 19:36 and 20:37 | — | `bench-…-1936.json`, `bench-…-2037.json` | **invalid** (prompt-cache reuse; memory pressure) — do not quote |
| Load-control smoke (W5 part 1, 4 phones) | 4/4 answered through the new queue | scratchpad only | functional check, not a measurement |

### A9. Robustness and safety

| What | Result | Source | Validity |
|---|---|---|---|
| Power cut during book upload | resumed where it stopped (98 → 51 → 35 OCR pages left across two kills) | DECISIONS 13 Oct | valid |
| Concurrent logins / requests (bench) | found D6: shared SQLite connection used from threads → HTTP 500; fixed and guarded by a test | DECISIONS 19 Oct | valid |
| Privacy: no table links questions to accounts | unit test `test_no_table_links_questions_to_accounts` | tests | valid |
| Schema v3 → v4 upgrade keeps data | unit test + real eval database copy | DECISIONS 20 Oct | valid |

### A10. Measured in the research notes (not reproducible from `eval/` yet)

Footer page-number vote found the correct page offset on all 13 SCERT PDFs with a text layer; contents-page parsing matched known chapter starts; converting legacy-font Malayalam pages kept more key-fact terms than OCR (0.85 vs 0.56, n = 14, crude). Source: `reports/RuralMinds feature research 27 Oct.md`. Re-measure in `eval/` before quoting.

### A11. Numerical problems — "Solve step by step" chip (21 Oct)

Item set `eval/datasets/num/numerical.jsonl`: 38 items, **gold answers solved by hand and not yet checked by a reviewer (`verified: false` on all): every number here is draft-gold and indicative**. Split frozen by `python -m eval.numerical freeze` (21 dev / 17 test); everything tuned on during 20 Oct (book numericals, the user's three problems, Maths p 41 trial items) is forced to dev. Arms on the same items: the full app path with the chip (`solve`), the same model solving alone with a FINAL line (`alone`, eval prompt `numerical_alone_v1`), and setup + SymPy only for Maths (no Maths book indexed). Files: `num-gemma4-e2b-dev-20261021-1140-rescored.json`, `num-gemma4-e2b-baseline-test-20261021-1200-rescored.json` (the `-rescored` files apply two bench-scoring fixes found in an audit of the runs: whole numbers must match exactly — "3999 m" had passed for 4000 — and a comparison is right when the right choice is named; the original files are kept).

| What | Dev | Test (baseline, read once) | Validity |
|---|---|---|---|
| Science, full app path: ✓ shown and right | 11/14 (0.52–0.92) | 10/13 (0.50–0.92) | indicative, draft gold |
| Science: **✓ shown on a wrong answer** | 0/11 | **1/11** (90 km/h → 6.94 m/s: the setup converted units by hand *and* gave km/h, so it was converted twice) | indicative |
| Science: unsolved (safe message) | 3/14 | 2/13 (one was a mathcheck bug, below) | indicative |
| Science: same model alone, right | 12/14 (0.60–0.96) | 13/13 (0.77–1.0) | indicative; the alone answer is never checked |
| Maths setup only: ✓ right / ✓ wrong | 4/5 / 0 | 2/3 / 1 (both angles shown, not the asked smaller one) | indicative, n tiny |
| Not-numerical questions answered normally | 2/2 | 1/1 | indicative |
| First text shown after tapping Solve | p50 23.6 s, p95 42.8 s (dev + test, n = 30) | | **invalid as a benchmark**: ~1 GB RAM free, other apps open; direction only |

Bug found by the run and fixed after it (21 Oct): an unknown named `s` could not be solved next to SymPy's unit second (also `s`), so a correct setup ("s = v * t") came back "no solution"; unknowns are now real-valued symbols (`mathcheck.symbol`, regression test). Offline simulation on the saved runs, not a run: showing the ✓ only when the calculator's answer agrees with the model's own answer would have removed both wrong ✓ in test and kept every right one; on dev it would have removed one right ✓ (60 650 m, model alone said 60 400). Designed after reading the test split, so it must be confirmed on fresh items.

**After the agreement guard + setup v3 (21 Oct, dev only; `num-guard-setup3-dev-20261021-1247.json`; solve and setup arms):** Science ✓ shown and right 10/14 (was 11/14), ✓ on a wrong answer 0/10 (was 0/11), held back 4/14 (was 3/14). The guard held back two answers: the 60 650 m journey (calculator right, model alone said 60 400: the expected cost) and "2500 g in kg", where setup v3 still divided by 1000 itself and the calculator would have shown 0.0025 kg with a ✓ (the model alone said 2.5 kg). Maths setup only: 3/5 (was 4/5): the book/pen/pencil setup regressed to wrong relations under prompt v3 and failed safely (parse error). Draft gold, dev was tuned on: indicative; the test split is not read again until the fresh test problems exist.

## B. To do

Priority: **P1** needed for the submission, **P2** if time allows, **P3** after the hackathon.

| # | Evaluation | Why | Needs | Priority |
|---|---|---|---|---|
| T1 | **Final frozen test run** (once) | the "after" for every claim | all fixes in; server restarted; `split verify` | P1 |
| T2 | **Human-grade ~40 seeded test answers** | answer-quality numbers (judges failed) | ~2–3 h of the grader; `eval/grade.py export --sample 40` | P1 |
| T3 | **Bench on AC, clean machine** | the headline load number | plugged in, nothing else open; same command as the battery run | P1 |
| T4 | **1 vs 2 model slots** (`-np 1` vs `-np 2`) | 2 slots share one GPU: 1 slot may give the same answers/min with less RAM and faster single answers | two bench runs, same conditions | P1 |
| T5 | **Sustained run 20–30 min on battery** | battery life at classroom load; heat-soak slowdown | sampler on; laptop charged | P1 |
| T6 | **Hotspot device count** | "phones served" = min(bench, hotspot limit); Windows' cap is reported as 8 but unverified | count phones that can join | P1 |
| T7 | Power-pull recovery of the whole stack | GOAL success criterion; only ingest resume was tested | pull power mid-answer; check index and an answer are unchanged | P2 |
| T8 | **Malayalam pass criterion** | CLAUDE.md §8: claim Malayalam support only after its slice passes — no threshold was ever set | team decides thresholds (e.g. hit@3, citation, human-correct) before T1 | P1 |
| T9 | Manglish (W4): transliteration CER/WER on IndoNLP valid-2; Manglish arm before/after lexicon | weakest arm on test (hit@3 16/24) | lexicon work; dataset licence check | P2 |
| T10 | Third-script / Hindi rate after a generation grammar | 2/93 dev answers had a stray script | GBNF grammar change | P2 |
| T11 | Topic-less requests (W3): chapter routing to notes, check mode (mistake found / wrong correction), quiz marking | concepts right chapter 1/6; quiz marking does not work (D1) | W3 build; behaviour metrics, not mode labels | P2 |
| T12 | Wellbeing reply | decided 19 Oct; frozen test labels say "refuse", so report the difference | build + ANSWER_POLICY update | P2 |
| T13 | Creativity limits: temperature sweep per mode; EXAMPLE box off by default | grader found the EXAMPLE box lowered several answers | dev sweep; unsupported-claim rate target ≤ 5% (indicative at n ≈ 15) | P2 |
| T14 | Citation support check (D17) / reranker spike (A1) | fake citations (exam-stress advice cited to map pages); does not catch inverted facts | time-boxed; drop if first word p50 > 15 s or RAM swaps | P2 |
| T15 | Science tables and OCR fixes: cell F1 on ~10 tables; junk text pages (D12); split subscripts/tables (D14); dropped boxed text in ML OCR (D15) | Science citations and ML coverage | W6 / subject RAG | P3 → see [subject-rag.md](subject-rag.md) |
| T16 | Storage projection (MB per book → whole syllabus) | premise check for "SQLite is enough" | count after each ingest | P2 |
| T17 | Judge v3 with an explicit rubric, confirmed on the fresh T2 grades | would save grading time later | T2 first | P3 |
| T18 | Teacher usability, 1–3 real teachers | only impact evidence obtainable in time; label "teacher feedback (n = …)", never "pilot" | a session with teachers | P2 |
| T19 | New subjects: Maths, English, Malayalam (and Science done properly) | no eval items exist for them | see [subject-rag.md](subject-rag.md) | next phase |

## C. Gaps in the record to fix

- ~~Bake-off winner missing from DECISIONS~~ — recorded 20 Oct (Gemma 4 E2B, won on Malayalam).
- The test baseline was run before M6 and W5; the final run (T1) will include them — say so when comparing.
