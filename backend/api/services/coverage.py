from __future__ import annotations

from api.models import DriverLapAnalysis, RaceResultData, SeasonSchedule


def _build_readiness(can_proceed, available_data, unavailable_data, message=None):
    return {
        "can_proceed": bool(can_proceed),
        "available_data": list(available_data),
        "unavailable_data": list(unavailable_data),
        "message": message,
        "warnings": [] if can_proceed else ([message] if message else []),
    }


def get_persistence_coverage(year: int, round_number: int | None = None) -> dict:
    schedule_record = SeasonSchedule.objects.filter(year=year).first()
    all_rounds = schedule_record.payload.get("races", []) if schedule_record else []

    if round_number is not None:
        all_rounds = [r for r in all_rounds if r.get("round") == round_number]

    if not all_rounds:
        return {
            "season": year,
            "round": round_number,
            "race_count": 0,
            "coverage": [],
            "readiness": _build_readiness(
                False,
                [],
                ["persistence_coverage"],
                f"No persisted coverage found for season {year}{f' round {round_number}' if round_number is not None else ''}.",
            ),
        }

    coverage = []
    for race in all_rounds:
        rnd = race.get("round")

        result_record = RaceResultData.objects.filter(year=year, round_number=rnd, session="R").first()
        results_list = result_record.payload.get("results", []) if result_record else []
        results_count = len(results_list)

        lap_rows = list(DriverLapAnalysis.objects.filter(year=year, round_number=rnd, session="R"))
        drivers_with_stints = sum(1 for row in lap_rows if row.payload.get("stints"))
        drivers_with_pace = sum(1 for row in lap_rows if row.payload.get("pace"))
        drivers_with_sectors = sum(1 for row in lap_rows if row.payload.get("sectors"))
        drivers_with_tyre = sum(1 for row in lap_rows if row.payload.get("tyre_strategy"))

        populated = results_count > 0

        counts = {
            "results": results_count,
            "stints": drivers_with_stints,
            "metrics": drivers_with_pace,
            "sectors": drivers_with_sectors,
            "tyre_strategy": drivers_with_tyre,
        }
        flags = {
            "race_detail": populated,
            "race_results": populated,
            "analysis_stints": drivers_with_stints > 0,
            "analysis_pace": drivers_with_pace > 0,
            "analysis_tyre_strategy": drivers_with_tyre > 0,
            "analysis_sector": drivers_with_sectors > 0,
        }
        flags["all_db_first_ready"] = all(flags.values())

        coverage.append(
            {
                "round": int(rnd),
                "race_name": race.get("name"),
                "status": "completed" if populated else "upcoming",
                "populated_at": None,
                "counts": counts,
                "db_first_flags": flags,
            }
        )

    return {
        "season": year,
        "round": round_number,
        "race_count": len(coverage),
        "coverage": coverage,
        "readiness": _build_readiness(True, ["persistence_coverage"], [], None),
    }