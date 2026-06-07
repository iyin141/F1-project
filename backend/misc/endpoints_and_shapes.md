# F1 Project Endpoints & Response Data Shapes

This document catalogs all the primary API endpoints exposed by the F1 Project backend, detailing their URL paths, purpose, and the shape of the data they return (as defined by their DRF serializers).

---

## 1. Schedule & Calendar

### Season Schedule
- **Endpoint:** `GET /api/races/<year>/`
- **Shape (`RaceSerializer` list):**
  Returns an array of races for the given year.
  ```json
  [
    {
      "round": 1,
      "name": "Bahrain Grand Prix",
      "date": "2024-03-02",
      "location": "Sakhir",
      "country": "Bahrain",
      "event_format": "standard",
      "session1": "FP1", "session1_date_utc": "...",
      "session2": "FP2", "session2_date_utc": "...",
      "session3": "FP3", "session3_date_utc": "...",
      "session4": "Qualifying", "session4_date_utc": "...",
      "session5": "Race", "session5_date_utc": "..."
    }
  ]
  ```

### Race Detail
- **Endpoint:** `GET /api/races/<year>/<round>/`
- **Shape:** Single `RaceSerializer` object.

---

## 2. Race & Session Results

### Race Results
- **Endpoint:** `GET /api/races/<year>/<round>/results/`
- **Shape (`RaceResultSerializer` list):**
  ```json
  [
    {
      "position": 1,
      "driver_number": 1,
      "driver_name": "Max Verstappen",
      "team": "Red Bull Racing",
      "points": 26,
      "status": "Finished",
      "grid_position": 1,
      "laps": 57,
      "gap": "0.000",
      "fastest_lap": "1:32.608",
      "fastest_lap_of_race": true
    }
  ]
  ```

### Qualifying Results
- **Endpoint:** `GET /api/races/<year>/<round>/qualifying/`
- **Shape (`QualifyingResultSerializer` list):** Includes `q1_time`, `q2_time`, `q3_time`.

### Sprint & Practice Results
- **Endpoints:**
  - `GET /api/races/<year>/<round>/sprint/`
  - `GET /api/races/<year>/<round>/sprint-shootout/`
  - `GET /api/races/<year>/<round>/practice/<session_name>/`
- **Shape:** Similar arrays of driver finishes/times (`PracticeResultSerializer` provides `lap_time` and `lap_number`).

---

## 3. Deep Analysis Endpoints (Lap, Pace, Strategy)

*All Deep Analysis and Telemetry endpoints wrap their data in a standardized response envelope:*
```json
{
  "meta": {
    "year": 2024, "round": 1, "session": "R", "row_count": 57,
    "extracted_at": "...", "limit_max": 1000
  },
  "filters_applied": { "driver": "VER", "limit": null },
  "data": [ /* Array of Row Serializers */ ]
}
```

### Laps
- **Endpoint:** `GET /api/analysis/races/<year>/<round>/laps/`
- **Shape (`LapAnalysisRowSerializer`):** `lap_time`, `sector1`, `sector2`, `sector3`, `compound`, `stint`, `is_personal_best`.

### Stints
- **Endpoint:** `GET /api/analysis/races/<year>/<round>/stints/`
- **Shape (`StintAnalysisRowSerializer`):** `stint_number`, `compound`, `lap_start`, `lap_end`, `total_laps`, `median_lap_seconds`.

### Pace
- **Endpoint:** `GET /api/analysis/races/<year>/<round>/pace/`
- **Shape (`PaceAnalysisRowSerializer`):** `session_median_lap_seconds`, `session_best_lap_seconds`, `consistency_stddev_seconds`, `pace_improvement_seconds`.

### Tyre Strategy
- **Endpoint:** `GET /api/analysis/races/<year>/<round>/tyre-strategy/`
- **Shape (`TyreStrategyRowSerializer`):** Includes `avg_lap_seconds`, `median_lap_seconds`, and `degradation_seconds` per compound stint.

### Sector Analysis
- **Endpoint:** `GET /api/analysis/races/<year>/<round>/sector-analysis/`
- **Shape (`SectorAnalysisRowSerializer`):** Compares best and median sector times, providing a `theoretical_best_lap_seconds` per driver.

---

## 4. High-Frequency Telemetry

### Single Driver Telemetry
- **Endpoint:** `GET /api/analysis/races/<year>/<round>/telemetry/`
- **Shape (`TelemetryAnalysisPointSerializer`):**
  Returns thousands of data points per lap.
  ```json
  [
    {
      "time_seconds": 1.234,
      "distance_m": 54.2,
      "speed_kph": 240.5,
      "throttle_pct": 100.0,
      "brake": false,
      "rpm": 11500,
      "gear": 6
    }
  ]
  ```

### Telemetry Overlay (Compare Two Drivers)
- **Endpoint:** `GET /api/analysis/races/<year>/<round>/telemetry/overlay/`
- **Shape (`TelemetryOverlayResponseSerializer`):** Returns an array of `traces`, where each trace contains the driver code and their respective array of telemetry points.

### Telemetry Summary
- **Endpoint:** `GET /api/analysis/races/<year>/<round>/telemetry/summary/`
- **Shape (`TelemetrySummaryPayloadSerializer`):** Returns aggregated data like `max_speed_kph`, `braking_zones`, and `throttle_on_percentage`.

---

## 5. Drivers & Constructors Standings

### Driver Standings
- **Endpoint:** `GET /api/drivers/<year>/`
- **Shape (`DriverStandingsResponseSerializer`):**
  ```json
  {
    "year": 2024,
    "drivers": [
      {
        "position": 1,
        "driver_name": "Max Verstappen",
        "points": 400.0,
        "wins": 15,
        "constructor": "Red Bull Racing"
      }
    ]
  }
  ```

### Constructor Standings
- **Endpoint:** `GET /api/constructors/<year>/`
- **Shape (`ConstructorStandingsResponseSerializer`):** Similar to Drivers, grouped by Constructor.

### Driver Career
- **Endpoint:** `GET /api/drivers/<driver_code>/career/`
- **Shape (`DriverCareerResponseSerializer`):** Arrays of `career` rows detailing races, wins, podiums, and championships per year, alongside lifetime `career_totals`.

### Driver Season
- **Endpoint:** `GET /api/drivers/<driver_code>/<year>/`
- **Shape (`DriverSeasonResponseSerializer`):** A breakdown of every race a driver competed in during a specific year, including finish positions, points, sprint results, and grid positions.

---

## 6. Unified Data Endpoints (Timeline Events)
Provides granular timeline events across an entire session under the `/api/unified/races/<year>/<round>/` prefix:

- `/weather/` -> `WeatherRowSerializer` (`air_temp_c`, `track_temp_c`, `rainfall`)
- `/pit-stops/` -> `PitStopRowSerializer` (`stop_duration_seconds`, `time_gain_loss_seconds`)
- `/incidents/` -> `IncidentRowSerializer` (`message_type`, `flag`, `drivers_involved`)
- `/positions/` -> `PositionChangeRowSerializer` (`position_change`, `gap_to_leader_seconds`)
- `/drs/` -> `DRSRowSerializer` (`drs_available`, `drs_activated`)
- `/track-status/` -> `TrackStatusRowSerializer` (`status`, `cause`, `affected_zone`)
