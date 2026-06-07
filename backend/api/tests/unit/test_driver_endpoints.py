"""
Comprehensive unit tests for driver career and season endpoints.
Tests cover error handling, readiness patterns, and edge cases.
"""
from unittest.mock import Mock, patch
from django.test import TestCase
from rest_framework.test import APIRequestFactory
from api.drivers.views import DriverCareerAPIView, DriverSeasonAPIView
import json

def _parse_stream(response):
    if hasattr(response, 'streaming_content'):
        content = b"".join(response.streaming_content).decode("utf-8")
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return json.loads(content.split("\n\n")[0].replace("data: ", ""))
    return response.data


class DriverCareerAPIViewTests(TestCase):
    """Tests for /api/drivers/{driver_code}/career/ endpoint."""

    def setUp(self):
        self.factory = APIRequestFactory()
        # Ensure factory-created requests include the INTERNAL_API_KEY
        try:
            import os

            internal_key = os.environ.get("INTERNAL_API_KEY")

            if internal_key:
                _orig_get = self.factory.get

                def _get_with_key(path, data=None, **extra):
                    extra.setdefault("HTTP_X_API_KEY", str(internal_key))
                    return _orig_get(path, data=data, **extra)

                self.factory.get = _get_with_key
        except Exception:
            # Best-effort only for test migration; don't raise here.
            pass
        self.view = DriverCareerAPIView.as_view()

    @patch('api.drivers.views.get_persisted_driver_career')
    def test_career_valid_known_driver(self, mock_get_persisted):
        """Test retrieving career for valid known driver (VER)."""
        mock_get_persisted.return_value = {
            "driver_code": "VER",
            "driver_name": "Max Verstappen",
            "nationality": "Dutch",
            "career": [{"year": 2022, "constructor": "RB", "position": 1, "points": 454, "wins": 15, "podiums": 19, "poles": 7, "fastest_laps": 5, "races_entered": 22, "dnfs": 0}],
            "career_totals": {"championships": 3, "wins": 80, "podiums": 120, "poles": 25, "fastest_laps": 30, "races_entered": 210, "dnfs": 15, "total_points": 2000},
        }
        
        request = self.factory.get("/api/drivers/VER/career/")
        response = self.view(request, driver_code="VER")
        
        data = _parse_stream(response)
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["readiness"]["can_proceed"])
        self.assertEqual(len(data["career"]), 1)

    @patch('api.drivers.views.get_persisted_driver_career')
    def test_career_valid_unknown_driver(self, mock_get_persisted):
        """Test retrieving career for unknown driver returns can_proceed=false."""
        mock_get_persisted.return_value = {"driver_code": "ZZZ", "driver_name": None, "nationality": None, "career": [], "career_totals": {"championships": 0, "wins": 0, "podiums": 0, "poles": 0, "fastest_laps": 0, "races_entered": 0, "dnfs": 0, "total_points": 0}}
        
        request = self.factory.get("/api/drivers/ZZZ/career/")
        response = self.view(request, driver_code="ZZZ")
        
        data = _parse_stream(response)
        
        self.assertEqual(response.status_code, 200)
        self.assertFalse(data["readiness"]["can_proceed"])
        self.assertEqual(len(data["career"]), 0)

    def test_career_invalid_code_too_short(self):
        """Test rejecting driver code that is too short."""
        request = self.factory.get("/api/drivers/VE/career/")
        response = self.view(request, driver_code="VE")
        
        data = _parse_stream(response)
        
        self.assertEqual(response.status_code, 200)
        self.assertFalse(data["readiness"]["can_proceed"])
        data = _parse_stream(response)
        self.assertIn("Invalid driver code", data["readiness"]["message"])

    def test_career_invalid_code_too_long(self):
        """Test rejecting driver code that is too long."""
        request = self.factory.get("/api/drivers/VERS/career/")
        response = self.view(request, driver_code="VERS")
        
        data = _parse_stream(response)
        
        self.assertEqual(response.status_code, 200)
        self.assertFalse(data["readiness"]["can_proceed"])
        data = _parse_stream(response)
        self.assertIn("Invalid driver code", data["readiness"]["message"])

    @patch('api.drivers.views.get_persisted_driver_career')
    def test_career_case_insensitive_driver_code(self, mock_get_persisted):
        """Test that driver code is converted to uppercase."""
        mock_get_persisted.return_value = {"driver_code": "HAM", "driver_name": "Lewis Hamilton", "nationality": "British", "career": [{"year": 2023, "constructor": "MER", "position": 2, "points": 470, "wins": 5, "podiums": 14, "poles": 4, "fastest_laps": 3, "races_entered": 22, "dnfs": 0}], "career_totals": {"championships": 7, "wins": 103, "podiums": 190, "poles": 88, "fastest_laps": 60, "races_entered": 320, "dnfs": 20, "total_points": 4500}}
        
        request = self.factory.get("/api/drivers/ham/career/")
        response = self.view(request, driver_code="ham")
        
        self.assertEqual(response.status_code, 200)
        mock_get_persisted.assert_called_once_with("HAM")

    @patch('api.drivers.views.get_persisted_driver_career')
    def test_career_service_exception_returns_500(self, mock_get_persisted):
        """Test that unexpected service exception returns 500."""
        mock_get_persisted.side_effect = RuntimeError("Unexpected database error")
        
        request = self.factory.get("/api/drivers/VER/career/")
        response = self.view(request, driver_code="VER")
        
        data = _parse_stream(response)
        
        self.assertEqual(response.status_code, 500)
        self.assertFalse(data["readiness"]["can_proceed"])

    @patch('api.drivers.views.get_persisted_driver_career')
    def test_career_multiple_seasons(self, mock_get_persisted):
        """Test career data with multiple seasons."""
        mock_get_persisted.return_value = {
            "driver_code": "SEN",
            "driver_name": "Ayrton Senna",
            "nationality": "Brazilian",
            "career": [
                {"year": 1984, "constructor": "TOL", "position": 3, "points": 95, "wins": 7, "podiums": 16, "poles": 8, "fastest_laps": 5, "races_entered": 16, "dnfs": 2},
                {"year": 1985, "constructor": "LOT", "position": 2, "points": 90, "wins": 8, "podiums": 14, "poles": 7, "fastest_laps": 4, "races_entered": 16, "dnfs": 1},
            ],
            "career_totals": {"championships": 3, "wins": 41, "podiums": 64, "poles": 65, "fastest_laps": 19, "races_entered": 161, "dnfs": 25, "total_points": 610}
        }
        
        request = self.factory.get("/api/drivers/SEN/career/")
        response = self.view(request, driver_code="SEN")
        
        data = _parse_stream(response)
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["readiness"]["can_proceed"])
        self.assertEqual(len(data["career"]), 2)

    @patch('api.drivers.views.get_persisted_driver_career')
    def test_career_null_fields_handled(self, mock_get_persisted):
        """Test that null fields are handled gracefully."""
        mock_get_persisted.return_value = {"driver_code": "RAI", "driver_name": None, "nationality": None, "career": [], "career_totals": {"championships": 0, "wins": 0, "podiums": 0, "poles": 0, "fastest_laps": 0, "races_entered": 0, "dnfs": 0, "total_points": 0}}
        
        request = self.factory.get("/api/drivers/RAI/career/")
        response = self.view(request, driver_code="RAI")
        
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(data["driver_name"])
        self.assertIsNone(data["nationality"])


