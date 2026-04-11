"""Unified FastF1 data extraction service with intelligent caching and normalization."""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from .fastf1_runtime import fastf1
from .readiness import is_data_unavailable_error

# Constants
_ALLOWED_SESSIONS = {"R", "Q", "FP1", "FP2", "FP3"}
_MAX_LIMIT = 2000
_MAX_TELEMETRY_POINTS = 3000
_DEFAULT_TELEMETRY_POINTS = 800
def _is_unsupported_session_error(exc: Exception) -> bool:
    return is_data_unavailable_error(exc)


class SessionManager:
    """Intelligent FastF1 session loader with caching to avoid redundant API calls."""

    _cache: dict[tuple[int, int, str], Any] = {}
    _cache_info = {"hits": 0, "misses": 0}

    @classmethod
    def get_session(cls, year: int, round_number: int, session_type: str):
        """
        Load or retrieve cached FastF1 session.
        Loads with telemetry=True, weather=True, messages=True for all extractors.
        """
        session_type = str(session_type).upper()
        if session_type not in _ALLOWED_SESSIONS:
            raise ValueError(f"session_type must be one of {_ALLOWED_SESSIONS}")

        cache_key = (year, round_number, session_type)

        # Cache hit
        if cache_key in cls._cache:
            cls._cache_info["hits"] += 1
            return cls._cache[cache_key]

        # Cache miss - load from FastF1
        cls._cache_info["misses"] += 1
        try:
            session = fastf1.get_session(year, round_number, session_type)
            # Load all data needed by any extractor
            session.load(telemetry=True, weather=True, messages=True)
            cls._cache[cache_key] = session
            return session
        except Exception as exc:
            if "session" in locals() and _is_unsupported_session_error(exc):
                cls._cache[cache_key] = session
                return session
            raise Exception(f"Failed to load session {year} R{round_number} {session_type}: {str(exc)}")

    @classmethod
    def clear_cache(cls):
        """Clear all cached sessions."""
        cls._cache.clear()
        cls._cache_info = {"hits": 0, "misses": 0}

    @classmethod
    def get_cache_stats(cls) -> dict:
        """Return cache hit/miss statistics."""
        total = cls._cache_info["hits"] + cls._cache_info["misses"]
        hit_rate = (cls._cache_info["hits"] / total * 100) if total > 0 else 0.0
        return {
            "cached_sessions": len(cls._cache),
            "hits": cls._cache_info["hits"],
            "misses": cls._cache_info["misses"],
            "hit_rate_percent": round(hit_rate, 2),
        }


class DataNormalizer:
    """Centralized data normalization to handle type conversions, NaN/None consistently."""

    @staticmethod
    def to_int(value: Any) -> Optional[int]:
        """Convert value to integer, return None if invalid/NaN."""
        if value is None or pd.isna(value):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def to_float(value: Any, precision: int = 3) -> Optional[float]:
        """Convert value to float with precision, return None if invalid/NaN."""
        if value is None or pd.isna(value):
            return None
        try:
            return round(float(value), precision)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def to_str(value: Any) -> Optional[str]:
        """Convert value to string, return None if invalid/NaN."""
        if value is None or pd.isna(value):
            return None
        return str(value)

    @staticmethod
    def to_bool(value: Any) -> bool:
        """Convert value to boolean, treat NaN/None as False."""
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return False
        return bool(value)

    @staticmethod
    def to_time_seconds(value: Any, precision: int = 4) -> Optional[float]:
        """Convert timedelta or time string to seconds."""
        if value is None or pd.isna(value):
            return None

        # Already a timedelta
        if hasattr(value, "total_seconds"):
            return DataNormalizer.to_float(value.total_seconds(), precision)

        # Try to convert to timedelta
        try:
            td = pd.to_timedelta(value)
            return DataNormalizer.to_float(td.total_seconds(), precision)
        except Exception:
            return None

    @staticmethod
    def to_timedelta_str(value: Any) -> Optional[str]:
        """Convert time value to HH:MM:SS.mmm string format."""
        if value is None or pd.isna(value):
            return None
        return str(value)

    @staticmethod
    def safe_get(df: Optional[pd.DataFrame], col: str, default: Any = None) -> Any:
        """Safely get column from dataframe, return default if not exists."""
        if df is None or col not in df.columns:
            return default
        return df[col]

    @staticmethod
    def fill_na(series: pd.Series, fill_value: Any = 0) -> pd.Series:
        """Fill NA values in series."""
        if series is None or series.empty:
            return series
        return series.fillna(fill_value)

    @staticmethod
    def normalize_session_type(session_type: str) -> str:
        """Normalize session type string to uppercase, validate."""
        normalized = str(session_type).upper()
        if normalized not in _ALLOWED_SESSIONS:
            raise ValueError(f"session_type must be one of {_ALLOWED_SESSIONS}")
        return normalized

    @staticmethod
    def normalize_driver_code(driver_code: Optional[str]) -> Optional[str]:
        """Normalize driver code to uppercase."""
        if driver_code is None:
            return None
        return str(driver_code).upper()


