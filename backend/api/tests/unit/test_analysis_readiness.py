from unittest.mock import patch

import pandas as pd
from django.test import TestCase

from api.services.analysis import get_lap_analysis


class _FakeSession:
    def __init__(self, laps: pd.DataFrame):
        self.laps = laps
        self.weather = pd.DataFrame()
        self.messages = pd.DataFrame()
        self.track_status = pd.DataFrame()

    def load(self, telemetry=False, weather=False, messages=False):
        return None


class AnalysisReadinessTests(TestCase):
    @patch("api.services.analysis.fastf1.get_session")
    def test_lap_analysis_returns_readiness_payload_when_session_unsupported(self, mock_get_session):
        mock_session = _FakeSession(laps=pd.DataFrame())

        def _raise_on_load(*args, **kwargs):
            raise Exception("Cannot load laps, telemetry, weather, and message data because the relevant API is not supported for this session.")

        mock_session.load = _raise_on_load
        mock_get_session.return_value = mock_session

        payload = get_lap_analysis(year=2016, round_number=3, session="R")

        self.assertEqual(payload["meta"]["can_proceed"], False)
        self.assertIn("laps", payload["meta"]["unavailable_data"])
        self.assertEqual(payload["meta"]["row_count"], 0)
        self.assertEqual(payload["data"], [])
        self.assertTrue(payload["meta"]["message"])

    @patch("api.services.analysis.fastf1.get_session")
    def test_lap_analysis_returns_readiness_payload_when_schedule_data_unavailable(self, mock_get_session):
        mock_session = _FakeSession(laps=pd.DataFrame())

        def _raise_on_load(*args, **kwargs):
            raise Exception("Failed to load any schedule data.")

        mock_session.load = _raise_on_load
        mock_get_session.return_value = mock_session

        payload = get_lap_analysis(year=1990, round_number=2, session="R")

        self.assertEqual(payload["meta"]["can_proceed"], False)
        self.assertIn("laps", payload["meta"]["unavailable_data"])
        self.assertIn("Failed to load any schedule data", payload["meta"]["message"])
        self.assertEqual(payload["meta"]["row_count"], 0)
        self.assertEqual(payload["data"], [])

    @patch("api.services.analysis.fastf1.get_session")
    def test_lap_analysis_keeps_working_for_supported_session(self, mock_get_session):
        laps = pd.DataFrame(
            [
                {
                    "Driver": "VER",
                    "LapNumber": 1,
                    "LapTime": pd.to_timedelta("00:01:31"),
                    "Sector1Time": pd.to_timedelta("00:00:30"),
                    "Sector2Time": pd.to_timedelta("00:00:30"),
                    "Sector3Time": pd.to_timedelta("00:00:31"),
                    "Compound": "SOFT",
                    "Stint": 1,
                    "IsPersonalBest": True,
                }
            ]
        )

        mock_get_session.return_value = _FakeSession(laps=laps)

        payload = get_lap_analysis(year=2020, round_number=2, session="R", limit=5)

        self.assertEqual(payload["meta"]["can_proceed"], True)
        self.assertEqual(payload["meta"]["row_count"], 1)
        self.assertEqual(payload["data"][0]["driver_code"], "VER")