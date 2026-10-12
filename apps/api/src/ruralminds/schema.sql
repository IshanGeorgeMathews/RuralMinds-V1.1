-- RuralMinds SQLite schema (source of truth). Applied by ruralminds.db.init_schema()
-- after the sqlite-vec extension is loaded. Phase 0: no student accounts at all.

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
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0(
    chunk_id    INTEGER PRIMARY KEY,
    embedding   float[1024] distance_metric=cosine,
    medium      TEXT,
    subject     TEXT,
    chapter_no  INTEGER
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

-- Refused / low-confidence questions -> teacher queue. Deliberately no student identifier.
CREATE TABLE IF NOT EXISTS unanswered (
    id            INTEGER PRIMARY KEY,
    question      TEXT NOT NULL,
    language      TEXT,
    subject       TEXT,
    chapter_no    INTEGER,
    best_score    REAL,
    reason        TEXT,                       -- gate | no_valid_citation
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Aggregate usage only (no per-child tracking).
CREATE TABLE IF NOT EXISTS usage_daily (
    day           TEXT NOT NULL,
    language      TEXT NOT NULL,
    subject       TEXT NOT NULL,
    questions     INTEGER NOT NULL DEFAULT 0,
    cache_hits    INTEGER NOT NULL DEFAULT 0,
    refusals      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, language, subject)
);
