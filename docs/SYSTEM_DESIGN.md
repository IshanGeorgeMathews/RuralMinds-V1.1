# RuralMinds — System Design (Phase 0 → Phase 2)

_Status: approved design, 12 Oct 2026. Deadline: Thu 15 Oct 2026. Sources reconciled: `implementation/CLAUDE.md` + `implementation/Claude_ruralminds/ruralminds/docs/*` (binding rules) and `implementation/plan.md` (long-term blueprint). Numbers in this document are either from the 12 Oct inventory or marked "not measured" until `eval/` produces them._

## 1. North star and the rules we design against
- **North star:** a phone in airplane mode (Wi-Fi on) asks a textbook question. It gets back a correct answer that cites the chapter and page, and the student can check that page on the spot. The answer comes from a laptop in the room with no internet.
- **Binding rules (CLAUDE.md §2):**
  - offline core
  - cited, grounded answers or a polite refusal
  - one pinned model
  - no personal data about students
  - every answer labelled
  - only measured numbers

> **Scope change, recorded honestly.** CLAUDE.md, ROADMAP and DECISIONS (11 Oct) froze the scope to "Maths + Science, NCERT Class 9–10, English first". The team has now chosen **Kerala SCERT Class 8 Social Science, English + Malayalam** as the 15 Oct corpus.
>
> Reasons:
> - Only Kerala SCERT books are on disk.
> - English Social Science has a clean text layer.
> - The Malayalam edition *appears* page-parallel to it. Only p.11 (Bhimbetka) has been checked so far; more pages get checked on Monday. If it holds, the language comparison is directly measurable.
>
> The rule "claim Malayalam only after its eval passes" still holds. The comparison *is* that eval. Maths, Science, SymPy checks and hint-first mode move to Phase 1. Pending (separate approval): a line in DECISIONS.md and an update to CLAUDE.md §11.

## 2. Inventory: what's installed and what it means

### 2.1 Machine and tools (checked 12 Oct)
| Item | State | What it means for the plan |
|---|---|---|
| Laptop | Ryzen 7 7730U, 8C/16T, 13.9 GB RAM, iGPU, Windows 11, **22 GB free disk** | This is the demo server (tier A) and the only hardware we can measure before the deadline. Every N100/school-box figure stays "not measured". |
| llama.cpp | `llama-server` b11556 (CPU build) on PATH; `llama-bench` and `llama-batched-bench` present | The runtime is ready |
| Ollama 0.40.2 | `gemma4:e2b` (Q4_K_M, Apache 2.0 per `ollama show --license`) plus older models | Used only as a GGUF *file source* for the bake-off. Not in the answer path (CLAUDE.md: not Ollama). |
| Python `.venv` 3.12 | fastapi, uvicorn, httpx, pydantic-settings, pypdfium2 5.14, sqlite-vec 0.1.9, aiosqlite, pytest, ruff, (SQLAlchemy/Alembic unused in the MVP) | SQLite 3.53.1, FTS5 and sqlite-vec all load. That's verified. |
| Tesseract 5.5.3 | `eng`, `mal`, `osd` | Malayalam OCR is possible. In a 2-page sample it took 3–5 s per page at 300 DPI, and body text read well. |
| Node 22 / npm 10 | SvelteKit 2 scaffold with vite-plugin-pwa | Keep SvelteKit and **disable the PWA plugin** (see C8) |
| IndicXlit | Checkpoint and source present; no fairseq installed | Can't run. Manglish handling moves to Phase 1. |
| Not present | `sqlite3` CLI, dnsmasq, Caddy, systemd (this is Windows) | Phones find the server by QR code + IP; no `.lan` name for the demo |

### 2.2 Models: what's missing
| Needed | On disk? | Action |
|---|---|---|
| Qwen3-4B-Instruct-2507 Q4_K_M GGUF (~2.5 GB) | No | **Download today** for the bake-off |
| Gemma 4 E2B GGUF | Inside an Ollama blob | Load the blob path in `llama-server` and test it today. Thinking is on by default, so turn it off; check the exact flag with `llama-server --help`. **If the blob won't load:** run the local `llama-quantize` on the already-pulled `ggml-org/gemma-4-E2B-GGUF:BF16` blob to make a Q4_K_M. That needs no download and keeps the bake-off fair against Qwen's Q4_K_M. |
| bge-m3 GGUF (dense, ~0.6 GB at Q8_0) | No. Only the HF PyTorch and ONNX copies exist, and `llama-server` can't load either. | **Download today.** Serve it with `--embedding`; confirm the pooling flag with `--help`. |
| bge-reranker-v2-m3 | Safetensors only | Not in the MVP. A Phase 1 experiment. |

