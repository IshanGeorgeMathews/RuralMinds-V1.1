# Maths and numerical problems (Maths, Physics, Chemistry)

**State on 20 Oct 2026:** option A chosen (DECISIONS 2026-10-20); answer card = §3.5. Built: `mathcheck.py` (§6 step 2: safe parser, solve, units, worked steps, unit labels; 35 unit tests) and the two prompts `maths_setup_v1` / `system_v3_numerical_en` (tried on 10 items, §6a), and the solve path (§6 step 3): `numerical.py` + mode `solve` in `answer.py`, chip-only, with a method-only fallback and `math_status` in every solve answer; 10 tests. Live check on a database copy: 3 Science numericals solved with the right pages cited, 1 non-numerical question routed to the tutor answer; first word 15–40 s on a busy laptop (not a measurement; the setup call comes before the first word, so step 4 shows a progress step). Next: step 4 (chip + answer card). Measured today: how well our current ingestion reads the Maths book (§1). Everything else here is a proposal. Numbers from papers are marked *external* and are never RuralMinds results (rule 6).

## 0. Scope conflict — decide first

DECISIONS 2026-10-17 says **"Maths stays out"**, and [subject-rag.md](subject-rag.md) recommends Maths after the submission. Seven days remain and P1 evaluations are still open (T1 final test run, T2 human grading, T3 AC bench, T4–T6, T8 Malayalam criterion — [evaluation-register.md](evaluation-register.md)).

| Option | What happens by 27 Oct | Risk |
|---|---|---|
| **A (recommended)** | This design + **one opt-in slice**: a "Solve step by step" chip on **Science Pt1 EN numericals** (Measurements, Motion, Force — already indexed, clean text layer, no OCR needed) using solve-then-explain with SymPy (§3). Steps 2–4 of §6: about **2–2.5 days**. The OCR spike and all of Maths come after the submission. | **Not small.** It competes with T1, T2 (2–3 h grading), T3–T6 for the same 7 days. The book has only ~6–7 real numerical problems (§1), so most `px_num` items must be team-written variants. Two model calls per answer push first word up and capacity down (§3.2). The chip is opt-in, so the frozen-test path is untouched. |
| B | Reopen the decision and build Maths Pt1 EN for the demo | Needs OCR of 80 pages, a new eval set with hand-solved answers, new prompts and UI. Likely pushes T1–T6 out. |
| C | Design only; build everything after 27 Oct | No demo of calculations. |

Whatever is built **must not change the Social Science / Science answer path before T1**, or the final frozen-test run no longer measures the tuned pipeline. The maths path is chosen by an explicit chip or by the book's subject, never by a new automatic classifier on existing books before T1.

## 1. What we measured today (20 Oct)

The `needs_ocr` count is a full-book count; the Tesseract rows are **qualitative (n = 3 pages: 21, 41, 61)**. Reproduce the count with `needs_ocr(page_text, medium, 0.6)` from `ruralminds.pages` over every page of each PDF (pypdfium2 `get_text_range()`).

Book: `maths_pt1.pdf` (Class 8 Maths Part 1, English, 96 pages; sits in the `malayalam_medium` folder). The Malayalam edition is `maths_mal_pt1.pdf`.

| Check | Result |
|---|---|
| Does our ingest notice the junk text layer? | **Yes.** `needs_ocr` sends 80/96 English pages to OCR; the 16 kept (pp 1–6, 47–59, 67, the Polygons chapter) have a real text layer. All 96 Malayalam pages go to OCR (legacy font). |
| Tesseract on word problems (p 41, Equations) | Words and numbers read well ("perimeter … 80 metres … one metre more than twice the breadth"). |
| Tesseract on operators | **Silently wrong.** Book: `x = (100 − 70) ÷ 10 = 30 ÷ 10 = 3`. OCR: `x = (100 — 70) + 10=30+ 10=3`. |
| Tesseract on symbols / superscripts | `△AMP` → `AAMP`; on the image-only chapter opener (p 61) `(x+a)(x+b) = x²+(a+b)x+ab` → `Geb) = x*+(ath)x +ab`. |
| Geometry pages (p 21) | Figures come out as stray letters and angles ("£\ 50° %"). The text of the questions survives. |
| Science Pt1 EN numericals (indexed chunks, ch 8–10) | A regex for "number + unit … ?" found 10 candidates, of which ~6–7 are real problems (5 in Motion, e.g. "acceleration of a car which started from rest and acquired 40 m/s in 8 s"). Thin. |
| Science Pt1 EN (already indexed) | Chemistry equations are flattened: "Mg + O2 MgO NaOH + H2 SO4" (arrow lost, subscripts split — known defect D14); units lose superscripts ("20 m2"). |

