# Deployment checklist — f1-project backend

Follow these steps to deploy the backend safely and validate the persistence parity and auth hardening changes.

1. Pre-deploy checks

- Ensure CI passes on the branch (see `.github/workflows/ci.yml`).
- Confirm `INTERNAL_API_KEY` is provisioned for both web and worker environments.

2. Set environment variables

Unix (bash):

```bash
export INTERNAL_API_KEY="<long-random-key>"
export DJANGO_SETTINGS_MODULE=f1_project.settings
```

Windows (PowerShell):

```powershell
$env:INTERNAL_API_KEY = "<long-random-key>"
$env:DJANGO_SETTINGS_MODULE = 'f1_project.settings'
```

3. Apply DB migrations

```bash
python backend/manage.py migrate
```

4. Run unit & parity tests (recommended before rollout)

```bash
python backend/manage.py test api.tests.unit.test_api_key_env_fastpath --settings=f1_project.settings_test --keepdb --noinput
python backend/manage.py test api.tests.unit.test_persistence_parity --settings=f1_project.settings_test --keepdb --noinput
python backend/manage.py test api.tests.unit.test_store_serializer_alignment --settings=f1_project.settings_test --keepdb --noinput
```

5. Smoke validation (optional manual): pick 1–3 recent rounds and run the populate commands in staging

```bash
# race + analysis
python backend/manage.py populate_race --year 2024 --round 3 --session R --force

# session data (weather, incidents, positions)
python backend/manage.py populate_session --year 2024 --round 3 --session R --force

# driver telemetry for a single driver
python backend/manage.py populate_telemetry --year 2024 --round 3 --session R --driver HAM --force
```

Compare the persisted `payload['data']` for the relevant model rows to the API output (e.g., via `api.results.services` serializers or by calling the API endpoint).

6. Rollout

- Deploy to workers and web instances with `INTERNAL_API_KEY` set.
- Stagger rollout if desired (e.g., web first, then workers) and monitor metrics described in `MONITORING.md`.

7. Post-deploy

- Run the parity smoke validations again on staging/production samples.
- Verify no unexpected DB lookup spikes from auth code paths.
