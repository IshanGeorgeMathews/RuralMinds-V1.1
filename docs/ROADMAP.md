# RuralMinds — Roadmap

Rule: finish the current phase's "done when" before starting the next. The deadline wins over features.

## Phase 0 — Hackathon MVP (now → Thu 15 Oct 2026)
**Done when:** a phone in airplane mode (Wi-Fi on) gets a cited answer and a refusal, with eval numbers recorded.

| Day | Build | Admin (team) |
|---|---|---|
| Sun 11 | `llama-server` running Qwen3-4B-2507; ingest 1 NCERT Class 10 maths chapter; first end-to-end answer | Register on MY Bharat; public repo (Apache-2.0); start Annexure 1 |
| **Mon 12** | Heading-based chunking with pages; class/subject filter; grounded prompt with `[ch, p]`; refusal threshold; JSON output; exact-match cache keyed to doc hash; offline router + dnsmasq `generate_204` | Draft problem statement + slides 1–5; **save complete v1 on portal** |
| Tue 13 | 100–150-item test set; measure recall@3, accuracy, refusal accuracy, p50/p95 latency, 3–4 phone concurrency, watts; README, architecture doc, tests, setup script; record 3–5 min uncut airplane-mode demo | |
| Wed 14 | Bug fixes only; final slides with measured numbers only; cost sheet + risk register in repo | **Upload final version** |
| Thu 15 | **No new features.** Re-check files, repo public, video plays | Deadline |

### MVP checklist
- [ ] `db/schema.sql` applied
- [ ] `ingest.py`: PDF → page text → heading chunks → embeddings → SQLite
- [ ] `retrieve.py`: FTS5 + vector + RRF + filters
- [ ] `answer.py`: cache → retrieve → gate → prompt → llama → validate → label
- [ ] `mathcheck.py`: SymPy check
- [ ] API: `POST /api/ask` (streaming), `GET /api/subjects`, `GET /generate_204`, `GET /health`
- [ ] Teacher: upload + publish (can be a simple form for MVP)
- [ ] Student UI: pick class/subject/chapter → ask → answer card with citation + label → follow-up
- [ ] Offline Wi-Fi tested on 2–3 Android phones incl. a cheap one
- [ ] `eval/run.py` + results committed
- [ ] `scripts/bench.sh` numbers committed

## Phase 1 — Before the state jury demo (16 Oct → as early as possible; jury can be 16 Oct–30 Nov)
- Teacher approval screen (shows source passage, one-tap "wrong")
- Overnight pre-generation of answers for every textbook exercise → approval queue
- Hint-first mode
- Chapter packs (PDF + approved answers + quiz) downloadable to phone + ask-later outbox
- Malayalam benchmark (20–30+ items); claim only if it passes
- Measurements on a real ₹25–40k N150 node; UPS pull-the-plug recovery test
- Health page, USB backup/restore
- Signed school letter; if possible a 1-week trial with 10–20 students on one chapter

## Phase 2 — Pilot (Wayanad)
- Setup wizard (6 questions, forced password change, printed recovery code)
- Groups not tied to grade, assignments unlock chapter ranges
- Class-code + picture-PIN sign-in, guest mode
- Aggregate teacher dashboard: top questions by chapter, "couldn't answer" list
- Prerequisite fallback (index lower grades)
- DPDP: privacy notice, retention schedule, processor agreement, breach runbook
- Pilot: 6–10 weeks, Grades 8–10 maths, supervised 2× 45 min/week, waitlist control

## Later (only with evidence)
- Structured, moderated forum (no DMs, no images, pre-moderated first posts)
- Semantic cache (≥ 0.85 threshold, first-turn only, after measured precision)
- Village study points (CPE links + solar), Hindi/Bengali packs for national scale
- Voice input (Malayalam ASR WER currently too high)

## Cut (don't build)
IVR/dial-up · runtime model rerouting · attendance/timetable ERP · in-browser load simulator (replace with queue model + real load test) · on-phone LLM as baseline
