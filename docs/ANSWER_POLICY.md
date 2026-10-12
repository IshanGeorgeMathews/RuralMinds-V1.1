# RuralMinds — Answer Policy

This is the contract for how RuralMinds answers. Prompts, code and tests must follow it. Changes here need a line in `DECISIONS.md`.

## 1. Every answer must
1. Be grounded only in the retrieved textbook chunks.
2. Cite at least one source as `[Ch <n>, p <page>]`, and every cited page must exist in the retrieved chunks.
3. Carry a label: `AI explanation — from your textbook, may contain mistakes` or `Teacher-approved`.
4. Stay short: about 300 tokens max, plain language suited to Grade 8–10, one idea per sentence.
5. Use the student's chosen language (English by default; Malayalam only once benchmarked).

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

## 5. Maths safety
- The model returns `expression` and `final_number` in JSON when there is arithmetic.
- SymPy evaluates `expression`; if it doesn't equal `final_number`, replace the final number with the SymPy result and flag `math_corrected: true`, or fall back to showing steps without the final number.

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
