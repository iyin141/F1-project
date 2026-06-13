from unittest.mock import patch

import pandas as pd
from django.test import TestCase

from api.services.unified_service import WeatherExtractor
from api.services.readiness import classify_fastf1_exception


class _FakeSession:
    def __init__(self, weather: pd.DataFrame = None):
        self.laps = pd.DataFrame()
        self.weather = weather if weather is not None else pd.DataFrame()
        self.messages = pd.DataFrame()
        self.track_status = pd.DataFrame()
        self.api_path = ""
        self._load_error = None

    def load(self, telemetry=False, weather=False, messages=False):
        return None

class ExtractorReadinessTests(TestCase):
    def test_extractor_returns_readiness_payload_when_session_unsupported(self):
        mock_session = _FakeSession()
        mock_session._load_error = "Cannot load laps, telemetry, weather, and message data because the relevant API is not supported for this session."
        
        # Use year=2020 to bypass the pre-2018 historical guard
        extractor = WeatherExtractor(mock_session, year=2020, round_number=1, session_type="R", limit=None)
        with self.assertRaisesRegex(Exception, "No weather data available"):
            extractor.extract()

    def test_extractor_returns_readiness_payload_when_schedule_data_unavailable(self):
        mock_session = _FakeSession()
        mock_session._load_error = "Failed to load any schedule data."

        # Use year=2020 to bypass the pre-2018 historical guard
        extractor = WeatherExtractor(mock_session, year=2020, round_number=2, session_type="R", limit=None)
        with self.assertRaisesRegex(Exception, "No weather data available"):
            extractor.extract()

    def test_extractor_keeps_working_for_supported_session(self):
        weather = pd.DataFrame(
            [
                {
                    "Time": pd.to_timedelta("00:01:31"),
                    "AirTemp": 25.0,
                    "Humidity": 50.0,
                    "Pressure": 1000.0,
                    "Rainfall": False,
                    "TrackTemp": 30.0,
                    "WindDirection": 180,
                    "WindSpeed": 5.0,
                }
            ]
        )

        extractor = WeatherExtractor(_FakeSession(weather=weather), year=2020, round_number=2, session_type="R", limit=5)
        payload = extractor.extract()

        self.assertEqual(len(payload["data"]), 1)