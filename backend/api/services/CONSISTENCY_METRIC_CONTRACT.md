# Consistency Metric Contract

Status: Draft for implementation
Version: consistency_v1
Scope: Race session consistency metrics for backend persistence and API delivery

## 1) Purpose

Define a deterministic, testable contract for driver consistency metrics so backend computation, storage, and frontend rendering stay aligned.

This contract produces two metrics per driver per race:

- Raw consistency: lap-time standard deviation over filtered valid laps
- Normalized consistency: standard deviation of residuals after stint/compound context normalization

Telemetry-heavy operations are out of scope.

## 2) Session and Data Scope

- Default session: Race (R)
- Unit of computation: One race, all participating drivers
- Required source columns per lap row:
  - driver_code (string)
  - lap_number (int)
  - lap_time_seconds (float)
  - stint_number (int, nullable)
  - compound (string, nullable)
  - is_pit_in_lap (bool)
  - is_pit_out_lap (bool)
  - track_status_code (string or int, nullable)

Optional source columns:

- position
- constructor_name
- weather fields

## 3) Canonical Preprocessing Rules

Apply rules in this exact order.

### Rule A: Keep valid timed laps

- Keep only rows where lap_time_seconds is finite and > 0.

### Rule B: Exclude lap 1

- Exclude lap_number == 1.

### Rule C: Exclude pit transition laps

- Exclude rows where is_pit_in_lap == true or is_pit_out_lap == true.

### Rule D: Exclude SC and VSC laps

- Exclude rows where track_status_code indicates Safety Car or Virtual Safety Car.
- Mapping may vary by source. Implementation must normalize to:
  - GREEN
  - YELLOW
  - SC
  - VSC
  - RED
- Exclude SC and VSC only.

### Rule E: Robust outlier clipping (per driver)

- Compute median lap time m and MAD per driver on remaining laps.
- Scale estimate: sigma_robust = 1.4826 \* MAD
- Exclude lap i if abs(t_i - m) > 3.5 \* sigma_robust
- If MAD == 0, skip Rule E for that driver.

### Rule F: Minimum valid laps gate

- If valid_lap_count < 8 after A-E:
  - Do not compute metrics
  - Mark driver as insufficient_data
  - Exclude from ranking

## 4) Grouping Rules for Normalization

Normalize by local race phase so strategy effects do not dominate consistency.

Primary grouping key:

- (driver_code, stint_number)

Compound guardrail:

- If compound changes inside same stint_number, split into subgroup segments by contiguous compound runs.

Minimum subgroup size:

- Minimum 3 laps per subgroup.
- If subgroup has < 3 laps:
  - Merge with nearest adjacent subgroup for same driver by lap_number distance.
  - If merged subgroup still < 3 laps, exclude those laps from normalized metric only.
- Excluded normalized laps still count for raw metric.

## 5) Metric Definitions

For a driver d with N valid laps after A-E:

Raw metric:

- mu_raw = mean(t_i)
- raw_stddev_seconds = sqrt((1/N) \* sum((t_i - mu_raw)^2))

Normalized metric:

- For each lap i in subgroup g(i), compute subgroup mean mu_g(i)
- Residual r_i = t_i - mu_g(i)
- Let M be number of laps included in normalized computation
- normalized_stddev_seconds = sqrt((1/M) \* sum(r_i^2))

Scale-free optional metric:

- normalized_cv = normalized_stddev_seconds / mu_raw

All numeric outputs rounded to 4 decimal places unless otherwise stated.

## 6) Ranking Rules

Eligible drivers: valid_lap_count >= 8 and normalized metric computed.

Sort keys (ascending unless stated):

1. normalized_stddev_seconds
2. -valid_lap_count (more valid laps wins)
3. raw_stddev_seconds
4. race_position (lower wins, nullable last)
5. driver_code (stable final tie-break)

## 7) Output Schema (Per Driver)

Required fields:

