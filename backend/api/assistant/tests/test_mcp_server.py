"""The MCP server through the SDK's in-memory client (no process, no network, no model)."""
import asyncio
import json
import sys

import pytest

from api.assistant import mcp_server
from api.assistant.retrieval import Hit

TOOLS = {"f1_search_documents", "f1_get_chaos", "f1_get_track_map", "f1_get_incidents", "f1_get_track_status",
         "f1_get_race_results", "f1_get_race_schedule"}


def run(coro):
    return asyncio.run(coro)


async def call(name, args):
    from mcp.client import Client

    async with Client(mcp_server.build_server()) as c:
        r = await c.call_tool(name, args)
        text = r.content[0].text if r.content else ""
        return r.is_error, text


def hit():
    t = "B1.9.5 " + "Penalties for incidents. " * 40
    return Hit(1, t, t[:300], 14, "B1.9.5", "B1.9 Incidents", "https://www.fia.com/x.pdf", "2026 F1 Regulations Section B",
               "sporting_regs", 2026, "", 1.0)


def test_exactly_the_read_only_tools_are_listed():
    from mcp.client import Client

    async def go():
        async with Client(mcp_server.build_server()) as c:
            return (await c.list_tools()).tools

    tools = run(go())
    assert {t.name for t in tools} == TOOLS and len(tools) < 15
    for t in tools:
        a = t.annotations
        assert a.read_only_hint is True and a.destructive_hint is False and a.open_world_hint is False, t.name
        assert t.description and t.input_schema["type"] == "object"
    names = [t.name for t in tools]
    assert all(n.startswith("f1_") for n in names)                       # service prefix: no clashes in a multi-server client
    assert not any(w in n for n in names for w in ("create", "update", "delete", "build", "populate", "enqueue", "write"))


def test_search_documents_returns_capped_extracts_and_citation_fields(monkeypatch):
    seen = {}
    monkeypatch.setattr("api.assistant.retrieval.retrieve", lambda q, **kw: seen.update(kw) or [hit()])
    err, text = run(call("f1_search_documents", {"query": "penalty for causing a collision", "year": 2026, "limit": 3}))
    assert not err and seen["year"] == 2026 and seen["top_k"] == 3
    out = json.loads(text)
    r = out["results"][0]
    assert len(r["extract"]) <= 300 and r["article"] == "B1.9.5" and r["page"] == 14 and r["url"].startswith("https://www.fia.com/")
    assert "text" not in r and "copyright" in out                      # never the full chunk


@pytest.mark.parametrize("name, args", [
    ("f1_search_documents", {"query": "ab"}),                           # too short
    ("f1_search_documents", {"query": "valid query", "doc_type": "pizza"}),
    ("f1_search_documents", {"query": "valid query", "limit": 99}),
    ("f1_get_chaos", {"year": 1800, "round": 1}),
    ("f1_get_track_map", {"year": 2025, "round": 5, "scheme": "zigzag"}),
    ("f1_get_incidents", {"year": 2025, "round": 0}),
])
def test_bad_input_is_an_error_result_not_a_crash(name, args):
    err, text = run(call(name, args))
    assert err and text


@pytest.mark.django_db
@pytest.mark.parametrize("name, args, hint", [
    ("f1_get_chaos", {"year": 2025, "round": 5}, "chaos pipeline"),
    ("f1_get_track_map", {"year": 2025, "round": 5}, "track-map"),
    ("f1_get_incidents", {"year": 2025, "round": 5}, "never calls FastF1"),
    ("f1_get_track_status", {"year": 2025, "round": 5}, "never calls FastF1"),
    ("f1_get_race_results", {"year": 2025, "round": 5}, "never calls FastF1"),
    ("f1_get_race_schedule", {"year": 2025}, "/api/schedule/2025"),
])
def test_missing_data_says_what_builds_it_and_never_fetches_live(name, args, hint):
    err, text = run(call(name, args))
    assert err and hint in text


