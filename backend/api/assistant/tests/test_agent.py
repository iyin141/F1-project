"""The agent with a fake runner and fake retrieval: planning, the round bound, citations, evidence-not-found."""
import pytest

from api.assistant import agent, tools
from api.assistant.llm import AuthExpired, BadOutput, FakeRunner
from api.assistant.retrieval import Hit


def hit(i=1, article="B1.9.5", page=14, text="B1.9.5 In the event of an incident the stewards may impose a time penalty of 5 seconds."):
    return Hit(chunk_id=i, text=text, extract=text[:300], page=page, article=article, section="B1.9 Penalties",
               source_url=f"https://www.fia.com/system/files/documents/reg{i}.pdf", source_title="2026 F1 Sporting Regulations",
               doc_type="sporting_regs", year=2026, race="", score=1.0)


def retriever(hits_by_call=None, calls=None):
    calls = calls if calls is not None else []

    def fn(question, **kw):
        calls.append((question, kw))
        return list((hits_by_call or [[hit()]])[min(len(calls) - 1, len(hits_by_call or [[hit()]]) - 1)])

    return fn


def search(q="time penalty collision", **kw):
    return {"action": "tools", "tool_calls": [{"tool": "search_documents", "args": {"query": q, **kw}}]}


ANSWER = {"action": "answer"}


def run(plans, answer="A 5 second penalty applies [E1].", retrieve=None, question="What penalty for a collision?", year=None, rnd=None):
    events = []
    runner = FakeRunner(plans, answer)
    res = agent.run_agent(question, year, rnd, runner=runner, emit=events.append, retrieve=retrieve or retriever())
    return runner, events, res


def types(events):
    return [e["type"] for e in events]


# ---- the happy path and event order ----

def test_plan_search_answer_event_order_and_citations():
    runner, events, res = run([search(), ANSWER])
    t = types(events)
    assert t[0] == "status" and events[0]["phase"] == "solving"
    phases = [e["phase"] for e in events if e["type"] == "status"]
    assert phases == ["solving", "searching", "solving", "composing"]
    assert t[-2:] == ["citations", "done"] and t.count("token") >= 3
    assert all(x == "token" for x in t[t.index("token"):-2])         # tokens are contiguous, then citations, then done
    cites = next(e for e in events if e["type"] == "citations")["citations"]
    assert len(cites) == 1
    c = cites[0]
    assert (c["id"], c["article"], c["page"], c["n"]) == ("E1", "B1.9.5", 14, 1)
    assert c["url"].startswith("https://www.fia.com/") and len(c["extract"]) <= 300
    done = events[-1]
    assert done["grounded"] and not done["not_found"] and done["rounds"] == 1 and done["tools_used"] == ["search_documents"]
    assert "[E1]" in runner.answer_prompts[0] and "B1.9.5" in runner.answer_prompts[0]


def test_streamed_tokens_rebuild_the_answer():
    _, events, _ = run([search(), ANSWER], answer="Five seconds [E1].")
    assert "".join(e["text"] for e in events if e["type"] == "token") == "Five seconds [E1]."


# ---- the round bound ----

def test_at_most_four_tool_rounds_then_forced_answer():
    calls = []
    plans = [search(f"query number {i}") for i in range(10)]
    runner, events, res = run(plans, retrieve=retriever(calls=calls))
    assert len(runner.plan_prompts) == agent.MAX_ROUNDS == 4        # the planner is not asked a 5th time
    assert len(calls) == 4 and res["rounds"] == 4
    assert types(events)[-1] == "done" and res["answer"]


def test_repeated_call_is_not_executed_twice():
    calls = []
    runner, events, _ = run([search("same"), search("same"), ANSWER], retrieve=retriever(calls=calls))
    assert len(calls) == 1
    assert "already called" in runner.plan_prompts[2]


def test_calls_per_round_are_capped():
    many = {"action": "tools", "tool_calls": [{"tool": "search_documents", "args": {"query": f"query {i}"}} for i in range(8)]}
    calls = []
    run([many, ANSWER], retrieve=retriever(calls=calls))
    assert len(calls) == agent.MAX_CALLS_PER_ROUND


# ---- validation of what the planner asks for ----

