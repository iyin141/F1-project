"""Race history for features and the baseline: a loader (DB -> plain race dicts) and `Counts`, the running
(successes, trials) tally per hierarchy level. Races are processed in (year, round) order and a race is added to
the tally only AFTER its own row is built, which is what makes the history leakage-free.

Race dict (what tests build by hand):
  year, round, circuit (slug or schedule location), ctype ('street'|'permanent'|'hybrid'|None), profile {numeric traits},
  total_laps, weather {...}, drivers {code: {team, grid}}, agg (labels.aggregate_labels output),
  events [{type, lap, end_lap}] (SC/VSC/red), lane [pit-lane seconds].
"""
import statistics
from collections import defaultdict

from . import labels as L

RACE_TARGETS = L.TARGETS  # race and lap_window scopes
DRIVER_TARGETS = ["dnf_mechanical", "dnf_incident", "slow_stop", "unlucky_stop"]  # sc_vsc_red is not a driver trait
PRIOR_M = 8.0  # ponytail: one fixed shrinkage strength (pseudo-races) for every level; tune per level from the backtest


def race_key(r) -> tuple:
    return (r["year"], r["round"])


# ---- loading -----------------------------------------------------------------------------------------------

def _weather(rows) -> dict:
    def mean(k):
        v = [r[k] for r in rows if r.get(k) is not None]
        return sum(v) / len(v) if v else None
    return {"track_temp_c": mean("track_temp_c"), "air_temp_c": mean("air_temp_c"), "humidity_pct": mean("humidity_pct"),
            "wind_speed_ms": mean("wind_speed_ms"),
            "rain_frac": (sum(bool(r.get("rainfall")) for r in rows) / len(rows)) if rows else None}


def circuit_lookup():
    """{schedule location: CircuitProfile} (first match)."""
    from .models import CircuitProfile

    out = {}
    for p in CircuitProfile.objects.all():
        for loc in p.locations or []:
            out.setdefault(loc, p)
    return out


def race_meta(year, rnd, lookup) -> dict:
    """Circuit identity and traits for a race from the stored schedule (works for a race with no results yet)."""
    from api.models import SeasonSchedule

    sched = SeasonSchedule.objects.filter(year=year).first()
    race = next((r for r in (sched.payload.get("races", []) if sched else []) if r.get("round") == rnd), {})
    loc = race.get("location") or ""
    p = lookup.get(loc)
    prof = {k: getattr(p, k) for k in ("length_m", "corners", "wall_proximity", "overtaking_index", "elevation_range_m")} if p else {}
    return {"year": year, "round": rnd, "location": loc, "circuit": (p.slug if p else loc) or "unknown",
            "ctype": p.circuit_type if p else None, "profile": prof}


def load_races(up_to=None) -> list[dict]:
    """Every race with a stored result, ordered. `up_to` = (year, round) inclusive bound."""
    from api.models import PitStopData, PositionData, RaceResultData, WeatherData

    from .models import RaceEventLabel
    from .tasks import _rows

    lookup, out = circuit_lookup(), []
    for rr in RaceResultData.objects.filter(session="R").order_by("year", "round_number"):
        y, n = rr.year, rr.round_number
        if up_to and (y, n) > up_to:
            break
        results = list((rr.payload or {}).get("results", []))
        if not results:
            continue
        stops = _rows(PitStopData, y, n)
        ids = {}
        for r in stops + _rows(PositionData, y, n):
            if r.get("driver_number") is not None and r.get("driver_code"):
                ids[r["driver_number"]] = r["driver_code"]
        drivers = {ids.get(r.get("driver_number"), f"#{r.get('driver_number')}"):
                   {"team": r.get("team") or "", "grid": r.get("grid_position")} for r in results}
        total = max((r.get("laps") or 0 for r in results), default=0)
        evs = list(RaceEventLabel.objects.filter(year=y, round_number=n).values("type", "driver", "lap", "end_lap"))
        w = WeatherData.objects.filter(year=y, round_number=n, session="R").first()
        out.append({**race_meta(y, n, lookup), "total_laps": total, "drivers": drivers,
                    "weather": _weather(list((w.payload or {}).get("data", [])) if w else []),
                    "agg": L.aggregate_labels(evs, total, list(drivers)),
                    "events": [e for e in evs if e["type"] in L.NEUTRAL],
                    "lane": [s["stop_duration_seconds"] for s in stops if s.get("stop_duration_seconds")]})
    return out


# ---- running tally -----------------------------------------------------------------------------------------

def strata(window: int) -> str:
    return "first" if window == 1 else "rest"


class Counts:
    """(k successes, n trials) per (scope, target, level, name)."""

    def __init__(self):
        self.c = defaultdict(lambda: [0, 0])
        self.lanes = defaultdict(list)  # circuit / "" -> pit-lane seconds seen so far
        self.races = 0

    def _add(self, scope, t, lvl, name, k, n=1):
        cell = self.c[(scope, t, lvl, name)]
        cell[0] += k
        cell[1] += n

    def update(self, race):
        """Add one finished race. Call only after that race's own features are built."""
        self.races += 1
        circ, ct, agg = race["circuit"], race["ctype"], race["agg"]
        for t in RACE_TARGETS:
            for lvl, name in (("g", ""), ("t", ct), ("c", circ)):
                if lvl != "t" or ct:
                    self._add("race", t, lvl, name, int(agg["race"][t] > 0))
            for w in agg["windows"]:
                s = strata(w["window"])
                for lvl, name in (("g", ""), ("t", ct), ("c", circ)):
                    if lvl != "t" or ct:
                        self._add("win", t, lvl, f"{s}|{name}", int(w[t] > 0))
        for code, d in race["drivers"].items():
            for t in DRIVER_TARGETS:
                k = int(agg["drivers"].get(code, {}).get(t, 0) > 0)
                for lvl, name in (("g", ""), ("team", d["team"]), ("d", code)):
                    self._add("drv", t, lvl, name, k)
        self.lanes[circ] += race["lane"]
        self.lanes[""] += race["lane"]

    def rate(self, scope, t, chain, m=PRIOR_M):
        """Hierarchical Beta-Binomial. chain = [(level, name), ...] broad -> specific; the first must be ('g', '').
        Posterior of each level is its own Beta prior (parent posterior mean x strength m) updated with its counts,
        so a level with few trials stays near its parent. Returns (mean, a, b, n_trials_at_last_level)."""
        k, n = self.c.get((scope, t) + chain[0], (0, 0))
        a, b = 1 + k, 1 + n - k  # uniform prior at the root
        last = n
        for lvl in chain[1:]:
            k, n = self.c.get((scope, t, lvl[0], lvl[1]), (0, 0))
            p = a / (a + b)
            a, b = m * p + k, m * (1 - p) + n - k
            last = n
        return a / (a + b), a, b, last

    def lane_rel(self, circ):
        """Circuit median pit-lane time over the global median, from earlier races only (None until both exist)."""
        c, g = self.lanes.get(circ), self.lanes.get("")
        return statistics.median(c) / statistics.median(g) if c and g else None


def race_chain(race):
    return [("g", "")] + ([("t", race["ctype"])] if race["ctype"] else []) + [("c", race["circuit"])]


def win_chain(race, window):
    s = strata(window)
    return [("g", f"{s}|")] + ([("t", f"{s}|{race['ctype']}")] if race["ctype"] else []) + [("c", f"{s}|{race['circuit']}")]


def drv_chain(code, team):
    return [("g", ""), ("team", team), ("d", code)]
