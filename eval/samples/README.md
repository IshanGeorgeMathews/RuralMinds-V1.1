# Sample data and test cases

These question sets are written by the RuralMinds team. They contain **no textbook text**: only our own questions, the printed page numbers where each answer is found, and whether the book should answer the question at all. They are drafts, and teachers are still reviewing them.

| File | Items | What it tests |
|---|---|---|
| `questions_dev_en_ml.jsonl` | 20 | The same 10 questions in English and Malayalam: right page found, cited answer, polite refusal for off-syllabus questions |
| `questions_manglish.jsonl` | 20 | 10 Manglish questions (Malayalam typed in English letters), searched against the Malayalam book and the English book |
| `questions_tutor_modes.jsonl` | 10 | Tutor requests: real-life example, story, "I didn't understand", quiz, Manglish, cross-language |
| `questions_refusal_check.jsonl` | 20 | Off-syllabus questions that must be refused, plus tutor questions that must still be answered |

Each line looks like this:

```json
{"id": "d02-en", "lang": "en", "medium": "en", "question": "Where is Bhimbetka and what was special about it?",
 "answerable": true, "gold_pages": [11], "key_facts": "Madhya Pradesh; rock shelters"}
```

- `lang` is the language the answer should be in.
- `medium` is the book searched.
- `gold_pages` are the printed pages of Kerala SCERT Social Science Std VIII Part 1.

To run a set through the real answer pipeline (the model servers must be running):

```powershell
uv run python -m eval.run --testset eval/samples/questions_dev_en_ml.jsonl --label my-run
```

Results are written to `eval/results/`, with every answer included so people can grade them. The unit tests are in `apps/api/tests/`; run them with `uv run pytest`.
