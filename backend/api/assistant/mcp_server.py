"""F1 Control Room MCP server: read-only tools over the same in-process services the web API uses.

Seven plain tools (fewer than 15, so no Code Mode wrapper yet). Everything is READ-ONLY and local: stored data and the
stored document corpus only. No tool writes, enqueues a task, or calls live FastF1 / Jolpica / Claude; a tool whose data
has not been stored says so and tells the caller which web endpoint builds it.

Built with the MCP Python SDK v2 (`MCPServer`, the renamed FastMCP). Run: `python stewards_mcp/server.py` from `backend/` (stdio).
FIA copyright: document results carry short extracts (<= 300 characters) and the FIA source URL, never full text.
"""
from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

SERVER_NAME = "f1_control_room_mcp"
EXTRACT_CAP = 300
RO = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
Year = Annotated[int, Field(ge=1950, le=2100, description="Season year, e.g. 2025")]
Round = Annotated[int, Field(ge=1, le=40, description="Round number within the season, e.g. 5")]
DocType = Literal["sporting_regs", "technical_regs", "other_regs", "stewards_decision", "event_notes"]
INSTRUCTIONS = (
    "Read-only access to F1 Control Room: stored race data (results, schedule, race-control incidents, track status), "
    "the Chaos Point model's stored predictions, stored track geometry, and search over FIA regulations and stewards' "
    "decisions. Nothing is fetched live: when data is not stored the tool says so. Cite FIA documents with their title, "
    "article, page and URL; quote at most the returned extract."
)


class ToolFailure(ToolError):
    """An anticipated failure (missing data, bad input): the SDK returns it as an error result whose text guides the
    caller. Any other exception is treated as a crash and the caller only sees a generic message."""


