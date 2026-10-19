"""Chapter study notes: the answer to "summarise chapter 2" and the Learn screen.

A whole chapter (3,000-7,000 tokens here) is too long to read at question time on a laptop,
so notes are made once per chapter, in the background:

  map:      every ~900 tokens of the chapter -> 3-5 key points, each with a source marker;
            the marker is checked and replaced by that chunk's printed pages (our numbers,
            never the model's)
  overview: the key points -> a 4-6 sentence overview (no new facts)

    python -m ruralminds.notes --book ss8-pt1-en [--chapter 2] [--force]
"""

import argparse
import asyncio
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass

import httpx

from .config import settings
from .db import connect, init_schema
from .llm import COMPLETE_TIMEOUT, complete
from .textnorm import normalize
from .tutor import load_prompt

log = logging.getLogger("ruralminds.notes")

GROUP_TOKENS = 900  # bge-m3 tokens of book text per map call
_MARKER = re.compile(r"\[\s*S\s*(\d+)\s*\]", re.IGNORECASE)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?।])")
_LANGUAGE = {"en": "English", "ml": "Malayalam (Malayalam script)"}


@dataclass
class ChunkText:
    text: str
    page_start: int
    page_end: int
    token_count: int


def notes_answer(
    conn: sqlite3.Connection, document_id: int, chapter_no: int, language: str
) -> dict[str, object] | None:
    row = conn.execute(
        "SELECT n.*, bc.title AS chapter_title FROM chapter_notes n"
        " LEFT JOIN book_chapters bc ON bc.document_id = n.document_id"
        " AND bc.chapter_no = n.chapter_no"
        " WHERE n.document_id = ? AND n.chapter_no = ? AND n.language = ?",
        (document_id, chapter_no, language),
    ).fetchone()
    if row is None:
        return None
    return {
        "document_id": document_id,
        "chapter_no": chapter_no,
        "chapter_title": row["chapter_title"],
        "overview": row["overview"],
        "points": [{**point, "text": _tidy(point["text"])} for point in json.loads(row["points"])],
        "language": language,
        "label": "teacher_approved" if row["status"] == "approved" else "ai_notes",
    }


def _tidy(text: str) -> str:
    """Removing a marker leaves "word ." behind; close the gap."""
    return _SPACE_BEFORE_PUNCT.sub(r"\1", " ".join(text.split()))


def group_chunks(chunks: list[ChunkText], budget: int = GROUP_TOKENS) -> list[list[ChunkText]]:
    groups: list[list[ChunkText]] = [[]]
    used = 0
    for chunk in chunks:
        if groups[-1] and used + chunk.token_count > budget:
            groups.append([])
            used = 0
        groups[-1].append(chunk)
        used += chunk.token_count
    return [group for group in groups if group]


def parse_points(reply: str, group: list[ChunkText]) -> list[dict[str, object]]:
    """Bullet lines with at least one valid marker; pages come from the cited chunks."""
    points = []
    for line in reply.splitlines():
        if not _BULLET.match(line):
            continue
        cited = [int(n) for n in _MARKER.findall(line) if 1 <= int(n) <= len(group)]
        text = _tidy(_MARKER.sub("", _BULLET.sub("", line)))
        if not cited or len(text) < 8:
            continue  # an uncited point could be the model's own knowledge: dropped
        chunks = [group[n - 1] for n in dict.fromkeys(cited)]
        points.append(
            {
                "text": normalize(text),
                "page_start": min(chunk.page_start for chunk in chunks),
                "page_end": max(chunk.page_end for chunk in chunks),
            }
        )
    return points


async def wait_for_idle_model(client: httpx.AsyncClient, poll_s: float = 2.0) -> None:
    """Students first: before each model call, wait until no llama-server slot is busy.
    Notes run in their own process and cannot join the API's answer queue, so this is how
    they step aside (W5, 19 Oct). Known gap: while a notes call runs, the API still counts
    that slot as free; llama-server then queues the student's request itself, briefly."""
    while True:
        try:
            slots = (await client.get(f"{settings.llm_url}/slots", timeout=5)).json()
        except (httpx.HTTPError, ValueError):
            return  # cannot tell (e.g. /slots disabled): don't block notes forever
        if not any(slot.get("is_processing") for slot in slots):
            return
        await asyncio.sleep(poll_s)


async def chapter_points(
    client: httpx.AsyncClient, chunks: list[ChunkText], language: str
) -> list[dict[str, object]]:
    points = []
    for group in group_chunks(chunks):
        sources = "\n\n".join(f"[S{n}] {chunk.text}" for n, chunk in enumerate(group, start=1))
        messages = [
            {"role": "system", "content": load_prompt("notes_points_v1")},
            {
                "role": "user",
                "content": f"Language: {_LANGUAGE[language]}\n\nSources:\n{sources}",
            },
        ]
        await wait_for_idle_model(client)
        points.extend(parse_points(await complete(messages, client, max_tokens=320), group))
    return points


