from datetime import date
from unittest.mock import Mock, patch

import pandas as pd
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from api.models import DriverMetric, Race, RaceResult, SectorAggregate, StintData


class PopulateRaceCommandTests(TestCase):
    @patch("api.management.commands.populate_race.fastf1.get_session")
    @patch("api.management.commands.populate_race.get_sector_analysis")
    @patch("api.management.commands.populate_race.get_pace_analysis")
    @patch("api.management.commands.populate_race.get_stint_analysis")
    @patch("api.management.commands.populate_race.get_race_by_round")
    def test_populate_race_creates_persisted_rows(
        self,
        mock_get_race_by_round,
        mock_get_stint_analysis,
        mock_get_pace_analysis,
        mock_get_sector_analysis,
        mock_get_session,
    ):
        mock_get_race_by_round.return_value = {
            "round": 1,
            "name": "Bahrain Grand Prix",
            "date": date(2024, 3, 2),
            "location": "Sakhir",
            "country": "Bahrain",
        }

        mock_get_stint_analysis.return_value = {
            "data": [
                {
                    "driver_code": "VER",
                    "driver_number": 1,
                    "stint_number": 1,
                    "compound": "SOFT",
                    "lap_start": 1,
                    "lap_end": 20,
                    "total_laps": 20,
                    "median_lap_seconds": 95.123,
                    "min_lap_seconds": 94.9,
                    "max_lap_seconds": 96.0,
                }
            ]
        }

        mock_get_pace_analysis.return_value = {
            "data": [
                {
                    "driver_code": "VER",
                    "laps_completed": 57,
                    "session_median_lap_seconds": 95.5,
                    "consistency_stddev_seconds": 0.42,
                }
            ]
        }

        mock_get_sector_analysis.return_value = {
            "data": [
                {
                    "driver_code": "VER",
                    "driver_number": 1,
                    "laps_count": 57,
                    "best_sector1_seconds": 30.111,
                    "best_sector2_seconds": 35.222,
                    "best_sector3_seconds": 28.333,
                    "median_sector1_seconds": 30.444,
                    "median_sector2_seconds": 35.555,
                    "median_sector3_seconds": 28.666,
                    "best_lap_seconds": 93.900,
                    "theoretical_best_lap_seconds": 93.666,
                    "delta_to_theoretical_seconds": 0.234,
                }
            ]
        }

        mock_session = Mock()
        mock_session.results = pd.DataFrame(
            [
                {
                    "Abbreviation": "VER",
                    "DriverNumber": 1,
                    "FullName": "Max Verstappen",
                    "TeamName": "Red Bull Racing",
                    "GridPosition": 1,
                    "Position": 1,
                    "Points": 25,
                    "Status": "Finished",
                    "Laps": 57,
                }
            ]
        )
        mock_get_session.return_value = mock_session

        call_command("populate_race", "--year", "2024", "--round", "1")

        race = Race.objects.get(season=2024, round_number=1)
        self.assertEqual(race.status, Race.Status.COMPLETED)
        self.assertIsNotNone(race.populated_at)

        self.assertEqual(RaceResult.objects.filter(race=race).count(), 1)
        self.assertEqual(StintData.objects.filter(race=race).count(), 1)
        self.assertEqual(DriverMetric.objects.filter(race=race, season_aggregate=False).count(), 1)
        self.assertEqual(SectorAggregate.objects.filter(race=race).count(), 1)

    @patch("api.management.commands.populate_race.get_race_by_round")
    def test_populate_race_skips_already_populated_without_force(self, mock_get_race_by_round):
        mock_get_race_by_round.return_value = {
            "round": 1,
            "name": "Bahrain Grand Prix",
            "date": date(2024, 3, 2),
            "location": "Sakhir",
            "country": "Bahrain",
        }

        race = Race.objects.create(
            season=2024,
            round_number=1,
            race_name="Bahrain Grand Prix",
            circuit_name="Bahrain Grand Prix",
            country="Bahrain",
            location="Sakhir",
            race_date=date(2024, 3, 2),
            status=Race.Status.COMPLETED,
            populated_at=timezone.now(),
        )

        call_command("populate_race", "--year", "2024", "--round", "1")

        race.refresh_from_db()
        self.assertEqual(race.status, Race.Status.COMPLETED)
        mock_get_race_by_round.assert_called_once_with(2024, 1)
