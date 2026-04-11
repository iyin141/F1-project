from __future__ import annotations

from django.db.models import Count

from api.models import DriverMetric, Race, RaceResult, SectorAggregate, StintData


def _build_readiness(can_proceed, available_data, unavailable_data, message=None):
    return {
        "can_proceed": bool(can_proceed),
        "available_data": list(available_data),
        "unavailable_data": list(unavailable_data),
        "message": message,
        "warnings": [] if can_proceed else ([message] if message else []),
    }


def get_persistence_coverage(year: int, round_number: int | None = None) -> dict:
    races_qs = Race.objects.filter(season=year).order_by("round_number")
    if round_number is not None:
        races_qs = races_qs.filter(round_number=round_number)

    if not races_qs.exists():
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

    race_ids = list(races_qs.values_list("id", flat=True))

    results_counts = {
        row["race_id"]: row["count"]
        for row in RaceResult.objects.filter(race_id__in=race_ids)
        .values("race_id")
        .annotate(count=Count("id"))
    }
    stint_counts = {
        row["race_id"]: row["count"]
        for row in StintData.objects.filter(race_id__in=race_ids)
        .values("race_id")
        .annotate(count=Count("id"))
    }
    metric_counts = {
        row["race_id"]: row["count"]
        for row in DriverMetric.objects.filter(race_id__in=race_ids, season_aggregate=False)
        .values("race_id")
        .annotate(count=Count("id"))
    }
    sector_counts = {
        row["race_id"]: row["count"]
        for row in SectorAggregate.objects.filter(race_id__in=race_ids)
        .values("race_id")
        .annotate(count=Count("id"))
    }

    coverage = []
    for race in races_qs:
        populated = race.status == Race.Status.COMPLETED and race.populated_at is not None
        counts = {
            "results": int(results_counts.get(race.id, 0)),
            "stints": int(stint_counts.get(race.id, 0)),
            "metrics": int(metric_counts.get(race.id, 0)),
            "sectors": int(sector_counts.get(race.id, 0)),
        }
        flags = {
            "race_detail": populated,
            "race_results": populated and counts["results"] > 0,
            "analysis_stints": populated and counts["stints"] > 0,
            "analysis_pace": populated and counts["metrics"] > 0,
            "analysis_tyre_strategy": populated and counts["stints"] > 0,
            "analysis_sector": populated and counts["sectors"] > 0,
        }
        flags["all_db_first_ready"] = all(flags.values())

        coverage.append(
            {
                "round": int(race.round_number),
                "race_name": race.race_name,
                "status": race.status,
                "populated_at": race.populated_at.isoformat() if race.populated_at else None,
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