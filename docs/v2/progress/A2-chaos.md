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

## Phase 2c: Kumo path, calibration, pipeline chain

Status: done, awaiting review. Rebased on v2/integration (7ab8d7f) first.

Files (`backend/api/chaos/`): `ml_tasks.py` (new), `tasks.py` (+`build_pipeline`, `run_chaos_pipeline`, `refresh_chaos`, `pipeline_targets`), `history.py` (+`target_race`, `outcome`; `run_baseline` now uses `target_race`, same behaviour), `tests/test_kumo_pipeline.py`, `tests/test_features_baseline.py` (fixture now seeds number-to-code rows so driver labels line up with results), `NEEDS.md`.

Tests: full suite 372 passed, 0 failed, 16 skipped (merged baseline 355). No torch in the environment.

Design choices
- Interface `TabularModel` (fit, predict -> P(y=1), clear). `KumoAdapter` wraps `sdm.models.KumoTabular(task="classification", size, device).eval()` per KUMO_SETUP and is the ONLY place torch/sdm are imported (inside `__init__`). `model_factory` is the patch point; tests inject a fake. A subprocess test proves importing `api.chaos.tasks` and `api.chaos.ml_tasks` after `django.setup()` loads neither torch nor sdm.
- `run_kumo(year, round)`: one fit per (scope, target) (14 targets across race/driver/lap_window; driver scope excludes sc_vsc_red). Context = Parquet rows of the newest FeatureSet filtered to races strictly before the target (recomputed from history if the file is missing); query = the target race's rows built from that same history (so an upcoming race with no result row works). `live_only` columns dropped; feature columns <= 100; context sampled to 50,000 if larger. A single-class context skips that target and records it in `ModelRun.metrics.skipped`.
- p10/p90: Kumo regression quantiles are not used because every stored target is binary (the slow-stop duration is only in `detail`). Instead the band is p10/p90 over K=5 fits on random 80% context subsamples (context bagging), with the mean as the probability. This measures sensitivity to the context sample, not a full predictive interval; labelled `interval: context_bagging_p10_p90` in the ModelRun. Upgrade path: regression quantiles on lane-time, or conformal bands after the VM backtest.
- `calibrate_and_store(year, round)`: reads the race's RAW run (`kumo_tabular`), fits `IsotonicRegression` per (scope, target) on RAW predictions of earlier finished races vs their outcomes (needs >= 200 points and both classes), else identity. Result is a separate ModelRun `kumo_tabular_calibrated` with `calibration` JSON per key (method, n, 10-bin reliability, ECE, raw ECE) and `metrics.calibrated` true/false. Raw and calibrated stay separate so backtest calibration never trains on calibrated output. The monotone map applied to p, p10 and p90 keeps p10 <= p <= p90.
- Backtest predictions exist only if `run_kumo` has been run for past races; nothing runs that automatically. A backfill loop over past races (oldest first) is a VM operation: until then calibration is identity and flagged.
- Pipeline: `build_pipeline(y, r)` = chain of immutable signatures build_labels, build_features, run_baseline, then run_kumo and calibrate_and_store only when `CHAOS_ENABLE_KUMO` is truthy (1/true/yes/on). The ml steps are referenced by task name, so the default process never imports them; routes send `api.chaos.ml_tasks.*` to `ml`. `run_chaos_pipeline` queues the chain. `refresh_chaos` runs it for the latest race with a stored result and for the next scheduled round (same season round+1, else next season round 1, only if the schedule has it). The pipeline is data-driven, not clock-driven.

Suggested beat schedule: `refresh_chaos` weekly in season, Monday 06:00 UTC (labels and features after the race results are stored; refreshes the just-finished race) and Wednesday 06:00 UTC (predictions for the coming weekend). Both are idempotent, so running it twice a week or outside the season is safe. If result ingestion lags on Monday, the Wednesday run catches it.

