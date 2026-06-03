"""
Unit tests for database persistence of race result models.
Verifies RaceResultData, QualifyingResultData, PracticeResultData persistence and payload structure.
"""
import pytest
from django.test import TestCase
from django.db import IntegrityError

from api.models import RaceResultData, QualifyingResultData, PracticeResultData


@pytest.mark.django_db
class TestRaceResultDataPersistence(TestCase):
    """Test RaceResultData model persistence and constraints."""
    
    def test_race_result_data_creates_record_with_payload(self):
        """Verify RaceResultData record is created with correct payload structure."""
        payload = {
            'data': [
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
                },
                {
                    'position': 2,
                    'driver_number': 44,
                    'driver_name': 'Lewis Hamilton',
                    'team': 'Mercedes',
                    'points': 18,
                    'status': 'Finished',
                    'grid_position': 2,
                    'laps': 57,
                    'gap': '+1.234',
                    'fastest_lap': None,
                }
            ]
        }
        
        record = RaceResultData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload=payload
        )
        
        assert record.id is not None
        assert record.payload == payload
        assert len(record.payload['data']) == 2
        assert record.payload['data'][0]['position'] == 1
        assert record.payload['data'][0]['points'] == 25
    
    def test_race_result_data_unique_constraint_enforced(self):
        """Verify unique constraint on year/round/session prevents duplicates."""
        RaceResultData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload={'data': []}
        )
        
        with pytest.raises(IntegrityError):
            RaceResultData.objects.create(
                year=2023,
                round_number=4,
                session="R",
                payload={'data': []}
            )
    
    def test_race_result_data_required_fields_present(self):
        """Verify race result records contain all required fields."""
        payload = {
            'data': [
                {
                    'position': 1,
                    'driver_number': 1,
                    'driver_name': 'Max Verstappen',
                    'team': 'Red Bull Racing',
                    'points': 25,
                    'status': 'Finished',
                    'grid_position': 1,
                    'laps': 57,
                }
            ]
        }
        
        record = RaceResultData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload=payload
        )
        
        result_row = record.payload['data'][0]
        required_fields = ['position', 'driver_number', 'driver_name', 'team', 'points', 'status']
        assert all(field in result_row for field in required_fields)


@pytest.mark.django_db
class TestQualifyingResultDataPersistence(TestCase):
    """Test QualifyingResultData model persistence and constraints."""
    
    def test_qualifying_result_data_creates_record_with_payload(self):
        """Verify QualifyingResultData record is created with correct payload structure."""
        payload = {
            'data': [
                {
                    'grid_position': 1,
                    'driver_number': 1,
                    'driver_name': 'Max Verstappen',
                    'team': 'Red Bull Racing',
                    'q1_time': '1:26.123',
                    'q2_time': '1:25.456',
                    'q3_time': '1:24.789',
                    'status': 'Finished',
                },
                {
                    'grid_position': 2,
                    'driver_number': 44,
                    'driver_name': 'Lewis Hamilton',
                    'team': 'Mercedes',
                    'q1_time': '1:26.234',
                    'q2_time': '1:25.567',
                    'q3_time': '1:24.890',
                    'status': 'Finished',
                }
            ]
        }
        
        record = QualifyingResultData.objects.create(
            year=2023,
            round_number=4,
            payload=payload
        )
        
        assert record.payload == payload
        assert len(record.payload['data']) == 2
        assert record.payload['data'][0]['grid_position'] == 1
        assert record.payload['data'][0]['q3_time'] == '1:24.789'
    
    def test_qualifying_result_data_unique_constraint_enforced(self):
        """Verify unique constraint prevents duplicates."""
        QualifyingResultData.objects.create(
            year=2023,
            round_number=4,
            payload={'data': []}
        )
        
        with pytest.raises(IntegrityError):
            QualifyingResultData.objects.create(
                year=2023,
                round_number=4,
                payload={'data': []}
            )
    
    def test_qualifying_result_data_no_session_field(self):
        """Verify qualifying results don't have a session field (only year/round)."""
        record = QualifyingResultData.objects.create(
            year=2023,
            round_number=4,
            payload={'data': []}
        )
        
        assert record.year == 2023
        assert record.round_number == 4
        assert not hasattr(record, 'session') or record.session is None


