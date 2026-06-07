"""
Unit tests for Tier 2 workers: weather, pit stops, incidents, race results.
Verifies worker output structure and database persistence.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase

from api.workers.tier2_fast.populate_weather import populate_weather
from api.workers.tier2_fast.populate_pit_stops import populate_pit_stops
from api.workers.tier2_fast.populate_incidents import populate_incidents
from api.workers.tier2_fast.populate_race_results import populate_race_results

from api.models import WeatherData, PitStopData, IncidentData, RaceResultData


@pytest.mark.django_db
class TestPopulateWeatherWorker(TestCase):
    """Test weather data extraction and persistence."""
    
    @patch('api.workers.tier2_fast.populate_weather.SessionManager.get_session')
    @patch('api.workers.tier2_fast.populate_weather.WeatherExtractor')
    def test_populate_weather_returns_correct_structure(self, mock_extractor_class, mock_get_session):
        """Verify populate_weather returns structured data with required fields."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.return_value = {
            'data': [
                {
                    'lap_number': 1,
                    'track_temp_c': 45.2,
                    'air_temp_c': 28.5,
                    'humidity_pct': 65.0,
                    'wind_speed_ms': 5.2,
                    'wind_direction_deg': 180.0,
                    'rainfall': False,
                },
                {
                    'lap_number': 5,
                    'track_temp_c': 46.1,
                    'air_temp_c': 29.2,
                    'humidity_pct': 62.0,
                    'wind_speed_ms': 5.5,
                    'wind_direction_deg': 185.0,
                    'rainfall': False,
                }
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        result = populate_weather(task_key="weather:2023:4:R", year=2023, round_number=4, session_type="R")
        
        assert result is None  # worker returns None
        
        record = WeatherData.objects.get(year=2023, round_number=4, session="R")
        assert len(record.payload['data']) == 2
        assert all('track_temp_c' in row for row in record.payload['data'])
        assert all('air_temp_c' in row for row in record.payload['data'])
    
    @patch('api.workers.tier2_fast.populate_weather.SessionManager.get_session')
    @patch('api.workers.tier2_fast.populate_weather.WeatherExtractor')
    def test_populate_weather_persists_to_database(self, mock_extractor_class, mock_get_session):
        """Verify populate_weather creates WeatherData record with correct payload."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.return_value = {
            'data': [
                {'lap_number': 1, 'track_temp_c': 45.2, 'air_temp_c': 28.5}
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        populate_weather(task_key="weather:2023:4:R", year=2023, round_number=4, session_type="R")
        
        record = WeatherData.objects.get(year=2023, round_number=4, session="R")
        assert record.payload['data'] == [{'lap_number': 1, 'track_temp_c': 45.2, 'air_temp_c': 28.5}]


@pytest.mark.django_db
class TestPopulatePitStopsWorker(TestCase):
    """Test pit stop data extraction and persistence."""
    
    @patch('api.workers.tier2_fast.populate_pit_stops.SessionManager.get_session')
    @patch('api.workers.tier2_fast.populate_pit_stops.PitStopExtractor')
    def test_populate_pit_stops_returns_correct_structure(self, mock_extractor_class, mock_get_session):
        """Verify populate_pit_stops returns structured data with required fields."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.return_value = {
            'data': [
                {
                    'driver_number': 44,
                    'driver_code': 'HAM',
                    'stop_number': 1,
                    'lap_in': 15,
                    'stop_duration_seconds': 2.3,
                },
                {
                    'driver_number': 77,
                    'driver_code': 'BOT',
                    'stop_number': 1,
                    'lap_in': 16,
                    'stop_duration_seconds': 2.1,
                }
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        populate_pit_stops(task_key="pit_stops:2023:4:R", year=2023, round_number=4, session_type="R")
        
        record = PitStopData.objects.get(year=2023, round_number=4, session="R")
        assert len(record.payload['data']) == 2
        assert all('driver_number' in row for row in record.payload['data'])
        assert all('stop_duration_seconds' in row for row in record.payload['data'])
    
    @patch('api.workers.tier2_fast.populate_pit_stops.SessionManager.get_session')
    @patch('api.workers.tier2_fast.populate_pit_stops.PitStopExtractor')
    def test_populate_pit_stops_persists_to_database(self, mock_extractor_class, mock_get_session):
        """Verify populate_pit_stops creates PitStopData record with correct payload."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.return_value = {
            'data': [
                {'driver_number': 44, 'driver_code': 'HAM', 'stop_number': 1}
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        populate_pit_stops(task_key="pit_stops:2023:4:R", year=2023, round_number=4, session_type="R")
        
        record = PitStopData.objects.get(year=2023, round_number=4, session="R")
        assert record.payload['data'] == [{'driver_number': 44, 'driver_code': 'HAM', 'stop_number': 1}]


@pytest.mark.django_db
class TestPopulateIncidentsWorker(TestCase):
    """Test incident data extraction and persistence."""
    
    @patch('api.workers.tier2_fast.populate_incidents.SessionManager.get_session')
    @patch('api.workers.tier2_fast.populate_incidents.IncidentExtractor')
    def test_populate_incidents_returns_correct_structure(self, mock_extractor_class, mock_get_session):
        """Verify populate_incidents returns structured data with required fields."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.return_value = {
            'data': [
                {
                    'lap_number': 1,
                    'drivers_involved': ['VER'],
                    'message_type': 'PUNCTURE',
                    'message_text': 'Puncture in Turn 1',
                },
                {
                    'lap_number': 5,
                    'drivers_involved': ['HAM'],
                    'message_type': 'COLLISION',
                    'message_text': 'Contact with opponent',
                }
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        populate_incidents(task_key="incidents:2023:4:R", year=2023, round_number=4, session_type="R")
        
        record = IncidentData.objects.get(year=2023, round_number=4, session="R")
        assert len(record.payload['data']) == 2
        assert all('drivers_involved' in row for row in record.payload['data'])
        assert all('message_type' in row for row in record.payload['data'])
    
    @patch('api.workers.tier2_fast.populate_incidents.SessionManager.get_session')
    @patch('api.workers.tier2_fast.populate_incidents.IncidentExtractor')
    def test_populate_incidents_persists_to_database(self, mock_extractor_class, mock_get_session):
        """Verify populate_incidents creates IncidentData record with correct payload."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.return_value = {
            'data': [
                {'lap_number': 1, 'drivers_involved': ['VER'], 'message_type': 'PUNCTURE'}
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        populate_incidents(task_key="incidents:2023:4:R", year=2023, round_number=4, session_type="R")
        
        record = IncidentData.objects.get(year=2023, round_number=4, session="R")
        assert record.payload['data'] == [{'lap_number': 1, 'drivers_involved': ['VER'], 'message_type': 'PUNCTURE'}]


@pytest.mark.django_db
class TestPopulateRaceResultsWorker(TestCase):
    """Test race results extraction and persistence."""
    
    @patch('api.results.parsing.parse_session_once')
    @patch('api.results.helpers._load_session_with_readiness')
    @patch('api.services.store.store_race_results')
    def test_populate_race_results_persists_to_database(self, mock_store, mock_load, mock_parse):
        """Verify populate_race_results extracts and delegates to store_race_results."""
        mock_session = Mock()
        mock_load.return_value = (mock_session, {"can_proceed": True})
        
        mock_parsed = Mock()
        mock_parsed.race_results = [
            {
                'position': 1,
                'driver_number': 1,
                'driver_name': 'Max Verstappen',
                'team': 'Red Bull Racing',
                'points': 25,
                'status': 'Finished',
                'grid_position': 1,
                'laps': 57,
                'gap': 'LEADER',
                'fastest_lap': '1:43.202',
                'fastest_lap_of_race': True,
            }
        ]
        mock_parse.return_value = mock_parsed
        
        populate_race_results(task_key="race_results:2023:4:R", year=2023, round_number=4, session_type="R")
        
        mock_store.assert_called_once()
        call_args = mock_store.call_args[0]
        assert call_args[0] == 2023
        assert call_args[1] == 4
        assert call_args[2] == "R"
        assert len(call_args[3]) > 0
        assert call_args[3][0]['driver_name'] == 'Max Verstappen'
