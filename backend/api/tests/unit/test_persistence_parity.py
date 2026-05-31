from django.test import TestCase
from unittest.mock import patch

from api.management.commands.populate_race import _run_race, _run_qualifying, _run_practice, _run_sprint, _run_sprint_shootout
from api.models import (
    RaceResultData,
    QualifyingResultData,
    PracticeResultData,
    DriverTelemetry,
    DriverStandings,
    SessionData,
)
from api.models import RaceResultData as _R
from api.results.serializers import (
    RaceResultSerializer,
    QualifyingResultSerializer,
    PracticeResultSerializer,
    SprintResultSerializer,
)


class PersistenceParityTest(TestCase):
    @patch('api.management.commands.populate_race.get_race_by_round')
    @patch('api.management.commands.populate_race.get_race_session_results')
    @patch('api.management.commands.populate_race.fastf1.get_session')
    def test_race_persistence_parity(self, mock_get_session, mock_get_race_session_results, mock_get_race_by_round):
        # Dummy session with a no-op load() used by the command
        class DummySession:
            def load(self, *args, **kwargs):
                return None

        mock_get_session.return_value = DummySession()

        sample = [
            {
                'position': 1,
                'driver_number': 44,
                'driver_name': 'Lewis Hamilton',
                'team': 'Mercedes',
                'points': 25,
                'status': 'Finished',
                'grid_position': 1,
                'laps': 56,
                'gap': 'LEADER',
                'fastest_lap': '1:12.345',
                'fastest_lap_of_race': True,
            },
            {
                'position': 2,
                'driver_number': 77,
                'driver_name': 'Valtteri Bottas',
                'team': 'Mercedes',
                'points': 18,
                'status': 'Finished',
                'grid_position': 2,
                'laps': 56,
                'gap': '+1.234',
                'fastest_lap': None,
                'fastest_lap_of_race': False,
            },
        ]

        mock_get_race_session_results.return_value = sample
        mock_get_race_by_round.return_value = {
            'name': 'Test Grand Prix',
            'date': None,
            'location': 'Testville',
            'country': 'Testland',
            'event_format': None,
            'session1': None,
            'session1_date_utc': None,
            'session2': None,
            'session2_date_utc': None,
            'session3': None,
            'session3_date_utc': None,
            'session4': None,
            'session4_date_utc': None,
            'session5': None,
            'session5_date_utc': None,
        }

        _run_race(2000, 1, force=True)

        record = RaceResultData.objects.get(year=2000, round_number=1, session='R')
        self.assertEqual(record.payload.get('data'), RaceResultSerializer(sample, many=True).data)

    @patch('api.management.commands.populate_race.get_qualifying_results')
    def test_qualifying_persistence_parity(self, mock_get_qualifying_results):
        sample = [
            {
                'position': 1,
                'driver_number': 44,
                'driver_name': 'Lewis Hamilton',
                'team': 'Mercedes',
                'q1_time': '1:12.345',
                'q2_time': None,
                'q3_time': None,
            }
        ]

        mock_get_qualifying_results.return_value = {'data': sample, 'meta': {}}

        _run_qualifying(2001, 2, force=True)

        record = QualifyingResultData.objects.get(year=2001, round_number=2)
        self.assertEqual(record.payload.get('data'), QualifyingResultSerializer(sample, many=True).data)

    @patch('api.management.commands.populate_race.get_practice_session_results')
    def test_practice_persistence_parity(self, mock_get_practice):
        sample = [
            {
                'position': 1,
                'driver_code': 'HAM',
                'team': 'Mercedes',
                'lap_time': '1:12.345',
                'lap_number': 44,
            }
        ]
        mock_get_practice.return_value = {'data': sample, 'meta': {}}

        _run_practice(2002, 3, 'FP1', force=True)

        record = PracticeResultData.objects.get(year=2002, round_number=3, session='FP1')
        self.assertEqual(record.payload.get('data'), PracticeResultSerializer(sample, many=True).data)

    @patch('api.management.commands.populate_race.get_sprint_results')
    def test_sprint_persistence_parity(self, mock_get_sprint):
        sample = [
            {
                'position': 1,
                'driver_number': 33,
                'driver_name': 'Max Verstappen',
                'team': 'Red Bull',
                'points': 8,
                'status': 'Finished',
                'grid_position': 1,
                'laps': 20,
                'gap': 'LEADER',
                'fastest_lap': None,
                'fastest_lap_of_sprint': False,
            }
        ]
        mock_get_sprint.return_value = {'data': sample, 'meta': {}}

        _run_sprint(2003, 4, force=True)

        # Sprint results are stored in RaceResultData with session 'S'
        from api.models import RaceResultData as _R
        record = _R.objects.get(year=2003, round_number=4, session='S')
        self.assertEqual(record.payload.get('data'), SprintResultSerializer(sample, many=True).data)

    @patch('api.management.commands.populate_race.get_sprint_shootout_results')
    def test_sprint_shootout_persistence_parity(self, mock_get_shootout):
        sample = [
            {
                'position': 1,
                'driver_number': 5,
                'driver_name': 'Sebastian Vettel',
                'team': 'Aston Martin',
                'q1_time': '1:15.000',
                'q2_time': None,
                'q3_time': None,
            }
        ]
        mock_get_shootout.return_value = {'data': sample, 'meta': {}}

        _run_sprint_shootout(2004, 5, force=True)

        record = _R.objects.get(year=2004, round_number=5, session='SQ')
        from api.results.serializers import SprintShootoutResultSerializer
        self.assertEqual(record.payload.get('data'), SprintShootoutResultSerializer(sample, many=True).data)

    @patch('api.management.commands.populate_telemetry.fastf1.get_session')
    def test_telemetry_persistence_parity(self, mock_get_session):
        import pandas as pd

        # Build a simple telemetry DataFrame for one lap
        tel_df = pd.DataFrame({
            'Distance': [0.0, 100.0],
            'Speed': [0.0, 200.0],
            'Throttle': [0.0, 100.0],
            'Brake': [False, False],
            'nGear': [1, 2],
            'RPM': [1000, 8000],
            'DRS': [False, True],
            'RelativeDistance': [0.0, 100.0],
        })

        class DummyRow:
            def __init__(self, lap_number, tel_df):
                self._lap_number = lap_number
                self._tel_df = tel_df

            def __getitem__(self, key):
                if key == 'LapNumber':
                    return self._lap_number
                raise KeyError(key)

            def get_car_data(self):
                class CarData:
                    def __init__(self, df):
                        self._df = df

                    def add_distance(self):
                        return self._df

                return CarData(self._tel_df)

        class DummyDriverLaps:
            def iterrows(self):
                return iter([(0, DummyRow(1, tel_df))])

        class DummySession:
            def load(self, *args, **kwargs):
                return None

            @property
            def laps(self):
                class Laps:
                    def pick_driver(self, driver):
                        return DummyDriverLaps()

                return Laps()

        mock_get_session.return_value = DummySession()

        from api.management.commands.populate_telemetry import run as tele_run

        tele_run(2018, 7, 'R', 'HAM', force=True, stride=1)

        expected_payload = {
            '1': {
                'distance': [0.0, 100.0],
                'speed': [0.0, 200.0],
                'throttle': [0.0, 100.0],
                'brake': [False, False],
                'gear': [1, 2],
                'rpm': [1000, 8000],
                'drs': [False, True],
                'relative_distance': [0.0, 100.0],
            }
        }

        record = DriverTelemetry.objects.get(year=2018, round_number=7, session='R', driver_code='HAM')
        self.assertEqual(record.payload, expected_payload)

    @patch('api.management.commands.populate_standings.requests.get')
    def test_standings_persistence_parity(self, mock_get):
        sample_json = {
            'MRData': {
                'StandingsTable': {
                    'StandingsLists': [
                        {
                            'DriverStandings': [
                                {
                                    'position': '1',
                                    'points': '25',
                                    'wins': '1',
                                    'Driver': {'givenName': 'Lewis', 'familyName': 'Hamilton'},
                                    'Constructors': [{'name': 'Mercedes'}],
                                }
                            ]
                        }
                    ]
                }
            }
        }

        class DummyResp:
            status_code = 200

            def json(self):
                return sample_json

        mock_get.return_value = DummyResp()

        from api.management.commands.populate_standings import run as standings_run
        standings_run(2020, force=True)

        record = DriverStandings.objects.get(year=2020, driver_code=None)

        expected = [
            {
                'position': 1,
                'driver_name': 'Lewis Hamilton',
                'points': 25.0,
                'wins': 1,
                'constructor': 'Mercedes',
            }
        ]

        from api.serializers import DriverStandingSerializer
        self.assertEqual(record.payload.get('standings'), DriverStandingSerializer(expected, many=True).data)

    def test_session_persistence_parity(self):
        sample = [
            {'lap_number': 1, 'driver_code': 'HAM', 'track_temp_c': 25.0}
        ]

        # Temporarily override the extractor specs so we control the extractor used
        import importlib
        mod = importlib.import_module('api.management.commands.populate_session')

        class DummyExtractor:
            def __init__(self, *args, **kwargs):
                pass

            def extract(self, **kwargs):
                return {'data': sample}

        original_specs = getattr(mod, '_EXTRACTOR_SPECS')
        try:
            mod._EXTRACTOR_SPECS = [('weather', DummyExtractor, {})]
            from api.management.commands.populate_session import run as session_run
            session_run(2021, 6, 'R', force=True, only='weather')
        finally:
            mod._EXTRACTOR_SPECS = original_specs

        rec = SessionData.objects.get(year=2021, round_number=6, session='R')
        self.assertEqual(rec.payload.get('weather'), sample)
