import json
from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from api.models import DriverMetric, Race, RaceResult, SectorAggregate, StintData


class PersistenceCoverageCommandTests(TestCase):
    def test_persistence_coverage_json_reports_db_first_flags(self):
        race = Race.objects.create(
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
            race=race,
            driver_code="VER",
            driver_number=1,
            driver_name="Max Verstappen",
            constructor_name="Red Bull Racing",
            finish_position=1,
            points=25,
        )
        StintData.objects.create(
            race=race,
            driver_code="VER",
            driver_number=1,
            stint_number=1,
            compound="SOFT",
            lap_start=1,
            lap_end=20,
            laps_in_stint=20,
            computed_at=timezone.now(),
        )
        DriverMetric.objects.create(
            race=race,
            season=2024,
            driver_code="VER",
            valid_lap_count=57,
            season_aggregate=False,
            formula_version="consistency_v1",
            computed_at=timezone.now(),
        )
        SectorAggregate.objects.create(
            race=race,
            driver_code="VER",
            driver_number=1,
            laps_count=57,
            computed_at=timezone.now(),
        )

        out = StringIO()
        call_command("persistence_coverage", "--year", "2024", "--json", stdout=out)
        payload = json.loads(out.getvalue())

        self.assertEqual(payload["race_count"], 1)
        item = payload["coverage"][0]
        self.assertEqual(item["round"], 1)
        self.assertEqual(item["counts"]["sectors"], 1)
        self.assertTrue(item["db_first_flags"]["analysis_sector"])
        self.assertTrue(item["db_first_flags"]["all_db_first_ready"])

    def test_persistence_coverage_plain_text_does_not_raise(self):
        race = Race.objects.create(
            season=2024,
            round_number=2,
            race_name="Saudi Arabian Grand Prix",
            circuit_name="Jeddah Corniche Circuit",
            country="Saudi Arabia",
            location="Jeddah",
            race_date=date(2024, 3, 9),
            status=Race.Status.COMPLETED,
            populated_at=timezone.now(),
        )
        RaceResult.objects.create(
            race=race,
            driver_code="NOR",
            driver_number=4,
            driver_name="Lando Norris",
            constructor_name="McLaren",
            finish_position=1,
            points=25,
        )

        out = StringIO()
        # Must not raise NameError - non-JSON path iterates payload.get("coverage")
        call_command("persistence_coverage", "--year", "2024", "--round", "2", stdout=out)
        output = out.getvalue()

        self.assertIn("R02", output)
        self.assertIn("Saudi Arabian Grand Prix", output)
