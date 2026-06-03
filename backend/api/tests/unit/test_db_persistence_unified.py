"""
Unit tests for database persistence of unified data models.
Verifies JSONB payload structure, uniqueness constraints, and data integrity.
"""
import pytest
from django.test import TestCase
from django.db import IntegrityError
from django.utils import timezone

from api.models import WeatherData, PitStopData, IncidentData, PositionData, DRSData, TrackStatusData


@pytest.mark.django_db
class TestWeatherDataPersistence(TestCase):
    """Test WeatherData model persistence and constraints."""
    
    def test_weather_data_creates_record_with_payload(self):
        """Verify WeatherData record is created with correct payload structure."""
        payload = {
            'data': [
                {'time': '2023-04-30T11:00:00Z', 'track_temp': 45.2, 'air_temp': 28.5},
                {'time': '2023-04-30T11:05:00Z', 'track_temp': 46.1, 'air_temp': 29.2},
            ]
        }
        
        record = WeatherData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload=payload
        )
        
        assert record.id is not None
        assert record.payload == payload
        assert record.payload['data'][0]['track_temp'] == 45.2
        assert record.created_at is not None
    
    def test_weather_data_unique_constraint_enforced(self):
        """Verify unique constraint on year/round/session prevents duplicates."""
        WeatherData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload={'data': []}
        )
        
        with pytest.raises(IntegrityError):
            WeatherData.objects.create(
                year=2023,
                round_number=4,
                session="R",
                payload={'data': []}
            )
    
    def test_weather_data_different_sessions_allowed(self):
        """Verify different sessions can be stored for same year/round."""
        WeatherData.objects.create(year=2023, round_number=4, session="R", payload={'data': []})
        WeatherData.objects.create(year=2023, round_number=4, session="Q", payload={'data': []})
        
        assert WeatherData.objects.filter(year=2023, round_number=4).count() == 2
    
    def test_weather_data_timestamps_auto_set(self):
        """Verify created_at and updated_at timestamps are set automatically."""
        before = timezone.now()
        record = WeatherData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload={'data': []}
        )
        after = timezone.now()
        
        assert record.created_at is not None
        assert record.updated_at is not None
        assert before <= record.created_at <= after


@pytest.mark.django_db
class TestPitStopDataPersistence(TestCase):
    """Test PitStopData model persistence and constraints."""
    
    def test_pit_stop_data_creates_record_with_payload(self):
        """Verify PitStopData record is created with correct payload structure."""
        payload = {
            'data': [
                {'driver_number': 44, 'driver_code': 'HAM', 'stop_number': 1, 'lap': 15},
                {'driver_number': 77, 'driver_code': 'BOT', 'stop_number': 1, 'lap': 16},
            ]
        }
        
        record = PitStopData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload=payload
        )
        
        assert record.id is not None
        assert record.payload == payload
        assert len(record.payload['data']) == 2
    
    def test_pit_stop_data_unique_constraint_enforced(self):
        """Verify unique constraint prevents duplicate year/round/session combinations."""
        PitStopData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload={'data': []}
        )
        
        with pytest.raises(IntegrityError):
            PitStopData.objects.create(
                year=2023,
                round_number=4,
                session="R",
                payload={'data': []}
            )
    
    def test_pit_stop_data_can_update_existing_record(self):
        """Verify existing record can be updated with new payload."""
        record = PitStopData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload={'data': []}
        )
        original_id = record.id
        
        # Update the record
        record.payload = {'data': [{'driver_code': 'VER'}]}
        record.save()
        
        updated_record = PitStopData.objects.get(id=original_id)
        assert updated_record.payload['data'][0]['driver_code'] == 'VER'


@pytest.mark.django_db
class TestIncidentDataPersistence(TestCase):
    """Test IncidentData model persistence and constraints."""
    
    def test_incident_data_creates_record_with_payload(self):
        """Verify IncidentData record is created with correct payload structure."""
        payload = {
            'data': [
                {'lap': 1, 'driver_code': 'VER', 'incident_type': 'PUNCTURE', 'message': 'Puncture'},
                {'lap': 5, 'driver_code': 'HAM', 'incident_type': 'COLLISION', 'message': 'Contact'},
            ]
        }
        
        record = IncidentData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload=payload
        )
        
        assert record.payload == payload
        assert all('incident_type' in item for item in record.payload['data'])
    
    def test_incident_data_empty_payload_allowed(self):
        """Verify empty incident data is allowed (races with no incidents)."""
        record = IncidentData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload={'data': []}
        )
        
        assert record.payload == {'data': []}


