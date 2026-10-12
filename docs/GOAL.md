# RuralMinds — Goal and Scope

## The problem in one paragraph
A rural student studies alone after school, gets stuck on a maths or science step, and has nobody to ask: no tutor (about three-quarters of rural students take no paid tuition), no parent who knows the subject, and unreliable or costly mobile data. DIKSHA and SAMAGRA already put the *textbook* online and offline. Nothing gives the *explanation* offline. RuralMinds fills that gap.

> **Pitch line:** "DIKSHA gave rural students the textbook offline. RuralMinds gives them the explanation offline."

## What RuralMinds is
A low-cost local server (target: ₹25–40k mini-PC, solar/battery capable) in a school or village study point. It:
1. Holds teacher-approved textbooks (NCERT/SCERT PDFs) and a local search index.
2. Runs one small pinned LLM locally (no cloud).
3. Serves a mobile web app over local Wi-Fi that needs **no internet and no mobile data**.
4. Answers student questions grounded in the textbook, with chapter + page citations, worked examples and a practice question; refuses when the book doesn't cover it.
5. Serves teacher-approved answers instantly from a cache (exam-season load).

## Who uses it
| User | What they do | What they must never be able to do |
|---|---|---|
| **Student** (Grades 8–10, shared phone) | Pick class/subject/chapter, ask a question, follow up, try a practice question, download chapter packs | See other students' data, change content, administer the server |
| **Teacher** | Upload/publish content, approve or fix cached answers, see the "couldn't answer" list, run supervised sessions | See per-child surveillance data (aggregate only) |
| **Admin / tech buddy** (teacher + trained senior students) | Setup wizard, health page, backup to USB, restore | — |

Sign-in for students: class code + name from list + picture PIN, or guest mode (nothing saved). **No phone, email, Aadhaar or APAAR, ever.**

## How it is used (evidence-driven)
Research shows supervised, scheduled AI/adaptive tutoring raised scores 0.2–0.4 SD, while unsupervised home use gave near zero and an answer-giving chatbot *lowered* exam scores 17%. So:
- Primary mode: a scheduled, supervised **"RuralMinds hour"** at school or a village study point.
- Secondary: **chapter packs** downloaded to phones + an **ask-later outbox** that syncs when the phone is back on the school Wi-Fi.
- Answers are **hint-first** for homework-style questions (see `ANSWER_POLICY.md`).

## Initial scope (hackathon build)
- Subjects: Maths and Science.
- Grades: 8–10 (index lower grades later for prerequisite fallback).
- Content: NCERT Class 9–10 + one Kerala SCERT chapter.
- Languages: English first. Malayalam only after it passes our benchmark. Hindi later.

## Non-goals (say no to these)
- Not a replacement for teachers or classroom teaching.
- Not a general chatbot — it answers from the school's books, not the whole internet.
- Not a cloud app with an offline mode bolted on.
- Not a school ERP: no attendance/timetable module (only a session schedule + aggregate usage log).
- No IVR/dial-up, no runtime model switching, no in-browser load simulator, no open forum in the first build.
- Not "the first offline AI tutor" — that claim is false. Our novelty is: page-cited grounding, honest refusals, teacher-approved exam cache, Kerala/SCERT + Malayalam path, and a costed operating model (power, maintenance, privacy).

## What success looks like
**For the hackathon (must be measured, not claimed):**
- Works with internet physically disconnected; phone in airplane mode + Wi-Fi.
- Retrieval recall@3, answer accuracy, refusal accuracy on our test set.
- p50/p95 time-to-first-token and total latency on the actual hardware.
- Concurrent phones served; cached vs live latency; watts drawn.
- Recovers after power is pulled, index intact.

**For a pilot:** independent test without AI access, 6–10 weeks, waitlist control; uptime; cost per student per month; teacher minutes spent.

## Where it scales
Built and proven in Kerala (Wayanad pilot). The real need is in states where 19–58% of schools have internet — Jharkhand, West Bengal, Meghalaya. "We built it in Kerala, where 92% of schools are online; we deploy it where 19–58% are. RuralMinds needs electricity and a Wi-Fi router, not the internet."
