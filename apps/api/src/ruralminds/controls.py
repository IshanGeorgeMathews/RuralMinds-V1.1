"""Admin switches stored in the `settings` table, enforced on the server for every question.

Hiding a button in the UI is not a restriction; these checks are.
"""

import json
import sqlite3
from dataclasses import asdict, dataclass, field, fields

LANGUAGES = ("en", "ml")


@dataclass
class Controls:
    answering_enabled: bool = True
    allowed_languages: list[str] = field(default_factory=lambda: list(LANGUAGES))
    disabled_classes: list[int] = field(default_factory=list)
    max_students: int = 500
    max_teachers: int = 50


def load_controls(conn: sqlite3.Connection) -> Controls:
    stored = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM settings")}
    values = {f.name: json.loads(stored[f.name]) for f in fields(Controls) if f.name in stored}
    return Controls(**values)


def save_controls(conn: sqlite3.Connection, controls: Controls) -> None:
    if not set(controls.allowed_languages) <= set(LANGUAGES):
        raise ValueError("unknown language")
    with conn:
        conn.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            [(key, json.dumps(value)) for key, value in asdict(controls).items()],
        )


def ask_blocked(controls: Controls, language: str, class_id: int | None) -> str | None:
    """message_key explaining why this question may not be answered now, or None."""
    if not controls.answering_enabled:
        return "error.paused"
    if language not in controls.allowed_languages:
        return "error.language_off"
    if class_id is not None and class_id in controls.disabled_classes:
        return "error.class_off"
    return None