@pytest.mark.django_db
class TestPositionDataPersistence(TestCase):
    """Test PositionData model persistence and constraints."""
    
    def test_position_data_creates_record_with_payload(self):
        """Verify PositionData record is created with correct payload structure."""
        payload = {
            'data': [
                {'lap': 1, 'driver_number': 1, 'driver_code': 'VER', 'position': 1},
                {'lap': 1, 'driver_number': 44, 'driver_code': 'HAM', 'position': 2},
            ]
        }
        
        record = PositionData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload=payload
        )
        
        assert record.payload == payload
        assert len(record.payload['data']) == 2
    
    def test_position_data_unique_constraint_enforced(self):
        """Verify unique constraint prevents duplicates."""
        PositionData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload={'data': []}
        )
        
        with pytest.raises(IntegrityError):
            PositionData.objects.create(
                year=2023,
                round_number=4,
                session="R",
                payload={'data': []}
            )


@pytest.mark.django_db
class TestDRSDataPersistence(TestCase):
    """Test DRSData model persistence and constraints."""
    
    def test_drs_data_creates_record_with_payload(self):
        """Verify DRSData record is created with correct payload structure."""
        payload = {
            'data': [
                {'lap': 5, 'driver_code': 'VER', 'status': 'AVAILABLE'},
                {'lap': 6, 'driver_code': 'HAM', 'status': 'USED'},
            ]
        }
        
        record = DRSData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload=payload
        )
        
        assert record.payload == payload
        assert all('status' in item for item in record.payload['data'])
    
    def test_drs_data_supports_multiple_records_per_session(self):
        """Verify payload can contain multiple DRS events per session."""
        payload = {
            'data': [
                {'lap': 5, 'driver_code': 'VER', 'status': 'AVAILABLE'},
                {'lap': 5, 'driver_code': 'VER', 'status': 'USED'},
                {'lap': 6, 'driver_code': 'HAM', 'status': 'AVAILABLE'},
            ]
        }
        
        record = DRSData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload=payload
        )
        
        assert len(record.payload['data']) == 3


@pytest.mark.django_db
class TestTrackStatusDataPersistence(TestCase):
    """Test TrackStatusData model persistence and constraints."""
    
    def test_track_status_data_creates_record_with_payload(self):
        """Verify TrackStatusData record is created with correct payload structure."""
        payload = {
            'data': [
                {'lap': 0, 'status': 'GREEN', 'message': 'Race start'},
                {'lap': 10, 'status': 'YELLOW', 'message': 'Incident at Turn 1'},
            ]
        }
        
        record = TrackStatusData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload=payload
        )
        
        assert record.payload == payload
        assert all('status' in item for item in record.payload['data'])
    
    def test_track_status_data_valid_statuses(self):
        """Verify track status data includes all expected status types."""
        payload = {
            'data': [
                {'status': 'GREEN'},
                {'status': 'YELLOW'},
                {'status': 'RED'},
            ]
        }
        
        record = TrackStatusData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload=payload
        )
        
        statuses = [item['status'] for item in record.payload['data']]
        assert 'GREEN' in statuses
        assert 'YELLOW' in statuses
        assert 'RED' in statuses
    
    def test_track_status_data_unique_constraint_enforced(self):
        """Verify unique constraint prevents duplicates."""
        TrackStatusData.objects.create(
            year=2023,
            round_number=4,
            session="R",
            payload={'data': []}
        )
        
        with pytest.raises(IntegrityError):
            TrackStatusData.objects.create(
                year=2023,
                round_number=4,
                session="R",
                payload={'data': []}
            )


@pytest.mark.django_db
class TestUnifiedModelsPersistenceShared(TestCase):
    """Test shared persistence patterns across all unified models."""
    
    def test_all_unified_models_support_jsonb_payload(self):
        """Verify all unified models can store complex JSONB payloads."""
        complex_payload = {
            'data': [
                {'field1': 'value1', 'field2': 123, 'field3': 45.67, 'field4': True, 'field5': None},
                {'field1': 'value2', 'nested': {'key': 'value'}, 'array': [1, 2, 3]},
            ]
        }
        
        models = [WeatherData, PitStopData, IncidentData, PositionData, DRSData, TrackStatusData]
        
        for model_class in models:
            record = model_class.objects.create(
                year=2023,
                round_number=4,
                session="R",
                payload=complex_payload
            )
            assert record.payload == complex_payload
            # Clean up for next iteration
            record.delete()
    
    def test_all_unified_models_retrieve_identical_payload(self):
        """Verify payload retrieved from DB matches what was stored."""
        original_payload = {
            'data': [
                {'id': 1, 'name': 'Test', 'values': [1.1, 2.2, 3.3]},
            ]
        }
        
        models = [WeatherData, PitStopData, IncidentData, PositionData, DRSData, TrackStatusData]
        
        for model_class in models:
            model_class.objects.create(
                year=2023,
                round_number=4,
                session="R",
                payload=original_payload
            )
            
            retrieved = model_class.objects.get(year=2023, round_number=4, session="R")
            assert retrieved.payload == original_payload
            # Clean up
            retrieved.delete()
