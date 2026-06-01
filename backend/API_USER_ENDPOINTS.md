# F1 API — User-Facing Endpoints

This document lists the primary user-facing API endpoints, how to call them, their HTTP method, explicit JSON return shapes, and important usage rules.

Base URL: /api/

All endpoints return JSON (`application/json`) unless otherwise noted. Most endpoints require an API key via the `X-API-Key` header (see **Authentication & Rules**).

---

**Authentication & Rules**

- **Auth header**: Provide your API key in the `X-API-Key` header. Example: `X-API-Key: 00000000-0000-0000-0000-000000000000`.
- **Rate limits**: Tiered rate limits apply (per-key token bucket). See `/api/auth/me/` to inspect your live quota.
- **Return type**: All documented endpoints return JSON objects or arrays. Every response that can be partial includes a `readiness` object describing availability.
- **Errors**: Standard HTTP error codes + JSON payloads with `error` and `message` fields.

---

**Authentication / Registration**

- `POST /api/auth/register/`
  - Method: POST
  - Body: JSON `{ "email": "you@example.com" }`
  - Returns: 201/202/200 JSON object
    - Example: `{"message":"created","email":"you@example.com","api_key":"<uuid>"}`
  - Rules: Internal-only endpoint (requires `INTERNAL_API_KEY` or an internal-tier key in header). Rate-limited: 5 attempts/hour per IP.

- `GET /api/auth/me/`
  - Method: GET
  - Returns: 200 JSON object
    - Response serializer: `api.views.registration.RegisterResponseSerializer` (see `backend/api/views/registration.py`)
    - Example keys: `{"api_key":"<uuid>","tier":"free|pro","request_count":12,"quota_window":"2026-06-01T00:00:00Z"}`
  - Rules: Requires valid API key. Use to check quota before heavy requests.

---

**Drivers**

- `GET /api/drivers/<int:year>/`
  - Method: GET
  - Returns: 200 JSON object
    - Response serializer: `api.drivers.serializers.DriverStandingsResponseSerializer` (driver standings list)
    - Example: `{"year":2024,"standings":[{"position":1,"driver_code":"VER","points":438}],"readiness":{...}}`
  - Rules: `year` must be integer (1950+). Data served from DB or returned as available in `readiness`.

- `GET /api/drivers/<str:driver_code>/career/`
  - Method: GET
  - Returns: 200 JSON object
    - Response serializer: `api.drivers.serializers.DriverCareerResponseSerializer`
    - Example: `{"driver_code":"HAM","career_summary":{"seasons":[...],"total_wins":103},"readiness":{...}}`
  - Rules: `driver_code` accepts a 3-letter FIA code (alphabetic, case-insensitive) or a Jolpica driver id (string). Alphabetic codes must be exactly 3 letters; otherwise treated as provider id. No auth for read, but rate limits apply.

- `GET /api/drivers/<str:driver_code>/<int:year>/`
  - Method: GET
  - Returns: 200 JSON object
    - Response serializer: `api.drivers.serializers.DriverSeasonResponseSerializer` (per-season breakdown)
    - Example: `{"driver_code":"LEC","year":2024,"races":[{"round":1,"position":2,"points":18}],"readiness":{...}}`
  - Rules: `year` must be integer; same driver_code rules as above.

- `GET /api/drivers/search/?year=<year>`
  - Method: GET
  - Returns: 200 JSON array
    - Response serializer: `api.drivers.serializers.DriverListResponseSerializer` / `api.drivers.serializers.DriverListItemSerializer` (list of drivers)
    - Example: `[{"driver_code":"HAM","driver_name":"Lewis Hamilton","team":"Mercedes"}, ...]`
  - Rules: `year` query param required.

- `GET /api/drivers/search-by-name/?q=<query>&year=<year>`
  - Method: GET
  - Returns: 200 JSON array
    - Response serializer: `api.drivers.serializers.DriverSearchByNameResponseSerializer` / `DriverSearchByNameResultSerializer`
    - Example: `[{"driver_code":"VER","driver_name":"Max Verstappen","year":2024}]`
  - Rules: `q` min length 2. Year optional. DB-only search.

---

**Races & Schedule**

- `GET /api/races/<int:year>/`
  - Method: GET
  - Returns: 200 JSON object
    - Response serializer: `api.schedule.serializers.RaceSerializer` (used for season schedule entries)
    - Example: `{"year":2024,"races":[{"round":1,"name":"Bahrain Grand Prix","date":"2024-03-02"}],"readiness":{...}}`

- `GET /api/races/<int:year>/<int:round_number>/`
  - Method: GET
  - Returns: 200 JSON object
    - Response serializer: `api.schedule.serializers.RaceSerializer` (single race detail payload) and related session payloads using `api.results.serializers` types where applicable
    - Example: `{"year":2024,"round":1,"name":"Bahrain Grand Prix","sessions":{...},"readiness":{...}}`

