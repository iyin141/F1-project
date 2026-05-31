# FASTF1 Session Capture Instructions

To create a deterministic FastF1 session fixture for parity tests, run these steps locally where FastF1 can access the session telemetry data.

1. Create a small script `scripts/capture_fastf1_session.py` in the repo root:

```python
import pickle
import fastf1

# Example: capture 2023, round 1, Race session
year = 2023
round_number = 1
session_name = 'R'  # 'R', 'Q', 'FP1', etc.

session = fastf1.get_session(year, round_number, session_name)
session.load()  # may download telemetry; ensure network available

with open('backend/api/fixtures/fastf1_session_2023_R.pkl', 'wb') as f:
    pickle.dump(session, f)

print('Saved session fixture to backend/api/fixtures/fastf1_session_2023_R.pkl')
```

2. Run the script in a Python environment with `fastf1` installed:

```bash
python scripts/capture_fastf1_session.py
```

3. Use the resulting pickle file in tests by loading it and passing the `session` object to extractor helpers, e.g.:

```python
import pickle
from api.results.services.race import get_race_session_results

with open('backend/api/fixtures/fastf1_session_2023_R.pkl', 'rb') as f:
    session = pickle.load(f)

rows = get_race_session_results(session)
```

Notes:

- FastF1 data may change across releases; pin `fastf1` and related dependencies in your test environment for determinism.
- If pickling large session objects is problematic, consider extracting the minimal data your extractor consumes (laps, drivers) and storing that as JSON.