def test_stored_data_is_returned(monkeypatch):
    monkeypatch.setattr("api.services.persistence.get_persisted_incidents_data",
                        lambda y, r, s, **kw: {"meta": {"y": y}, "data": [{"msg": f"incident {i}"} for i in range(50)]})
    monkeypatch.setattr("api.services.persistence.get_persisted_track_status_data", lambda y, r, s, **kw: {"periods": [{"status": "SC"}]})
    monkeypatch.setattr("api.services.persistence.get_persisted_race_results", lambda y, r: [{"position": 1, "driver": "VER"}])
    monkeypatch.setattr("api.services.persistence.get_persisted_season_schedule", lambda y: [{"round": 1, "name": "Australian GP"}])
    out = json.loads(run(call("f1_get_incidents", {"year": 2025, "round": 1, "limit": 5}))[1])
    assert out["total"] == 50 and len(out["data"]) == 5                  # limited, with the total
    assert json.loads(run(call("f1_get_track_status", {"year": 2025, "round": 1}))[1])["periods"][0]["status"] == "SC"
    assert json.loads(run(call("f1_get_race_results", {"year": 2025, "round": 1}))[1])["results"][0]["driver"] == "VER"
    assert json.loads(run(call("f1_get_race_schedule", {"year": 2025}))[1])["races"][0]["name"] == "Australian GP"


def test_track_map_is_decimated_and_keeps_the_last_point(monkeypatch):
    n = 1500
    geom = {"circuit_key": 7, "year": 2025, "layout_hash": "h", "source": "s",
            "points": {"distance": list(range(n)), "x": list(range(n)), "y": list(range(n))},
            "corners": [{"n": 1}], "drs_zones": [], "mini_sectors": {"distance": {"boundaries": [0, 100]}, "corners": {"boundaries": [0]}}}
    monkeypatch.setattr("api.trackmap.service.get_geometry_payload", lambda y, r: geom)
    out = json.loads(run(call("f1_get_track_map", {"year": 2025, "round": 5, "max_points": 100}))[1])
    pts = out["points"]["distance"]
    assert 100 <= len(pts) <= 102 and pts[0] == 0 and pts[-1] == n - 1 and out["meta"]["points_returned"] == len(pts)
    assert out["corners"] == [{"n": 1}] and out["mini_sectors"]["boundaries"] == [0, 100]


@pytest.mark.django_db
def test_chaos_payload_is_served_from_the_service(monkeypatch):
    from api.chaos import service as chaos

    monkeypatch.setattr(chaos, "select_run", lambda y, r, choice="auto": (object(), {"model": "beta_binomial"}))
    monkeypatch.setattr(chaos, "race_payload", lambda y, r, run, block: {"targets": {"safety_car": {"probability": 0.4}}, "model": block})
    out = json.loads(run(call("f1_get_chaos", {"year": 2025, "round": 5}))[1])
    assert out["targets"]["safety_car"]["probability"] == 0.4 and out["model"]["model"] == "beta_binomial"


def test_server_module_neither_writes_nor_reaches_live_sources():
    import inspect

    src = inspect.getsource(mcp_server)
    for banned in ("fastf1", "jolpica", ".delay(", "apply_async", "TaskManager", ".save(", ".create(", ".delete(", "subprocess"):
        assert banned not in src.replace("never calls FastF1", "").replace("FastF1 / Jolpica / Claude", ""), banned


def test_entry_point_runs_over_stdio_and_lists_the_tools():
    """Start `python stewards_mcp/server.py` for real and talk to it with the SDK's stdio client."""
    import os
    from pathlib import Path

    from mcp.client import Client
    from mcp.client.stdio import StdioServerParameters

    backend = Path(mcp_server.__file__).resolve().parents[2]
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}        # settings_test points PYTHONPATH at f1_project/
    env["DJANGO_SETTINGS_MODULE"] = "f1_project.settings_test"

    async def go():
        params = StdioServerParameters(command=sys.executable, args=[str(backend / "stewards_mcp" / "server.py")], cwd=str(backend), env=env)
        async with Client(params) as c:
            return {t.name for t in (await c.list_tools()).tools}

    assert run(asyncio.wait_for(go(), 90)) == TOOLS
