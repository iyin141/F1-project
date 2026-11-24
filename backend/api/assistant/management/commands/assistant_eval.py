"""Evaluate the stewards assistant against evals/questions.jsonl.

  assistant_eval snapshot              write evals/snapshot.json (the ingested sources, with sha256) for the question set
  assistant_eval check-gold            every gold citation must exist in the snapshot corpus
  assistant_eval retrieval             recall@8 and MRR for FTS, vector, RRF, RRF+rerank (700 chars) and (full text); no LLM
  assistant_eval e2e --sample 12       end to end on a sample: citation accuracy, LLM-judged correctness, evidence-not-found

Results are written to evals/results/ with the corpus snapshot hash and the configuration. `e2e` calls the real `claude`
CLI (about 5 calls per question) and stops at --max-calls.
"""
import json
import statistics
import subprocess
import time
from functools import partial
from pathlib import Path
from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from api.assistant import evaluation as ev
from api.assistant import retrieval as rt
from api.assistant.models import DocChunk, DocumentSource

EVALS = Path(__file__).resolve().parents[2] / "evals"
K = 8


def _git_head():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _item(row):
    return SimpleNamespace(doc_type=row["doc_type"], year=row["year"], title=(row["title"] or "").lower(), text=row["text"])


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, p):
        p.add_argument("action", choices=["snapshot", "check-gold", "retrieval", "e2e"])
        p.add_argument("--questions", default=str(EVALS / "questions.jsonl"))
        p.add_argument("--snapshot", default=str(EVALS / "snapshot.json"))
        p.add_argument("--out", default=str(EVALS / "results"))
        p.add_argument("--pool", type=int, default=rt.POOL)
        p.add_argument("--rerank-chars", type=int, default=rt.DEFAULT_RERANK_CHARS)
        p.add_argument("--sample", type=int, default=12)
        p.add_argument("--max-calls", type=int, default=60)
        p.add_argument("--ids", nargs="*", help="e2e: explicit question ids instead of the stratified sample")

    # ------------------------------------------------------------------
    def handle(self, *a, action, **o):
        getattr(self, "do_" + action.replace("-", "_"))(o)

    def _source_ids(self, o):
        snap = json.loads(Path(o["snapshot"]).read_text(encoding="utf-8"))
        by_sha = {s.sha256: s.pk for s in DocumentSource.objects.filter(sha256__in=[x["sha256"] for x in snap["sources"]])}
        missing = [x["url"] for x in snap["sources"] if x["sha256"] not in by_sha]
        if missing:
            raise CommandError(f"{len(missing)} snapshot sources are not in this database, e.g. {missing[0]}")
        return snap, sorted(by_sha.values())

    def _write(self, o, name, payload):
        out = Path(o["out"])
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{time.strftime('%Y%m%d-%H%M%S')}_{name}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self.stdout.write(f"saved {path}")

    # ------------------------------------------------------------------
    def do_snapshot(self, o):
        srcs = list(DocumentSource.objects.filter(ingested_at__isnull=False).order_by("pk"))
        sources = [{"sha256": s.sha256, "doc_type": s.doc_type, "year": s.year, "title": s.title, "url": s.url,
                    "chunks": s.chunks.count()} for s in srcs]
        payload = {"written": time.strftime("%Y-%m-%d %H:%M:%S"), "snapshot_hash": ev.snapshot_hash(x["sha256"] for x in sources),
                   "sources": sources}
        Path(o["snapshot"]).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self.stdout.write(f"{len(sources)} sources, {sum(x['chunks'] for x in sources)} chunks, hash {payload['snapshot_hash'][:16]}")

    def do_check_gold(self, o):
        snap, ids = self._source_ids(o)
        chunks = [SimpleNamespace(doc_type=c.source.doc_type, year=c.source.year, title=c.source.title.lower(), text=c.text)
                  for c in DocChunk.objects.filter(source_id__in=ids).select_related("source")]
        bad = []
        for q in ev.load_questions(o["questions"]):
            if q.get("gold") and not any(ev.matches_gold(c, q["gold"]) for c in chunks):
                bad.append(q["id"])
        self.stdout.write(f"gold citations missing from the snapshot corpus: {bad or 'none'}")
        if bad:
            raise CommandError("fix the gold of: " + ", ".join(bad))

    # ------------------------------------------------------------------
    def do_retrieval(self, o):
        from api.assistant.embeddings import embed_query

        snap, ids = self._source_ids(o)
        qs = [q for q in ev.load_questions(o["questions"]) if q.get("gold")]
        reranker = rt.FastEmbedReranker(max_chars=0)
        chars, pool = o["rerank_chars"], o["pool"]
        methods = ["fts", "vector", "rrf", "rrf+rerank%d" % chars, "rrf+rerank_full", "rrf+rerank%d+year_filter" % chars]
        ranks = {m: {} for m in methods}
        ms = {m: [] for m in methods}
        for n, q in enumerate(qs, 1):
            qvec = embed_query(q["question"])
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute("SET LOCAL hnsw.ef_search = 100")

                def lists(year=None):
                    t = time.time()
                    f = rt.fts_ids(cur, q["question"], rt.K_EACH, year=year, source_ids=ids)
                    v = rt.vector_ids(cur, qvec, rt.K_EACH, year=year, source_ids=ids)
                    return f, v, [i for i, _ in rt.rrf([f, v])], (time.time() - t) * 1000

                f, v, fused, base_ms = lists()
                rows = rt._load(cur, list({*f, *v, *fused}))
                fy, vy, fused_y, base_y = lists(q["year"]) if q.get("year") else (None, None, None, 0)
                if fused_y:
                    rows.update(rt._load(cur, [i for i in fused_y if i not in rows]))
            item = lambda i: _item(rows[i])  # noqa: E731
            gold = q["gold"]
            ranks["fts"][q["id"]] = ev.first_gold_rank([item(i) for i in f], gold)
            ranks["vector"][q["id"]] = ev.first_gold_rank([item(i) for i in v], gold)
            ranks["rrf"][q["id"]] = ev.first_gold_rank([item(i) for i in fused], gold)
            ms["fts"].append(base_ms), ms["vector"].append(base_ms), ms["rrf"].append(base_ms)

            def rerank(cand, trunc):
                texts = [rows[i]["text"][:trunc] if trunc else rows[i]["text"] for i in cand]
                t = time.time()
                sc = reranker.score(q["question"], texts)
                order = [i for _, i in sorted(zip(sc, cand), key=lambda x: -x[0])]
                return order, (time.time() - t) * 1000 + base_ms

            order, t1 = rerank(fused[:pool], chars)
            ranks[methods[3]][q["id"]] = ev.first_gold_rank([item(i) for i in order], gold)
            ms[methods[3]].append(t1)
            order, t2 = rerank(fused[:pool], 0)
            ranks[methods[4]][q["id"]] = ev.first_gold_rank([item(i) for i in order], gold)
            ms[methods[4]].append(t2)
            if q.get("year"):
                order, t3 = rerank(fused_y[:pool], chars)
                ranks[methods[5]][q["id"]] = ev.first_gold_rank([item(i) for i in order], gold)
                ms[methods[5]].append(t3 - base_ms + base_y)
            if n % 10 == 0:
                self.stdout.write(f"{n}/{len(qs)} questions")
        summary, by_type = {}, {}
        for m in methods:
            r = ranks[m]
            summary[m] = {"n": len(r), "recall@8": round(ev.recall_at_k(r.values(), K), 4), "mrr": round(ev.mrr(r.values()), 4),
                          "recall@20": round(ev.recall_at_k(r.values(), 20), 4), "median_ms": round(statistics.median(ms[m]) if ms[m] else 0)}
            for t in {q["type"] for q in qs}:
                ids_t = [q["id"] for q in qs if q["type"] == t and q["id"] in r]
                by_type.setdefault(m, {})[t] = {"n": len(ids_t), "recall@8": round(ev.recall_at_k([r[i] for i in ids_t], K), 4),
                                                "mrr": round(ev.mrr([r[i] for i in ids_t]), 4)}
        self.stdout.write(f"{'method':32} {'n':>4} {'R@8':>7} {'R@20':>7} {'MRR':>7} {'ms':>7}")
        for m, s in summary.items():
            self.stdout.write(f"{m:32} {s['n']:>4} {s['recall@8']:>7.3f} {s['recall@20']:>7.3f} {s['mrr']:>7.3f} {s['median_ms']:>7}")
        self._write(o, "retrieval", {
            "corpus_snapshot": {"hash": snap["snapshot_hash"], "sources": len(snap["sources"])},
            "config": {"pool": pool, "rerank_chars": chars, "k_each": rt.K_EACH, "rrf_k": rt.RRF_K, "reranker": reranker.model_name,
                       "embedding": "BAAI/bge-small-en-v1.5 (fastembed INT8)", "git": _git_head()},
            "summary": summary, "by_type": by_type, "ranks": ranks,
            "missed_everywhere": [q["id"] for q in qs if all(ranks[m].get(q["id"]) is None for m in methods)],
        })

    # ------------------------------------------------------------------
    def do_e2e(self, o):
        from api.assistant.agent import run_agent
        from api.assistant.llm import ClaudeRunner

        snap, ids = self._source_ids(o)
        allq = {q["id"]: q for q in ev.load_questions(o["questions"])}
        if o["ids"]:
            sample = [allq[i] for i in o["ids"]]
        else:  # stratified, deterministic: every k-th question of each answerable-in-corpus type
            want = {"rule": 5, "precedent": 3, "notes": 1, "unanswerable": max(o["sample"] - 9, 0)}
            sample = []
            for t, n in want.items():
                pool_t = [q for q in allq.values() if q["type"] == t]
                step = max(len(pool_t) // max(n, 1), 1)
                sample += pool_t[::step][:n]
        runner = ClaudeRunner()
        retrieve = partial(rt.retrieve, source_ids=ids)
        results = []
        for q in sample:
            if runner.calls >= o["max_calls"] - 6:
                self.stdout.write(f"call budget reached ({runner.calls}); stopping before {q['id']}")
                break
            t, calls0, cost0 = time.time(), runner.calls, runner.cost_usd
            events = []
            res = run_agent(q["question"], q.get("year"), None, runner=runner, emit=events.append, retrieve=retrieve)
            if not res:
                results.append({"id": q["id"], "type": q["type"], "error": [e for e in events if e["type"] == "error"][-1:]})
                continue
            cites = next((e["citations"] for e in events if e["type"] == "citations"), [])
            texts = {e.id: e.text for e in res["_evidence"]}
            acc = ev.citation_accuracy(cites, texts, q.get("gold")) if q.get("answerable") else None
            verdict = ev.judge(runner, q["question"], q["reference"], res["answer"])
            results.append({"id": q["id"], "type": q["type"], "answerable": q["answerable"], "not_found": res["not_found"],
                            "judge": verdict, "citation": acc,
                            "cited": [{"id": c["id"], "year": c.get("year"), "doc_type": c.get("doc_type"), "article": c.get("article"),
                                       "page": c.get("page"), "title": c.get("title")} for c in cites], "grounded": res["grounded"], "n_citations": res["citations"],
                            "rounds": res["rounds"], "tools_used": res["tools_used"], "evidence_items": res["evidence_items"],
                            "evidence_used": res.get("evidence_used"), "long_quotes": res["long_quotes"],
                            "seconds": round(time.time() - t, 1), "calls": runner.calls - calls0,
                            "cost_usd": round(runner.cost_usd - cost0, 4), "answer": res["answer"]})
            r = results[-1]
            self.stdout.write(f"{q['id']} {q['type']:12} correct={verdict['correct']!s:5} nf={r['not_found']!s:5} cit_hit="
                              f"{(acc or {}).get('hit')} rounds={r['rounds']} calls={r['calls']} ${r['cost_usd']} {r['seconds']}s")
        ok = [r for r in results if "judge" in r]
        answerable = [r for r in ok if r["answerable"]]
        nf = ev.precision_recall([r["not_found"] for r in ok], [not r["answerable"] for r in ok])
        summary = {
            "questions": len(ok), "calls": runner.calls, "cost_usd": round(runner.cost_usd, 4),
            "answer_correctness": round(sum(r["judge"]["correct"] for r in ok) / len(ok), 3) if ok else None,
            "answerable_correctness": round(sum(r["judge"]["correct"] for r in answerable) / len(answerable), 3) if answerable else None,
            "citation_hit_rate": round(sum(r["citation"]["hit"] for r in answerable) / len(answerable), 3) if answerable else None,
            "citation_precision": round(statistics.mean(r["citation"]["precision"] for r in answerable if r["citation"]["precision"] is not None), 3)
            if any(r["citation"]["precision"] is not None for r in answerable) else None,
            "evidence_not_found": nf, "median_seconds": statistics.median(r["seconds"] for r in ok) if ok else None,
            "mean_rounds": round(statistics.mean(r["rounds"] for r in ok), 2) if ok else None,
        }
        self.stdout.write(json.dumps(summary, indent=2))
        self._write(o, "e2e", {"corpus_snapshot": {"hash": snap["snapshot_hash"], "sources": len(snap["sources"])},
                               "config": {"planner": runner.planner_model, "answer": runner.answer_model,
                                          "evidence_cap": 10, "git": _git_head()},
                               "summary": summary, "results": results})
