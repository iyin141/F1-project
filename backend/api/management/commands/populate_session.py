"""Populate full SessionData (weather, pit_stops, incidents, positions, drs, track_status)."""
from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from api.models import (
    WeatherData,
    PitStopData,
    IncidentData,
    PositionData,
    DRSData,
    TrackStatusData,
)
from api.services.fastf1_runtime import fastf1
from api.services.store import (
    store_weather_data,
    store_pit_stop_data,
    store_incident_data,
    store_position_data,
    store_drs_data,
    store_track_status_data,
)
from api.services.unified_service import (
    DRSExtractor,
    IncidentExtractor,
    PitStopExtractor,
    PositionExtractor,
    TrackStatusExtractor,
    WeatherExtractor,
    resolve_load_params,
)

_ALLOWED_SESSIONS = {"R", "Q", "S", "SQ", "FP1", "FP2", "FP3"}

# (key_name, extractor_class, extra_kwargs)
_EXTRACTOR_SPECS = [
    ("weather", WeatherExtractor, {}),
    ("pit_stops", PitStopExtractor, {}),
    ("incidents", IncidentExtractor, {}),
    ("positions", PositionExtractor, {}),
    ("drs", DRSExtractor, {}),
    ("track_status", TrackStatusExtractor, {}),
]

# Mapping of key names to (model_class, store_function)
_MODEL_STORE_MAP = {
    "weather": (WeatherData, store_weather_data),
    "pit_stops": (PitStopData, store_pit_stop_data),
    "incidents": (IncidentData, store_incident_data),
    "positions": (PositionData, store_position_data),
    "drs": (DRSData, store_drs_data),
    "track_status": (TrackStatusData, store_track_status_data),
}

logger = logging.getLogger(__name__)


@transaction.atomic
def run(
    year: int,
    round_number: int,
    session_type: str,
    force: bool = False,
    only: str | None = None,
) -> int:
    """
    Fetch unified session data from FastF1 and persist to dedicated models.
    Returns the total number of rows stored across all keys. Returns 0 if all keys
    already present and not forced.
    Raises ValueError on failure.
    """
    session_type = str(session_type).upper()

    if session_type not in _ALLOWED_SESSIONS:
        raise ValueError(f"Invalid session type: {session_type}. Must be one of {sorted(_ALLOWED_SESSIONS)}.")

    # Resolve which keys to populate
    if only:
        requested_keys = {k.strip().lower() for k in only.split(",")}
        valid_keys = {spec[0] for spec in _EXTRACTOR_SPECS}
        unknown = requested_keys - valid_keys
        if unknown:
            raise ValueError(f"Unknown keys in only: {sorted(unknown)}. Valid keys: {sorted(valid_keys)}.")
        specs = [s for s in _EXTRACTOR_SPECS if s[0] in requested_keys]
    else:
        specs = list(_EXTRACTOR_SPECS)

    # Skip already-present keys unless --force
    if not force:
        skipped = []
        remaining_specs = []
        for key, extractor_cls, extra_kwargs in specs:
            model_cls, _ = _MODEL_STORE_MAP[key]
            exists = model_cls.objects.filter(
                year=year, round_number=round_number, session=session_type
            ).exists()
            if exists:
                skipped.append(key)
            else:
                remaining_specs.append((key, extractor_cls, extra_kwargs))
        specs = remaining_specs
        if skipped:
            logger.info("event=skipped_keys command=populate_session year=%s round=%s session=%s keys=%s", year, round_number, session_type, skipped)

    if not specs:
        logger.info("event=nothing_to_populate command=populate_session year=%s round=%s session=%s", year, round_number, session_type)
        return 0

    # Load FastF1 session once with minimal parameters
    try:
        session = fastf1.get_session(year, round_number, session_type)
        required_types = [s[0] for s in specs]
        load_params = resolve_load_params(required_types)
        session.load(**load_params)
    except Exception as exc:
        raise ValueError(f"Failed to load FastF1 session: {exc}")

    # Run each extractor and persist to dedicated models
    total_rows = 0
    for key, extractor_cls, extra_kwargs in specs:
        try:
            extractor = extractor_cls(
                session=session,
                year=year,
                round_number=round_number,
                session_type=session_type,
            )
            result = extractor.extract(**extra_kwargs)
            rows = result.get("data", [])
            
            # Persist to dedicated model using store function
            _, store_func = _MODEL_STORE_MAP[key]
            store_func(year, round_number, session_type, rows)
            
            total_rows += len(rows)
            logger.info("event=extracted_and_stored command=populate_session key=%s rows=%s", key, len(rows))
        except Exception as exc:
            logger.warning("event=extraction_failed command=populate_session key=%s error=%s", key, exc)

    logger.info(
        "event=completed command=populate_session year=%s round=%s session=%s total_rows=%s",
        year, round_number, session_type, total_rows,
    )
    return total_rows


class Command(BaseCommand):
    help = (
        "Populate SessionData for one round/session (weather, pit_stops, incidents, "
        "positions, drs, track_status). Merges keys into an existing row if present."
    )

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True, help="Season year, e.g. 2024")
        parser.add_argument("--round", type=int, required=True, dest="round_number", help="Round number, e.g. 5")
        parser.add_argument("--session", type=str, default="R", help="Session type: R, Q, FP1, FP2, FP3, S, SQ")
        parser.add_argument("--only", type=str, default=None, help="Comma-separated keys to populate")
        parser.add_argument("--force", action="store_true", help="Overwrite existing keys")

    def handle(self, *args, **options):
        year = options["year"]
        round_number = options["round_number"]
        session_type = str(options["session"]).upper()
        force = options["force"]
        only = options.get("only")
        logger.info("event=command_started command=populate_session year=%s round=%s session=%s force=%s", year, round_number, session_type, force)

        try:
            total_rows = run(year=year, round_number=round_number, session_type=session_type, force=force, only=only)
        except ValueError as exc:
            raise CommandError(str(exc))

        if total_rows:
            self.stdout.write(self.style.SUCCESS(f"Populated SessionData year={year} round={round_number} session={session_type} | total_rows={total_rows}"))
        else:
            self.stdout.write(self.style.WARNING("Nothing new to populate — all requested keys already present."))
