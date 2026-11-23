"""Numeric feature tables (race / driver / lap_window) from race dicts (see history.py). Leakage-free: a race's
features come from the tally of strictly earlier races; the race is added only after its rows are built.

Column groups are returned in the FeatureSet meta: `id` (strings/keys, not for the model), `target` (y_*),
`live_only` (known only once the race is running, e.g. a restart in this window), the rest are model features."""
import pandas as pd

from . import history as H

FEATURE_VERSION = "1"
MAX_ROWS, MAX_COLS = 60_000, 100  # Kumo Tabular pretraining scope
ERA_YEAR = 2022
TYPES = ("street", "hybrid", "permanent")
PROFILE = ("length_m", "corners", "wall_proximity", "overtaking_index", "elevation_range_m")
WEATHER = ("track_temp_c", "air_temp_c", "humidity_pct", "wind_speed_ms", "rain_frac")


def _static(race, counts) -> dict:
    ch = H.race_chain(race)
    f = {"year": race["year"], "round": race["round"], "era_2022": int(race["year"] >= ERA_YEAR),
         "total_laps": race["total_laps"], "prior_races": counts.races,
         "circuit_lane_rel": counts.lane_rel(race["circuit"])}
    f.update({f"circuit_is_{t}": (int(race["ctype"] == t) if race["ctype"] else None) for t in TYPES})  # one-hot
    f.update({k: race["profile"].get(k) for k in PROFILE})
    f.update({k: race["weather"].get(k) for k in WEATHER})
    for t in H.RACE_TARGETS:
        f[f"glob_{t}"] = counts.rate("race", t, ch[:1])[0]
        f[f"type_{t}"] = counts.rate("race", t, ch[:2])[0] if race["ctype"] else None
        p, _, _, n = counts.rate("race", t, ch)
        f[f"circ_{t}"] = p
    f["circuit_prior_races"] = counts.rate("race", "sc_vsc_red", ch)[3]
    return f


def _window_flags(race, w) -> dict:
    lo, hi = w["lap_start"], w["lap_end"]
    return {"first_window": int(w["window"] == 1),
            "live_restart_flag": int(any(e["type"] in ("sc", "red_flag") and e.get("end_lap") and lo <= e["end_lap"] <= hi
                                         for e in race["events"]))}


def build_tables(races) -> dict[str, pd.DataFrame]:
    """races: race dicts sorted by (year, round)."""
    counts = H.Counts()
    race_rows, drv_rows, win_rows = [], [], []
    for race in races:
        st, agg = _static(race, counts), race["agg"]
        ids = {"id_year": race["year"], "id_round": race["round"]}
        race_rows.append({**ids, **st, **{f"y_{t}": int(agg["race"][t] > 0) for t in H.RACE_TARGETS}})
        for code, d in race["drivers"].items():
            row = {**ids, "id_driver": code, "id_team": d["team"], **st,
                   "grid": d["grid"], "pit_lane_start": int(d["grid"] == 0), "field_size": len(race["drivers"])}
            for t in H.DRIVER_TARGETS:
                row[f"team_{t}"] = counts.rate("drv", t, H.drv_chain(code, d["team"])[:2])[0]
                p, _, _, n = counts.rate("drv", t, H.drv_chain(code, d["team"]))
                row[f"drv_{t}"] = p
                row[f"y_{t}"] = int(agg["drivers"].get(code, {}).get(t, 0) > 0)
            row["drv_prior_races"] = counts.rate("drv", "slow_stop", H.drv_chain(code, d["team"]))[3]
            drv_rows.append(row)
        for w in agg["windows"]:
            row = {**ids, "id_window": w["window"], **{k: st[k] for k in ("year", "round", "era_2022", "total_laps", "circuit_lane_rel",
                                                                          *[f"circuit_is_{t}" for t in TYPES], *PROFILE, *WEATHER)},
                   "window": w["window"], "lap_start": w["lap_start"], "lap_end": w["lap_end"],
                   "window_frac": w["lap_start"] / max(1, race["total_laps"]), **_window_flags(race, w)}
            for t in H.RACE_TARGETS:
                wc = H.win_chain(race, w["window"])
                row[f"glob_{t}"] = counts.rate("win", t, wc[:1])[0]
                row[f"type_{t}"] = counts.rate("win", t, wc[:2])[0] if race["ctype"] else None
                row[f"circ_{t}"] = counts.rate("win", t, wc)[0]
                row[f"y_{t}"] = int(w[t] > 0)
            win_rows.append(row)
        counts.update(race)  # only now: later races see this one, this one never saw itself
    return {k: _numeric(pd.DataFrame(v)) for k, v in (("race", race_rows), ("driver", drv_rows), ("lap_window", win_rows))}


def _numeric(df):
    """All-None columns (unknown traits) come out as object; force every non-id column to float/int with NaN."""
    num = [c for c in df.columns if not c.startswith("id_") or c in ("id_year", "id_round", "id_window")]
    df[num] = df[num].apply(pd.to_numeric)
    return df


def column_groups(df) -> dict:
    cols = list(df.columns)
    ids = [c for c in cols if c.startswith("id_")]
    tg = [c for c in cols if c.startswith("y_")]
    live = [c for c in cols if c == "live_restart_flag"]
    return {"id": ids, "target": tg, "live_only": live,
            "feature": [c for c in cols if c not in ids + tg]}


def check_limits(name, df):
    if len(df) > MAX_ROWS or len(df.columns) > MAX_COLS:
        raise ValueError(f"{name}: {len(df)} rows x {len(df.columns)} cols exceeds Kumo scope {MAX_ROWS} x {MAX_COLS}")