**Why this matters more than anything else in this document:** SymPy can only check the arithmetic of the problem it is given. If OCR turned `÷` into `+`, SymPy will happily "verify" a wrong answer. So reading the problem correctly is its own stage, with its own number (§5).

## 2. Problem types — what can be verified

Every Maths/Physics/Chemistry item gets a `kind` tag. Only the first three can be machine-checked; the rest are explained and cited, never "verified". Reported numbers are always per kind.

| kind | Example (Class 8) | Machine check |
|---|---|---|
| `numeric` | area of a 5 m × 4 m room; speed = distance / time | SymPy evaluates; units with `sympy.physics.units` |
| `algebraic` | "sum of three consecutive odd numbers is 33" → solve | SymPy solves the equations and substitutes back |
| `chem_balance` | balance Mg + O₂ → MgO | SymPy matrix null space gives the coefficients (only after D14 is fixed) |
| `geometry_figure` | congruent triangles, constructions (p 21) | none — concept explanation + link to the page image |
| `proof_reasoning` | "Can the sum of three consecutive odd numbers be 36? Why?" | final claim only, if it reduces to an equation; the reason is human-graded |
| `concept` | "what is an identity?" | none — normal tutor answer |

## 3. Design

### 3.1 Ingestion (problem-aware)
- **Reading:** Tesseract stays the default. The spike (§6 step 1) compares it with one vision OCR model on 8–10 problem-heavy pages. Whatever reads numbers and operators better wins, by measurement.
- **Problems are units.** Chunking never splits a worked example or an exercise (CLAUDE.md §8). Exercise starts are detected by numbering patterns (`(1)`, `i)`, `ii)`), section markers ("Let us assess", "Additional problems", the textbook's icon labels) and kept with their sub-parts.
- **A problem table** (new, small): one row per detected exercise or worked example: book, chapter, page, number, text, `kind`, `is_worked_example`. This is what the solution bank and "similar problem" generation use. It works for any teacher upload because detection is by pattern, not by hand.
- **Ingest report:** problems found per chapter shown on the teacher's Books screen, so a teacher sees when detection failed on their book (research report item A2).

### 3.2 Answering: "solve first, explain second"
A 2B model is weak at arithmetic, so it never computes the answer. The flow:

1. **Retrieve** as today (the problem's own page, or the concept's worked example).
2. **Setup call** (short, constrained JSON through llama-server's `json_schema` — no new library): `{"kind", "unknowns": ["x"], "equations": ["x + (x+2) + (x+4) = 33"], "asked": "x, x+2, x+4", "units": {...}}`.
3. **SymPy solves** the equations and substitutes the result back. Parse failure, no solution or several solutions → fall back to a concept explanation with the cited worked example, no final number (ANSWER_POLICY §5).
4. **Explain call** (streamed): the model receives the *already-solved* steps and explains them in simple words, citing the method page. It explains a known-correct solution instead of inventing one (the Harvard tutor RCT fed pre-written solutions — *external*, Kestin et al., cited in the research report).
5. **Check:** every number in the explanation that claims to be a result must match SymPy's; otherwise the final number is replaced and flagged `math_corrected` (ANSWER_POLICY §5).

**Safety:** model output is never passed to `sympify`/`parse_expr` raw (they use `eval`). A whitelist tokenizer (digits, `+ - * / ^ ( ) =`, declared single-letter symbols, known unit names) runs first; anything else is a parse failure. The whitelist stops code injection but not runaway work (`2^(10^10)`, a degree-50 polynomial), so the parser also caps exponents, number length and polynomial degree, and SymPy runs in a worker process with a hard timeout (never on the event loop); a timeout takes the step-3 fallback.

**Latency:** the setup call is not streamed, so first word = the whole setup call + the explain call's first word (today's first word is p50 8.2 s against a 15 s target), and two calls per answer lower the ~3 answers/min capacity. Mitigation: the setup call gets only the problem text (not the 600-token retrieved context) and a small max-tokens cap; the phone shows a "setting up the problem…" step meanwhile. Measured in §5 stage 10 before any claim.

**Physics:** quantities carry units through `sympy.physics.units` (part of SymPy; no Pint needed). A wrong or missing unit in the final answer is an error.

### 3.3 Three tiers of problems
| Tier | Source | How it is answered | Label |
|---|---|---|---|
| **A. Textbook exercise** | the problem table | Pre-solved in idle time (same idle loop as `revision_worker.py`), SymPy-checked, then teacher-approved. Served with **zero model time** — this also helps the ~3 answers/min capacity limit. | `Teacher-approved` once approved, else `AI explanation` |
| **B. Student's own problem on a book concept** | typed by the student | §3.2 live. Citation points at the **method page** (worked example), not at the problem. | `AI explanation` (+ "answer checked by calculator" badge when SymPy agreed) |
| **C. "Give me a similar problem"** | generated from a textbook exercise | The model proposes new numbers; SymPy solves; **accept only if** the answer is clean (e.g. a positive integer where the original was) and the equation *skeleton* matches the source (numbers replaced by symbols, compared with `srepr`) — a deterministic "same concept" check. The answer always comes from SymPy. | new label `Practice problem — made from Ch n, p p` |

### 3.4 Hint-first (ANSWER_POLICY §3)
Turn 1: concept + first step only; the final number is withheld (checkable: turn 1 must not contain it). Turn 2: next step, or check the student's attempt by substituting their answer into the equations with SymPy (cheap and exact). Turn 3: the full solution. Never refuse to show the solution.

### 3.5 Answer card (the "box") — draft, to confirm
```
┌─────────────────────────────────────────┐
│ Idea  Consecutive odd numbers differ by 2│
│                                          │
│ Steps                                    │
│ 1. Let the smallest be x.                │
│ 2. The numbers are x, x + 2, x + 4.      │
│ 3. x + (x + 2) + (x + 4) = 33            │
│ 4. 3x + 6 = 33  →  3x = 27  →  x = 9     │
│ ┌──────────────────────────────────────┐ │
│ │ Answer: 9, 11, 13   ✓ checked        │ │
│ └──────────────────────────────────────┘ │
│ Method from: Ch 2 Equations, p 41  [page]│
│ Try this: … (answer hidden until tapped) │
│ AI explanation — may contain mistakes    │
└──────────────────────────────────────────┘
```
- The EXAMPLE box is **off** for maths (the grader found it lowered answers, T13).
- Maths is shown as plain text with Unicode (x², ÷, √, ½) first: cheapest, no new library, and a 2B model writing LaTeX costs tokens and errors. If fractions or powers look bad on the cheap phone, see the rendering options in §4.
- Figures are never drawn by the model; geometry answers link to the textbook page image (`pagepng.py` already does this).

### 3.6 Refusal changes (needs an ANSWER_POLICY update)
Today a student's own problem would likely be refused (NOT_IN_TEXTBOOK or no valid `[Sn]`), because the book does not contain *that* problem. New rule for maths/numericals: **answer when the concept and method are in the book** (cite the method page); **refuse when the concept is not** (e.g. calculus in Class 8, or a topic from another book).

### 3.7 Malayalam (later)
SymPy is independent of language; only the explain prompt changes (`system_v3_maths_ml.md`). The risk is reading: all 96 Malayalam Maths pages need OCR, so the reading-fidelity check (§5, stage 1) is repeated on the Malayalam book before any claim. Manglish number words ("randu", "moonu") come later with W4.

## 4. Libraries and models researched

None of these is approved yet except SymPy (approved 17 Oct, parked). Each "ask" needs a yes from the team before it is installed (CLAUDE.md §3).

| Candidate | What it gives | Licence / footprint | Verdict |
|---|---|---|---|
| **SymPy** | solve, simplify, check equality, units (`sympy.physics.units`), chemical balancing (matrix null space), checking a student's attempt | BSD-3, pure Python, no torch | **Use — core.** Already approved. |
| llama-server `json_schema` / GBNF | forces the setup call to return valid JSON | already in our llama.cpp build | **Use.** No new dependency. |
| **PaddleOCR-VL 1.5** (0.9B) | page OCR with a `Formula Recognition:` prompt; GGUF + mmproj run in `llama-server` | Apache-2.0; a second model file, used at ingest only | **Spike candidate #1.** Malayalam support not listed — unknown. New component → ask. |
| Granite-Docling 258M | document conversion incl. formulas; GGUF + mmproj (community conversions) | Apache-2.0 (base model) | Spike candidate #2 (smaller). Formula output format to check on the official card. |
| Gemma 4 E2B vision (mmproj) | the same model family reads page images | ggml-org publishes mmproj Q8_0 557 MB / BF16 987 MB, but **weights only as Q4_0 / Q8_0 / BF16 — no Q4_K_M** | Not "free": our pinned weights are the Ollama Q4_K_M blob. Either an mmproj works with that blob (unverified), or we change the pinned weights (rule 3 → re-run the eval). Ingest-time only. |
| RapidLaTeXOCR | formula image → LaTeX (ONNX) | MIT (stated second-hand); needs onnxruntime + a formula detector | Not now: crops only, not whole pages; adds a runtime. |
| pix2tex, Nougat, Marker/Surya | formula / page OCR | torch, non-commercial weights, or GPL | **No** (torch-free stack, Apache repo). |
| Pint | units | BSD | **No** — SymPy units cover Class 8–10. |
| latex2mathml | LaTeX → MathML on the server; desktop Chrome shows MathML natively from 109 (Android support listed for current versions — test on the cheap phone) | MIT, pure Python | Only if plain-text maths is not readable on the phone. Ask first. |
| Temml / KaTeX | LaTeX rendering in the browser | MIT; Temml ~150–175 KB JS+CSS, KaTeX ~280 KB | Temml only if needed; KaTeX would use most of the 300 KB budget. |

External results that support the design (not ours, not to be quoted as RuralMinds numbers): program-based verification raised Gemma-2-2b-it on GSM8K from 73.4% to 79.6% (PROVE, arXiv 2410.12608); SymPy code generation with self-correction helped larger models on harder sets (SymCode, arXiv 2510.25975).

## 5. Bench plan

Same rules as everything else: dev for tuning, frozen test read twice (baseline + final), Wilson 95% intervals, small samples called indicative, clean machine, server restarted.

### 5.1 Item sets (all with hand-solved gold answers — the textbook most likely has no answer key, so budget team time)
| Set | What | Target n | Expected |
|---|---|---|---|
| `mx_book` | textbook exercises (numeric/algebraic) | 40 | answer |
| `mx_variant` | same exercises with new numbers (unseen) | 40 | answer |
| `mx_novel` | team-written problems on book concepts, different wording | 20 | answer (cite method page) |
| `mx_figure` | geometry / figure items | 10 | concept + page link (human-graded) |
| `mx_offsyllabus` | beyond Class 8 or not in this book | 10 | refuse |
| `px_num` | physics numericals (Measurements, Motion, Force): the ~6–7 in the book + team-written variants | 20 | answer with correct unit |
| `cx_balance` | chemical equations | 10 | after D14 only |
| **held-out** | whole chapters reserved for test, plus **Science Pt2 EN as an unseen book** | — | measures "works on a teacher's new upload", which held-out items cannot |

Malayalam versions of `mx_book`/`mx_variant` come after the English slice passes.

### 5.2 Metrics, by stage (so a failure can be located)
| Stage | Metric | How |
|---|---|---|
| 1. Reading | number/operator error rate vs a hand transcription of ~30 problems; Tesseract vs the spike model | script, exact token compare |
| 2. Problem detection | exercises found / exercises in the chapter; worked examples never split | count on 2 chapters + unit test |
| 3. Retrieval | hit@3 on the problem page (`mx_book`) and the method page (`mx_novel`) | existing `eval/metrics.py` |
| 4. Setup | JSON parse rate; equations solvable; SymPy agree / corrected / parse-fail rates | logged per item |
| 5. Final answer | **final-answer accuracy vs gold**, two arms on the same items: **model alone** (today's tutor prompt) vs **solve-then-explain** — the difference is the value of SymPy | SymPy equality with gold; units checked |
| 6. Hint-first | turn-1 leak rate (final number appears in turn 1) | automatic |
| 7. Explanation | step errors, clarity — human-graded sample of 20 (judges failed, A7) | grade sheet |
| 8. Similar problems | solvable + clean rate; skeleton-match rate; same-concept by a human on 20 | automatic + human |
| 9. Refusal | must-refuse recall on `mx_offsyllabus`; false refusals on `mx_novel` | existing metrics |
| 10. Time and load | first word and total p50/p95 (two model calls); SymPy time per answer; bench answers/min with a maths mix; share served with zero model time (tier A) | `eval/run.py`, `eval/bench.py` |

Note: `eval/run.py` is single-turn. Hint-first is checked with the turn-1 leak proxy plus the full-solution accuracy; a real multi-turn runner is P3.

### 5.3 Pass criteria — to fix before the first test read (like T8)
Proposed, for the team to change: solve-then-explain beats model-alone on `mx_variant` with non-overlapping intervals; turn-1 leak ≤ 1/20; no answer marked "✓ checked" that is wrong against gold (any such case is a stage-1 reading error and must be reported as such).

## 6. Build order (each step testable on its own)

| Step | What | Estimate | Fits before 27 Oct? |
|---|---|---|---|
| 1 | **OCR spike**: Tesseract vs one vision model on 8–10 problem pages; stage-1 metric; answering paused (0.7 GB free RAM halved generation, 19 Oct). Needed for Maths only, not for the Science slice. | 0.5 day | no (after 27 Oct) |
| 2 | `mathcheck.py`: whitelist parser, solve, substitute-back, units; unit tests | 0.5 day | yes |
| 3 | Setup JSON prompt + explain prompt (`system_v3_maths_en.md`), "Solve step by step" chip, answer card | 1 day | yes, Science numericals only |
| 4 | `px_num` dev/test items (20) + bench arms (model-alone vs solve-then-explain) | 0.5–1 day incl. hand-solving | yes, after T1 |
| 5 | Maths Pt1 EN ingest with problem table + ingest report | 1–2 days | no |
| 6 | Tier A idle pre-solving + teacher approval | 1 day | no |
| 7 | Tier C similar problems + skeleton check | 1 day | no |
| 8 | Full maths eval sets, held-out book run | 2+ days | no |
| 9 | Malayalam reading check, ML prompts, ML items | 2+ days | no |

## 6a. Prompt trial, 20 Oct (scratch script, not a measurement)

Ten book problems (6 Science Pt1 numericals, 4 Maths Pt1 p 41) and 1 non-numerical question, run through setup call → SymPy → explain call on the live model. Timings are **not reported**: the laptop was busy (generation ~8.5 tok/s against 13.7 tok/s clean) and the server was restarted mid-trial.

What the trial changed in the design:
- **Setup output is a line format** (`KIND / UNKNOWNS / KNOWN / EQUATION / ASKED / UNIT`) constrained by a GBNF grammar, not JSON: indented JSON was 176 tokens for one problem. `KNOWN` may only hold a number and a unit, so relations must be written as equations.
- **The model never writes maths.** Asked to "copy the working exactly", it dropped brackets (`a = v - u / t`) and added its own line. Now SymPy produces the worked lines (`worked_steps`), and the explain grammar writes each line into the reply as fixed text; the model writes only one sentence under each, so the sentence matches its line and the line cannot change. Sentences may not contain `$` or `\` (the model wrote LaTeX once).
- **Units on plain numbers come from the question** (`answer_unit_for`): the model filled "degree/none" on a sum of odd numbers.

What it showed (indicative, n = 10):
- Science numericals: 6/6 set up correctly and solved (incl. km/h → m/s); all formula substitution.
- Maths story problems: 2/4 solved correctly; 2 failed safely (no number shown). **But one of the safe failures had wrong equations** (`b = c + 4` for "4 rupees more than the pen"), and it failed only because of an unrelated parse error. A wrong setup that parses would be shown as "✓ checked" and be wrong. **This is the main risk of the design**: SymPy checks the arithmetic, not the reading of the story. Stage 4 of the bench (setup correct) must be reported on its own; a candidate guard is two setups that must agree before the badge is shown, decided by measurement.
- Two-equation problems have no worked lines yet, so their last sentence is vague ("substitute b … then find the breadth").

## 7. To decide (team)
1. Option A, B or C (§0).
2. What "draw the box" means: the answer card in §3.5, a boxed final answer, figures, or something else.
3. Which vision OCR model goes into the spike (PaddleOCR-VL vs Granite-Docling vs Gemma's own mmproj), as a new component.
4. Labels: `Practice problem — made from …` for tier C, and the "✓ checked" badge wording.
5. ANSWER_POLICY change: maths/numerical answers cite the method page; refuse only when the concept is not in the book.
6. Who hand-solves the gold answers, and the pass criteria in §5.3.

## Sources
- [ggml-org/gemma-4-E2B-it-GGUF files](https://huggingface.co/ggml-org/gemma-4-E2B-it-GGUF/tree/main)
- [PaddleOCR-VL 1.5 GGUF](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.5-GGUF/blob/main/README.md)
- [granite-docling-258M GGUF (community)](https://huggingface.co/infil00p/granite-docling-258M-GGUF)
- [RapidLaTeXOCR](https://github.com/RapidAI/RapidLaTeXOCR), [pix2text LaTeX OCR](https://pix2text.readthedocs.io/zh/latest/pix2text/latex_ocr/)
- [PROVE: programs as verifiers (arXiv 2410.12608)](https://arxiv.org/html/2410.12608v1), [SymCode (arXiv 2510.25975)](https://arxiv.org/html/2510.25975v2)
- [Temml](https://www.github.com/ronkok/Temml), [latex2mathml](https://pypi.org/project/latex2mathml/3.64.0/), [MathML browser support](https://caniuse.com/mathml)
