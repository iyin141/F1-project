from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from api.models import DriverMetric, Race, RaceResult, SectorAggregate, StintData
from api.services.analysis import get_pace_analysis, get_sector_analysis, get_stint_analysis, get_tyre_strategy_analysis
from api.services.results import get_race_results
from api.services.schedule import get_race_by_round


class PersistenceFallbackTests(TestCase):
    def setUp(self):
        self.race = Race.objects.create(
            season=2024,
            round_number=1,
            race_name="Bahrain Grand Prix",
            circuit_name="Bahrain International Circuit",
            country="Bahrain",
            location="Sakhir",
            race_date=date(2024, 3, 2),
            status=Race.Status.COMPLETED,
            populated_at=timezone.now(),
        )

        RaceResult.objects.create(
            race=self.race,
            driver_code="VER",
            driver_number=1,
            driver_name="Max Verstappen",
            constructor_name="Red Bull Racing",
            finish_position=1,
            points=Decimal("25.00"),
        )

        StintData.objects.create(
            race=self.race,
            driver_code="VER",
            driver_number=1,
            stint_number=1,
            compound="SOFT",
            lap_start=1,
            lap_end=20,
            laps_in_stint=20,
            avg_lap_seconds=Decimal("95.100"),
            median_lap_seconds=Decimal("95.080"),
            min_lap_seconds=Decimal("94.800"),
            max_lap_seconds=Decimal("96.000"),
            degradation_seconds=Decimal("0.700"),
            computed_at=timezone.now(),
        )

        DriverMetric.objects.create(
            race=self.race,
            season=2024,
            driver_code="VER",
            consistency_score=Decimal("0.4200"),
            avg_pace_seconds=Decimal("95.500"),
            valid_lap_count=57,
            season_aggregate=False,
            formula_version="consistency_v1",
            computed_at=timezone.now(),
        )

        SectorAggregate.objects.create(
            race=self.race,
            driver_code="VER",
            driver_number=1,
            laps_count=57,
            best_sector1_seconds=Decimal("30.111"),
            best_sector2_seconds=Decimal("35.222"),
            best_sector3_seconds=Decimal("28.333"),
            median_sector1_seconds=Decimal("30.444"),
            median_sector2_seconds=Decimal("35.555"),
            median_sector3_seconds=Decimal("28.666"),
            best_lap_seconds=Decimal("93.900"),
            theoretical_best_lap_seconds=Decimal("93.666"),
            delta_to_theoretical_seconds=Decimal("0.234"),
            computed_at=timezone.now(),
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
