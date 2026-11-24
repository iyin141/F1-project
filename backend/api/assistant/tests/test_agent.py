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

def test_planner_bad_json_twice_falls_back_to_answer_and_not_found():
    runner, events, res = run([BadOutput("x")], answer="never used")
    assert res["not_found"] and runner.answer_prompts == []


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