@pytest.mark.parametrize("bad, fragment", [
    ({"tool": "drop_database", "args": {}}, "unknown tool"),
    ({"tool": "search_documents", "args": {}}, "query"),
    ({"tool": "search_documents", "args": {"query": "ok query", "year": 1999}}, "1999"),
    ({"tool": "get_incidents", "args": {}}, "needs y and r"),
    ({"tool": "get_chaos", "args": {"y": 2025, "r": 99}}, "99"),
    ({"tool": "search_documents", "args": {"query": "ok query", "sql": "x"}}, "sql"),
])
def test_bad_tool_calls_become_observations_not_executions(bad, fragment):
    calls = []
    runner, events, _ = run([{"action": "tools", "tool_calls": [bad]}, ANSWER], retrieve=retriever(calls=calls))
    assert calls == []
    assert fragment in runner.plan_prompts[1]


def test_request_year_and_round_fill_in_missing_arguments(monkeypatch):
    seen = []
    monkeypatch.setattr("api.services.persistence.get_persisted_incidents_data",
                        lambda y, r, s, **kw: seen.append((y, r, s)) or {"data": [{"msg": "5 SECOND TIME PENALTY CAR 11"}]})
    plan = {"action": "tools", "tool_calls": [{"tool": "get_incidents", "args": {}}]}
    runner, events, res = run([plan, ANSWER], answer="Car 11 was penalised [E1].", year=2026, rnd=22)
    assert seen == [(2026, 22, "R")]
    cite = next(e for e in events if e["type"] == "citations")["citations"][0]
    assert cite["kind"] == "data" and cite["year"] == 2026 and cite["url"] == ""


def test_get_chaos_and_track_status_use_services_in_process(monkeypatch):
    from api.chaos import service as chaos

    monkeypatch.setattr(chaos, "select_run", lambda y, r: (object(), {"model": "beta_binomial"}))
    monkeypatch.setattr(chaos, "race_payload", lambda y, r, run, block: {"targets": {"safety_car": {"probability": 0.4}}, "chaos_index": 1.2, "model": block, "meta": {}})
    monkeypatch.setattr("api.services.persistence.get_persisted_track_status_data", lambda y, r, s, **kw: None)
    plan = {"action": "tools", "tool_calls": [{"tool": "get_chaos", "args": {"y": 2025, "r": 5}}, {"tool": "get_track_status", "args": {"y": 2025, "r": 5}}]}
    runner, events, res = run([plan, ANSWER], answer="Safety car probability was 0.4 [E1].")
    assert res["tools_used"] == ["get_chaos"]                          # track status had no data: nothing invented
    assert "returned nothing" in runner.plan_prompts[1]
    assert "0.4" in runner.answer_prompts[0]


def test_similar_past_decisions_searches_stewards_decisions_only():
    calls = []
    plan = {"action": "tools", "tool_calls": [{"tool": "similar_past_decisions", "args": {"offence": "causing a collision", "n": 3}}]}
    run([plan, ANSWER], retrieve=retriever(calls=calls))
    assert calls[0][1]["doc_type"] == "stewards_decision" and calls[0][1]["top_k"] == 3


# ---- evidence not found ----

def test_no_evidence_means_evidence_not_found_without_a_model_call():
    runner, events, res = run([search(), ANSWER], retrieve=lambda q, **kw: [])
    assert res["not_found"] and res["answer"] == "Evidence not found."
    assert runner.answer_prompts == []                                  # no answer call spent
    assert next(e for e in events if e["type"] == "citations")["citations"] == []
    assert types(events)[-1] == "done"


def test_model_reporting_missing_evidence_gets_no_citations():
    _, events, res = run([search(), ANSWER], answer="Evidence not found. I searched the 2026 sporting regulations for DRS.")
    assert res["not_found"] and res["citations"] == 0 and res["grounded"]


# ---- citation formatting and quote cap ----

def test_build_citations_orders_dedupes_and_flags_unknown():
    ev = [tools.Evidence(id=f"E{i}", tool="search_documents", kind="document", label=f"doc {i}", text="t", extract="x" * 400,
                         url=f"https://fia/{i}", title=f"Doc {i}", page=i, article=f"B{i}") for i in (1, 2, 3)]
    cites, unknown = agent.build_citations("A [E3]. B [E1, E3] and [E9][E2].", ev)
    assert [c["id"] for c in cites] == ["E3", "E1", "E2"] and [c["n"] for c in cites] == [1, 2, 3]
    assert unknown == ["E9"]
    assert cites[0]["page"] == 3 and cites[0]["article"] == "B3" and cites[0]["url"] == "https://fia/3"


