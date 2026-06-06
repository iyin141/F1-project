"""Driver season service — fetches a driver's race-by-race breakdown for a year."""
from __future__ import annotations

import logging

from api.drivers.jolpica_client import (
    resolve_driver_id,
    get_season_driver_map,
    fetch_season_results,
    fetch_season_qualifying,
    fetch_season_sprint,
)
from api.drivers.repository import resolve_driver_metadata, get_persisted_driver_season_breakdown

logger = logging.getLogger(__name__)


def get_driver_season(driver_code: str, year: int) -> dict:
    """Get full season results for a driver.

    `driver_code` may be a 3-letter FIA code or a Jolpica driverId. Detect
    Jolpica IDs and use them directly as `driver_id` to avoid unnecessary
    resolution calls.
    """
    # Treat only clearly-formed Jolpica ids (contain '_' or '-') as Jolpica ids.
    # Avoid treating long surnames like "HAMILTON" as Jolpica ids.
    is_jolpica_id = bool(driver_code and ("_" in driver_code or "-" in driver_code))

    normalized_code = driver_code if is_jolpica_id else (driver_code or "").upper()
    # Prefer DB-backed resolver which can match names or codes to Jolpica ids
    metadata = resolve_driver_metadata(driver_code, year)
    driver_id = metadata.get("driver_id") if metadata else None
    if not driver_id:
        driver_id = resolve_driver_id(normalized_code, year) if not is_jolpica_id else None

    # If still not resolved, attempt to match the identifier against the
    # Jolpica season driver map (family name or driver_id). This helps when
    # the DB is empty but the user supplied a surname like 'hamilton'.
    if not driver_id:
        try:
            season_map_try = get_season_driver_map(year)
            ident = (driver_code or "").strip().lower()
            for did, info in season_map_try.items():
                name = (info.get('name') or '').lower()
                if ident and (ident == did.lower() or ident in name.split() or ident == (info.get('code') or '').lower()):
                    driver_id = did
                    break
        except Exception:
            logger.debug("season-map fallback resolution failed", exc_info=True)
    if not driver_id:
        return {
            "driver_code": driver_code,
            "driver_name": None,
            "year": year,
            "total_races": 0,
            "sprint_weekends": 0,
            "races": [],
            "message": "Driver not found"
        }

    season_map = get_season_driver_map(year)
    driver_info = season_map.get(driver_id, {})
    driver_name = driver_info.get('name')

    # If we have a canonical 3-letter code from the season map, prefer
    # returning persisted DB payload if present rather than fetching from Jolpica.
    canonical_code = (driver_info.get('code') or None) if driver_info else None
    if canonical_code:
        persisted = get_persisted_driver_season_breakdown(canonical_code, year)
        if persisted:
            # Ensure we return a shape compatible with callers
            return {
                "driver_code": canonical_code,
                "driver_id": driver_id,
                "canonical_code": canonical_code,
                "driver_name": driver_name,
                "year": year,
                "total_races": len(persisted.get("races", [])),
                "sprint_weekends": 0,
                "races": persisted.get("races", []),
                "message": None,
            }

    # Ensure driver_id passed to Jolpica client is normalized
    driver_id = (driver_id or "").lower()

    races = fetch_season_results(year, driver_id)
    quali = fetch_season_qualifying(year, driver_id)
    
    quali_lookup = {}
    for q in quali:
        round_num = int(q.get('round', 0))
        qr_list = q.get('QualifyingResults', [])
        if qr_list:
            qr = qr_list[0]
            quali_lookup[round_num] = {
                "qualifying_position": int(qr.get('position', 0)) if qr.get('position') else None,
                "qualifying_time": (qr.get('Q3') or qr.get('Q2') or qr.get('Q1'))
            }

    sprint_races = fetch_season_sprint(year, driver_id)
    sprint_lookup = {}
    for s in sprint_races:
        round_num = int(s.get('round', 0))
        sr_list = s.get('SprintResults', [])
        if sr_list:
            sr = sr_list[0]
            sprint_lookup[round_num] = {
                "sprint_position": int(sr.get('position', 0)) if sr.get('position') else None,
                "sprint_points": float(sr.get('points', 0)) if sr.get('points') else None,
                "sprint_status": sr.get('status'),
                "sprint_grid": int(sr.get('grid', 0)) if sr.get('grid') else None,
                "sprint_laps": int(sr.get('laps', 0)) if sr.get('laps') else None,
                "sprint_fastest_lap": (sr.get('FastestLap', {}).get('rank') == '1')
            }

    result_races = []
    for race in races:
        round_num = int(race.get('round', 0))
        rr_list = race.get('Results', [])
        if not rr_list:
            continue
        rr = rr_list[0]

        q_data = quali_lookup.get(round_num, {
            "qualifying_position": None,
            "qualifying_time": None
        })

        s_data = sprint_lookup.get(round_num, {
            "sprint_position": None,
            "sprint_points": None,
            "sprint_status": None,
            "sprint_grid": None,
            "sprint_laps": None,
            "sprint_fastest_lap": None
        })

        fastest_lap = rr.get('FastestLap', {}).get('rank') == '1'
        pos_str = rr.get('position', '')
        finish_position = int(pos_str) if pos_str.isdigit() else None

        result_races.append({
            "year": year,
            "round": round_num,
            "race_name": race.get('raceName', ''),
            "location": race.get('Circuit', {}).get('Location', {}).get('locality', ''),
            "race_date": race.get('date'),
            "qualifying_position": q_data["qualifying_position"],
            "qualifying_time": q_data["qualifying_time"],
            "sprint_position": s_data["sprint_position"],
            "sprint_points": s_data["sprint_points"],
            "sprint_status": s_data["sprint_status"],
            "sprint_grid": s_data["sprint_grid"],
            "sprint_laps": s_data["sprint_laps"],
            "sprint_fastest_lap": s_data["sprint_fastest_lap"],
            "grid_position": int(rr.get('grid', 0)) if rr.get('grid') else None,
            "finish_position": finish_position,
            "points": float(rr.get('points', 0)) if rr.get('points') else 0.0,
            "status": rr.get('status'),
            "fastest_lap": fastest_lap,
            "laps_completed": int(rr.get('laps', 0)) if rr.get('laps') else None,
        })

    # If no races were found, attempt a single fallback: if the original
    # resolution treated the input as a Jolpica id, try resolving via the
    # DB-backed resolver (3-letter code / name) and retry once.
    if not result_races:
        logger.debug("No races found for driver_id=%s year=%s; attempting fallback resolution", driver_id, year)
        # Only attempt fallback if we didn't already use the DB resolver
        if is_jolpica_id:
            alt_driver_id = resolve_driver_id((driver_code or "").upper(), year)
        else:
            alt_driver_id = None

        if alt_driver_id and alt_driver_id != driver_id:
            alt_driver_id = alt_driver_id.lower()
            logger.debug("Retrying with alternate resolved driver_id=%s", alt_driver_id)
            races = fetch_season_results(year, alt_driver_id)
            # rebuild result_races from the fetched races
            result_races = []
            for race in races:
                round_num = int(race.get('round', 0))
                rr_list = race.get('Results', [])
                if not rr_list:
                    continue
                rr = rr_list[0]

                q_data = quali_lookup.get(round_num, {"qualifying_position": None, "qualifying_time": None})
                s_data = sprint_lookup.get(round_num, {"sprint_position": None, "sprint_points": None, "sprint_status": None, "sprint_grid": None, "sprint_laps": None, "sprint_fastest_lap": None})

                fastest_lap = rr.get('FastestLap', {}).get('rank') == '1'
                pos_str = rr.get('position', '')
                finish_position = int(pos_str) if pos_str.isdigit() else None

                result_races.append({
                    "year": year,
                    "round": round_num,
                    "race_name": race.get('raceName', ''),
                    "location": race.get('Circuit', {}).get('Location', {}).get('locality', ''),
                    "race_date": race.get('date'),
                    "qualifying_position": q_data["qualifying_position"],
                    "qualifying_time": q_data["qualifying_time"],
                    "sprint_position": s_data["sprint_position"],
                    "sprint_points": s_data["sprint_points"],
                    "sprint_status": s_data["sprint_status"],
                    "sprint_grid": s_data["sprint_grid"],
                    "sprint_laps": s_data["sprint_laps"],
                    "sprint_fastest_lap": s_data["sprint_fastest_lap"],
                    "grid_position": int(rr.get('grid', 0)) if rr.get('grid') else None,
                    "finish_position": finish_position,
                    "points": float(rr.get('points', 0)) if rr.get('points') else 0.0,
                    "status": rr.get('status'),
                    "fastest_lap": fastest_lap,
                    "laps_completed": int(rr.get('laps', 0)) if rr.get('laps') else None,
                })

    return {
        "input": driver_code,
        "driver_id": driver_id,
        "canonical_code": (driver_info.get('code') or None),
        "driver_name": driver_name,
        "year": year,
        "total_races": len(result_races),
        "sprint_weekends": len(sprint_lookup),
        "races": result_races,
        "message": None if result_races else "No season data available",
    }
