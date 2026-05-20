# API Endpoints to Database Models Mapping

Complete reference of all F1 Dashboard API endpoints, their data persistence patterns, and which database models store the data.

---

## Overview

- **Read-Only Endpoints**: Query data from the database without direct saves. May trigger background Celery tasks that persist data.
- **Task-Triggered Endpoints**: Return data immediately while enqueueing async tasks to populate/update models in the background.
- **Models**: The 12 database models that store persisted F1 data.

---

## Database Models Reference

| Model                   | Purpose                                                                            | Persisted By                                                                   |
| ----------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `SeasonSchedule`        | Race calendar for a season                                                         | `populate_schedule` task                                                       |
| `RaceResultData`        | Race session results (R, S, SQ)                                                    | `populate_race_results` task                                                   |
| `QualifyingResultData`  | Qualifying session results (Q)                                                     | `populate_race_results` task                                                   |
| `PracticeResultData`    | Practice session results (FP1-FP3)                                                 | `populate_race_results` task                                                   |
| `DriverStandings`       | Driver championship standings by year                                              | `populate_standings` task                                                      |
| `ConstructorStandings`  | Constructor championship standings by year                                         | `populate_constructor_standings` task                                          |
| `DriverCareer`          | Complete driver career history                                                     | `populate_driver_career` task                                                  |
| `DriverSeasonBreakdown` | Driver performance breakdown for a season                                          | `populate_driver_season` task                                                  |
| `DriverLapAnalysis`     | Per-lap analysis (times, sectors, stints)                                          | `populate_session_data` task                                                   |
| `DriverTelemetry`       | Telemetry data per driver per session                                              | `populate_telemetry` task                                                      |
| `SessionData`           | Unified session data (weather, pit stops, incidents, positions, DRS, track status) | Multiple tasks: `populate_weather`, `populate_pit_stops`, `populate_incidents` |
| `TaskRecord`            | Background task execution status                                                   | TaskManager (lifecycle tracking)                                               |

---

## Endpoints by Domain

### 🏁 Schedule Domain (`/api/races/`)

#### `GET /api/races/{year}/`

**View**: `SeasonScheduleAPIView`

- **Purpose**: Get full race calendar for a season
- **Returns**: List of races with round, name, date, location, country
- **Data Persistence**:
  - **Read from**: `SeasonSchedule` model (if cached)
  - **Writes to**: Enqueues `populate_schedule` task → `SeasonSchedule`
- **Behavior**: DB-first; falls back to FastF1 and triggers background persistence if not cached

#### `GET /api/races/{year}/{round}/`

**View**: `RaceDetailAPIView`

- **Purpose**: Get details for a single race
- **Returns**: Race name, date, location, country for one round
- **Data Persistence**:
  - **Read from**: `SeasonSchedule` model
  - **Writes to**: None (read-only)
- **Behavior**: Queries cached schedule; falls back to FastF1 live

---

### 🏎️ Results Domain (`/api/races/`)

#### `GET /api/races/{year}/{round}/results/`

**View**: `RaceResultsAPIView`

- **Purpose**: Get race & qualifying results combined
- **Returns**: Race classification and qualifying times
- **Data Persistence**:
  - **Read from**: `RaceResultData`, `QualifyingResultData` models
  - **Writes to**: Enqueues `populate_race_results` tasks for missing sessions
- **Models Updated**:
  - `RaceResultData` (race session type 'R')
  - `QualifyingResultData` (qualifying session type 'Q')

#### `GET /api/races/{year}/{round}/qualifying/`

**View**: `QualifyingResultsAPIView`

- **Purpose**: Get qualifying session results
- **Returns**: Q1, Q2, Q3 times and final grid positions
- **Data Persistence**:
  - **Read from**: `QualifyingResultData` model
  - **Writes to**: Enqueues `populate_race_results` task if missing

#### `GET /api/races/{year}/{round}/sprint/`

**View**: `SprintResultsAPIView`

- **Purpose**: Get sprint race results
- **Returns**: Sprint race classification
- **Data Persistence**:
  - **Read from**: `RaceResultData` model (session type 'S')
  - **Writes to**: Enqueues `populate_race_results` task if missing

#### `GET /api/races/{year}/{round}/sprint-shootout/`

**View**: `SprintShootoutResultsAPIView`

- **Purpose**: Get sprint shootout results
- **Returns**: Sprint shootout classification
- **Data Persistence**:
  - **Read from**: `RaceResultData` model (session type 'SQ')
  - **Writes to**: Enqueues `populate_race_results` task if missing

#### `GET /api/races/{year}/{round}/practice/{session_name}/`

**View**: `PracticeSessionAPIView`

