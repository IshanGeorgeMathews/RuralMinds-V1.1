# Review: the "Not answered" inbox and teacher answering

**Short version:** the team is right. As built, "teacher answers the student's question" is not realistic. Nobody receives the teacher's answer, and the teacher often cannot tell what was asked. The inbox is still valuable as a **signal of what the app and the book cannot answer**. Its actions should feed things the whole class sees (revision questions, notes, a class discussion), not one-to-one replies.

## What happens today

1. A student's question is refused. The server stores one inbox row per question per class and book: the question text, language, chapter, refusal reason and a repeat count. It stores **no student, no device and no conversation** (rule 4, DECISIONS 13 Oct).
2. The teacher sees the list and can press **Answer**. That opens "Try the AI" with the question. If the answer is good, she approves it into the exact-match cache.
3. The approved answer helps only when someone types **the same words again**.

## Why it does not work as "teacher answering"

| Problem | Cause | Can it be fixed without breaking a rule? |
|---|---|---|
| The student who asked never sees the teacher's answer | No per-student storage or notifications, deliberately | No: per-student replies need a per-child record (rule 4, DPDP s.9(3)) |
| The teacher cannot understand many rows | Conversation history lives only on the phone, so a follow-up like "why?" or "explain simpler" reaches the inbox without its topic | Partly: store the *search topic* the server worked out (it already rewrites follow-ups into a topic) instead of the raw words |
| Approving only helps exact repeats | The cache is exact-match only (DECISIONS 11 Oct) | Partly: see exam revision backlog B1 ("suggest, don't substitute") |
| Teachers have little time | Answering many single questions one by one is the most expensive way to help | Yes: group them and act once for the whole class |
| Many rows are not "unanswerable" at all | Wrong chapter selected, a Malayalam OCR page lost (D15), or a retrieval miss | Yes: label them so the right person (teacher, admin) acts |

## What the inbox is good for

- **Gaps report:** what students wanted that the book, as indexed, could not answer, by chapter and by reason, with counts. This is useful to the teacher (what to cover in class) and to us (real questions for the eval, kept private; retrieval misses and OCR losses to fix).
- **Input to exam revision:** a question asked repeatedly before an exam is exactly what the revision bank is for. One action puts it in front of the whole class.

## Recommendation (not built; for discussion)

1. **Reposition the tab** as "Questions the app couldn't answer", grouped by chapter, most repeated first, with the reason in plain words.
2. **Replace "Answer" with class-level actions:**
   - **Add to revision questions:** goes into the question bank for that book and chapter. It is answered by the pipeline or by the teacher, and reaches every student of every class using the book as a chip or revision note.
   - **Answered in class:** the teacher covered it in person; dismiss.
   - **Not in syllabus:** dismiss, and count it for the gaps report.
   - **Book problem:** sends the row to the admin (wrong chapter title, missing page, unreadable OCR).
3. **Store the topic, not the fragment.** For a follow-up, store the search topic the server derived, so "why?" becomes "why did Harappan cities decline".
4. **Count, don't track.** Totals per class and chapter only; nothing per student.
5. **Do not build** per-student replies or notifications.

## How to measure it

- Share of inbox rows that are retrieval misses or data problems vs truly off-book (sample about 50 rows by hand).
- Teacher minutes per week spent on the inbox (ask in the teacher session).
- Number of inbox questions that become revision questions, and how often those chips are opened (class-level counts).
