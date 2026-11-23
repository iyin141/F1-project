"""Pure label logic (no DB). Inputs are the stored payload rows; outputs are plain dicts shaped like RaceEventLabel.

Stored formats this relies on (see api/services/unified_service.py extractors):
- TrackStatusData rows: {lap_number, status, ...}. `status` is FastF1's code as a string: 1 clear, 2 yellow,
  4 SC, 5 red, 6 VSC, 7 VSC ending. The extractor reads a "Lap" column that FastF1's track_status does not have,
  so lap_number is probably None in real data; laps are then taken from race-control messages (see neutral_events).
- IncidentData rows (race control): {lap_number, flag, message_text}.
- PitStopData rows: {driver_code, driver_number, lap_in, stop_duration_seconds} where the duration is PIT-LANE
  time (PitInTime -> PitOutTime), not stationary time. Stationary time is not stored.
- RaceResultData rows: {driver_number, team, status, laps, ...}; no driver code.
"""
import re
import statistics
from pathlib import Path

import yaml

DATA = Path(__file__).parent / "data"
WINDOW = 5
SLOW_PERCENTILE = 90
MIN_STOPS_FOR_THRESHOLD = 20  # ponytail: below this a 90th percentile is noise; no slow_stop labels for that season
UNLUCKY_LAPS = 2

_CODES = {"1": "1", "2": "2", "4": "4", "5": "5", "6": "6", "7": "7",
          "allclear": "1", "yellow": "2", "scdeployed": "4", "red": "5", "vscdeployed": "6", "vscending": "7"}
_TYPE = {"4": "sc", "5": "red_flag", "6": "vsc"}
NEUTRAL = ("sc", "vsc", "red_flag")


# ---- DNF -----------------------------------------------------------------------------------------------

def load_status_map(path=None) -> dict:
    return yaml.safe_load(Path(path or DATA / "dnf_status_map.yaml").read_text(encoding="utf-8"))


def classify_status(status, smap) -> tuple[str | None, bool]:
    """(group, unmapped). group None = not a retirement. Unknown strings -> (fallback, True)."""
    s = str(status or "").strip().lower()
    if not s:
        return smap["fallback"], True
    nd = smap["not_dnf"]
    if s in nd["exact"] or any(re.match(r, s) for r in nd["regex"]):
        return None, False
    for group, names in smap["groups"].items():
        if s in [n.lower() for n in names]:
            return group, False
    return smap["fallback"], s not in ("retired", "withdrew")


def dnf_labels(year, rnd, results, ids, total_laps, smap) -> list[dict]:
    out = []
    for r in results:
        group, unmapped = classify_status(r.get("status"), smap)
        if group is None:
            continue
        laps = r.get("laps") or 0
        num = r.get("driver_number")
        out.append(dict(
            year=year, round_number=rnd, driver=ids.get(num, f"#{num}"), team=r.get("team") or "",
            type=f"dnf_{group}", source="results", mapping_version=str(smap["version"]),
            lap=min(laps + 1, total_laps) if total_laps else laps + 1,  # lap on which the car stopped
            detail={"status": r.get("status"), "laps_completed": laps, "unmapped": unmapped}))
    return out


# ---- SC / VSC / red -------------------------------------------------------------------------------------

def _rc_marks(rc_rows):
    """Race-control messages -> {'sc'|'vsc'|'red_flag': [start laps], 'sc_end': [...], 'vsc_end': [...]}."""
    marks = {k: [] for k in ("sc", "vsc", "red_flag", "sc_end", "vsc_end")}
    for m in rc_rows:
        t = str(m.get("message_text") or "").upper()
        lap = m.get("lap_number")
        if "VIRTUAL SAFETY CAR DEPLOYED" in t or t.startswith("VSC DEPLOYED"):
            marks["vsc"].append(lap)
        elif "VIRTUAL SAFETY CAR ENDING" in t or t.startswith("VSC ENDING"):
            marks["vsc_end"].append(lap)
        elif "SAFETY CAR DEPLOYED" in t:
            marks["sc"].append(lap)
        elif "SAFETY CAR IN THIS LAP" in t:
            marks["sc_end"].append(lap)
        elif t.strip() == "RED FLAG" or (str(m.get("flag") or "").upper() == "RED" and "RED FLAG" in t):
            marks["red_flag"].append(lap)
    return marks