DEFERRED-VM (not attempted): installing torch/sdm, downloading weights, real Kumo inference, aarch64 smoke test and timing. Specifically unverified: the layout of `KumoTabular.predict` output (the adapter's `_class1` tolerates (n,), (n,1), (n,2) and TableTensor-like objects), whether `fit` accepts NaN features and the `[R,1]` long label shape for our data, per-fit time with ~14 targets x 5 bags (70 fits per race; if too slow, set `CHAOS_KUMO_BAGS=1`), and `KumoRelational`.
A short local CPU check that would settle the design question "is bagging affordable and is NaN accepted": on the VM, run the KUMO_SETUP smoke script, then `fit` on one real driver-scope table (about 4,000 rows x 40 columns with NaNs) and time 5 fits.

Open questions
- Context bagging costs 5x the fits; if the VM shows Kumo is slow, drop to bags=1 and widen bands with the baseline Beta band instead.
- Calibration is pooled over entities per (scope, target); the data is small, so per-circuit-type calibration is not worth it yet.

Needs from orchestrator
- Beat entry for `api.chaos.tasks.refresh_chaos` (schedule above); `CHAOS_ENABLE_KUMO=1`, `HF_HUB_OFFLINE=1` and the ml-image deps from NEEDS.md on the ml worker only.

## Phase 2d: evaluation (leave-one-season-out backtest)

Status: done, awaiting review. Rebased on v2/integration (7d5b51a) first.

Files (`backend/api/chaos/`): `backtest.py`, `metrics.py` (brier, log-loss, AUC, reliability/ECE; `ml_tasks.reliability` now imports from it), `management/commands/chaos_backtest.py`, `history.Counts(m)` and `features.build_tables(no_update=, m=)` (defaults unchanged), `tests/test_backtest.py`, `NEEDS.md`.

Tests: full suite 391 passed, 0 failed, 17 skipped (previous 372/0/16). The extra skip is `test_lightgbm_adapter_when_installed` (lightgbm is not in this venv: pip failed with an SSL error; install was not retried). The LightGBM adapter is therefore untested against the real library.

Design choices
- Leakage control (the hard part of leave-one-season-out with history features): one feature pass over all races in time order; races of the held-out season S are built from history but never ADDED to it. So no training row (even in later seasons) carries S in its history, and S rows only know earlier training races. Tests: changing every label of S leaves every feature row of every season identical; a control without the guard shows later seasons do change; the tuned prior and the training rows ignore S labels.
- Identical splits: every model gets the same train and held-out rows from that single table. A (scope, target, season) cell whose training labels are one class is skipped for ALL models.
- Prior strength: grid (2, 4, 8, 16, 32), chosen per held-out season by sequential baseline Brier over rows of the other seasons only. The chosen value per season is in the report (`prior_strength`) and in `ModelRun.metrics`. All models use the features built with that value.
- Models: `beta_binomial` = the baseline's own posterior columns in the table (same numbers `B.predict` produces); `lightgbm` (CPU, small trees); `kumo` through `TabularModel` / `ml_tasks.model_factory`, one fit per cell, no bagging. Missing dependency: skipped and named in `skipped_models`, command prints `SKIPPED <model>: <reason>`.
- Features for the learned models drop raw `year` (cannot transfer to a held-out season; `era_2022` carries the regulation change) and all `live_only` columns. Kumo/LightGBM use the same columns as production otherwise.
- Metrics per (scope, target): per held-out season and pooled (`overall`, which also has the 10-bin reliability and ECE). AUC is None when a cell has one class. Saved in `ModelRun(model="backtest", race_key="loso-<first>-<last>")` (`metrics` = whole report, `calibration` = reliability per model and cell) and written as JSON and CSV (one row per model, scope, target, season, "all" = pooled) to `<CHAOS_FEATURES_DIR>/backtest/loso_<first>-<last>.{json,csv}`.
- `--backfill-kumo`: after the report, runs the production `run_kumo` (expanding window, context = earlier races) for every race in the selected seasons. That stores the raw per-race predictions `calibrate_and_store` fits isotonic on, so one command builds the calibration data. Tested with a fake model (every race with history gets a raw ModelRun, and `calibrate_and_store` then runs on them).
- Sanity check: `sc_rates` (SC race share per circuit, plus any-neutralisation share) and `canada_check` (Canada near 60%, tolerance 15 points, needs at least 5 races else "not enough data"). Printed as a report line and stored in the report. Tested on synthetic data.

DEFERRED (no populated DB here). Exact VM commands (from the repo root, ml image; service names per KUMO_SETUP.md, adjust to the compose file):
1. Weights and deps once: see KUMO_SETUP.md Option B; `pip install lightgbm` in the ml image; worker env `HF_HUB_OFFLINE=1`.
2. Circuit seed and key links:
   `docker compose --profile ml run --rm worker-ml python manage.py shell -c "from api.chaos.circuits import populate_circuit_profiles, link_circuit_keys; print(populate_circuit_profiles()); [print(y, link_circuit_keys(y)) for y in range(2018, 2026)]"`
3. Labels for every stored race, then features:
   `docker compose --profile ml run --rm worker-ml python manage.py shell -c "from api.models import RaceResultData; from api.chaos.tasks import build_labels, build_features; [build_labels(r.year, r.round_number) for r in RaceResultData.objects.filter(session='R').order_by('year','round_number')]; print(build_features())"`
4. Backtest with the calibration backfill (CHAOS_FEATURES_DIR set to the /features volume):
   `docker compose --profile ml run --rm worker-ml python manage.py chaos_backtest --seasons 2018-2025 --models beta_binomial,lightgbm,kumo --backfill-kumo`
   Quick variant first (no Kumo, seconds): `... chaos_backtest --seasons 2018-2025 --models beta_binomial,lightgbm`.
5. Read `loso_2018-2025.csv` / `.json` in the features volume, check the Canada line, then run `refresh_chaos` (or the pipeline for one race) with `CHAOS_ENABLE_KUMO=1`.
Nothing in this phase has been run on real data: no real Brier, AUC or ECE numbers exist yet.

Open questions
- Seasons 2018-2021 have no ground-effect cars; `era_2022` is in the features, but a per-era report split (pre/post 2022) is not separate from the per-season rows (easy to aggregate from the CSV).
- The SC label quality depends on race-control text for laps (see 2a findings); run the Mendeley cross-check script first on the VM before trusting SC scores.
- The prior grid is shared by all scopes; per-scope tuning is a one-line change if the report shows different optima.

Needs from orchestrator
- Add `lightgbm` to the ml image only. Nothing else.

## Phase 2e: endpoints

Status: done, awaiting review. Rebased on v2/integration (3ff422c) first.

Files (`backend/api/chaos/`): `urls.py`, `views.py`, `service.py` (payloads), `serializers.py` (schema shapes), `cache.py`, `signals.py` + `apps.py` `ready()`, `tasks.py` (+`populate_chaos`, `pipeline_task_key`, `mark_pipeline_done`), `tests/test_endpoints.py`.

Tests: full suite 427 passed, 0 failed, 16 skipped (previous 391/0/17: +36 chaos, and the lightgbm test now runs instead of skipping).

Routes (under `/api/chaos/`): `races/<y>/<r>/`, `races/<y>/<r>/drivers/`, `races/<y>/<r>/laps/?target=`, `circuits/<slug>/history/`, `drivers/<code>/profile/`, `model/`.

Design choices
- Auth, permission and throttle are the project defaults, not redeclared; a test asserts the class lists equal `AnalysisTelemetryAPIView`'s, and that no-key requests get the same status as an existing analysis view. `endpoint_type="chaos"` is not in `ENDPOINT_COSTS`, so cost 1 (same as `track_map`). drf-spectacular: explicit operation ids, parameters and response shapes; generation emits no chaos warnings (I renamed my pending serializer to `ChaosPending` because `Pending` collided with trackmap's component name).
- Model choice, never silent: default order is the calibrated Kumo run, then the Beta-Binomial baseline (raw Kumo is served only when asked for). Every response has a `model` block: model, size, run id, calibration state (`isotonic`, or `identity (too little backtest history ...)`, or none), `is_fallback` and a `fallback_reason` when the baseline is served by default. `?model=auto|kumo_calibrated|kumo|baseline`; a named model with no run for that race is 404, never a substitute; invalid value is 400.
- Chaos Index = sum over three "disruptive" targets (`sc_vsc_red`, `dnf_mechanical`, `dnf_incident`) of their expected event counts from the SAME run: sc_vsc_red = sum of the lap-window probabilities, DNF targets = sum of the per-driver probabilities. If a scope is missing for a target (for example Kumo skipped it), the race-level at-least-one probability is used and `expected_events[t].source` says so. Slow and unlucky stops are shown but not in the index. `chaos_index_band` = sums of per-entity p10/p90, labelled as a conservative, non-joint band. A test recomputes the index from the stored calibrated predictions.
- Factors: for each race target, predicted probability vs the circuit-type average (global if the type is unknown), plus "k of n past races at this circuit"; top 5 by size of the difference, with a text line.
- No predictions yet: 202 `{status: pending, task_key: chaos:<y>:<r>, detail}` and `TaskManager.enqueue_if_needed(task_key, populate_chaos, y, r)`, the same shape as trackmap's mini-sectors. `populate_chaos` (task_key first, like populate_*) launches the pipeline chain and leaves the TaskRecord `running`; `run_baseline` marks it `complete` when predictions exist, so repeated requests do not requeue. If no race is stored before the requested one there is nothing to predict from: 404, not an eternal 202. Bad year/round (year 1950-2100, round 1-40) is 400.
- Circuit history, driver profile and model page read stored labels and ModelRuns. The driver profile is labelled as tendencies (shrunk toward team and field, p10/p90 widen with few races). Unknown circuit slug or driver code with no stored races: 404; code not 3 letters: 400. `model/` returns the latest run per model with its calibration table and the latest backtest (pooled metrics, 10-bin reliability) and is an empty 200 when nothing has run.
- Cache: the `default` alias (Redis 1, the app cache; `telemetry_cache` is reserved for telemetry). Keys carry a version counter bumped via `transaction.on_commit` whenever a `ModelRun` is saved, which invalidates all chaos responses at once (the predictions of the same atomic block are already written by then). TTLs: race, drivers, laps 6 h (they only change with a new run); circuit history and driver profile 1 h; model page 10 min. A cache outage degrades to uncached, never an error (tested). In the test settings the cache is in-memory, so tests clear it.

