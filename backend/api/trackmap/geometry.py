"""Pure geometry builder: pole-lap telemetry + circuit info -> TrackGeometry fields.

FastF1 3.8.1 names used (checked against the installed source):
  Lap.get_telemetry() -> Telemetry with X, Y, Z (1/10 m), Distance (m), DRS (int)
  Session.get_circuit_info().corners -> DataFrame X, Y, Number, Letter, Angle, Distance
  Session.laps.pick_fastest() -> Lap
Nothing here imports fastf1, so tests feed plain DataFrames.

Downsampling is a fixed distance step (lap_length / N_POINTS), not Douglas-Peucker:
Douglas-Peucker drops points on straights, which breaks index <-> distance lookup
and makes mini-sector / delta interpolation depend on where points happened to survive.
A uniform step is ~3.5 m on a 5.3 km lap, well below GPS noise.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

N_POINTS = 1500
N_MINI_SECTORS = 25
DRS_OPEN_MIN = 10  # FastF1 DRS channel: 0-14, even >= 10 means flap open (8 = eligible only)
MIN_DRS_ZONE_M = 50.0
_HASH_POINTS = 48  # coarse shape signature, see layout_hash()


def downsample(tel: pd.DataFrame, n_points: int = N_POINTS) -> dict:
    """Resample X/Y/Z onto a uniform distance grid of n_points samples."""
    t = tel.dropna(subset=["Distance", "X", "Y"]).sort_values("Distance")
    # np.interp needs increasing x; drop repeated distances (car stationary).
    t = t.drop_duplicates(subset="Distance")
    d = t["Distance"].to_numpy(float)
    if len(d) < 2 or d[-1] <= d[0]:
        raise ValueError("telemetry has no usable distance range")
    grid = np.linspace(d[0], d[-1], n_points)
    out = {}
    for col in ("X", "Y", "Z"):
        src = t[col].to_numpy(float) if col in t else np.zeros(len(d))
        out[col.lower()] = np.interp(grid, d, np.nan_to_num(src))
    return {
        "x": [round(float(v), 1) for v in out["x"]],
        "y": [round(float(v), 1) for v in out["y"]],
        "z": [round(float(v), 1) for v in out["z"]],
        "distance": [round(float(v), 2) for v in grid],
    }


def drs_zones(tel: pd.DataFrame) -> list[dict]:
    """Contiguous runs where the DRS channel is open, as {start_m, end_m}."""
    if "DRS" not in tel:
        return []
    t = tel.dropna(subset=["Distance"]).sort_values("Distance")
    open_ = t["DRS"].fillna(0).to_numpy() >= DRS_OPEN_MIN
    dist = t["Distance"].to_numpy(float)
    zones, start = [], None
    for i, o in enumerate(open_):
        if o and start is None:
            start = dist[i]
        elif not o and start is not None:
            zones.append((start, dist[i - 1]))
            start = None
    if start is not None:
        zones.append((start, dist[-1]))
    # ponytail: a zone open across the start line stays two zones; merge if a circuit needs it.
    return [
        {"start_m": round(float(a), 1), "end_m": round(float(b), 1)}
        for a, b in zones
        if b - a >= MIN_DRS_ZONE_M
    ]


def corners_list(corners: pd.DataFrame | None) -> list[dict]:
    if corners is None or len(corners) == 0:
        return []
    out = []
    for _, r in corners.iterrows():
        out.append({
            "number": int(r["Number"]),
            "letter": str(r["Letter"]) if pd.notna(r["Letter"]) else "",
            "angle": round(float(r["Angle"]), 1),
            "distance": round(float(r["Distance"]), 1) if pd.notna(r["Distance"]) else None,
            "x": round(float(r["X"]), 1),
            "y": round(float(r["Y"]), 1),
        })
    return sorted(out, key=lambda c: (c["distance"] is None, c["distance"] or 0))


def mini_sectors(length_m: float, corners: list[dict], n: int = N_MINI_SECTORS) -> dict:
    """Both schemes as boundary lists in metres (len = sectors + 1, first 0, last length)."""
    step = length_m / n
    equal = [round(i * step, 2) for i in range(n + 1)]
    anchors = [c for c in corners if c["distance"] is not None]
    # Corner-anchored: one sector per corner, cut at the midpoint between neighbours.
    cuts = [round((a["distance"] + b["distance"]) / 2, 2) for a, b in zip(anchors, anchors[1:])]
    return {
        "distance": {"boundaries": equal},
        "corners": {
            "boundaries": [0.0, *cuts, round(length_m, 2)] if anchors else equal,
            "labels": [f"T{c['number']}{c['letter']}" for c in anchors],
        },
    }


def layout_hash(points: dict, n: int = _HASH_POINTS) -> str:
    """Hash of a coarse shape signature, so the same layout hashes the same across
    sessions/years despite racing-line noise: lap length to 25 m, plus n points at
    fixed fractions of the lap with positions rounded to 20 m (200 units).
    ponytail: values sitting on a rounding edge can flip the hash; the cost is one
    extra TrackGeometry row, not wrong data. Switch to a shape-distance match if that bites.
    """
    d = points["distance"]
    length = d[-1] - d[0]
    idx = np.linspace(0, len(d) - 1, n).round().astype(int)
    sig = {
        "len": int(round(length / 25.0)),
        "xy": [[int(round(points["x"][i] / 200.0)), int(round(points["y"][i] / 200.0))] for i in idx],
    }
    return hashlib.sha256(json.dumps(sig, separators=(",", ":")).encode()).hexdigest()


def build_geometry(tel: pd.DataFrame, corners: pd.DataFrame | None) -> dict:
    """tel: pole-lap telemetry (X, Y, Z, Distance, DRS). Returns TrackGeometry field values."""
    points = downsample(tel)
    length = points["distance"][-1]
    clist = corners_list(corners)
    return {
        "layout_hash": layout_hash(points),
        "points": points,
        "corners": clist,
        "mini_sectors": mini_sectors(length, clist),
        "drs_zones": drs_zones(tel),
    }


def build_from_session(session) -> tuple[int, dict, str]:
    """Pull the pole lap and circuit info out of a loaded FastF1 Session."""
    lap = session.laps.pick_fastest()
    if lap is None:
        raise ValueError("no fastest lap")
    tel = lap.get_telemetry()
    info = session.get_circuit_info()
    fields = build_geometry(tel, info.corners if info is not None else None)
    circuit_key = int(session.session_info["Meeting"]["Circuit"]["Key"])
    return circuit_key, fields, f"{lap.get('Driver', '?')} pole lap"
