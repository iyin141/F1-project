"""Populate DriverTelemetry — one row per driver per session, all laps in payload."""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from api.models import DriverTelemetry
from api.services.fastf1_runtime import fastf1
from api.services.store import store_driver_telemetry
from api.services.unified_service import resolve_load_params

_ALLOWED_SESSIONS = {"R", "Q", "S", "SQ", "FP1", "FP2", "FP3"}
_DEFAULT_STRIDE = 3
_MAX_POINTS_PER_LAP = 3000
_TELEMETRY_MIN_YEAR = 2018

logger = logging.getLogger(__name__)


def _safe_list(series, dtype=None) -> list:
    """Convert a pandas Series to a plain Python list, handling NaN/None."""
    try:
        if dtype == bool:
            return series.fillna(False).astype(bool).tolist()
        return series.fillna(0).tolist()
    except Exception:
        return []


def run(
    year: int,
    round_number: int,
    session_type: str,
    driver_code: Optional[str] = None,
    force: bool = False,
    stride: int = _DEFAULT_STRIDE,
) -> int:
    """
    Fetch ALL laps for all drivers (or one driver) in one session and persist as DriverTelemetry rows.

    Payload structure:
        {
            "1": {"distance": [...], "speed": [...], "throttle": [...], ...},
            "2": {...},
            ...
        }

    Returns the number of laps stored in the payload.
    Raises ValueError on session-load failure or invalid args.
    """
    session_type = str(session_type).upper()
    stride = max(1, stride)

    if int(year) < _TELEMETRY_MIN_YEAR:
        raise ValueError(f"Telemetry not available before {_TELEMETRY_MIN_YEAR}. Got year={year}.")

    if session_type not in _ALLOWED_SESSIONS:
        raise ValueError(f"Invalid session type: {session_type}.")

    try:
        session = fastf1.get_session(year, round_number, session_type)
        load_params = resolve_load_params(["telemetry"])
        session.load(**load_params)
    except Exception as exc:
        raise ValueError(f"Failed to load FastF1 session: {exc}")

    if driver_code:
        target_drivers = [str(driver_code).upper()]
    else:
        # Get all drivers in session
        try:
            target_drivers = session.laps['Driver'].unique().tolist()
        except Exception:
            target_drivers = []

    total_laps_stored = 0

    for driver in target_drivers:
        if not force:
            if DriverTelemetry.objects.filter(
                year=year, round_number=round_number,
                session=session_type, driver_code=driver,
            ).exists():
                logger.info(
                    "event=skipped command=populate_telemetry year=%s round=%s session=%s driver=%s reason=already_stored",
                    year, round_number, session_type, driver,
                )
                continue

        try:
            driver_laps = session.laps.pick_driver(driver)
        except Exception as exc:
            logger.warning("event=telemetry_driver_error driver=%s error=%s", driver, exc)
            continue
            
        laps_payload: dict[str, dict] = {}

        for _, lap_row in driver_laps.iterrows():
            lap_number = int(lap_row["LapNumber"])
            try:
                tel = lap_row.get_car_data().add_distance()
                if tel is None or tel.empty:
                    continue

                # Downsample if needed
                if stride > 1:
                    tel = tel.iloc[::stride]
                if len(tel) > _MAX_POINTS_PER_LAP:
                    import math
                    step = max(1, math.ceil(len(tel) / _MAX_POINTS_PER_LAP))
                    tel = tel.iloc[::step]

                s1_time = lap_row.get("Sector1SessionTime")
                s2_time = lap_row.get("Sector2SessionTime")
                s3_time = lap_row.get("Sector3SessionTime")
                
                sectors = []
                for t in tel["SessionTime"]:
                    if pd.notna(s1_time) and t <= s1_time:
                        sectors.append(1)
                    elif pd.notna(s2_time) and t <= s2_time:
                        sectors.append(2)
                    elif pd.notna(s3_time) and t <= s3_time:
                        sectors.append(3)
                    else:
                        sectors.append(3)

                laps_payload[str(lap_number)] = {
                    "distance":          _safe_list(tel["Distance"]) if "Distance" in tel else [],
                    "speed":             _safe_list(tel["Speed"]) if "Speed" in tel else [],
                    "throttle":          _safe_list(tel["Throttle"]) if "Throttle" in tel else [],
                    "brake":             _safe_list(tel["Brake"], dtype=bool) if "Brake" in tel else [],
                    "gear":              _safe_list(tel["nGear"]) if "nGear" in tel else [],
                    "rpm":               _safe_list(tel["RPM"]) if "RPM" in tel else [],
                    "drs":               _safe_list(tel["DRS"]) if "DRS" in tel else [],
                    "relative_distance": _safe_list(tel["RelativeDistance"]) if "RelativeDistance" in tel else [],
                    "sector":            sectors,
                }
            except Exception as exc:
                logger.warning(
                    "event=lap_telemetry_error driver=%s lap=%s error=%s — skipping lap",
                    driver, lap_number, exc,
                )

        if laps_payload:
            store_driver_telemetry(
                year=year,
                round_number=round_number,
                session=session_type,
                driver_code=driver,
                laps_payload=laps_payload,
            )
            total_laps_stored += len(laps_payload)

    logger.info(
        "event=completed command=populate_telemetry year=%s round=%s session=%s total_laps=%s",
        year, round_number, session_type, total_laps_stored,
    )
    return total_laps_stored


class Command(BaseCommand):
    help = "Populate DriverTelemetry — one row per driver, all laps in payload."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True)
        parser.add_argument("--round", type=int, required=True, dest="round_number")
        parser.add_argument("--session", type=str, default="R")
        parser.add_argument("--driver", type=str, required=False, dest="driver_code",
                            help="Optional 3-letter driver code. If omitted, all drivers are processed.")
        parser.add_argument("--stride", type=int, default=_DEFAULT_STRIDE,
                            help=f"Keep every Nth telemetry point (default: {_DEFAULT_STRIDE})")
        parser.add_argument("--force", action="store_true",
                            help="Overwrite existing row even if already stored")

    def handle(self, *args, **options):
        year = options["year"]
        round_number = options["round_number"]
        session_type = str(options["session"]).upper()
        driver_code = str(options["driver_code"]).upper()
        stride = max(1, options["stride"])
        force = options["force"]
        logger.info(
            "event=command_started command=populate_telemetry year=%s round=%s session=%s driver=%s force=%s",
            year, round_number, session_type, driver_code, force,
        )

        try:
            lap_count = run(
                year=year,
                round_number=round_number,
                session_type=session_type,
                driver_code=driver_code,
                stride=stride,
                force=force,
            )
        except ValueError as exc:
            raise CommandError(str(exc))

        if lap_count:
            self.stdout.write(self.style.SUCCESS(
                f"Stored telemetry for {driver_code} year={year} round={round_number} "
                f"session={session_type} | laps={lap_count}"
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f"Skipped {driver_code} year={year} round={round_number} session={session_type} "
                "— already stored (use --force to overwrite)."
            ))
