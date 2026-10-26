# RuralMinds — Answer Policy

This is the contract for how RuralMinds answers. Prompts, code and tests must follow it. Changes here need a line in `DECISIONS.md`.

## 1. Every answer must
1. Be grounded only in the retrieved textbook chunks.
2. Cite at least one source as `[Ch <n>, p <page>]`, and every cited page must exist in the retrieved chunks.
3. Carry a label: `AI explanation — from your textbook, may contain mistakes` or `Teacher-approved`.
4. Stay short: about 300 tokens max, plain language suited to Grade 8–10, one idea per sentence.
5. Use the student's chosen language (English by default; Malayalam only once benchmarked).

## 1a. Tutor, not a text retriever (13 Oct)
Students use RuralMinds to *understand*, so answers explain in the model's own simple words and must not copy book sentences. Facts about the topic still come only from the retrieved sources, each with a source marker. **One labelled exception:** an everyday example, comparison or story frame may come from outside the book, shown in its own box marked "Example to help you understand — not from your book"; it may not state facts about the topic and never carries a citation. Modes: explain (default), simpler, example, story, quiz (answers hidden until tapped), summary (served from chapter study notes). Prompt: `prompts/system_v2_tutor_{en,ml}.md`.

## 1c. Exam revision answers (20 Oct)
Revision chips show a teacher's chosen questions for a class's exam. Each answer is one of: the pipeline's cited answer, approved as is (`Teacher-approved`); the same answer reworded by the teacher, with its textbook pages kept (`Teacher-approved`); or **the teacher's own answer, which has no page citation and is labelled `Teacher's answer`** — the one exception to "every answer cites chapter and page" (DECISIONS 2026-10-20). Students see the question first and open the answer after trying (attempt-first). Teacher-written answers are served only as revision chips, never to a typed question, where students expect page citations.

## 1b. Languages (13 Oct)
- The **UI language** is a Settings choice and never changes answers.
- The **answer language** is the student's "Answer in" setting: Auto (default: the question's language; Manglish → Malayalam), English or Malayalam.
- The **search language** is always the book's language: a question in another language or in Manglish is rewritten into the book's language before searching (`prompts/rewrite_v1.md`).

## 2. Answer shape (explain mode)
1. **Concept** — 2–4 sentences in simple words.
2. **Worked example** — taken from the textbook where possible, with numbered steps.
3. **Check yourself** — one similar practice question (no answer shown until asked).
4. **Source** — citations.

## 3. Hint-first mode (homework / exercise questions)
Triggered when the question matches a textbook exercise, or the student picks "Help me solve".
- Turn 1: identify the concept + first hint only. Ask the student to try.
- Turn 2: next hint, or check the student's attempt and point to the first wrong step.
- Turn 3 (or after 2 hint requests, or after a real attempt): full worked solution.
- **Never refuse outright** to show the solution. Pure withholding drives weak students away; pure answer-giving harms learning. This is the middle path.

## 4. Refusal (out of syllabus / low confidence)
When the best retrieval score is below `REFUSAL_THRESHOLD`, or no retrieved chunk supports the answer:
> "I couldn't find this in your <subject> textbook for Class <n>. Try choosing a different chapter, or ask your teacher. I've saved this question for your teacher."
- Log the question (no student id) to the `unanswered` table → teacher dashboard.
- Never answer from general model knowledge as if it were the textbook.
- **Time-sensitive questions are refused** ("Who is the current President / Chief Minister / Prime Minister?", "this year's…"): office holders and current figures change, and the book only records what was true when it was printed. Refuse even when the book asks the same question as an activity, and even when the model "knows" an answer (18 Oct).

## 5. Maths safety
**As built: the "Solve step by step" chip** (Science numericals, English; DECISIONS 2026-10-20 and 2026-10-21). This replaces the original plan below.
- The model writes the problem as equations in JSON: knowns with the question's own units, unknowns, and relations. It never writes conversion numbers. SymPy solves the equations and converts the units.
- After the explanation, the same model solves the problem again on its own, ending with a FINAL line. "✓ Checked by the calculator" is shown only when every value the calculator shows also appears in that FINAL line (`agreement.py`).
- When the problem cannot be set up or solved, or the two answers disagree, **no answer is shown**. The phone shows a fixed message, the pages that may help, and "Show the method anyway".
- The method fallback is written without the calculator. It is labelled "written by AI without the calculator, may be wrong".
- A Malayalam answer language gets the fixed message: step-by-step solving is English only until a Malayalam slice passes.

*Original plan (not built):* the model returns `expression` and `final_number` in JSON; SymPy evaluates `expression`, and if it doesn't equal `final_number`, the final number is replaced with the SymPy result and flagged `math_corrected: true`.

## 6. Prerequisite fallback (later phase)
If a student fails the same step twice, retrieve the prerequisite concept from a lower grade's book and explain that first.

## 7. Follow-ups
Keep the last 2–3 turns. A follow-up like "why did we divide by 2?" refers to the previous answer's steps; re-use its chunks and add fresh retrieval.

## 8. Things the model must never do
- Invent page numbers, chapter titles, exam rules or marks schemes.
- Give medical, personal or non-academic advice beyond a gentle redirect.
- Ask the student for personal details.
- Use chain-of-thought "thinking" text in the output (it hurts faithfulness and wastes tokens).

## 9. Output JSON (see `server/app/schemas/answer.schema.json`)
```json
{
  "status": "answered | refused",
  "mode": "explain | hint | solution",
  "answer_markdown": "…",
  "steps": ["…"],
  "practice_question": "…",
  "expression": "2*x + 3 - 7",
  "final_number": "2",
  "citations": [{"chapter": 4, "page": 73}],
  "language": "en"
}
```
