# Unified FastF1 Data Extraction Service Design

## Overview

Single comprehensive REST API service that extracts **all** FastF1 data (telemetry, weather, pit stops, incidents, positions, DRS, track status) with intelligent caching, normalization, and validation.

## Architecture

### 1. **Session Manager** (`SessionManager`)

**Purpose:** Load FastF1 sessions once, cache them, expose to all extractors.

```python
class SessionManager:
    _cache = {}  # {(year, round, session): FSession}

    @classmethod
    def get_session(cls, year, round, session_type):
        # Returns cached or loads fresh
        # Loads: telemetry=True, weather=True, messages=True
        # Caches by (year, round, session_type) tuple
```

**Benefits:**

- No redundant FastF1 API calls
- Shared cache across all data extractors
- Single source of truth for session data

---

### 2. **Data Normalizer** (`DataNormalizer`)

**Purpose:** Handle type conversions, NaN/None, precision rounding consistently.

```python
class DataNormalizer:
    @staticmethod
    def to_int(value) -> Optional[int]
    @staticmethod
    def to_float(value, precision=3) -> Optional[float]
    @staticmethod
    def to_str(value) -> Optional[str]
    @staticmethod
    def to_bool(value) -> bool
    @staticmethod
    def to_time_seconds(value) -> Optional[float]
    @staticmethod
    def to_timedelta_str(value) -> Optional[str]
    @staticmethod
    def safe_get(df, col, default=None)
    @staticmethod
    def fill_na(series, fill_value=0)
```

**Replaces:** Current ad-hoc `_safe_*` functions. Centralized, reusable, testable.

---

### 3. **Base Data Extractor** (`BaseDataExtractor`)

**Purpose:** Abstract interface for all data extraction types.

```python
class BaseDataExtractor:
    def __init__(self, session, year, round, session_type, driver=None):
        self.session = session
        self.year = year
        self.round = round
        self.session_type = session_type
        self.driver = driver

    def extract(self, **kwargs) -> dict:
        """Override in subclasses. Returns:
        {
            "meta": {...},
            "filters_applied": {...},
            "data": [...]
        }
        """
        raise NotImplementedError

    def _build_response(self, data_rows, additional_meta=None):
        """Standard response builder"""
        base_meta = {
            "year": self.year,
            "round": self.round,
            "session": self.session_type,
            "row_count": len(data_rows),
            "extracted_at": datetime.now().isoformat(),
        }
        if additional_meta:
            base_meta.update(additional_meta)

        return {
            "meta": base_meta,
            "filters_applied": {
                "driver": self.driver,
            },
            "data": data_rows,
        }
```

---

### 4. **Concrete Extractors** (All inherit from `BaseDataExtractor`)

#### **TelemetryExtractor**

- Lap telemetry (speed, throttle, brake, gear, RPM, distance)
- Sector window filtering
- Point downsampling (stride + limit)

#### **WeatherExtractor**

- Track/air temperature, humidity, wind
- Per-lap snapshots or session average
- Weather change timeline

#### **PitStopExtractor**

- Stop duration, lap, compound strategy
- Driver, stop number, crew efficiency
- Loss per lap vs. fresh compound gain

#### **IncidentExtractor**

- Messages (radio calls, marshalling)
- Crashes, retirements, mechanical failures
- Safety car/VSC deployments
- Timestamp and affected drivers

#### **PositionExtractor**

- Position changes lap-by-lap
- Gap to leader/car ahead
- Overtake opportunities (where/when)
- On-track vs. pit stop gains

#### **DRSExtractor**

- DRS activation zones
- DRS available vs. used
- Performance delta with DRS
- Gap before/after activation

#### **TrackStatusExtractor**

- Yellow/red flag timeline
- Safety car deployments
- Virtual safety car periods
- Track hazard locations

#### **TyreDegradationExtractor**

- Compound-specific lap-by-lap pace
- Degradation curve per tyre
- Optimal tyre life prediction
- Pit window analysis

---

### 5. **Response Serializers**

```python
# Base serializer classes (used by all extractors)
class BaseMetaSerializer(serializers.Serializer):
    year = serializers.IntegerField()
    round = serializers.IntegerField()
    session = serializers.CharField()
    row_count = serializers.IntegerField()
    extracted_at = serializers.DateTimeField()

class BaseFiltersSerializer(serializers.Serializer):
    driver = serializers.CharField(allow_null=True)

class BaseResponseSerializer(serializers.Serializer):
    meta = BaseMetaSerializer()
    filters_applied = BaseFiltersSerializer()
    data = serializers.ListField()  # Subclasses define specific row serializers
```

