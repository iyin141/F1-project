"""Retrieval: pure pieces everywhere; SQL against a TEMP-table schema on the local pgvector container only
(skipped without STEWARDS_PG_DSN)."""
import os

import pytest

from api.assistant import retrieval as r

DSN = os.environ.get("STEWARDS_PG_DSN")


# ---------- pure ----------

def test_rrf_hand_computed():
    # lists: A = [1, 2, 3], B = [3, 1]; k = 60
    got = dict(r.rrf([[1, 2, 3], [3, 1]]))
    assert got[1] == pytest.approx(1 / 61 + 1 / 62)   # rank 1 in A, rank 2 in B
    assert got[2] == pytest.approx(1 / 62)            # only in A, rank 2
    assert got[3] == pytest.approx(1 / 63 + 1 / 61)   # rank 3 in A, rank 1 in B
    order = [d for d, _ in r.rrf([[1, 2, 3], [3, 1]])]
    assert order == [1, 3, 2]  # 0.03253 > 0.03226 > 0.01613


def test_rrf_tie_break_is_deterministic():
    # 7 and 9 each appear once at rank 1 in different lists: equal score, equal best rank -> lower id first
    assert [d for d, _ in r.rrf([[9], [7]])] == [7, 9]
    assert r.rrf([]) == []


def test_fts_query_or_joined_and_safe():
    q = r.fts_query("What is the penalty under B5.10.1 for 'drop table; --' ?")
    assert " | " in q and "'b5.10.1'" in q and "'penalty'" in q
    assert ";" not in q and "--" not in q.replace(" | ", "")
    assert r.fts_query("?!") == ""


def test_extract_cap_and_word_boundary():
    long = ("word " * 200).strip()
    e = r.extract(long)
    assert len(e) <= r.EXTRACT_CAP + 3 and e.endswith("...") and not e.endswith("wor...")
    assert r.extract("short  text\nhere") == "short text here"


def test_retrieve_refuses_sqlite():
    with pytest.raises(RuntimeError):
        r.retrieve("x", embed_query=lambda q: [0.0] * 384)


# ---------- SQL (live) ----------

live = pytest.mark.skipif(not DSN, reason="set STEWARDS_PG_DSN (local pgvector container) to run")


def vec(i: int) -> list[float]:
    v = [0.0] * 384
    v[i] = 1.0
    return v


class FakeReranker:
    """Scores by a fixed table so ordering is known: prefers the text containing 'GOLD'."""

    def score(self, query, texts):
        return [10.0 if "GOLD" in t else float(len(t)) / 1000 for t in texts]


@pytest.fixture
def cur():
    import psycopg2

    conn = psycopg2.connect(DSN)
    c = conn.cursor()
    c.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # TEMP tables shadow the real ones for this session only; rolled back at the end.
    c.execute("CREATE TEMP TABLE assistant_documentsource (id int primary key, url text, title text, doc_type text, "
              "year int, race text)")
    c.execute("CREATE TEMP TABLE assistant_docchunk (id int primary key, source_id int, text text, page int, "
              "article text, section text, embedding vector(384), search_vector tsvector)")
    c.execute("INSERT INTO assistant_documentsource VALUES "
              "(1,'https://fia/reg.pdf','Sporting 2026','sporting_regs',2026,''),"
              "(2,'https://fia/vegas.pdf','Vegas car 11','stewards_decision',2026,'las vegas grand prix'),"
              "(3,'https://fia/old.pdf','Sporting 2022','sporting_regs',2022,'')")
    rows = [  # id, source, text, article, vector index
        (1, 1, "A time penalty is imposed for causing a collision GOLD", "B1.9.5", 0),
        (2, 1, "Tyre pressures must be at the minimum before the start", "B6.3", 1),
        (3, 2, "Car 11 caused a collision and received a five second time penalty", "", 2),
        (4, 3, "Collision penalties in 2022 were similar", "B1.9", 3),
        (5, 1, "Formation lap behind the safety car", "B5.10", 4),
    ]
    for cid, sid, text, art, vi in rows:
        c.execute("INSERT INTO assistant_docchunk VALUES (%s,%s,%s,1,%s,'sec',%s::vector,to_tsvector('english',%s))",
                  (cid, sid, text, art, "[" + ",".join(map(str, vec(vi))) + "]", text))
    yield c
    conn.rollback()
    conn.close()


@live
def test_fts_and_vector_rank_and_filters(cur):
    assert r.fts_ids(cur, "collision penalty", 50)[:1] != []
    assert set(r.fts_ids(cur, "collision penalty", 50)) == {1, 3, 4}
    assert set(r.fts_ids(cur, "collision penalty", 50, year=2026)) == {1, 3}
    assert r.fts_ids(cur, "collision penalty", 50, doc_type="stewards_decision") == [3]
    assert r.fts_ids(cur, "collision penalty", 50, race="vegas") == [3]
    assert r.vector_ids(cur, vec(4), 3)[0] == 5
    assert r.vector_ids(cur, vec(4), 50, doc_type="stewards_decision") == [3]
    assert r.vector_ids(cur, vec(0), 50, year=2022) == [4]


@live
def test_search_fuses_and_reranks(cur):
    # query vector close to chunk 3 (vector side), text matches 1, 3, 4 (FTS side)
    hits = r.search(cur, "five second time penalty collision", vec(2), rerank=False)
    assert hits[0].chunk_id == 3 and hits[0].fts_rank == 1 and hits[0].vec_rank == 1  # both lists agree
    assert {h.chunk_id for h in hits} >= {1, 3, 4, 5}
    # the fake reranker overrides the fusion order
    hits = r.search(cur, "collision penalty", vec(2), reranker=FakeReranker())
    assert hits[0].chunk_id == 1
    # citation fields and the extract cap travel with every hit
    h = hits[0]
    assert (h.source_url, h.source_title, h.article, h.page) == ("https://fia/reg.pdf", "Sporting 2026", "B1.9.5", 1)
    assert len(h.extract) <= r.EXTRACT_CAP + 3
    assert len(r.search(cur, "collision penalty", vec(2), rerank=False, top_k=2)) == 2
    only = r.search(cur, "collision penalty", vec(2), year=2022, rerank=False)
    assert [x.chunk_id for x in only] == [4]