- **Purpose**: Get fastest laps for a practice session
- **Parameters**: `session_name` = FP1, FP2, or FP3
- **Returns**: Practice leaderboard with best lap times
- **Data Persistence**:
  - **Read from**: `PracticeResultData` model
  - **Writes to**: Enqueues `populate_race_results` task if missing
- **Models Updated**: `PracticeResultData` (for FP1, FP2, FP3)

#### `GET /api/races/{year}/{round}/weekend/`

**View**: `WeekendResultsAPIView`

- **Purpose**: Get all session results for a race weekend
- **Returns**: Results for every session (FP1-3, Q, SS, S, R)
- **Data Persistence**:
  - **Read from**: Multiple result models (Schedule, Race, Qualifying, Sprint, Shootout, Practice)
  - **Writes to**: Enqueues `populate_race_results` tasks for missing sessions
- **Models Updated**:
  - `SeasonSchedule` (format determination)
  - `QualifyingResultData`
  - `RaceResultData`
  - `PracticeResultData`

---

### 👥 Driver Domain (`/api/drivers/`)

#### `GET /api/drivers/standings/{year}/`

**View**: `DriverStandingsAPIView`

- **Purpose**: Get driver championship standings
- **Returns**: Current/historical standings with position, points, wins
- **Data Persistence**:
  - **Read from**: `DriverStandings` model
  - **Writes to**: Enqueues `populate_standings` task → `DriverStandings`
- **Behavior**: DB-first; triggers background persistence if not cached for year

#### `GET /api/drivers/{driver_code}/career/`

**View**: `DriverCareerAPIView`

- **Purpose**: Get complete driver career history
- **Returns**: All seasons with position, points, wins, podiums, poles, fastest laps, DNFs
- **Data Persistence**:
  - **Read from**: `DriverCareer` model
  - **Writes to**: Enqueues `populate_driver_career` task → `DriverCareer`
- **Behavior**: DB-first; fetches from Jolpica API for missing seasons

#### `GET /api/drivers/{driver_code}/{year}/`

**View**: `DriverSeasonAPIView`

- **Purpose**: Get driver performance breakdown for a season
- **Returns**: All races in season with results, points, status
- **Data Persistence**:
  - **Read from**: `DriverSeasonBreakdown` model
  - **Writes to**: Enqueues `populate_driver_season` task → `DriverSeasonBreakdown`
- **Behavior**: DB-first; triggers background persistence if not cached

---

### 🏗️ Constructor Domain (`/api/constructors/`)

#### `GET /api/constructors/{year}/`

**View**: `ConstructorStandingsAPIView`

- **Purpose**: Get constructor championship standings
- **Returns**: Team standings with position, points, wins
- **Data Persistence**:
  - **Read from**: `ConstructorStandings` model
  - **Writes to**: Enqueues `populate_constructor_standings` task → `ConstructorStandings`
- **Behavior**: DB-first; triggers background persistence if not cached

---

### 📊 Analysis Domain (`/api/analysis/races/`)

#### `GET /api/analysis/races/{year}/{round}/laps/`

**View**: `AnalysisLapsAPIView`

- **Purpose**: Get lap-by-lap analysis
- **Query Parameters**: `session` (R/Q/S/SQ/FP1-FP3), `driver` (3-letter code), `limit`
- **Returns**: Per-lap data: lap time, sector times, compound, stint, personal best flag
- **Data Persistence**:
  - **Read from**: `DriverLapAnalysis` model
  - **Writes to**: Enqueues `populate_session_data` task → `DriverLapAnalysis`, `SessionData`

#### `GET /api/analysis/races/{year}/{round}/stints/`

**View**: `AnalysisStintsAPIView`

- **Purpose**: Get stint analysis (tire strategy)
- **Query Parameters**: `session`, `driver`, `limit`
- **Returns**: Stint data with compound, lap range, duration
- **Data Persistence**:
  - **Read from**: `DriverLapAnalysis` model
  - **Writes to**: Enqueues `populate_session_data` task → `DriverLapAnalysis`

#### `GET /api/analysis/races/{year}/{round}/pace/`

**View**: `AnalysisPaceAPIView`

- **Purpose**: Get pace analysis (pace delta)
- **Query Parameters**: `session`, `driver`, `limit`
- **Returns**: Pace comparison data
- **Data Persistence**:
  - **Read from**: `SessionData` model
  - **Writes to**: Enqueues `populate_session_data` task → `SessionData`

#### `GET /api/analysis/races/{year}/{round}/tyre-strategy/`

**View**: `AnalysisTyreStrategyAPIView`

- **Purpose**: Get tyre strategy analysis
- **Query Parameters**: `session`, `driver`, `limit`
- **Returns**: Tire usage, laps on compound, stops
- **Data Persistence**:
  - **Read from**: `SessionData` model
  - **Writes to**: Enqueues `populate_session_data` task → `SessionData`

#### `GET /api/analysis/races/{year}/{round}/sector-analysis/`

