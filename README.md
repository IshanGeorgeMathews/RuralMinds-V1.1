# RuralMinds

**DIKSHA gave rural students the textbook offline. RuralMinds gives them the explanation offline.**

RuralMinds is a learning server for rural schools that runs with **no internet at all**.

- A laptop in the school runs a small AI model and hosts the school's own Wi-Fi.
- Students open a web page on their phones and ask doubts from their textbook. English is the main language; Malayalam and Manglish questions work too and are still being evaluated (see *Known limits*).
- The tutor explains in simple words and adds an everyday example, clearly marked as not from the book.
- **Every answer shows the textbook page it came from**, and tapping the citation opens an image of that page.
- When the book does not cover a question, RuralMinds says so instead of inventing an answer, and passes the question to the teacher.

Built for Kerala SCERT Class 8 (Social Science Part 1 in English and Malayalam medium, Basic Science Part 1 in English) as an entry to MY Bharat Hack for Social Cause 2027, Kerala round.

## What works today

**Students** (phone browser, no app install)
- Explanations, simpler re-explanations, real-life examples, stories and quizzes, each with page citations.
- Chapter study notes for a quick read of a whole chapter.
- **Exam revision chips:** questions the teacher has checked for the coming exam, answered instantly with no model call. Students try first, then open the answer.
- **"Solve step by step"** for Science numericals (English only): the model writes the equations, the SymPy calculator solves them, and a second, independent solution must agree before the "✓ Checked by the calculator" badge is shown. When the two disagree, no answer is shown.
- When many phones ask at once, each phone sees its place in line and a wait estimate. One question is in flight per phone at a time.
- Each answer is labelled *AI explanation*, *Teacher-approved* or *Teacher's answer*.

**Teachers**
- Upload a textbook PDF. It is checked while it uploads and is safe if the power goes in the middle.
- Try the AI on a book before publishing it to students.
- Approve good answers, which are then served instantly.
- Set exam portions (book, chapters, classes, dates). The laptop drafts revision questions in its idle time; the teacher approves, edits or rejects each one beside the cited page.
- Inbox of questions the book could not answer, with repeats counted.
- Class-level activity.

**Admin** (on the school computer only)
- Accounts are created by the admin; there is no self sign-up.
- Pause answering, limit answer languages or classes, and see usage and speed statistics.

**Privacy**
- Accounts hold only a username and class: no names, phone numbers, Aadhaar or other IDs.
- No question is ever linked to an account (enforced by a unit test).
- Nothing leaves the school computer.

## Measured results

All numbers below were measured on one laptop: Ryzen 7 7730U, 14 GB RAM, the model running on the integrated GPU (Vulkan). The model is Gemma 4 E2B (Q4_K_M) on llama.cpp `llama-server`; search uses bge-m3. Every row names its result file in [`eval/results/`](eval/results/), and the full register, with whether each run is valid, is in [`docs/workstreams/evaluation-register.md`](docs/workstreams/evaluation-register.md). Brackets are Wilson 95% confidence intervals.

**Answer quality: frozen test split, read once on 19 Oct** (`baseline-v2-test-gemma4-e2b-20261019-1709.json`). Eval v2 has 354 verified items, split 107 dev / 247 test and frozen by a sha256 manifest. Tuning uses dev only. This is the *before* run: the refusal-gate change, load control, exam revision and the solve chip came after it, and the final test run has not been done yet.

| What | Result |
|---|---|
| Right textbook page in the top 3 search results | 185/210 (0.83–0.92), MRR 0.80 |
| … Social Science EN / Science EN / Social Science ML / Manglish | 66/71 · 46/50 · 35/38 · 16/24 |
| Answered when the book has the answer | 197/210 (0.90–0.96) |
| Citation points at the right page | 164/210 (0.72–0.83); Malayalam is the weakest at 27/38 |
| Off-syllabus questions refused | 32/37 (0.72–0.94) |
| Answerable questions wrongly refused | 13/210 (0.04–0.10) |
| Time to first word, p50 / p95 / p99 | 8.2 s / 14.5 s / 17.7 s |
| Full answer time, p50 / p95 | 29.1 s / 45.2 s |
| First word p50: Social Science EN / Social Science ML / Manglish | 8.0 s / 10.6 s / 12.9–14.5 s |

