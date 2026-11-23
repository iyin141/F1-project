# chaos dependencies

Phase 2a adds none (PyYAML, pandas, numpy are already in `backend/requirements.txt`).
Test tooling not in requirements: `pytest==9.0.3`, `pytest-django==4.12.0`.
Later phases (not installed here): `structured-data-models` + `torch` (ml image only, `ml_tasks.py`), `lightgbm` (backtest reference).

## Phase 2c (ml image only, not installed in the web/default image)
`structured-data-models==0.3.0` (import `sdm`), `torch>=2.7` (CPU wheel on aarch64). `scikit-learn` (isotonic) is already pinned. Weights: `hf download nvidia/Kumo-Tabular --revision v1.0.1 --include "config.json" "small/*"`, worker env `HF_HUB_OFFLINE=1` (KUMO_SETUP.md).
Env read by the tasks: `CHAOS_ENABLE_KUMO`, `CHAOS_KUMO_SIZE` (small), `CHAOS_KUMO_DEVICE` (cpu), `CHAOS_KUMO_BAGS` (5), `CHAOS_KUMO_ESTIMATORS` (4), `CHAOS_FEATURES_DIR`.