Each extractor has specialized serializer:

- `TelemetryResponseSerializer` with `TelemetryRowSerializer`
- `WeatherResponseSerializer` with `WeatherRowSerializer`
- etc.

---

### 6. **Query API Endpoint**

**Unified Query Route:**

```
GET /api/analysis/races/<year>/<round>/full-session/?
    session=R&
    include=telemetry,weather,pit_stops,incidents,positions,drs,track_status,tyre_degradation
```

**Individual Extract Routes (convenience):**

```
GET /api/analysis/races/<year>/<round>/weather/
GET /api/analysis/races/<year>/<round>/pit-stops/
GET /api/analysis/races/<year>/<round>/incidents/
GET /api/analysis/races/<year>/<round>/positions/
GET /api/analysis/races/<year>/<round>/drs/
GET /api/analysis/races/<year>/<round>/track-status/
GET /api/analysis/races/<year>/<round>/tyre-degradation/
```

**View Implementation:**

```python
class AnalysisFullSessionAPIView(APIView):
    def get(self, request, year, round_number):
        session_type = request.query_params.get("session", "R")
        include_list = request.query_params.get("include", "").split(",")

        # Load session once
        session = SessionManager.get_session(year, round_number, session_type)

        # Extract requested data
        response_data = {"meta": {...}, "data": {}}
        for include_type in include_list:
            extractor_class = EXTRACTORS_MAP[include_type]
            extractor = extractor_class(session, year, round_number, session_type)
            response_data["data"][include_type] = extractor.extract()

        return Response(response_data)
```

---

### 7. **Error Handling & Validation**

```python
class DataExtractionError(Exception):
    """Raised when data extraction fails"""

class ValidationError(Exception):
    """Raised when data doesn't meet constraints"""

# In views:
try:
    data = extractor.extract()
except (ValueError, DataExtractionError) as e:
    return Response({"error": str(e)}, status=400)
except Exception as e:
    return Response({"error": f"Service error: {str(e)}"}, status=500)
```

---

### 8. **Testing Strategy**

**Unit Tests:**

- Mock FastF1 session with synthetic data
- Test each extractor independently
- Verify normalization consistency
- Validate response shapes match serializers

**Integration Tests:**

- Mock full session load
- Query multiple extractors simultaneously
- Verify no data corruption across extractors
- Test caching behavior

**Smoke Tests:**

- Live API calls to real race sessions
- Verify end-to-end payload structure
- Check performance (cache hit times)

---

## Implementation Order

1. **SessionManager** + **DataNormalizer** (shared infrastructure)
2. **Existing extractors refactor** (laps, stints, pace, telemetry → use new base)
3. **New extractors** (weather, pit stops, incidents, positions, DRS, track status, tyre degradation)
4. **Unified response serializers**
5. **Full-session query endpoint** + individual convenience routes
6. **Comprehensive test suite**
7. **Performance profiling** (cache hit rates, response times)

## Benefits

✅ **Single session load** — eliminates N redundant FastF1 API calls  
✅ **Unified error handling** — consistent validation + error responses  
✅ **Extensible** — new data sources bolt in with minimal refactoring  
✅ **Testable** — each extractor tested independently + with mock data  
✅ **Cacheable** — frontend can query `?include=all` once, get everything  
✅ **Frontend-friendly** — one endpoint for all race data, or pick individual metrics

## Data Coverage

| Data Type        | Source                                    | Status              |
| ---------------- | ----------------------------------------- | ------------------- |
| Laps             | `session.laps`                            | Existing (refactor) |
| Stints           | `session.laps` groupby                    | Existing (refactor) |
| Pace             | `session.laps` analysis                   | Existing (refactor) |
| Telemetry        | `lap.get_car_data()`                      | Existing (refactor) |
| Weather          | `session.weather` + `lap.weather`         | **New**             |
| Pit Stops        | `session.laps["PitInLap"]` + pit data     | **New**             |
| Incidents        | `session.messages`                        | **New**             |
| Positions        | Position change tracking                  | **New**             |
| DRS              | `lap.drs_enabled` / `lap.drs_activations` | **New**             |
| Track Status     | `session.track_status`                    | **New**             |
| Tyre Degradation | `session.laps` by compound                | **New**             |
