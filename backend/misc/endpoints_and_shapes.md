# API Endpoints and Data Shapes

This document outlines the domain-driven endpoints available in the backend and the JSON schema returned by their respective serializers. All data-fetching endpoints generally return their response wrapped in a unified meta structure unless they return an async task processing response:

```json
{
  "meta": { "year": 2024, "round": 1, "session": "R", "row_count": 10 },
  "filters_applied": { ... },
  "data": [ ... ]
}
```

---

## 1. Drivers Domain (`api/drivers/`)

### `/api/drivers/search/`
- **Purpose**: Search for a driver by string.
- **Data Shape** (`DriverSearchMatchesSerializer`):
  ```json
  {
    "matches": [
      {
        "driver_code": "VER",
        "name": "Max Verstappen",
        "match_type": "exact",
        "confidence": 1.0
      }
    ]
  }
  ```

### `/api/drivers/<driver_id>/career/`
- **Purpose**: Historical career stats for a driver.
- **Data Shape** (`DriverCareerResponseSerializer` -> `DriverCareerSeasonSerializer` / `DriverCareerTotalsSerializer`):
  ```json
  {
    "driver_name": "Max Verstappen",
    "nationality": "Dutch",
    "career": [
      { "year": 2023, "constructor": "Red Bull", "position": 1, "points": 575, "wins": 19 }
    ],
    "career_totals": { "championships": 3, "wins": 54, "podiums": 98 }
  }
  ```

### `/api/drivers/standings/<year>/`
- **Purpose**: Season driver standings.
- **Data Shape** (`DriverStandingsResponseSerializer` -> `DriverStandingSerializer`):
  ```json
  {
    "standings": [
      { "position": 1, "driver_code": "VER", "driver_name": "Max Verstappen", "points": 575, "wins": 19, "constructor": "Red Bull" }
    ]
  }
  ```

---

## 2. Constructors Domain (`api/constructors/`)

### `/api/constructors/standings/<year>/`
- **Purpose**: Season constructor standings.
- **Data Shape** (`ConstructorStandingsResponseSerializer` -> `ConstructorSerializer`):
  ```json
  {
    "standings": [
      { "position": 1, "team_id": "red_bull", "name": "Red Bull Racing", "points": 860, "wins": 21 }
    ]
  }
  ```

---

## 3. Results Domain (`api/results/`)

### `/api/results/<year>/<round>/race/`
- **Purpose**: Final classification of the race.
- **Data Shape** (`RaceResultSerializer`):
  ```json
  {
    "position": 1,
    "driver_number": 1,
    "driver_name": "Max Verstappen",
    "team": "Red Bull Racing",
    "points": 25,
    "status": "Finished",
    "grid_position": 1,
    "laps": 57,
    "gap": "+0.000",
    "fastest_lap": "1:34.000",
    "fastest_lap_of_race": true
  }
  ```

### `/api/results/<year>/<round>/qualifying/`
- **Purpose**: Qualifying times.
- **Data Shape** (`QualifyingResultSerializer`):
  ```json
  {
    "position": 1,
    "driver_number": 1,
    "driver_name": "Max Verstappen",
    "team": "Red Bull Racing",
    "q1_time": "1:30.000",
    "q2_time": "1:29.500",
    "q3_time": "1:29.000"
  }
  ```

---

## 4. Session Domain (`api/session/` & `api/unified/`)

### Lap Analysis (`/api/unified/races/<year>/<round>/laps/`)
- **Data Shape** (`LapAnalysisRowSerializer`):
  ```json
  {
    "lap_number": 1,
    "driver_code": "VER",
    "lap_time": "1:35.000",
    "sector1": "30.000",
    "sector2": "30.000",
    "sector3": "35.000",
    "compound": "SOFT",
    "stint": 1,
    "is_personal_best": true
  }
  ```

### Stint Analysis (`/api/unified/races/<year>/<round>/stints/`)
- **Data Shape** (`StintAnalysisRowSerializer`):
  ```json
  {
    "driver_code": "VER",
    "driver_number": 1,
    "stint_number": 1,
    "compound": "SOFT",
    "lap_start": 1,
    "lap_end": 15,
    "total_laps": 15
  }
  ```

### Telemetry Overlay (`/api/unified/races/<year>/<round>/telemetry-overlay/`)
- **Data Shape** (`TelemetryOverlayTraceSerializer`):
  ```json
  {
    "driver_code": "VER",
    "lap_number": 15,
    "compound": "SOFT",
    "lap_time": "1:30.000",
    "telemetry": {
      "distance": [0, 10, 20],
      "speed": [300, 310, 315],
      "throttle": [100, 100, 100],
      "brake": [0, 0, 0],
      "gear": [8, 8, 8]
    }
  }
  ```

### Weather Data (`/api/unified/races/<year>/<round>/weather/`)
- **Data Shape** (`WeatherRowSerializer`):
  ```json
  {
    "lap_number": 5,
    "track_temp_c": 35.5,
    "air_temp_c": 28.0,
    "humidity_pct": 45.0,
    "wind_speed_ms": 3.2,
    "wind_direction_deg": 180,
    "rainfall": false
  }
  ```

### Pit Stops (`/api/unified/races/<year>/<round>/pit-stops/`)
- **Data Shape** (`PitStopRowSerializer`):
  ```json
  {
    "driver_code": "VER",
    "driver_number": 1,
    "stop_number": 1,
    "lap_in": 15,
    "lap_out": 16,
    "stop_duration_seconds": 2.5,
    "compound_in": "SOFT",
    "compound_out": "MEDIUM"
  }
  ```

---

## 5. Schedule Domain (`api/schedule/`)

### `/api/schedule/<year>/`
- **Purpose**: Get the race calendar for a specific year.
- **Data Shape** (`RaceSerializer`):
  ```json
  {
    "round": 1,
    "name": "Bahrain Grand Prix",
    "date": "2024-03-02",
    "location": "Sakhir",
    "country": "Bahrain",
    "sessions": {
      "FP1": "2024-02-29T11:30:00Z",
      "Qualifying": "2024-03-01T16:00:00Z"
    }
  }
  ```
