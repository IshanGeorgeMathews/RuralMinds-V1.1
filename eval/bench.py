"""Load bench: real HTTP + SSE requests against the API at rising concurrency.

    uv run python -m eval.bench --levels 1 2 4 8                 # closed loop
    uv run python -m eval.bench --levels --rates 2 4 --duration 360  # open loop only
    uv run python -m eval.bench --retrieval          # whole-book vs one-chapter search time

Needs both llama-servers running (scripts/start_all.ps1 -ModelsOnly). The bench copies the
database to data/bench-run.db, adds a bench class and student there, starts its own API on a
spare port against that copy, and stops it at the end: the live database and its usage stats are
never touched. Questions come from the eval dev split (Social Science EN/ML, Science EN,
Manglish), each asked at most once per run (QuestionDeck), so no answer is sped up by the
prompt cache of an earlier identical question.

Closed loop (--levels): N phones that each ask again as soon as their answer ends; shows the
ceiling. Open loop (--rates): students arrive at random (Poisson) at R per minute whatever
the queue is doing, like a class; shows whether a class asking at that rate is served.

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
import hashlib
import json
import os
import random
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
    Path("eval/datasets/v2") / n
    for n in ("ss_en.jsonl", "ss_ml.jsonl", "sci_en.jsonl", "manglish.jsonl")
]
SEED = "ruralminds-bench"
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
    # The revision worker would generate between levels and skew them: off for the bench.
    env = {
        **os.environ,
        "RURALMINDS_DB_PATH": BENCH_DB.as_posix(),
        "RURALMINDS_REVISION_WORKER": "false",
    }
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
    usable = [
        i
        for i in items
        if i.get("split") == "dev" and i.get("status") != "dropped" and i.get("answerable", True)
    ]
    return [
        {"question": i["question"], "document_id": doc_ids[i["book_id"]], "lang": i["lang"]}
        for i in usable
    ]


class QuestionDeck:
    """Each request takes a question not yet asked in this run, in a seeded order: a repeat
    would be answered partly from llama-server's prompt cache and look faster than a real one
    (levels 1-2 of the first bench on 19 Oct did). When the deck runs out it reshuffles and
    counts the repeats, so a report can say how many there were."""

    def __init__(self, questions: list[dict]) -> None:
        self._questions = sorted(
            questions, key=lambda q: hashlib.sha256(f"{SEED}:{q['question']}".encode()).digest()
        )
        self._next = 0
        self.repeats = 0

    def __len__(self) -> int:
        return len(self._questions)

    def draw(self) -> dict:
        if self._next >= len(self._questions):
            self.repeats += 1
        question = self._questions[self._next % len(self._questions)]
        self._next += 1
        return question


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


async def signed_in_client(base: str, password: str) -> httpx.AsyncClient:
    """One simulated phone: its own client and session cookie."""
    client = httpx.AsyncClient()
    login = await client.post(
        f"{base}/api/login", json={"username": BENCH_USER, "password": password}
    )
    login.raise_for_status()
    return client


async def user_loop(base: str, password: str, deck: QuestionDeck, count: int) -> list[dict]:
    """Closed loop: a phone that asks its next question as soon as the last answer ends."""
    client = await signed_in_client(base, password)
    try:
        return [await ask_once(client, base, deck.draw()) for _ in range(count)]
    finally:
        await client.aclose()


def arrival_times(rate_per_min: float, duration_s: float, seed: str) -> list[float]:
    """Poisson arrivals (exponential gaps), seeded so every run asks at the same moments."""
    rng = random.Random(seed)
    times, moment = [], rng.expovariate(rate_per_min / 60)
    while moment < duration_s:
        times.append(moment)
        moment += rng.expovariate(rate_per_min / 60)
    return times


async def one_arrival(base: str, password: str, question: dict, delay: float) -> dict:
    """Open loop: a student who asks once at a random moment, whatever the queue is doing."""
    await asyncio.sleep(delay)
    client = await signed_in_client(base, password)
    try:
        return await ask_once(client, base, question)
    finally:
        await client.aclose()


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


async def measured(label: dict, requests, slo: float) -> dict:
    """Run one level's requests and add llama-server token rates and the time window."""
    async with httpx.AsyncClient() as client:
        before = await llama_metrics(client)
        started_at, started = datetime.now(), time.perf_counter()
        batches = await asyncio.gather(*requests)
        wall = time.perf_counter() - started
        after = await llama_metrics(client)
    results = [r for batch in batches for r in (batch if isinstance(batch, list) else [batch])]
    window = [
        started_at.isoformat(timespec="seconds"),
        datetime.now().isoformat(timespec="seconds"),
    ]
    return (
        label
        | summarise_level(results, wall, slo)
        | token_rates(before, after)
        | {"window": window}
    )


