# RuralMinds — Goal and Scope

Every number in this file is either measured by `eval/` (file named) or cited. Anything not yet built is marked *(planned)*.

## The problem in one paragraph
A student studying a state textbook gets stuck on a point and has nobody to ask at that moment, and mobile data may be unreliable or costly. General chatbots answer anything, without saying where in the book the answer comes from, and an answer-giving chatbot can hurt learning: students who practised with plain GPT-4 scored 17% lower on a later exam without AI, while a guard-railed tutor only matched the control group ([Bastani et al., PNAS 2025](https://knowledge.wharton.upenn.edu/article/without-guardrails-generative-ai-can-harm-education)). RuralMinds answers only from the school's textbook, cites the chapter and printed page, and says so when the book doesn't cover a question.

> **Pitch line:** "An open-source, offline, page-cited tutor that refuses off-book questions and lets teachers approve answers. It runs on a box in the room and needs no internet or mobile data."

## What RuralMinds is
A local server (the demo runs on one laptop) in a school or study point. It:
1. Holds textbooks a teacher has uploaded and published, with a local search index.
2. Runs one small LLM locally, loaded once (Gemma 4 E2B in the current build; no cloud).
3. Serves a mobile web app over local Wi-Fi that needs **no internet and no mobile data**.
4. Answers student questions grounded in the textbook, with chapter + printed-page citations, an everyday example and a check question; refuses when the book doesn't cover it.
5. Serves teacher-approved answers instantly from an exact-match cache.

## Who uses it
| User | What they do | What they must never be able to do |
|---|---|---|
| **Student** (Class 8, shared phone) | Pick a book and chapter, ask a question, follow up, ask for a simpler version, an example, a story, a quiz or chapter notes | See other students' data, change content, administer the server |
| **Teacher** | Upload and publish books, approve answers into the cache, see the "couldn't answer" list for their class | See per-child surveillance data (aggregate only) |
| **Admin** | Create classes and accounts, pause the model, limit languages per class, see aggregate stats | — |

Sign-in for students: a username and password issued by the teacher or admin, linked to a class only. **No phone, email, Aadhaar or APAAR, ever.**

## How it is used
- Primary mode: a scheduled, supervised **"RuralMinds hour"** at school or a study point. Supervised, scheduled AI tutoring has shown gains in maths: Mindspark 0.37 SD ([Muralidharan et al., AER](https://econ.ucsd.edu/~kamurali/papers/Published%20Articles/Disrupting_education_AER.pdf)) and Rori 0.36 SD at one hour a week ([Stanford SCALE](https://scale.stanford.edu/publications/effective-and-scalable-math-support-experimental-evidence-impact-ai-math-tutor-ghana)). Those studies tested maths, so we do not claim their effect sizes for RuralMinds.
- *(planned)* Chapter packs downloaded to phones and an ask-later outbox.
- *(planned)* Hint-first answers for exercise questions (see `ANSWER_POLICY.md`).

## Current scope (hackathon build)
- Books: Kerala SCERT Class 8 Social Science Part 1 (English and Malayalam) and Basic Science Part 1 (English).
- Languages: English and Malayalam, plus Malayalam typed in English letters (Manglish). Malayalam quality is reported from its own eval slice.
- *(planned)* Maths, once the maths PDFs can be read reliably.

## Non-goals (say no to these)
- Not a replacement for teachers or classroom teaching.
- Not a general chatbot — it answers from the school's books, not the whole internet.
- Not a cloud app with an offline mode bolted on.
- Not a school ERP: no attendance/timetable module (only an aggregate usage log).
- No IVR/dial-up, no runtime model switching, no in-browser load simulator, no open forum in the first build.
- Not "the first offline AI tutor" — that claim is false. Our novelty is: page-cited grounding, honest refusals, a teacher-approved answer cache, the Kerala SCERT + Malayalam path, and measured numbers.

## What success looks like
**For the hackathon (measured, not claimed; results in `eval/results/` and `docs/DECISIONS.md`):**
- Works with internet physically disconnected; phone in airplane mode + Wi-Fi.
- Retrieval hit@3, answer correctness (human-graded), refusal recall and false refusals on a frozen test split, each with a 95% interval.
- p50/p95 first-word and total time on the actual hardware.
- Answers per minute and first-word time at 1/2/4/8 concurrent phones; cached vs live time; watts drawn on battery.
- Recovers after power is pulled, index intact.

**For a pilot** *(planned)*: an independent test without AI access over 6–10 weeks with a waitlist control; uptime; teacher minutes spent.

## Where it could go
RuralMinds needs electricity and a Wi-Fi network, not the internet. It is Apache-2.0 and built on Linux-ready components, so it could serve schools with poor connectivity or sit alongside existing state platforms. Running on specific school hardware (for example KITE laptops) is a target, not yet measured.