**View**: `AnalysisSectorAPIView`

- **Purpose**: Get sector analysis
- **Query Parameters**: `session`, `driver`, `limit`
- **Returns**: Per-sector lap times, deltas
- **Data Persistence**:
  - **Read from**: `SessionData` model
  - **Writes to**: Enqueues `populate_session_data` task → `SessionData`

#### `GET /api/analysis/races/{year}/{round}/telemetry/`

**View**: `AnalysisTelemetryAPIView`

- **Purpose**: Get telemetry data
- **Query Parameters**: `session`, `driver`, `lap`
- **Returns**: Speed, throttle, brake, DRS, gear data
- **Data Persistence**:
  - **Read from**: `DriverTelemetry` model
  - **Writes to**: Enqueues `populate_telemetry` task → `DriverTelemetry`
- **Queue**: `tier4_telemetry` (low priority)

#### `GET /api/analysis/races/{year}/{round}/telemetry/overlay/`

**View**: `AnalysisTelemetryOverlayAPIView`

- **Purpose**: Get overlay of multiple telemetry traces
- **Query Parameters**: `session`, `drivers`, `lap`
- **Returns**: Telemetry for multiple drivers on same lap
- **Data Persistence**:
  - **Read from**: `DriverTelemetry` model
  - **Writes to**: Enqueues `populate_telemetry` tasks → `DriverTelemetry`

#### `GET /api/analysis/races/{year}/{round}/telemetry/summary/`

**View**: `AnalysisTelemetrySummaryAPIView`

- **Purpose**: Get telemetry summary for a driver
- **Query Parameters**: `session`, `driver`
- **Returns**: Aggregated telemetry statistics
- **Data Persistence**:
  - **Read from**: `DriverTelemetry` model
  - **Writes to**: Enqueues `populate_telemetry` task → `DriverTelemetry`

---

### 🔀 Unified Session Domain (`/api/unified/races/`)

Unified endpoints provide a single interface to access various session data types. All enqueue background tasks to populate `SessionData`.

#### `GET /api/unified/races/{year}/{round}/full-session/`

**View**: `UnifiedFullSessionAPIView`

- **Purpose**: Comprehensive session data
- **Returns**: Combined data from all session extractors
- **Data Persistence**:
  - **Read from**: `SessionData` model
  - **Writes to**: Enqueues `populate_session_data` task → `SessionData`

#### `GET /api/unified/races/{year}/{round}/weather/`

**View**: `UnifiedWeatherAPIView`

- **Purpose**: Get weather data
- **Returns**: Air temp, track temp, wind, humidity, rainfall
- **Data Persistence**:
  - **Read from**: `SessionData` model (weather field)
  - **Writes to**: Enqueues `populate_weather` task → `SessionData`
- **Queue**: `tier2_fast`

#### `GET /api/unified/races/{year}/{round}/pit-stops/`

**View**: `UnifiedPitStopsAPIView`

- **Purpose**: Get pit stop data
- **Returns**: Stop number, lap, duration, compound changes
- **Data Persistence**:
  - **Read from**: `SessionData` model (pit_stops field)
  - **Writes to**: Enqueues `populate_pit_stops` task → `SessionData`
- **Queue**: `tier2_fast`

#### `GET /api/unified/races/{year}/{round}/incidents/`

**View**: `UnifiedIncidentsAPIView`

- **Purpose**: Get incident/accident/collision data
- **Returns**: Incidents with drivers, lap, type, classification
- **Data Persistence**:
  - **Read from**: `SessionData` model (incidents field)
  - **Writes to**: Enqueues `populate_incidents` task → `SessionData`
- **Queue**: `tier2_fast`

#### `GET /api/unified/races/{year}/{round}/positions/`

**View**: `UnifiedPositionsAPIView`

- **Purpose**: Get track position data
- **Returns**: Position history with lap numbers
- **Data Persistence**:
  - **Read from**: `SessionData` model (positions field)
  - **Writes to**: Enqueues `populate_session_data` task → `SessionData`
- **Queue**: `tier2_fast`

#### `GET /api/unified/races/{year}/{round}/drs/`

**View**: `UnifiedDRSAPIView`

- **Purpose**: Get DRS deployment data
- **Returns**: DRS usage by lap and driver
- **Data Persistence**:
  - **Read from**: `SessionData` model (drs field)
  - **Writes to**: Enqueues `populate_session_data` task → `SessionData`
- **Queue**: `tier2_fast`

#### `GET /api/unified/races/{year}/{round}/track-status/`

**View**: `UnifiedTrackStatusAPIView`

- **Purpose**: Get track status evolution
- **Returns**: Status changes (green, yellow, red, VSC, SC) with laps
- **Data Persistence**:
  - **Read from**: `SessionData` model (track_status field)
  - **Writes to**: Enqueues `populate_session_data` task → `SessionData`