**Human grading of 60 dev answers** (one grader, 19 Oct): correct 0.90 (0.84–0.95), faithful to the book 0.91 (0.85–0.96). Three AI judges (Qwen3-4B, gpt-oss:120b, gemma4:31b) failed the agreement rule fixed in advance (kappa ≥ 0.6 against the human grades), so answer-quality numbers come from human grades only.

**Load and power (battery, clean machine, 19 Oct 22:50,** `bench-gemma4-e2b-np2-battery-20261019-2250.json`**):**

| Phones asking nonstop | 1 | 2 | 4 | 8 |
|---|---|---|---|---|
| Answers per minute | 2.3 | 3.0 | 3.1 | 2.6 |
| First word within 15 s | 2/2 | 4/4 | 2/8 | 0/16 |
| First word, median | 6.6 s | 9.7 s | 38 s | 138 s |

- The laptop produces about 3 answers per minute however many phones ask, so capacity, not speed, limits a classroom. That is why exam chips, approved answers and notes are served without a model call.
- Students arriving at random at 2 questions per minute were all served within 15 s (5 of 5, a thin sample); at 4 per minute, 7 of 24 were.
- Battery draw under load was 11–13 W, about 0.07–0.08 Wh per answer (Windows' smoothed discharge rate: indicative).
- The server needs the laptop to itself: with other apps filling the RAM, generation ran at half speed (7.5 vs 13.7 tokens/s).

**"Solve step by step" on Science numericals** (final test read, 21 Oct, `num-guard-setup3-final-test-20261021-1355-rescored.json`; answers checked by the team, small n, indicative):
- **No wrong ✓** in 26 Science problems: 0 of the 18 answers shown with a ✓ were wrong (0–0.18). Before the agreement guard, the baseline showed one wrong ✓.
- Shown with a ✓ and right: 8 of 13 fresh team-written problems (0.36–0.82) and 10 of 13 original test problems (0.50–0.92). The rest were held back with a safe message, never shown wrong.
- The cost of the guard is that some right answers are held back; multi-part questions are not set up yet.

**Other checks**
- Search time over the whole book vs one chapter: p50 177 vs 164 ms (`retrieval-timing-20261018-1953.json`).
- Power cut during a book upload: resumed where it stopped (98 → 51 → 35 OCR pages left across two kills; [`docs/DECISIONS.md`](docs/DECISIONS.md), 13 Oct).
- Model choice: Gemma 4 E2B beat Qwen3-4B-Instruct-2507 on Malayalam (8/8 vs 7/8 cited) and speed (Malayalam first word p50 9.0 s vs 65.9 s) on 20 dev items (`bakeoff-*-20261012-*.json`, indicative).

**Still to measure before claiming more:** the final frozen test run, human grading of test answers, a bench on mains power, 1 vs 2 model slots, a 20–30 min battery run, and how many phones the Windows hotspot accepts (to-do list T1–T6 in the register).

**Known limits**
- **Malayalam support is not claimed yet.** It works end to end, but no pass threshold has been agreed for its eval slice, and Malayalam citations are the weakest arm (27/38).
- Manglish is the weakest arm on test (right page in top 3: 16/24; 6/24 wrongly refused).
- With 4 or more phones asking nonstop, most students wait longer than 15 s for the first word.
- "Important points of chapter N" found the right chapter 1 of 6 times; quiz answers are not marked yet.
- Wellbeing questions ("I feel stressed about exams") can get advice with citations to unrelated pages; a citation-free reply is decided but not built.
- Step-by-step solving is English only, and Maths is not part of the evaluation yet (OCR silently changes Maths operators, e.g. ÷ read as +).
- The Malayalam screen text and the AI study notes still need a teacher's review.

## Documentation

- **Technical design with architecture diagrams:** [`docs/TECHNICAL_DESIGN.md`](docs/TECHNICAL_DESIGN.md)
- **Every measurement, its file and validity, and what is still to measure:** [`docs/workstreams/evaluation-register.md`](docs/workstreams/evaluation-register.md)
- **How answers must behave:** [`docs/ANSWER_POLICY.md`](docs/ANSWER_POLICY.md)
- **Decisions and the evidence behind them:** [`docs/DECISIONS.md`](docs/DECISIONS.md)
- **Status of each workstream:** [`docs/workstreams/`](docs/workstreams/)
- **Demo flow:** [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)
- **Eval data:** [`eval/datasets/v2/`](eval/datasets/v2/) (the frozen eval set), [`eval/datasets/num/`](eval/datasets/num/) (numericals) and [`eval/samples/`](eval/samples/) (the first draft sets). The v2 questions were drafted with an AI assistant and reviewed one by one by the team; the numerical gold answers were solved by hand.
- **Test cases:** [`apps/api/tests/`](apps/api/tests/), unit and API tests for search filters, refusal, citations, accounts, uploads, the queue, exam revision, the calculator and privacy.

## Setup

Needs Python 3.12 with [`uv`](https://docs.astral.sh/uv/), Node 22, llama.cpp `llama-server`, Tesseract with `eng` and `mal` language data, and the GGUF model files (not included). See [`docs/setup-prerequisites.md`](docs/setup-prerequisites.md).

```powershell
uv sync
npm --prefix frontend install
npm --prefix frontend run build
copy .env.example .env                       # then set the model paths (below)
./scripts/start_all.ps1                      # both model servers + the API on port 8000
uv run python -m ruralminds.ingest --book ss8-pt1-en   # books listed in apps/api/books.toml
uv run python -m ruralminds.notes --book ss8-pt1-en    # chapter study notes
uv run python -m ruralminds.admin init       # admin password + one-time recovery code
uv run python -m ruralminds.admin demo       # optional: demo classes, students, teacher
```

`books.toml` lists the two Social Science books. Other books (the Science book used in the eval) are added through the teacher's upload screen.

Phones on the laptop's Wi-Fi open `http://<laptop-ip>:8000`. Admin pages open only on the laptop itself (`http://localhost:8000/admin`).

## Environment variables

All settings are read from `.env` with the `RURALMINDS_` prefix. [`.env.example`](.env.example) lists the ones you usually change; every other setting and its default is in [`apps/api/src/ruralminds/config.py`](apps/api/src/ruralminds/config.py). The model-server variables are read by `scripts/start_all.ps1`.

| Variable | Example | Meaning |
|---|---|---|
| `RURALMINDS_CHAT_MODEL_PATH` | `models/gemma-4-e2b-Q4_K_M.gguf` | Chat model file |
| `RURALMINDS_CHAT_MODEL_LABEL` | `Gemma 4 E2B (Q4_K_M)` | Name shown on the admin screen |
| `RURALMINDS_EMBED_MODEL_PATH` | `models/bge-m3-Q8_0.gguf` | Embedding model file |
| `RURALMINDS_LLAMA_SERVER_PATH` | `llama-server` | llama.cpp server binary (a Vulkan build uses the GPU) |
| `RURALMINDS_EMBED_SERVER_PATH` | *(empty = same binary)* | Binary for the embedding server |
| `RURALMINDS_LLM_GPU_LAYERS` | `0` CPU · `99` GPU | Model layers on the GPU |
| `RURALMINDS_LLM_KV_TYPE`, `RURALMINDS_LLM_FLASH_ATTN` | `q8_0`, `auto` (CPU) · `f16`, `off` (Radeon iGPU) | KV cache and flash attention per backend |
| `RURALMINDS_LLM_PARALLEL` | `2` | Answers generated at the same time |
| `RURALMINDS_LLM_CTX`, `RURALMINDS_EMBED_CTX`, `RURALMINDS_THREADS` | `8192`, `4096`, `8` | Server sizing |
| `RURALMINDS_LLM_URL`, `RURALMINDS_EMBED_URL` | `http://127.0.0.1:8080`, `http://127.0.0.1:8081` | Local servers only, never internet hosts |
| `RURALMINDS_DB_PATH` | `data/ruralminds.db` | SQLite database |
| `RURALMINDS_API_HOST`, `RURALMINDS_API_PORT` | `0.0.0.0`, `8000` | Where phones connect |
| `RURALMINDS_ENV` | `development` | Environment name |
| `RURALMINDS_MAX_CONTEXT_TOKENS`, `RURALMINDS_FINAL_TOP_K` | `600`, `4` | How much book text the model reads |
| `RURALMINDS_MAX_TOKENS`, `RURALMINDS_TEMPERATURE` | `300`, `0.2` | Answer length cap and randomness |
| `RURALMINDS_HISTORY_TURNS` | `2` | Earlier turns of the chat the model sees |
| `RURALMINDS_REFUSAL_THRESHOLD` | `0.5` | Minimum match score when no keyword matches |
| `RURALMINDS_MAX_QUEUE`, `RURALMINDS_MAX_WAIT_S` | `30`, `180` | Turn new questions away ("busy") above this many waiting or this predicted wait in seconds |
| `RURALMINDS_REVISION_WORKER`, `RURALMINDS_REVISION_IDLE_S` | `true`, `45` | Draft exam questions only after this many seconds with no student question |
| `RURALMINDS_MATH_TIMEOUT_S` | `3.0` | Time limit for one calculator solve |
| `RURALMINDS_STUDENT_IDLE_MINUTES`, `RURALMINDS_TEACHER_IDLE_MINUTES` | `30`, `480` | Automatic sign-out (shared phones) |
| `RURALMINDS_LOGIN_MAX_FAILURES` | `5` | Wrong passwords before a wait |
| `RURALMINDS_MAX_UPLOAD_MB`, `RURALMINDS_MAX_PAGES` | `60`, `400` | Upload limits |
| `RURALMINDS_MIN_FREE_DISK_GB`, `RURALMINDS_MAX_INGEST_ATTEMPTS` | `2`, `3` | Disk safety margin, retries after a failure |

## Tests and evaluation

```powershell
uv run pytest                                  # unit + API tests
uv run ruff check apps                         # lint (also run by CI)
npm --prefix frontend run check                # frontend type check

# eval v2 (dev split for tuning; the test split is read only for the baseline and the final run)
uv run python -m eval.split verify             # the frozen split is unchanged
uv run python -m eval.run --testset eval/datasets/v2/ss_en.jsonl eval/datasets/v2/sci_en.jsonl eval/datasets/v2/ss_ml.jsonl eval/datasets/v2/manglish.jsonl eval/datasets/v2/refusal.jsonl eval/datasets/v2/intents.jsonl --split dev --label my-run
uv run python -m eval.bench --levels 1 2 4 8 --label my-bench   # load bench
uv run python -m eval.numerical run --split dev --label my-run  # Solve step by step
```

`eval.split verify` also reads 18 refusal items taken from IndicQuest, which stay in `data/eval-private/` until their licence is confirmed, so it needs that file. Measured runs restart the chat server first (its prompt cache otherwise speeds up repeats) and run with nothing else open on the laptop.

## Licence

Apache-2.0 ([`LICENSE`](LICENSE)). Textbook PDFs, model weights and the database are never committed. SCERT textbooks are © Department of Education, Government of Kerala; permission for redistribution is pending. Third-party licences are in [`docs/licenses/`](docs/licenses/).