class DriverSeasonAPIViewTests(TestCase):
    """Tests for /api/drivers/{driver_code}/{year}/ endpoint."""

    def setUp(self):
        self.factory = APIRequestFactory()
        # Ensure factory-created requests include the INTERNAL_API_KEY
        try:
            import os

            internal_key = os.environ.get("INTERNAL_API_KEY")

            if internal_key:
                _orig_get = self.factory.get

                def _get_with_key(path, data=None, **extra):
                    extra.setdefault("HTTP_X_API_KEY", str(internal_key))
                    return _orig_get(path, data=data, **extra)

                self.factory.get = _get_with_key
        except Exception:
            pass
        self.view = DriverSeasonAPIView.as_view()

    @patch('api.drivers.views.get_persisted_driver_season_breakdown')
    def test_season_valid_with_races(self, mock_get_persisted):
        """Test retrieving valid season with race data."""
        mock_get_persisted.return_value = {
            "driver_code": "VER",
            "driver_name": "Max Verstappen",
            "year": 2023,
            "constructor": "Red Bull Racing",
            "final_position": 1,
            "final_points": 575,
            "races": [{"year": 2023, "round": 1, "race_name": "Bahrain", "location": "Sakhir", "race_date": "2023-03-05", "grid_position": 1, "finish_position": 1, "points": 25, "status": "Finished", "fastest_lap": True, "laps_completed": 57, "qualifying_position": 1, "qualifying_time": "1:32.031"}],
        }
        
        request = self.factory.get("/api/drivers/VER/2023/")
        response = self.view(request, driver_code="VER", year=2023)
        
        data = _parse_stream(response)
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["readiness"]["can_proceed"])
        self.assertEqual(len(data["races"]), 1)

    @patch('api.drivers.views.get_persisted_driver_season_breakdown')
    def test_season_valid_driver_no_data(self, mock_get_persisted):
        """Test retrieving season with no race data."""
        mock_get_persisted.return_value = {"driver_code": "VER", "driver_name": None, "year": 1950, "constructor": None, "final_position": None, "final_points": None, "races": []}
        
        request = self.factory.get("/api/drivers/VER/1950/")
        response = self.view(request, driver_code="VER", year=1950)
        
        data = _parse_stream(response)
        
        self.assertEqual(response.status_code, 200)
        self.assertFalse(data["readiness"]["can_proceed"])
        self.assertEqual(len(data["races"]), 0)

    def test_season_invalid_driver_code(self):
        """Test rejecting invalid driver code format."""
        request = self.factory.get("/api/drivers/VE/2023/")
        response = self.view(request, driver_code="VE", year=2023)
        
        data = _parse_stream(response)
        
        self.assertEqual(response.status_code, 200)
        self.assertFalse(data["readiness"]["can_proceed"])
        data = _parse_stream(response)
        self.assertIn("Invalid driver code", data["readiness"]["message"])

    def test_season_invalid_year_too_low(self):
        """Test rejecting year before 1950."""
        request = self.factory.get("/api/drivers/VER/1949/")
        response = self.view(request, driver_code="VER", year=1949)
        
        data = _parse_stream(response)
        
        self.assertEqual(response.status_code, 200)
        self.assertFalse(data["readiness"]["can_proceed"])
        data = _parse_stream(response)
        self.assertIn("Invalid year", data["readiness"]["message"])

    def test_season_invalid_year_too_high(self):
        """Test rejecting year after 2100."""
        request = self.factory.get("/api/drivers/VER/2101/")
        response = self.view(request, driver_code="VER", year=2101)
        
        data = _parse_stream(response)
        
        self.assertEqual(response.status_code, 200)
        self.assertFalse(data["readiness"]["can_proceed"])
        data = _parse_stream(response)
        self.assertIn("Invalid year", data["readiness"]["message"])

    @patch('api.drivers.views.get_persisted_driver_season_breakdown')
    def test_season_year_boundary_1950(self, mock_get_persisted):
        """Test that year=1950 is valid (boundary condition)."""
        mock_get_persisted.return_value = {"driver_code": "ASM", "driver_name": "Giuseppe Farina", "year": 1950, "constructor": "Alfa Romeo", "final_position": 2, "final_points": 30, "races": []}
        
        request = self.factory.get("/api/drivers/ASM/1950/")
        response = self.view(request, driver_code="ASM", year=1950)
        
        self.assertEqual(response.status_code, 200)

    @patch('api.drivers.views.get_persisted_driver_season_breakdown')
    def test_season_case_insensitive_driver_code(self, mock_get_persisted):
        """Test that driver code is uppercase in season endpoint."""
        mock_get_persisted.return_value = {"driver_code": "HAM", "driver_name": "Lewis Hamilton", "year": 2023, "constructor": "Mercedes", "final_position": 2, "final_points": 470, "races": [{"year": 2023, "round": 1, "race_name": "Bahrain", "location": "Sakhir", "race_date": "2023-03-05", "grid_position": 1, "finish_position": 2, "points": 18, "status": "Finished", "fastest_lap": False, "laps_completed": 57, "qualifying_position": None, "qualifying_time": None}]}
        
        request = self.factory.get("/api/drivers/ham/2023/")
        response = self.view(request, driver_code="ham", year=2023)
        
        self.assertEqual(response.status_code, 200)
        mock_get_persisted.assert_called_once_with("HAM", 2023)

    @patch('api.drivers.views.get_persisted_driver_season_breakdown')
    def test_season_service_exception_returns_500(self, mock_get_persisted):
        """Test that unexpected service exception returns 500."""
        mock_get_persisted.side_effect = RuntimeError("Database connection error")
        
        request = self.factory.get("/api/drivers/VER/2023/")
        response = self.view(request, driver_code="VER", year=2023)
        
        data = _parse_stream(response)
        
        self.assertEqual(response.status_code, 500)
        self.assertFalse(data["readiness"]["can_proceed"])

    @patch('api.drivers.views.get_persisted_driver_season_breakdown')
    def test_season_multiple_races(self, mock_get_persisted):
        """Test season with multiple races."""
        races = []
        for round_num in range(1, 6):
            races.append({"year": 2023, "round": round_num, "race_name": f"Race {round_num}", "location": f"Location {round_num}", "race_date": "2023-05-01", "grid_position": round_num, "finish_position": round_num, "points": 25 - round_num, "status": "Finished", "fastest_lap": False, "laps_completed": 57, "qualifying_position": round_num, "qualifying_time": "1:30.000"})
        
        mock_get_persisted.return_value = {"driver_code": "VER", "driver_name": "Max Verstappen", "year": 2023, "constructor": "Red Bull Racing", "final_position": 1, "final_points": 575, "races": races}
        
        request = self.factory.get("/api/drivers/VER/2023/")
        response = self.view(request, driver_code="VER", year=2023)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data["races"]), 5)
        self.assertTrue(response.data["readiness"]["can_proceed"])

    @patch('api.drivers.views.get_persisted_driver_season_breakdown')
    def test_season_null_fields_handled(self, mock_get_persisted):
        """Test that null fields in season response are handled."""
        mock_get_persisted.return_value = {"driver_code": "TST", "driver_name": None, "year": 2023, "constructor": None, "final_position": None, "final_points": None, "races": []}
        
        request = self.factory.get("/api/drivers/TST/2023/")
        response = self.view(request, driver_code="TST", year=2023)
        
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(data["driver_name"])
        self.assertIsNone(data["constructor"])


