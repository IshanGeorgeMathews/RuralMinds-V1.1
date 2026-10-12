# RuralMinds — Architecture

## 1. Big picture
```
 Student phone (browser / PWA)          Teacher phone or PC
        │  Wi-Fi only, no internet             │
        ▼                                      ▼
 ┌──────────────────────── Travel router / AP (no WAN) ────────────────────────┐
 │  DHCP + DNS via dnsmasq on server: ruralminds.lan → server IP               │
 │  connectivitycheck / generate_204 → server returns HTTP 204                 │
 └─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
 ┌──────────────────────────── RuralMinds server ──────────────────────────────┐
 │  FastAPI :8000  ── serves built PWA + JSON API                              │
 │     ├─ cache.py      exact-match teacher-approved answers                   │
 │     ├─ retrieve.py   FTS5 (BM25) + sqlite-vec → RRF → top-k chunks          │
 │     ├─ answer.py     prompt build → llama-server → JSON validate → SymPy    │
 │     └─ ingest.py     background job: PDF → pages → chunks → embeddings      │
 │                                                                              │
 │  llama-server :8080  Qwen3-4B-Instruct-2507 Q4_K_M  (chat, 2 parallel slots) │
 │  llama-server :8081  bge-m3 GGUF  (--embedding)                              │
 │  SQLite  data/ruralminds.db  (WAL)   +  data/files/ (original PDFs)          │
 └──────────────────────────────────────────────────────────────────────────────┘
        │  UPS / LiFePO4 battery / optional solar
```
Internet is optional and only for deliberate maintenance (updates, new content). It is never in the answer path.

## 2. Ingestion pipeline (`ingest.py`)
1. **Classify the PDF:** Unicode text / legacy-font text / scanned. Legacy fonts and scans go to OCR (Tesseract `mal+eng` / `hin+eng`) as a background job; a teacher spot-checks a sample page.
2. **Extract per page** with PyMuPDF, keeping page numbers and headings (font size/weight heuristics + the book's table of contents).
3. **Chunk by heading**, ~250–400 tokens. **Never split** a worked example, an exercise question, or a theorem/definition box across chunks. Each chunk keeps: `doc_id, chapter_no, chapter_title, section, page_start, page_end, kind (text|example|exercise|definition)`.
4. **Embed** each chunk via the embedding server; store vector in `sqlite-vec`, text in FTS5.
5. **Hash** the source file (SHA-256). If a document is re-uploaded with a new hash, mark every cached answer from the old version `needs_review`.
6. New documents are **unpublished** until a teacher publishes them.

## 3. Question flow (`answer.py`)
```
question + {grade, subject, chapter?, language, mode, history}
   │
   ├─1─ normalise (lowercase, trim, collapse spaces, strip punctuation)
   ├─2─ cache lookup: key = hash(normalised_q, language, grade, subject, chapter, doc_hash)
   │       hit (approved) → return "Teacher-approved" answer instantly
   ├─3─ retrieve: filter by grade/subject/published chapters → FTS5 top-20 + vector top-20
   │       → reciprocal-rank fusion → top-3/4 chunks (≤ ~600 tokens total)
   ├─4─ confidence gate: if best fused score < REFUSAL_THRESHOLD → polite refusal + suggest chapter
   ├─5─ prompt: fixed system prompt FIRST (prefix-cached) + chunks with [ch, p] labels
   │       + last 2–3 turns of history + question
   ├─6─ llama-server /v1/chat/completions: temperature 0.2, max_tokens 300,
   │       response_format = answer.schema.json, stream = true
   ├─7─ validate: JSON schema ok? every citation maps to a retrieved chunk? 
   │       SymPy re-checks `expression` == `final_number`? If not → fallback text / retry once
   └─8─ label "AI explanation" + citations → stream to phone; log aggregate metrics only
```
Follow-ups ("why did we divide by 2?") reuse the previous turn's chunks plus a fresh retrieval.

## 4. Concurrency & performance rules
- One model pinned in RAM; `llama-server -np 2` (parallel slots) with continuous batching. Tune slot count by measurement.
- The API keeps a small async queue; the phone shows "You are #3 in line" instead of timing out.
- Prompt-processing (prefill) is the main CPU cost → keep retrieved context small, keep the system prompt identical and first so llama-server reuses it (`--cache-reuse`), stream tokens.
- KV cache quantised `-ctk q8_0 -ctv q8_0` to halve memory.

## 5. Data model (summary — `db/schema.sql` is the source of truth)
- `documents`, `chunks`, `chunks_fts` (FTS5), `chunk_vectors` (sqlite-vec)
- `groups` (section / multigrade / level / remedial — not forced to follow grade), `group_members`, `assignments` (unlock chapter ranges per group)
- `users` (role: student|teacher|admin; students have display name + picture-PIN hash only)
- `answer_cache` (status: draft|approved|needs_review|rejected; source doc hash)
- `unanswered` (refusals/low-confidence questions → teacher queue, no student id)
- `usage_daily` (aggregate counts only)

## 6. Offline networking (demo)
- Travel router with **no internet cable**; server has a static IP.
- `dnsmasq` on the server: resolves `ruralminds.lan` and the Android/iOS connectivity-check hosts to the server; FastAPI answers `/generate_204` with 204 so Android keeps Wi-Fi connected.
- Students reach `http://ruralminds.lan:8000` or the IP via a printed QR card ("tap *Stay connected*, turn mobile data off").
- See `network/dnsmasq.conf`.

## 7. Resilience
- SQLite in WAL mode; graceful shutdown on UPS low-battery signal; systemd units with `Restart=always`.
- Nightly backup to a second disk; one-button USB backup of DB + uploads (not models).
- Degraded mode: if llama-server is down, still serve cached answers and chapter packs.
- `/health` page: disk, RAM, temperature, model status, today's latency, queue length, last backup, last unclean shutdown.

## 8. Hardware tiers (capacity figures are UNVERIFIED until benchmarked)
| Tier | Hardware | Model |
|---|---|---|
| A. Demo | Team laptop, 16 GB | Qwen3-4B-2507 Q4 |
| B. School node | Intel N100/N150 mini-PC, 16 GB, NVMe | Qwen3-1.7B (speed) or 4B (quality) |
| C. Larger school | Used i5 + RTX 3060 12 GB or Ryzen 8845HS 64 GB | Qwen3-8B / MoE |