def test_answer_with_an_unknown_citation_is_not_grounded():
    _, events, res = run([search(), ANSWER], answer="Five seconds [E1] and also [E7].")
    assert res["invalid_citations"] == ["E7"] and not res["grounded"]


def test_answer_without_any_citation_is_not_grounded():
    _, _, res = run([search(), ANSWER], answer="Five seconds, I believe.")
    assert not res["grounded"] and res["citations"] == 0


def test_quotes_over_300_characters_are_counted():
    assert agent.long_quotes('He said "' + "x" * 301 + '" ok') == 1
    assert agent.long_quotes('"' + "x" * 300 + '"') == 0
    assert agent.long_quotes("“" + "y" * 400 + "”") == 1
    _, _, res = run([search(), ANSWER], answer='Rule: "' + "z" * 350 + '" [E1]')
    assert res["long_quotes"] == 1
    long_text = "word " * 200
    h = hit(text=long_text)
    assert len(tools._doc_evidence(h, "E1", "search_documents").citation()["extract"]) <= 300


# ---- failures ----

def test_planner_bad_json_twice_falls_back_to_a_search_then_not_found_when_nothing_is_found():
    calls = []
    runner, events, res = run([BadOutput("x"), ANSWER], answer="never used", retrieve=lambda q, **kw: calls.append(q) or [])
    assert calls == ["What penalty for a collision?"]                       # round one was forced to search the question
    assert res["not_found"] and runner.answer_prompts == []


def test_a_first_round_answer_is_turned_into_a_search():
    """Regression from the live eval: the planner answered a rules question without calling any tool."""
    calls = []
    runner, events, res = run([ANSWER, ANSWER], retrieve=retriever(calls=calls))
    assert len(calls) == 1 and calls[0][0] == "What penalty for a collision?"
    assert not res["not_found"] and res["rounds"] == 1 and runner.answer_prompts
    assert "searching" in [e["phase"] for e in events if e["type"] == "status"]


def test_a_first_round_with_no_calls_is_turned_into_a_search():
    calls = []
    run([{"action": "tools", "tool_calls": []}, ANSWER], retrieve=retriever(calls=calls))
    assert len(calls) == 1


def test_a_later_round_answer_is_honoured():
    calls = []
    run([search(), ANSWER], retrieve=retriever(calls=calls))
    assert len(calls) == 1


def test_auth_expired_ends_with_an_error_event_and_no_done():
    events = []
    runner = FakeRunner([AuthExpired("expired")])
    agent.run_agent("q?", None, None, runner=runner, emit=events.append, retrieve=retriever())
    assert types(events)[-1] == "error" and events[-1]["code"] == "auth_expired" and "done" not in types(events)


def test_tool_crash_is_reported_to_the_planner_not_fatal():
    def boom(q, **kw):
        raise RuntimeError("db down")

    runner, events, res = run([search(), ANSWER], retrieve=boom)
    assert "failed: RuntimeError" in runner.plan_prompts[1] and res["not_found"]


# ---- the answer evidence cap ----

def many_hits(n, tag="a"):
    return [hit(i + 1, article=f"B{tag}.{i}", text=f"B{tag}.{i} rule text number {i} for {tag}.") for i in range(n)]


def test_answer_prompt_is_capped_to_ten_items_best_ranked_first():
    plans = [{"action": "tools", "tool_calls": [{"tool": "search_documents", "args": {"query": "first query"}},
                                                  {"tool": "search_documents", "args": {"query": "second query"}}]}, ANSWER]
    n = {"i": 0}

    def fn(q, **kw):
        n["i"] += 1
        return many_hits(9, "x" if n["i"] == 1 else "y")

    runner, events, res = run(plans, answer="See [E1] and [E2].", retrieve=fn)
    prompt = runner.answer_prompts[0]
    assert prompt.count("(document)") == agent.MAX_ANSWER_EVIDENCE == 10
    assert res["evidence_items"] == 18 and res["evidence_used"] == 10
    # round robin: the top 5 of each call, not 9 of the first and 1 of the second
    assert "Bx.4 " in prompt and "By.4 " in prompt and "Bx.8 " not in prompt and "By.8 " not in prompt


