"""Postgres + pgvector checks. Skipped unless STEWARDS_PG_DSN points at a database with the `vector` extension
(local container `f1-stewards-pg` on port 5433, never Neon). Uses TEMP tables in a rolled-back transaction."""
import os

import pytest

DSN = os.environ.get("STEWARDS_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="set STEWARDS_PG_DSN (local pgvector container) to run")


def test_vector_cosine_order_and_tsvector_match():
    import psycopg2

    conn = psycopg2.connect(DSN)
    try:
        cur = conn.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute("CREATE TEMP TABLE t (id int, embedding vector(384), sv tsvector, txt text)")
        a = "[" + ",".join(["1"] + ["0"] * 383) + "]"
        b = "[" + ",".join(["0", "1"] + ["0"] * 382) + "]"
        cur.execute("INSERT INTO t VALUES (1, %s, to_tsvector('english', 'time penalty for causing a collision'), 'x'), "
                    "(2, %s, to_tsvector('english', 'tyre pressure limits'), 'y')", (a, b))
        cur.execute("CREATE INDEX ON t USING hnsw (embedding vector_cosine_ops)")
        cur.execute("SELECT id FROM t ORDER BY embedding <=> %s LIMIT 1", (a,))
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT id FROM t WHERE sv @@ plainto_tsquery('english', 'penalties collision')")
        assert [r[0] for r in cur.fetchall()] == [1]
    finally:
        conn.rollback()
        conn.close()
