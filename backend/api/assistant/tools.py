"""The agent's tools. They call the services in-process (no HTTP) and return `Evidence` items.

Every fact the answer may use arrives as an Evidence item with an id (E1, E2, ...); the answer cites those ids and
Python turns them into citations (document, page, article, source URL), so the model cannot invent a source.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from jsonschema import Draft202012Validator

EXTRACT_CAP = 300
DATA_CHARS = 3000      # cap on a data tool's JSON handed to the model
MIN_YEAR, MAX_YEAR = 2018, 2030


class ToolError(ValueError):
    """Bad tool name or arguments from the planner: reported back to it as an observation, never executed."""


@dataclass
class Evidence:
    id: str
    tool: str
    kind: str                  # "document" | "data"
    label: str                 # short human title
    text: str                  # what the model reads (full chunk, or the compact data JSON)
    extract: str = ""          # <= 300 chars: the only text that may be quoted to users
    url: str = ""              # FIA source URL for documents
    title: str = ""
    page: int | None = None
    article: str = ""
    section: str = ""
    year: int | None = None
    race: str = ""
    doc_type: str = ""
    meta: dict = field(default_factory=dict)

    def citation(self) -> dict:
        return {"id": self.id, "kind": self.kind, "label": self.label, "title": self.title or self.label,
                "url": self.url, "page": self.page, "article": self.article, "section": self.section,
                "year": self.year, "race": self.race, "doc_type": self.doc_type, "extract": self.extract}


@dataclass
class ToolContext:
    year: int | None = None
    round: int | None = None
    retrieve: Callable[..., list] | None = None   # defaults to retrieval.retrieve; tests inject a fake

    def do_retrieve(self, question, **kw):
        if self.retrieve is None:
            from .retrieval import retrieve

            return retrieve(question, **kw)
        return self.retrieve(question, **kw)


_INT_YEAR = {"type": "integer", "minimum": MIN_YEAR, "maximum": MAX_YEAR}
_INT_ROUND = {"type": "integer", "minimum": 1, "maximum": 30}
DOC_TYPES = ["sporting_regs", "technical_regs", "other_regs", "stewards_decision", "event_notes"]

SPECS: dict[str, dict] = {
    "search_documents": {
        "description": "Search the FIA regulations, stewards' decisions and event notes. Use for any rule or ruling question.",
        "schema": {"type": "object", "properties": {"query": {"type": "string", "minLength": 3, "maxLength": 300},
                                                      "year": _INT_YEAR, "doc_type": {"enum": DOC_TYPES}},
                   "required": ["query"], "additionalProperties": False},
    },
    "get_incidents": {
        "description": "Race-control incident messages (investigations, penalties, collisions) of one race, from our database.",
        "schema": {"type": "object", "properties": {"y": _INT_YEAR, "r": _INT_ROUND}, "required": ["y", "r"], "additionalProperties": False},
    },
    "get_track_status": {
        "description": "Track status periods (yellow flag, safety car, virtual safety car, red flag) of one race.",
        "schema": {"type": "object", "properties": {"y": _INT_YEAR, "r": _INT_ROUND}, "required": ["y", "r"], "additionalProperties": False},
    },
    "get_chaos": {
        "description": "Chaos Point model output for one race: probabilities of safety car, red flag, collisions, retirements.",
        "schema": {"type": "object", "properties": {"y": _INT_YEAR, "r": _INT_ROUND}, "required": ["y", "r"], "additionalProperties": False},
    },
    "similar_past_decisions": {
        "description": "Stewards' decisions on a similar offence in past races (precedent). n = how many, 1-10.",
        "schema": {"type": "object", "properties": {"offence": {"type": "string", "minLength": 3, "maxLength": 300},
                                                      "n": {"type": "integer", "minimum": 1, "maximum": 10}},
                   "required": ["offence"], "additionalProperties": False},
    },
}
TOOL_NAMES = list(SPECS)


def validate_call(name: str, args: Any, ctx: ToolContext) -> dict:
    """Check tool name and arguments against the JSON schema; fill y/r from the request when omitted."""
    if name not in SPECS:
        raise ToolError(f"unknown tool {name!r}; available: {', '.join(TOOL_NAMES)}")
    if not isinstance(args, dict):
        raise ToolError("args must be an object")
    args = dict(args)
    if name in ("get_incidents", "get_track_status", "get_chaos"):
        args.setdefault("y", ctx.year)
        args.setdefault("r", ctx.round)
        if args["y"] is None or args["r"] is None:
            raise ToolError(f"{name} needs y and r (the request gave no year/round)")
    errs = sorted(Draft202012Validator(SPECS[name]["schema"]).iter_errors(args), key=lambda e: list(e.path))
    if errs:
        raise ToolError(f"{name}: " + "; ".join(e.message for e in errs[:3]))
    return args


def _doc_evidence(hit, eid: str, tool: str) -> Evidence:
    return Evidence(id=eid, tool=tool, kind="document", label=(hit.source_title or hit.section or "FIA document"),
                    text=hit.text, extract=hit.extract[:EXTRACT_CAP], url=hit.source_url, title=hit.source_title,
                    page=hit.page, article=hit.article, section=hit.section, year=hit.year, race=hit.race,
                    doc_type=hit.doc_type)


def _compact(payload: Any) -> str:
    s = json.dumps(payload, default=str, separators=(",", ":"))
    return s if len(s) <= DATA_CHARS else s[:DATA_CHARS] + '..."[truncated]"'


def _data_evidence(eid, tool, label, payload, year, rnd) -> Evidence:
    text = _compact(payload)
    return Evidence(id=eid, tool=tool, kind="data", label=label, text=text, extract=text[:EXTRACT_CAP],
                    title=label, year=year, meta={"round": rnd})


def _ranked(items: list[Evidence]) -> list[Evidence]:
    """Remember each hit's position within its call (0 = best), used to pick the answer's evidence."""
    for i, e in enumerate(items):
        e.meta["rank"] = i
    return items


def run_tool(name: str, args: dict, ctx: ToolContext, next_id: Callable[[], str]) -> list[Evidence]:
    """Execute one validated call. Returns [] when the tool found nothing (never raises for 'no data')."""
    if name == "search_documents":
        hits = ctx.do_retrieve(args["query"], year=args.get("year") or ctx.year, doc_type=args.get("doc_type"),
                               top_k=6, pool=20)
        return _ranked([_doc_evidence(h, next_id(), name) for h in hits])
    if name == "similar_past_decisions":
        hits = ctx.do_retrieve(args["offence"], doc_type="stewards_decision", top_k=int(args.get("n", 5)), pool=20)
        return _ranked([_doc_evidence(h, next_id(), name) for h in hits])
    y, r = args["y"], args["r"]
    if name == "get_incidents":
        from api.services.persistence import get_persisted_incidents_data

        payload = get_persisted_incidents_data(y, r, "R")
        label = f"Race control incidents, {y} round {r}"
    elif name == "get_track_status":
        from api.services.persistence import get_persisted_track_status_data

        payload = get_persisted_track_status_data(y, r, "R")
        label = f"Track status periods, {y} round {r}"
    else:  # get_chaos
        from api.chaos import service as chaos

        run, block = chaos.select_run(y, r)
        payload = None
        if run is not None:
            full = chaos.race_payload(y, r, run, block)
            payload = {k: full[k] for k in ("targets", "chaos_index", "chaos_index_band", "expected_events", "model") if k in full}
        label = f"Chaos Point prediction, {y} round {r}"
    return [] if not payload else [_data_evidence(next_id(), name, label, payload, y, r)]
