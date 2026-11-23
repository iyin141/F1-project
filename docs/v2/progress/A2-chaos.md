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
