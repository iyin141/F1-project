"""Populate race and other session data into persisted JSONB models."""
from __future__ import annotations

import json
import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from api.models import DriverLapAnalysis, PracticeResultData, QualifyingResultData, RaceResultData, SeasonSchedule
from api.services.analysis import get_pace_analysis, get_sector_analysis, get_stint_analysis
from api.services.cache import build_cache_key, ttl_for, set_in_cache
from api.services.fastf1_runtime import fastf1
from api.services.schedule import get_race_by_round
from api.results.services.race import get_race_session_results
from api.results.services.qualifying import get_qualifying_results
from api.results.services.practice import get_practice_session_results
from api.results.services.sprint import get_sprint_results, get_sprint_shootout_results
from api.services.store import (
    store_practice_results,
    store_qualifying_results,
    store_sprint_results,
    store_sprint_shootout_results,
    store_race_results,
    store_driver_lap_analysis,
    store_season_schedule,
)
from api.results.helpers import format_timedelta


def _to_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


logger = logging.getLogger(__name__)

_ALLOWED_SESSIONS = {"R", "Q", "FP1", "FP2", "FP3", "S", "SQ"}


def _build_lap_data(driver_laps) -> list:
    """
    Returns a list of lap objects for one driver.
    Excludes laps with no LapTime recorded.
    """
    laps = []
    if driver_laps is None or driver_laps.empty:
        return laps

    for _, lap in driver_laps.iterrows():
        if lap.get("LapTime") is None or str(lap.get("LapTime")) == "NaT":
            continue
        laps.append(
            {
                "lap_number": int(lap["LapNumber"]),
                "lap_time": str(lap["LapTime"]),
                "sector1": str(lap.get("Sector1Time", "")),
                "sector2": str(lap.get("Sector2Time", "")),
                "sector3": str(lap.get("Sector3Time", "")),
                "compound": str(lap.get("Compound", "")),
                "stint": int(lap.get("Stint", 0)),
                "is_personal_best": bool(lap.get("IsPersonalBest", False)),
            }
        )
    return laps


# ---------------------------------------------------------------------------
# Module-level session runners — no self dependency, usable from Celery tasks
# ---------------------------------------------------------------------------

@transaction.atomic
def _run_race(year: int, round_number: int, force: bool) -> int:
    race_info = get_race_by_round(year, round_number)
    if race_info is None:
        raise ValueError(f"Race not found for season={year} round={round_number}")

    existing_result = RaceResultData.objects.filter(year=year, round_number=round_number, session="R").first()
    if existing_result and existing_result.payload.get("results") and not force:
        logger.info("event=skipped command=populate_race session=R year=%s round=%s reason=already_stored", year, round_number)
        return 0

    if force:
        RaceResultData.objects.filter(year=year, round_number=round_number, session="R").delete()
        DriverLapAnalysis.objects.filter(year=year, round_number=round_number, session="R").delete()

    # 1) Merge into SeasonSchedule using central store helper
    existing = SeasonSchedule.objects.filter(year=year).first()
    races_list = existing.payload.get("races", []) if (existing and existing.payload) else []
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
    store_season_schedule(year, races_list)

    # 2) Load FastF1 race session and extract canonical rows via service
    session = fastf1.get_session(year, round_number, "R")
    session.load(laps=True, telemetry=False, weather=False, messages=False)

    # Use canonical extractor to build rows that match API output
    results_list = get_race_session_results(session)

    # Persist canonical race result payload via store helper (writes payload.data)
    store_race_results(year, round_number, "R", results_list)

    # 3) Analysis per driver
    stint_payload = get_stint_analysis(year=year, round_number=round_number, session="R")
    pace_payload = get_pace_analysis(year=year, round_number=round_number, session="R")
    sector_payload = get_sector_analysis(year=year, round_number=round_number, session="R")

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
        # Extract driver-specific laps from the already loaded session
        driver_laps = session.laps.pick_drivers([dc]) if hasattr(session, "laps") else None

        # Persist via store helper which will normalise rows and use canonical serializers
        store_driver_lap_analysis(
            year=year,
            round_number=round_number,
            session="R",
            driver_code=dc,
            laps=_build_lap_data(driver_laps),
            stints=stints,
            tyre_strategy=stints,
            pace=pace_by_driver.get(dc, {}),
            sectors=sectors_by_driver.get(dc, {}),
        )

    logger.info("event=completed command=populate_race session=R year=%s round=%s results=%s drivers=%s", year, round_number, len(results_list), len(all_drivers))
    return len(results_list)


