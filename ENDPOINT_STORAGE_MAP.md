# Endpoint -> Storage Map (New Model Structure)

This document shows where each API endpoint stores data in the current model structure.

## Model/Table Reference

- SeasonSchedule -> season_schedule
- RaceResultData -> race_results
- QualifyingResultData -> qualifying_results
- PracticeResultData -> practice_results
- DriverLapAnalysis -> driver_lap_analysis
- DriverTelemetry -> driver_telemetry
- SessionData -> session_data
- DriverStandings -> driver_standings
- ConstructorStandings -> constructor_standings
- TaskRecord -> celery_task_record

## Important Behavior

- Most endpoints are GET-only and return live/persisted data.
- Some GET endpoints trigger async background persistence through Celery.
- Async dispatch always writes task lifecycle state to TaskRecord (celery_task_record).

## Endpoint Mapping

| Endpoint                                                     | View                            | Persistence behavior                                                                                                                          | Target model/table(s)                                                                                                             |
| ------------------------------------------------------------ | ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| /api/races/{year}/                                           | SeasonScheduleAPIView           | Read-only endpoint. Returns live schedule with persisted overlay when present. No write from this endpoint.                                   | none                                                                                                                              |
| /api/races/{year}/{round_number}/                            | RaceDetailAPIView               | Read-only endpoint. No write from this endpoint.                                                                                              | none                                                                                                                              |
| /api/races/{year}/{round_number}/results/                    | RaceResultsAPIView              | On live fetch, enqueues populate_race_results with task_key race:{year}:{round}:R. Worker persists race session data.                         | RaceResultData/race_results, DriverLapAnalysis/driver_lap_analysis, SeasonSchedule/season_schedule, TaskRecord/celery_task_record |
| /api/races/{year}/{round_number}/qualifying/                 | QualifyingResultsAPIView        | On live fetch, enqueues populate_race_results with task_key race:{year}:{round}:Q.                                                            | QualifyingResultData/qualifying_results, TaskRecord/celery_task_record                                                            |
| /api/races/{year}/{round_number}/sprint/                     | SprintResultsAPIView            | On live fetch, enqueues populate_race_results with task_key race:{year}:{round}:S.                                                            | RaceResultData/race_results (session=S), TaskRecord/celery_task_record                                                            |
| /api/races/{year}/{round_number}/sprint-shootout/            | SprintShootoutResultsAPIView    | On live fetch, enqueues populate_race_results with task_key race:{year}:{round}:SQ.                                                           | RaceResultData/race_results (session=SQ), TaskRecord/celery_task_record                                                           |
| /api/races/{year}/{round_number}/practice/{session_name}/    | PracticeSessionAPIView          | On live fetch, enqueues populate_race_results with task_key race:{year}:{round}:{FP1/FP2/FP3}.                                                | PracticeResultData/practice_results, TaskRecord/celery_task_record                                                                |
| /api/analysis/races/{year}/{round_number}/laps/              | AnalysisLapsAPIView             | Read/compute endpoint. Does not enqueue persistence.                                                                                          | none (may read from DriverLapAnalysis)                                                                                            |
| /api/analysis/races/{year}/{round_number}/stints/            | AnalysisStintsAPIView           | Read endpoint. Uses persisted data for race session when available; no write.                                                                 | none (may read from DriverLapAnalysis)                                                                                            |
| /api/analysis/races/{year}/{round_number}/pace/              | AnalysisPaceAPIView             | Read endpoint. Uses persisted data for race session when available; no write.                                                                 | none (may read from DriverLapAnalysis)                                                                                            |
| /api/analysis/races/{year}/{round_number}/tyre-strategy/     | AnalysisTyreStrategyAPIView     | Read endpoint. Uses persisted data for race session when available; no write.                                                                 | none (may read from DriverLapAnalysis)                                                                                            |
| /api/analysis/races/{year}/{round_number}/sector-analysis/   | AnalysisSectorAPIView           | Read endpoint. Uses persisted data for race session when available; no write.                                                                 | none (may read from DriverLapAnalysis)                                                                                            |
| /api/analysis/races/{year}/{round_number}/telemetry/         | AnalysisTelemetryAPIView        | On live fetch, enqueues populate_telemetry with task_key telemetry:{year}:{round}:{session}.                                                  | DriverTelemetry/driver_telemetry, TaskRecord/celery_task_record                                                                   |
| /api/analysis/races/{year}/{round_number}/telemetry/overlay/ | AnalysisTelemetryOverlayAPIView | On live fetch, enqueues populate_telemetry for each requested driver/lap pair (same task_key scope).                                          | DriverTelemetry/driver_telemetry, TaskRecord/celery_task_record                                                                   |
| /api/analysis/races/{year}/{round_number}/telemetry/summary/ | AnalysisTelemetrySummaryAPIView | On live fetch, enqueues populate_telemetry with task_key telemetry:{year}:{round}:{session}.                                                  | DriverTelemetry/driver_telemetry, TaskRecord/celery_task_record                                                                   |
| /api/drivers/{year}/                                         | DriverStandingsAPIView          | If standings not persisted, enqueues populate_standings with task_key standings:{year}.                                                       | DriverStandings/driver_standings (season aggregate row), TaskRecord/celery_task_record                                            |
| /api/constructors/{year}/                                    | ConstructorStandingsAPIView     | Currently read-only from external API. No persistence triggered by this endpoint in current wiring.                                           | none (ConstructorStandings model exists but not written here)                                                                     |
| /api/coverage/persistence/{year}/                            | PersistenceCoverageAPIView      | Read-only coverage inspection.                                                                                                                | none                                                                                                                              |
| /api/coverage/persistence/{year}/{round_number}/             | PersistenceCoverageAPIView      | Read-only coverage inspection.                                                                                                                | none                                                                                                                              |
| /api/unified/races/{year}/{round_number}/full-session/       | UnifiedFullSessionAPIView       | When at least one include type is available from live session, enqueues populate_session_data with task_key session:{year}:{round}:{session}. | SessionData/session_data (keys: weather, pit_stops, incidents, positions, drs, track_status), TaskRecord/celery_task_record       |
| /api/unified/races/{year}/{round_number}/weather/            | UnifiedWeatherAPIView           | Read-only unified extractor endpoint; no enqueue from this endpoint.                                                                          | none                                                                                                                              |
| /api/unified/races/{year}/{round_number}/pit-stops/          | UnifiedPitStopsAPIView          | Read-only unified extractor endpoint; no enqueue from this endpoint.                                                                          | none                                                                                                                              |
| /api/unified/races/{year}/{round_number}/incidents/          | UnifiedIncidentsAPIView         | Read-only unified extractor endpoint; no enqueue from this endpoint.                                                                          | none                                                                                                                              |
| /api/unified/races/{year}/{round_number}/positions/          | UnifiedPositionsAPIView         | Read-only unified extractor endpoint; no enqueue from this endpoint.                                                                          | none                                                                                                                              |
| /api/unified/races/{year}/{round_number}/drs/                | UnifiedDRSAPIView               | Read-only unified extractor endpoint; no enqueue from this endpoint.                                                                          | none                                                                                                                              |
| /api/unified/races/{year}/{round_number}/track-status/       | UnifiedTrackStatusAPIView       | Read-only unified extractor endpoint; no enqueue from this endpoint.                                                                          | none                                                                                                                              |
| /api/drivers/{driver_code}/career/                           | DriverCareerAPIView             | Read-only aggregation endpoint (DB + Jolpica fallback). No write from this endpoint.                                                          | none                                                                                                                              |
| /api/drivers/{driver_code}/{year}/                           | DriverSeasonAPIView             | Read-only aggregation endpoint (DB + Jolpica fallback). No write from this endpoint.                                                          | none                                                                                                                              |

## Async Task -> Write Targets

- populate_standings
  - writes DriverStandings/driver_standings
- populate_race_results
  - session R: writes RaceResultData/race_results, DriverLapAnalysis/driver_lap_analysis, SeasonSchedule/season_schedule
  - session Q: writes QualifyingResultData/qualifying_results
  - session FP1/FP2/FP3: writes PracticeResultData/practice_results
  - session S/SQ: writes RaceResultData/race_results
- populate_session_data
  - writes SessionData/session_data (merged payload keys)
- populate_telemetry
  - writes DriverTelemetry/driver_telemetry

All above tasks also update TaskRecord/celery_task_record for pending/running/complete/failed state tracking.