LightGBM
- Installed `lightgbm==4.7.0` (CPU wheel) in my venv; `test_lightgbm_adapter_when_installed` now runs and passes. Pin `lightgbm==4.7.0` in the ml image (pip failed several times with SSL errors on this network before it went through).

DEFERRED / not verified
- Everything runs on synthetic data; real response sizes and timings are unmeasured. The `laps` total length for an upcoming race is the median of past races (stated in `meta.total_laps_note`).
- `TASK_TIER_MAP` has no entry for `populate_chaos` (defaults to tier3, 90 s lock TTL, which is right for the queue; the real work is the chain). Suggest `"populate_chaos": ("tier3_medium", 120)`.

Open questions
- Should `model/` be public-facing in the UI as is, or trimmed (it can carry many reliability cells)?

Needs from orchestrator
- Optional `TASK_TIER_MAP` entry above; optional `ENDPOINT_COSTS["chaos"]` if cost 1 is not wanted.

## Phase 2f: circuit identity fixes (from API_TEST_2026-11-24)

Status: done, awaiting review. Rebased on v2/integration (c1e7e2c) first.

Root causes (from reading the code; the Neon copy itself was not available to me)
- The seed was only used if someone ran `populate_circuit_profiles`, which nothing called: with no `CircuitProfile` rows every race came out circuit `unknown` with empty traits.
- Matching used only the schedule `location`, exact. The stored schedule also has the event `name`, and 2026 adds Madrid ("Spanish Grand Prix" there) and renames Barcelona's event.
- `link_circuit_keys` was never wired, and could not have been hooked on the trackmap cache pointer from a signal (the pointer is written after the geometry row is saved).

