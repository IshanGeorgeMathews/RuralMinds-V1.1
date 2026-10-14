"""Hybrid retrieval: FTS5 (BM25) + sqlite-vec (cosine), merged by reciprocal-rank fusion.

Keyword search catches exact names (Bhimbetka, Harappa) that embeddings blur; vectors catch
paraphrases, Malayalam suffix variants that FTS misses, and cross-lingual questions. RRF only
needs ranks, so the two very different score scales never have to be compared.
"""

import re
import sqlite3
from dataclasses import dataclass

from .db import serialize_vector
from .llm import embed
from .textnorm import malayalam_stem, normalize

RRF_K = 60  # standard constant from the RRF paper; damps the advantage of rank 1
CANDIDATES = 20  # per search, before fusion

# Python's \w misses Malayalam vowel signs and virama (they are combining marks), so a plain
# \w+ would split words the same way the default FTS tokenizer did.
_WORD = re.compile(r"[\w\u0D00-\u0D7F\u200C\u200D]+")
_STOPWORDS = frozenset(
    {"a", "an", "and", "are", "as", "at", "be", "by", "did", "do", "does", "for", "from"}
    | {"how", "in", "is", "it", "of", "on", "or", "the", "to", "was", "were", "what", "when"}
    | {"where", "which", "who", "whom", "why", "with"}
    # Malayalam question words and fillers
    | {"എന്ത്", "എന്താണ്", "എന്തൊക്കെയാണ്", "എന്തൊക്കെ", "എന്തുകൊണ്ട്", "എന്നാൽ", "എന്ന്"}
    | {"എന്ന", "ആര്", "ആരാണ്", "ആരെല്ലാം", "എവിടെ", "എപ്പോൾ", "എങ്ങനെ", "ഏത്", "ഏതാണ്"}
    | {"ഏവ", "ആണ്", "ഒരു", "ഈ", "ആ", "ഉണ്ട്", "എന്നിവ"}
)


@dataclass
class Filters:
    medium: str
    subject: str
    chapter_no: int | None = None
    # Students always search one allocated book; chapter numbers only mean something inside a
    # book. None (eval, CLI) searches every published book of that medium and subject.
    document_id: int | None = None


@dataclass
class RetrievedChunk:
    chunk_id: int
    book_id: str
    medium: str
    chapter_no: int
    chapter_title: str
    page_start: int
    page_end: int
    text: str
    token_count: int
    score: float = 0.0  # RRF
    fts_rank: int | None = None  # 1-based
    vec_rank: int | None = None
    similarity: float | None = None  # cosine similarity to the question (1 - distance)


def fts_query(question: str) -> str | None:
    """OR of quoted prefix terms. Quoting stops FTS5 syntax injection (AND, NEAR, *, ")."""
    words = _WORD.findall(normalize(question).lower())
    terms = [_search_term(w) for w in words if w not in _STOPWORDS and len(w) > 1]
    if not terms:
        return None
    # Prefix match catches plurals and suffixes ("river" -> "rivers", ചുമതല -> ചുമതലകൾ).
    return " OR ".join(f'"{t}"*' if len(t) >= 3 else f'"{t}"' for t in dict.fromkeys(terms))


def _search_term(word: str) -> str:
    is_malayalam = any("\u0d00" <= ch <= "\u0d7f" for ch in word)
    return malayalam_stem(word) if is_malayalam else word


def _filter_sql(
    filters: Filters, medium: str, subject: str, chapter: str, document: str
) -> tuple[str, list]:
    """WHERE fragment for the hard filters; column names differ between the two searches."""
    sql = f" AND {medium} = ? AND {subject} = ?"
    params: list[object] = [filters.medium, filters.subject]
    if filters.chapter_no is not None:
        sql += f" AND {chapter} = ?"
        params.append(filters.chapter_no)
    if filters.document_id is not None:
        sql += f" AND {document} = ?"
        params.append(filters.document_id)
    return sql, params


