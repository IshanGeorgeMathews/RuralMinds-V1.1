"""Run an eval set through the real answer pipeline (in-process, against the live llama-servers).

    uv run python -m eval.run --testset eval/datasets/bakeoff_dev.jsonl --label gemma4-e2b

Writes eval/results/<label>-<timestamp>.json with every answer (for human grading) plus
automatic metrics: recall@3, citation support, refusal accuracy, time to first token, total.
Answer correctness is graded by people afterwards; this script never judges it.
"""

import argparse
import asyncio
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

import httpx

from ruralminds.answer import PROMPT_VERSION, AnswerQueue, AskRequest, answer_stream
from ruralminds.config import settings
from ruralminds.db import connect

RECALL_K = 3


def overlaps(pages: list[int], start: int, end: int) -> bool:
    return any(start <= page <= end for page in pages)


def book_for(conn, item: dict, medium: str) -> int:
    """Search one named book, as the app does: an item may name `book_id`; otherwise the first
    published Social Science book of that medium. Keeps teacher uploads out of the numbers."""
    row = conn.execute(
        "SELECT id FROM documents WHERE book_id = ? OR (? IS NULL AND medium = ?"
        " AND subject = 'social_science' AND status = 'published') ORDER BY id LIMIT 1",
        (item.get("book_id"), item.get("book_id"), medium),
    ).fetchone()
    if row is None:
        raise SystemExit(f"no book for item {item['id']}")
    return row[0]


async def run_item(conn, client: httpx.AsyncClient, item: dict) -> dict:
    medium = item.get("medium", item["lang"])
    request = AskRequest(
        item["question"],
        item["lang"],
        medium,
        document_id=book_for(conn, item, medium),
        use_cache=False,
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
    citations = data.get("citations", [])
    refused = final.get("event") != "done"
    result = {
        **item,
        "event": final.get("event"),
        "refused": refused,
        "reason": data.get("reason"),
        "answer": data.get("text"),
        "example": data.get("example"),
        "check": data.get("check"),
        "quiz_answers": data.get("answers"),
        "mode": data.get("mode"),
        "search_query": data.get("gate", {}).get("search_query"),
        "citations": [(c["chapter_no"], c["page_start"], c["page_end"]) for c in citations],
        "retrieved_pages": [(r["page_start"], r["page_end"]) for r in retrieved],
        "ttft_s": round(ttft, 2) if ttft is not None else None,
        "total_s": round(total, 2),
        "refusal_correct": refused != item["answerable"],
        "grade": None,  # filled in by human graders: 0 wrong, 1 partly right, 2 right
    }
    if item["answerable"]:
        top = retrieved[:RECALL_K]
        result["recall_at_3"] = any(overlaps(gold, r["page_start"], r["page_end"]) for r in top)
        result["citation_supported"] = any(
            overlaps(gold, c["page_start"], c["page_end"]) for c in citations
        )
    return result


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(fraction * len(ordered)))], 2)


def _group(result: dict) -> str:
    # An item may name its arm (e.g. "manglish->en-book"); otherwise it is grouped by language.
    return result.get("arm", result["lang"])


def summarise(results: list[dict]) -> dict:
    summary = {}
    for group in sorted({_group(r) for r in results}):
        rows = [r for r in results if _group(r) == group]
        answerable = [r for r in rows if r["answerable"]]
        answered = [r for r in answerable if not r["refused"]]
        ttfts = [r["ttft_s"] for r in answered if r["ttft_s"] is not None]
        summary[group] = {
            "items": len(rows),
            "recall_at_3": _rate(answerable, "recall_at_3"),
            "answered_when_answerable": _share(len(answered), len(answerable)),
            "citation_supported": _rate(answerable, "citation_supported"),
            "refusal_accuracy": _rate(rows, "refusal_correct"),
            "ttft_p50_s": percentile(ttfts, 0.5),
            "ttft_p95_s": percentile(ttfts, 0.95),
            "total_p50_s": percentile([r["total_s"] for r in answered], 0.5),
            "total_mean_s": round(statistics.mean(r["total_s"] for r in rows), 2),
        }
    return summary


def _rate(rows: list[dict], key: str) -> str:
    return _share(sum(bool(r.get(key)) for r in rows), len(rows))


def _share(hits: int, count: int) -> str:
    return f"{hits}/{count}" if count else "0/0"


async def run(testset: Path, label: str, split: str | None) -> dict:
    items = [json.loads(line) for line in testset.read_text(encoding="utf-8").splitlines() if line]
    items = [item for item in items if split is None or item.get("split") == split]
    conn = connect(settings.db_path)
    async with httpx.AsyncClient() as client:
        props = (await client.get(f"{settings.llm_url}/props")).json()
        await run_item(conn, client, {**items[0], "id": "warmup"})  # first call pays GPU warm-up
        results = []
        for item in items:
            results.append(await run_item(conn, client, item))
            print(_progress_line(results[-1]), flush=True)
    return {
        "label": label,
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "testset": str(testset),
        "split": split,
        "model_path": props.get("model_path"),
        "prompt_version": PROMPT_VERSION,
        "settings": {
            key: getattr(settings, key)
            for key in ("max_context_tokens", "final_top_k", "refusal_threshold", "temperature")
        }
        | {"max_tokens": settings.max_tokens},
        "summary": summarise(results),
        "results": results,
    }


def _progress_line(result: dict) -> str:
    status = "REFUSED " + str(result["reason"]) if result["refused"] else "answered"
    recall = result.get("recall_at_3", "-")
    return f"{result['id']:7} {status:28} recall@3={recall!s:5} ttft={result['ttft_s']}s total={result['total_s']}s"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an eval set through the answer pipeline")
    parser.add_argument("--testset", type=Path, required=True)
    parser.add_argument("--label", required=True, help="e.g. the model name")
    parser.add_argument("--split", help="only items with this split (dev/test)")
    parser.add_argument("--out", type=Path, default=Path("eval/results"))
    args = parser.parse_args()
    report = asyncio.run(run(args.testset, args.label, args.split))
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    path = args.out / f"{args.label}-{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
