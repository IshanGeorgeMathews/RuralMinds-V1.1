"""Run an eval set through the real answer pipeline (in-process, against the live llama-servers).

    uv run python -m eval.run --testset eval/datasets/bakeoff_dev.jsonl --label gemma4-e2b

Writes eval/results/<label>-<timestamp>.json with every answer (for human grading) plus
automatic metrics (definitions in eval/metrics.py): hit@1/3/5, recall@3/5, MRR, nDCG@5,
citation support, refusal precision/recall/F1 and false-refusal rate, each rate with a Wilson
95% interval; time to first token and total time as p50/p95/p99.
Answer correctness is graded by people afterwards; this script never judges it.

Result files before metrics_version 2 named hit@3 "recall_at_3" (true/false per item).
"""

import argparse
import asyncio
import json
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import httpx

from eval.metrics import mean_with_ci, percentile, rate, refusal_report, retrieval_scores
from eval.split import verify as verify_split
from ruralminds import tutor
from ruralminds.answer import PROMPT_VERSION, AnswerQueue, AskRequest, Turn, answer_stream
from ruralminds.config import settings
from ruralminds.db import connect

METRICS_VERSION = 2
# Events that give the student an answer: a model answer, or chapter study notes.
ANSWER_EVENTS = ("done", "notes")


def overlaps(pages: list[int], start: int, end: int) -> bool:
    return any(start <= page <= end for page in pages)


def book_for(conn, item: dict, medium: str) -> tuple[int, str]:
    """(document id, subject) of the book to search, as the app does: an item may name `book_id`;
    otherwise the first published Social Science book of that medium. Keeps teacher uploads out
    of the numbers. The subject comes from the book because retrieval filters on it."""
    row = conn.execute(
        "SELECT id, subject FROM documents WHERE book_id = ? OR (? IS NULL AND medium = ?"
        " AND subject = 'social_science' AND status = 'published') ORDER BY id LIMIT 1",
        (item.get("book_id"), item.get("book_id"), medium),
    ).fetchone()
    if row is None:
        raise SystemExit(f"no book for item {item['id']}")
    return row[0], row[1]


async def run_item(conn, client: httpx.AsyncClient, item: dict) -> dict:
    medium = item.get("medium", item["lang"])
    document_id, subject = book_for(conn, item, medium)
    request = AskRequest(
        item["question"],
        item["lang"],
        medium,
        subject=subject,
        # A chapter the student picked in the app; chapter-level requests name it in the question.
        chapter_no=item.get("selected_chapter"),
        # Earlier turns as the phone sends them (question + shown answer text only).
        history=[Turn(turn["question"], turn["answer"]) for turn in item.get("history", [])],
        document_id=document_id,
        use_cache=False,
        mode=item.get("chip"),  # a quick-action chip the student tapped, if any
        debug=True,  # keep a refused answer's text: refusal causes (e.g. Hindi) stay visible
    )
    start = time.perf_counter()
    ttft, final = None, {}
    async for event in answer_stream(conn, client, AnswerQueue(1, 1), request):
        if event["event"] == "token" and ttft is None:
            ttft = time.perf_counter() - start
        elif event["event"] != "token":
            final = event
    total = time.perf_counter() - start
    return score(item, final, ttft, total)


