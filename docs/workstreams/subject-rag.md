# Subject RAG — retrieval and answering set up per subject

**State on 20 Oct 2026:** prepared for discussion. Nothing built. Exam revision resumes after this ([exam-revision.md](exam-revision.md)).

Today the whole pipeline is built around one kind of book: Social Science prose, where a good answer explains facts in the student's own words and cites a page. Other subjects need different chunking, different answers and different checks. This document records what we know per subject and what must be decided before building.

## 1. Where each subject stands

| Subject | Books on the server | What works | Known problems (with defect ids) |
|---|---|---|---|
| Social Science (EN) | SS8 Pt1 EN | hit@3 66/71 on test; human-graded correct 0.90 (dev, all arms) | Chapter 6 "Reading Maps" retrieval misses; maps and figures are not read |
| Social Science (ML) | SS8 Pt1 ML (OCR) | hit@3 35/38 on test | Citation right only 27/38; OCR drops boxed sidebars (D15: pp 62, 65, 92, 115) and pp 23, 43 are unreadable |
| Science (EN) | Basic Science Pt1 EN (teacher upload) | hit@3 46/50 on test | Junk text layers kept as text (D12: pp 113, 124); subscripts split (H₂O → "H2⏎O") and table columns scrambled (D14); running-header removal is Social-Science-only |
| Maths | none indexed | — | Maths PDFs have an unusable text layer (research notes): needs OCR of the page (band OCR); SymPy approved but parked; no eval items |
| English (language subject) | none indexed | — | Not started |
| Malayalam (language subject) | none indexed | — | Not started; legacy-font PDFs → OCR (or font conversion, licence open) |

## 2. How the subjects differ (the "answering window" for each)

**Maths.** Students get stuck on a *step*, not a fact.
- Chunking must keep a worked example or an exercise whole (the CLAUDE.md §8 test).
- Answers are hint-first for exercises (ANSWER_POLICY §3): show the next step, not the result.
- Arithmetic is checked by SymPy, never trusted from a 2B model.
- **Prerequisite pinpointing (team idea, to discuss):** when a student cannot do a step, the cause is often an earlier concept, e.g. fractions behind a ratio problem. That needs a concept map (chapter → concepts → prerequisite concepts, possibly from earlier classes) and a way to tell which prerequisite is missing, for example one short check question per prerequisite.

**Science.** Mostly like Social Science, plus:
- tables kept as tables;
- formulas and units kept intact (H₂O, cm³);
- diagrams referred to by figure number and page;
- numeric questions checked like Maths.

**English (language subject).** Questions are about a text the student is reading: what a line or poem means, theme, character, word meaning, grammar.
- Unlike Social Science, quoting the exact lines is necessary, so answers quote briefly and explain.
- Explaining in simple English with Malayalam help may matter more here than anywhere.
- Retrieval should find the passage or poem first, then the lines.

**Malayalam (language subject).** The same as English but for Malayalam texts and grammar (വ്യാകരണം). It depends on OCR quality, or on legacy-font conversion, whose licence is undecided (research notes, Decision 4).

## 3. To decide (team)

1. **Which subject first**, given 7 days to the 27 Oct deadline. Maths needs OCR of the pages, step-wise answers, SymPy and a new eval set; English or Malayalam needs ingestion of new books and a new answer style; finishing Science (tables, D12, D14) is the smallest. Recommendation: finish Science and do one language subject or Maths after the submission, unless the demo needs it.
2. **Answer shape per subject**: one prompt family per subject (`prompts/system_v3_<subject>_<lang>.md`), chosen by the book's subject. That is a fixed rule, not model rerouting (rule 3 stays).
3. **Chunking rules per subject**: worked examples, exercises, tables and poems are never split.
4. **Maths prerequisite pinpointing**: scope, the source of the concept map (teacher-made or drafted then teacher-checked), and how the gap is detected.
5. **Book sources and licences** for Maths, English and Malayalam (SCERT licence still unconfirmed overall).

## 4. Evaluation needed per subject (before any claim)

| Subject | Eval set to build | Key metrics |
|---|---|---|
| Science (finish) | Table and formula questions added to `sci_en` (dev + test) | hit@3 on table items; table cell F1 on ~10 tables; citation right |
| Maths | Numeric and step items with known answers; hint-first items | final-answer accuracy checked by SymPy; "gave the next step, not the answer" rate; refusal for out-of-syllabus |
| English | Meaning / theme / word / grammar items per lesson, with gold passages | hit@3 on the passage; human-graded correctness and clarity |
| Malayalam | Same as English, in Malayalam; OCR loss tags as in `ss_ml` | as English; OCR loss share |
| All | Same split rules (30% dev, frozen test), same human grading (judges failed) | as in [evaluation-register.md](evaluation-register.md) |
