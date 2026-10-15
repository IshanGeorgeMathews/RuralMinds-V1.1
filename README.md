# RuralMinds

**DIKSHA gave rural students the textbook offline. RuralMinds gives them the explanation offline.**

RuralMinds is a learning server for rural schools that runs with **no internet at all**.

- A laptop in the school runs a small AI model and hosts the school's own Wi-Fi.
- Students open a web page on their phones and ask doubts from their textbook in English, Malayalam or Manglish.
- The tutor explains in simple words and adds an everyday example, clearly marked as not from the book.
- **Every answer shows the textbook page it came from**, and one tap opens the real page.
- When the book does not cover a question, RuralMinds says so instead of inventing an answer, and passes the question to the teacher.

Built for Kerala SCERT Class 8 Social Science (English and Malayalam medium) as an entry to MY Bharat Hack for Social Cause.

## What works today

**Students** (phone browser, no app install)
- Explanations, simpler re-explanations, real-life examples, stories and quizzes, each with page citations.
- Chapter study notes for a quick read of a whole chapter.
- Each answer is labelled *AI explanation* or *Teacher-approved*.

**Teachers**
- Upload a textbook PDF. It is checked while it uploads and is safe if the power goes in the middle.
- Try the AI on a book before publishing it to students.
- Approve good answers, which are then served instantly.
- Inbox of questions the book could not answer, with repeats counted.
- Class-level activity.

**Admin** (on the school computer only)
- Accounts are created by the admin; there is no self sign-up.
- Pause answering, limit answer languages or classes, and see usage and speed statistics.

**Privacy**
- Accounts hold only a username and class: no names, phone numbers, Aadhaar or other IDs.
- No question is ever linked to an account.
- Nothing leaves the school computer.

## Measured results

All numbers below were measured on one laptop: Ryzen 7 7730U, 14 GB RAM, model running on the integrated GPU. The model is Gemma 4 E2B (Q4_K_M) on llama.cpp; search uses bge-m3. The question sets are small drafts written by the team (see [`eval/samples/`](eval/samples/)), so treat them as early evidence, not a benchmark.

| What | Result | Source (`eval/results/`) |
|---|---|---|
| Right textbook page in top 3, dev set (EN / ML) | 8/8 · 8/8 | `v2tutor-dev-gemma-contended-*.json` |
| Answered with a supported page citation, tutor set | 8/8 | `tutor-final-gemma-quiet-*.json` |
| Off-syllabus questions politely refused | 10/12 | `final-check-gemma-contended-*.json` |
| Manglish questions, right page in top 3 (English book), before → after the language fix | 4/8 → 7/8 | `manglish-*.json`, `v2tutor-manglish-*.json` |
| Time to first word, English (median) | 5.6 s | `tutor-final-gemma-quiet-*.json` |
| Full answer time, English / Malayalam | 13–28 s / 30–40 s | `tutor-final-gemma-quiet-*.json` |
| Power cut during a book upload | resumed where it stopped (98 → 51 → 35 OCR pages left across two kills) | [`docs/DECISIONS.md`](docs/DECISIONS.md), 13 Oct |

**Not measured yet:** how many phones the laptop serves at once, and power draw in watts. We do not quote estimates for these.

**Known limits:**
- One kind of off-syllabus question can still slip through. "At what temperature does water boil?" finds the geography pages about the Earth's temperature and gets answered.
- Malayalam answers take longer than English ones, because Malayalam text needs more model tokens.
- The Malayalam screen text and the AI study notes still need a teacher's review.

## Documentation

- **Technical design with architecture diagrams:** [`docs/TECHNICAL_DESIGN.md`](docs/TECHNICAL_DESIGN.md)
- **How answers must behave:** [`docs/ANSWER_POLICY.md`](docs/ANSWER_POLICY.md)
- **Decisions and the evidence behind them:** [`docs/DECISIONS.md`](docs/DECISIONS.md)
- **Demo flow:** [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)
- **Sample data:** [`eval/samples/`](eval/samples/), our own question sets with expected pages and refusals.
- **Test cases:** [`apps/api/tests/`](apps/api/tests/), unit and API tests for search filters, refusal, citations, accounts, uploads and privacy.

## Setup

Needs Python 3.12 with [`uv`](https://docs.astral.sh/uv/), Node 22, llama.cpp `llama-server`, Tesseract with `eng` and `mal` language data, and the GGUF model files (not included). See [`docs/setup-prerequisites.md`](docs/setup-prerequisites.md).

```powershell
uv sync
npm --prefix frontend install
npm --prefix frontend run build
copy .env.example .env                       # then set the model paths (below)
./scripts/start_all.ps1                      # both model servers + the API on port 8000
uv run python -m ruralminds.ingest --book ss8-pt1-en   # books are listed in apps/api/books.toml
uv run python -m ruralminds.notes --book ss8-pt1-en    # chapter study notes
uv run python -m ruralminds.admin init       # admin password + one-time recovery code
uv run python -m ruralminds.admin demo       # optional: demo classes, students, teacher
```

Phones on the laptop's Wi-Fi open `http://<laptop-ip>:8000`. Admin pages open only on the laptop itself (`http://localhost:8000/admin`).

## Environment variables

All settings are read from `.env` with the `RURALMINDS_` prefix; [`.env.example`](.env.example) lists every one.

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
| `RURALMINDS_REFUSAL_THRESHOLD` | `0.5` | Minimum match score when no keyword matches |
| `RURALMINDS_MAX_QUEUE` | `30` | Questions allowed to wait before "busy" |
| `RURALMINDS_STUDENT_IDLE_MINUTES`, `RURALMINDS_TEACHER_IDLE_MINUTES` | `30`, `480` | Automatic sign-out (shared phones) |
| `RURALMINDS_LOGIN_MAX_FAILURES` | `5` | Wrong passwords before a wait |
| `RURALMINDS_MAX_UPLOAD_MB`, `RURALMINDS_MAX_PAGES` | `60`, `400` | Upload limits |
| `RURALMINDS_MIN_FREE_DISK_GB`, `RURALMINDS_MAX_INGEST_ATTEMPTS` | `2`, `3` | Disk safety margin, retries after a failure |

## Tests and evaluation

```powershell
uv run pytest                                  # unit + API tests
npm --prefix frontend run check                # frontend type check
uv run python -m eval.run --testset eval/samples/questions_dev_en_ml.jsonl --label my-run
```

## Licence

Apache-2.0 ([`LICENSE`](LICENSE)). Textbook PDFs, model weights and the database are never committed. SCERT textbooks are © Department of Education, Government of Kerala; permission for redistribution is pending. Third-party licences are in [`docs/licenses/`](docs/licenses/).
