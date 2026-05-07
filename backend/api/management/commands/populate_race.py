"""Populate race and other session data into persisted JSONB models."""
from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from api.models import DriverLapAnalysis, PracticeResultData, QualifyingResultData, RaceResultData, SeasonSchedule
from api.services.analysis import get_pace_analysis, get_sector_analysis, get_stint_analysis
from api.services.fastf1_runtime import fastf1
from api.services.schedule import get_race_by_round
from api.services.store import (
    store_practice_results,
    store_qualifying_results,
    store_sprint_results,
    store_sprint_shootout_results,
)


def _to_int(value):
    """Convert value to int or None."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value):
    """Convert value to float or None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Populate persisted session data (results, analysis) for one season/round/session"

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True, help="Season year, e.g. 2024")
        parser.add_argument("--round", type=int, required=True, dest="round_number", help="Round number, e.g. 5")
        parser.add_argument(
            "--session",
            type=str,
            default="R",
            help="Session type: R (race, default), Q (qualifying), FP1/FP2/FP3 (practice), S (sprint), SQ (sprint shootout)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Recompute and overwrite persisted data even if session is already populated",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        year = options["year"]
        round_number = options["round_number"]
        session_type = str(options["session"]).upper()
        force = options["force"]
        logger.info("event=command_started command=populate_race year=%s round=%s session=%s force=%s", year, round_number, session_type, force)

        if session_type == "R":
            self._populate_race_session(year, round_number, force)
        elif session_type == "Q":
            self._populate_qualifying_session(year, round_number, force)
        elif session_type in ("FP1", "FP2", "FP3"):
            self._populate_practice_session(year, round_number, session_type, force)
        elif session_type == "S":
            self._populate_sprint_session(year, round_number, force)
        elif session_type == "SQ":
            self._populate_sprint_shootout_session(year, round_number, force)
        else:
            raise CommandError(f"Invalid session type: {session_type}. Must be R, Q, FP1, FP2, FP3, S, or SQ.")

    def _populate_race_session(self, year: int, round_number: int, force: bool):
        """Populate race session (R) with results and driver analysis."""
        race_info = get_race_by_round(year, round_number)
        if race_info is None:
            raise CommandError(f"Race not found for season={year} round={round_number}")

        # Skip if already populated and no --force
        existing_result = RaceResultData.objects.filter(
            year=year, round_number=round_number, session="R"
        ).first()
        if existing_result and existing_result.payload.get("results") and not force:
            self.stdout.write(
                self.style.WARNING(
                    f"Skipping season={year} round={round_number} session=R: already populated (use --force to overwrite)."
                )
            )
            return

        if force:
            RaceResultData.objects.filter(year=year, round_number=round_number, session="R").delete()
            DriverLapAnalysis.objects.filter(year=year, round_number=round_number, session="R").delete()

        # 1) Merge this round into SeasonSchedule
        schedule_record, _ = SeasonSchedule.objects.get_or_create(year=year, defaults={"payload": {"races": []}})
        races_list = schedule_record.payload.get("races", [])
        # Remove existing entry for this round if present
        races_list = [r for r in races_list if r.get("round") != round_number]
        races_list.append({
            "round": round_number,
            "name": race_info.get("name", f"Round {round_number}"),
            "date": race_info.get("date").isoformat() if hasattr(race_info.get("date"), "isoformat") else race_info.get("date"),
            "location": race_info.get("location"),
            "country": race_info.get("country", "Unknown"),
            "event_format": race_info.get("event_format"),
            "session1": race_info.get("session1"),
            "session1_date_utc": race_info.get("session1_date_utc").isoformat() if hasattr(race_info.get("session1_date_utc"), "isoformat") else race_info.get("session1_date_utc"),
            "session2": race_info.get("session2"),
            "session2_date_utc": race_info.get("session2_date_utc").isoformat() if hasattr(race_info.get("session2_date_utc"), "isoformat") else race_info.get("session2_date_utc"),
            "session3": race_info.get("session3"),
            "session3_date_utc": race_info.get("session3_date_utc").isoformat() if hasattr(race_info.get("session3_date_utc"), "isoformat") else race_info.get("session3_date_utc"),
            "session4": race_info.get("session4"),
            "session4_date_utc": race_info.get("session4_date_utc").isoformat() if hasattr(race_info.get("session4_date_utc"), "isoformat") else race_info.get("session4_date_utc"),
            "session5": race_info.get("session5"),
            "session5_date_utc": race_info.get("session5_date_utc").isoformat() if hasattr(race_info.get("session5_date_utc"), "isoformat") else race_info.get("session5_date_utc"),
        })
        races_list.sort(key=lambda r: r.get("round", 0))
        schedule_record.payload = {"races": races_list}
        schedule_record.save(update_fields=["payload", "updated_at"])

        # 2) Load FastF1 race session for results
        session = fastf1.get_session(year, round_number, "R")
        session.load(laps=False, telemetry=False, weather=False, messages=False)

        results_list = []
        for _, row in session.results.iterrows():
            driver_code = str(row.get("Abbreviation") or row.get("Driver") or "").upper().strip()
            if not driver_code:
                continue
            results_list.append({
                "driver_code": driver_code,
                "driver_number": _to_int(row.get("DriverNumber")),
                "driver_name": str(row.get("FullName") or "Unknown"),
                "team": str(row.get("TeamName") or "Unknown"),
                "position": _to_int(row.get("Position")),
                "grid_position": _to_int(row.get("GridPosition")),
                "points": _to_float(row.get("Points")) or 0.0,
                "status": str(row.get("Status") or ""),
                "fastest_lap": False,
                "laps": _to_int(row.get("Laps")),
            })

        RaceResultData.objects.update_or_create(
            year=year,
            round_number=round_number,
            session="R",
            defaults={"payload": {"results": results_list}},
        )

        # 3) Collect analysis per driver and write one DriverLapAnalysis row each
        stint_payload = get_stint_analysis(year=year, round_number=round_number, session="R")
        pace_payload = get_pace_analysis(year=year, round_number=round_number, session="R")
        sector_payload = get_sector_analysis(year=year, round_number=round_number, session="R")

        # Index by driver_code
        stints_by_driver: dict[str, list] = {}
        for row in stint_payload.get("data", []):
            dc = str(row.get("driver_code") or "").upper().strip()
            if dc:
                stints_by_driver.setdefault(dc, []).append(row)

        pace_by_driver: dict[str, dict] = {}
        for row in pace_payload.get("data", []):
            dc = str(row.get("driver_code") or "").upper().strip()
            if dc:
                pace_by_driver[dc] = {
                    "laps_completed": _to_int(row.get("laps_completed")) or 0,
                    "session_median_lap_seconds": _to_float(row.get("session_median_lap_seconds")),
                    "session_best_lap_seconds": _to_float(row.get("session_best_lap_seconds")),
                    "consistency_stddev_seconds": _to_float(row.get("consistency_stddev_seconds")),
                    "pace_improvement_seconds": _to_float(row.get("pace_improvement_seconds")),
                    "driver_number": _to_int(row.get("driver_number")),
                }

        sectors_by_driver: dict[str, dict] = {}
        for row in sector_payload.get("data", []):
            dc = str(row.get("driver_code") or "").upper().strip()
            if dc:
                sectors_by_driver[dc] = {
                    "laps_count": _to_int(row.get("laps_count")) or 0,
                    "best_sector1_seconds": _to_float(row.get("best_sector1_seconds")),
                    "best_sector2_seconds": _to_float(row.get("best_sector2_seconds")),
                    "best_sector3_seconds": _to_float(row.get("best_sector3_seconds")),
                    "median_sector1_seconds": _to_float(row.get("median_sector1_seconds")),
                    "median_sector2_seconds": _to_float(row.get("median_sector2_seconds")),
                    "median_sector3_seconds": _to_float(row.get("median_sector3_seconds")),
                    "best_lap_seconds": _to_float(row.get("best_lap_seconds")),
                    "theoretical_best_lap_seconds": _to_float(row.get("theoretical_best_lap_seconds")),
                    "delta_to_theoretical_seconds": _to_float(row.get("delta_to_theoretical_seconds")),
                    "driver_number": _to_int(row.get("driver_number")),
                }

        all_drivers = set(stints_by_driver) | set(pace_by_driver) | set(sectors_by_driver)
        for dc in all_drivers:
            stints = stints_by_driver.get(dc, [])
            DriverLapAnalysis.objects.update_or_create(
                year=year,
                round_number=round_number,
                session="R",
                driver_code=dc,
                defaults={
                    "payload": {
                        "stints": stints,
                        "tyre_strategy": stints,
                        "pace": pace_by_driver.get(dc, {}),
                        "sectors": sectors_by_driver.get(dc, {}),
                    }
                },
            )

        logger.info("event=command_completed command=populate_race year=%s round=%s session=R results=%s drivers=%s", year, round_number, len(results_list), len(all_drivers))
        self.stdout.write(
            self.style.SUCCESS(
                f"Populated season={year} round={round_number} session=R | "
                f"results={len(results_list)} drivers_with_analysis={len(all_drivers)}"
            )
        )

    def _populate_qualifying_session(self, year: int, round_number: int, force: bool):
        """Populate qualifying session (Q) with results."""
        if not force and QualifyingResultData.objects.filter(
            year=year, round_number=round_number
        ).exists():
            self.stdout.write(
                self.style.WARNING(
                    f"Skipping season={year} round={round_number} session=Q: already populated (use --force to overwrite)."
                )
            )
            return

        if force:
            QualifyingResultData.objects.filter(year=year, round_number=round_number).delete()

        session = fastf1.get_session(year, round_number, "Q")
        session.load(laps=False, telemetry=False, weather=False, messages=False)

        results_list = []
        for _, row in session.results.iterrows():
            driver_code = str(row.get("Abbreviation") or row.get("Driver") or "").upper().strip()
            if not driver_code:
                continue
            results_list.append({
                "driver_code": driver_code,
                "driver_number": _to_int(row.get("DriverNumber")),
                "driver_name": str(row.get("FullName") or "Unknown"),
                "team": str(row.get("TeamName") or "Unknown"),
                "position": _to_int(row.get("Position")),
                "grid_position": None,
                "points": 0.0,
                "status": str(row.get("Status") or ""),
                "fastest_lap": False,
                "laps": _to_int(row.get("Laps")),
            })

        store_qualifying_results(year, round_number, results_list)
        logger.info("event=command_completed command=populate_race year=%s round=%s session=Q results=%s", year, round_number, len(results_list))
        self.stdout.write(
            self.style.SUCCESS(
                f"Populated season={year} round={round_number} session=Q | results={len(results_list)}"
            )
        )

    def _populate_practice_session(self, year: int, round_number: int, session_name: str, force: bool):
        """Populate practice session (FP1/FP2/FP3) with results."""
        if not force and PracticeResultData.objects.filter(
            year=year, round_number=round_number, session=session_name
        ).exists():
            self.stdout.write(
                self.style.WARNING(
                    f"Skipping season={year} round={round_number} session={session_name}: already populated (use --force to overwrite)."
                )
            )
            return

        if force:
            PracticeResultData.objects.filter(
                year=year, round_number=round_number, session=session_name
            ).delete()

        session = fastf1.get_session(year, round_number, session_name)
        session.load(laps=False, telemetry=False, weather=False, messages=False)

        results_list = []
        for _, row in session.results.iterrows():
            driver_code = str(row.get("Abbreviation") or row.get("Driver") or "").upper().strip()
            if not driver_code:
                continue
            results_list.append({
                "driver_code": driver_code,
                "driver_number": _to_int(row.get("DriverNumber")),
                "driver_name": str(row.get("FullName") or "Unknown"),
                "team": str(row.get("TeamName") or "Unknown"),
                "position": None,
                "grid_position": None,
                "points": 0.0,
                "status": str(row.get("Status") or ""),
                "fastest_lap": False,
                "laps": _to_int(row.get("Laps")),
            })

        store_practice_results(year, round_number, session_name, results_list)
        logger.info("event=command_completed command=populate_race year=%s round=%s session=%s results=%s", year, round_number, session_name, len(results_list))
        self.stdout.write(
            self.style.SUCCESS(
                f"Populated season={year} round={round_number} session={session_name} | results={len(results_list)}"
            )
        )

    def _populate_sprint_session(self, year: int, round_number: int, force: bool):
        """Populate sprint race session (S) with results."""
        if not force and RaceResultData.objects.filter(
            year=year, round_number=round_number, session="S"
        ).exists():
            self.stdout.write(
                self.style.WARNING(
                    f"Skipping season={year} round={round_number} session=S: already populated (use --force to overwrite)."
                )
            )
            return

        if force:
            RaceResultData.objects.filter(
                year=year, round_number=round_number, session="S"
            ).delete()

        session = fastf1.get_session(year, round_number, "S")
        session.load(laps=False, telemetry=False, weather=False, messages=False)

        results_list = []
        for _, row in session.results.iterrows():
            driver_code = str(row.get("Abbreviation") or row.get("Driver") or "").upper().strip()
            if not driver_code:
                continue
            results_list.append({
                "driver_code": driver_code,
                "driver_number": _to_int(row.get("DriverNumber")),
                "driver_name": str(row.get("FullName") or "Unknown"),
                "team": str(row.get("TeamName") or "Unknown"),
                "position": _to_int(row.get("Position")),
                "grid_position": _to_int(row.get("GridPosition")),
                "points": _to_float(row.get("Points")) or 0.0,
                "status": str(row.get("Status") or ""),
                "fastest_lap": False,
                "laps": _to_int(row.get("Laps")),
            })

        store_sprint_results(year, round_number, results_list)
        logger.info("event=command_completed command=populate_race year=%s round=%s session=S results=%s", year, round_number, len(results_list))
        self.stdout.write(
            self.style.SUCCESS(
                f"Populated season={year} round={round_number} session=S | results={len(results_list)}"
            )
        )

    def _populate_sprint_shootout_session(self, year: int, round_number: int, force: bool):
        """Populate sprint shootout session (SQ) with results."""
        if not force and RaceResultData.objects.filter(
            year=year, round_number=round_number, session="SQ"
        ).exists():
            self.stdout.write(
                self.style.WARNING(
                    f"Skipping season={year} round={round_number} session=SQ: already populated (use --force to overwrite)."
                )
            )
            return

        if force:
            RaceResultData.objects.filter(
                year=year, round_number=round_number, session="SQ"
            ).delete()

        session = fastf1.get_session(year, round_number, "SQ")
        session.load(laps=False, telemetry=False, weather=False, messages=False)

        results_list = []
        for _, row in session.results.iterrows():
            driver_code = str(row.get("Abbreviation") or row.get("Driver") or "").upper().strip()
            if not driver_code:
                continue
            results_list.append({
                "driver_code": driver_code,
                "driver_number": _to_int(row.get("DriverNumber")),
                "driver_name": str(row.get("FullName") or "Unknown"),
                "team": str(row.get("TeamName") or "Unknown"),
                "position": _to_int(row.get("Position")),
                "grid_position": None,
                "points": 0.0,
                "status": str(row.get("Status") or ""),
                "fastest_lap": False,
                "laps": _to_int(row.get("Laps")),
            })

        store_sprint_shootout_results(year, round_number, results_list)
        logger.info("event=command_completed command=populate_race year=%s round=%s session=SQ results=%s", year, round_number, len(results_list))
        self.stdout.write(
            self.style.SUCCESS(
                f"Populated season={year} round={round_number} session=SQ | results={len(results_list)}"
            )
        )