- **Queue**: `tier2_fast`

---

### 📋 Task Status Domain (`/api/tasks/`)

#### `GET /api/tasks/{task_id}/status/`

**View**: `TaskStatusAPIView` (Phase 5)

- **Purpose**: Poll background task status
- **Returns**: Task state (PENDING, RUNNING, SUCCESS, FAILED) with progress
- **Data Persistence**:
  - **Read from**: `TaskRecord` model
  - **Writes to**: None (read-only status check)
- **Behavior**: Non-blocking polling endpoint for monitoring async operations

---

## Data Flow Patterns

### Pattern 1: Direct Model Reads (No DB Writes)

```
API Request → View → Service → Query Model → Response
No background tasks enqueued
Example: GET /api/races/{year}/{round}/
```

### Pattern 2: DB-First with Background Persistence

```
API Request → View → Service
  ├─ Query Model (if cached) → Return cached data
  └─ Not cached:
     ├─ Query FastF1/Jolpica live
     ├─ Return live data
     └─ Enqueue populate_* task

Background Task:
  populate_* → Fetch data → Write to Model → Mark complete

Next Request: Uses cached model data
```

### Pattern 3: Task Status Polling

```
API Request → View → Check TaskRecord → Return status
User polls periodically until status = SUCCESS/FAILED
```

---

## Model Relationships

### By Primary Purpose

**Championship & Standings:**

- `DriverStandings` ← populated by `/api/drivers/standings/{year}/`
- `ConstructorStandings` ← populated by `/api/constructors/{year}/`

**Race Results:**

- `RaceResultData` ← populated by `/api/races/{year}/{round}/results/`
- `QualifyingResultData` ← populated by `/api/races/{year}/{round}/qualifying/`
- `PracticeResultData` ← populated by `/api/races/{year}/{round}/practice/{session}/`

**Driver Information:**

- `DriverCareer` ← populated by `/api/drivers/{driver_code}/career/`
- `DriverSeasonBreakdown` ← populated by `/api/drivers/{driver_code}/{year}/`

**Session Analysis:**

- `DriverLapAnalysis` ← populated by `/api/analysis/races/{year}/{round}/laps/`
- `DriverTelemetry` ← populated by `/api/analysis/races/{year}/{round}/telemetry/`
- `SessionData` ← populated by unified endpoints and weather/incidents/pit stops endpoints

**Infrastructure:**

- `SeasonSchedule` ← populated by `/api/races/{year}/`
- `TaskRecord` ← lifecycle tracking for all background tasks

---

## Queue Routing (Celery)

| Queue             | Priority | TTL      | Tasks                                                                                                                           |
| ----------------- | -------- | -------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `tier1_instant`   | Highest  | N/A      | `populate_standings`, `populate_constructor_standings`, `populate_schedule`, `populate_driver_career`, `populate_driver_season` |
| `tier2_fast`      | High     | 60s      | `populate_race_results`, `populate_session_data`, `populate_weather`, `populate_pit_stops`, `populate_incidents`                |
| `tier4_telemetry` | Low      | Ack late | `populate_telemetry`                                                                                                            |
| `backfill`        | Lowest   | N/A      | Bulk historical data tasks (Phase 6)                                                                                            |

---

## Phase 6: Race Completion Prefetching

When a race result is saved via signal handler:

```
RaceResultData saved → on_race_result_created() signal
  → detect_race_completion(year, round_number)
  → If race complete:
     → prefetch_race_completion(year, round_number)
     → Enqueues 4 tasks in tier2_fast:
        1. populate_race_results (full session)
        2. populate_session_data (laps, stints)
        3. populate_weather (weather)
        4. populate_incidents (incidents)
```

---

## Summary Statistics

- **Total Endpoints**: 28
- **Total Models**: 12
- **Models with Direct DB Writes**: 12
- **Task-Triggered Models**: 10
- **Read-Only Endpoints**: ~8
- **Write-Enqueuing Endpoints**: ~20
- **Celery Queues**: 4 (tier1_instant, tier2_fast, tier4_telemetry, backfill)

---

## Key Design Principles

1. **DB-First Strategy**: All endpoints check persisted models before falling back to live API calls
2. **Background Persistence**: Data writes happen asynchronously via Celery tasks, never in the request-response cycle
3. **Readiness Metadata**: All responses include `readiness` object indicating data availability and warnings
4. **Deduplication**: TaskManager uses Redis SETNX locks to prevent duplicate task execution
5. **Non-Blocking**: API returns immediately with cached/live data while background task completes
6. **Tiered Queuing**: Critical standing/schedule tasks run on tier1_instant; heavy analysis on tier4_telemetry

---

**Last Updated**: Phase 6 Complete  
**Status**: Production Ready