Changes (`backend/api/chaos/`)
- `circuits.py`: `CircuitIndex` (match a schedule row to a circuit) and `load_index()` = seed file overlaid with stored `CircuitProfile` rows, so identity and circuit type work even before any row is stored. Matching order: `location` exact, event `name` exact, name without "Grand Prix", then a whole-word alias (5+ letters) inside either. Text is normalised (case, accents, punctuation). An alias shared by two circuits never matches. Country is deliberately NOT used (Italy, Spain, USA have several circuits; a wrong silent match is worse than a logged miss).
- `data/circuits.yaml` v2: 32 circuits (Madrid added, hybrid), aliases extended with FastF1 location variants and event names for 2018-2026. Add an alias plus a case in `tests/test_circuits.py` when the log shows an unmatched circuit.
- Linking, automatic in two places:
  1. `post_save` signal on `TrackGeometry` (created only) in `chaos/signals.py`, run on commit, errors logged not raised. Chosen over editing trackmap (another branch owns it) and over the cache pointer (written after the save). It reads the race that built the geometry from `TrackGeometry.source` ("<year> R<round> ..."), looks that round up in the stored schedule, matches the circuit, sets `circuit_key`, length and corners (creating the profile row from the seed if needed). Never overwrites a different existing key (warns). The coupling to the `source` format is covered by a test that runs the real `build_track_geometry`.
  2. Start of `build_features`: `populate_circuit_profiles()` (seed rows), then `link_circuit_keys()` backfill over every stored `TrackGeometry` and every year's cache pointers (this also covers a geometry reused from another year, which does not fire the signal). The task result has `circuit_links_made` and `unmatched_circuits`.
- Unmatched circuits are logged loudly: `[chaos] UNMATCHED CIRCUIT <year> R<n> (<why>)` once per process per race (no schedule row, or location/name shown), `build_features` logs a summary warning with the races, and returns them. `race_meta` keeps a usable identity when unmatched (the location text, `unknown` only if the schedule has no row) and `circuit_matched=false`.
- `GET /api/chaos/circuits/`: slug, name, type, aliases, circuit_key, length, corners, `stored` (profile row exists). `circuits/<slug>/history/` now works for any listed slug (empty `races` until data exists); an unknown slug is 404 with a pointer to the list.

Tests: new `tests/test_circuits.py` (one case per alias in the seed, as location and as event name; 33 realistic 2022-2026 location/name pairs; ambiguous and unknown; race_meta and log text; unmatched summary in build_features; signal link; link via a real track-map build; conflict and unmatched geometry; backfill idempotence; list endpoint and auth). Suite (rebased on ea33879, FastF1 3.9.2 installed) excluding `api/assistant`, whose tests need the rag requirements not installed per instructions: 573 passed, 0 failed, 17 skipped (about 6 minutes on this machine).

DEFERRED: running against the real 2026 schedule on the VM/Neon: if the log still prints `UNMATCHED CIRCUIT 2026 R5 (location=... name=...)`, the printed text is exactly what to add as an alias.
Needs from orchestrator: none.