@pytest.mark.django_db
class TestPracticeResultDataPersistence(TestCase):
    """Test PracticeResultData model persistence and constraints."""
    
    def test_practice_result_data_creates_record_with_payload(self):
        """Verify PracticeResultData record is created with correct payload structure."""
        payload = {
            'data': [
                {
                    'position': 1,
                    'driver_number': 1,
                    'driver_name': 'Max Verstappen',
                    'team': 'Red Bull Racing',
                    'laps': 45,
                    'best_lap_time': '1:25.123',
                    'gap_to_leader': None,
                },
                {
                    'position': 2,
                    'driver_number': 44,
                    'driver_name': 'Lewis Hamilton',
                    'team': 'Mercedes',
                    'laps': 42,
                    'best_lap_time': '1:25.456',
                    'gap_to_leader': 0.333,
                }
            ]
        }
        
        record = PracticeResultData.objects.create(
            year=2023,
            round_number=4,
            session="FP1",
            payload=payload
        )
        
        assert record.payload == payload
        assert len(record.payload['data']) == 2
        assert record.payload['data'][0]['best_lap_time'] == '1:25.123'
    
    def test_practice_result_data_supports_all_session_types(self):
        """Verify practice results can be stored for FP1, FP2, FP3."""
        base_payload = {'data': []}
        
        for session_type in ['FP1', 'FP2', 'FP3']:
            record = PracticeResultData.objects.create(
                year=2023,
                round_number=4,
                session=session_type,
                payload=base_payload
            )
            assert record.session == session_type
    
    def test_practice_result_data_unique_constraint_enforced(self):
        """Verify unique constraint prevents duplicates for same session."""
        PracticeResultData.objects.create(
            year=2023,
            round_number=4,
            session="FP1",
            payload={'data': []}
        )
        
        with pytest.raises(IntegrityError):
            PracticeResultData.objects.create(
                year=2023,
                round_number=4,
                session="FP1",
                payload={'data': []}
            )
    
    def test_practice_result_data_different_sessions_allowed(self):
        """Verify different practice sessions can be stored for same round."""
        for session_type in ['FP1', 'FP2', 'FP3']:
            PracticeResultData.objects.create(
                year=2023,
                round_number=4,
                session=session_type,
                payload={'data': []}
            )
        
        assert PracticeResultData.objects.filter(year=2023, round_number=4).count() == 3


@pytest.mark.django_db
class TestRaceModelsPersistenceShared(TestCase):
    """Test shared persistence patterns across all race models."""
    
    def test_all_race_models_have_year_round_keys(self):
        """Verify all race models store year and round_number."""
        # RaceResultData with session
        record1 = RaceResultData.objects.create(
            year=2024,
            round_number=1,
            session="R",
            payload={'data': []}
        )
        assert record1.year == 2024
        assert record1.round_number == 1
        
        # QualifyingResultData without session
        record2 = QualifyingResultData.objects.create(
            year=2024,
            round_number=1,
            payload={'data': []}
        )
        assert record2.year == 2024
        assert record2.round_number == 1
        
        # PracticeResultData with session
        record3 = PracticeResultData.objects.create(
            year=2024,
            round_number=1,
            session="FP1",
            payload={'data': []}
        )
        assert record3.year == 2024
        assert record3.round_number == 1
    
    def test_all_race_models_accept_complex_payloads(self):
        """Verify all race models can store complex nested JSONB structures."""
        complex_payload = {
            'data': [
                {
                    'position': 1,
                    'driver_info': {
                        'name': 'Test Driver',
                        'number': 1,
                        'team': 'Test Team'
                    },
                    'lap_times': [90.1, 90.2, 90.15],
                    'pit_stops': [
                        {'lap': 15, 'duration': 2.3},
                        {'lap': 35, 'duration': 2.1}
                    ],
                    'penalties': None,
                }
            ]
        }
        
        # RaceResultData
        record1 = RaceResultData.objects.create(
            year=2024,
            round_number=1,
            session="R",
            payload=complex_payload
        )
        assert record1.payload == complex_payload
        assert record1.payload['data'][0]['driver_info']['name'] == 'Test Driver'
        
        # QualifyingResultData
        record2 = QualifyingResultData.objects.create(
            year=2024,
            round_number=1,
            payload=complex_payload
        )
        assert record2.payload == complex_payload
        assert record2.payload['data'][0]['pit_stops'][0]['duration'] == 2.3
        
        # PracticeResultData
        record3 = PracticeResultData.objects.create(
            year=2024,
            round_number=1,
            session="FP1",
            payload=complex_payload
        )
        assert record3.payload == complex_payload
        assert len(record3.payload['data'][0]['pit_stops']) == 2


@pytest.mark.django_db
class TestRaceResultsPayloadValidation(TestCase):
    """Test payload structure validation for race results."""
    
    def test_race_result_payload_contains_position_and_driver_info(self):
        """Verify each race result includes position and driver information."""
        payload = {
            'data': [
                {
                    'position': 1,
                    'driver_number': 1,
                    'driver_name': 'Test Driver',
                    'team': 'Test Team',
                    'points': 25,
                }
            ]
        }
        
        record = RaceResultData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload=payload
        )
        
        result = record.payload['data'][0]
        assert 'position' in result
        assert 'driver_number' in result
        assert 'driver_name' in result
        assert 'team' in result
        assert 'points' in result
    
    def test_practice_result_payload_contains_lap_times(self):
        """Verify practice results include lap time information."""
        payload = {
            'data': [
                {
                    'position': 1,
                    'driver_name': 'Test Driver',
                    'laps': 45,
                    'best_lap_time': '1:25.123',
                }
            ]
        }
        
        record = PracticeResultData.objects.create(
            year=2023,
            round_number=4,
            session="FP1",
            payload=payload
        )
        
        result = record.payload['data'][0]
        assert 'best_lap_time' in result
        assert 'laps' in result
