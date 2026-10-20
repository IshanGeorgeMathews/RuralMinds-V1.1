# Exam revision — status and queued backlog

**State on 20 Oct 2026:** steps 1–3 built and tested; the rest is **queued until retrieval is set up properly for each subject** (team decision, 20 Oct; see [subject-rag.md](subject-rag.md)). This document is the place to resume from.

## 1. The goal (as clarified by the team, 20 Oct)

Protect the school server on exam eve. The server will usually be a weaker PC than the demo laptop, and the demo laptop already tops out at about 3 AI answers per minute (bench, 19 Oct). Twenty students asking at once means minutes of queueing. So:

1. **Answer the expected questions once, ahead of time.** Teacher-checked answers to likely exam questions are stored until the exam date and served with no AI time.
2. **Catch repeats.** When a student types a question that matches an approved one, give the approved answer instead of a new AI answer. Students ask the same doubts repeatedly, especially the day before the exam, often about points in the chapter notes.
3. **Students can still ask their own questions** after reading the prepared answers; those go to the AI queue.
4. **The admin can protect the server:** limit how many AI questions can be asked over a period, or move everyone to the queue / prepared answers when load is high.
5. **Prepared questions double as notes:** students can read them per chapter until the exam, like a question-and-answer revision sheet.

## 2. What is built (W5 part 2, steps 1–3)

| Piece | What it does | Where |
|---|---|---|
| Question bank (schema v4) | Questions per (book, chapter), shared by every class using the book, kept across exams; states pending → draft → approved / rejected / not in book / failed | `schema.sql`, `exams.py` |
| Exam portions | Title, book, chapters, classes, show-from date, exam date, suggested questions per chapter (default 6, 0–20). Refuses a class that does not use the book (e.g. Malayalam medium) | `exams.py`, teacher tab "Exam revision" |
| Teacher's own questions | Answered through the normal pipeline and queue; or the teacher writes the answer herself (labelled "Teacher's answer", no page — exception to rule 2, DECISIONS 20 Oct) | `exams.py`, `api_teacher.py` |
| Review beside the page | Approve, edit the wording (pages kept), reject, withdraw; "not in the book" shown as such, with "write the answer" | `ExamRevision.svelte`, `RevisionAnswer.svelte` |
| Idle-time drafting worker | Drafts suggested questions from chapter notes and answers them when no student needs the model (queue empty, slots idle, no question for 45 s, not paused); teacher's own questions first, then soonest exam; unanswerable suggestions set aside; tries capped at 3× | `revision_worker.py`, prompt `exam_questions_v1` |
| Student chips | "Exam revision · N days left" on the start screen; attempt-first ("think first", then "Show answer"); served by question id; hidden the day after the exam or if the book is replaced | `RevisionChips.svelte`, `api_student.py` |
| Typed repeats (exact only) | Approved cited answers are also written to the exact-match cache, so the *same* typed question (case, spaces and final "?" ignored) is answered with no model call | `cache.py` |

Tests: `apps/api/tests/test_exams.py` (scenario: 8A + 8B on one book, 8C Malayalam, 9A Class 9), `test_api.py` (end to end), `test_ingestion.py` (v3 → v4 upgrade).

## 3. What was measured (all on a copy of the database, Gemma 4 E2B, laptop on battery)

| Check | Result | Status |
|---|---|---|
| Teacher question answered through the queue | 18 s, cited pp 11–12 | single run |
| Off-book teacher question | "not in the book", no invented answer | single run |
| Student chip tap | 3 ms, no model call | single run |
| Same question typed by a student | served from the cache, one event, no model call | single run |
| Drafting worker, no student load | 30 suggested questions (SS 2 ch × 6, Science 3 ch × 6) answered in ~12 min, all 30 cite a page, 0 set aside | single run, quality not graded |
| Exam-eve capacity (before/after) | **not measured** — see backlog B5 | queued |

## 4. Known problems

- **Unreproduced HTTP 500** reported by the team while reviewing and cancelling (20 Oct, team's own server on port 8000). Replayed every exam endpoint on a consistent copy of the live data: all succeeded. Needs the traceback from that server's terminal.
- A teacher question filed under the wrong chapter comes back "not in the book" (answers search only the chosen chapter). Seen live: "What is force" under chapter 1; it is in chapter 10.
- The drafted questions' answers have not been graded for quality (only "cites a page" was checked).

## 5. Queued backlog (resume after subject RAG)

Each item lists the decision it needs, because two of them touch CLAUDE.md rules.

**B1. Match typed questions to approved ones ("similar question").**
Today only an *exact* repeat is caught. The goal is that "why did harappan cities decline" and "reasons for the decline of Harappan cities" both get the approved answer.
- *Conflict:* CLAUDE.md §10 and DECISIONS 11 Oct forbid semantic cache matching in the demo, because a similar-looking question can have a different answer ("causes of WW1" vs "results of WW1") and a cache would serve it confidently.
- *Proposed safe version:* **suggest, don't substitute.** Before queueing a typed question, show up to 3 approved questions from the same book and chapter that are close to it ("Is your question one of these? — answers ready now"). The student taps one (no AI) or sends their own (queue). The student confirms the match, so a wrong match costs one glance, not a wrong answer.
- *Needs:* a decision line amending the §10 rule; a measured false-suggestion rate on a paraphrase set (e.g. 50 paraphrase pairs + 50 near-miss pairs from the bank) before switching it on; the similarity threshold calibrated on dev.

**B2. Admin limits to protect a weak server.**
- (a) **Per-class question budget** over a period, e.g. 120 AI questions per class per day. Aggregate counts only; fits rule 4.
- (b) **Per-phone rate** within a session, e.g. 1 in flight (built) plus N per hour, kept in memory and forgotten at sign-out.
- (c) **High-load mode:** when the predicted wait passes a set limit, a new question first shows the prepared answers and notes for that chapter, then "join the queue (about N min)". Today the server turns questions away above 180 s (W5 part 1).
- (d) **Per-student quota** ("each student 10 questions a day") — *conflicts with rule 4* if counted per account (a per-child usage record). Needs an explicit team decision; recommendation is (a) + (b) + (c) instead.

**B3. Revision notes view.** Approved questions and answers per chapter shown as a readable sheet ("Questions to revise"), available from the show-from date until the exam date. No model call. Printable later (with the notes print view).

**B4. Doubts from the chapter notes.** Students' doubts cluster on points in the notes. Draft questions *per key point* (the worker already drafts from the notes), show them under each point as "common doubts", and attach a "my doubt is about this point" ask button that pre-fills the chapter and point.

**B5. Exam-eve bench (capacity before/after).** A bench mix where about half the requests are chip taps or exact repeats, compared with the 19 Oct battery baseline (2.6–3.1 answers/min; 4 questions/min arrivals → 7/24 within 15 s). Report goodput over admitted requests and shed requests separately. Run on the target weak hardware too when available.

**B6. Wrong-chapter teacher questions.** When the chosen chapter refuses, search the whole book and tell the teacher "this is answered in chapter N — move it there?".

**B7. Grade the drafted questions.** Human-grade a sample of drafted question–answer pairs (usefulness of the question, correctness of the answer) before claiming anything about them.

**B8. Find the 500** (needs the traceback).

## 6. What to report when it is done

Exam-eve goodput and answers per minute before/after (B5); share of exam-eve requests answered with no AI time; teacher minutes to review a 4-chapter exam (time it once with a real teacher); false-suggestion rate for B1 if built.
