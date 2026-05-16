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

logger = logging.getLogger(__name__)


def get_driver_season(driver_code: str, year: int) -> dict:
    """Get full season results for a driver."""
    driver_code = driver_code.upper()
    driver_id = resolve_driver_id(driver_code, year)
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

    return {
        "driver_code": driver_code.upper(),
        "driver_name": driver_name,
        "year": year,
        "total_races": len(result_races),
        "sprint_weekends": len(sprint_lookup),
        "races": result_races,
        "message": None if result_races else "No season data available",
    }