class DataValidator:
    """Validation utility for FastF1 data constraints and field requirements."""

    @staticmethod
    def validate_year(year: int):
        """Validate year is reasonable (1950+)."""
        if not isinstance(year, int):
            raise ValueError("year must be an integer")
        if year < 1950 or year > 2100:
            raise ValueError(f"year {year} is out of valid F1 range (1950-2100)")

    @staticmethod
    def validate_round(round_number: int):
        """Validate round is in valid range."""
        if not isinstance(round_number, int):
            raise ValueError("round_number must be an integer")
        if round_number < 1 or round_number > 24:
            raise ValueError(f"round_number {round_number} must be between 1 and 24")

    @staticmethod
    def validate_session_type(session_type: str):
        """Validate session type."""
        normalized = str(session_type).upper()
        if normalized not in _ALLOWED_SESSIONS:
            raise ValueError(f"session_type must be one of {_ALLOWED_SESSIONS}")
        return normalized

    @staticmethod
    def validate_lap_number(lap_number: int, max_laps: int):
        """Validate lap number within session."""
        if not isinstance(lap_number, int):
            raise ValueError("lap_number must be an integer")
        if lap_number < 1 or lap_number > max_laps:
            raise ValueError(f"lap_number {lap_number} must be between 1 and {max_laps}")

    @staticmethod
    def validate_sector_window(sector_start: Optional[int], sector_end: Optional[int]):
        """Validate sector start/end parameters."""
        if sector_start is None and sector_end is None:
            return

        if sector_start is None or sector_end is None:
            raise ValueError("sector_start and sector_end must be provided together")

        if not isinstance(sector_start, int) or not isinstance(sector_end, int):
            raise ValueError("sector_start and sector_end must be integers")

        if sector_start < 1 or sector_start > 3 or sector_end < 1 or sector_end > 3:
            raise ValueError("sector_start and sector_end must be between 1 and 3")

        if sector_start > sector_end:
            raise ValueError("sector_start must be less than or equal to sector_end")

    @staticmethod
    def validate_stride(stride: int):
        """Validate telemetry stride parameter."""
        if not isinstance(stride, int):
            raise ValueError("stride must be an integer")
        if stride < 1:
            raise ValueError("stride must be positive")

    @staticmethod
    def validate_limit(limit: Optional[int]):
        """Validate limit parameter."""
        if limit is None:
            return
        if not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        if limit < 1:
            raise ValueError("limit must be a positive integer")

    @staticmethod
    def validate_non_empty(data: Any, field_name: str = "data"):
        """Validate data is not empty."""
        if data is None or (hasattr(data, "__len__") and len(data) == 0):
            raise ValueError(f"{field_name} cannot be empty")

    @staticmethod
    def validate_dataframe(df: pd.DataFrame, min_rows: int = 1) -> bool:
        """Validate dataframe has minimum rows and is not all NaN."""
        if df is None or df.empty:
            return False
        if len(df) < min_rows:
            return False
        return True


