"""The stewards assistant agent: a LangGraph state machine over the headless Claude runner.

    plan --tools--> tools --> plan --...--> plan --answer--> answer --> END        (at most MAX_ROUNDS tool rounds)

The `claude -p` CLI cannot call our Python tools natively, so the planner node asks it (structured JSON) which tools
to run, or to answer. Python validates and executes the calls in-process, then feeds the results back. The answer
node writes the final text from the Evidence items only and streams it; Python builds the citations from the
evidence ids the text cites, so a source cannot be invented. No evidence = "Evidence not found." without a model call.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, TypedDict

from langgraph.graph import END, StateGraph

from .llm import AuthExpired, BadOutput, ClaudeError, RateLimited, make_planner_runnable
from .tools import SPECS, TOOL_NAMES, EXTRACT_CAP, Evidence, ToolContext, ToolError, run_tool, validate_call

logger = logging.getLogger(__name__)

MAX_ROUNDS = 4
MAX_CALLS_PER_ROUND = 3
NOT_FOUND_TEXT = "Evidence not found."

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["tools", "answer"]},
        "reasoning": {"type": "string"},
        "tool_calls": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"tool": {"type": "string", "enum": TOOL_NAMES}, "args": {"type": "object"}},
                      "required": ["tool", "args"]},
        },
    },
    "required": ["action"],
}

PLANNER_SYSTEM = (
    "You plan tool calls for a Formula 1 stewards and rules assistant. You do not answer the question yourself. "
    "Choose tools to gather evidence; set action to \"answer\" once the evidence collected so far is enough, or when "
    "no tool can help. Tools (name: purpose, argument schema):\n"
    + "\n".join(f"- {n}: {s['description']} args={json.dumps(s['schema']['properties'])}" for n, s in SPECS.items())
    + "\nRules: at most 3 tool calls per round; never repeat a call you already made; use search_documents for rule "
    "and ruling questions (rephrase the query for retrieval, keep article numbers if the user gave them); use the "
    "get_* tools only for a specific race (year y and round r); use similar_past_decisions for precedent. "
    "Reply with the JSON object only."
)

ANSWER_SYSTEM = (
    "You are the stewards and rules assistant of F1 Control Room. Answer ONLY from the evidence items provided; "
    "outside knowledge is not allowed. Cite every claim with the evidence id in square brackets, for example [E2] or "
    "[E1][E3]; never cite an id that is not in the list. State the article number and page when the evidence gives "
    "them. Quote at most 300 characters in any one quotation, and otherwise paraphrase; never reproduce long "
    "passages of the regulations. If the evidence does not contain the answer, reply exactly \"Evidence not found.\" "
    "followed by one sentence saying what was searched. Be concise (under 200 words)."
)

_CITE = re.compile(r"\[(E\d+(?:\s*,\s*E\d+)*)\]")
_LONG_QUOTE = re.compile(r"\"([^\"]{%d,})\"|“([^”]{%d,})”" % (EXTRACT_CAP + 1, EXTRACT_CAP + 1))


class AgentState(TypedDict, total=False):
    question: str
    year: int | None
    round: int | None
    evidence: list[Evidence]
    observations: list[str]
    calls_made: list[str]
    rounds: int
    plan: dict
    answer: str
    result: dict


# ---------- pure helpers (unit-tested) ----------

def evidence_for_prompt(items: list[Evidence]) -> str:
    out = []
    for e in items:
        head = f"[{e.id}] ({e.kind}) {e.label}"
        if e.article:
            head += f" | article {e.article}"
        if e.page:
            head += f" | page {e.page}"
        if e.section:
            head += f" | section {e.section}"
        out.append(f"{head}\n{e.text}")
    return "\n\n".join(out)


def build_citations(answer: str, evidence: list[Evidence]) -> tuple[list[dict], list[str]]:
    """Evidence ids cited in the text, in order of first appearance -> (citations, unknown ids). Each citation
    carries document title, page, article, section, FIA source URL and the <=300-char extract."""
    by_id = {e.id: e for e in evidence}
    seen, cites, unknown = set(), [], []
    for m in _CITE.finditer(answer):
        for eid in re.split(r"\s*,\s*", m.group(1)):
            if eid in seen:
                continue
            seen.add(eid)
            if eid in by_id:
                c = by_id[eid].citation()
                c["n"] = len(cites) + 1
                cites.append(c)
            else:
                unknown.append(eid)
    return cites, unknown


def long_quotes(answer: str) -> int:
    """Quotations longer than the 300-character cap (reported in the done event; the text is already streamed)."""
    return len(_LONG_QUOTE.findall(answer))


def is_not_found(answer: str) -> bool:
    return answer.strip().lower().startswith("evidence not found")


def planner_prompt(state: AgentState) -> str:
    ev = "\n".join(
        f"- [{e.id}] {e.tool}: {e.label}" + (f" (article {e.article}, p.{e.page})" if e.article else "") + f": {e.extract[:160]}"
        for e in state.get("evidence", [])
    ) or "(none yet)"
    obs = "\n".join(f"- {o}" for o in state.get("observations", [])) or "(none)"
    ctx = []
    if state.get("year"):
        ctx.append(f"year={state['year']}")
    if state.get("round"):
        ctx.append(f"round={state['round']}")
    return (f"Question: {state['question']}\nRequest context: {', '.join(ctx) or 'none'}\n"
            f"Tool round {state.get('rounds', 0) + 1} of at most {MAX_ROUNDS}.\n"
            f"Calls already made:\n" + ("\n".join(f"- {c}" for c in state.get("calls_made", [])) or "(none)")
            + f"\nEvidence so far:\n{ev}\nProblems with earlier calls:\n{obs}")


# ---------- graph ----------

def _cfg(config) -> dict:
    return config["configurable"]


def plan_node(state: AgentState, config) -> dict:
    c = _cfg(config)
    if state.get("rounds", 0) >= MAX_ROUNDS:  # bound: after the 4th tool round the only way out is the answer
        return {"plan": {"action": "answer", "forced": True}}
    c["emit"]({"type": "status", "phase": "solving", "message": "Deciding what to look up"})
    try:
        plan = c["planner"].invoke(planner_prompt(state))
    except BadOutput:
        logger.warning("[assistant] planner returned bad JSON twice; going straight to the answer")
        return {"plan": {"action": "answer", "planner_failed": True}}
    if not isinstance(plan, dict) or plan.get("action") not in ("tools", "answer"):
        return {"plan": {"action": "answer", "planner_failed": True}}
    return {"plan": plan}


def route_after_plan(state: AgentState) -> str:
    return "tools" if state["plan"].get("action") == "tools" else "answer"


def tools_node(state: AgentState, config) -> dict:
    c = _cfg(config)
    ctx: ToolContext = c["ctx"]
    calls = state["plan"].get("tool_calls") or []
    evidence = list(state.get("evidence", []))
    observations, made = [], list(state.get("calls_made", []))
    if not calls:
        observations.append("action was 'tools' but no tool_calls were given")
    names = [x.get("tool") for x in calls[:MAX_CALLS_PER_ROUND] if isinstance(x, dict)]
    c["emit"]({"type": "status", "phase": "searching", "message": "Searching", "tools": names})

    def next_id():
        return f"E{len(evidence) + 1}"

    for call in calls[:MAX_CALLS_PER_ROUND]:
        name = call.get("tool") if isinstance(call, dict) else None
        try:
            args = validate_call(name, call.get("args", {}), ctx)
            sig = f"{name}({json.dumps(args, sort_keys=True)})"
            if sig in made:
                observations.append(f"{sig} was already called; its results are in the evidence")
                continue
            made.append(sig)
            found = run_tool(name, args, ctx, next_id)
            evidence += found
            if not found:
                observations.append(f"{sig} returned nothing")
        except ToolError as exc:
            observations.append(str(exc))
        except Exception as exc:  # noqa: BLE001  a failing tool must not kill the question
            logger.exception("[assistant] tool %s failed", name)
            observations.append(f"{name} failed: {type(exc).__name__}")
    return {"evidence": evidence, "observations": observations, "calls_made": made, "rounds": state.get("rounds", 0) + 1}


def answer_node(state: AgentState, config) -> dict:
    c = _cfg(config)
    emit, runner = c["emit"], c["runner"]
    evidence = state.get("evidence", [])
    base = {"rounds": state.get("rounds", 0), "tools_used": sorted({e.tool for e in evidence}),
            "evidence_items": len(evidence), "model_answer": getattr(runner, "answer_model", None)}
    emit({"type": "status", "phase": "composing", "message": "Writing the answer"})
    if not evidence:  # nothing found: say so without spending a model call
        emit({"type": "token", "text": NOT_FOUND_TEXT})
        emit({"type": "citations", "citations": []})
        result = {**base, "answer": NOT_FOUND_TEXT, "grounded": True, "not_found": True, "citations": 0,
                  "invalid_citations": [], "long_quotes": 0, "cost_usd": getattr(runner, "cost_usd", 0.0)}
        emit({"type": "done", **result})
        return {"answer": NOT_FOUND_TEXT, "result": result}
    prompt = f"Question: {state['question']}\n\nEvidence:\n{evidence_for_prompt(evidence)}\n\nAnswer the question."
    text = ""
    for kind, value in runner.stream_answer(prompt, ANSWER_SYSTEM):
        if kind == "delta":
            text += value
            emit({"type": "token", "text": value})
        else:
            text = value.get("text") or text
    not_found = is_not_found(text)
    cites, unknown = ([], []) if not_found else build_citations(text, evidence)
    emit({"type": "citations", "citations": cites})
    result = {**base, "answer": text, "not_found": not_found, "citations": len(cites), "invalid_citations": unknown,
              "grounded": not_found or bool(cites) and not unknown, "long_quotes": long_quotes(text),
              "cost_usd": getattr(runner, "cost_usd", 0.0)}
    emit({"type": "done", **result})
    return {"answer": text, "result": result}


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("plan", plan_node)
    g.add_node("tools", tools_node)
    g.add_node("answer", answer_node)
    g.set_entry_point("plan")
    g.add_conditional_edges("plan", route_after_plan, {"tools": "tools", "answer": "answer"})
    g.add_edge("tools", "plan")
    g.add_edge("answer", END)
    return g.compile()


_GRAPH = None


def run_agent(question: str, year: int | None, rnd: int | None, *, runner, emit: Callable[[dict], None],
              retrieve: Callable | None = None) -> dict:
    """Run one question. Events go to `emit` (status, token, citations, done | error). Returns the final result dict."""
    global _GRAPH
    _GRAPH = _GRAPH or build_graph()
    planner = make_planner_runnable(runner, PLANNER_SYSTEM, PLAN_SCHEMA)
    ctx = ToolContext(year=year, round=rnd, retrieve=retrieve)
    try:
        out = _GRAPH.invoke(
            {"question": question, "year": year, "round": rnd, "evidence": [], "observations": [], "calls_made": [], "rounds": 0},
            config={"configurable": {"emit": emit, "runner": runner, "planner": planner, "ctx": ctx}, "recursion_limit": 40},
        )
        return out.get("result", {})
    except AuthExpired:
        emit({"type": "error", "code": "auth_expired", "message": "The assistant's Claude login has expired; the operator must renew it."})
    except RateLimited:
        emit({"type": "error", "code": "rate_limited", "message": "The assistant hit its usage limit; try again later."})
    except ClaudeError as exc:
        logger.error("[assistant] claude failed: %s", exc)
        emit({"type": "error", "code": "llm_failed", "message": "The assistant could not produce an answer."})
    except Exception:  # noqa: BLE001
        logger.exception("[assistant] agent crashed")
        emit({"type": "error", "code": "internal", "message": "The assistant failed unexpectedly."})
    return {}