### 2.3 PDFs (Kerala SCERT Std VIII, 2015, at `docs/Class-8 scert textbook/`)
| Book | Pages | Text layer | Role |
|---|---|---|---|
| EN Social Science Pt1 (7 chapters: Early Human Life … Economic Thought) | 120 | Clean Unicode. Junk "1234567890…" rule lines need filtering. Printed page numbers aren't in the text layer; the TOC suggests PDF page = printed page (to be checked by eye on 5 pages). | **Phase 0, English** |
| ML Social Science Pt1 (`social_science_mal_pt1.pdf`) | 120 | Legacy ASCII (ML-TT) font, so the text layer is gibberish. **OCR every page.** | **Phase 0, Malayalam** |
| EN/ML Social Science Pt2 | 104 / 104 | Same as Pt1 | Not indexed. Its topics become **near-miss refusal questions**. |
| EN Basic Science Pt1 | 159 | Clean; running header shows printed page = PDF page (137 pages checked, 0 mismatches) | Phase 1, first. Optional stretch on Tuesday if everything is green. |
| EN Basic Science Pt2 | 128 | Clean, but printed pages start at about 167, so there's a page offset | Phase 1 |
| Maths Pt1 (English text, in `malayalam_medium/maths_pt1.pdf`) | 96 | Custom font encoding, so OCR is needed. In a 2-page test, symbols were mangled (∠→Z) and sidebars interleaved. | Phase 1 (risky) |
| All other Malayalam-medium books | 60–159 | Legacy font, so OCR is needed | Phase 1+ |

### 2.4 Datasets
None of these covers SCERT Class 8, so **the gold eval set is written by hand**. Sizes come from dataset READMEs; the parquet files weren't opened.

| Dataset | Contents / format / size | Usable for the eval? |
|---|---|---|
| L3Cube-IndicQuest | 200 QA pairs per language (EN, ML …) on history, geography, politics and economics. CSV, ~130 KB. | Yes, as a **refusal pool**, but only after removing items that Social Science Pt1 actually covers. It overlaps our subject. |
| Indic-Rag-Suite (en, ml) | LLM-generated Wikipedia QA (`question`, `answer`, `paragraph`, `model_name`). Parquet, 2.4 GB + 0.66 GB. | Only as an off-topic refusal and distractor pool. Never gold. |
| Bharat_NanoTouche2020_ml | Malayalam IR set: 49 queries / 5,745 docs / 932 qrels. Parquet, 12 MB. | Phase 1: sanity-check bge-m3 Malayalam retrieval |
| Dakshina-romanized-ml | 185,673 ml↔Latin word pairs. Parquet, 4.5 MB. | Phase 1: Manglish |
| IndoNLP-Transliteration-ml | Manglish→ML sentences: 5,000 train / 2,500 valid rows. CSV, 3.6 MB. | Phase 1: Manglish normaliser |
| L3Cube-IndicNews, IndicSQuAD (README only), nlp-for-manglish | News classification, missing data, ULMFiT embeddings | No |

## 3. Architecture (Phase 0)

```
 Student phone (Chrome, airplane mode + Wi-Fi)      Teacher (phone/laptop browser)
            │  http://<hotspot-IP>:8000  (QR card)          │
            ▼                                                ▼
 ┌──── Windows Mobile Hotspot on the laptop (no upstream internet) ────┐
 └─────────────────────────────────────────────────────────────────────┘
            ▼
 ┌──────────────────────── RuralMinds laptop ─────────────────────────┐
 │ FastAPI :8000 (apps/api)  — serves frontend/build + JSON/SSE API    │
 │   cache → retrieve (FTS5 + sqlite-vec, RRF) → gate → prompt →       │
 │   llama-server stream → citation check → label → SSE to phone       │
 │ llama-server 127.0.0.1:8080  pinned chat model (bake-off winner)    │
 │ llama-server 127.0.0.1:8081  bge-m3 --embedding                     │
 │ SQLite data/ruralminds.db (WAL)   data/ocr/ (cached OCR text)       │
 │ Battery = built-in UPS                                              │
 └─────────────────────────────────────────────────────────────────────┘
```

