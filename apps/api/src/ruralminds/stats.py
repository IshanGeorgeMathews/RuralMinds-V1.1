"""Usage numbers for the admin overview and class activity for teachers.

Everything is counted per class, language, book and chapter, never per student (rule 4).
Groups with fewer than MIN_GROUP questions are not shown, so a small class cannot be read
back to one child. "Often not found" means the textbook search failed, not that the class
is weak: we label what we measured.
"""

import sqlite3
from collections import Counter

import httpx

from .config import settings

MIN_GROUP = 5


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def usage(conn: sqlite3.Connection, days: int) -> dict[str, object]:
    since = f"-{days - 1} days"
    rows = conn.execute(
        "SELECT a.day, a.language, a.outcome, a.ttft_ms, a.total_ms, a.class_id,"
        " c.grade, c.section FROM answer_log a LEFT JOIN classes c ON c.id = a.class_id"
        " WHERE a.day >= date('now', 'localtime', ?)",
        (since,),
    ).fetchall()
    by_day: dict[str, Counter[str]] = {}
    for row in rows:
        by_day.setdefault(row["day"], Counter())[row["outcome"]] += 1
    answered = [row for row in rows if row["outcome"] == "answered"]
    first_word = [row["ttft_ms"] for row in answered if row["ttft_ms"] is not None]
    total = [row["total_ms"] for row in answered if row["total_ms"] is not None]
    return {
        "days": days,
        "questions": len(rows),
        "outcomes": dict(Counter(row["outcome"] for row in rows)),
        "by_day": [{"day": day, **counts} for day, counts in sorted(by_day.items())],
        "by_language": dict(Counter(row["language"] for row in rows)),
        "by_class": dict(Counter(_class_label(row) for row in rows)),
        "first_word_ms": {
            "p50": _percentile(first_word, 0.5),
            "p95": _percentile(first_word, 0.95),
        },
        "total_ms": {"p50": _percentile(total, 0.5), "p95": _percentile(total, 0.95)},
    }


def _class_label(row: sqlite3.Row) -> str:
    return f"{row['grade']}{row['section']}" if row["grade"] is not None else "teacher"


def class_activity(conn: sqlite3.Connection, class_ids: list[int], days: int) -> list[dict]:
    """Per class and chapter: how often asked, how often the book had no answer."""
    if not class_ids:
        return []
    marks = ",".join("?" * len(class_ids))
    rows = conn.execute(
        "SELECT a.class_id, a.document_id, a.chapter_no, d.title AS book,"
        " bc.title AS chapter_title, count(*) AS asked,"
        " sum(a.outcome = 'refused') AS not_found,"
        " sum(a.language = 'ml') AS in_malayalam"
        " FROM answer_log a LEFT JOIN documents d ON d.id = a.document_id"
        " LEFT JOIN book_chapters bc ON bc.document_id = a.document_id"
        " AND bc.chapter_no = a.chapter_no"
        f" WHERE a.class_id IN ({marks}) AND a.day >= date('now', 'localtime', ?)"
        " GROUP BY a.class_id, a.document_id, a.chapter_no ORDER BY asked DESC",
        (*class_ids, f"-{days - 1} days"),
    ).fetchall()
    return [dict(row) for row in rows if row["asked"] >= MIN_GROUP]


async def model_status(client: httpx.AsyncClient) -> dict[str, object]:
    """What the admin panel shows about the two llama-servers. Never raises."""
    status: dict[str, object] = {"chat": False, "embed": False, "model": None, "busy_slots": None}
    for name, url in (("chat", settings.llm_url), ("embed", settings.embed_url)):
        try:
            status[name] = (await client.get(f"{url}/health", timeout=2)).status_code == 200
        except httpx.HTTPError:
            status[name] = False
    if status["chat"]:
        try:
            props = (await client.get(f"{settings.llm_url}/props", timeout=2)).json()
            path = str(props.get("model_path", "")).replace("\\", "/").rsplit("/", 1)[-1]
            status["model"] = settings.chat_model_label or path or None
            slots = (await client.get(f"{settings.llm_url}/slots", timeout=2)).json()
            status["busy_slots"] = sum(bool(slot.get("is_processing")) for slot in slots)
            status["slots"] = len(slots)
        except (httpx.HTTPError, ValueError):
            pass
    return status
