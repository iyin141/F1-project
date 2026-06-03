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
                    'time': '2023-04-30T11:00:00Z',
                    'track_temp': 45.2,
                    'air_temp': 28.5,
                    'humidity': 65,
                    'wind_speed': 5.2,
                    'wind_direction': 180,
                    'rainfall': False,
                },
                {
                    'time': '2023-04-30T11:05:00Z',
                    'track_temp': 46.1,
                    'air_temp': 29.2,
                    'humidity': 62,
                    'wind_speed': 5.5,
                    'wind_direction': 185,
                    'rainfall': False,
                }
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        result = populate_weather(year=2023, round_number=4, session_type="R")
        
        assert result is not None
        assert 'data' in result
        assert len(result['data']) == 2
        assert all('track_temp' in row for row in result['data'])
        assert all('air_temp' in row for row in result['data'])
    
    @patch('api.workers.tier2_fast.populate_weather.SessionManager.get_session')
    @patch('api.workers.tier2_fast.populate_weather.WeatherExtractor')
    def test_populate_weather_persists_to_database(self, mock_extractor_class, mock_get_session):
        """Verify populate_weather creates WeatherData record with correct payload."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.return_value = {
            'data': [
                {'time': '2023-04-30T11:00:00Z', 'track_temp': 45.2, 'air_temp': 28.5}
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        populate_weather(year=2023, round_number=4, session_type="R")
        
        record = WeatherData.objects.get(year=2023, round_number=4, session="R")
        assert record.payload == {'data': [{'time': '2023-04-30T11:00:00Z', 'track_temp': 45.2, 'air_temp': 28.5}]}
        assert record.created_at is not None


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
                    'lap': 15,
                    'duration_seconds': 2.3,
                },
                {
                    'driver_number': 77,
                    'driver_code': 'BOT',
                    'stop_number': 1,
                    'lap': 16,
                    'duration_seconds': 2.1,
                }
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        result = populate_pit_stops(year=2023, round_number=4, session_type="R")
        
        assert result is not None
        assert 'data' in result
        assert len(result['data']) == 2
        assert all('driver_number' in row for row in result['data'])
        assert all('duration_seconds' in row for row in result['data'])
    
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
        
        populate_pit_stops(year=2023, round_number=4, session_type="R")
        
        record = PitStopData.objects.get(year=2023, round_number=4, session="R")
        assert record.payload == {'data': [{'driver_number': 44, 'driver_code': 'HAM', 'stop_number': 1}]}
        assert record.created_at is not None


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
                    'lap': 1,
                    'time': '2023-04-30T11:05:00Z',
                    'driver_number': 1,
                    'driver_code': 'VER',
                    'incident_type': 'PUNCTURE',
                    'message': 'Puncture in Turn 1',
                },
                {
                    'lap': 5,
                    'time': '2023-04-30T11:20:00Z',
                    'driver_number': 44,
                    'driver_code': 'HAM',
                    'incident_type': 'COLLISION',
                    'message': 'Contact with opponent',
                }
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        result = populate_incidents(year=2023, round_number=4, session_type="R")
        
        assert result is not None
        assert 'data' in result
        assert len(result['data']) == 2
        assert all('driver_code' in row for row in result['data'])
        assert all('incident_type' in row for row in result['data'])
    
    @patch('api.workers.tier2_fast.populate_incidents.SessionManager.get_session')
    @patch('api.workers.tier2_fast.populate_incidents.IncidentExtractor')
    def test_populate_incidents_persists_to_database(self, mock_extractor_class, mock_get_session):
        """Verify populate_incidents creates IncidentData record with correct payload."""
        mock_session = Mock()
        mock_get_session.return_value = mock_session
        
        mock_extractor = Mock()
        mock_extractor.extract.return_value = {
            'data': [
                {'lap': 1, 'driver_code': 'VER', 'incident_type': 'PUNCTURE'}
            ]
        }
        mock_extractor_class.return_value = mock_extractor
        
        populate_incidents(year=2023, round_number=4, session_type="R")
        
        record = IncidentData.objects.get(year=2023, round_number=4, session="R")
        assert record.payload == {'data': [{'lap': 1, 'driver_code': 'VER', 'incident_type': 'PUNCTURE'}]}
        assert record.created_at is not None


@pytest.mark.django_db
class TestPopulateRaceResultsWorker(TestCase):
    """Test race results extraction and persistence."""
    
    @patch('api.workers.tier2_fast.populate_race_results.run')
    def test_populate_race_results_calls_run_command(self, mock_run):
        """Verify populate_race_results calls run() with correct parameters."""
        mock_run.return_value = None
        
        populate_race_results(year=2023, round_number=4, session_type="R")
        
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs['year'] == 2023
        assert call_kwargs['round_number'] == 4
        assert call_kwargs['session_type'] == "R"
    
    @patch('api.management.commands.populate_race.fastf1.get_session')
    @patch('api.management.commands.populate_race.get_race_by_round')
    @patch('api.management.commands.populate_race.get_race_session_results')
    def test_populate_race_results_persists_to_database(self, mock_get_results, mock_get_race, mock_get_session):
        """Verify populate_race_results creates RaceResultData record."""
        mock_session = Mock()
        mock_session.load = Mock()
        mock_get_session.return_value = mock_session
        
        mock_get_race.return_value = {
            'name': 'Azerbaijan Grand Prix',
            'date': None,
            'location': 'Baku',
            'country': 'Azerbaijan',
            'event_format': 'sprint_shootout',
            'session1': 'Practice 1',
            'session1_date_utc': None,
            'session2': 'Qualifying',
            'session2_date_utc': None,
            'session3': 'Sprint Shootout',
            'session3_date_utc': None,
            'session4': 'Sprint',
            'session4_date_utc': None,
            'session5': 'Race',
            'session5_date_utc': None,
        }
        
        mock_get_results.return_value = [
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
        
        populate_race_results(year=2023, round_number=4, session_type="R")
        
        record = RaceResultData.objects.get(year=2023, round_number=4, session="R")
        assert record.payload is not None
        assert 'data' in record.payload
        assert len(record.payload['data']) > 0
