from unittest.mock import patch

from django.test import TestCase

from api.models import DriverLapAnalysis, RaceResultData
from api.services.analysis import get_pace_analysis, get_sector_analysis, get_stint_analysis, get_tyre_strategy_analysis
from api.services.results import get_race_results
from api.services.schedule import get_race_by_round


class PersistenceFallbackTests(TestCase):
    def setUp(self):
        RaceResultData.objects.create(
            year=2024,
            round_number=1,
            session="R",
            payload={
                "results": [
                    {
                        "driver_code": "VER",
                        "driver_number": 1,
                        "driver_name": "Max Verstappen",
                        "team": "Red Bull Racing",
                        "position": 1,
                        "grid_position": 1,
                        "points": 25.0,
                        "status": "Finished",
                        "fastest_lap": False,
                        "laps": 57,
                    }
                ]
            },
        )

        DriverLapAnalysis.objects.create(
            year=2024,
            round_number=1,
            session="R",
            driver_code="VER",
            payload={
                "stints": [
                    {
                        "driver_code": "VER",
                        "driver_number": 1,
                        "stint_number": 1,
                        "compound": "SOFT",
                        "lap_start": 1,
                        "lap_end": 20,
                        "total_laps": 20,
                        "median_lap_seconds": 95.08,
                        "min_lap_seconds": 94.8,
                        "max_lap_seconds": 96.0,
                    }
                ],
                "tyre_strategy": [
                    {
                        "driver_code": "VER",
                        "driver_number": 1,
                        "stint_number": 1,
                        "compound": "SOFT",
                        "lap_start": 1,
                        "lap_end": 20,
                        "laps_in_stint": 20,
                        "avg_lap_seconds": 95.1,
                        "median_lap_seconds": 95.08,
                        "degradation_seconds": 0.7,
                    }
                ],
                "pace": {
                    "driver_code": "VER",
                    "driver_number": 1,
                    "laps_completed": 57,
                    "session_median_lap_seconds": 95.5,
                    "session_best_lap_seconds": None,
                    "consistency_stddev_seconds": 0.42,
                    "pace_improvement_seconds": None,
                },
                "sectors": {
                    "driver_code": "VER",
                    "driver_number": 1,
                    "laps_count": 57,
                    "best_sector1_seconds": 30.111,
                    "best_sector2_seconds": 35.222,
                    "best_sector3_seconds": 28.333,
                    "median_sector1_seconds": 30.444,
                    "median_sector2_seconds": 35.555,
                    "median_sector3_seconds": 28.666,
                    "best_lap_seconds": 93.9,
                    "theoretical_best_lap_seconds": 93.666,
                    "delta_to_theoretical_seconds": 0.234,
                },
            },
        )

    @patch("api.services.analysis.fastf1.get_session")
    def test_get_stint_analysis_uses_persisted_data_for_race_session(self, mock_get_session):
        payload = get_stint_analysis(year=2024, round_number=1, session="R", driver="VER", limit=5)

        self.assertEqual(payload["meta"]["row_count"], 1)
        self.assertEqual(payload["data"][0]["driver_code"], "VER")
        mock_get_session.assert_not_called()

    @patch("api.services.analysis.fastf1.get_session")
    def test_get_pace_analysis_uses_persisted_data_for_race_session(self, mock_get_session):
        payload = get_pace_analysis(year=2024, round_number=1, session="R", driver="VER", limit=5)

        self.assertEqual(payload["meta"]["row_count"], 1)
        self.assertEqual(payload["data"][0]["driver_code"], "VER")
        self.assertEqual(payload["data"][0]["laps_completed"], 57)
        mock_get_session.assert_not_called()

    @patch("api.services.analysis.fastf1.get_session")
    def test_get_tyre_strategy_uses_persisted_data_for_race_session(self, mock_get_session):
        payload = get_tyre_strategy_analysis(year=2024, round_number=1, session="R", driver="VER", limit=5)

        self.assertEqual(payload["meta"]["row_count"], 1)
        self.assertEqual(payload["data"][0]["compound"], "SOFT")
        mock_get_session.assert_not_called()

    @patch("api.services.schedule.get_season_schedule")
    def test_get_race_by_round_uses_persisted_data(self, mock_get_season_schedule):
        from api.models import SeasonSchedule

        SeasonSchedule.objects.create(
            year=2024,
            payload={
                "races": [
                    {
                        "round": 1,
                        "name": "Bahrain Grand Prix",
                        "date": "2024-03-02",
                        "location": "Sakhir",
                        "country": "Bahrain",
                    }
                ]
            },
        )

        race = get_race_by_round(year=2024, round_number=1)

        self.assertIsNotNone(race)
        self.assertEqual(race["name"], "Bahrain Grand Prix")
        mock_get_season_schedule.assert_not_called()

    @patch("api.services.results.get_qualifying_results", return_value=[])
    @patch("api.services.results.fastf1.get_session")
    def test_get_race_results_uses_persisted_race_rows(self, mock_get_session, _mock_get_qualifying):
        payload = get_race_results(year=2024, round_number=1)

        self.assertEqual(len(payload["race"]), 1)
        self.assertEqual(payload["race"][0]["driver_name"], "Max Verstappen")
        mock_get_session.assert_not_called()

    @patch("api.services.analysis.fastf1.get_session")
    def test_get_sector_analysis_uses_persisted_data_for_race_session(self, mock_get_session):
        payload = get_sector_analysis(year=2024, round_number=1, session="R", driver="VER", limit=5)

        self.assertEqual(payload["meta"]["row_count"], 1)
        self.assertEqual(payload["data"][0]["driver_code"], "VER")
        self.assertEqual(payload["data"][0]["theoretical_best_lap_seconds"], 93.666)
        mock_get_session.assert_not_called()



