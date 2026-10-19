"""SQLite connection helpers: WAL, foreign keys, sqlite-vec, schema and its migration."""

import logging
import sqlite3
from pathlib import Path

import sqlite_vec

log = logging.getLogger("ruralminds.db")

SCHEMA_FILE = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 4

# v3 -> v4 (20 Oct): revision question bank and exam portions; new tables only.
# v1 -> v2: accounts, uploads, settings, answer_log; chunk_vectors gains document_id.
# vec0 tables cannot be ALTERed, so the vectors are parked in a plain table and copied back:
# no re-embedding. One transaction, so a power cut leaves the v1 file untouched.
_V1_TO_V2_BEFORE = """
CREATE TABLE _vec_backup AS
    SELECT v.chunk_id, v.embedding, v.medium, v.subject, v.chapter_no, c.document_id
    FROM chunk_vectors v JOIN chunks c ON c.id = v.chunk_id;
DROP TABLE chunk_vectors;
DROP TABLE IF EXISTS usage_daily;
ALTER TABLE unanswered ADD COLUMN class_id INTEGER NOT NULL DEFAULT 0;
ALTER TABLE unanswered ADD COLUMN document_id INTEGER;
"""
# v2 -> v3: the inbox groups repeated questions (only students' questions are kept).
_V2_TO_V3_BEFORE = """
ALTER TABLE unanswered ADD COLUMN normalised_q TEXT;
ALTER TABLE unanswered ADD COLUMN times_asked INTEGER NOT NULL DEFAULT 1;
ALTER TABLE unanswered ADD COLUMN last_asked TEXT;
DELETE FROM unanswered WHERE class_id = 0 OR document_id IS NULL;
UPDATE unanswered SET normalised_q = lower(trim(question)), last_asked = created_at;
DELETE FROM unanswered WHERE id NOT IN
    (SELECT max(id) FROM unanswered GROUP BY class_id, document_id, normalised_q);
"""
_V1_TO_V2_AFTER = """
INSERT INTO chunk_vectors (chunk_id, embedding, medium, subject, chapter_no, document_id)
    SELECT chunk_id, embedding, medium, subject, chapter_no, document_id FROM _vec_backup;
DROP TABLE _vec_backup;
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open the database with the pragmas every connection needs."""
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    # WAL survives power cuts mid-write and lets readers continue during ingestion.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    schema = SCHEMA_FILE.read_text(encoding="utf-8")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    has_tables = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'documents'").fetchone()
    if has_tables is None or version >= SCHEMA_VERSION:
        conn.executescript(schema)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        return
    # Older file: run every step it is missing, then the schema, in one transaction.
    log.warning("upgrading database schema from version %d to %d", version, SCHEMA_VERSION)
    # Each step only for files older than it: re-running v2->v3's ADD COLUMNs on a v3 file
    # would fail ("duplicate column") and the server would not start. v3 -> v4 only adds
    # tables (revision bank, exam portions), which the schema's CREATE IF NOT EXISTS makes.
    before = (_V1_TO_V2_BEFORE if version < 2 else "") + (_V2_TO_V3_BEFORE if version < 3 else "")
    after = _V1_TO_V2_AFTER if version < 2 else ""
    stamp = f"PRAGMA user_version = {SCHEMA_VERSION};"
    conn.executescript(f"BEGIN;{before}{schema}{after}{stamp}COMMIT;")


def serialize_vector(vector: list[float]) -> bytes:
    return sqlite_vec.serialize_float32(vector)