def test_select_for_answer_keeps_data_items_and_original_order():
    def ev(i, rank, kind="document"):
        return tools.Evidence(id=f"E{i}", tool="t", kind=kind, label="l", text="t", meta={"rank": rank})

    items = [ev(1, 3), ev(2, 0, "data"), ev(3, 1), ev(4, 2), ev(5, 0)]
    got = agent.select_for_answer(items, cap=3)
    assert [e.id for e in got] == ["E2", "E3", "E5"]          # ranks 0, 0, 1 kept, in id order


def test_citing_an_item_the_model_never_saw_is_flagged():
    plan = {"action": "tools", "tool_calls": [{"tool": "search_documents", "args": {"query": "a lot of hits"}}]}
    _, _, res = run([plan, ANSWER], answer="Rule [E1] and invented [E12].", retrieve=lambda q, **kw: many_hits(14))
    assert res["evidence_used"] == 10 and res["invalid_citations"] == ["E12"] and not res["grounded"]


# ---- regression: evidence ids must be unique (found by the 3d live eval: every hit of one call was "E1") ----

def test_every_hit_of_one_call_gets_its_own_id_and_citations_point_at_the_right_document():
    hits = [hit(i, article=f"B1.9.{i}", page=10 + i, text=f"B1.9.{i} rule number {i} text") for i in range(1, 5)]
    for i, h in enumerate(hits, 1):
        h.source_title = f"Document {i}"
    runner, events, res = run([search(), ANSWER], answer="Rule three [E3] and rule one [E1].", retrieve=lambda q, **kw: hits)
    prompt = runner.answer_prompts[0]
    assert [f"[E{i}] (document)" in prompt for i in (1, 2, 3, 4)] == [True] * 4
    cites = next(e for e in events if e["type"] == "citations")["citations"]
    assert [(c["id"], c["title"], c["article"], c["page"]) for c in cites] == [("E3", "Document 3", "B1.9.3", 13), ("E1", "Document 1", "B1.9.1", 11)]
    assert res["grounded"] and res["invalid_citations"] == []


def test_ids_keep_counting_across_calls_and_rounds():
    calls = {"n": 0}

    def fn(q, **kw):
        calls["n"] += 1
        return [hit(calls["n"] * 10 + j, article=f"B{calls['n']}.{j}") for j in range(2)]

    two = {"action": "tools", "tool_calls": [{"tool": "search_documents", "args": {"query": "first query"}},
                                             {"tool": "search_documents", "args": {"query": "second query"}}]}
    runner, _, res = run([two, search("third query"), ANSWER], retrieve=fn, answer="x [E6]")
    assert res["evidence_items"] == 6
    assert all(f"[E{i}] (document)" in runner.answer_prompts[0] for i in range(1, 7))


# ---- year inference and the rerank default (3d findings) ----

@pytest.mark.parametrize("q, year", [
    ("What is the minimum mass in the 2023 technical regulations?", 2023),
    ("Under the 2025 rules and the 2025 sporting regulations, what applies?", 2025),
    ("How did the 2022 and 2024 regulations differ on engines?", None),   # a comparison: no single year
    ("What does Article 33.4 say?", None),
    ("Who won in 1999?", None),
    ("Results of the 2019 Monaco Grand Prix?", None),                      # outside 2018-2030 is not inferred... 2019 is inside
])
def test_infer_year(q, year):
    got = tools.infer_year(q)
    assert got == (2019 if "2019" in q else year)


def test_the_requests_year_is_inferred_from_the_question_and_filters_the_search():
    calls = []
    run([search(), ANSWER], retrieve=retriever(calls=calls), question="How many engines in the 2024 sporting regulations?")
    assert calls[0][1]["year"] == 2024
    calls.clear()
    run([search(), ANSWER], retrieve=retriever(calls=calls), question="How many engines in the 2024 sporting regulations?", year=2022)
    assert calls[0][1]["year"] == 2022                                      # an explicit request year wins


def test_rerank_is_off_by_default_and_search_tools_ask_for_eight(monkeypatch):
    from api.assistant import retrieval

    assert retrieval.RERANK_DEFAULT is False
    calls = []
    run([search(), ANSWER], retrieve=retriever(calls=calls))
    assert calls[0][1]["top_k"] == 8