class BaseDataExtractor(ABC):
    """Abstract base class for all FastF1 data extractors."""

    def __init__(
        self,
        session: Any,
        year: int,
        round_number: int,
        session_type: str,
        driver: Optional[str] = None,
        limit: Optional[int] = None,
    ):
        """
        Initialize extractor.

        Args:
            session: FastF1 session object (from SessionManager)
            year: Race year
            round_number: Round number
            session_type: Session type (R, Q, FP1, FP2, FP3)
            driver: Optional driver code filter
            limit: Optional row limit
        """
        self.session = session
        self.year = year
        self.round_number = round_number
        self.session_type = DataNormalizer.normalize_session_type(session_type)
        self.driver = DataNormalizer.normalize_driver_code(driver)
        self.limit = self._validate_limit(limit)

    @staticmethod
    def _validate_limit(limit: Optional[int]) -> Optional[int]:
        """Validate limit parameter."""
        if limit is None:
            return None
        if limit < 1:
            raise ValueError("limit must be a positive integer")
        return min(limit, _MAX_LIMIT)

    @abstractmethod
    def extract(self, **kwargs) -> dict:
        """
        Extract and return normalized data.
        Must return dict with structure:
        {
            "meta": {...},
            "filters_applied": {...},
            "data": [...]
        }
        """
        pass

    def _build_response(
        self,
        data_rows: list[dict],
        additional_meta: Optional[dict] = None,
        additional_filters: Optional[dict] = None,
    ) -> dict:
        """
        Build standard response object.

        Args:
            data_rows: List of normalized data rows
            additional_meta: Optional extra metadata fields
            additional_filters: Optional extra filter fields
        """
        meta = {
            "year": self.year,
            "round": self.round_number,
            "session": self.session_type,
            "row_count": len(data_rows),
            "extracted_at": datetime.now().isoformat(),
            "limit_max": _MAX_LIMIT,
        }
        if additional_meta:
            meta.update(additional_meta)

        filters = {
            "driver": self.driver,
            "limit": self.limit,
        }
        if additional_filters:
            filters.update(additional_filters)

        return {
            "meta": meta,
            "filters_applied": filters,
            "data": data_rows,
        }

    def _pick_drivers(self, drivers_list: list[str]) -> list[str]:
        """Filter drivers list by self.driver if set."""
        if not self.driver:
            return drivers_list
        return [d for d in drivers_list if str(d).upper() == self.driver]


# ============================================================================
# Concrete Extractors - implement specific data extraction workflows
# ============================================================================


class TelemetryExtractor(BaseDataExtractor):
    """Extract and aggregate telemetry data for drivers and laps."""

    def extract(
        self,
        driver: Optional[str] = None,
        lap: Optional[int] = None,
        limit_points: int = _DEFAULT_TELEMETRY_POINTS,
        stride: int = 1,
        sector_start: Optional[int] = None,
        sector_end: Optional[int] = None,
    ) -> dict:
        """
        Extract telemetry for specified driver/lap or all drivers' best laps.

        Args:
            driver: Optional driver code override
            lap: Optional specific lap number
            limit_points: Maximum telemetry points to return (default 800)
            stride: Sampling stride (every nth point)
            sector_start: Optional sector window start (1-3)
            sector_end: Optional sector window end (1-3)
        """
        # Use provided driver or instance driver
        target_driver = driver or self.driver
        if not target_driver:
            raise ValueError("driver parameter is required")

        # Validate parameters
        DataValidator.validate_stride(stride)
        if limit_points < 1 or limit_points > _MAX_TELEMETRY_POINTS:
            raise ValueError(f"limit_points must be between 1 and {_MAX_TELEMETRY_POINTS}")
        DataValidator.validate_sector_window(sector_start, sector_end)

        try:
            laps = self.session.laps.pick_drivers([target_driver])
            if laps.empty:
                raise ValueError(f"No laps found for driver {target_driver}")

            # Determine which lap to extract
            selected_lap_number = lap
            if selected_lap_number is None:
                valid_laps = laps[laps["LapTime"].notna()]
                if valid_laps.empty:
                    raise ValueError(f"No valid lap times for driver {target_driver}")
                # Pick fastest lap
                selected_lap_number = int(valid_laps.sort_values(by="LapTime").iloc[0]["LapNumber"])

            lap_rows = laps[laps["LapNumber"] == selected_lap_number]
            if lap_rows.empty:
                raise ValueError(f"Lap {selected_lap_number} not found for driver {target_driver}")

            selected_lap = lap_rows.iloc[0]
            telemetry = selected_lap.get_car_data().add_distance().copy()

            if telemetry.empty:
                raise ValueError(f"No telemetry data for {target_driver} lap {selected_lap_number}")

            # Apply sector window filtering
            if sector_start is not None and sector_end is not None:
                telemetry = self._apply_sector_window(telemetry, sector_start, sector_end)

            # Apply stride
            if stride > 1:
                telemetry = telemetry.iloc[::stride]

            # Apply point limit
            if len(telemetry) > limit_points:
                downsample_step = max(1, math.ceil(len(telemetry) / limit_points))
                telemetry = telemetry.iloc[::downsample_step]

            # Normalize to rows
            telemetry_rows = self._telemetry_rows_from_frame(telemetry)

            return self._build_response(
                telemetry_rows,
                additional_meta={
                    "selected_lap": int(selected_lap_number),
                    "telemetry_points": len(telemetry_rows),
                },
                additional_filters={
                    "driver": target_driver,
                    "lap": selected_lap_number,
                    "limit_points": limit_points,
                    "stride": stride,
                    "sector_window": f"{sector_start}-{sector_end}" if sector_start else None,
                },
            )
        except ValueError:
            raise
        except Exception as exc:
            raise Exception(f"Telemetry extraction error: {str(exc)}")

    @staticmethod
    def _apply_sector_window(
        telemetry: pd.DataFrame, sector_start: int, sector_end: int
    ) -> pd.DataFrame:
        """Filter telemetry to specific sector window."""
        if sector_start is None or sector_end is None or telemetry.empty:
            return telemetry
        if "Distance" not in telemetry.columns:
            return telemetry

        max_distance = telemetry["Distance"].max()
        if pd.isna(max_distance) or max_distance <= 0:
            return telemetry

        sector_size = float(max_distance) / 3.0
        start_distance = (sector_start - 1) * sector_size
        end_distance = sector_end * sector_size
        return telemetry[(telemetry["Distance"] >= start_distance) & (telemetry["Distance"] <= end_distance)]

    @staticmethod
    def _telemetry_rows_from_frame(telemetry: pd.DataFrame) -> list[dict]:
        """Convert telemetry dataframe to normalized rows."""
        rows = []
        for _, row in telemetry.iterrows():
            rows.append(
                {
                    "time_seconds": DataNormalizer.to_time_seconds(row.get("Time"), precision=4),
                    "distance_m": DataNormalizer.to_float(row.get("Distance"), precision=3),
                    "speed_kph": DataNormalizer.to_float(row.get("Speed"), precision=2),
                    "throttle_pct": DataNormalizer.to_float(row.get("Throttle"), precision=2),
                    "brake": DataNormalizer.to_bool(row.get("Brake")),
                    "drs": DataNormalizer.to_bool(row.get("DRS")),
                    "rpm": DataNormalizer.to_int(row.get("RPM")),
                    "gear": DataNormalizer.to_int(row.get("nGear")),
                }
            )
        return rows


