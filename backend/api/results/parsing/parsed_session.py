"""
ParsedSession — single-pass extraction of all derivative metrics from a loaded
FastF1 session object.

Architecture:
    LOAD SESSION (1 time via _load_session_with_readiness)
        ↓
    parse_session_once(session)  →  ParsedSession dataclass
        ├─ lap_data       (per-lap rows)
        ├─ stint_data      (per-driver per-stint aggregates)
        ├─ pace_data       (per-driver pace aggregates)
        ├─ sector_data     (per-driver best/median sector times)
        ├─ tyre_strategy   (stint + degradation metrics)
        └─ race_results    (from session.results — positions, gaps, etc.)

All downstream consumers (serializers, DB persistence) read from the
ParsedSession object instead of re-loading and re-parsing the session.

Field names and computation logic match the existing analysis functions in
api/services/analysis.py and api/results/services/race.py so serializers and
DB schemas don't break.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers (inlined from analysis.py to avoid circular imports)
# ---------------------------------------------------------------------------

def _safe_int(value):
    if pd.isna(value):
        return None
    return int(value)


def _safe_float(value, precision=3):
    if value is None or pd.isna(value):
        return None
    return round(float(value), precision)


def _safe_time_str(value):
    if pd.isna(value):
        return None
    return str(value)


def _safe_bool(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    return bool(value)


def _lap_seconds(value):
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "total_seconds"):
        return value.total_seconds()
    try:
        return pd.to_timedelta(value).total_seconds()
    except Exception:
        return None


def _format_lap_time(td):
    """Format a timedelta as M:SS.mmm string."""
    if td is None or pd.isnull(td):
        return None
    try:
        total = td.total_seconds()
        minutes = int(total // 60)
        seconds = total % 60
        return f"{minutes}:{seconds:06.3f}"
    except Exception:
        return str(td)


def _format_gap(gap, position):
    if pd.isna(position):
        position = None
    if position == 1:
        return "LEADER"
    if pd.isnull(gap):
        return "+DNF"
    try:
        if hasattr(gap, "total_seconds"):
            gap_seconds = gap.total_seconds()
            return f"+{gap_seconds:.3f}s"
        else:
            gap_str = str(gap).strip()
            if not gap_str.startswith("+"):
                return f"+{gap_str}"
            return gap_str
    except Exception:
        return "+DNF"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class ParsedSession:
    """Holds all pre-computed data for a single session.

    Created by ``parse_session_once`` — do NOT instantiate directly.
    """

    # Raw metadata
    year: int
    round_number: int
    session_type: str

    # Derivative data (all lists of plain dicts)
    lap_data: list[dict] = field(default_factory=list)
    stint_data: list[dict] = field(default_factory=list)
    pace_data: list[dict] = field(default_factory=list)
    sector_data: list[dict] = field(default_factory=list)
    tyre_strategy: list[dict] = field(default_factory=list)
    race_results: list[dict] = field(default_factory=list)
    qualifying_results: list[dict] = field(default_factory=list)
    practice_results: list[dict] = field(default_factory=list)

    # Per-driver views for DB persistence
    stints_by_driver: dict[str, list] = field(default_factory=dict)
    pace_by_driver: dict[str, dict] = field(default_factory=dict)
    sectors_by_driver: dict[str, dict] = field(default_factory=dict)
    tyre_by_driver: dict[str, list] = field(default_factory=dict)
    laps_by_driver: dict[str, list] = field(default_factory=dict)

    # All driver codes found
    all_drivers: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def parse_session_once(
    session,
    year: int,
    round_number: int,
    session_type: str = "R",
) -> ParsedSession:
    """Extract all analysis data from a loaded FastF1 session in a single pass.

    Args:
        session: A fully-loaded FastF1 session object (session.load() done).
        year: Season year.
        round_number: Race round.
        session_type: Session identifier (R, Q, FP1, etc.).

    Returns:
        A populated ParsedSession.
    """
    parsed = ParsedSession(
        year=year,
        round_number=round_number,
        session_type=session_type,
    )

    # ── Session results (from session.results) ──────────────────────────
    if session_type == "Q":
        parsed.qualifying_results = _extract_qualifying_results(session)
    elif session_type in ["FP1", "FP2", "FP3"]:
        parsed.practice_results = _extract_practice_results(session)
    else:
        # R, S, SQ all use race-style results
        parsed.race_results = _extract_race_results(session)

    # ── Lap-level analysis (from session.laps) ───────────────────────
    laps_df = _get_valid_laps(session)
    if laps_df is not None and not laps_df.empty:
        # Pre-compute seconds columns once
        laps_df = laps_df.copy()
        laps_df["lap_seconds"] = laps_df["LapTime"].apply(_lap_seconds)
        laps_df["s1_seconds"] = laps_df["Sector1Time"].apply(_lap_seconds)
        laps_df["s2_seconds"] = laps_df["Sector2Time"].apply(_lap_seconds)
        laps_df["s3_seconds"] = laps_df["Sector3Time"].apply(_lap_seconds)

        parsed.lap_data = _extract_lap_data(laps_df)
        parsed.stint_data = _extract_stint_data(laps_df)
        parsed.pace_data = _extract_pace_data(laps_df)
        parsed.sector_data = _extract_sector_data(laps_df)
        parsed.tyre_strategy = _extract_tyre_strategy(laps_df)

        # Build per-driver views for DB persistence
        _build_per_driver_views(parsed, laps_df, session)

    logger.info(
        "event=parse_session_once year=%s round=%s session=%s "
        "laps=%d stints=%d pace=%d sectors=%d tyre=%d results=%d drivers=%d",
        year, round_number, session_type,
        len(parsed.lap_data), len(parsed.stint_data),
        len(parsed.pace_data), len(parsed.sector_data),
        len(parsed.tyre_strategy), len(parsed.race_results),
        len(parsed.all_drivers),
    )
    return parsed


# ---------------------------------------------------------------------------
# Extractors — each runs on pre-computed DataFrames (no extra .load())
# ---------------------------------------------------------------------------

def _get_valid_laps(session) -> Optional[pd.DataFrame]:
    """Get laps with valid LapTime from the session."""
    try:
        laps = session.laps
        if laps is None or laps.empty:
            return None
        if "LapTime" not in laps.columns:
            return None
        return laps[laps["LapTime"].notna()].copy()
    except Exception:
        return None


def _extract_race_results(session) -> list[dict]:
    """Extract race results — mirrors get_race_session_results() exactly."""
    try:
        results = session.results
        if results is None or results.empty:
            return []
    except Exception:
        return []

    results = results.copy()
    race_data = []

    # Calculate fastest laps
    fastest_laps = None
    fastest_driver_num = None
    try:
        if hasattr(session, "laps") and not session.laps.empty and "LapTime" in session.laps.columns:
            laps = session.laps
            fastest_laps = (
                laps.groupby("DriverNumber")["LapTime"]
                .min()
                .reset_index()
                .rename(columns={"LapTime": "FastestLap"})
            )
            raw_fastest = laps.groupby("DriverNumber")["LapTime"].min()
            if not raw_fastest.empty:
                fastest_driver_num = raw_fastest.idxmin()
    except Exception as e:
        logger.warning("Failed to calculate fastest laps: %s", e)

    if fastest_laps is not None and not fastest_laps.empty:
        results = results.merge(fastest_laps, on="DriverNumber", how="left")
    else:
        results["FastestLap"] = pd.NaT

    for _, row in results.iterrows():
        position = int(row["Position"]) if pd.notna(row.get("Position", None)) else None
        gap = None
        raw_gap = row.get("Time") if "Time" in row else None
        if position == 1:
            gap = "LEADER"
        else:
            gap = _format_gap(raw_gap, position)

        fastest_lap_str = None
        if "FastestLap" in row:
            fastest_lap_str = _format_lap_time(row["FastestLap"])

        driver_number_str = str(row["DriverNumber"]) if pd.notna(row.get("DriverNumber")) else None
        is_fastest_of_race = (
            (driver_number_str == str(fastest_driver_num))
            if fastest_driver_num and driver_number_str
            else False
        )

        race_data.append({
            "position": position,
            "driver_number": int(row["DriverNumber"]) if pd.notna(row.get("DriverNumber", None)) else None,
            "driver_name": row.get("FullName", "Unknown"),
            "team": row.get("TeamName", "Unknown"),
            "points": int(row["Points"]) if pd.notna(row.get("Points", None)) else 0,
            "status": row.get("Status", "Unknown"),
            "grid_position": int(row["GridPosition"]) if pd.notna(row.get("GridPosition", None)) else None,
            "laps": int(row["Laps"]) if pd.notna(row.get("Laps", None)) else 0,
            "gap": gap,
            "fastest_lap": fastest_lap_str,
            "fastest_lap_of_race": is_fastest_of_race,
        })

    return race_data


def _extract_qualifying_results(session) -> list[dict]:
    """Extract qualifying results."""
    try:
        results = session.results
        if results is None or results.empty:
            return []
    except Exception:
        return []

    results = results.copy()
    qualifying_data = []

    for _, row in results.iterrows():
        if pd.notna(row.get('Q1', None)):
            qualifying_info = {
                'position': int(row['Position']) if pd.notna(row.get('Position', None)) else None,
                'driver_number': int(row['DriverNumber']) if pd.notna(row.get('DriverNumber', None)) else None,
                'driver_name': row.get('FullName', 'Unknown'),
                'team': row.get('TeamName', 'Unknown'),
                'q1_time': _format_lap_time(row.get('Q1')),
                'q2_time': _format_lap_time(row.get('Q2')),
                'q3_time': _format_lap_time(row.get('Q3')),
            }
            qualifying_data.append(qualifying_info)
    return qualifying_data


def _extract_practice_results(session) -> list[dict]:
    """Extract practice results (fastest laps)."""
    try:
        results = session.results
        if results is None or results.empty:
            return []
    except Exception:
        return []

    results = results.copy()
    practice_data = []

    # Calculate fastest laps
    fastest_laps = None
    try:
        if hasattr(session, "laps") and not session.laps.empty and "LapTime" in session.laps.columns:
            laps = session.laps
            fastest_laps = (
                laps.groupby("DriverNumber")["LapTime"]
                .min()
                .reset_index()
                .rename(columns={"LapTime": "FastestLap"})
            )
    except Exception:
        pass

    if fastest_laps is not None and not fastest_laps.empty:
        results = results.merge(fastest_laps, on="DriverNumber", how="left")
    else:
        results["FastestLap"] = pd.NaT

    # Sort by fastest lap
    results = results.sort_values(by="FastestLap").reset_index(drop=True)

    for idx, row in results.iterrows():
        if pd.notna(row.get('FastestLap')):
            practice_info = {
                'position': int(idx) + 1,
                'driver_number': int(row['DriverNumber']) if pd.notna(row.get('DriverNumber', None)) else None,
                'driver_name': row.get('FullName', 'Unknown'),
                'team': row.get('TeamName', 'Unknown'),
                'fastest_lap': _format_lap_time(row['FastestLap']),
            }
            practice_data.append(practice_info)
    return practice_data


def _extract_lap_data(laps: pd.DataFrame) -> list[dict]:
    """Extract per-lap rows — mirrors get_lap_analysis() logic."""
    rows = []
    for _, row in laps.iterrows():
        rows.append({
            "driver_code": row.get("Driver", "Unknown"),
            "lap_number": _safe_int(row.get("LapNumber")),
            "lap_time": _safe_time_str(row.get("LapTime")),
            "sector1": _safe_time_str(row.get("Sector1Time")),
            "sector2": _safe_time_str(row.get("Sector2Time")),
            "sector3": _safe_time_str(row.get("Sector3Time")),
            "compound": row.get("Compound") if pd.notna(row.get("Compound")) else None,
            "stint": _safe_int(row.get("Stint")),
            "is_personal_best": _safe_bool(row.get("IsPersonalBest")),
        })
    return rows


def _extract_stint_data(laps: pd.DataFrame) -> list[dict]:
    """Extract stint aggregates — mirrors get_stint_analysis() logic."""
    stint_laps = laps[laps["Stint"].notna()]
    if stint_laps.empty:
        return []

    grouped = (
        stint_laps.groupby(["Driver", "DriverNumber", "Stint"], dropna=True)
        .agg(
            compound=("Compound", lambda s: s.dropna().iloc[-1] if not s.dropna().empty else None),
            lap_start=("LapNumber", "min"),
            lap_end=("LapNumber", "max"),
            total_laps=("LapNumber", "count"),
            avg_lap_seconds=("lap_seconds", "mean"),
            median_lap_seconds=("lap_seconds", "median"),
            min_lap_seconds=("lap_seconds", "min"),
            max_lap_seconds=("lap_seconds", "max"),
        )
        .reset_index()
    )
    grouped = grouped.sort_values(by=["Driver", "Stint"], ascending=[True, True])

    rows = []
    for _, row in grouped.iterrows():
        rows.append({
            "driver_code": row.get("Driver", "Unknown"),
            "driver_number": _safe_int(row.get("DriverNumber")),
            "stint_number": _safe_int(row.get("Stint")),
            "compound": row.get("compound") if pd.notna(row.get("compound")) else None,
            "lap_start": _safe_int(row.get("lap_start")),
            "lap_end": _safe_int(row.get("lap_end")),
            "total_laps": _safe_int(row.get("total_laps")) or 0,
            "laps_in_stint": _safe_int(row.get("total_laps")) or 0,
            "avg_lap_seconds": _safe_float(row.get("avg_lap_seconds")),
            "median_lap_seconds": _safe_float(row.get("median_lap_seconds")),
            "min_lap_seconds": _safe_float(row.get("min_lap_seconds")),
            "max_lap_seconds": _safe_float(row.get("max_lap_seconds")),
        })
    return rows


def _extract_pace_data(laps: pd.DataFrame) -> list[dict]:
    """Extract driver pace aggregates — mirrors get_pace_analysis() logic."""
    rows = []
    for (driver_code, driver_number), group in laps.groupby(["Driver", "DriverNumber"], dropna=True):
        group = group.sort_values(by="LapNumber")
        lap_seconds = group["lap_seconds"].dropna()
        lap_count = int(lap_seconds.shape[0])

        improvement = None
        if lap_count >= 6:
            segment_size = max(1, lap_count // 3)
            first_segment = lap_seconds.iloc[:segment_size]
            last_segment = lap_seconds.iloc[-segment_size:]
            if not first_segment.empty and not last_segment.empty:
                improvement = first_segment.median() - last_segment.median()

        rows.append({
            "driver_code": str(driver_code),
            "driver_number": _safe_int(driver_number),
            "laps_completed": lap_count,
            "session_median_lap_seconds": _safe_float(lap_seconds.median()),
            "session_best_lap_seconds": _safe_float(lap_seconds.min()),
            "consistency_stddev_seconds": _safe_float(lap_seconds.std()),
            "pace_improvement_seconds": _safe_float(improvement),
        })

    rows = sorted(
        rows,
        key=lambda r: (r["session_median_lap_seconds"] is None, r["session_median_lap_seconds"]),
    )
    return rows


def _extract_sector_data(laps: pd.DataFrame) -> list[dict]:
    """Extract sector-level pace — mirrors get_sector_analysis() logic."""
    rows = []
    for (driver_code, driver_number), group in laps.groupby(["Driver", "DriverNumber"], dropna=True):
        lap_seconds = group["lap_seconds"].dropna()
        s1 = group["s1_seconds"].dropna()
        s2 = group["s2_seconds"].dropna()
        s3 = group["s3_seconds"].dropna()

        best_s1 = _safe_float(s1.min()) if not s1.empty else None
        best_s2 = _safe_float(s2.min()) if not s2.empty else None
        best_s3 = _safe_float(s3.min()) if not s3.empty else None

        theoretical_best = None
        if best_s1 is not None and best_s2 is not None and best_s3 is not None:
            theoretical_best = _safe_float(best_s1 + best_s2 + best_s3)

        best_lap = _safe_float(lap_seconds.min()) if not lap_seconds.empty else None
        delta_to_theoretical = None
        if best_lap is not None and theoretical_best is not None:
            delta_to_theoretical = _safe_float(best_lap - theoretical_best)

        rows.append({
            "driver_code": str(driver_code),
            "driver_number": _safe_int(driver_number),
            "laps_count": int(lap_seconds.shape[0]),
            "best_sector1_seconds": best_s1,
            "best_sector2_seconds": best_s2,
            "best_sector3_seconds": best_s3,
            "median_sector1_seconds": _safe_float(s1.median()) if not s1.empty else None,
            "median_sector2_seconds": _safe_float(s2.median()) if not s2.empty else None,
            "median_sector3_seconds": _safe_float(s3.median()) if not s3.empty else None,
            "best_lap_seconds": best_lap,
            "theoretical_best_lap_seconds": theoretical_best,
            "delta_to_theoretical_seconds": delta_to_theoretical,
        })

    rows = sorted(
        rows,
        key=lambda item: (
            item["theoretical_best_lap_seconds"] is None,
            item["theoretical_best_lap_seconds"],
        ),
    )
    return rows


def _extract_tyre_strategy(laps: pd.DataFrame) -> list[dict]:
    """Extract tyre strategy — mirrors get_tyre_strategy_analysis() logic."""
    stint_laps = laps[laps["Stint"].notna()]
    if stint_laps.empty:
        return []

    rows = []
    for (driver_code, driver_number, stint_number), group in stint_laps.groupby(
        ["Driver", "DriverNumber", "Stint"], dropna=True
    ):
        group = group.sort_values(by="LapNumber")
        lap_seconds = group["lap_seconds"].dropna()
        lap_count = int(lap_seconds.shape[0])

        degradation = None
        if lap_count >= 4:
            split = max(1, lap_count // 2)
            start_segment = lap_seconds.iloc[:split]
            end_segment = lap_seconds.iloc[-split:]
            if not start_segment.empty and not end_segment.empty:
                degradation = end_segment.median() - start_segment.median()

        compound_values = group["Compound"].dropna()
        compound = compound_values.iloc[-1] if not compound_values.empty else None

        rows.append({
            "driver_code": str(driver_code),
            "driver_number": _safe_int(driver_number),
            "stint_number": _safe_int(stint_number),
            "compound": compound,
            "lap_start": _safe_int(group["LapNumber"].min()),
            "lap_end": _safe_int(group["LapNumber"].max()),
            "laps_in_stint": lap_count,
            "avg_lap_seconds": _safe_float(lap_seconds.mean()),
            "median_lap_seconds": _safe_float(lap_seconds.median()),
            "degradation_seconds": _safe_float(degradation),
        })

    rows = sorted(rows, key=lambda item: (item["driver_code"], item["stint_number"]))
    return rows


# ---------------------------------------------------------------------------
# Per-driver views (for DB persistence via store_driver_lap_analysis)
# ---------------------------------------------------------------------------

def _build_per_driver_views(parsed: ParsedSession, laps: pd.DataFrame, session) -> None:
    """Build per-driver dicts from the already-computed aggregate lists.

    Also builds ``laps_by_driver`` from the raw session laps so we can
    persist the original lap-time strings (matching populate_race._build_lap_data).
    """
    # Stints by driver
    for row in parsed.stint_data:
        dc = str(row.get("driver_code") or "").upper().strip()
        if dc:
            parsed.stints_by_driver.setdefault(dc, []).append(row)

    # Pace by driver (single dict per driver)
    for row in parsed.pace_data:
        dc = str(row.get("driver_code") or "").upper().strip()
        if dc:
            parsed.pace_by_driver[dc] = {
                "laps_completed": row.get("laps_completed", 0),
                "session_median_lap_seconds": row.get("session_median_lap_seconds"),
                "session_best_lap_seconds": row.get("session_best_lap_seconds"),
                "consistency_stddev_seconds": row.get("consistency_stddev_seconds"),
                "pace_improvement_seconds": row.get("pace_improvement_seconds"),
                "driver_number": row.get("driver_number"),
            }

    # Sectors by driver (single dict per driver)
    for row in parsed.sector_data:
        dc = str(row.get("driver_code") or "").upper().strip()
        if dc:
            parsed.sectors_by_driver[dc] = {
                "laps_count": row.get("laps_count", 0),
                "best_sector1_seconds": row.get("best_sector1_seconds"),
                "best_sector2_seconds": row.get("best_sector2_seconds"),
                "best_sector3_seconds": row.get("best_sector3_seconds"),
                "median_sector1_seconds": row.get("median_sector1_seconds"),
                "median_sector2_seconds": row.get("median_sector2_seconds"),
                "median_sector3_seconds": row.get("median_sector3_seconds"),
                "best_lap_seconds": row.get("best_lap_seconds"),
                "theoretical_best_lap_seconds": row.get("theoretical_best_lap_seconds"),
                "delta_to_theoretical_seconds": row.get("delta_to_theoretical_seconds"),
                "driver_number": row.get("driver_number"),
            }

    # Tyre strategy by driver
    for row in parsed.tyre_strategy:
        dc = str(row.get("driver_code") or "").upper().strip()
        if dc:
            parsed.tyre_by_driver.setdefault(dc, []).append(row)

    # Build laps_by_driver from raw session.laps (matching _build_lap_data format)
    try:
        all_laps = session.laps
        if all_laps is not None and not all_laps.empty:
            for dc in set(laps["Driver"].dropna().unique()):
                dc_upper = str(dc).upper()
                driver_laps = all_laps[all_laps["Driver"] == dc]
                lap_list = []
                for _, lap in driver_laps.iterrows():
                    if lap.get("LapTime") is None or str(lap.get("LapTime")) == "NaT":
                        continue
                    lap_list.append({
                        "lap_number": int(lap["LapNumber"]),
                        "lap_time": str(lap["LapTime"]),
                        "sector1": str(lap.get("Sector1Time", "")),
                        "sector2": str(lap.get("Sector2Time", "")),
                        "sector3": str(lap.get("Sector3Time", "")),
                        "compound": str(lap.get("Compound", "")),
                        "stint": int(lap.get("Stint", 0)),
                        "is_personal_best": bool(lap.get("IsPersonalBest", False)),
                    })
                parsed.laps_by_driver[dc_upper] = lap_list
    except Exception as e:
        logger.warning("Failed to build laps_by_driver: %s", e)

    # Collect all driver codes
    parsed.all_drivers = (
        set(parsed.stints_by_driver)
        | set(parsed.pace_by_driver)
        | set(parsed.sectors_by_driver)
        | set(parsed.tyre_by_driver)
        | set(parsed.laps_by_driver)
    )
