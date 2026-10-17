# CLAUDE.md — RuralMinds

Read this first, every session. Deeper detail lives in `docs/` — read the relevant doc before working on that area.

| Read before working on… | File |
|---|---|
| Why the project exists, scope, non-goals | `docs/GOAL.md` |
| System design, data flow, components | `docs/ARCHITECTURE.md` |
| How answers must behave (citations, refusal, hints) | `docs/ANSWER_POLICY.md` |
| What to build now vs later | `docs/ROADMAP.md` |
| Past decisions (don't re-litigate) | `docs/DECISIONS.md` |
| Hackathon demo flow | `docs/DEMO_SCRIPT.md` |
| **Current Phase 0 design, day plan, conflicts resolved** (wins where `ARCHITECTURE.md` differs) | `docs/SYSTEM_DESIGN.md` |

---

## 1. Project overview
- **Name:** RuralMinds
- **What it does:** An offline-first learning server for rural schools. Teachers load textbook PDFs; students connect their phones to the school's local Wi-Fi (no internet) and ask questions; a small local LLM answers using RAG over the textbook, **always citing chapter and page**, and refusing when the textbook doesn't cover it.
- **Who it's for:** Grade 8–10 students (maths + science first) in rural government schools, used in a supervised "RuralMinds hour" at school or a village study point. Teachers approve content and cached answers.
- **Context:** Entry for MyBharat Hack for Social Cause (HSC) 2027, Kerala round. **Submission deadline: Tue 27 Oct 2026** (moved from 15 Oct; see `docs/DECISIONS.md` 2026-10-17). Judges value a *working, provably offline demo* with *measured* numbers over ambition.
- **North star:** A phone in airplane mode (Wi-Fi only) asks a textbook question and gets a correct, cited, checkable answer from a box in the room. Everything else is secondary.

## 2. Non-negotiable rules (break these and the project fails)
1. **Offline core.** The question → retrieval → generation → answer path must never call the internet. No cloud APIs, no CDN fonts/scripts, no telemetry, no runtime model downloads. Every JS/CSS asset is bundled locally.
2. **Grounded answers only.** Every AI answer carries `[chapter, page]` citations from retrieved chunks. If retrieval confidence is below threshold, refuse politely (see `docs/ANSWER_POLICY.md`). Never invent textbook facts or page numbers.
3. **One pinned model.** No runtime model switching/rerouting. One model per hardware tier, loaded once.
4. **Children's privacy (DPDP-ready).** Never collect phone number, email, Aadhaar, APAAR or other IDs from students. No per-child tracking dashboards, no third-party trackers. Student data never leaves the school server.
5. **Label everything.** Each answer is labelled `AI explanation` or `Teacher-approved`. Forum content (later) is labelled `Student`.
6. **Measure, don't claim.** Never hard-code or write performance/accuracy/concurrency/cost numbers into docs or UI that weren't measured by `eval/` or `scripts/bench.sh`.

## 3. Tech stack
- **LLM runtime:** `llama.cpp` → `llama-server` (OpenAI-compatible HTTP), bound to 127.0.0.1. **Not Ollama** (serializes requests; poor concurrency). Ollama may only be used as a source of GGUF files.
- **Model (pinned):** decided by the Tue 13 Oct bake-off on the eval dev split: `Qwen3-4B-Instruct-2507` Q4_K_M vs `Gemma 4 E2B` Q4_K_M. One winner, loaded once, recorded in `docs/DECISIONS.md`. No runtime switching.
- **Embeddings:** `bge-m3` GGUF served by a second `llama-server --embedding` (keeps the stack torch-free).
- **Backend:** Python 3.12, FastAPI, Uvicorn. `httpx` to talk to llama-server. Raw SQL via stdlib `sqlite3` for Phase 0 (SQLAlchemy/Alembic are installed but unused until the schema stabilises).
- **Storage & retrieval:** One SQLite file — FTS5 (keyword/BM25) + `sqlite-vec` (vectors), merged by reciprocal-rank fusion. WAL mode on.
- **PDF ingestion:** `pypdfium2` (not PyMuPDF — AGPL). Tesseract (`mal`, `eng`) for pages with no usable text layer, including legacy-font (ML-TT) Malayalam pages.
- **Citations:** the model cites sources as `[S1]…[S4]`; the server maps them to chapter + printed page from `apps/api/books.toml`. The model never writes page numbers.
- **Maths check (Phase 1):** SymPy validates arithmetic once maths is indexed.
- **Frontend:** SvelteKit (static adapter), built to static files and served by FastAPI. Mobile-first, works on cheap Android Chrome. No external CDNs. No service worker over plain HTTP (browsers won't register one on a LAN IP), so `vite-plugin-pwa` stays disabled until the HTTPS option exists.
- **Network (demo):** Windows Mobile Hotspot on the laptop (no upstream internet); phones reach `http://<hotspot-IP>:8000` via QR card + IP. Fallback: Ubuntu with a NetworkManager hotspot + `dnsmasq` (`ruralminds.lan`, answers Android's `generate_204`). **Never `.local`.**

Don't add a new library or framework without asking me first and saying why. Prefer the standard library.

## 4. Folder structure
```
RuralMinds/
├── CLAUDE.md
├── README.md
├── LICENSE                     # Apache-2.0
├── docs/                       # goal, architecture, answer policy, roadmap, decisions, demo, SYSTEM_DESIGN
│   └── licenses/               # third-party model/tool licences
├── apps/
│   ├── api/
│   │   ├── books.toml          # book manifest: medium, subject, chapters, page mapping
│   │   ├── src/ruralminds/
│   │   │   ├── main.py         # FastAPI app + routes
│   │   │   ├── config.py       # settings from .env (prefix RURALMINDS_)
│   │   │   ├── db.py, schema.sql   # sqlite3 + sqlite-vec; schema is the source of truth
│   │   │   ├── ingest.py       # PDF → pages (text or OCR) → chunks → embeddings → SQLite
│   │   │   ├── retrieve.py     # hybrid FTS5 + vector search, RRF, medium/subject/chapter filter
│   │   │   ├── answer.py       # cache → retrieve → gate → prompt → llama-server → marker check → label
│   │   │   ├── llm.py          # llama-server client (chat stream + embeddings)
│   │   │   ├── cache.py        # teacher-approved exact-match cache
│   │   │   └── prompts/        # system prompt templates (versioned)
│   │   └── tests/
│   └── worker/                 # background jobs (stub in Phase 0)
├── frontend/                   # SvelteKit app (student + teacher screens)
├── eval/                       # test set + evaluation runner + bench + results
├── scripts/                    # start servers, power sampling
├── packaging/                  # Linux packaging (Phase 2)
├── implementation/             # plan.md blueprint + original scaffold (reference only)
├── models/                     # GGUF files — git-ignored, never committed
└── data/                       # SQLite DB, OCR cache — git-ignored
```
Keep files in the matching folder. Ask before creating a new top-level folder.

## 5. Commands
```powershell
# one-time setup
uv sync
npm --prefix frontend install

# start the model servers + API (needs models/ populated)
./scripts/start_all.ps1

# ingest a textbook listed in apps/api/books.toml
uv run python -m ruralminds.ingest --book ss8-pt1-en

# first run: create the admin (prints a one-time recovery code); demo accounts for the judges
uv run python -m ruralminds.admin init
uv run python -m ruralminds.admin demo

# run the API alone (serves frontend/build too)
uv run uvicorn ruralminds.main:app --host 0.0.0.0 --port 8000

# frontend dev / build
npm --prefix frontend run dev
npm --prefix frontend run build

# tests and evaluation
uv run pytest
uv run python -m eval.run --testset eval/datasets/testset.jsonl --out eval/results/
uv run python -m eval.bench          # latency + concurrency
```
_These are the target commands from `docs/SYSTEM_DESIGN.md`; the modules are being built Mon–Tue._
After changes: run `pytest`. After anything touching retrieval, prompts or the model: run the eval and report the before/after numbers.

## 6. How I want you to work with me
I'm an engineering student and still learning, and we are on a hard deadline.
- **Plan before big changes.** If a change touches more than 2 files, give a short plan and wait for my OK.
- **Teach, don't just fix.** When you fix a bug, explain the cause and the fix in a few lines.
- **Small steps.** One working, testable change at a time. Working ugly code beats unfinished pretty code before 15 Oct.
- **Be honest.** If my idea is wrong, too big for the deadline, or contradicts `docs/`, say so directly.
- **Scope guard.** If I ask for something in the "Later / Cut" list in `docs/ROADMAP.md`, remind me and ask if I really want it now.
- **Ask when unsure.** Don't guess requirements.

## 7. Code style
- Python: type hints everywhere, `async` for I/O, functions under ~40 lines, `ruff` for lint/format.
- Svelte/TS: small components, plain scoped CSS, no heavy UI kits. Keep the bundle small (target < 300 KB gzipped).
- Clear names (`retrieved_chunks`, not `rc`). Comment the *why*, not the *what*.
- Errors: no bare `except`. Return friendly student-facing messages; log the technical detail.
- Config from `.env` via `config.py`. No hard-coded paths, ports, thresholds or secrets.
- Prompts live in `apps/api/src/ruralminds/prompts/` as files with a version line, never inline strings scattered through code.
- UI text must be translatable (keys in `frontend/src/lib/i18n/{en,ml}.json`), large fonts, works at 360 px width.

## 8. Testing & evaluation
- Unit tests for: chunking (never splits a worked example or exercise), retrieval filters, cache keying/invalidation, refusal threshold, SymPy check, JSON validation.
- `eval/testset.jsonl` is the quality gate. Metrics: retrieval recall@3, answer accuracy, refusal accuracy, p50/p95 time-to-first-token and total latency.
- Only claim Malayalam support after the Malayalam slice of the eval passes.

## 9. Git rules
- Don't commit or push unless I ask. Commit messages: `feat:`, `fix:`, `docs:`, `eval:`, `chore:`.
- Never commit: `.env`, `models/`, `*.gguf`, `data/`, `node_modules/`, textbook PDFs, student data.
- Repo must stay public-ready with an open licence (Apache-2.0).

## 10. Don'ts
- Don't add internet calls, analytics, CDN links or cloud fallbacks — not even "just for dev".
- Don't build: IVR/dial-up, model rerouting, attendance/timetable ERP, in-browser load simulator, open forum (deferred).
- Don't use semantic cache matching in the demo build (false hits). Exact-match teacher-approved cache only.
- Don't delete files or big blocks of code without asking.
- Don't invent APIs, library functions or CLI flags. If unsure a flag exists, say so and check the docs/`--help`.

## 11. Current focus
<!-- Update as the project moves -->
- **Now (17 → 27 Oct):** measurement first (v2 eval set with frozen test split, standard metrics + CIs, answer-quality rubric, server bench), then fixes, topic-less requests + creativity limits, Manglish, load control + exam-revision chips, Science Pt1 EN with tables. Order and details: DECISIONS 2026-10-17.
- **Done by 15 Oct:** Phase 0 — Kerala SCERT Class 8 Social Science Part 1 in **English and Malayalam** (Malayalam via OCR) → hybrid retrieval → streamed answer with `[Sn]` citations rendered as chapter + page → refusal path + unanswered list → exact-match cache + teacher screen → measured EN vs ML eval, bench, power and recovery numbers. Day plan: `docs/SYSTEM_DESIGN.md` §4. Added 13 Oct (DECISIONS): accounts for students/teachers/admin (username + class only), teacher PDF upload with validation and power-cut-safe ingestion, admin controls (pause, language/class limits, stats).
- **Next (Phase 1):** Maths + Science in English (Basic Science Pt1 first, then Maths via OCR), then Malayalam; JSON schema + SymPy + hint-first; Manglish via IndicXlit; Linux node with dnsmasq.
- **Known risks:** Malayalam OCR quality and prefill latency, Windows hotspot without internet (fallback: Ubuntu), small-model citation compliance, SCERT textbook licence unconfirmed.

## 12. Decisions log
See `docs/DECISIONS.md`. Add a line there whenever we decide something non-obvious.
