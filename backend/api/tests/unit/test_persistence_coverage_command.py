import io
import json
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from api.models import DriverLapAnalysis, RaceResultData, SeasonSchedule


class PersistenceCoverageCommandTests(TestCase):
    def setUp(self):
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
                        "points": 25.0,
                        "status": "Finished",
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
                "stints": [{"stint_number": 1, "compound": "SOFT"}],
                "tyre_strategy": [{"stint_number": 1, "compound": "SOFT"}],
                "pace": {"laps_completed": 57},
                "sectors": {"laps_count": 57},
            },
        )

    def test_persistence_coverage_json_reports_db_first_flags(self):
        out = StringIO()
        call_command("persistence_coverage", "--year", "2024", "--json", stdout=out)
        payload = json.loads(out.getvalue())

        self.assertEqual(payload["race_count"], 1)
        item = payload["coverage"][0]
        self.assertEqual(item["round"], 1)
        self.assertTrue(item["db_first_flags"]["analysis_sector"])
        self.assertTrue(item["db_first_flags"]["all_db_first_ready"])

    def test_persistence_coverage_plain_text_does_not_raise(self):
        out = StringIO()
        call_command("persistence_coverage", "--year", "2024", "--round", "1", stdout=out)
        output = out.getvalue()

        self.assertIn("2024", output)
        self.assertIn("Bahrain", output)

    def test_command_outputs_empty_when_no_data(self):
        buf = io.StringIO()
        call_command("persistence_coverage", "--year", "2025", stdout=buf)
        output = buf.getvalue()

        self.assertIn("2025", output)
