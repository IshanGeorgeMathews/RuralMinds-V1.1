# RuralMinds — Technical Design

**What it is:** an offline learning server for one school. A laptop in the classroom runs the AI and hosts the Wi-Fi, and students use a phone browser. There are no internet calls anywhere in the answer path.

## 1. Deployment

```mermaid
flowchart LR
    subgraph Phones["Students' phones (airplane mode + Wi-Fi)"]
        P1[Phone browser]
        P2[Phone browser]
    end
    T[Teacher browser]
    A["Admin browser<br/>(on the laptop only)"]
    subgraph Laptop["School laptop — no internet"]
        HS[Windows Mobile Hotspot]
        API["FastAPI :8000<br/>web app + JSON/SSE API"]
        LLM["llama-server :8080<br/>Gemma 4 E2B Q4_K_M (iGPU)"]
        EMB["llama-server :8081<br/>bge-m3 embeddings"]
        DB[("SQLite (WAL)<br/>FTS5 + sqlite-vec")]
        FILES[("PDFs, OCR cache,<br/>page images")]
        JOB["Ingest / notes jobs<br/>(separate low-priority process)"]
    end
    P1 & P2 & T --> HS --> API
    A --> API
    API --> LLM
    API --> EMB
    API --> DB
    API --> FILES
    JOB --> DB
    JOB --> LLM
    JOB --> EMB
```

- The model servers listen only on `127.0.0.1`.
- Admin pages answer only requests made from the laptop itself.

## 2. How one question is answered

```mermaid
sequenceDiagram
    participant S as Student phone
    participant A as API (answer.py)
    participant D as SQLite
    participant E as bge-m3
    participant M as Gemma 4 E2B
    S->>A: question, book, chapter, answer language (Auto/EN/ML)
    A->>A: admin switches (paused? language/class allowed?)
    A->>A: detect mode (explain / simpler / example / story / quiz / summary)
    alt summary
        A->>D: chapter study notes
        D-->>S: notes with page links (instant)
    else teacher-approved answer exists
        A->>D: exact-match cache
        D-->>S: answer labelled Teacher-approved (instant)
    else
        opt question not in the book's language (e.g. Manglish)
            A->>M: rewrite question into the book's language
        end
        A->>E: embed question
        A->>D: keyword search (BM25) + vector search, fused (RRF)
        A->>A: refusal gate 1 — nothing relevant found? refuse
        A->>M: tutor prompt + sources [S1]..[S4]
        M-->>S: streamed text
        A->>A: gate 2 — NOT_IN_TEXTBOOK, admits missing, wrong script, no valid [Sn]? refuse
        A-->>S: sections + citations (chapter, printed page) + label
    end
```

**Grounding guarantees**
- The model never sees page numbers. It cites `[S1]`, `[S2]` and so on, and the server maps each one to a chapter and printed page from its own tables, so a page number cannot be invented.
- Everyday examples may come from outside the book only in a box marked *not from your book*.
- Refused questions go to the teacher inbox, counted, with no student identifier.

## 3. Book upload (power-cut safe)

```mermaid
flowchart TD
    U[Teacher picks PDF] --> J["Create job<br/>awaiting_file"]
    J --> S["Stream to .part file<br/>size cap + sha256 while receiving"]
    S --> V{"Real PDF?<br/>pages within limit?<br/>not a duplicate?"}
    V -- no --> X[Rejected, .part deleted]
    V -- yes --> R["fsync + atomic rename<br/>data/books/sha.pdf"]
    R --> D["Teacher adds details<br/>chapters, classes"] --> Q[queued]
    Q --> I["Ingest process<br/>text layer or Tesseract OCR,<br/>cached per page"]
    I --> C["Chunk + embed<br/>one SQL transaction"]
    C --> RD[ready] --> PUB[Teacher tests, then publishes]
    C --> N[Study notes made in background]
    I -. power cut .-> RQ["On restart: re-queued,<br/>OCR resumes from cache"]
```

A janitor removes unfinished uploads and files that no book refers to, so the disk never fills with leftovers.

## 4. Data model (SQLite, `apps/api/src/ruralminds/schema.sql`)

```mermaid
erDiagram
    documents ||--o{ chunks : has
    documents ||--o{ book_chapters : has
    documents ||--o{ chapter_notes : has
    documents ||--o{ class_books : allocated
    classes ||--o{ class_books : reads
    classes ||--o{ users : students
    users ||--o{ sessions : has
    chunks ||--|| chunk_vectors : embedding
    classes ||--o{ unanswered : "per class, no user"
    classes ||--o{ answer_log : "per class, no user"
```

**Privacy by design**
- `users` holds a username, role and class only.
- No table links a question to a user. A unit test (`test_no_table_links_questions_to_accounts`) enforces this.

## 5. Components

| Part | File(s) | Job |
|---|---|---|
| Web API | `apps/api/src/ruralminds/main.py`, `api_student.py`, `api_teacher.py`, `api_admin.py` | Routes per role, serves the built web app |
| Answering | `answer.py`, `tutor.py`, `prompts/` | Modes, language rules, prompt, streaming, refusal checks |
| Search | `retrieve.py`, `textnorm.py` | Hybrid BM25 + vector search, Malayalam text normalisation |
| Books | `ingest.py`, `pages.py`, `chunker.py`, `uploads.py` | PDF → text or OCR → chunks → vectors; upload pipeline, janitor |
| Study notes | `notes.py` | Per-chapter key points with page ranges, plus an overview |
| Accounts | `auth.py`, `admin.py` | scrypt passwords, hashed session tokens, admin CLI |
| Admin switches, stats | `controls.py`, `stats.py` | Pause, language/class limits, class-level counts |
| Frontend | `frontend/src` (SvelteKit, static) | Student app, teacher and admin consoles, English/Malayalam UI |
| Evaluation | `eval/run.py`, `eval/samples/`, `eval/results/` | Recall@3, citation support, refusal accuracy, timings |

## 6. Technology choices

| Need | Choice | Why |
|---|---|---|
| Model runtime | llama.cpp `llama-server` (Vulkan on the iGPU) | Handles requests in parallel, OpenAI-style API; Ollama queues one request at a time |
| Model | Gemma 4 E2B Q4_K_M | Won the bake-off on speed in Malayalam: first word 9 s vs 66 s for Qwen3-4B (Qwen needed 3.4× the tokens for Malayalam text) |
| Embeddings | bge-m3 | Multilingual, works across English and Malayalam |
| Storage | One SQLite file (FTS5 + sqlite-vec, WAL) | No extra server, survives power cuts |
| PDF | pypdfium2 + Tesseract (`mal`, `eng`) | Permissive licences; the Malayalam PDFs use legacy fonts and need OCR |
| Frontend | SvelteKit static build, bundled local fonts | 94 KB gzipped (JS/CSS/HTML); no CDN |

All decisions and the measurements behind them are recorded in [`DECISIONS.md`](DECISIONS.md). The answer contract is in [`ANSWER_POLICY.md`](ANSWER_POLICY.md).