def _decimate(points: dict, max_points: int) -> dict:
    n = len(next(iter(points.values()), []))
    step = max(-(-n // max_points), 1)
    return {k: (v[::step] + ([v[-1]] if v and (n - 1) % step else [])) if isinstance(v, list) else v for k, v in points.items()}


# ---------- tool bodies (plain functions: testable without the protocol) ----------

def search_documents(query: str, year: int | None = None, doc_type: str | None = None, limit: int = 5) -> dict:
    from .retrieval import retrieve

    hits = retrieve(query, year=year, doc_type=doc_type, top_k=limit)
    return {
        "query": query, "count": len(hits),
        "copyright": "FIA publications: quote at most the extract and cite the source URL; do not reproduce full text.",
        "results": [{"title": h.source_title, "doc_type": h.doc_type, "year": h.year, "race": h.race, "article": h.article,
                     "page": h.page, "section": h.section, "url": h.source_url, "extract": h.extract[:EXTRACT_CAP]} for h in hits],
    }


def get_chaos(year: int, round: int, model: str = "auto") -> dict:
    from api.chaos import service as chaos

    try:
        chaos.parse_race(year, round)
        choice = chaos.parse_model(model)
    except chaos.ParamError as exc:
        raise ToolFailure(str(exc)) from exc
    run, block = chaos.select_run(year, round, choice)
    if run is None:
        raise ToolFailure(f"No Chaos Point model run is stored for {year} round {round}. It is produced by the chaos pipeline "
                          f"(see GET /api/chaos/races/{year}/{round}/); this tool never runs a model.")
    return chaos.race_payload(year, round, run, block)


def get_track_map(year: int, round: int, scheme: str = "distance", max_points: int = 150) -> dict:
    from api.trackmap import service as tm

    try:
        scheme = tm.parse_scheme(scheme)
    except tm.ParamError as exc:
        raise ToolFailure(str(exc)) from exc
    geom = tm.get_geometry_payload(year, round)
    if geom is None:
        raise ToolFailure(f"Track geometry for {year} round {round} has not been built. Request "
                          f"GET /api/analysis/races/{year}/{round}/track-map/ once on the web API to build it; this tool never calls FastF1.")
    out = tm.track_map_response(geom, scheme, year, round)
    out["points"] = _decimate(out["points"], max_points)
    out["meta"]["points_returned"] = len(next(iter(out["points"].values()), []))
    return out


def _stored(getter, what: str, year: int, rnd: int, endpoint: str, *args):
    data = getter(year, rnd, *args)
    if not data:
        raise ToolFailure(f"No stored {what} for {year} round {rnd}. It is populated by the web API (GET {endpoint}); "
                          "this tool only reads stored data and never calls FastF1.")
    return data


def get_incidents(year: int, round: int, limit: int = 30) -> dict:
    from api.services.persistence import get_persisted_incidents_data

    data = _stored(lambda y, r: get_persisted_incidents_data(y, r, "R"), "race-control incidents", year, round,
                   f"/api/analysis/races/{year}/{round}/incidents/")
    rows = data.get("data") if isinstance(data, dict) else None
    if isinstance(rows, list):
        return {"meta": data.get("meta", {}), "total": len(rows), "data": rows[:limit]}
    return data


def get_track_status(year: int, round: int) -> dict:
    from api.services.persistence import get_persisted_track_status_data

    return _stored(lambda y, r: get_persisted_track_status_data(y, r, "R"), "track status periods", year, round,
                   f"/api/analysis/races/{year}/{round}/track-status/")


def get_race_results(year: int, round: int) -> dict:
    from api.services.persistence import get_persisted_race_results

    rows = _stored(get_persisted_race_results, "race results", year, round, f"/api/races/{year}/{round}/results/")
    return {"year": year, "round": round, "count": len(rows), "results": rows}


def get_race_schedule(year: int) -> dict:
    from api.services.persistence import get_persisted_season_schedule

    races = get_persisted_season_schedule(year)
    if not races:
        raise ToolFailure(f"No stored schedule for {year}. It is populated by the web API (GET /api/schedule/{year}/).")
    return {"year": year, "count": len(races), "races": races}


# ---------- the server ----------

def build_server():
    from mcp.server.mcpserver import MCPServer

    s = MCPServer(SERVER_NAME, instructions=INSTRUCTIONS)

    @s.tool(name="f1_search_documents", annotations={"title": "Search FIA regulations and stewards' decisions", **RO})
    def f1_search_documents(
        query: Annotated[str, Field(min_length=3, max_length=300, description="What to look for, e.g. 'penalty for causing a collision' or 'Article B5.10 formation lap'")],
        year: Annotated[int | None, Field(ge=2018, le=2030, description="Only documents of this season/regulation year")] = None,
        doc_type: Annotated[DocType | None, Field(description="Restrict to one document type")] = None,
        limit: Annotated[int, Field(ge=1, le=8, description="Maximum results")] = 5,
    ) -> dict:
        """Hybrid (full-text + vector) search of the FIA Sporting/Technical Regulations, stewards' decisions and event notes.
        Returns short extracts with title, article, page and FIA URL. Use the year filter when the question names a year."""
        return search_documents(query, year, doc_type, limit)

    @s.tool(name="f1_get_chaos", annotations={"title": "Chaos Point prediction for a race", **RO})
    def f1_get_chaos(year: Year, round: Round, model: Annotated[Literal["auto", "kumo_calibrated", "kumo", "baseline"], Field(description="Model to read; auto prefers the calibrated Kumo run, then the baseline")] = "auto") -> dict:
        """Stored Chaos Point model output: probabilities of safety car, red flag, collisions and retirements, the chaos
        index with its band, expected events and the factors behind them, plus which model produced them."""
        return get_chaos(year, round, model)

    @s.tool(name="f1_get_track_map", annotations={"title": "Circuit outline, corners, mini-sectors, DRS zones", **RO})
    def f1_get_track_map(year: Year, round: Round, scheme: Annotated[Literal["distance", "corners"], Field(description="Mini-sector scheme")] = "distance",
                         max_points: Annotated[int, Field(ge=20, le=1500, description="Downsample the outline to about this many points")] = 150) -> dict:
        """Stored circuit geometry for the race's layout: columnar x/y/z/distance points (1/10 m units), corner markers, the
        mini-sector boundaries of the chosen scheme and DRS zones."""
        return get_track_map(year, round, scheme, max_points)

    @s.tool(name="f1_get_incidents", annotations={"title": "Race-control incidents of a race", **RO})
    def f1_get_incidents(year: Year, round: Round, limit: Annotated[int, Field(ge=1, le=200, description="Maximum rows")] = 30) -> dict:
        """Stored race-control messages (investigations, penalties, collisions) of the race session."""
        return get_incidents(year, round, limit)

    @s.tool(name="f1_get_track_status", annotations={"title": "Track status periods of a race", **RO})
    def f1_get_track_status(year: Year, round: Round) -> dict:
        """Stored track status periods of the race (green, yellow, safety car, VSC, red flag) with their times."""
        return get_track_status(year, round)

    @s.tool(name="f1_get_race_results", annotations={"title": "Race classification", **RO})
    def f1_get_race_results(year: Year, round: Round) -> dict:
        """Stored race result rows (position, driver, team, grid, status, points) for the Grand Prix."""
        return get_race_results(year, round)

    @s.tool(name="f1_get_race_schedule", annotations={"title": "Season calendar", **RO})
    def f1_get_race_schedule(year: Year) -> dict:
        """Stored calendar of a season: round numbers, Grand Prix names, circuits and dates."""
        return get_race_schedule(year)

    return s