def keyword_ranks(conn: sqlite3.Connection, question: str, filters: Filters) -> list[int]:
    match = fts_query(question)
    if match is None:
        return []
    filter_sql, params = _filter_sql(filters, "d.medium", "d.subject", "c.chapter_no", "d.id")
    # A named book may be unpublished (teacher preview); the caller has checked access.
    status_sql = "" if filters.document_id is not None else " AND d.status = 'published'"
    rows = conn.execute(
        "SELECT c.id FROM chunks_fts f JOIN chunks c ON c.id = f.rowid"
        " JOIN documents d ON d.id = c.document_id"
        " WHERE chunks_fts MATCH ?"
        + status_sql
        + filter_sql
        + " ORDER BY bm25(chunks_fts, 1.0, 0.5) LIMIT ?",
        [match, *params, CANDIDATES],
    ).fetchall()
    return [row[0] for row in rows]


def vector_ranks(
    conn: sqlite3.Connection, query_vector: list[float], filters: Filters
) -> list[tuple[int, float]]:
    """(chunk_id, cosine distance), nearest first. Filters run inside the KNN search."""
    filter_sql, params = _filter_sql(filters, "medium", "subject", "chapter_no", "document_id")
    rows = conn.execute(
        "SELECT chunk_id, distance FROM chunk_vectors WHERE embedding MATCH ? AND k = ?"
        + filter_sql
        + " ORDER BY distance",
        [serialize_vector(query_vector), CANDIDATES, *params],
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


def fuse(keyword: list[int], vector: list[tuple[int, float]]) -> dict[int, RetrievedChunk]:
    """Reciprocal-rank fusion. Returns stub chunks (ids, ranks, scores) to be filled from SQL."""
    fused: dict[int, RetrievedChunk] = {}

    def stub(chunk_id: int) -> RetrievedChunk:
        return fused.setdefault(chunk_id, RetrievedChunk(chunk_id, "", "", 0, "", 0, 0, "", 0))

    for rank, chunk_id in enumerate(keyword, start=1):
        hit = stub(chunk_id)
        hit.fts_rank, hit.score = rank, hit.score + 1 / (RRF_K + rank)
    for rank, (chunk_id, distance) in enumerate(vector, start=1):
        hit = stub(chunk_id)
        hit.vec_rank, hit.similarity = rank, 1.0 - distance
        hit.score += 1 / (RRF_K + rank)
    return fused


def _fill(conn: sqlite3.Connection, hits: list[RetrievedChunk]) -> None:
    for hit in hits:
        row = conn.execute(
            "SELECT d.book_id, d.medium, c.chapter_no, c.chapter_title, c.page_start,"
            " c.page_end, c.text, c.token_count FROM chunks c"
            " JOIN documents d ON d.id = c.document_id WHERE c.id = ?",
            (hit.chunk_id,),
        ).fetchone()
        (
            hit.book_id,
            hit.medium,
            hit.chapter_no,
            hit.chapter_title,
            hit.page_start,
            hit.page_end,
            hit.text,
            hit.token_count,
        ) = tuple(row)


def search(
    conn: sqlite3.Connection,
    question: str,
    query_vector: list[float],
    filters: Filters,
    top_k: int,
) -> list[RetrievedChunk]:
    """Best top_k chunks by RRF, each carrying its ranks and similarity for the refusal gate."""
    fused = fuse(keyword_ranks(conn, question, filters), vector_ranks(conn, query_vector, filters))
    best = sorted(fused.values(), key=lambda hit: hit.score, reverse=True)[:top_k]
    _fill(conn, best)
    return best


async def retrieve(
    conn: sqlite3.Connection, question: str, filters: Filters, top_k: int
) -> list[RetrievedChunk]:
    [query_vector] = await embed([question])
    return search(conn, question, query_vector, filters, top_k)