class WeatherExtractor(BaseDataExtractor):
    """Extract weather data for sessions."""

    def extract(self, include_per_lap: bool = False) -> dict:
        """
        Extract weather information.

        Args:
            include_per_lap: If True, include per-lap weather snapshots; else session average
        """
        try:
            weather = self.session.weather
            if weather is None or weather.empty:
                raise ValueError("No weather data available for this session")

            rows = []
            if include_per_lap:
                # Per-lap weather snapshots
                laps = self.session.laps.copy()
                laps = laps[laps["LapTime"].notna()]

                if self.driver:
                    laps = laps[laps["Driver"].astype(str).str.upper() == self.driver]

                for _, lap in laps.iterrows():
                    lap_weather = lap.get("Weather") if "Weather" in lap else None
                    if lap_weather:
                        rows.append(
                            {
                                "lap_number": DataNormalizer.to_int(lap["LapNumber"]),
                                "driver_code": str(lap["Driver"]),
                                "track_temp_c": DataNormalizer.to_float(lap_weather.get("TrackTemp")),
                                "air_temp_c": DataNormalizer.to_float(lap_weather.get("AirTemp")),
                                "humidity_pct": DataNormalizer.to_float(lap_weather.get("Humidity")),
                                "wind_speed_ms": DataNormalizer.to_float(lap_weather.get("WindSpeed")),
                                "wind_direction_deg": DataNormalizer.to_float(
                                    lap_weather.get("WindDirection")
                                ),
                                "rainfall": DataNormalizer.to_bool(lap_weather.get("Rainfall")),
                            }
                        )
            else:
                # Session-level weather aggregates
                latest_weather = weather.iloc[-1] if not weather.empty else {}
                rows.append(
                    {
                        "lap_number": None,
                        "driver_code": None,
                        "track_temp_c": DataNormalizer.to_float(latest_weather.get("TrackTemp")),
                        "air_temp_c": DataNormalizer.to_float(latest_weather.get("AirTemp")),
                        "humidity_pct": DataNormalizer.to_float(latest_weather.get("Humidity")),
                        "wind_speed_ms": DataNormalizer.to_float(latest_weather.get("WindSpeed")),
                        "wind_direction_deg": DataNormalizer.to_float(latest_weather.get("WindDirection")),
                        "rainfall": DataNormalizer.to_bool(latest_weather.get("Rainfall")),
                    }
                )

            return self._build_response(rows, additional_filters={"include_per_lap": include_per_lap})
        except ValueError:
            raise
        except Exception as exc:
            raise Exception(f"Weather extraction error: {str(exc)}")


