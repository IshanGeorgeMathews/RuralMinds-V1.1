"""SQLite connection helpers: WAL, foreign keys, sqlite-vec, schema."""

import sqlite3
from pathlib import Path

import sqlite_vec

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


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
    conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))


def serialize_vector(vector: list[float]) -> bytes:
    return sqlite_vec.serialize_float32(vector)
