-- RuralMinds SQLite schema (source of truth). Applied by ruralminds.db.init_schema()
-- after the sqlite-vec extension is loaded; db.migrate() upgrades older files first.
-- Schema version 3 (PRAGMA user_version). Accounts hold a username and nothing else about
-- a child: no name, phone, email or ID number, and no table links a question to an account.

-- ---------- Content ----------
CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY,
    book_id       TEXT NOT NULL UNIQUE,       -- id from apps/api/books.toml
    title         TEXT NOT NULL,
    board         TEXT NOT NULL,              -- SCERT-KL | NCERT | TEACHER
    medium        TEXT NOT NULL,              -- en | ml
    grade         INTEGER NOT NULL,
    subject       TEXT NOT NULL,              -- social_science | science | maths
    file_path     TEXT NOT NULL,
    sha256        TEXT NOT NULL,
    page_count    INTEGER NOT NULL,
    licence       TEXT,
    status        TEXT NOT NULL DEFAULT 'published' CHECK (status IN ('ready','published')),
    ingested_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per PDF page: how its text was obtained. Used for the OCR quality report.
CREATE TABLE IF NOT EXISTS pages (
    document_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    pdf_page      INTEGER NOT NULL,
    printed_page  INTEGER NOT NULL,
    chapter_no    INTEGER,
    method        TEXT NOT NULL CHECK (method IN ('text','ocr')),
    char_count    INTEGER NOT NULL,
    script_ratio  REAL NOT NULL,              -- share of letters in the book's script
    PRIMARY KEY (document_id, pdf_page)
);

CREATE TABLE IF NOT EXISTS chunks (
    id            INTEGER PRIMARY KEY,
    document_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal       INTEGER NOT NULL,
    chapter_no    INTEGER NOT NULL,
    chapter_title TEXT NOT NULL,
    page_start    INTEGER NOT NULL,           -- printed page numbers
    page_end      INTEGER NOT NULL,
    text          TEXT NOT NULL,
    token_count   INTEGER,                    -- embedder tokens
    UNIQUE (document_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id, chapter_no);

-- Keyword index (BM25). The default unicode61 tokenizer treats Malayalam vowel signs,
-- virama and ZWJ/ZWNJ as separators, which shreds words into single letters. tokenchars
-- lists them (U+0D00-0D03, 0D3B-0D3C, 0D3E-0D4D, 0D57, 0D62-0D63, U+200C, U+200D).
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, chapter_title,
    content='chunks', content_rowid='id',
    tokenize="unicode61 remove_diacritics 0 tokenchars 'ഀഁംഃ഻഼ാിീുൂൃൄ൅െേൈ൉ൊോൌ്ൗൢൣ‌‍'"
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text, chapter_title) VALUES (new.id, new.text, new.chapter_title);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, chapter_title)
    VALUES ('delete', old.id, old.text, old.chapter_title);
END;

-- Dense vectors (bge-m3, 1024 dims). Metadata columns allow filtering inside the KNN query.
-- vec0 rows are NOT removed by ON DELETE CASCADE: delete them explicitly with their chunks.
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0(
    chunk_id    INTEGER PRIMARY KEY,
    embedding   float[1024] distance_metric=cosine,
    medium      TEXT,
    subject     TEXT,
    chapter_no  INTEGER,
    document_id INTEGER
);