class PitStopExtractor(BaseDataExtractor):
    """Extract pit stop strategy and timing data."""

    def extract(self) -> dict:
        """Extract pit stop data for all drivers or specific driver."""
        try:
            laps = self.session.laps.copy()
            laps = laps[laps["LapTime"].notna()]

            if self.driver:
                laps = laps[laps["Driver"].astype(str).str.upper() == self.driver]

            rows = []
            pit_stop_counts = {}

            # Group by driver and extract pit stop info
            for driver_code, driver_laps in laps.groupby("Driver"):
                stop_num = 0
                for _, lap in driver_laps.sort_values("LapNumber").iterrows():
                    pit_in_lap = lap.get("PitInLap")
                    pit_out_lap = lap.get("PitOutLap")

                    if pd.notna(pit_in_lap):
                        stop_num += 1
                        pit_duration = lap.get("PitDuration")

                        rows.append(
                            {
                                "driver_code": str(driver_code),
                                "driver_number": DataNormalizer.to_int(lap.get("DriverNumber")),
                                "stop_number": stop_num,
                                "lap_in": DataNormalizer.to_int(pit_in_lap),
                                "lap_out": DataNormalizer.to_int(pit_out_lap),
                                "stop_duration_seconds": DataNormalizer.to_float(pit_duration, precision=2),
                                "compound_in": str(lap.get("Compound")) if pd.notna(lap.get("Compound")) else None,
                                "compound_out": None,  # Would need compound change tracking
                                "time_gain_loss_seconds": None,  # Calculated separately if needed
                            }
                        )

            if self.limit:
                rows = rows[: self.limit]

            return self._build_response(rows)
        except ValueError:
            raise
        except Exception as exc:
            raise Exception(f"Pit stop extraction error: {str(exc)}")


class IncidentExtractor(BaseDataExtractor):
    """Extract incidents, messages, and race events."""

    def extract(self, include_radio: bool = False) -> dict:
        """
        Extract incidents and messages.

        Args:
            include_radio: If True, include radio messages; else only incidents
        """
        try:
            messages = self.session.messages
            if messages is None or messages.empty:
                rows = []
            else:
                rows = []
                for _, msg in messages.iterrows():
                    msg_type = str(msg.get("Type", "message")).lower()

                    # Filter by type
                    if not include_radio and "radio" in msg_type:
                        continue

                    drivers_involved = []
                    if pd.notna(msg.get("Driver")):
                        drivers_involved.append(str(msg["Driver"]))
                    if pd.notna(msg.get("Driver2")):
                        drivers_involved.append(str(msg["Driver2"]))

                    rows.append(
                        {
                            "lap_number": DataNormalizer.to_int(msg.get("Lap")),
                            "message_type": msg_type,
                            "drivers_involved": drivers_involved,
                            "message_text": str(msg.get("Message", "")),
                            "timestamp_seconds": DataNormalizer.to_time_seconds(msg.get("Time")),
                            "impact_on_race": self._categorize_impact(msg_type),
                        }
                    )

            if self.limit:
                rows = rows[: self.limit]

            return self._build_response(rows, additional_filters={"include_radio": include_radio})
        except ValueError:
            raise
        except Exception as exc:
            raise Exception(f"Incident extraction error: {str(exc)}")

    @staticmethod
    def _categorize_impact(msg_type: str) -> str:
        """Categorize message impact on race."""
        msg_type_lower = msg_type.lower()
        if any(x in msg_type_lower for x in ["crash", "retirement", "dnf"]):
            return "high"
        elif any(x in msg_type_lower for x in ["safety", "yellow", "flag"]):
            return "medium"
        elif any(x in msg_type_lower for x in ["pit", "stop"]):
            return "low"
        return "unknown"


