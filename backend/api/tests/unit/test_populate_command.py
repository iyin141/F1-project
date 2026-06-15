from datetime import date
from unittest.mock import Mock, patch

import pandas as pd
from django.core.management import call_command
from django.test import TestCase

from api.models import DriverLapAnalysis, RaceResultData, SeasonSchedule


class PopulateRaceCommandTests(TestCase):
    @patch("api.management.commands.populate_race.fastf1.get_session")
    @patch("api.results.parsing.parse_session_once")
    @patch("api.management.commands.populate_race.get_race_by_round")
    @patch("api.management.commands.populate_race.get_race_session_results")
    def test_populate_race_creates_persisted_rows(
        self,
        mock_get_race_session_results,
        mock_get_race_by_round,
        mock_parse_session_once,
        mock_get_session,
    ):
        mock_get_race_session_results.return_value = [{"position": 1, "driver_code": "VER", "driver_name": "Max Verstappen", "driver_number": 1, "points": 25, "team": "Red Bull", "status": "Finished", "laps": 57, "grid_position": 1, "gap": "LEADER", "fastest_lap": None, "fastest_lap_of_race": False}]
        mock_get_race_by_round.return_value = {
            "round": 1,
            "name": "Bahrain Grand Prix",
            "date": date(2024, 3, 2),
            "location": "Sakhir",
            "country": "Bahrain",
        }

        mock_session = Mock()
        mock_get_session.return_value = mock_session

        mock_parsed = Mock()
        mock_parsed.all_drivers = ["VER"]
        mock_parsed.laps_by_driver = {
            "VER": [{"lap_number": 1, "lap_time": 95.5}]
        }
        mock_parsed.stints_by_driver = {
            "VER": [{"driver_code": "VER", "stint_number": 1, "compound": "SOFT", "lap_start": 1, "lap_end": 20}]
        }
        mock_parsed.tyre_by_driver = {
            "VER": [{"driver_code": "VER", "stint_number": 1, "compound": "SOFT", "lap_start": 1, "lap_end": 20}]
        }
        mock_parsed.pace_by_driver = {
            "VER": {"laps_completed": 57, "session_median_lap_seconds": 95.5}
        }
        mock_parsed.sectors_by_driver = {
            "VER": {"laps_count": 57, "best_sector1_seconds": 30.111}
        }
        mock_parsed.race_results = [
            {
                "driver_code": "VER",
                "driver_number": 1,
                "driver_name": "Max Verstappen",
                "team": "Red Bull Racing",
                "position": 1,
                "points": 25,
                "status": "Finished",
                "laps": 57,
            }
        ]
        mock_parse_session_once.return_value = mock_parsed

        call_command("populate_race", "--year", "2024", "--round", "1")

        self.assertTrue(
            RaceResultData.objects.filter(year=2024, round_number=1, session="R").exists()
        )
        result_record = RaceResultData.objects.get(year=2024, round_number=1, session="R")
        # The persisted canonical data is stored under `payload['data']` and
        # should match the RaceResultSerializer output (driver_number/driver_name).
        self.assertEqual(len(result_record.payload.get("data", [])), 1)
        self.assertEqual(result_record.payload["data"][0].get("driver_number"), 1)
        self.assertEqual(result_record.payload["data"][0].get("driver_name"), "Max Verstappen")

        self.assertTrue(
            DriverLapAnalysis.objects.filter(year=2024, round_number=1, session="R", driver_code="VER").exists()
        )
        lap_record = DriverLapAnalysis.objects.get(year=2024, round_number=1, session="R", driver_code="VER")
        self.assertIn("stints", lap_record.payload)
        self.assertIn("pace", lap_record.payload)
        self.assertIn("sectors", lap_record.payload)

        self.assertTrue(SeasonSchedule.objects.filter(year=2024).exists())

    @patch("api.management.commands.populate_race.get_race_by_round")
    def test_populate_race_skips_already_populated_without_force(self, mock_get_race_by_round):
        mock_get_race_by_round.return_value = {
            "round": 1,
            "name": "Bahrain Grand Prix",
            "date": date(2024, 3, 2),
            "location": "Sakhir",
            "country": "Bahrain",
        }

        RaceResultData.objects.create(
            year=2024,
            round_number=1,
            session="R",
            payload={"results": [{"driver_code": "VER"}]},
        )

        call_command("populate_race", "--year", "2024", "--round", "1")

        # Still only one record (command skipped)
        self.assertEqual(RaceResultData.objects.filter(year=2024, round_number=1, session="R").count(), 1)
        mock_get_race_by_round.assert_called_once_with(2024, 1)