-- Chapter list per book (from books.toml or the teacher's upload form): the catalog shown
-- to students and the page ranges used to tag chunks.
CREATE TABLE IF NOT EXISTS book_chapters (
    document_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chapter_no    INTEGER NOT NULL,
    title         TEXT NOT NULL,
    pdf_start     INTEGER NOT NULL,
    printed_start INTEGER NOT NULL,
    PRIMARY KEY (document_id, chapter_no)
);

-- Teacher uploads. The row exists before the file arrives, so a power cut at any point
-- leaves a job the server can resume or clean up (see uploads.py).
CREATE TABLE IF NOT EXISTS ingest_jobs (
    id            INTEGER PRIMARY KEY,
    status        TEXT NOT NULL DEFAULT 'awaiting_file'
                  CHECK (status IN ('awaiting_file','awaiting_details','queued','ingesting',
                                    'ready','failed')),
    filename      TEXT NOT NULL,              -- as named on the teacher's device; display only
    metadata      TEXT,                       -- JSON: title, grade, subject, medium, chapters...
    sha256        TEXT,
    bytes         INTEGER,
    page_count    INTEGER,
    attempts      INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    document_id   INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    created_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------- People (created by the admin; no self sign-up) ----------
CREATE TABLE IF NOT EXISTS classes (
    id            INTEGER PRIMARY KEY,
    grade         INTEGER NOT NULL CHECK (grade BETWEEN 1 AND 12),
    section       TEXT NOT NULL,
    medium        TEXT NOT NULL CHECK (medium IN ('en','ml')),
    enabled       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (grade, section)
);

CREATE TABLE IF NOT EXISTS class_books (
    class_id      INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    document_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    PRIMARY KEY (class_id, document_id)
);

CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY,
    username       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    role           TEXT NOT NULL CHECK (role IN ('student','teacher','admin')),
    class_id       INTEGER REFERENCES classes(id) ON DELETE SET NULL,  -- students only
    pw_hash        TEXT NOT NULL,
    enabled        INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_day TEXT                       -- a date, not a timestamp trail
);

CREATE TABLE IF NOT EXISTS teacher_classes (
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    class_id      INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, class_id)
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash    TEXT PRIMARY KEY,           -- sha256 of the cookie value
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at    REAL NOT NULL,              -- unix time; hard limit
    idle_seconds  INTEGER NOT NULL,
    last_seen     REAL NOT NULL
);

-- Admin switches. Values are JSON. Enforced by the server, not just hidden in the UI.
CREATE TABLE IF NOT EXISTS settings (
    key           TEXT PRIMARY KEY,
    value         TEXT NOT NULL
);

-- ---------- Answers ----------
CREATE TABLE IF NOT EXISTS answer_cache (
    id              INTEGER PRIMARY KEY,
    cache_key       TEXT NOT NULL UNIQUE,     -- hash(normalised_q, language, subject, chapter, book sha)
    question        TEXT NOT NULL,
    normalised_q    TEXT NOT NULL,
    language        TEXT NOT NULL,
    subject         TEXT NOT NULL,
    chapter_no      INTEGER,
    book_id         TEXT NOT NULL,
    doc_sha256      TEXT NOT NULL,
    answer_json     TEXT NOT NULL,            -- text + rendered citations
    status          TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft','approved','needs_review','rejected')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Questions the book could not answer -> teacher inbox. Deliberately no student identifier.
-- One row per (class, book, normalised question): asking again raises times_asked instead of
-- adding rows, and the janitor deletes old rows, so the inbox and the file stay small.
-- Only students' questions are stored (teacher tests and the eval are not).
CREATE TABLE IF NOT EXISTS unanswered (
    id            INTEGER PRIMARY KEY,
    question      TEXT NOT NULL,
    language      TEXT,
    subject       TEXT,
    chapter_no    INTEGER,
    best_score    REAL,
    reason        TEXT,                       -- gate | not_in_textbook | no_valid_citation
    class_id      INTEGER NOT NULL DEFAULT 0,
    document_id   INTEGER,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    normalised_q  TEXT,
    times_asked   INTEGER NOT NULL DEFAULT 1,
    last_asked    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_unanswered_question
    ON unanswered(class_id, document_id, normalised_q);

-- AI study notes per chapter (notes.py): key points with page ranges from our own chunks,
-- plus a short overview. Served instantly for "summarise chapter N"; a teacher can approve.
CREATE TABLE IF NOT EXISTS chapter_notes (
    document_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chapter_no    INTEGER NOT NULL,
    language      TEXT NOT NULL,
    overview      TEXT NOT NULL,
    points        TEXT NOT NULL,              -- JSON [{"text", "page_start", "page_end"}]
    status        TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved')),
    model         TEXT,
    seconds       REAL,                       -- generation time, for the cost note
    generated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (document_id, chapter_no, language)
);

-- One row per question for stats and class activity. Deliberately no user, session or
-- device column, and no question text (that lives only in `unanswered`, for the teacher).
CREATE TABLE IF NOT EXISTS answer_log (
    id            INTEGER PRIMARY KEY,
    day           TEXT NOT NULL DEFAULT (date('now', 'localtime')),
    class_id      INTEGER NOT NULL DEFAULT 0, -- 0 = teacher / eval
    document_id   INTEGER,
    chapter_no    INTEGER,
    language      TEXT NOT NULL,
    outcome       TEXT NOT NULL CHECK (outcome IN ('answered','refused','cached','error')),
    ttft_ms       INTEGER,
    total_ms      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_answer_log_day ON answer_log(day, class_id);
