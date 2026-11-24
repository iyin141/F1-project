"""Hybrid retrieval: Postgres full-text + pgvector cosine, reciprocal rank fusion, cross-encoder rerank.

    query -> FTS top-50 (ts_rank)  \
                                    > RRF (k=60) -> top-`pool` -> reranker -> top-8 Hits
          -> vector top-50 (cosine) /

Postgres only (raw SQL on the tsvector and `<=>`). Pure pieces (`rrf`, `fts_query`, `extract`) are
DB-free and unit-tested; the SQL is covered by the live test against the local pgvector container.

FIA terms: results carry a short quoted `extract` (EXTRACT_CAP chars) and the FIA source URL; the full
chunk `text` is for internal reranking/prompting and must not be returned to end users in bulk.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Protocol

from django.db import DatabaseError, connection, transaction

K_EACH = 50       # candidates from each retriever
RRF_K = 60        # Cormack et al. 2009 constant; flattens the gap between rank 1 and rank 10
POOL = 20         # fused candidates sent to the (expensive) reranker (decided with 3d: 30 costs 1.5x for little recall)
TOP_K = 8
EXTRACT_CAP = 300  # characters of quoted text shown per result (FIA T&C: short extracts only)

_TOKEN = re.compile(r"[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*")


# ---------- pure pieces ----------

def rrf(rankings: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    """Reciprocal rank fusion. score(d) = sum over rankings of 1 / (k + rank), rank 1-based.
    A document missing from a ranking adds nothing for it. Ties: better best-rank first, then lower id,
    so the result is deterministic."""
    score: dict[int, float] = {}
    best: dict[int, int] = {}
    for ranking in rankings:
        for pos, doc in enumerate(ranking, start=1):
            score[doc] = score.get(doc, 0.0) + 1.0 / (k + pos)
            best[doc] = min(best.get(doc, pos), pos)
    return sorted(score.items(), key=lambda kv: (-kv[1], best[kv[0]], kv[0]))


def fts_query(question: str) -> str:
    """OR-joined tsquery text. websearch/plainto AND every word, which returns nothing for a natural-language
    question; with OR, ts_rank scores by how many (and how rare) terms match. Tokens are alphanumeric
    (article numbers like B5.10.1 survive), so the string is injection-safe; stop words are dropped by the
    'english' config inside Postgres."""
    toks = list(dict.fromkeys(t.lower() for t in _TOKEN.findall(question)))
    return " | ".join(f"'{t}'" for t in toks)


def extract(text: str, cap: int = EXTRACT_CAP) -> str:
    """First `cap` characters, cut at a word boundary, with an ellipsis if shortened."""
    text = " ".join(text.split())
    if len(text) <= cap:
        return text
    return text[:cap].rsplit(" ", 1)[0].rstrip(",.;:") + "..."


# ---------- reranker interface ----------

class Reranker(Protocol):
    def score(self, query: str, texts: list[str]) -> list[float]: ...


class FastEmbedReranker:
    """ONNX cross-encoder through fastembed (no torch). Model chosen by STEWARDS_RERANKER."""

    def __init__(self, model_name: str | None = None, max_chars: int | None = None):
        self.model_name = model_name or os.environ.get("STEWARDS_RERANKER", DEFAULT_RERANKER)
        # Cross-encoder cost is linear in tokens: only the first max_chars of each passage are scored
        # (the heading and the rule's opening are at the start). 0 = no truncation.
        self.max_chars = int(os.environ.get("STEWARDS_RERANK_CHARS", DEFAULT_RERANK_CHARS)) if max_chars is None else max_chars
        self._m = None

    def score(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        if self._m is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            from .embeddings import _cache_dir

            self._m = TextCrossEncoder(model_name=self.model_name, cache_dir=_cache_dir())
        if self.max_chars:
            texts = [t[: self.max_chars] for t in texts]
        return [float(s) for s in self._m.rerank(query, texts)]


# Default is a small model on purpose: see docs/v2/progress/A3-stewards.md (3b) for the CPU numbers.
DEFAULT_RERANKER = "Xenova/ms-marco-MiniLM-L-12-v2"
DEFAULT_RERANK_CHARS = 700  # about 170 tokens
_reranker: Reranker | None = None


def get_reranker() -> Reranker:
    global _reranker
    if _reranker is None:
        _reranker = FastEmbedReranker()
    return _reranker


# ---------- results ----------

@dataclass
class Hit:
    chunk_id: int
    text: str            # full chunk, for reranking / prompting only
    extract: str         # <= EXTRACT_CAP chars, what may be quoted to users
    page: int | None
    article: str
    section: str
    source_url: str
    source_title: str
    doc_type: str
    year: int
    race: str
    score: float         # reranker score (or RRF score when rerank is off)
    fts_rank: int | None = None
    vec_rank: int | None = None
    rrf_score: float = 0.0


# ---------- SQL ----------

def _filters(year, doc_type, race, source_ids=None) -> tuple[str, list]:
    sql, params = "", []
    if source_ids is not None:  # restrict to a fixed corpus snapshot (used by the evaluation)
        sql += " AND s.id = ANY(%s)"
        params.append(list(source_ids))
    if year is not None:
        sql += " AND s.year = %s"
        params.append(int(year))
    if doc_type:
        sql += " AND s.doc_type = %s"
        params.append(doc_type)
    if race:
        sql += " AND s.race ILIKE %s"
        params.append(f"%{race}%")
    return sql, params


def fts_ids(cur, question: str, limit: int, year=None, doc_type=None, race=None, source_ids=None) -> list[int]:
    q = fts_query(question)
    if not q:
        return []
    f, fp = _filters(year, doc_type, race, source_ids)
    cur.execute(
        "SELECT c.id FROM assistant_docchunk c JOIN assistant_documentsource s ON s.id = c.source_id, "
        "to_tsquery('english', %s) q "
        f"WHERE c.search_vector @@ q{f} ORDER BY ts_rank(c.search_vector, q) DESC, c.id LIMIT %s",
        [q, *fp, limit],
    )
    return [r[0] for r in cur.fetchall()]


def vector_ids(cur, qvec: list[float], limit: int, year=None, doc_type=None, race=None, source_ids=None) -> list[int]:
    f, fp = _filters(year, doc_type, race, source_ids)
    lit = "[" + ",".join(f"{x:.7g}" for x in qvec) + "]"
    cur.execute(
        "SELECT c.id FROM assistant_docchunk c JOIN assistant_documentsource s ON s.id = c.source_id "
        f"WHERE c.embedding IS NOT NULL{f} ORDER BY c.embedding <=> %s::vector, c.id LIMIT %s",
        [*fp, lit, limit],
    )
    return [r[0] for r in cur.fetchall()]


def _load(cur, ids: list[int]) -> dict[int, dict]:
    if not ids:
        return {}
    cur.execute(
        "SELECT c.id, c.text, c.page, c.article, c.section, s.url, s.title, s.doc_type, s.year, s.race "
        "FROM assistant_docchunk c JOIN assistant_documentsource s ON s.id = c.source_id WHERE c.id = ANY(%s)",
        [ids],
    )
    cols = ["id", "text", "page", "article", "section", "url", "title", "doc_type", "year", "race"]
    return {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}


def search(cur, question, qvec, *, year=None, doc_type=None, race=None, source_ids=None, top_k=TOP_K, k_each=K_EACH,
           pool=POOL, reranker: Reranker | None = None, rerank=True) -> list[Hit]:
    """The retrieval pipeline on an open DB cursor (Django or psycopg2). `qvec` is the query embedding."""
    f_ids = fts_ids(cur, question, k_each, year, doc_type, race, source_ids)
    v_ids = vector_ids(cur, qvec, k_each, year, doc_type, race, source_ids)
    fused = rrf([f_ids, v_ids])[:pool]
    rows = _load(cur, [i for i, _ in fused])
    f_rank = {i: r for r, i in enumerate(f_ids, 1)}
    v_rank = {i: r for r, i in enumerate(v_ids, 1)}
    hits = [
        Hit(i, rows[i]["text"], extract(rows[i]["text"]), rows[i]["page"], rows[i]["article"], rows[i]["section"],
            rows[i]["url"], rows[i]["title"], rows[i]["doc_type"], rows[i]["year"], rows[i]["race"],
            score=s, fts_rank=f_rank.get(i), vec_rank=v_rank.get(i), rrf_score=s)
        for i, s in fused if i in rows
    ]
    if rerank and hits:
        scores = (reranker or get_reranker()).score(question, [h.text for h in hits])
        for h, sc in zip(hits, scores):
            h.score = sc
        hits.sort(key=lambda h: (-h.score, -h.rrf_score, h.chunk_id))
    return hits[:top_k]


def retrieve(question: str, *, embed_query=None, **kw) -> list[Hit]:
    """Hybrid search on the Django DB. kwargs: year, doc_type, race, top_k, k_each, pool, reranker, rerank
    (False = RRF order only). `embed_query(str) -> list[float]` defaults to the bge query embedder (with the
    BGE instruction prefix)."""
    if connection.vendor != "postgresql":
        raise RuntimeError("hybrid retrieval needs Postgres + pgvector")
    if embed_query is None:
        from .embeddings import embed_query
    qvec = embed_query(question)
    with transaction.atomic(), connection.cursor() as cur:
        try:  # pgvector >= 0.8: keep scanning the HNSW graph until the WHERE filter is satisfied
            with transaction.atomic():
                cur.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order'")
        except DatabaseError:
            pass
        with transaction.atomic():
            cur.execute("SET LOCAL hnsw.ef_search = 100")
        return search(cur, question, qvec, **kw)