@transaction.atomic
def _run_qualifying(year: int, round_number: int, force: bool) -> int:
    if not force and QualifyingResultData.objects.filter(year=year, round_number=round_number).exists():
        logger.info("event=skipped command=populate_race session=Q year=%s round=%s reason=already_stored", year, round_number)
        return 0
    if force:
        QualifyingResultData.objects.filter(year=year, round_number=round_number).delete()

    # Use the qualifying service extractor so the persisted rows match API responses
    qualifying_payload = get_qualifying_results(year, round_number)
    if isinstance(qualifying_payload, dict):
        results_list = qualifying_payload.get("data", [])
    else:
        results_list = qualifying_payload

    store_qualifying_results(year, round_number, results_list)
    logger.info("event=completed command=populate_race session=Q year=%s round=%s results=%s", year, round_number, len(results_list))
    return len(results_list)


@transaction.atomic
def _run_practice(year: int, round_number: int, session_name: str, force: bool) -> int:
    if not force and PracticeResultData.objects.filter(year=year, round_number=round_number, session=session_name).exists():
        logger.info("event=skipped command=populate_race session=%s year=%s round=%s reason=already_stored", session_name, year, round_number)
        return 0
    if force:
        PracticeResultData.objects.filter(year=year, round_number=round_number, session=session_name).delete()

    # Use practice service extractor so persisted practice rows match API responses
    practice_payload = get_practice_session_results(year, round_number, session_name)
    if isinstance(practice_payload, dict):
        results_list = practice_payload.get("data", [])
    else:
        results_list = practice_payload

    store_practice_results(year, round_number, session_name, results_list)
    logger.info("event=completed command=populate_race session=%s year=%s round=%s results=%s", session_name, year, round_number, len(results_list))
    return len(results_list)


@transaction.atomic
def _run_sprint(year: int, round_number: int, force: bool) -> int:
    if not force and RaceResultData.objects.filter(year=year, round_number=round_number, session="S").exists():
        logger.info("event=skipped command=populate_race session=S year=%s round=%s reason=already_stored", year, round_number)
        return 0
    if force:
        RaceResultData.objects.filter(year=year, round_number=round_number, session="S").delete()

    # Use sprint service extractor (which reuses race extractor) to produce canonical rows
    sprint_payload = get_sprint_results(year, round_number)
    if isinstance(sprint_payload, dict):
        results_list = sprint_payload.get("data", [])
    else:
        results_list = sprint_payload

    store_sprint_results(year, round_number, results_list)
    logger.info("event=completed command=populate_race session=S year=%s round=%s results=%s", year, round_number, len(results_list))
    return len(results_list)


@transaction.atomic
def _run_sprint_shootout(year: int, round_number: int, force: bool) -> int:
    if not force and RaceResultData.objects.filter(year=year, round_number=round_number, session="SQ").exists():
        logger.info("event=skipped command=populate_race session=SQ year=%s round=%s reason=already_stored", year, round_number)
        return 0
    if force:
        RaceResultData.objects.filter(year=year, round_number=round_number, session="SQ").delete()

    shootout_payload = get_sprint_shootout_results(year, round_number)
    if isinstance(shootout_payload, dict):
        results_list = shootout_payload.get("data", [])
    else:
        results_list = shootout_payload

    store_sprint_shootout_results(year, round_number, results_list)
    logger.info("event=completed command=populate_race session=SQ year=%s round=%s results=%s", year, round_number, len(results_list))
    return len(results_list)


def run(year: int, round_number: int, session_type: str, force: bool = False) -> int:
    """
    Dispatch to the appropriate session runner.
    Returns the number of results stored (0 if skipped).
    Raises ValueError for invalid session type or data failure.
    """
    session_type = str(session_type).upper()
    if session_type == "R":
        return _run_race(year, round_number, force)
    elif session_type == "Q":
        return _run_qualifying(year, round_number, force)
    elif session_type in ("FP1", "FP2", "FP3"):
        return _run_practice(year, round_number, session_type, force)
    elif session_type == "S":
        return _run_sprint(year, round_number, force)
    elif session_type == "SQ":
        return _run_sprint_shootout(year, round_number, force)
    else:
        raise ValueError(f"Invalid session type: {session_type}. Must be R, Q, FP1, FP2, FP3, S, or SQ.")


class Command(BaseCommand):
    help = "Populate persisted session data (results, analysis) for one season/round/session"

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True)
        parser.add_argument("--round", type=int, required=True, dest="round_number")
        parser.add_argument("--session", type=str, default="R")
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **options):
        year = options["year"]
        round_number = options["round_number"]
        session_type = str(options["session"]).upper()
        force = options["force"]
        logger.info("event=command_started command=populate_race year=%s round=%s session=%s force=%s", year, round_number, session_type, force)

        try:
            count = run(year=year, round_number=round_number, session_type=session_type, force=force)
        except ValueError as exc:
            raise CommandError(str(exc))

        if count:
            self.stdout.write(self.style.SUCCESS(f"Populated year={year} round={round_number} session={session_type} | results={count}"))
        else:
            self.stdout.write(self.style.WARNING(f"Skipped year={year} round={round_number} session={session_type} — already stored (use --force to overwrite)."))
