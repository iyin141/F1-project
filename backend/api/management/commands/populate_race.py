from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from api.models import DriverMetric, Race, RaceResult, SectorAggregate, StintData
from api.services.analysis import get_pace_analysis, get_sector_analysis, get_stint_analysis
from api.services.fastf1_runtime import fastf1
from api.services.schedule import get_race_by_round


def _to_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_decimal(value, places: str = "0.000"):
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(Decimal(places))
    except Exception:
        return None


class Command(BaseCommand):
    help = "Populate persisted race data (results, stints, metrics) for one season/round"

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True, help="Season year, e.g. 2024")
        parser.add_argument("--round", type=int, required=True, dest="round_number", help="Round number, e.g. 5")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Recompute and overwrite persisted data even if race is already populated",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        year = options["year"]
        round_number = options["round_number"]
        force = options["force"]

        race_info = get_race_by_round(year, round_number)
        if race_info is None:
            raise CommandError(f"Race not found for season={year} round={round_number}")

        existing_race = Race.objects.filter(season=year, round_number=round_number).first()
        if (
            existing_race is not None
            and existing_race.populated_at is not None
            and existing_race.status == Race.Status.COMPLETED
            and not force
        ):
            self.stdout.write(
                self.style.WARNING(
                    f"Skipping season={year} round={round_number}: already populated (use --force to overwrite)."
                )
            )
            return

        race_defaults = {
            "race_name": race_info.get("name", f"Round {round_number}"),
            "circuit_name": race_info.get("name", "Unknown Circuit"),
            "country": race_info.get("country", "Unknown"),
            "location": race_info.get("location"),
            "race_date": race_info.get("date"),
            "status": Race.Status.UPCOMING,
            "fastf1_event_name": race_info.get("name"),
            "event_format": race_info.get("event_format"),
            "session1": race_info.get("session1"),
            "session1_date_utc": race_info.get("session1_date_utc"),
            "session2": race_info.get("session2"),
            "session2_date_utc": race_info.get("session2_date_utc"),
            "session3": race_info.get("session3"),
            "session3_date_utc": race_info.get("session3_date_utc"),
            "session4": race_info.get("session4"),
            "session4_date_utc": race_info.get("session4_date_utc"),
            "session5": race_info.get("session5"),
            "session5_date_utc": race_info.get("session5_date_utc"),
        }
        race, _ = Race.objects.update_or_create(
            season=year,
            round_number=round_number,
            defaults=race_defaults,
        )

        now = timezone.now()
        race.status = Race.Status.PROCESSING
        race.save(update_fields=["status", "updated_at"])

        if force:
            RaceResult.objects.filter(race=race).delete()
            StintData.objects.filter(race=race).delete()
            DriverMetric.objects.filter(race=race, season_aggregate=False).delete()
            SectorAggregate.objects.filter(race=race).delete()

        # 1) Persist race result rows from FastF1 race session
        session = fastf1.get_session(year, round_number, "R")
        session.load(laps=False, telemetry=False, weather=False, messages=False)

        for _, row in session.results.iterrows():
            driver_code = str(row.get("Abbreviation") or row.get("Driver") or "").upper().strip()
            if not driver_code:
                continue

            RaceResult.objects.update_or_create(
                race=race,
                driver_code=driver_code,
                defaults={
                    "driver_number": _to_int(row.get("DriverNumber")),
                    "driver_name": str(row.get("FullName") or "Unknown"),
                    "constructor_name": str(row.get("TeamName") or "Unknown"),
                    "grid_position": _to_int(row.get("GridPosition")),
                    "finish_position": _to_int(row.get("Position")),
                    "points": _to_decimal(row.get("Points"), "0.00") or Decimal("0.00"),
                    "status_text": str(row.get("Status") or ""),
                    "fastest_lap": False,
                    "laps_completed": _to_int(row.get("Laps")),
                },
            )

        # 2) Persist stint rows from existing analysis service
        stint_payload = get_stint_analysis(year=year, round_number=round_number, session="R")
        for row in stint_payload.get("data", []):
            stint_number = _to_int(row.get("stint_number"))
            driver_code = str(row.get("driver_code") or "").upper().strip()
            if not driver_code or stint_number is None:
                continue

            lap_start = _to_int(row.get("lap_start"))
            lap_end = _to_int(row.get("lap_end"))
            if lap_start is None or lap_end is None:
                continue

            StintData.objects.update_or_create(
                race=race,
                driver_code=driver_code,
                stint_number=stint_number,
                defaults={
                    "driver_number": _to_int(row.get("driver_number")),
                    "compound": row.get("compound"),
                    "lap_start": lap_start,
                    "lap_end": lap_end,
                    "laps_in_stint": _to_int(row.get("total_laps")) or (lap_end - lap_start + 1),
                    "avg_lap_seconds": _to_decimal(row.get("median_lap_seconds")),
                    "median_lap_seconds": _to_decimal(row.get("median_lap_seconds")),
                    "min_lap_seconds": _to_decimal(row.get("min_lap_seconds")),
                    "max_lap_seconds": _to_decimal(row.get("max_lap_seconds")),
                    "degradation_seconds": None,
                    "computed_at": now,
                },
            )

        # 3) Persist baseline per-race driver metrics from pace service
        pace_payload = get_pace_analysis(year=year, round_number=round_number, session="R")
        for row in pace_payload.get("data", []):
            driver_code = str(row.get("driver_code") or "").upper().strip()
            if not driver_code:
                continue

            DriverMetric.objects.update_or_create(
                race=race,
                driver_code=driver_code,
                season_aggregate=False,
                defaults={
                    "season": year,
                    "consistency_score": _to_decimal(row.get("consistency_stddev_seconds"), "0.0000"),
                    "raw_stddev_seconds": _to_decimal(row.get("consistency_stddev_seconds"), "0.0000"),
                    "normalized_stddev_seconds": None,
                    "normalized_cv": None,
                    "valid_lap_count": _to_int(row.get("laps_completed")) or 0,
                    "excluded_lap_count": 0,
                    "excluded_by_reason": {},
                    "avg_pace_seconds": _to_decimal(row.get("session_median_lap_seconds"), "0.000"),
                    "insufficient_data": False,
                    "formula_version": "consistency_v1",
                    "computed_at": now,
                },
            )

        # 4) Persist per-driver sector aggregates
        sector_payload = get_sector_analysis(year=year, round_number=round_number, session="R")
        for row in sector_payload.get("data", []):
            driver_code = str(row.get("driver_code") or "").upper().strip()
            if not driver_code:
                continue

            SectorAggregate.objects.update_or_create(
                race=race,
                driver_code=driver_code,
                defaults={
                    "driver_number": _to_int(row.get("driver_number")),
                    "laps_count": _to_int(row.get("laps_count")) or 0,
                    "best_sector1_seconds": _to_decimal(row.get("best_sector1_seconds")),
                    "best_sector2_seconds": _to_decimal(row.get("best_sector2_seconds")),
                    "best_sector3_seconds": _to_decimal(row.get("best_sector3_seconds")),
                    "median_sector1_seconds": _to_decimal(row.get("median_sector1_seconds")),
                    "median_sector2_seconds": _to_decimal(row.get("median_sector2_seconds")),
                    "median_sector3_seconds": _to_decimal(row.get("median_sector3_seconds")),
                    "best_lap_seconds": _to_decimal(row.get("best_lap_seconds")),
                    "theoretical_best_lap_seconds": _to_decimal(row.get("theoretical_best_lap_seconds")),
                    "delta_to_theoretical_seconds": _to_decimal(row.get("delta_to_theoretical_seconds")),
                    "computed_at": now,
                },
            )

        race.status = Race.Status.COMPLETED
        race.populated_at = now
        race.save(update_fields=["status", "populated_at", "updated_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Populated season={year} round={round_number} | "
                f"results={RaceResult.objects.filter(race=race).count()} "
                f"stints={StintData.objects.filter(race=race).count()} "
                f"metrics={DriverMetric.objects.filter(race=race, season_aggregate=False).count()} "
                f"sectors={SectorAggregate.objects.filter(race=race).count()}"
            )
        )
