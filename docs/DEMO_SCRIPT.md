# Demo Script (3–5 min, recorded uncut)

Goal: make the absence of internet *visible*, then prove trust with citations, refusal and numbers.

1. **Prove offline (30 s)** — Show the laptop's hotspot with its own internet switched off (`ping 8.8.8.8` fails). Phone: airplane mode on, Wi-Fi on, connected to `RuralMinds`. Try opening a public website → fails.
2. **Open the app (15 s)** — Scan the QR card → `http://<hotspot-IP>:8000`. Sign in as the demo student (`python -m ruralminds.admin demo` prints the accounts; sign in just before recording, students are signed out after 30 min idle). The class's book opens directly; tap a chapter chip.
3. **Cited answer (45 s)** — Ask a real Kerala SCERT Class 8 question. Show the answer with `[Ch, p]`. Tap the citation to open that page beside it.
4. **Follow-up (20 s)** — "Explain that more simply" → continues from the previous answer.
5. **Refusal (20 s)** — Ask an off-syllabus question → polite refusal, "saved for your teacher".
6. **Cache vs live (20 s)** — Ask a teacher-approved exam question → instant, labelled "Teacher-approved". Show measured live latency next to it.
7. **Multi-phone (30 s)** — 3–4 phones ask at once; show the queue position and parallel streaming.
8. **Power (30 s)** — Pull the plug on the UPS-backed server (or restart), it comes back with index intact.
9. **Numbers (30 s)** — One slide/screen: recall@3, accuracy, refusal accuracy, p50/p95 latency, phones served, watts. Measured, with method.

10. **Teacher and admin (optional, 40 s)** — Teacher: upload a PDF (size/type checked while it streams), "Try the AI" on it, publish. Admin, on the server laptop only: pause answering → the phone shows "paused"; resume. Accounts screen: usernames and classes only, no names or phone numbers.

Before recording: make sure every chapter's study notes are finished (Teacher → Books → Study notes), and never upload a book during timed or measured segments — reading a book and making its notes use the same model as students' answers and slow them down.

Rules: show Malayalam only if benchmarked. Run the video call from a separate device; point a camera at the offline setup. Keep an uncut, timestamped backup video.
