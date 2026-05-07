"""Populate DriverTelemetry rows for every driver/lap in a session."""
from __future__ import annotations

import logging
import math
from typing import Optional

import pandas as pd

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from api.models import DriverTelemetry
from api.services.fastf1_runtime import fastf1
from api.services.store import store_driver_telemetry

_ALLOWED_SESSIONS = {"R", "Q", "S", "SQ", "FP1", "FP2", "FP3"}
_DEFAULT_STRIDE = 3  # downsample: keep every Nth point by default
_MAX_POINTS_PER_LAP = 3000

logger = logging.getLogger(__name__)


def _safe_float(value, precision=3):
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return round(float(value), precision)
    except Exception:
        return None


def _safe_int(value):
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return int(value)
    except Exception:
        return None


def _safe_bool(value):
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return False
        return bool(value)
    except Exception:
        return False


def _lap_seconds(value):
    if value is None:
        return None
    if hasattr(value, "total_seconds"):
        return value.total_seconds()
    try:
        return pd.to_timedelta(value).total_seconds()
    except Exception:
        return None


def _build_telemetry_points(telemetry: pd.DataFrame, stride: int) -> list[dict]:
    """Convert a telemetry DataFrame to a list of point dicts, downsampled by stride."""
    if stride > 1:
        telemetry = telemetry.iloc[::stride]
    if len(telemetry) > _MAX_POINTS_PER_LAP:
        step = max(1, math.ceil(len(telemetry) / _MAX_POINTS_PER_LAP))
        telemetry = telemetry.iloc[::step]

    rows = []
    for _, row in telemetry.iterrows():
        rows.append({
            "time_seconds": _safe_float(_lap_seconds(row.get("Time")), precision=4),
            "distance_m": _safe_float(row.get("Distance"), precision=3),
            "speed_kph": _safe_float(row.get("Speed"), precision=2),
            "throttle_pct": _safe_float(row.get("Throttle"), precision=2),
            "brake": _safe_bool(row.get("Brake")),
            "rpm": _safe_int(row.get("RPM")),
            "gear": _safe_int(row.get("nGear")),
        })
    return rows


def _build_summary(lap_row, telemetry: pd.DataFrame) -> dict:
    """Build a compact summary dict from a single lap row and its telemetry."""
    lap_time_sec = _lap_seconds(lap_row.get("LapTime"))
    max_speed = _safe_float(telemetry["Speed"].max()) if "Speed" in telemetry.columns and not telemetry.empty else None
    avg_speed = _safe_float(telemetry["Speed"].mean()) if "Speed" in telemetry.columns and not telemetry.empty else None
    max_throttle = _safe_float(telemetry["Throttle"].max()) if "Throttle" in telemetry.columns and not telemetry.empty else None

    brake_series = telemetry["Brake"] if "Brake" in telemetry.columns else pd.Series(dtype=bool)
    brake_applications = int(brake_series.astype(bool).diff().gt(0).sum()) if not brake_series.empty else 0

    compound = str(lap_row.get("Compound") or "")
    tyre_life = _safe_int(lap_row.get("TyreLife"))

    return {
        "lap_time_seconds": lap_time_sec,
        "lap_number": _safe_int(lap_row.get("LapNumber")),
        "max_speed_kph": max_speed,
        "avg_speed_kph": avg_speed,
        "max_throttle_pct": max_throttle,
        "brake_applications": brake_applications,
        "compound": compound,
        "tyre_life_laps": tyre_life,
        "sector1_seconds": _lap_seconds(lap_row.get("Sector1Time")),
        "sector2_seconds": _lap_seconds(lap_row.get("Sector2Time")),
        "sector3_seconds": _lap_seconds(lap_row.get("Sector3Time")),
    }


