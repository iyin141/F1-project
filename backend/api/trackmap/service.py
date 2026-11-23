"""Read side of trackmap: geometry lookup, lap traces on the geometry grid, and the three response builders."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd
from django.core.cache import caches

from .models import TrackGeometry
from .telemetry_params import TIME_KEY

logger = logging.getLogger(__name__)

ALLOWED_SESSIONS = {"R", "Q", "S", "SQ", "FP1", "FP2", "FP3"}
SCHEMES = ("distance", "corners")
MAX_DRIVERS = 20
_DRIVER_RE = re.compile(r"^[A-Z]{3}$")
_MIN_SPEED_MS = 5 / 3.6  # floor so a stationary sample does not blow up 1/v


class ParamError(ValueError):
    """Bad query parameter; the view turns it into a 400."""


class TraceUnavailable(LookupError):
    """No persisted telemetry for a driver/lap; the view turns it into a 404."""


# --- cache keys / geometry lookup ------------------------------------------------

def geometry_cache_key(circuit_key: int, layout_hash: str) -> str:
    return f"trackmap:geometry:{circuit_key}:{layout_hash}"


def built_key(year: int, round_number: int) -> str:
    return f"trackmap:built:{year}:{round_number}"


def geometry_payload(g: TrackGeometry) -> dict:
    return {
        "circuit_key": g.circuit_key,
        "year": g.year,
        "layout_hash": g.layout_hash,
        "points": g.points,
        "corners": g.corners,
        "mini_sectors": g.mini_sectors,
        "drs_zones": g.drs_zones,
        "source": g.source,
    }


def get_geometry_payload(year: int, round_number: int) -> dict | None:
    """Cache pointer -> cached payload -> DB row. None when not built yet."""
    cache = caches["telemetry_cache"]
    ptr = cache.get(built_key(year, round_number))
    if not ptr:
        return None
    raw = cache.get(geometry_cache_key(*ptr))
    if raw is not None:
        return json.loads(raw) if isinstance(raw, str) else raw
    row = TrackGeometry.objects.filter(circuit_key=ptr[0], layout_hash=ptr[1]).first()
    if row is None:
        return None
    payload = geometry_payload(row)
    cache.set(geometry_cache_key(*ptr), json.dumps(payload), timeout=None)
    return payload


# --- param parsing ---------------------------------------------------------------

def parse_scheme(raw: str | None) -> str:
    scheme = (raw or "distance").lower()
    if scheme not in SCHEMES:
        raise ParamError("scheme must be one of: distance, corners")
    return scheme


def parse_session(raw: str | None) -> str:
    s = (raw or "R").upper()
    if s not in ALLOWED_SESSIONS:
        raise ParamError("session must be one of: " + ", ".join(sorted(ALLOWED_SESSIONS)))
    return s


def parse_lap(raw: str | None) -> str | int:
    if raw is None or raw == "" or raw.lower() == "fastest":
        return "fastest"
    try:
        lap = int(raw)
    except ValueError:
        raise ParamError("lap must be 'fastest' or a positive integer") from None
    if lap < 1:
        raise ParamError("lap must be 'fastest' or a positive integer")
    return lap


def parse_driver(raw: str | None, name: str) -> str:
    code = (raw or "").strip().upper()
    if not _DRIVER_RE.match(code):
        raise ParamError(f"{name} must be a 3-letter driver code")
    return code


def parse_drivers(raw: str | None) -> list[str]:
    if not raw:
        raise ParamError("drivers is required, e.g. drivers=VER,NOR")
    out = []
    for part in raw.split(","):
        code = parse_driver(part, "drivers")
        if code not in out:
            out.append(code)
    if len(out) > MAX_DRIVERS:
        raise ParamError(f"at most {MAX_DRIVERS} drivers")
    return out


# --- lap traces ------------------------------------------------------------------

@dataclass
class Trace:
    driver: str
    lap_number: int
    dist: np.ndarray  # metres, rescaled so the lap spans exactly the geometry length
    time: np.ndarray  # seconds from lap start
    lap_time: float
    time_source: str  # "telemetry" (stored time channel), "official" (lap table) or "integrated" (from speed)

    def time_at(self, d) -> np.ndarray:
        return np.interp(d, self.dist, self.time)


def _lap_arrays(lap_payload: dict):
    """(distance from 0, integrated time, stored time or None) for one persisted lap.

    Stored laps written since Phase 1c carry `elapsed_s` (measured seconds from lap start);
    older rows do not, so time is also integrated from speed (dd / v) as the fallback."""
    d = np.asarray(lap_payload.get("distance") or [], float)
    v = np.asarray(lap_payload.get("speed") or [], float)
    tm = np.asarray(lap_payload.get(TIME_KEY) or [], float)
    n = min(len(d), len(v))
    if n < 50:
        return None
    d, v = d[:n], v[:n]
    tm = tm[:n] if len(tm) >= n and np.isfinite(tm[:n]).all() else None
    d = np.maximum.accumulate(d - d[0])
    keep = np.concatenate([[True], np.diff(d) > 0])  # strictly increasing for interp
    d, v = d[keep], v[keep]
    if tm is not None:
        tm = np.maximum.accumulate(tm[keep] - tm[keep][0])
        if tm[-1] <= 0:
            tm = None
    if len(d) < 50 or d[-1] <= 0:
        return None
    inv = 1.0 / np.maximum(v / 3.6, _MIN_SPEED_MS)
    t = np.concatenate([[0.0], np.cumsum(np.diff(d) * 0.5 * (inv[:-1] + inv[1:]))])
    return d, t, tm


def _official_times(year, round_number, session, driver) -> dict[int, float]:
    """{lap_number: seconds} from the persisted lap table (race sessions only); {} if absent."""
    try:
        from api.services.persistence import get_persisted_lap_analysis

        data = get_persisted_lap_analysis(year, round_number, session, driver, None) or {}
        rows = data.get("data", []) if isinstance(data, dict) else data
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for r in rows:
        if r.get("lap_time") in (None, ""):
            continue
        try:
            out[int(r["lap_number"])] = float(pd.to_timedelta(r["lap_time"]).total_seconds())
        except (ValueError, TypeError, KeyError):
            continue
    return out


def load_trace(year, round_number, session, driver, lap, length_m: float) -> Trace:
    from api.services.persistence import get_persisted_driver_telemetry

    payload = get_persisted_driver_telemetry(year, round_number, session, driver)
    if not payload:
        raise TraceUnavailable(f"no persisted telemetry for {driver} in {year} round {round_number} {session}")
    laps = {}
    for key, lp in payload.items():
        try:
            res = _lap_arrays(lp)
            if res is not None:
                laps[int(key)] = res
        except (ValueError, TypeError):
            continue
    if not laps:
        raise TraceUnavailable(f"no usable telemetry laps for {driver}")
    official = _official_times(year, round_number, session, driver)

    if lap == "fastest":
        full = max(res[0][-1] for res in laps.values())
        # ponytail: complete laps only (>= 90 % of the longest), so in/out laps cannot win.
        cands = {n: r for n, r in laps.items() if r[0][-1] >= 0.9 * full}
        pool = {n: official[n] for n in cands if n in official}
        # no lap table: rank by measured time when stored, else integrated time
        lap_no = min(pool, key=pool.get) if pool else min(cands, key=lambda n: (cands[n][2] if cands[n][2] is not None else cands[n][1])[-1])
    else:
        lap_no = lap
        if lap_no not in laps:
            raise TraceUnavailable(f"no telemetry for {driver} lap {lap_no}")

    d, t, measured = laps[lap_no]
    if measured is not None:
        t, source = measured, "telemetry"  # stored time channel wins; no scaling needed
    elif lap_no in official and t[-1] > 0:
        t = t * (official[lap_no] / t[-1])  # scale so the lap adds up to the timed lap
        source = "official"
    else:
        source = "integrated"
    # Each lap's integrated distance drifts a few metres; fix the end points to the geometry length.
    return Trace(driver, lap_no, d * (length_m / d[-1]), t, float(t[-1]), source)


# --- response builders -----------------------------------------------------------

def track_map_response(geom: dict, scheme: str, year: int, round_number: int) -> dict:
    ms = geom["mini_sectors"][scheme]
    return {
        "meta": {
            "year": year, "round": round_number, "scheme": scheme,
            "circuit_key": geom["circuit_key"], "layout_hash": geom["layout_hash"],
            "geometry_year": geom["year"], "source": geom["source"],
            "point_count": len(geom["points"]["distance"]),
            "position_unit": "1/10 m",
        },
        "points": geom["points"],
        "corners": geom["corners"],
        "mini_sectors": ms,
        "drs_zones": geom["drs_zones"],
    }


def mini_sectors_response(geom, scheme, year, round_number, session, drivers, lap) -> dict:
    ms = geom["mini_sectors"][scheme]
    bounds = np.asarray(ms["boundaries"], float)
    length = float(geom["points"]["distance"][-1])
    per_driver, times = {}, {}
    for drv in drivers:
        tr = load_trace(year, round_number, session, drv, lap, length)
        t_b = tr.time_at(bounds)
        seg = np.diff(t_b)
        times[drv] = seg
        per_driver[drv] = {
            "lap_number": tr.lap_number,
            "lap_time": round(tr.lap_time, 3),
            "lap_time_source": tr.time_source,
            "sector_times": [round(float(x), 3) for x in seg],
        }
    stack = np.vstack([times[d] for d in drivers])
    best = stack.argmin(axis=0)
    fastest = [
        {"sector": i + 1, "driver": drivers[int(b)], "time": round(float(stack[int(b), i]), 3)}
        for i, b in enumerate(best)
    ]
    gaps = {d: [round(float(x), 3) for x in times[d] - stack.min(axis=0)] for d in drivers}
    return {
        "meta": {
            "year": year, "round": round_number, "session": session, "scheme": scheme,
            "lap": lap, "sector_count": len(bounds) - 1,
            "circuit_key": geom["circuit_key"], "layout_hash": geom["layout_hash"],
        },
        "boundaries": ms["boundaries"],
        "labels": ms.get("labels", []),
        "drivers": per_driver,
        "fastest_per_sector": fastest,
        "gaps": gaps,
    }


def delta_response(geom, year, round_number, session, ref, cmp_, lap) -> dict:
    grid = np.asarray(geom["points"]["distance"], float)
    length = float(grid[-1])
    a = load_trace(year, round_number, session, ref, lap, length)
    b = load_trace(year, round_number, session, cmp_, lap, length)
    delta = b.time_at(grid) - a.time_at(grid)  # positive: cmp is behind ref
    return {
        "meta": {
            "year": year, "round": round_number, "session": session, "lap": lap,
            "circuit_key": geom["circuit_key"], "layout_hash": geom["layout_hash"],
            "point_count": len(grid), "delta_sign": "positive = cmp slower than ref",
        },
        "ref": {"driver": ref, "lap_number": a.lap_number, "lap_time": round(a.lap_time, 3), "lap_time_source": a.time_source},
        "cmp": {"driver": cmp_, "lap_number": b.lap_number, "lap_time": round(b.lap_time, 3), "lap_time_source": b.time_source},
        "distance": [round(float(x), 2) for x in grid],
        "delta": [round(float(x), 3) for x in delta],
    }