### 3.1 Components mapped to repo files
`[new]` means the file is created during the build; `[exists]` means it's already there.

| Component | File(s) | Responsibility |
|---|---|---|
| App + routes | `apps/api/src/ruralminds/main.py` [exists] | <ul><li>`POST /api/ask` (SSE events: `queued{pos}`, `token`, `citations`, `done`, `refused`)</li><li>`GET /api/catalog` (books and chapters per medium)</li><li>`GET /api/page/{doc_id}/{page}.png` (rendered textbook page, so a citation opens the real page)</li><li>`GET /generate_204`</li><li>`GET /health`</li><li>Teacher routes</li><li>Static mount of `frontend/build`</li></ul> |
| Settings | `.../ruralminds/config.py` [new] | pydantic-settings with prefix `RURALMINDS_`. Holds ports, model URLs, thresholds, top-k, token caps and the teacher PIN hash. **`LLM_BACKEND=ollama` is removed from `.env.example`.** |
| DB | `.../ruralminds/db.py`, `.../ruralminds/schema.sql` [new] | <ul><li>Stdlib `sqlite3` with WAL, `foreign_keys` and `busy_timeout`.</li><li>Loads sqlite-vec and applies the schema.</li><li>The schema adapts `implementation/.../db/schema.sql`, keeping documents, chunks, `chunks_fts`, `vec0`, `answer_cache`, `unanswered` and `usage_daily`.</li><li>It **drops** users, groups and assignments for the MVP, since there's no student login.</li></ul> |
| Book manifest | `apps/api/books.toml` [new] | Per PDF: title, medium, subject, grade, part, `page_offset`, and chapter→page ranges taken from the TOC. Citations come from this manifest, never from the model. |
| Ingestion CLI | `.../ruralminds/ingest.py` [new] (`python -m ruralminds.ingest --book <id>`) | <ul><li>Extract with pypdfium2.</li><li>**Per-page classifier** (Malayalam-block ratio plus a gibberish heuristic): unicode, legacy font, or empty. Anything not unicode goes to Tesseract `mal+eng` at 300 DPI, cached in `data/ocr/<sha>/<page>.txt`.</li><li>Clean junk lines.</li><li>Chunk by heading/paragraph at about 250–350 tokens without crossing activity boxes, keeping `chapter_no`, `page_start` and `page_end`.</li><li>Embed in batches, then insert in a single transaction so a crash leaves no half-ingested book.</li><li>Record a SHA-256 per book.</li></ul> |
| Retrieval | `.../ruralminds/retrieve.py` [new] | <ul><li>Hard filters: medium, subject and an optional chapter.</li><li>FTS5 BM25 top-20 plus vector top-20, merged with RRF (k=60), keeping the top 3–4.</li><li>Returns fused scores and features for the refusal gate.</li></ul> |
| Answering | `.../ruralminds/answer.py`, `.../ruralminds/prompts/system_v1_{en,ml}.md`, `.../ruralminds/llm.py` [new] | <ul><li>Exact-match cache, then retrieve, then the confidence gate, then the prompt (fixed system prompt first so its prefix can be reused, then sources labelled `[S1]…[S4]`, the last 2 turns and the question).</li><li>Streams from llama-server.</li><li>The server checks every `[Sn]` marker, drops invalid ones, and turns an answer with **no valid marker into a refusal**.</li><li>Valid markers are rendered as "Ch 1, p 11".</li><li>Labels the answer and logs aggregates.</li></ul> |
| Queue | inside `answer.py` | An asyncio semaphore sized to llama-server's parallel slots. Waiting requests receive `queued{pos}`. There's a cap on the queue length, and a disconnect cancels the upstream stream. |
| Cache | `.../ruralminds/cache.py` [new] | Key = hash(normalised question, language, subject, chapter, book SHA). Only teacher-approved entries are served. A new book SHA marks entries `needs_review`. |
| Teacher screen | `frontend/src/routes/teacher/` + `/api/teacher/*` | <ul><li>Shared teacher PIN; hashed with stdlib `hashlib.scrypt`, so no new library.</li><li>Shows the "Couldn't answer" list (no student identifiers).</li><li>Approve or reject a live answer into the cache, with the source passage shown.</li></ul> |
| Student UI | `frontend/src/routes/+page.svelte`, `ask/` + `src/lib/i18n/{en,ml}.json` | <ul><li>Flow: pick language/medium, then chapter, then ask. The answer streams into a card showing the label ("AI explanation — from your textbook, may contain mistakes" or "Teacher-approved") and citation chips that open the page image.</li><li>Buttons: Stop, and "New question" (clears history).</li><li>Works at 360 px, uses large type, and has no external assets.</li></ul> |
| Eval | `eval/datasets/testset.jsonl`, `eval/run.py`, `eval/bench.py`, `eval/results/` [new] | Covered in §5 |
| Ops scripts | `scripts/start_all.ps1` (+ `start_llama.sh` for Linux), `scripts/power.ps1` [new] | <ul><li>Start both llama-servers and the API with pinned flags.</li><li>Sample battery discharge rate (WMI `BatteryStatus`; check that it's available) while running on battery, to get measured watts.</li></ul> |
| Worker | `apps/worker` [exists] | Stays a stub in Phase 0. Ingestion runs as a CLI before the demo. |
| Answer shape per subject | `prompts/system_v1_social_{en,ml}.md` | ANSWER_POLICY §2 assumes maths: concept → worked example → practice question. For Social Science the shape is a 2–4 sentence explanation, then "What your textbook says" (key points with `[Sn]`), then one "Check yourself" question. Needs an ANSWER_POLICY line (separate approval). |
| Teacher upload | CLI in Phase 0 | The ROADMAP MVP item "Teacher: upload + publish" becomes **the ingest CLI run by us** before the demo. A browser upload form moves to Phase 1. Stated openly. |
| Unit tests | `apps/api/tests/` | As required by CLAUDE.md §8: <ul><li>chunker (page tags kept, no empty or junk chunks)</li><li>page classifier (legacy-font page goes to OCR)</li><li>retrieval filters (medium and chapter respected)</li><li>RRF</li><li>cache key and invalidation on a new book SHA</li><li>refusal gate threshold</li><li>marker validation (an invalid `[S9]` gets dropped; no markers means a refusal)</li></ul> |

Answer output is **plain text with `[Sn]` markers, streamed**, rather than the JSON schema in ANSWER_POLICY §9. There are two reasons:
1. The model never writes page numbers, so it cannot make one up. That is stronger than checking afterwards.
2. Tokens can be streamed to the phone, so time-to-first-token is visible.

**Streaming vs grounding (rule 2).**
- Tokens stream into a card marked **"checking sources…"**, with no label or citations yet.
- On `done`, the server validates the markers:
  - **If they pass:** it attaches the citation chips and the exact label "AI explanation — from your textbook, may contain mistakes".
  - **If they fail:** the server sends `refused`. The phone **replaces the whole card** with the refusal text (ANSWER_POLICY §4), and the question is logged to `unanswered`.
- **Definition of "refused" for eval scoring:** the confidence gate tripped, OR the answer had no valid marker.

The JSON schema plus SymPy comes back in Phase 1 for maths mode (C12).

### 3.2 Three points of view

**Students on cheap, shared Android phones**
- **Getting in:**
  - Scan the QR card, or type the IP.
  - No login, no app install, no service worker (it won't register over plain-HTTP LAN).
  - The page is small: target under 300 KB gzipped, to be measured at build time.
- **Shared-phone privacy:**
  - Conversation history lives only in page memory and is sent with each request.
  - "New question" clears it.
  - Nothing is stored about the student, either on the phone or on the server.
- **Flaky Wi-Fi and waiting:**
  - The phone shows its place in the queue and streams tokens as they arrive.
  - There's a Stop button.
  - A dropped connection shows "Can't reach the school computer, check you're on RuralMinds Wi-Fi" with a Retry button.
- **Language:**
  - The student picks English or Malayalam; UI strings come from `en.json`/`ml.json`.
  - Malayalam relies on the phone's system font. We bundle Noto Sans Malayalam only if a test phone renders it badly.

**Teachers and admins on low-cost hardware with unreliable power**
- **Start-up:** one script, `scripts/start_all.ps1`, starts everything. `/health` shows a light for the LLM, the embedder and the database, plus free disk space.
- **Power:**
  - The laptop battery acts as the UPS.
  - SQLite runs in WAL mode, and each book is ingested in one transaction.
  - Restarting after a kill is a scripted test (§5).
- **Content:**
  - Books go in through the ingest CLI. The PDFs stay local and never go into git.
  - The teacher screen holds the unanswered queue and the approve/reject controls.
- **Deferred:**
  - Linux appliance (systemd, dnsmasq, `.deb`, setup wizard), USB backup button, N100 node: Phase 1–2.
  - **Manual backup in Phase 0:** copy `data/ruralminds.db` using `VACUUM INTO`.

**Judges**
- **Offline proof:**
  - Laptop: not connected to any upstream network (it only hosts the hotspot), no Ethernet, and `ping 8.8.8.8` fails on camera.
  - Phones: airplane mode plus Wi-Fi joined to the laptop hotspot.
- **Citations:**
  - Every answer chip opens the actual rendered textbook page.
  - Citation validity holds by construction, and **support** is measured as recall@3.
- **Handling what it can't answer:**
  - Refusal is tested with near-miss questions (Pt2 topics, other classes) as well as off-topic ones.
  - Every refusal is logged to the teacher list.
- **Correctness, English vs Malayalam:** a side-by-side table of the same questions, measured.
- **Cost and scale:**
  - Only measured figures: questions per hour at 1/2/3 concurrent phones on this laptop, and watts drawn on battery.
  - Hardware prices and N100 capacity are explicitly marked "not measured".

## 4. Phase 0 build plan (Mon 12 → Thu 15), with "done when" checks

### Mon 12 (rest of today)
| Task | Done when |
|---|---|
| **Admin:** save the complete v1 on the MY Bharat portal (ROADMAP) | The portal shows v1 saved |
| Download the Qwen3-4B-2507 Q4_K_M and bge-m3 GGUFs. Start both servers. Load Gemma 4 E2B from the Ollama blob in `llama-server`. | `/health` on :8080 and :8081 returns ok, and one chat completion works per model |
| Hotspot test: laptop hotspot with no internet, all 3 phones in airplane mode + Wi-Fi, a Windows Firewall inbound rule for :8000 | A phone opens `http://<hotspot-ip>:8000/health`. **If the Windows hotspot won't start offline, switch to the Ubuntu fallback** (§7 R3). |
| `schema.sql` + `db.py` + `books.toml` (EN and ML Social Science Pt1). Check page mapping by eye on 5 pages per book. | A script prints chunk counts. FTS search for "Bhimbetka" in the EN book returns p 11. `pytest` passes the chunker and page-classifier tests. |
| OCR the ML Social Science Pt1 book in the background | `data/ocr/` holds 120 pages, and a per-page Malayalam-ratio report flags weak pages |
| Team: start writing eval items for Ch 1, 2 and 4, in EN and ML in parallel | ≥40 items drafted |

### Tue 13
| Task | Done when |
|---|---|
| `retrieve.py` (filters + hybrid + RRF) and `answer.py` (prompt, stream, marker check, refusal gate, label) | `curl` gets a cited EN answer, a cited ML answer, and a refusal for an off-syllabus question. `pytest` passes the filter, RRF, cache, gate and marker-validation tests. |
| **Bake-off (by about 13:00):** run the same 20 **dev-split** items (10 EN, 10 ML) through Qwen3-4B-2507 and Gemma 4 E2B, with identical retrieval and prompts. Using the dev split keeps the reported test numbers uncontaminated. Score: correctness and marker compliance (human-scored), refusal compliance, TTFT and tok/s for EN and ML, peak RAM. | Results saved in `eval/results/bakeoff-*.json`. Model pinned by the rule "higher correctness; on a tie, the faster one". A line added to DECISIONS. |
| Frontend: student flow + teacher screen; disable vite-plugin-pwa | Works on a real phone at 360 px over the hotspot; build size recorded |
| Exact-match cache + unanswered list | An approved answer comes back labelled "Teacher-approved" with no LLM call |
| Eval set finished; refusal threshold tuned on the **dev split only** | ≥100 items (§5); threshold value is in `.env` with a note on the split |

### Wed 14
| Task | Done when |
|---|---|
| `eval/run.py` on the test split, for EN and ML (plus the cross-lingual arm) | A results JSON is committed with model, quantisation, hardware, prompt version and threshold |
| `eval/bench.py` at 1, 2 and 3 concurrent phones (real phones; a script can add more simulated clients), with `-np 1` vs `-np 2` | p50/p95 TTFT and total time, plus questions per hour, recorded |
| Power and recovery: measure watts on battery during the bench; kill the API and the llama-servers and restart them | Measured watts recorded. After restart, chunk counts and an answer are unchanged. |
| README measured-results table; numbers in this document filled in from `results/` only. Fix `docs/licenses/gemma`; add an Apache-2.0 `LICENSE`. | Every number has a source file |
| Record the 3–5 minute uncut demo (§6), plus a backup take | Video file plays |
| **Admin:** upload the final version | Upload confirmed |

### Thu 15: no new features
- Re-check that the repo is public-ready (no PDFs, models or `.env` committed), that the video plays, and that the links work. Then submit.

**Stretch (only if Tuesday ends green):** index EN Basic Science Pt1, which has clean text, as a second subject.

## 5. Evaluation design (the proof)
- **Test set:** `eval/datasets/testset.jsonl`, written by the team from the books. The questions are our own work; no textbook text is copied into the repo.
  - About 60 EN answerable items across Ch 1, 2 and 4.
  - About 40 ML items: the same questions in Malayalam. The editions appear page-parallel, so they can share gold pages; check each one.
  - About 25 refusal items:
    - **Near misses:** Pt2 topics and Class 9 history in EN and ML.
    - **Off-topic:** from IndicQuest and Indic-Rag-Suite, after removing anything Pt1 covers.
  - About 10 follow-up pairs.
- **Split:** a dev split (about 30%) is used to tune the threshold and prompt **and to run the model bake-off**. Numbers are reported on the held-out test split.
- **Metrics:**
  - recall@3: a gold page appears among the top-3 chunks' pages
  - answer accuracy: graded by 2 team members on a 0/1/2 rubric, with agreement reported
  - refusal accuracy, both missed refusals and wrong refusals
  - citation support: the cited source contains a gold page
  - TTFT and total latency, p50/p95
  - prompt tokens for EN vs ML (Malayalam uses many more tokens per word, which drives prefill cost)
- **Arms:**
  - (a) EN question → EN book
  - (b) ML question → ML book (OCR text)
  - (c) ML question → EN book (cross-lingual bge-m3). This shows whether OCR noise or the model limits Malayalam.
- **Claim rule:** Malayalam is called "supported" only if arm (b) clears targets fixed in advance: recall@3 ≥ 0.8 and accuracy ≥ 70%. These targets are proposed, and the team confirms them before the run. Otherwise we present it as "measured, not yet passing".

## 6. Demo (3–5 min, uncut)
1. Show the laptop with internet off and `ping` failing. The phone is in airplane mode and joins the hotspot.
2. Scan the QR code, pick English → Social Science → Ch 1, and ask. The answer streams with "Ch 1, p 11". Tap the chip to show the real page.
3. Ask the same question in Malayalam.
   - **If arm (b) passed:** present it as "Malayalam supported".
   - **If it didn't:** present it as "our measured EN vs ML comparison", showing the answer next to the numbers. Either way it is never presented as more than the eval shows (DEMO_SCRIPT rule).
4. Ask a follow-up.
5. Ask a near-miss question (a Pt2 topic): polite refusal, and it appears on the teacher list.
6. On the teacher screen, approve an answer, then ask it again: instant, labelled "Teacher-approved".
7. All 3 phones ask at once: show queue positions.
8. Unplug the charger and keep serving. Kill and restart the server; the index is intact.
9. Numbers slide: EN vs ML table, refusal, latency, phones served, watts. All from `eval/results`, with the method stated.

## 7. Our edge and the top risks

**Edge (each one provable live):**
- The offline setup is visible on camera.
- Clicking a citation opens the real page.
- A **measured English vs Malayalam comparison on the same textbook** that no other team will have.
- Refusals tested on near-miss questions.
- Teacher-approved cache.
- Zero student data by design: show the schema.
- A measured, not claimed, power and capacity sheet.

| # | Risk | Fix |
|---|---|---|
| R1 | Malayalam OCR noise; display fonts garbled | Body text read well in the sample. Use a per-page Malayalam-ratio QA, spot-check 5 pages by hand, and drop junk headings. Fall back to arm (c), cross-lingual retrieval over the EN book, and present the measured result honestly. |
| R2 | Malayalam prefill latency (many tokens per word) | Measure prompt tokens; use top-3 chunks for ML; stream; keep the system prompt identical so its prefix is reused |
| R3 | Windows Mobile Hotspot may refuse to start with no upstream internet. It also caps how many devices can connect (believed to be 8; check the settings page), which limits the concurrency demo and any scale claim. | Test today and record the cap. **Fallback (decided 12 Oct):** move the server to Ubuntu with a NetworkManager hotspot + `dnsmasq` (`ruralminds.lan`, `generate_204`). A school deployment uses a real access point (Phase 1). |
| R4 | Model downloads and disk (22 GB free) | About 3 GB of downloads fits. If space gets tight, the user may delete `dataset/indic-nlp/`, which is about 3.8 GB in total (1.5 GB `.git` pack plus the IndicNews zips) and which nothing uses. |
| R5 | A small model ignores the source markers or answers beyond the sources | The server strips invalid markers, and an answer with no valid marker becomes a refusal. Temperature 0.2, one short example in the prompt, and the bake-off scores this. |
| R6 | Refusal threshold over-fitted | Dev/test split; report both error types |
| R7 | Wrong page numbers (no page numbers in the Social Science text layer) | Map pages through `books.toml` and check 5 pages per book by eye. Citations come only from the manifest. |
| R8 | Windows Firewall or Wi-Fi client isolation blocks phones | Add an inbound rule for :8000 on the hotspot profile (the user runs it as admin) and test with 2 phones today |
| R9 | Not enough time to write eval items | Split the writing across the team. Parallel EN/ML items share gold pages. Cut follow-ups first. |
| R10 | Scope creep from plan.md | §8 cut list. Wednesday is bug fixes only; Thursday has no features. |
| R11 | Textbook rights | Never commit PDFs. Attribute SCERT. Note that permission is pending. |

## 8. Before vs after 15 Oct

**Phase 0 (by 15 Oct):**
- Social Science Pt1, EN + ML
- hybrid retrieval
- cited, streamed answers
- refusal + unanswered list
- exact-match cache + teacher screen
- eval + bench + power + recovery
- demo video

**Phase 1 (from 16 Oct, before the state jury):**
- Maths and Science in EN (Science Pt1 first, then Maths via OCR), then ML
- JSON answer schema + SymPy check + hint-first mode
- Manglish through IndicXlit (needs fairseq or a port), evaluated on IndoNLP and Dakshina
- bge-m3 check on Bharat-NanoTouche
- reranker experiment
- health page, USB backup
- Linux node with systemd + dnsmasq + `ruralminds.lan`
- N100 measurements

**Phase 2 (pilot):**
- class code + picture PIN sign-in (no IDs)
- groups, assignments, chapter packs, ask-later outbox
- setup wizard / `.deb`
- HTTPS option, which enables a service worker / installable PWA
- DPDP paperwork

**Cut or later (plan.md items):**
- module registry and editions
- quizzes, forum, analytics and mastery tracking (per-child tracking conflicts with rule 4 as written)
- semantic cache
- hosted cloud demo, portal, Cloudflare/R2
- signed `.rmpkg` updates
- Caddy

## 9. Where plan.md disagrees with CLAUDE.md / docs, with recommendations
| # | Topic | plan.md (and repo) | CLAUDE.md / docs | Recommendation |
|---|---|---|---|---|
| C1 | LLM runtime | llama-server, but the repo's `.env.example` says `ollama` | llama-server, never Ollama | **llama-server.** Fix `.env.example`. |
| C2 | Model | Gemma 4 E2B/E4B | Qwen3-4B-2507 pinned | **Bake-off on Tuesday, then pin one** (user's decision); record it in DECISIONS |
| C3 | Answer cache | Semantic at cosine ≥0.95 | Exact match, teacher-approved | **CLAUDE.md** (avoids false hits) |
| C4 | No retrieval hit | "Offer general help, labelled" | Strict refusal | **CLAUDE.md** (the grounding rule) |
| C5 | Student data | Per-student chat threads, learning events, mastery, consent records | No IDs, aggregates only | **CLAUDE.md** for Phase 0. Revisit consent-based features for the pilot. |
| C6 | Discovery | `ruralminds.local` via mDNS | Never `.local`; `ruralminds.lan` | **QR + IP for the demo** (Windows, no dnsmasq); `.lan` on the Linux node later |
| C7 | Cloud demo / portal | Hosted demo tenant | "Not a cloud app" | **Cut** |
| C8 | PWA | No service worker on plain HTTP (correct) | "Installable PWA" | **plan.md is right.** Drop the installable-PWA claim for HTTP and disable the plugin. |
| C9 | PDF library | pypdfium2 (PyMuPDF is AGPL) | PyMuPDF | **pypdfium2** (already installed, Apache/BSD licence) |
| C10 | Data layer | SQLAlchemy + Alembic | Raw `schema.sql` | **Raw SQL for Phase 0** (user's decision); Alembic when the schema stabilises |
| C11 | Layout / frontend | `apps/api`, `apps/worker`, SvelteKit | `server/`, `client/`, React | **Keep the repo layout and SvelteKit** (user's decision); update CLAUDE.md §4 |
| C12 | Citation format | `[n]` markers mapped by the server | `[Ch, p]` in JSON | **`[Sn]` markers, server renders Ch/p**; JSON + SymPy return for maths in Phase 1. Needs an ANSWER_POLICY/DECISIONS line. |
| C13 | Language and scope | Malayalam-first + Manglish, Class 8–10 | English first, Maths + Science, NCERT 9–10 | **User's decision:** Social Science EN + ML (measured) now; Maths/Science next; Manglish in Phase 1 |
| C14 | Reranker | On for 16 GB machines | None | **Off in Phase 0**; Phase 1 experiment |
| C15 | Context / token budget | 2,500 prompt / 320 output | ≤600 context / 300 output | Start around 600–900 context tokens (3–4 chunks), 300 output; **tune using measured TTFT** |
| C16 | Parallel slots | `--parallel 1` on small machines | `-np 2` | **Measure 1 vs 2** in the bench |
| C17 | Gemma licence | Apache 2.0 | `docs/licenses/gemma` says Gemma Terms | **Apache 2.0** (verified from the model's own licence text). Fix the file. |
| C18 | NCERT licence | Needs written permission | README says CC BY-NC-ND | Doesn't matter for Phase 0 (no NCERT). Never bundle; get advice before using NCERT. |
| C19 | Performance figures | tok/s, "60–120 questions/hr", RAM, ₹ prices | Measure, don't claim | **Removed or marked "not measured"** until `eval/` produces them |
| C20 | Doc placement | — | CLAUDE.md and docs live under `implementation/` | **Move them to the repo root** (user's call) so CLAUDE.md loads automatically and the `docs/` links work |

## 10. Missing items and decisions (updated 12 Oct)
**Decided:**
- New top-level `scripts/` folder approved.
- No new libraries. Page images are pre-rendered to PNG at ingest with stdlib `zlib` + `struct`. The QR card is generated once with an offline tool.
- `books.toml`, read with stdlib `tomllib`.
- 3 Android phones are available for the demo and the concurrency bench (1, 2 and 3 concurrent).
- Hotspot fallback: Ubuntu.
- Follow-up doc edits done:
  - DECISIONS lines
  - CLAUDE.md (§3, §4, §5, §7, §11)
  - `.env.example` (llama-server, no Ollama)
  - `docs/licenses/gemma` (Apache-2.0)
  - `LICENSE`
  - CLAUDE.md and its docs moved to the repo root

**Still open:**
- **Downloads:** the Qwen3-4B-2507 Q4_K_M and bge-m3 GGUFs. These are the only internet steps, and both happen before the demo.
- **Battery WMI readings:** check that they work on this laptop. If they don't, borrow a plug-in watt meter.
- **Admin actions (user):** the Windows Firewall rule and the hotspot test.
- **`docs/licenses/qwen`:** it holds the *Qwen RESEARCH LICENSE* (non-commercial, Qwen2.5-era). If Qwen3-4B-2507 wins the bake-off, replace it with that model's own licence after checking it on the model card at download time.
- **ANSWER_POLICY:** needs lines for the `[Sn]` citation flow and the Social Science answer shape.
- **ARCHITECTURE.md:** still describes `server/`, PyMuPDF and React. `SYSTEM_DESIGN.md` wins where they differ.