def neutral_events(ts_rows, rc_rows) -> tuple[list[dict], list[str]]:
    """SC / VSC / red events with start and end lap, plus cross-check notes.

    Track status decides how many events there are and of what type (the status stream is walked once, so
    red-then-restart and SC, green, SC both come out right). Laps come from the track-status row when stored,
    else from the n-th race-control message of the same type. With no track status at all, race control alone is used.
    """
    marks = _rc_marks(rc_rows)
    events = []
    cur = None
    for row in ts_rows:
        code = _CODES.get(str(row.get("status", "")).strip().lower())
        lap = row.get("lap_number")
        if code in _TYPE:
            if cur and cur["type"] == _TYPE[code]:
                continue
            if cur:
                cur["end_lap"] = lap
            cur = dict(type=_TYPE[code], lap=lap, end_lap=None, source="track_status")
            events.append(cur)
        elif cur and (code in ("1", "2") or (code == "7" and cur["type"] == "vsc")):
            cur["end_lap"] = lap
            cur = None
    notes = []
    if not ts_rows:
        for t in NEUTRAL:
            events += [dict(type=t, lap=lap, end_lap=None, source="race_control") for lap in marks[t]]
    else:
        for t in NEUTRAL:
            laps = marks[t]
            mine = [e for e in events if e["type"] == t]
            agree = len(laps) == len(mine)
            if not agree:
                notes.append(f"{t}: track_status={len(mine)} race_control={len(laps)}")
            ends = marks.get(f"{t}_end", [])
            for i, e in enumerate(mine):
                if e["lap"] is None and i < len(laps):
                    e["lap"] = laps[i]
                if agree:
                    e["source"] = "track_status+race_control"
                if e["end_lap"] is None and i < len(ends):
                    e["end_lap"] = ends[i]
    for e in events:
        if e["lap"] is not None and (e["end_lap"] is None or e["end_lap"] < e["lap"]):
            e["end_lap"] = e["lap"]  # ponytail: unknown end -> one lap; a stop on a later SC lap then reads as green
    return events, notes


# ---- pit stops ------------------------------------------------------------------------------------------

def season_threshold(durations) -> float | None:
    d = sorted(x for x in durations if x is not None and x > 0)
    if len(d) < MIN_STOPS_FOR_THRESHOLD:
        return None
    return statistics.quantiles(d, n=100, method="inclusive")[SLOW_PERCENTILE - 1]


def pit_labels(year, rnd, stops, neutral, threshold, teams) -> list[dict]:
    """slow_stop: lane time > season p90, and not on a red-flag lap. unlucky_stop: stop made under green
    (no earlier SC/VSC/red interval covers the lap) with an SC or VSC starting 0..2 laps later."""
    known = [e for e in neutral if e["lap"] is not None]
    out = []
    for s in stops:
        lap, code = s.get("lap_in"), s.get("driver_code") or ""
        if lap is None:
            continue
        base = dict(year=year, round_number=rnd, lap=lap, driver=code, team=teams.get(code, ""))
        dur = s.get("stop_duration_seconds")
        red_lap = any(e["type"] == "red_flag" and e["lap"] <= lap <= e["end_lap"] for e in known)
        if threshold and dur and dur > threshold and not red_lap:
            out.append({**base, "type": "slow_stop", "source": "pit_stops",
                        "detail": {"lane_seconds": dur, "threshold": round(threshold, 3), "stop_number": s.get("stop_number")}})
        under_neutral = any(e["lap"] < lap <= e["end_lap"] for e in known)
        nxt = [e for e in known if e["type"] in ("sc", "vsc") and 0 <= e["lap"] - lap <= UNLUCKY_LAPS]
        if nxt and not under_neutral and not red_lap:
            e = min(nxt, key=lambda e: e["lap"])
            out.append({**base, "type": "unlucky_stop", "source": "pit_stops+track_status",
                        "detail": {"followed_by": e["type"], "laps_before": e["lap"] - lap, "stop_number": s.get("stop_number")}})
    return out


# ---- aggregation ----------------------------------------------------------------------------------------

TARGETS = ["sc_vsc_red", "dnf_mechanical", "dnf_incident", "slow_stop", "unlucky_stop"]


def target_of(ev_type, smap) -> str | None:
    if ev_type in NEUTRAL:
        return "sc_vsc_red"
    if ev_type in ("slow_stop", "unlucky_stop"):
        return ev_type
    if ev_type.startswith("dnf_"):
        for name, groups in smap["targets"].items():
            if ev_type[4:] in groups:
                return name
    return None  # dnf_other feeds no target


def aggregate_labels(events, total_laps, drivers=(), smap=None, window=WINDOW) -> dict:
    """Event rows -> the plan's three granularities.

    race: count per target. drivers: per driver-race counts. windows: 1-based 5-lap windows; an event belongs to
    the window holding its (start) lap, events with an unresolved lap are left out of the windows.
    """
    smap = smap or load_status_map()
    zero = lambda: {n: 0 for n in TARGETS}  # noqa: E731
    race, per_driver = zero(), {d: zero() for d in drivers}
    n_win = -(-total_laps // window) if total_laps else 0
    wins = [zero() for _ in range(n_win)]
    for ev in events:
        tg = target_of(ev["type"], smap)
        if tg is None:
            continue
        race[tg] += 1
        if ev.get("driver") and tg != "sc_vsc_red":
            per_driver.setdefault(ev["driver"], zero())[tg] += 1
        lap = ev.get("lap")
        if lap and (lap - 1) // window < n_win:
            wins[(lap - 1) // window][tg] += 1
    return {"race": race, "drivers": per_driver,
            "windows": [{"window": i + 1, "lap_start": i * window + 1, "lap_end": min((i + 1) * window, total_laps), **w}
                        for i, w in enumerate(wins)]}