---

**Results**

- Results endpoints are mounted under `/api/races/` (see `/backend/api/results/urls.py` for specifics). Typical endpoints return race/practice/qualifying results as JSON arrays or objects.

- Common return shapes:
  - `GET /api/races/<year>/<round>/results/` → 200 JSON object
    - Response serializers: `api.results.serializers.QualifyingResultSerializer` (for `results.qualifying`) and `api.results.serializers.RaceResultSerializer` (for `results.race`). The outer envelope includes a `readiness` object.
    - Example: `{"year":2024,"round":1,"results":{"qualifying":[...],"race":[...]},"readiness":{...}}`
  - `GET /api/races/<year>/<round>/qualifying/` → 200 JSON object
    - Response serializer: `api.results.serializers.QualifyingResultSerializer` (array of qualifying rows)
    - Example: `{"year":2024,"round":1,"qualifying":[{"position":1,"driver_name":"Max Verstappen",...}],"readiness":{...}}`
  - `GET /api/races/<year>/<round>/practice/<session>/` → 200 JSON object
    - Response serializer: `api.results.serializers.PracticeResultSerializer` (array of practice rows)
    - Example: `{"year":2024,"round":1,"session":"FP1","practice":[{"driver_code":"VER","lap_time":"0:01:31.000"}],"readiness":{...}}`

- Note: When a requested dataset is known to be missing or empty in the DB the response will include a `readiness` object explaining which pieces are available and which are not. Endpoints do not perform blocking FastF1 loads on the HTTP thread.

---

**Analysis**

- `GET /api/analysis/races/<int:year>/<int:round_number>/laps/`
  - Method: GET
  - Returns: 200 JSON object
    - Response serializer: `api.serializers.LapAnalysisResponseSerializer` (meta, filters_applied, data)
    - Example: `{"meta": {...}, "filters_applied": {...}, "data": [{"driver_code":"VER","lap_number":1,...}]}`

- `GET /api/analysis/races/<int:year>/<int:round_number>/stints/`
  - Method: GET
  - Returns: 200 JSON object
    - Response serializer: `api.serializers.StintAnalysisResponseSerializer`
    - Example: `{"meta": {...}, "data": [{"driver_code":"HAM","stint":1,"average_lap":...}]}`

- Other analysis endpoints: `pace`, `tyre-strategy`, `sector-analysis`, `telemetry`, `telemetry/overlay`, `telemetry/summary` — all GET and return JSON objects.
- Other analysis endpoints and their serializers:
  - `pace` → `api.serializers.PaceAnalysisResponseSerializer`
  - `tyre-strategy` → `api.serializers.TyreStrategyResponseSerializer`
  - `sector-analysis` → `api.serializers.SectorAnalysisResponseSerializer`
  - `telemetry` → `api.serializers.TelemetryAnalysisResponseSerializer`
  - `telemetry/overlay` → `api.serializers.TelemetryOverlayResponseSerializer`
  - `telemetry/summary` → `api.serializers.TelemetrySummaryResponseSerializer`

---

**Unified (aggregated)**

- Example: `GET /api/unified/races/<int:year>/<int:round_number>/full-session/`
  - Method: GET
  - Returns: 200 JSON object (aggregated session payload)
    - Response serializer: `api.serializers.UnifiedBaseResponseSerializer` (envelope) and `api.serializers.UnifiedMetaSerializer` for meta fields
    - Example keys: `positions`, `telemetry`, `incidents`, `readiness`.

---

**Constructors**

- `GET /api/constructors/<int:year>/`
  - Method: GET
  - Method: GET
  - Returns: 200 JSON object
    - Response serializer: `api.constructors.serializers.ConstructorStandingsResponseSerializer`
    - Example: `{"year":2024,"constructors":[{"position":1,"constructor_name":"Red Bull Racing","points":860}],"readiness":{...}}`

---

**General Rules & Examples**

- Authentication header example:

```http
GET /api/auth/me/ HTTP/1.1
Host: api.example.com
X-API-Key: 00000000-0000-0000-0000-000000000000
```

- Response example (success):

```json
{
  "tier": "free",
  "request_count": 12,
  "readiness": { "can_proceed": true, "available_data": ["season_breakdown"] }
}
```

- Driver identifier rules: pass 3-letter FIA codes (exactly 3 alphabetic chars) or provider-specific Jolpica ids (strings). Alphabetic codes will be uppercased before lookup. Invalid alpha codes (length != 3) return a `readiness` payload with `can_proceed=false` and a 200 status.

- Rate limiting and throttling: enforced per-tier. Use `/api/auth/me/` to inspect live token counts.

---

If you want, I can:

- Expand this file with every route from `api.results` and other modules (I can scan and add them).
- Generate OpenAPI/Swagger from the running project (server already exposes `/api/schema/` and `/api/docs/`).