async def run_level(
    base: str, password: str, deck: QuestionDeck, users: int, per_user: int, slo: float
) -> dict:
    requests = [user_loop(base, password, deck, per_user) for _ in range(users)]
    return await measured({"mode": "closed", "concurrency": users}, requests, slo)


async def run_open(
    base: str, password: str, deck: QuestionDeck, rate: float, duration: float, slo: float
) -> dict:
    """Students arrive at `rate` per minute for `duration` seconds; the level ends when the
    last of them is answered, so the wait of a backed-up queue is included."""
    times = arrival_times(rate, duration, f"{SEED}:{rate}")
    requests = [one_arrival(base, password, deck.draw(), t) for t in times]
    label = {"mode": "open", "rate_per_min": rate, "duration_s": duration, "arrivals": len(times)}
    return await measured(label, requests, slo)


def summarise_level(results: list[dict], wall: float, slo: float) -> dict:
    answered = [r for r in results if r["event"] in ANSWER_EVENTS]
    admitted = [r for r in results if r["event"] != "busy"]
    good = [
        r
        for r in results
        if (r["event"] in ANSWER_EVENTS and (r["ttft_s"] or r["total_s"]) <= slo)
        or (r["event"] == "refused" and r["total_s"] <= slo)
    ]
    ttfts = [r["ttft_s"] for r in answered if r["ttft_s"] is not None]
    totals = [r["total_s"] for r in answered]
    return {
        "requests": len(results),
        "events": {
            e: sum(r["event"] == e for r in results) for e in sorted({r["event"] for r in results})
        },
        "answers_per_min": round(len(answered) / wall * 60, 2),
        "goodput": round(len(good) / len(results), 3) if results else None,
        # Shedding (W5) turns some questions away at once: report it apart, and goodput over
        # the questions that were let in, or shedding would read as a quality drop.
        "shed": sum(r["event"] == "busy" for r in results),
        "goodput_admitted": round(len(good) / len(admitted), 3) if admitted else None,
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
async def bench(args: argparse.Namespace) -> dict:
    password = prepare_db()
    api = start_api(args.port)
    base = f"http://127.0.0.1:{args.port}"
    try:
        await wait_healthy(base)
        deck = QuestionDeck(load_questions())
        await user_loop(base, password, deck, 1)  # warm-up, not measured
        runs = [run_level(base, password, deck, u, args.per_user, args.slo) for u in args.levels]
        runs += [
            run_open(base, password, deck, rate, args.duration, args.slo) for rate in args.rates
        ]
        results = []
        for run in runs:  # one at a time: levels must not overlap
            level = await run
            if args.resources and args.resources.exists():
                level["resources"] = resource_summary(args.resources, level["window"])
            print(json.dumps(level), flush=True)
            results.append(level)
    finally:
        api.terminate()
        api.wait(timeout=30)
    return {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "slo_first_word_s": args.slo,
        "llm_parallel": settings.llm_parallel,
        "per_user": args.per_user,
        "questions_in_deck": len(deck),
        "repeated_questions": deck.repeats,
        "levels": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Load bench for the RuralMinds API")
    parser.add_argument("--levels", type=int, nargs="*", default=[1, 2, 4, 8])
    parser.add_argument(
        "--per-user", type=int, default=2, help="questions each simulated phone asks"
    )
    parser.add_argument(
        "--rates", type=float, nargs="*", default=[], help="open loop: arrivals per minute"
    )
    parser.add_argument("--duration", type=float, default=360, help="open loop: seconds")
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
        report = asyncio.run(bench(args))
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{args.label}-{datetime.now():%Y%m%d-%H%M}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