class DriverEndpointReadinessTests(TestCase):
    """Tests focusing on readiness object structure and behavior."""

    def setUp(self):
        self.factory = APIRequestFactory()
        # Ensure factory-created requests include the INTERNAL_API_KEY
        try:
            import os

            internal_key = os.environ.get("INTERNAL_API_KEY")

            if internal_key:
                _orig_get = self.factory.get

                def _get_with_key(path, data=None, **extra):
                    extra.setdefault("HTTP_X_API_KEY", str(internal_key))
                    return _orig_get(path, data=data, **extra)

                self.factory.get = _get_with_key
        except Exception:
            pass
        self.career_view = DriverCareerAPIView.as_view()
        self.season_view = DriverSeasonAPIView.as_view()

    @patch('api.drivers.views.get_persisted_driver_career')
    def test_career_readiness_success_structure(self, mock_get_persisted):
        """Verify readiness object structure when career data succeeds."""
        mock_get_persisted.return_value = {"driver_code": "VER", "driver_name": "Max", "nationality": "Dutch", "career": [{"year": 2023, "constructor": "RB", "position": 1, "points": 575, "wins": 19, "podiums": 21, "poles": 7, "fastest_laps": 4, "races_entered": 22, "dnfs": 0}], "career_totals": {"championships": 1, "wins": 19, "podiums": 21, "poles": 7, "fastest_laps": 4, "races_entered": 22, "dnfs": 0, "total_points": 575}}
        
        request = self.factory.get("/api/drivers/VER/career/")
        response = self.career_view(request, driver_code="VER")
        
        data = _parse_stream(response)
        readiness = data["readiness"]
        self.assertTrue(readiness["can_proceed"])
        self.assertEqual(readiness["available_data"], ["career"])
        self.assertEqual(readiness["unavailable_data"], [])
        self.assertIsNone(readiness["message"])
        self.assertEqual(readiness["warnings"], [])

    def test_career_readiness_failure_structure(self):
        """Verify readiness object structure when career data is missing."""
        request = self.factory.get("/api/drivers/ZZZ/career/")
        response = self.career_view(request, driver_code="ZZZ")
        
        data = _parse_stream(response)
        readiness = data["readiness"]
        self.assertFalse(readiness["can_proceed"])
        self.assertEqual(readiness["available_data"], [])
        self.assertEqual(readiness["unavailable_data"], ["career"])
        self.assertIsNotNone(readiness["message"])

    @patch('api.drivers.views.get_persisted_driver_season_breakdown')
    def test_season_readiness_success_structure(self, mock_get_persisted):
        """Verify readiness object structure when season data succeeds."""
        mock_get_persisted.return_value = {"driver_code": "HAM", "driver_name": "Lewis", "year": 2023, "constructor": "Mercedes", "final_position": 2, "final_points": 470, "races": [{"year": 2023, "round": 1, "race_name": "Bahrain", "location": "Sakhir", "race_date": "2023-03-05", "grid_position": 1, "finish_position": 2, "points": 18, "status": "Finished", "fastest_lap": False, "laps_completed": 57, "qualifying_position": 1, "qualifying_time": "1:32.000"}]}
        
        request = self.factory.get("/api/drivers/HAM/2023/")
        response = self.season_view(request, driver_code="HAM", year=2023)
        
        data = _parse_stream(response)
        readiness = data["readiness"]
        self.assertTrue(readiness["can_proceed"])
        self.assertEqual(readiness["available_data"], ["season_breakdown"])
        self.assertEqual(readiness["unavailable_data"], [])

    def test_season_readiness_failure_structure(self):
        """Verify readiness object structure when season validation fails."""
        request = self.factory.get("/api/drivers/VE/2023/")
        response = self.season_view(request, driver_code="VE", year=2023)
        
        data = _parse_stream(response)
        readiness = data["readiness"]
        self.assertFalse(readiness["can_proceed"])
        self.assertEqual(readiness["unavailable_data"], ["season_breakdown"])
        self.assertIsNotNone(readiness["message"])