class PositionExtractor(BaseDataExtractor):
    """Extract position changes and gaps over race distance."""

    def extract(self, sample_interval: int = 5) -> dict:
        """
        Extract position and gap data.

        Args:
            sample_interval: Sample every N laps for position data
        """
        try:
            laps = self.session.laps.copy()
            laps = laps[laps["LapTime"].notna()]

            if self.driver:
                laps = laps[laps["Driver"].astype(str).str.upper() == self.driver]

            rows = []
            lap_numbers = sorted(laps["LapNumber"].unique())

            # Sample laps at interval
            sampled_laps = [ln for ln in lap_numbers if ln % sample_interval == 0 or ln == lap_numbers[-1]]

            for lap_num in sampled_laps:
                lap_slice = laps[laps["LapNumber"] == lap_num]
                if lap_slice.empty:
                    continue

                # Get all drivers' positions at this lap
                for driver_code, driver_group in lap_slice.groupby("Driver"):
                    lap_row = driver_group.iloc[0]
                    rows.append(
                        {
                            "driver_code": str(driver_code),
                            "driver_number": DataNormalizer.to_int(lap_row.get("DriverNumber")),
                            "lap_number": DataNormalizer.to_int(lap_num),
                            "position": DataNormalizer.to_int(lap_row.get("Position")),
                            "position_change": None,  # Would need prior lap data
                            "gap_to_leader_seconds": None,  # Would need race delta data
                            "gap_to_ahead_seconds": None,  # Would need interval data
                        }
                    )

            if self.limit:
                rows = rows[: self.limit]

            return self._build_response(rows, additional_filters={"sample_interval": sample_interval})
        except ValueError:
            raise
        except Exception as exc:
            raise Exception(f"Position extraction error: {str(exc)}")


class DRSExtractor(BaseDataExtractor):
    """Extract DRS activation data."""

    def extract(self) -> dict:
        """Extract DRS activation by driver and lap."""
        try:
            laps = self.session.laps.copy()
            laps = laps[laps["LapTime"].notna()]

            if self.driver:
                laps = laps[laps["Driver"].astype(str).str.upper() == self.driver]

            rows = []
            for _, lap in laps.iterrows():
                drs_available = "DRS" in lap and pd.notna(lap.get("DRS"))
                drs_activated = drs_available and DataNormalizer.to_bool(lap.get("DRS"))

                rows.append(
                    {
                        "driver_code": str(lap.get("Driver")),
                        "driver_number": DataNormalizer.to_int(lap.get("DriverNumber")),
                        "lap_number": DataNormalizer.to_int(lap.get("LapNumber")),
                        "drs_available": drs_available,
                        "drs_activated": drs_activated,
                        "gap_behind_seconds": None,  # Would need gap data
                        "performance_delta_ms": None,  # Would need delta calculation
                    }
                )

            if self.limit:
                rows = rows[: self.limit]

            return self._build_response(rows)
        except ValueError:
            raise
        except Exception as exc:
            raise Exception(f"DRS extraction error: {str(exc)}")


class TrackStatusExtractor(BaseDataExtractor):
    """Extract track status timeline."""

    def extract(self) -> dict:
        """Extract track status changes (flags, safety car, etc)."""
        try:
            track_status = self.session.track_status
            if track_status is None or track_status.empty:
                rows = []
            else:
                rows = []
                prev_status = None
                prev_lap = None

                for _, row in track_status.iterrows():
                    status = str(row.get("Status", "UNKNOWN"))
                    lap = DataNormalizer.to_int(row.get("Lap"))
                    time = row.get("Time")

                    if status != prev_status:
                        rows.append(
                            {
                                "lap_number": lap,
                                "status": status,
                                "status_duration_laps": None,  # Calculated from gaps
                                "cause": self._map_status_to_cause(status),
                                "affected_zone": None,
                            }
                        )
                        prev_status = status
                        prev_lap = lap

            if self.limit:
                rows = rows[: self.limit]

            return self._build_response(rows)
        except ValueError:
            raise
        except Exception as exc:
            raise Exception(f"Track status extraction error: {str(exc)}")

    @staticmethod
    def _map_status_to_cause(status: str) -> Optional[str]:
        """Map status to likely cause."""
        status_lower = status.lower()
        if "yellow" in status_lower:
            return "Yellow flag incident"
        elif "red" in status_lower:
            return "Red flag incident"
        elif "safety" in status_lower:
            return "Safety car deployed"
        elif "virtual" in status_lower:
            return "Virtual safety car"
        return None


# Registry for extractor classes (used by unified endpoint)
EXTRACTORS_MAP = {
    "telemetry": TelemetryExtractor,
    "weather": WeatherExtractor,
    "pit_stops": PitStopExtractor,
    "incidents": IncidentExtractor,
    "positions": PositionExtractor,
    "drs": DRSExtractor,
    "track_status": TrackStatusExtractor,
}