def score(item: dict, final: dict, ttft: float | None, total: float) -> dict:
    data = final.get("data", {})
    gold = item["gold_pages"]
    retrieved = data.get("gate", {}).get("retrieved", [])
    citations = data.get("citations") or data.get("points", [])  # notes cite per key point
    refused = final.get("event") not in ANSWER_EVENTS
    result = {
        **item,
        "event": final.get("event"),
        "refused": refused,
        "reason": data.get("reason"),
        "answer": data.get("text"),
        "raw_text": data.get("raw_text"),  # model text of a refused answer
        "example": data.get("example"),
        "check": data.get("check"),
        "quiz_answers": data.get("answers"),
        "mode": routed_mode(final),
        "search_query": data.get("gate", {}).get("search_query"),
        "citations": [
            (c.get("chapter_no", data.get("chapter_no")), c["page_start"], c["page_end"])
            for c in citations
        ],
        "retrieved_pages": [(r["page_start"], r["page_end"]) for r in retrieved],
        "ttft_s": round(ttft, 2) if ttft is not None else None,
        "total_s": round(total, 2),
        "refusal_correct": refused != item["answerable"],
        "grade": None,  # filled in by human graders: 0 wrong, 1 partly right, 2 right
    }
    if not refused:
        # Script fidelity: a letter outside Latin and Malayalam in what the phone showed.
        shown = (result["answer"], result["example"], result["check"], result["quiz_answers"])
        result["third_script"] = tutor.third_script(" ".join(str(x) for x in shown if x))
    if "expected_mode" in item:
        result["intent_correct"] = result["mode"] in as_list(item["expected_mode"])
    if "expected_chapter" in item:
        chapters = {chapter for chapter, _, _ in result["citations"]}
        result["chapter_correct"] = chapters == {item["expected_chapter"]}
    if item["answerable"]:
        ranked = [(r["page_start"], r["page_end"]) for r in retrieved]
        # Cached answers and study notes skip retrieval: no ranking to score.
        result["retrieval"] = retrieval_scores(gold, ranked) if ranked else None
        result["citation_supported"] = any(
            overlaps(gold, c["page_start"], c["page_end"]) for c in citations
        )
    return result


def routed_mode(final: dict) -> str | None:
    """The kind of help the app chose; study notes answer chapter-level requests."""
    if final.get("event") == "notes":
        return "notes"
    return final.get("data", {}).get("mode")


def as_list(value: object) -> list:
    return value if isinstance(value, list) else [value]


def _group(result: dict) -> str:
    # An item may name its arm (e.g. "manglish->en-book"); otherwise it is grouped by language.
    return result.get("arm", result["lang"])


def summarise(results: list[dict], key: Callable[[dict], str] | None = None) -> dict:
    key = key or _group
    groups = sorted({key(r) for r in results})
    summary = {group: _summary([r for r in results if key(r) == group]) for group in groups}
    if len(groups) > 1:
        summary["all"] = _summary(results)
    return summary


def _summary(rows: list[dict]) -> dict:
    answerable = [r for r in rows if r["answerable"]]
    answered = [r for r in answerable if not r["refused"]]
    scored = [r["retrieval"] for r in answerable if r.get("retrieval")]
    ttfts = [r["ttft_s"] for r in answered if r["ttft_s"] is not None]
    totals = [r["total_s"] for r in answered]
    return {
        "items": len(rows),
        "retrieval": {
            **{
                key: rate(sum(bool(s[key]) for s in scored), len(scored))
                for key in ("hit_at_1", "hit_at_3", "hit_at_5")
            },
            **{
                key: mean_with_ci([float(s[key]) for s in scored])
                for key in ("recall_at_3", "recall_at_5", "mrr", "ndcg_at_5")
            },
        },
        "answered_when_answerable": rate(len(answered), len(answerable)),
        "citation_supported": rate(
            sum(bool(r.get("citation_supported")) for r in answerable), len(answerable)
        ),
        "refusal": refusal_report([(r["answerable"], r["refused"]) for r in rows]),
        "intent_correct": _rate_of(rows, "intent_correct"),
        "chapter_correct": _rate_of(rows, "chapter_correct"),
        "third_script": _rate_of(rows, "third_script"),
        "ttft_s": {f"p{p}": percentile(ttfts, p / 100) for p in (50, 95, 99)},
        "total_s": {f"p{p}": percentile(totals, p / 100) for p in (50, 95, 99)},
    }


