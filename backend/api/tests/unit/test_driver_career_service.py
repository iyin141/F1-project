"""Unit tests for driver career service fallback behavior and Jolpica parsing."""

from unittest.mock import Mock, patch

from django.test import TestCase

from api.services.driver_career_service import DriverCareerService


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class DriverCareerServiceTests(TestCase):
    def setUp(self):
        self.service = DriverCareerService()

    def test_parse_driver_standing_payload_handles_jolpica_shape(self):
        payload = {
            "MRData": {
                "StandingsTable": {
                    "StandingsLists": [
                        {
                            "season": "2007",
                            "DriverStandings": [
                                {
                                    "position": "2",
                                    "points": "109",
                                    "wins": "4",
                                    "Driver": {
                                        "code": "HAM",
                                        "givenName": "Lewis",
                                        "familyName": "Hamilton",
                                        "nationality": "British",
                                    },
                                    "Constructors": [{"name": "McLaren"}],
                                }
                            ],
                        }
                    ]
                }
            }
        }

        parsed = self.service._parse_driver_standing_payload(payload, "HAM")

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["year"], 2007)
        self.assertEqual(parsed[0]["driver_name"], "Lewis Hamilton")
        self.assertEqual(parsed[0]["constructor"], "McLaren")

    @patch("api.services.driver_career_service.requests.get")
    def test_get_schedule_from_jolpica_reads_race_name_field(self, mock_get):
        mock_get.return_value = _FakeResponse(
            {
                "MRData": {
                    "RaceTable": {
                        "Races": [
                            {
                                "round": "1",
                                "raceName": "Bahrain Grand Prix",
                                "Circuit": {"Location": {"locality": "Sakhir"}},
                                "date": "2023-03-05",
                            }
                        ]
                    }
                }
            }
        )

        races = self.service._get_schedule_from_jolpica(2023)

        self.assertEqual(len(races), 1)
        self.assertEqual(races[0]["race_name"], "Bahrain Grand Prix")

    @patch("api.services.driver_career_service.RaceResult")
    def test_get_round_result_uses_fallback_results_when_db_missing(self, mock_race_result):
        qs = Mock()
        mock_race_result.objects.filter.return_value.select_related.return_value = qs
        qs.first.return_value = None

        fallback = {
            1: {
                "grid_position": 4,
                "finish_position": 3,
                "points": 15.0,
                "status": "Finished",
                "fastest_lap": False,
                "laps_completed": 57,
                "driver_name": "Lewis Hamilton",
                "constructor": "McLaren",
                "qualifying_position": None,
                "qualifying_time": None,
            }
        }

        result = self.service._get_round_result("HAM", 2007, 1, fallback_results=fallback)

        self.assertIsNotNone(result)
        self.assertEqual(result["finish_position"], 3)
        self.assertEqual(result["driver_name"], "Lewis Hamilton")

    @patch("api.services.driver_career_service.datetime")
    @patch("api.services.driver_career_service.requests.get")
    @patch.object(DriverCareerService, "_resolve_driver_id")
    def test_get_career_from_jolpica_resolves_driver_id_and_parses(self, mock_resolve_driver_id, mock_get, mock_datetime):
        mock_resolve_driver_id.return_value = "hamilton"
        mock_datetime.now.return_value.year = 1951

        empty_year = _FakeResponse({"MRData": {"StandingsTable": {"StandingsLists": []}}})
        data_year = _FakeResponse(
            {
                "MRData": {
                    "StandingsTable": {
                        "StandingsLists": [
                            {
                                "season": "1951",
                                "DriverStandings": [
                                    {
                                        "position": "1",
                                        "points": "20",
                                        "wins": "2",
                                        "Driver": {
                                            "code": "HAM",
                                            "givenName": "Lewis",
                                            "familyName": "Hamilton",
                                            "nationality": "British",
                                        },
                                        "Constructors": [{"name": "Mercedes"}],
                                    }
                                ],
                            }
                        ]
                    }
                }
            }
        )
        mock_get.side_effect = [empty_year, data_year]

        seasons = self.service._get_career_from_jolpica("HAM")

        self.assertEqual(len(seasons), 1)
        self.assertEqual(seasons[0]["year"], 1951)
        self.assertEqual(seasons[0]["wins"], 2)
