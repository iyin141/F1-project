"""
Phase D Implementation Guide: Worker Serialization Pattern

This guide shows how to update each of the 14 workers to properly serialize and publish
full data payloads via the worker_utils.handle_result() function.

All workers follow the same 3-step pattern:

1. Fetch/calculate result data
2. Serialize using appropriate serializer
3. Call worker_utils.handle_result() to publish, cache, persist, and complete task

===========================================================================================
PATTERN A: Workers that fetch data from DB after command runs
===========================================================================================

Example: populate_race_results, populate_standings (already updated)

template_worker.py:
from api.services import worker_utils
from api.models import SomeModel
from api.serializers import SomeResponseSerializer

    @shared_task(bind=True, max_retries=0, queue="tier1_instant")
    def template_worker(self, task_key: str, year: int, ...):
        try:
            # 1. Run command that persists data
            from api.management.commands.populate_something import run
            run(year=int(year), ...)

            # 2. Fetch persisted data
            data = SomeModel.objects.filter(year=year, ...).values()
            data_list = list(data)

            # 3. Serialize
            serializer = SomeResponseSerializer(data_list, many=True)
            serialized_data = serializer.data

            # 4. Handle result
            worker_utils.handle_result(
                task_key=task_key,
                data_type="some_type",
                serialized_data=serialized_data,
                cache_key=f"some_type:{year}:...",
                db_rows=None,
                db_model=None,
            )
        except Exception as exc:
            ...

APPLICABLE TO:

- ✅ populate_race_results (DONE) — fetches RaceResultData after command runs
- ✅ populate_standings (DONE) — fetches DriverStandings after command runs
- [ ] populate_constructor_standings — fetch ConstructorStandings, use ConstructorStandingsResponseSerializer
- [ ] populate_schedule — fetch SeasonSchedule, use appropriate serializer
- [ ] populate_driver_career — fetch DriverCareer, use DriverCareerResponseSerializer
- [ ] populate_driver_season — fetch DriverSeasonBreakdown, use DriverSeasonResponseSerializer

===========================================================================================
PATTERN B: Workers that extract and persist to new dedicated models
===========================================================================================

Example: populate_weather, populate_incidents, populate_pit_stops, populate_drs,
populate_track_status

These workers need to:

1. Run populate_session.py command
2. Get back extracted data
3. Serialize with appropriate serializer
4. Persist to dedicated DB model (WeatherData, IncidentData, PitStopData, DRSData, TrackStatusData)
5. Publish to pub/sub with full payload

NOTE: populate_session.py returns data_dict[key] = rows_list.
rows_list is already in the format expected by bulk_create().

template_worker.py:
from api.services import worker_utils
from api.models import WeatherData # Replace with appropriate model
from api.serializers import WeatherResponseSerializer # Replace with appropriate serializer

    @shared_task(bind=True, max_retries=0, queue="tier2_fast")
    def populate_weather(self, task_key: str, year: int, round_number: int):
        try:
            # 1. Extract data via populate_session command
            from api.management.commands.populate_session import run
            run(year=int(year), round_number=int(round_number), session_type="R", only="weather")

            # 2. Fetch extracted data from DB
            rows = WeatherData.objects.filter(
                year=int(year),
                round_number=int(round_number),
                session="R"
            ).values()
            rows_list = list(rows)

            # 3. Serialize
            serializer = WeatherResponseSerializer(rows_list, many=True)
            serialized_data = serializer.data

            # 4. Handle result (db_rows=None because data already persisted by run())
            worker_utils.handle_result(
                task_key=task_key,
                data_type="weather",
                serialized_data=serialized_data,
                cache_key=f"weather:{year}:{round_number}:R",
                db_rows=None,  # Already bulk_created by command
                db_model=None,
            )
        except Exception as exc:
            ...

APPLICABLE TO:

- [ ] populate_weather → WeatherData + WeatherResponseSerializer
- [ ] populate_incidents → IncidentData + IncidentResponseSerializer
- [ ] populate_pit_stops → PitStopData + PitStopResponseSerializer
- [ ] populate_positions → PositionData + PositionResponseSerializer (from populate_session)
- [ ] populate_drs → DRSData + DRSResponseSerializer (from populate_session)
- [ ] populate_track_status → TrackStatusData + TrackStatusResponseSerializer (from populate_session)

===========================================================================================
PATTERN C: Telemetry workers (specialized)
===========================================================================================

Example: populate_telemetry

Same as Pattern B but:

- Uses DriverTelemetry model (already exists)
- Uses TelemetryAnalysisResponseSerializer
- Session flags: telemetry=True, laps=True (from ENDPOINT_LOAD_MAP)

template_worker.py:
from api.management.commands.populate_telemetry import run
from api.models import DriverTelemetry
from api.serializers import TelemetryAnalysisResponseSerializer

    @shared_task(bind=True, max_retries=0, queue="tier4_telemetry")
    def populate_telemetry(self, task_key: str, year: int, round_number: int, session_type: str):
        try:
            run(year=int(year), round_number=int(round_number), session_type=str(session_type))

            rows = DriverTelemetry.objects.filter(
                year=int(year),
                round_number=int(round_number),
                session=str(session_type)
            ).values()
            rows_list = list(rows)

            serializer = TelemetryAnalysisResponseSerializer(rows_list, many=True)
            serialized_data = serializer.data

            worker_utils.handle_result(
                task_key=task_key,
                data_type="telemetry",
                serialized_data=serialized_data,
                cache_key=f"telemetry:{year}:{round_number}:{session_type}",
                db_rows=None,
                db_model=None,
            )
        except Exception as exc:
            ...

APPLICABLE TO:

- [ ] populate_telemetry → DriverTelemetry + TelemetryAnalysisResponseSerializer

===========================================================================================
PATTERN D: Derived analysis workers (no DB writes)
===========================================================================================

These workers compute analysis from lap data and don't write to DB.
They only: serialize + publish + cache.

template_worker.py:
from api.services import worker_utils
from api.services.analysis import get_stint_analysis # Example
from api.serializers import StintAnalysisResponseSerializer

    @shared_task(bind=True, max_retries=0, queue="tier3_medium")
    def populate_stint_analysis(self, task_key: str, year: int, round_number: int, session_type: str):
        try:
            # 1. Load session and compute analysis
            from api.services.fastf1_runtime import fastf1
            session = fastf1.get_session(int(year), int(round_number), str(session_type))
            session.load(laps=True)  # Use ENDPOINT_LOAD_MAP

            # 2. Get analysis from service
            analysis_data = get_stint_analysis(session)

            # 3. Serialize
            serializer = StintAnalysisResponseSerializer(analysis_data, many=True)
            serialized_data = serializer.data

            # 4. Handle result (db_rows=None, no DB write)
            worker_utils.handle_result(
                task_key=task_key,
                data_type="stint_analysis",
                serialized_data=serialized_data,
                cache_key=f"stint_analysis:{year}:{round_number}:{session_type}",
                db_rows=None,
                db_model=None,
            )
        except Exception as exc:
            ...

APPLICABLE TO:

- [ ] populate_stint_analysis → StintAnalysisResponseSerializer (no DB model)
- [ ] populate_pace_analysis → PaceAnalysisResponseSerializer (no DB model)
- [ ] populate_sector_analysis → SectorAnalysisResponseSerializer (no DB model)
- [ ] populate_tyre_strategy → TyreStrategyResponseSerializer (no DB model)
- [ ] populate_telemetry_summary → TelemetrySummaryResponseSerializer (no DB model)

===========================================================================================
PATTERN E: Pagination workers (read from DB, serialize, publish)
===========================================================================================

These workers read paginated data from DB and publish with pagination metadata.
Currently they have TODO stubs — implement as:

template_worker.py:
from api.services import worker_utils
from api.models import DriverLapAnalysis
from api.serializers import LapAnalysisResponseSerializer

    @shared_task(bind=True, max_retries=0, queue="tier5_pagination")
    def paginate_laps(self, task_key: str, year: int, round_number: int, session_type: str, page: int = 1):
        try:
            # 1. Read paginated data from DB
            page_size = 50
            offset = (int(page) - 1) * page_size

            rows = DriverLapAnalysis.objects.filter(
                year=int(year),
                round_number=int(round_number),
                session=str(session_type),
            )[offset:offset+page_size].values()
            rows_list = list(rows)

            # 2. Serialize
            serializer = LapAnalysisResponseSerializer(rows_list, many=True)
            serialized_data = serializer.data

            # 3. Handle result
            worker_utils.handle_result(
                task_key=task_key,
                data_type="paginate_laps",
                serialized_data=serialized_data,
                cache_key=f"paginate_laps:{year}:{round_number}:{session_type}:{page}",
                db_rows=None,
                db_model=None,
            )
        except Exception as exc:
            ...

APPLICABLE TO:

- [ ] paginate_laps → DriverLapAnalysis + LapAnalysisResponseSerializer
- [ ] paginate_positions → PositionData + PositionResponseSerializer
- [ ] paginate_telemetry → DriverTelemetry + TelemetryAnalysisResponseSerializer

===========================================================================================
KEY POINTS
===========================================================================================

1. **Always use worker_utils.handle_result()**: Ensures consistent pub/sub payload format:
   {
   "status": "complete",
   "source": "worker",
   "data_type": "...",
   "data": {...serialized_payload...}
   }

2. **Cache key format**: "{data_type}:{year}:{round_number}:{session_type}"
   (Must match nonblocking.py's cache_key pattern)

3. **Import worker_utils early**: `from api.services import worker_utils`

4. **Serializers**: Use many=True for lists, many=False for single objects
   Serializer input can be list of dicts (from .values()) or model instances

5. **Error handling**: pubsub.publish_error() for pub/sub, TaskRecord.update() for status
   worker_utils handles the success case only

6. **Load flags**: Import from endpoint_load_map when extracting from FastF1

   ```python
   from api.workers.endpoint_load_map import get_session_load_kwargs
   load_kwargs = get_session_load_kwargs("laps")
   session.load(**load_kwargs)
   ```

7. **DB persistence**:
   - If command already bulk_creates: pass db_rows=None, db_model=None
   - If extracting raw data: pass db_rows=list_of_dicts, db_model=ModelClass

===========================================================================================
TESTING THE PATTERN
===========================================================================================

After updating each worker, test with:

1. Call worker via Celery or direct task invocation
2. Check Redis pub/sub: `redis-cli PUBSUB CHANNELS | grep task_result`
3. Verify cache: `redis-cli GET {cache_key}`
4. Verify SSE returns full data (not just status marker)
5. Verify DB has persisted rows (if applicable)

Example test in manage.py shell:
from api.workers.tier1_instant.populate_standings import populate_standings
result = populate_standings.apply_async(
args=("standings:2024", 2024),
queue="tier1_instant"
) # Check result.id in Redis # Check cache key in Redis # Check DriverStandings table

===========================================================================================
NEXT STEPS
===========================================================================================

1. Rank workers by impact (which requests use them most?)
2. Apply Pattern A to: constructor_standings, schedule, driver_career, driver_season
3. Apply Pattern B to: weather, incidents, pit_stops (+ create new populate_session.py task if needed)
4. Apply Pattern C to: populate_telemetry
5. Apply Pattern D to: stint, pace, sector, tyre_strategy, telemetry_summary analysis
6. Apply Pattern E to: paginate_laps, paginate_positions, paginate_telemetry
7. Run full test suite
8. Test SSE with real request to verify end-to-end data flow
   """
