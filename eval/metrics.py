"""Standard evaluation metrics, stdlib only, so every number in a report has one definition.

Retrieval units are textbook pages: a retrieved chunk is relevant when its page range covers
a gold page, and each gold page counts once (two chunks on the same page are not two hits).

    hit@k      any gold page in the top k chunks (what earlier reports called "recall_at_3";
               identical to recall@k when an item has one gold page)
    recall@k   share of the item's gold pages covered by the top k chunks
    MRR        mean of 1 / rank of the first chunk that covers a gold page (0 if none)
    nDCG@k     gain 1 for each newly covered gold page, discounted by log2(rank + 1);
               the ideal ranking covers one gold page per rank

Refusal is scored as a binary classifier whose positive class is "should refuse", so
precision answers "when we refused, was it right?" and recall "did we refuse everything
off-book?". The false-refusal rate is the share of answerable questions we refused.

Every rate carries a Wilson 95% interval: on 8 items, 8/8 only shows the true rate is
above ~0.68, and a report must say so.
"""

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

Z_95 = 1.959964


def wilson_interval(hits: int, count: int, z: float = Z_95) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion (better than ±z·SE at small n)."""
    if count == 0:
        return None
    share = hits / count
    denominator = 1 + z * z / count
    centre = (share + z * z / (2 * count)) / denominator
    margin = z * math.sqrt(share * (1 - share) / count + z * z / (4 * count * count)) / denominator
    return round(max(0.0, centre - margin), 3), round(min(1.0, centre + margin), 3)


def rate(hits: int, count: int) -> dict[str, object]:
    return {
        "hits": hits,
        "n": count,
        "rate": round(hits / count, 3) if count else None,
        "ci95": wilson_interval(hits, count),
    }


def mean_with_ci(values: Sequence[float], resamples: int = 2000) -> dict[str, object]:
    """Mean with a percentile-bootstrap 95% interval (the usual choice for MRR / nDCG).

    A normal approximation can leave [0, 1] on small samples (it gave 1.08 on 8 items);
    resampled means cannot. Fixed seed, so a re-run reports the same interval.
    """
    if not values:
        return {"mean": None, "n": 0, "ci95": None}
    mean = sum(values) / len(values)
    if len(values) < 2:
        return {"mean": round(mean, 3), "n": len(values), "ci95": None}
    rng = random.Random(0)
    means = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(resamples))
    low, high = means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]
    return {"mean": round(mean, 3), "n": len(values), "ci95": (round(low, 3), round(high, 3))}


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Nearest-rank percentile: the smallest value with at least `fraction` of values <= it."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return round(ordered[rank - 1], 2)


# ---------- retrieval ----------
PageRange = tuple[int, int]


def _new_gold(gold: set[int], covered: set[int], page_range: PageRange) -> set[int]:
    start, end = page_range
    return {page for page in gold if start <= page <= end} - covered


def first_relevant_rank(gold: Sequence[int], ranked: Sequence[PageRange]) -> int | None:
    pages = set(gold)
    for rank, page_range in enumerate(ranked, start=1):
        if _new_gold(pages, set(), page_range):
            return rank
    return None


def hit_at(gold: Sequence[int], ranked: Sequence[PageRange], k: int) -> bool:
    rank = first_relevant_rank(gold, ranked)
    return rank is not None and rank <= k


def recall_at(gold: Sequence[int], ranked: Sequence[PageRange], k: int) -> float:
    pages, covered = set(gold), set()
    for page_range in ranked[:k]:
        covered |= _new_gold(pages, covered, page_range)
    return len(covered) / len(pages) if pages else 0.0


def reciprocal_rank(gold: Sequence[int], ranked: Sequence[PageRange]) -> float:
    rank = first_relevant_rank(gold, ranked)
    return 1 / rank if rank else 0.0


def ndcg_at(gold: Sequence[int], ranked: Sequence[PageRange], k: int) -> float:
    pages, covered = set(gold), set()
    dcg = 0.0
    for rank, page_range in enumerate(ranked[:k], start=1):
        gained = _new_gold(pages, covered, page_range)
        covered |= gained
        dcg += len(gained) / math.log2(rank + 1)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(pages), k) + 1))
    return dcg / ideal if ideal else 0.0


def retrieval_scores(gold: Sequence[int], ranked: Sequence[PageRange]) -> dict[str, float | bool]:
    """Per-item retrieval metrics; the report averages them over answerable items."""
    return {
        "hit_at_1": hit_at(gold, ranked, 1),
        "hit_at_3": hit_at(gold, ranked, 3),
        "hit_at_5": hit_at(gold, ranked, 5),
        "recall_at_3": recall_at(gold, ranked, 3),
        "recall_at_5": recall_at(gold, ranked, 5),
        "mrr": reciprocal_rank(gold, ranked),
        "ndcg_at_5": round(ndcg_at(gold, ranked, 5), 4),
    }


# ---------- refusal ----------
@dataclass
class RefusalCounts:
    true_refusals: int = 0  # off-book, refused
    false_refusals: int = 0  # answerable, refused
    missed_refusals: int = 0  # off-book, answered
    answered_ok: int = 0  # answerable, answered

    def add(self, answerable: bool, refused: bool) -> None:
        if refused and not answerable:
            self.true_refusals += 1
        elif refused:
            self.false_refusals += 1
        elif not answerable:
            self.missed_refusals += 1
        else:
            self.answered_ok += 1


def refusal_report(pairs: Sequence[tuple[bool, bool]]) -> dict[str, object]:
    """pairs = (answerable, refused) per item."""
    counts = RefusalCounts()
    for answerable, refused in pairs:
        counts.add(answerable, refused)
    refused = counts.true_refusals + counts.false_refusals
    should_refuse = counts.true_refusals + counts.missed_refusals
    answerable = counts.false_refusals + counts.answered_ok
    precision = counts.true_refusals / refused if refused else None
    recall = counts.true_refusals / should_refuse if should_refuse else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {
        "counts": counts.__dict__,
        "accuracy": rate(counts.true_refusals + counts.answered_ok, len(pairs)),
        "precision": rate(counts.true_refusals, refused),
        "recall": rate(counts.true_refusals, should_refuse),
        "f1": round(f1, 3) if f1 is not None else None,
        "false_refusal_rate": rate(counts.false_refusals, answerable),
    }


# ---------- agreement between graders ----------
def cohen_kappa(first: Sequence[object], second: Sequence[object]) -> float | None:
    """Chance-corrected agreement of two graders on the same items (nominal labels)."""
    if len(first) != len(second):
        raise ValueError("graders must label the same items")
    if not first:
        return None
    count = len(first)
    observed = sum(a == b for a, b in zip(first, second, strict=True)) / count
    labels = set(first) | set(second)
    expected = sum(
        (sum(a == label for a in first) / count) * (sum(b == label for b in second) / count)
        for label in labels
    )
    if expected == 1:
        return 1.0  # both graders used one identical label throughout
    return round((observed - expected) / (1 - expected), 3)


def weighted_kappa(
    first: Sequence[int], second: Sequence[int], labels: Sequence[int]
) -> float | None:
    """Quadratic-weighted Cohen's kappa for ordinal scores (e.g. a 1-3 rubric): disagreeing by
    two steps costs four times as much as by one, which plain kappa ignores."""
    if len(first) != len(second):
        raise ValueError("graders must score the same items")
    if not first:
        return None
    index = {label: n for n, label in enumerate(labels)}
    size, count = len(labels), len(first)
    observed = [[0.0] * size for _ in range(size)]
    for a, b in zip(first, second, strict=True):
        observed[index[a]][index[b]] += 1
    row = [sum(observed[i]) for i in range(size)]
    col = [sum(observed[i][j] for i in range(size)) for j in range(size)]
    weight = [[(i - j) ** 2 / (size - 1) ** 2 for j in range(size)] for i in range(size)]
    disagree = sum(weight[i][j] * observed[i][j] for i in range(size) for j in range(size))
    chance = sum(weight[i][j] * row[i] * col[j] / count for i in range(size) for j in range(size))
    if chance == 0:
        return 1.0
    return round(1 - disagree / chance, 3)
