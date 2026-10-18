"""Load bench: real HTTP + SSE requests against the API at rising concurrency.

    uv run python -m eval.bench --levels 1 2 4 8
    uv run python -m eval.bench --retrieval          # whole-book vs one-chapter search time

Needs both llama-servers running (scripts/start_all.ps1 -ModelsOnly). The bench copies the
database to data/bench-run.db, adds a bench class and student there, starts its own API on a
spare port against that copy, and stops it at the end: the live database and its usage stats are
never touched. Questions come from the eval dev split (Social Science EN/ML, Science EN).

Per level (standard serving metrics, as in MLPerf Inference's server scenario):
  TTFT and end-to-end time p50/p95/p99; answers per minute; goodput = share of requests that
  were served within the first-word target (answered with first token <= --slo seconds, or
  refused within it); busy/error counts; decode and prompt tokens/s from llama-server's
  /metrics (only when it was started with --metrics).
Resource use (CPU, RAM, GPU, battery watts) is sampled by scripts/sample_resources.ps1; give its
CSV with --resources and each level's window is summarised from it.
"""

import argparse
import asyncio
import csv
import json
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

from eval.metrics import percentile
from ruralminds.config import settings
from ruralminds.db import connect

BENCH_DB = Path("data/bench-run.db")
BENCH_USER = "bench-student"
QUESTION_FILES = [
    Path("eval/datasets/v2") / n for n in ("ss_en.jsonl", "ss_ml.jsonl", "sci_en.jsonl")
]
ANSWER_EVENTS = ("done", "notes")


# ---------- setup ----------
def prepare_db() -> str:
    """Fresh copy of the live database with a bench class that has every book; returns the
    bench student's password. Refuses when an ingest job is unfinished: the bench API would
    resume it and OCR would run during the measurements."""
    live = connect(settings.db_path)
    pending = live.execute(
        "SELECT count(*) FROM ingest_jobs WHERE status IN ('queued', 'ingesting')"
    ).fetchone()[0]
    if pending:
        raise SystemExit(f"{pending} ingest job(s) unfinished: let them finish before benching")
    BENCH_DB.unlink(missing_ok=True)
    live.execute(f"VACUUM INTO '{BENCH_DB.as_posix()}'")
    live.close()
    from ruralminds import auth  # imported late: hashing setup is not needed for --retrieval

    conn = connect(BENCH_DB)
    password = secrets.token_urlsafe(12)
    with conn:
        conn.execute("INSERT OR IGNORE INTO classes (grade, section, medium) VALUES (8, 'Z', 'en')")
        class_id = conn.execute(
            "SELECT id FROM classes WHERE grade = 8 AND section = 'Z'"
        ).fetchone()[0]
        conn.execute("INSERT OR IGNORE INTO class_books SELECT ?, id FROM documents", (class_id,))
        conn.execute(
            "INSERT INTO users (username, role, class_id, pw_hash) VALUES (?, 'student', ?, ?)"
            " ON CONFLICT (username) DO UPDATE SET pw_hash = excluded.pw_hash, enabled = 1",
            (BENCH_USER, class_id, auth.hash_password(password)),
        )
    conn.close()
    return password


def start_api(port: int) -> subprocess.Popen:
    env = {**os.environ, "RURALMINDS_DB_PATH": BENCH_DB.as_posix()}
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "ruralminds.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    return subprocess.Popen(command, env=env)


async def wait_healthy(base: str, seconds: int = 60) -> None:
    async with httpx.AsyncClient() as client:
        for _ in range(seconds * 2):
            try:
                if (await client.get(f"{base}/health", timeout=1)).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
    raise SystemExit("bench API did not start")


