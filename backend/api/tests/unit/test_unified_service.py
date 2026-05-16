from unittest.mock import patch

import pandas as pd
from django.test import TestCase

from api.services.unified_service import SessionManager, WeatherExtractor


class _PartialSession:
    def __init__(self):
        self.laps = pd.DataFrame()
        self.weather = pd.DataFrame(
            [
                {
                    "TrackTemp": 31.2,
                    "AirTemp": 24.8,
                    "Humidity": 42.0,
                    "WindSpeed": 3.4,
                    "WindDirection": 180,
                    "Rainfall": False,
                }
            ]
        )
        self.messages = pd.DataFrame()
        self.track_status = pd.DataFrame()

    def load(self, telemetry=False, weather=False, messages=False, laps=True, **kwargs):
        raise Exception(
            "The data you are trying to access has not been loaded yet. See `Session.load`"
        )


class UnifiedServiceTests(TestCase):
    def setUp(self):
        SessionManager.clear_cache()

    @patch("api.services.unified_service.fastf1.get_session")
    def test_session_manager_retains_partial_session_on_unsupported_load(self, mock_get_session):
        partial_session = _PartialSession()
        mock_get_session.return_value = partial_session

        loaded_session = SessionManager.get_session(2016, 2, "R")
        cached_session = SessionManager.get_session(2016, 2, "R")

        self.assertIs(loaded_session, partial_session)
        self.assertIs(cached_session, partial_session)
        self.assertEqual(mock_get_session.call_count, 1)

    @patch("api.services.unified_service.fastf1.get_session")
    def test_weather_extractor_uses_partially_loaded_session(self, mock_get_session):
        partial_session = _PartialSession()
        mock_get_session.return_value = partial_session

        loaded_session = SessionManager.get_session(2016, 2, "R")
        payload = WeatherExtractor(loaded_session, 2016, 2, "R").extract()

        self.assertEqual(payload["meta"]["row_count"], 1)
        self.assertEqual(payload["data"][0]["track_temp_c"], 31.2)
        self.assertEqual(payload["data"][0]["air_temp_c"], 24.8)