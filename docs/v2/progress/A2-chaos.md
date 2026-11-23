# A2 chaos progress

## Phase 2a: labels (models, DNF mapping, build_labels, CircuitProfile seed, Mendeley script)

Status: done, awaiting review.

Files (all under `backend/api/chaos/` unless noted): `models.py` (CircuitProfile, RaceEventLabel), `migrations/0001_initial.py`, `labels.py` (pure logic), `tasks.py` (`build_labels`, `label_aggregates`), `circuits.py`, `data/dnf_status_map.yaml` (version "1"), `data/circuits.yaml`, `scripts/crosscheck_mendeley.py`, `tests/test_labels.py`, `NEEDS.md`; this file.

Tests: full suite 334 passed, 2 failed (the known `test_driver_endpoints` readiness pair), 16 skipped. Baseline 295/2/16, so +39, no new failures. Migration applies on SQLite.

Design choices
- Only CircuitProfile and RaceEventLabel now. FeatureSet, ModelRun, ChaosPrediction wait for 2b/2c (nothing reads them yet; avoids migration churn).
- RaceEventLabel rows are events (lap, driver, team, type, source, end_lap, mapping_version, detail JSON). Race, driver-race and 5-lap-window targets are NOT separate tables: `aggregate_labels()` derives them (window = event's start lap, 1-based, 5 laps); `label_aggregates(y, r)` reads them from the DB. One source of truth, 2b calls it.
- Types: `sc`, `vsc`, `red_flag`, `dnf_<group>`, `slow_stop`, `unlucky_stop`. Targets: sc_vsc_red; dnf_mechanical = engine+gearbox+hydraulics+electrical+brakes; dnf_incident = accident+collision; `dnf_other` feeds neither target (roll-up is in the YAML).
- `build_labels` replaces that race's rows in one transaction (idempotent), only reads session "R", returns `{status: no_results}` without stored results, and returns unmapped statuses and SC cross-check mismatches (also logged).
- Neutralisations: the track-status stream is walked once (so red then SC restart and SC, green, SC give the right counts). Cross-check with race-control text counts per type; source becomes `track_status+race_control` when counts agree, else `track_status` plus a mismatch note. No track status at all: race control alone.
- Slow stop uses PIT-LANE time (PitInTime to PitOutTime, what PitStopData stores). Stationary time is not stored. Threshold = season p90 over all stored R stops, needs at least 20 stops else no slow labels; stops on a red-flag lap are never slow. Unlucky = no earlier SC/VSC/red interval covers the stop lap, and an SC or VSC starts 0 to 2 laps later (red excluded, per plan).
- DNF lap = laps completed + 1. Driver code resolved from PitStopData/PositionData number-to-code; unresolved becomes `#<number>`.
- CircuitProfile keyed by `slug` with FastF1 `locations` aliases; `circuit_key` nullable (MultiViewer key is only learnable from a TrackGeometry row). length/corners come from the newest TrackGeometry for the key (read-only import). Seed has circuit TYPE only for 31 circuits (marked `verified: false`); wall proximity, overtaking index, elevation are null by design.

Findings about stored data (affect 2b)
- `TrackStatusData.lap_number` is almost certainly always None: `TrackStatusExtractor` reads a `Lap` column that FastF1's `track_status` does not have, and it drops `Time`. Labels therefore take laps from race-control messages (IncidentData has real laps). If a message is missing, the event keeps `lap=None`: it counts at race level but not in a window. Real fix (outside my files): store the track-status `Time` and map to lap via the lap table.
- PositionData is sampled every 5 laps, so it cannot give per-lap track status.
- Status vocabulary: no populated DB in the worktree, so the YAML is built from the Ergast/Jolpica status table (FastF1 uses the same strings), not from stored rows. Check on the VM.

Unmapped statuses (fall to `other`, flagged `detail.unmapped` unless generic): anything not in the YAML. Known mapped-to-`other` on purpose: Suspension, Steering, Throttle, Wheel/Wheel nut, Tyre, wings, Retired, Mechanical, Technical, Withdrew, Fire. Seen unmapped in real data: none yet (DEFERRED, needs data).

DEFERRED
- Mendeley SC cross-check run (needs CSV download + populated 2022-2025 labels). Script and its pure compare logic are written and tested on a synthetic frame; dataset column names were never inspected, so they are CLI args with auto-detect.
- Verifying the DNF mapping and seed against stored real data.

Open questions
- Should suspension/steering/throttle/etc. count as mechanical? The plan fixes eight groups, so they sit in `other` and feed no target. A ninth group `mechanical_other` would fix it.
- Season p90 of lane time is confounded by pit-lane length per circuit (Monaco vs Baku). Plan says season percentile; per-circuit percentile would be fairer. `detail` stores duration and threshold so 2b can recompute.

Needs from orchestrator
- Add `pytest==9.0.3` and `pytest-django==4.12.0` to requirements (carried from A1).
- Wire `build_labels.delay(year, round)` after race ingestion / in the Wednesday beat chain (task name `api.chaos.tasks.build_labels`, queue by module).
- Optional, outside my files: persist track-status `Time` and a lap mapping so SC laps do not depend on race-control text.

## Phase 2b: features + Beta-Binomial baseline (also: coordinator answers applied to 2a)

Status: done, awaiting review. Rebased on v2/integration (e08050c) first.

2a follow-ups: DNF mapping version "2" (new `chassis` group: suspension, steering, throttle, wheel, wheel nut, wings, fire, plus generic Mechanical/Technical; counted in `dnf_mechanical`; Retired, Withdrew, unknowns stay `other`). `circuits.link_circuit_keys(year)` fills a null `CircuitProfile.circuit_key` (and length/corners) from the trackmap `built:{year}:{round}` cache pointer matched to the schedule location. Not wired to run automatically.

Files (`backend/api/chaos/`): `models.py` (+FeatureSet, ModelRun, ChaosPrediction), `migrations/0002_*`, `history.py` (DB loader + running Beta-Binomial tally), `features.py` (tables), `baseline.py`, `tasks.py` (+`build_features`, `run_baseline`, `features_dir`), `tests/test_features_baseline.py`.

Tests: full suite 354 passed, 2 failed (known pair), 16 skipped. Merged baseline 334/2/16, so +20 (all chaos), no new failures.

Design choices
- Three Parquet files per build (scopes `race`, `driver`, `lap_window`), one FeatureSet row each. Version is derived from the data (`f<feat>-m<mapping>-n<races>-<lastYear>R<lastRound>`), so reruns overwrite the same files and rows (tested). `CHAOS_FEATURES_DIR`, else `<DATA_DIR or ~/.f1_control_room>/chaos_features`: outside the repo.
- Leakage control: races are walked in (year, round) order; a race's rows are built from the tally BEFORE it is added (`Counts.update` after). Tests change a race's labels and prove all rows of that race and earlier are unchanged, while later rows do change.
- Columns: FeatureSet.meta lists `feature`, `id` (id_* keys, strings allowed, not for the model), `target` (y_*), `live_only`. All feature and target columns are numeric (categoricals: circuit type one-hot; team/driver identity is carried by their historical rates, not ids). Limits checked (60,000 rows, 100 columns); actual sizes are a few thousand rows, ~50 columns.
- Features: era flag (>=2022), circuit traits (NaN when unknown), weather means of the race, grid, pit-lane start, window index/position, first-window flag, hierarchical posterior rates at each level (global, type, circuit; team, driver), `circuit_lane_rel` (circuit median pit-lane time over global median, earlier races only; coordinator's lane-length correction).
- `live_restart_flag` (an SC or red ends inside the window) uses the race's own events, so it is only valid for in-race rolling prediction. Marked `live_only`; a pre-race model must drop it. Same caveat for the race's own weather (forecast stand-in).
- Baseline: Beta-Binomial, uniform root prior, each level's prior = parent posterior mean x strength 8, updated by that level's counts. Race and lap_window: global, circuit type, circuit (window scope stratified by first window vs rest). Driver scope: global, team, driver; targets dnf_mechanical, dnf_incident, slow_stop, unlucky_stop (sc_vsc_red is not a driver trait). Trial = one race / one driver-race / one window; success = at least one event. probability = posterior mean; p10/p90 = Beta quantiles of the rate, widened if a very skewed posterior put its mean outside (contract p10 <= p <= p90).
- `run_baseline(year, round)` uses races strictly before the target (honest backtest for past races, tested by deleting the future). Upcoming race (no result row): circuit from the schedule, field from the latest race, windows from the median past length. One ModelRun per (model, race) via new `race_key` field, predictions replaced on rerun.

DEFERRED: no backtest metrics or calibration in ModelRun yet (plan 2c/evaluation). No `ModelRun.calibration` content. Nothing DEFERRED-VM.

Open questions
- Prior strength 8 is one number for every level; should be tuned in the leave-one-season-out backtest.
- Race-scope slow_stop and unlucky_stop will sit near 1 and near a high rate (at least one in 20 drivers); more informative as per-driver or per-window rates.
- Window features use the circuit's per-window rate only by first-vs-rest stratum, not by lap-in-race position; fine for a baseline.

Needs from orchestrator
- Chain `build_labels`, `build_features`, `run_baseline` in the beat task (each is its own task; build_features takes no args and rebuilds all).
- A `.gitignore` entry is not needed (files go outside the repo); set `CHAOS_FEATURES_DIR` to the `/features` volume in compose. pyarrow 21.0.0 and scipy are already in requirements; no new deps.