- season (int)
- round (int)
- session (string)
- driver_code (string)
- formula_version (string, fixed: consistency_v1)
- valid_lap_count (int)
- excluded_lap_count (int)
- excluded_by_reason (object map string->int)
- raw_stddev_seconds (float|null)
- normalized_stddev_seconds (float|null)
- normalized_cv (float|null)
- consistency_rank (int|null)
- insufficient_data (bool)
- computed_at (ISO datetime string)

Optional fields:

- avg_pace_seconds (float|null)
- race_position (int|null)
- qualifying_position (int|null)
- value_index (float|null)

Example:
{
"season": 2024,
"round": 5,
"session": "R",
"driver_code": "VER",
"formula_version": "consistency_v1",
"valid_lap_count": 42,
"excluded_lap_count": 8,
"excluded_by_reason": {
"lap1": 1,
"pit_transition": 2,
"sc_vsc": 3,
"outlier": 2
},
"raw_stddev_seconds": 0.6123,
"normalized_stddev_seconds": 0.2914,
"normalized_cv": 0.0030,
"consistency_rank": 2,
"insufficient_data": false,
"computed_at": "2026-04-05T12:30:00Z"
}

## 8) Determinism and Idempotency

- Given identical input rows and order-insensitive grouping, outputs must be identical.
- Sorting input rows by lap_number before processing is mandatory.
- Re-running computation for same race must overwrite persisted values for the same keys.

Persistence key for per-race metrics:

- (race_id, driver_code, season_aggregate=false)

## 9) Error and Fallback Behavior

Hard errors (fail race computation):

- Missing required source columns
- No drivers found
- All drivers invalid due to malformed times

Soft failures (driver-level only):

- Driver has < 8 valid laps
- Driver subgroup merge failed for normalization

Soft-fail drivers remain in payload with:

- insufficient_data = true
- metrics = null

## 10) Test Contract (Must Pass Before Merge)

### T01 Basic deterministic output

Input: fixed lap set for one driver
Assert: exact raw_stddev_seconds and normalized_stddev_seconds values

### T02 Excludes lap 1

Input includes lap 1
Assert: excluded_by_reason.lap1 increments

### T03 Excludes pit in/out

Input includes pit in and pit out laps
Assert: both excluded before metrics

### T04 Excludes SC and VSC laps

Input includes track_status SC and VSC
Assert: excluded_by_reason.sc_vsc increments

### T05 MAD outlier clipping

Input includes one extreme lap
Assert: outlier excluded and metrics stable

### T06 MAD zero branch

Input has identical lap times
Assert: no outlier clipping crash, stddev 0 where applicable

### T07 Minimum valid laps gate

Input with < 8 valid laps
Assert: insufficient_data true and metrics null

### T08 Subgroup split by compound change

Input same stint number with compound switch
Assert: normalization uses separate contiguous compound subgroups

### T09 Subgroup min-size merge

Input subgroup size 1-2 laps
Assert: merged if possible, else excluded from normalized set only

### T10 Ranking tie-breakers

Input two drivers with same normalized metric
Assert: ordering follows lap count, then raw stddev, then race_position

### T11 Idempotent rerun

Run computation twice with same input
Assert: exact same outputs

### T12 Output schema completeness

Assert all required fields present and correctly typed

## 11) API and DB Integration Requirements

For API responses that include consistency:

- Expose formula_version and excluded_by_reason for transparency.
- Expose both raw and normalized metrics.

For DB storage in driver_metrics:

- Persist normalized_stddev_seconds as canonical metric.
- Persist raw_stddev_seconds and normalized_cv as supporting fields.
- Persist valid_lap_count and excluded_lap_count for auditability.

## 12) Non-Goals for v1

- Compound-specific weather normalization
- Fuel-corrected pace models
- Position-adjusted traffic corrections
- Cross-race Bayesian shrinkage

These can be added under future formula versions (consistency_v2+).
