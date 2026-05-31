from unittest.mock import MagicMock, patch

from django.test import TestCase
import requests

from api.services.constructors import get_constructor_standings
from api.services.drivers import get_driver_standings


class StandingsReadinessTests(TestCase):
    def setUp(self):
        # Ensure persisted/cached standings for the synthetic test year do
        # not leak from other tests. Use local imports to avoid early import
        # side-effects during test discovery.
        from api.models import DriverStandings, ConstructorStandings
        from api.services.cache import cache_clear_pattern

        year = 2099
        DriverStandings.objects.filter(year=year).delete()
        ConstructorStandings.objects.filter(year=year).delete()
        cache_clear_pattern(f"f1:{year}:")
    @patch("api.services.drivers.requests.get")
    def test_driver_standings_returns_non_blocking_readiness_when_api_unavailable(self, mock_get):
        mock_get.side_effect = requests.RequestException("network unavailable")

        year = 2099
        # Ensure no persisted/cached standings leak from other tests
        from api.models import DriverStandings
        from api.services.cache import cache_clear_pattern

        DriverStandings.objects.filter(year=year).delete()
        cache_clear_pattern(f"f1:{year}:")

        # Ensure persisted lookup doesn't interfere with simulated API failure
        from unittest.mock import patch as _patch
        with _patch("api.drivers.services.standings.get_persisted_driver_standings", return_value=None):
            payload = get_driver_standings(year)

        self.assertEqual(payload["meta"]["year"], year)
        self.assertEqual(payload["meta"]["row_count"], 0)
        self.assertFalse(payload["meta"]["readiness"]["can_proceed"])
        self.assertIn("driver_standings_api", payload["meta"]["readiness"]["unavailable_data"])
        self.assertEqual(payload["data"], [])

    @patch("api.services.drivers.requests.get")
    def test_driver_standings_returns_readiness_when_api_responds(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "MRData": {
                "StandingsTable": {
                    "StandingsLists": [
                        {
                            "DriverStandings": [
                                {
                                    "position": "1",
                                    "points": "250",
                                    "wins": "7",
                                    "Driver": {"givenName": "Max", "familyName": "Verstappen"},
                                    "Constructors": [{"name": "Red Bull"}],
                                }
                            ]
                        }
                    ]
                }
            }
        }
        mock_get.return_value = mock_response

        payload = get_driver_standings(2021)

        self.assertTrue(payload["meta"]["readiness"]["can_proceed"])
        self.assertEqual(payload["meta"]["row_count"], 1)
        self.assertEqual(payload["data"][0]["driver_name"], "Max Verstappen")

    @patch("api.services.drivers.requests.get")
    def test_driver_standings_returns_message_when_api_returns_no_rows(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "MRData": {
                "StandingsTable": {
                    "StandingsLists": [
                        {
                            "DriverStandings": [],
                        }
                    ]
                }
            }
        }
        mock_get.return_value = mock_response

        payload = get_driver_standings(2021)

        self.assertFalse(payload["meta"]["readiness"]["can_proceed"])
        self.assertEqual(payload["data"], [])
        self.assertTrue(payload["meta"]["readiness"]["message"])

    @patch("api.services.constructors.requests.get")
    def test_constructor_standings_returns_non_blocking_readiness_when_api_unavailable(self, mock_get):
        mock_get.side_effect = requests.RequestException("network unavailable")

        year = 2099
        payload = get_constructor_standings(year)

        self.assertEqual(payload["meta"]["year"], year)
        self.assertEqual(payload["meta"]["row_count"], 0)
        self.assertFalse(payload["meta"]["readiness"]["can_proceed"])
        self.assertIn("constructor_standings_api", payload["meta"]["readiness"]["unavailable_data"])
        self.assertEqual(payload["data"], [])

    @patch("api.services.constructors.requests.get")
    def test_constructor_standings_returns_readiness_when_api_responds(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "MRData": {
                "StandingsTable": {
                    "StandingsLists": [
                        {
                            "ConstructorStandings": [
                                {
                                    "position": "1",
                                    "points": "350",
                                    "wins": "9",
                                    "Constructor": {"name": "Mercedes"},
                                }
                            ]
                        }
                    ]
                }
            }
        }
        mock_get.return_value = mock_response

        payload = get_constructor_standings(2021)

        self.assertTrue(payload["meta"]["readiness"]["can_proceed"])
        self.assertEqual(payload["meta"]["row_count"], 1)
        self.assertEqual(payload["data"][0]["constructor_name"], "Mercedes")

    @patch("api.services.constructors.requests.get")
    def test_constructor_standings_returns_message_when_api_returns_no_rows(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "MRData": {
                "StandingsTable": {
                    "StandingsLists": [
                        {
                            "ConstructorStandings": [],
                        }
                    ]
                }
            }
        }
        mock_get.return_value = mock_response

        payload = get_constructor_standings(2021)

        self.assertFalse(payload["meta"]["readiness"]["can_proceed"])
        self.assertEqual(payload["data"], [])
        self.assertTrue(payload["meta"]["readiness"]["message"])
