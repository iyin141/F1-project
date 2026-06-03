"""
Integration tests for full worker flow: endpoint → worker enqueued → DB persistence → retrieval.
Tests representative flows from different endpoint categories.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.core.cache import cache

from api.models import WeatherData, RaceResultData


@pytest.mark.django_db
class TestDatabasePersistenceIntegration(TestCase):
    """Test that database persistence works correctly for key models."""
    
    def test_weather_data_persistence_flow(self):
        """Test weather data can be persisted and retrieved correctly."""
        payload = {
            'data': [
                {
                    'time': '2023-04-30T11:00:00Z',
                    'track_temp': 45.2,
                    'air_temp': 28.5,
                    'humidity': 65,
                    'wind_speed': 5.2,
                }
            ]
        }
        
        # Simulate worker creating record
        record = WeatherData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload=payload
        )
        
        # Verify record can be retrieved
        retrieved = WeatherData.objects.get(year=2023, round_number=4, session="R")
        assert retrieved.id == record.id
        assert retrieved.payload == payload
        
        # Verify data structure matches
        assert retrieved.payload['data'][0]['track_temp'] == 45.2
    
    def test_race_result_persistence_flow(self):
        """Test race result data can be persisted and retrieved correctly."""
        payload = {
            'data': [
                {
                    'position': 1,
                    'driver_number': 1,
                    'driver_name': 'Max Verstappen',
                    'team': 'Red Bull Racing',
                    'points': 25,
                    'status': 'Finished',
                }
            ]
        }
        
        # Simulate worker creating record
        record = RaceResultData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload=payload
        )
        
        # Verify record can be retrieved
        retrieved = RaceResultData.objects.get(year=2023, round_number=4, session="R")
        assert retrieved.id == record.id
        assert retrieved.payload == payload
        
        # Verify position data is accessible
        assert retrieved.payload['data'][0]['position'] == 1
        assert retrieved.payload['data'][0]['points'] == 25


@pytest.mark.django_db
class TestModelUpdatePatterns(TestCase):
    """Test update_or_create patterns used by workers."""
    
    def test_weather_data_update_or_create_pattern(self):
        """Test that update_or_create correctly handles weather data."""
        payload1 = {'data': [{'track_temp': 45.2}]}
        payload2 = {'data': [{'track_temp': 46.1}]}
        
        # Initial create
        record, created = WeatherData.objects.update_or_create(
            year=2023,
            round_number=4,
            session="R",
            defaults={'payload': payload1}
        )
        
        assert created is True
        assert record.payload == payload1
        
        # Update
        record, created = WeatherData.objects.update_or_create(
            year=2023,
            round_number=4,
            session="R",
            defaults={'payload': payload2}
        )
        
        assert created is False
        assert record.payload == payload2
        assert WeatherData.objects.filter(year=2023, round_number=4, session="R").count() == 1
    
    def test_race_result_update_or_create_pattern(self):
        """Test that update_or_create correctly handles race results."""
        payload1 = {'data': [{'position': 1}]}
        payload2 = {'data': [{'position': 2}, {'position': 1}]}
        
        # Initial create
        record, created = RaceResultData.objects.update_or_create(
            year=2023,
            round_number=4,
            session="R",
            defaults={'payload': payload1}
        )
        
        assert created is True
        
        # Update with new payload
        record, created = RaceResultData.objects.update_or_create(
            year=2023,
            round_number=4,
            session="R",
            defaults={'payload': payload2}
        )
        
        assert created is False
        assert len(record.payload['data']) == 2


@pytest.mark.django_db
class TestPayloadIntegrity(TestCase):
    """Test that complex payloads maintain integrity through persistence."""
    
    def test_complex_weather_payload_integrity(self):
        """Test complex nested weather payload is preserved exactly."""
        payload = {
            'data': [
                {
                    'time': '2023-04-30T11:00:00Z',
                    'track_temp': 45.2,
                    'air_temp': 28.5,
                    'humidity': 65.5,
                    'wind': {
                        'speed': 5.2,
                        'direction': 180,
                        'gust': 6.1
                    },
                    'conditions': ['clear', 'dry'],
                    'rainfall': False,
                    'pressure': None,
                },
                {
                    'time': '2023-04-30T11:05:00Z',
                    'track_temp': 46.1,
                    'wind': {'speed': 5.5}
                }
            ],
            'metadata': {
                'recorded_at': '2023-04-30T11:00:00Z',
                'source': 'FastF1',
                'version': 1
            }
        }
        
        record = WeatherData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload=payload
        )
        
        retrieved = WeatherData.objects.get(id=record.id)
        
        # Verify entire structure is preserved
        assert retrieved.payload == payload
        assert retrieved.payload['data'][0]['wind']['gust'] == 6.1
        assert retrieved.payload['metadata']['source'] == 'FastF1'
        assert retrieved.payload['data'][0]['conditions'] == ['clear', 'dry']
    
    def test_complex_race_result_payload_integrity(self):
        """Test complex nested race result payload is preserved exactly."""
        payload = {
            'data': [
                {
                    'position': 1,
                    'driver': {
                        'number': 1,
                        'name': 'Max Verstappen',
                        'team': 'Red Bull Racing',
                        'details': {
                            'nationality': 'Dutch',
                            'points_this_race': 25
                        }
                    },
                    'performance': {
                        'grid_position': 1,
                        'laps_completed': 57,
                        'status': 'Finished',
                        'gap_to_leader': None,
                        'fastest_lap': {
                            'lap_number': 43,
                            'time': '1:43.202',
                            'is_fastest': True
                        }
                    },
                    'pit_stops': [
                        {'lap': 15, 'duration': 2.3, 'tyre_compound': 'SOFT'},
                        {'lap': 35, 'duration': 2.1, 'tyre_compound': 'HARD'}
                    ]
                }
            ]
        }
        
        record = RaceResultData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload=payload
        )
        
        retrieved = RaceResultData.objects.get(id=record.id)
        
        # Verify structure
        assert retrieved.payload == payload
        assert retrieved.payload['data'][0]['driver']['details']['points_this_race'] == 25
        assert retrieved.payload['data'][0]['performance']['fastest_lap']['is_fastest'] is True
        assert len(retrieved.payload['data'][0]['pit_stops']) == 2
        assert retrieved.payload['data'][0]['pit_stops'][1]['tyre_compound'] == 'HARD'


@pytest.mark.django_db
class TestMultipleSessionsFlow(TestCase):
    """Test handling multiple sessions per round."""
    
    def test_multiple_practice_sessions_same_round(self):
        """Test that multiple practice sessions for same round are stored separately."""
        from api.models import PracticeResultData
        
        base_payload = {'data': [{'position': 1}]}
        
        fp1 = PracticeResultData.objects.create(
            year=2023,
            round_number=4,
            session="FP1",
            payload=base_payload
        )
        
        fp2 = PracticeResultData.objects.create(
            year=2023,
            round_number=4,
            session="FP2",
            payload=base_payload
        )
        
        fp3 = PracticeResultData.objects.create(
            year=2023,
            round_number=4,
            session="FP3",
            payload=base_payload
        )
        
        # Verify all are stored separately
        assert PracticeResultData.objects.filter(year=2023, round_number=4).count() == 3
        assert PracticeResultData.objects.get(year=2023, round_number=4, session="FP1").id == fp1.id
        assert PracticeResultData.objects.get(year=2023, round_number=4, session="FP2").id == fp2.id
        assert PracticeResultData.objects.get(year=2023, round_number=4, session="FP3").id == fp3.id
    
    def test_race_and_weather_same_round_different_keys(self):
        """Test that race and weather data for same round use different keys."""
        weather = WeatherData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload={'data': []}
        )
        
        race = RaceResultData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload={'data': []}
        )
        
        # Both should exist independently in their respective tables
        assert WeatherData.objects.filter(year=2023, round_number=4, session="R").exists()
        assert RaceResultData.objects.filter(year=2023, round_number=4, session="R").exists()
        
        # Verify they're in different tables
        assert isinstance(weather, WeatherData)
        assert isinstance(race, RaceResultData)
        
        # Verify they both persist correctly
        retrieved_weather = WeatherData.objects.get(year=2023, round_number=4, session="R")
        retrieved_race = RaceResultData.objects.get(year=2023, round_number=4, session="R")
        
        assert retrieved_weather.payload == weather.payload
        assert retrieved_race.payload == race.payload

