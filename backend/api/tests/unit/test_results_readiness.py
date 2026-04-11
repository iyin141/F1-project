from unittest.mock import patch

import pandas as pd
from django.test import TestCase

from api.services.results import get_practice_session_results, get_qualifying_results, get_race_results


class _FakeSession:
    def __init__(self, laps=None, results=None):
        self.laps = laps if laps is not None else pd.DataFrame()
        self.results = results if results is not None else pd.DataFrame()

    def load(self, telemetry=False, weather=False, messages=False, laps=False):
        return None


class ResultsReadinessTests(TestCase):
    @patch("api.services.results.fastf1.get_session")
    def test_practice_returns_non_blocking_readiness_when_unsupported(self, mock_get_session):
        session = _FakeSession()

        def _raise_on_load(*args, **kwargs):
            raise Exception(
                "Cannot load laps, telemetry, weather, and message data because the relevant API is not supported for this session."
            )

        session.load = _raise_on_load
        mock_get_session.return_value = session

        payload = get_practice_session_results(2017, 2, "FP1")

        self.assertEqual(payload["meta"]["row_count"], 0)
        self.assertFalse(payload["meta"]["readiness"]["can_proceed"])
        self.assertIn("laps", payload["meta"]["readiness"]["unavailable_data"])
        self.assertEqual(payload["data"], [])

    @patch("api.services.results.fastf1.get_session")
    def test_practice_returns_non_blocking_readiness_when_schedule_data_unavailable(self, mock_get_session):
        session = _FakeSession()

        def _raise_on_load(*args, **kwargs):
            raise Exception("Failed to load any schedule data.")

        session.load = _raise_on_load
        mock_get_session.return_value = session

        payload = get_practice_session_results(1990, 2, "FP1")

        self.assertEqual(payload["meta"]["row_count"], 0)
        self.assertFalse(payload["meta"]["readiness"]["can_proceed"])
        self.assertIn("laps", payload["meta"]["readiness"]["unavailable_data"])
        self.assertIn("Failed to load any schedule data", payload["meta"]["readiness"]["message"])
        self.assertEqual(payload["data"], [])

    @patch("api.services.results.fastf1.get_session")
    def test_practice_returns_partial_results_fallback_when_laps_missing_but_results_exist(self, mock_get_session):
        session = _FakeSession(
            laps=pd.DataFrame(),
            results=pd.DataFrame(
                [
                    {
                        "Position": 1,
                        "DriverNumber": 1,
                        "Abbreviation": "VER",
                        "FullName": "Max Verstappen",
                        "TeamName": "Red Bull Racing",
                        "LapTime": pd.to_timedelta("00:01:31.123"),
                        "LapNumber": 7,
                    }
                ]
            ),
        )
        mock_get_session.return_value = session

        payload = get_practice_session_results(2017, 2, "FP1")

        self.assertEqual(payload["meta"]["row_count"], 1)
        self.assertTrue(payload["meta"]["readiness"]["can_proceed"])
        self.assertIn("results", payload["meta"]["readiness"]["available_data"])
        self.assertIn("laps", payload["meta"]["readiness"]["unavailable_data"])
        self.assertEqual(payload["data"][0]["driver_code"], "VER")
        self.assertEqual(payload["data"][0]["lap_time"], "0 days 00:01:31.123000")

    @patch("api.services.results.fastf1.get_session")
    def test_qualifying_returns_non_blocking_readiness_when_unsupported(self, mock_get_session):
        session = _FakeSession()

        def _raise_on_load(*args, **kwargs):
            raise Exception(
                "Cannot load laps, telemetry, weather, and message data because the relevant API is not supported for this session."
            )

        session.load = _raise_on_load
        mock_get_session.return_value = session

        payload = get_qualifying_results(2017, 2)

        self.assertEqual(payload["meta"]["row_count"], 0)
        self.assertFalse(payload["meta"]["readiness"]["can_proceed"])
        self.assertIn("results", payload["meta"]["readiness"]["unavailable_data"])
        self.assertEqual(payload["data"], [])

    @patch("api.services.results.get_qualifying_results")
    @patch("api.services.results.get_persisted_race_results")
    def test_race_results_returns_partial_when_qualifying_unavailable_but_persisted_race_exists(
        self, mock_persisted_race, mock_qualifying
    ):
        mock_persisted_race.return_value = [
            {
                "position": 1,
                "driver_number": 1,
                "driver_name": "Max Verstappen",
                "team": "Red Bull Racing",
                "points": 25,
                "status": "Finished",
                "grid_position": 1,
                "laps": 57,
            }
        ]
        mock_qualifying.return_value = {
            "meta": {
                "year": 2017,
                "round": 2,
                "session": "Q",
                "row_count": 0,
                "readiness": {
                    "can_proceed": False,
                    "available_data": [],
                    "unavailable_data": ["results"],
                    "message": "Session loaded, but required data is unavailable for 2017 Round 2 (Q). Missing: results.",
                    "warnings": [
                        "Session loaded, but required data is unavailable for 2017 Round 2 (Q). Missing: results."
                    ],
                },
            },
            "data": [],
        }

        payload = get_race_results(year=2017, round_number=2)

        self.assertTrue(payload["readiness"]["can_proceed"])
        self.assertEqual(len(payload["race"]), 1)
        self.assertEqual(payload["qualifying"], [])
        self.assertIn("results", payload["readiness"]["unavailable_data"])
