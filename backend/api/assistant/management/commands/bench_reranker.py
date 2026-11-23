"""Time a cross-encoder on real corpus candidates (run this on the target machine, e.g. the VM).

  python manage.py bench_reranker --model Xenova/ms-marco-MiniLM-L-12-v2 --pairs 30 50
"""
import time

from django.core.management.base import BaseCommand

from api.assistant import retrieval

QUESTIONS = [
    "What is the penalty for causing a collision?",
    "How does the formation lap behind the safety car work?",
    "When is a driver given a drive-through penalty?",
]


class Command(BaseCommand):
    help = "Measure reranker latency (ms per query) for N query/passage pairs."

    def add_arguments(self, p):
        p.add_argument("--model", default=retrieval.DEFAULT_RERANKER)
        p.add_argument("--pairs", type=int, nargs="+", default=[30, 50])
        p.add_argument("--runs", type=int, default=3)
        p.add_argument("--max-chars", type=int, default=None, help="truncate each passage (0 = none)")

    def handle(self, *a, model, pairs, runs, max_chars, **kw):
        t = time.time()
        rr = retrieval.FastEmbedReranker(model, max_chars)
        rr.score("warm up", ["warm up text"])  # loads the model
        self.stdout.write(f"{model}: load {time.time() - t:.1f}s, max_chars={rr.max_chars}")
        for n in pairs:
            ms = []
            for q in QUESTIONS * runs:
                texts = [h.text for h in retrieval.retrieve(q, rerank=False, pool=n, top_k=n)]
                t = time.time()
                rr.score(q, texts)
                ms.append((time.time() - t) * 1000 / max(len(texts), 1) * n)  # normalised to n pairs
            ms.sort()
            self.stdout.write(f"  {n} pairs: median {ms[len(ms) // 2]:.0f} ms, max {ms[-1]:.0f} ms (n={len(ms)})")