def load_questions() -> list[dict]:
    conn = connect(BENCH_DB)
    doc_ids = dict(conn.execute("SELECT book_id, id FROM documents").fetchall())
    items = [
        json.loads(line)
        for path in QUESTION_FILES
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    usable = [i for i in items if i.get("split") == "dev" and i.get("status") != "dropped"]
    return [
        {"question": i["question"], "document_id": doc_ids[i["book_id"]], "lang": i["lang"]}
        for i in usable
    ]


# ---------- one request ----------
async def ask_once(client: httpx.AsyncClient, base: str, question: dict) -> dict:
    """Stream one answer over SSE; time to first token, total time, final event."""
    body = {"question": question["question"], "document_id": question["document_id"]}
    started = time.perf_counter()
    first = None
    tokens = 0
    final = None
    async with client.stream("POST", f"{base}/api/ask", json=body, timeout=600) as reply:
        event = None
        async for line in reply.aiter_lines():
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: ") and event:
                if event == "token":
                    tokens += 1
                    first = first or time.perf_counter()
                elif event != "queued":
                    final = event
    ended = time.perf_counter()
    return {
        "event": final or f"http_{reply.status_code}",
        "ttft_s": None if first is None else first - started,
        "total_s": ended - started,
        "token_events": tokens,
    }


async def user_loop(
    base: str, password: str, questions: list[dict], count: int, offset: int
) -> list[dict]:
    async with httpx.AsyncClient() as client:
        login = await client.post(
            f"{base}/api/login", json={"username": BENCH_USER, "password": password}
        )
        login.raise_for_status()
        return [
            await ask_once(client, base, questions[(offset + n) % len(questions)])
            for n in range(count)
        ]


# ---------- one level ----------
async def llama_metrics(client: httpx.AsyncClient) -> dict[str, float]:
    """Prometheus counters from llama-server --metrics; empty if the flag is off."""
    try:
        reply = await client.get(f"{settings.llm_url}/metrics", timeout=5)
    except httpx.HTTPError:
        return {}
    if reply.status_code != 200:
        return {}
    pattern = re.compile(r"^llamacpp:(\w+)\s+([0-9.eE+-]+)$", re.MULTILINE)
    return {name: float(value) for name, value in pattern.findall(reply.text)}


def token_rates(before: dict, after: dict) -> dict:
    def rate(tokens: str, seconds: str) -> float | None:
        if tokens not in after or seconds not in after:
            return None
        spent = after[seconds] - before.get(seconds, 0)
        return round((after[tokens] - before.get(tokens, 0)) / spent, 1) if spent > 0 else None

    return {
        "decode_tokens_per_s": rate("tokens_predicted_total", "tokens_predicted_seconds_total"),
        "prompt_tokens_per_s": rate("prompt_tokens_total", "prompt_seconds_total"),
    }


async def run_level(
    base: str, password: str, questions: list[dict], users: int, per_user: int, slo: float
) -> dict:
    async with httpx.AsyncClient() as client:
        before = await llama_metrics(client)
        started_at, started = datetime.now(), time.perf_counter()
        batches = await asyncio.gather(
            *(user_loop(base, password, questions, per_user, u * per_user) for u in range(users))
        )
        wall = time.perf_counter() - started
        after = await llama_metrics(client)
    return (
        summarise_level(users, [r for batch in batches for r in batch], wall, slo)
        | token_rates(before, after)
        | {
            "window": [
                started_at.isoformat(timespec="seconds"),
                datetime.now().isoformat(timespec="seconds"),
            ]
        }
    )


def summarise_level(users: int, results: list[dict], wall: float, slo: float) -> dict:
    answered = [r for r in results if r["event"] in ANSWER_EVENTS]
    good = [
        r
        for r in results
        if (r["event"] in ANSWER_EVENTS and (r["ttft_s"] or r["total_s"]) <= slo)
        or (r["event"] == "refused" and r["total_s"] <= slo)
    ]
    ttfts = [r["ttft_s"] for r in answered if r["ttft_s"] is not None]
    totals = [r["total_s"] for r in answered]
    return {
        "concurrency": users,
        "requests": len(results),
        "events": {
            e: sum(r["event"] == e for r in results) for e in sorted({r["event"] for r in results})
        },
        "answers_per_min": round(len(answered) / wall * 60, 2),
        "goodput": round(len(good) / len(results), 3) if results else None,
        "ttft_s": {f"p{p}": percentile(ttfts, p / 100) for p in (50, 95, 99)},
        "total_s": {f"p{p}": percentile(totals, p / 100) for p in (50, 95, 99)},
        "wall_s": round(wall, 1),
    }


# ---------- resources ----------
def resource_summary(csv_path: Path, window: list[str]) -> dict:
    """Mean of each sampled column inside the level's time window (sample_resources.ps1 CSV)."""
    start, end = (datetime.fromisoformat(w) for w in window)
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = [
            r for r in csv.DictReader(handle) if start <= datetime.fromisoformat(r["time"]) <= end
        ]
    columns = [c for c in (rows[0].keys() if rows else []) if c != "time"]
    means = {}
    for column in columns:
        values = [float(r[column]) for r in rows if r[column] not in ("", None)]
        means[column] = round(sum(values) / len(values), 2) if values else None
    return {"samples": len(rows), **means}


# ---------- retrieval timing ----------
async def retrieval_timing(rounds: int) -> dict:
    """Does searching the whole book cost more than one chapter? (premise check, 17 Oct plan)"""
    from ruralminds.retrieve import Filters, retrieve

    conn = connect(settings.db_path)
    items = [
        json.loads(line) for line in QUESTION_FILES[0].read_text(encoding="utf-8").splitlines()
    ]
    items = [i for i in items if i.get("split") == "dev"][:rounds]
    doc = conn.execute("SELECT id FROM documents WHERE book_id = 'ss8-pt1-en'").fetchone()[0]
    timings: dict[str, list[float]] = {"whole_book": [], "one_chapter": []}
    for item in items:
        for label, chapter in (("whole_book", None), ("one_chapter", item["chapter_no"])):
            started = time.perf_counter()
            await retrieve(conn, item["question"], Filters("en", "social_science", chapter, doc), 6)
            timings[label].append((time.perf_counter() - started) * 1000)
    return {
        label: {"n": len(v), "p50_ms": percentile(v, 0.5), "p95_ms": percentile(v, 0.95)}
        for label, v in timings.items()
    }


# ---------- main ----------
async def bench(
    levels: list[int], per_user: int, slo: float, port: int, resources: Path | None
) -> dict:
    password = prepare_db()
    api = start_api(port)
    base = f"http://127.0.0.1:{port}"
    try:
        await wait_healthy(base)
        questions = load_questions()
        await user_loop(base, password, questions, 1, 0)  # warm-up, not measured
        results = []
        for users in levels:
            level = await run_level(base, password, questions, users, per_user, slo)
            if resources and resources.exists():
                level["resources"] = resource_summary(resources, level["window"])
            print(json.dumps(level), flush=True)
            results.append(level)
    finally:
        api.terminate()
        api.wait(timeout=30)
    return {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "slo_first_word_s": slo,
        "llm_parallel": settings.llm_parallel,
        "per_user": per_user,
        "levels": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Load bench for the RuralMinds API")
    parser.add_argument("--levels", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument(
        "--per-user", type=int, default=3, help="questions each simulated phone asks"
    )
    parser.add_argument("--slo", type=float, default=15.0, help="first-word target in seconds")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument(
        "--resources", type=Path, help="CSV written by scripts/sample_resources.ps1"
    )
    parser.add_argument(
        "--retrieval", action="store_true", help="only time whole-book vs chapter search"
    )
    parser.add_argument("--label", default="bench")
    parser.add_argument("--out", type=Path, default=Path("eval/results"))
    args = parser.parse_args()
    if args.retrieval:
        report = {"retrieval_ms": asyncio.run(retrieval_timing(30))}
    else:
        report = asyncio.run(bench(args.levels, args.per_user, args.slo, args.port, args.resources))
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{args.label}-{datetime.now():%Y%m%d-%H%M}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
