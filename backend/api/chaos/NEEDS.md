# chaos dependencies

Phase 2a adds none (PyYAML, pandas, numpy are already in `backend/requirements.txt`).
Test tooling not in requirements: `pytest==9.0.3`, `pytest-django==4.12.0`.
Later phases (not installed here): `structured-data-models` + `torch` (ml image only, `ml_tasks.py`), `lightgbm` (backtest reference).
