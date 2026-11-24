"""Evaluation of the stewards assistant: gold matching, retrieval metrics, end-to-end metrics, the LLM judge.

Pure functions (no DB, no model) so the metrics can be tested against hand-computed values. The management command
`assistant_eval` wires them to the database and the real runner.

Gold format (evals/questions.jsonl): `gold.alts` is a list of acceptable places; a hit matches when it matches ANY
alt. An alt may give `doc_type`, `year`, `articles` (the chunk's text must contain a paragraph that starts with one of
those article numbers), and `title_contains` (lower-case substring of the source title, used for stewards' decisions).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


def _has_article(text: str, article: str) -> bool:
    return re.search(r"(?:^|\n)\s*" + re.escape(article) + r"(?:[ .)]|$)", text) is not None


def alt_matches(item: Any, alt: dict) -> bool:
    """`item` needs .doc_type .year .title .text (a Hit with source_title, or a chunk)."""
    if alt.get("doc_type") and getattr(item, "doc_type") != alt["doc_type"]:
        return False
    if alt.get("year") and getattr(item, "year") != alt["year"]:
        return False
    if alt.get("title_contains") and alt["title_contains"] not in (getattr(item, "title") or "").lower():
        return False
    arts = alt.get("articles")
    if arts and not any(_has_article(getattr(item, "text"), a) for a in arts):
        return False
    return True


def matches_gold(item: Any, gold: dict | None) -> bool:
    return bool(gold) and any(alt_matches(item, a) for a in gold["alts"])


def first_gold_rank(items: list, gold: dict | None) -> int | None:
    """1-based rank of the first matching item, or None."""
    for i, it in enumerate(items, start=1):
        if matches_gold(it, gold):
            return i
    return None


def recall_at_k(ranks: Iterable[int | None], k: int) -> float:
    ranks = list(ranks)
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks) if ranks else 0.0


def mrr(ranks: Iterable[int | None], cutoff: int | None = None) -> float:
    ranks = list(ranks)
    vals = [(1.0 / r) if r is not None and (cutoff is None or r <= cutoff) else 0.0 for r in ranks]
    return sum(vals) / len(vals) if vals else 0.0


def precision_recall(predicted: list[bool], actual: list[bool]) -> dict:
    """Binary precision/recall/F1 of `predicted` against `actual` (positive = True)."""
    tp = sum(1 for p, a in zip(predicted, actual) if p and a)
    fp = sum(1 for p, a in zip(predicted, actual) if p and not a)
    fn = sum(1 for p, a in zip(predicted, actual) if not p and a)
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else (0.0 if prec is not None and rec is not None else None)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": prec, "recall": rec, "f1": f1}


@dataclass
class CitationLike:
    doc_type: str
    year: int | None
    title: str
    text: str


def citation_accuracy(cites: list[dict], evidence_text_by_id: dict[str, str], gold: dict | None) -> dict:
    """Per question: `hit` = at least one citation matches the gold; `precision` = share of citations that match."""
    items = [CitationLike(c.get("doc_type") or "", c.get("year"), (c.get("title") or "").lower(),
                          evidence_text_by_id.get(c["id"], c.get("extract", ""))) for c in cites]
    ok = [matches_gold(i, gold) for i in items]
    return {"hit": any(ok), "precision": (sum(ok) / len(ok)) if ok else None, "n": len(ok)}


# ---------- corpus snapshot ----------

def snapshot_hash(shas: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(shas)).encode()).hexdigest()


# ---------- LLM judge ----------

JUDGE_SCHEMA = {"type": "object", "properties": {"correct": {"type": "boolean"}, "reason": {"type": "string"}},
                "required": ["correct", "reason"]}
JUDGE_SYSTEM = (
    "You grade answers of a Formula 1 rules assistant. Given a question, a reference answer written from the FIA documents "
    "and the assistant's answer, decide whether the assistant's answer is correct: it must state the same facts as the "
    "reference (numbers, penalties, article content) and must not contradict it. Extra detail is fine; a missing key fact or "
    "a wrong number is not. If the reference says \"Evidence not found.\", the answer is correct only if it also says the "
    "evidence was not found. Reply with the JSON object only."
)


def judge_prompt(question: str, reference: str, answer: str) -> str:
    return f"Question: {question}\n\nReference answer: {reference}\n\nAssistant's answer: {answer}"


def judge(runner, question: str, reference: str, answer: str) -> dict:
    out = runner.plan(judge_prompt(question, reference, answer), JUDGE_SYSTEM, JUDGE_SCHEMA)
    return {"correct": bool(out.get("correct")), "reason": str(out.get("reason", ""))[:300]}


def load_questions(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
