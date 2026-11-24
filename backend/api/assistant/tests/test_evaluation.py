"""Metric functions against hand-computed values; gold matching; the judge with a fake runner; the question file."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.assistant import evaluation as ev
from api.assistant.llm import FakeRunner


def item(text="", doc_type="sporting_regs", year=2026, title=""):
    return SimpleNamespace(doc_type=doc_type, year=year, title=title.lower(), text=text)


# ---- recall@k and MRR ----

def test_recall_at_k_hand_computed():
    ranks = [1, 3, 9, None, 8]
    assert ev.recall_at_k(ranks, 8) == pytest.approx(3 / 5)   # ranks 1, 3, 8 are within 8
    assert ev.recall_at_k(ranks, 1) == pytest.approx(1 / 5)
    assert ev.recall_at_k(ranks, 50) == pytest.approx(4 / 5)
    assert ev.recall_at_k([], 8) == 0.0


def test_mrr_hand_computed():
    ranks = [1, 2, 4, None]
    assert ev.mrr(ranks) == pytest.approx((1 + 0.5 + 0.25 + 0) / 4)
    assert ev.mrr(ranks, cutoff=2) == pytest.approx((1 + 0.5) / 4)
    assert ev.mrr([None, None]) == 0.0


def test_first_gold_rank():
    gold = {"alts": [{"articles": ["B1.9.5"]}]}
    items = [item("B1.9.4 other"), item("x\nB1.9.5 Penalties"), item("B1.9.5 again")]
    assert ev.first_gold_rank(items, gold) == 2
    assert ev.first_gold_rank(items[:1], gold) is None
    assert ev.first_gold_rank(items, None) is None


# ---- gold matching ----

def test_article_must_start_a_paragraph_not_appear_in_a_cross_reference():
    gold = {"alts": [{"articles": ["4.1"]}]}
    assert ev.matches_gold(item("4.1 Minimum mass the car must weigh"), gold)
    assert ev.matches_gold(item("3.9 text\n4.1 Minimum mass"), gold)
    assert ev.matches_gold(item("4.1.1 a sub-paragraph of 4.1"), gold)        # a child paragraph counts
    assert not ev.matches_gold(item("as required by Article 4.1 of these regulations"), gold)
    assert not ev.matches_gold(item("14.1 Fire extinguishers"), gold)          # 14.1 is not 4.1
    assert not ev.matches_gold(item("4.10 something"), gold)


def test_alternatives_year_doctype_and_title():
    gold = {"alts": [{"doc_type": "sporting_regs", "year": 2026, "articles": ["B1.9.3"]},
                     {"doc_type": "sporting_regs", "year": 2022, "articles": ["54.2"]}]}
    assert ev.matches_gold(item("54.2 a) It shall be", year=2022), gold)
    assert not ev.matches_gold(item("54.2 a) It shall be", year=2024), gold)    # wrong year
    assert not ev.matches_gold(item("B1.9.3 Imposition", doc_type="technical_regs"), gold)
    dgold = {"alts": [{"doc_type": "stewards_decision", "title_contains": "car 11 - causing a collision"}]}
    assert ev.matches_gold(item("x", "stewards_decision", 2026, "Las Vegas Grand Prix - Infringement - Car 11 - Causing a collision with car 51"), dgold)
    assert not ev.matches_gold(item("x", "stewards_decision", 2026, "Australian GP - car 12"), dgold)


# ---- evidence-not-found precision / recall ----

def test_precision_recall_hand_computed():
    predicted = [True, True, False, False, True]   # the assistant said "not found"
    actual = [True, False, True, False, True]      # the question really is unanswerable
    pr = ev.precision_recall(predicted, actual)
    assert (pr["tp"], pr["fp"], pr["fn"]) == (2, 1, 1)
    assert pr["precision"] == pytest.approx(2 / 3) and pr["recall"] == pytest.approx(2 / 3) and pr["f1"] == pytest.approx(2 / 3)
    none = ev.precision_recall([False, False], [False, False])
    assert none["precision"] is None and none["recall"] is None


# ---- citation accuracy ----

def test_citation_accuracy_hit_and_precision():
    gold = {"alts": [{"doc_type": "sporting_regs", "year": 2026, "articles": ["B1.9.5"]}]}
    cites = [{"id": "E1", "doc_type": "sporting_regs", "year": 2026, "title": "2026 Sporting"},
             {"id": "E2", "doc_type": "sporting_regs", "year": 2022, "title": "2022 Sporting"}]
    texts = {"E1": "B1.9.5 Penalties for incidents", "E2": "B1.9.5 Penalties for incidents"}
    acc = ev.citation_accuracy(cites, texts, gold)
    assert acc == {"hit": True, "precision": 0.5, "n": 2}                     # the 2022 citation is the wrong year
    assert ev.citation_accuracy([], {}, gold) == {"hit": False, "precision": None, "n": 0}


# ---- judge ----

def test_judge_uses_the_runner_and_returns_a_verdict():
    runner = FakeRunner([{"correct": True, "reason": "states 5 seconds"}, {"correct": False, "reason": "x" * 500}])
    v = ev.judge(runner, "q?", "5 seconds", "A five second penalty [E1].")
    assert v == {"correct": True, "reason": "states 5 seconds"}
    assert "Reference answer: 5 seconds" in runner.plan_prompts[0] and "five second penalty" in runner.plan_prompts[0]
    assert len(ev.judge(runner, "q?", "r", "a")["reason"]) == 300
    assert runner.calls == 2                                                    # every judge call is counted against the budget


# ---- the question file ----

QUESTIONS = Path(ev.__file__).resolve().parent / "evals" / "questions.jsonl"


def test_question_file_shape_and_mix():
    qs = ev.load_questions(QUESTIONS)
    assert 90 <= len(qs) <= 110 and len({q["id"] for q in qs}) == len(qs)
    by = {}
    for q in qs:
        by.setdefault(q["type"], []).append(q)
        assert q["question"].strip().endswith(("?", "."))
        if q["type"] in ("rule", "precedent", "notes"):
            assert q["gold"]["alts"] and q["answerable"] is True and q["reference"]
        if q["type"] == "race_data":
            assert q["expected_tools"] and q["year"] and q["round"]
        if q["type"] == "unanswerable":
            assert q["answerable"] is False and q["gold"] is None
    assert set(by) == {"rule", "precedent", "notes", "race_data", "unanswerable"}
    assert len(by["rule"]) >= 45 and len(by["precedent"]) >= 20 and len(by["race_data"]) >= 8 and len(by["unanswerable"]) >= 10


def test_snapshot_hash_is_order_independent():
    assert ev.snapshot_hash(["b", "a"]) == ev.snapshot_hash(["a", "b"]) != ev.snapshot_hash(["a"])