async def overview(
    client: httpx.AsyncClient, points: list[dict[str, object]], language: str
) -> str:
    listing = "\n".join(f"- {point['text']}" for point in points)
    messages = [
        {"role": "system", "content": load_prompt("notes_overview_v1")},
        {"role": "user", "content": f"Language: {_LANGUAGE[language]}\n\nKey points:\n{listing}"},
    ]
    await wait_for_idle_model(client)
    return normalize(_MARKER.sub("", await complete(messages, client, max_tokens=260))).strip()


def _chunks(conn: sqlite3.Connection, document_id: int, chapter_no: int) -> list[ChunkText]:
    rows = conn.execute(
        "SELECT text, page_start, page_end, COALESCE(token_count, 250) AS tokens FROM chunks"
        " WHERE document_id = ? AND chapter_no = ? ORDER BY ordinal",
        (document_id, chapter_no),
    ).fetchall()
    return [ChunkText(row[0], row[1], row[2], row[3]) for row in rows]


async def make_chapter_notes(
    conn: sqlite3.Connection,
    client: httpx.AsyncClient,
    document_id: int,
    chapter_no: int,
    language: str,
) -> bool:
    started = time.perf_counter()
    chunks = _chunks(conn, document_id, chapter_no)
    if not chunks:
        return False
    points = await chapter_points(client, chunks, language)
    if not points:
        log.warning("no cited key points for document %d chapter %d", document_id, chapter_no)
        return False
    summary = await overview(client, points, language)
    seconds = round(time.perf_counter() - started, 1)
    with conn:
        conn.execute(
            "INSERT INTO chapter_notes (document_id, chapter_no, language, overview, points,"
            " status, model, seconds) VALUES (?,?,?,?,?, 'draft', ?, ?)"
            " ON CONFLICT (document_id, chapter_no, language) DO UPDATE SET"
            " overview = excluded.overview, points = excluded.points, status = 'draft',"
            " model = excluded.model, seconds = excluded.seconds,"
            " generated_at = datetime('now')",
            (
                document_id,
                chapter_no,
                language,
                summary,
                json.dumps(points, ensure_ascii=False),
                await _model_name(client),
                seconds,
            ),
        )
    log.info(
        "notes: document %d chapter %d: %d points in %.0f s",
        document_id,
        chapter_no,
        len(points),
        seconds,
    )
    return True


async def _model_name(client: httpx.AsyncClient) -> str | None:
    try:
        props = (await client.get(f"{settings.llm_url}/props", timeout=5)).json()
    except (httpx.HTTPError, ValueError):
        return None
    return str(props.get("model_path", "")).replace("\\", "/").rsplit("/", 1)[-1] or None


async def make_book_notes(
    conn: sqlite3.Connection,
    document_id: int,
    chapters: list[int] | None = None,
    force: bool = False,
) -> None:
    """Notes for every chapter (in the book's language) that has none yet, or all with force."""
    medium = conn.execute("SELECT medium FROM documents WHERE id = ?", (document_id,)).fetchone()[0]
    wanted = chapters or [
        row[0]
        for row in conn.execute(
            "SELECT chapter_no FROM book_chapters WHERE document_id = ? ORDER BY chapter_no",
            (document_id,),
        )
    ]
    async with httpx.AsyncClient(timeout=COMPLETE_TIMEOUT) as client:
        for chapter_no in wanted:
            exists = conn.execute(
                "SELECT status FROM chapter_notes WHERE document_id = ? AND chapter_no = ?"
                " AND language = ?",
                (document_id, chapter_no, medium),
            ).fetchone()
            if exists and (not force or exists[0] == "approved"):
                continue  # never overwrite notes a teacher approved
            try:
                await make_chapter_notes(conn, client, document_id, chapter_no, medium)
            except httpx.HTTPError:
                log.exception("notes failed for chapter %d; will retry next run", chapter_no)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate chapter study notes")
    parser.add_argument("--book", required=True, help="book id, e.g. ss8-pt1-en")
    parser.add_argument("--chapter", type=int, action="append")
    parser.add_argument("--force", action="store_true", help="regenerate (keeps approved notes)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    conn = connect(settings.db_path)
    init_schema(conn)
    row = conn.execute("SELECT id FROM documents WHERE book_id = ?", (args.book,)).fetchone()
    if row is None:
        parser.error(f"unknown book {args.book!r}")
    asyncio.run(make_book_notes(conn, row[0], args.chapter, args.force))


if __name__ == "__main__":
    main()