class Command(BaseCommand):
    help = (
        "Populate DriverTelemetry rows for all drivers/laps in a session. "
        "Telemetry is downsampled to keep storage manageable."
    )

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True, help="Season year, e.g. 2024")
        parser.add_argument("--round", type=int, required=True, dest="round_number", help="Round number, e.g. 5")
        parser.add_argument(
            "--session",
            type=str,
            default="R",
            help="Session type: R (default), Q, FP1, FP2, FP3, S, SQ",
        )
        parser.add_argument(
            "--driver",
            type=str,
            default=None,
            help="Only populate telemetry for this driver code, e.g. VER",
        )
        parser.add_argument(
            "--lap",
            type=int,
            default=None,
            help="Only populate telemetry for this specific lap number",
        )
        parser.add_argument(
            "--stride",
            type=int,
            default=_DEFAULT_STRIDE,
            help=f"Keep every Nth telemetry point (default: {_DEFAULT_STRIDE}). Higher = fewer points stored.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing DriverTelemetry rows",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        year = options["year"]
        round_number = options["round_number"]
        session_type = str(options["session"]).upper()
        driver_filter = str(options["driver"]).upper() if options["driver"] else None
        lap_filter = options["lap"]
        stride = max(1, options["stride"])
        force = options["force"]
        logger.info("event=command_started command=populate_telemetry year=%s round=%s session=%s driver=%s lap=%s", year, round_number, session_type, driver_filter or "all", lap_filter or "all")

        if session_type not in _ALLOWED_SESSIONS:
            raise CommandError(
                f"Invalid session type: {session_type}. Must be one of {sorted(_ALLOWED_SESSIONS)}."
            )

        if lap_filter is not None and lap_filter < 1:
            raise CommandError("--lap must be a positive integer")

        # Load FastF1 session with telemetry
        self.stdout.write(
            f"Loading FastF1 session year={year} round={round_number} session={session_type} (telemetry=True)…"
        )
        try:
            session = fastf1.get_session(year, round_number, session_type)
            session.load(telemetry=True, weather=False, messages=False)
        except Exception as exc:
            raise CommandError(f"Failed to load FastF1 session: {exc}")

        # Determine drivers to process
        laps = session.laps.copy()
        laps = laps[laps["LapTime"].notna()]

        if driver_filter:
            laps = laps[laps["Driver"].astype(str).str.upper() == driver_filter]
            if laps.empty:
                raise CommandError(f"No valid laps found for driver {driver_filter}")

        if lap_filter:
            laps = laps[laps["LapNumber"] == lap_filter]
            if laps.empty:
                raise CommandError(f"No valid laps found for lap {lap_filter}")

        all_driver_lap_pairs = (
            laps[["Driver", "LapNumber"]]
            .drop_duplicates()
            .sort_values(["Driver", "LapNumber"])
        )

        # Skip pairs already stored (unless --force)
        if not force:
            already_stored: set[tuple] = set(
                DriverTelemetry.objects.filter(
                    year=year, round_number=round_number, session=session_type
                ).values_list("driver_code", "lap")
            )
        else:
            already_stored = set()

        stored_count = 0
        skipped_count = 0
        error_count = 0

        for _, row in all_driver_lap_pairs.iterrows():
            driver_code = str(row["Driver"]).upper()
            lap_number = int(row["LapNumber"])

            if (driver_code, lap_number) in already_stored:
                skipped_count += 1
                continue

            try:
                lap_rows = laps[
                    (laps["Driver"].astype(str).str.upper() == driver_code)
                    & (laps["LapNumber"] == lap_number)
                ]
                if lap_rows.empty:
                    continue

                lap_row = lap_rows.iloc[0]
                tel = lap_row.get_car_data().add_distance()

                if tel is None or tel.empty:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  No telemetry data for {driver_code} lap {lap_number} — skipping"
                        )
                    )
                    skipped_count += 1
                    continue

                points = _build_telemetry_points(tel, stride)
                summary = _build_summary(lap_row, tel)

                store_driver_telemetry(
                    year=year,
                    round_number=round_number,
                    session=session_type,
                    driver_code=driver_code,
                    lap=lap_number,
                    telemetry_points=points,
                    summary=summary,
                )
                stored_count += 1

            except Exception as exc:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Error for {driver_code} lap {lap_number}: {exc} — skipping"
                    )
                )
                error_count += 1

        logger.info("event=command_completed command=populate_telemetry year=%s round=%s session=%s stored=%s skipped=%s errors=%s", year, round_number, session_type, stored_count, skipped_count, error_count)
        self.stdout.write(
            self.style.SUCCESS(
                f"Done year={year} round={round_number} session={session_type} | "
                f"stored={stored_count} skipped={skipped_count} errors={error_count}"
            )
        )