async def run(testsets: list[Path], label: str, split: str | None, verified_only: bool) -> dict:
    items = [
        json.loads(line)
        for testset in testsets
        for line in testset.read_text(encoding="utf-8").splitlines()
        if line
    ]
    items = select_items(items, split, verified_only)
    conn = connect(settings.db_path)
    async with httpx.AsyncClient() as client:
        await require_quiet(client)
        props = (await client.get(f"{settings.llm_url}/props")).json()
        await run_item(conn, client, warmup_item(items[0]))  # first call pays GPU warm-up
        results = []
        for item in items:
            results.append(await run_item(conn, client, item))
            print(_progress_line(results[-1]), flush=True)
    return {
        "label": label,
        "metrics_version": METRICS_VERSION,
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "testset": [str(testset) for testset in testsets],
        "db_path": str(settings.db_path),
        "split": split,
        "verified_only": verified_only,
        "model_path": props.get("model_path"),
        "prompt_version": PROMPT_VERSION,
        "settings": {
            key: getattr(settings, key)
            for key in ("max_context_tokens", "final_top_k", "refusal_threshold", "temperature")
        }
        | {"max_tokens": settings.max_tokens},
        "summary": summarise(results),
        "by_style": summarise(results, key=lambda r: r.get("style", "lookup")),
        "by_expected": summarise(results, key=lambda r: r.get("expected", "answer")),
        "results": results,
    }


async def require_quiet(client: httpx.AsyncClient) -> None:
    """Timings are only valid on an idle model: on 13 Oct, notes generation running on the
    same llama-server doubled the measured times ("contended" result files)."""
    slots = (await client.get(f"{settings.llm_url}/slots")).json()
    busy = sum(bool(slot.get("is_processing")) for slot in slots)
    if busy:
        raise SystemExit(f"llama-server has {busy} busy slot(s): stop notes/other jobs first")


def check_safe_to_run(split: str | None, allow_live_db: bool) -> None:
    """The eval goes through the real answer path, which writes answer_log rows: run it on a
    copy of the database so the admin's usage stats stay real. Test numbers need the frozen
    split unchanged."""
    if settings.db_path.resolve() == Path("data/ruralminds.db").resolve() and not allow_live_db:
        raise SystemExit(
            "eval would write to the live database: copy data/ruralminds.db to"
            " data/eval-run.db and set RURALMINDS_DB_PATH=data/eval-run.db"
            " (or pass --allow-live-db)"
        )
    if split == "test":
        changed = verify_split()
        if changed:
            raise SystemExit(f"frozen test items changed in {changed}: no test run")


def _rate_of(rows: list[dict], key: str) -> dict | None:
    """Rate over the items that define this check; None when no item does."""
    scored = [r[key] for r in rows if key in r]
    return rate(sum(scored), len(scored)) if scored else None


def warmup_item(template: dict) -> dict:
    """A question outside every item set: warming up with a measured item would cache its prompt
    and fake a near-zero first-word time for it."""
    return {**template, "id": "warmup", "question": "What is a map?", "history": [], "chip": None}


def select_items(items: list[dict], split: str | None, verified_only: bool) -> list[dict]:
    """Dropped items never count; numbers we publish come from reviewed items only."""
    return [
        item
        for item in items
        if item.get("status") != "dropped"
        and (split is None or item.get("split") == split)
        and (not verified_only or item.get("verified"))
    ]


def _progress_line(result: dict) -> str:
    status = "REFUSED " + str(result["reason"]) if result["refused"] else "answered"
    hit = (result.get("retrieval") or {}).get("hit_at_3", "-")
    return f"{result['id']:18} {status:28} hit@3={hit!s:5} ttft={result['ttft_s']}s total={result['total_s']}s"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an eval set through the answer pipeline")
    parser.add_argument("--testset", type=Path, nargs="+", required=True)
    parser.add_argument("--label", required=True, help="e.g. the model name")
    parser.add_argument("--split", help="only items with this split (dev/test)")
    parser.add_argument(
        "--verified-only", action="store_true", help="only items a reviewer marked ok"
    )
    parser.add_argument("--out", type=Path, default=Path("eval/results"))
    parser.add_argument("--allow-live-db", action="store_true", help="write to the real database")
    args = parser.parse_args()
    check_safe_to_run(args.split, args.allow_live_db)
    report = asyncio.run(run(args.testset, args.label, args.split, args.verified_only))
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    path = args.out / f"{args.label}-{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
