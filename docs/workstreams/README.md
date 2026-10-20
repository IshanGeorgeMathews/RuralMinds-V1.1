# Workstreams — status, evaluations and what comes next

One document per topic, so each can be read and updated on its own. `docs/DECISIONS.md` stays the dated log of *decisions*; these documents hold the *current state* of each area and its queued work. When a queued item is built or measured, update its document and add the decision line to DECISIONS.

| Document | What it holds | State (20 Oct 2026) |
|---|---|---|
| [evaluation-register.md](evaluation-register.md) | Every evaluation done so far (method, file, result, whether it is valid) and every evaluation still to do — all areas except exam revision | Living register |
| [exam-revision.md](exam-revision.md) | Exam revision module: what is built and measured, the clarified goal (protect a weak school server on exam eve), and the queued backlog | Steps 1–3 built; rest **queued until subject RAG is set up** |
| [teacher-inbox-review.md](teacher-inbox-review.md) | Review of the "Not answered" inbox and teacher answering: why it is not realistic as built, and what to do instead | Recommendation, not built |
| [subject-rag.md](subject-rag.md) | The next phase: retrieval and answering set up properly per subject (Maths, Science, English, Malayalam) | Prepared for discussion; nothing built |
| [maths-and-numericals.md](maths-and-numericals.md) | Maths, Physics and Chemistry problems: OCR findings, solve-then-explain with SymPy, problem tiers, answer card, libraries researched, bench plan | Option A chosen 20 Oct (Science numericals chip before 27 Oct); nothing built |

Rules that apply to every workstream (from CLAUDE.md and DECISIONS):
- Numbers come only from `eval/` or the bench, with the result file named; small samples carry their 95% interval and are called indicative.
- Tuning happens on the dev split only; the frozen test split is read once for the baseline (done 19 Oct) and once at the end.
- Measured runs restart the chat server first and run on a machine with nothing else open (19 Oct: other apps halved generation speed).
