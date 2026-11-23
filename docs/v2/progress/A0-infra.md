# A0 infra: progress

Phase: 0a (hygiene + Docker port + env-free tests). Status: done, awaiting review.

## Commits (v2/infra)
- Docker port (images, compose, nginx, Makefile, CI)
- Hygiene (untrack artefacts, move scripts, remove misc_2)
- Tests run with no .env
- Untrack backend/misc/*.txt (+ this progress file)

## Patch fixes (docs/v2/0001-docker-port.patch)
- The patch file is CRLF-corrupted: git rejects its binary deletions. Applied with CRs stripped, excluding docs/ and the deleted runtime files; those deletions done with `git rm --cached`.
- Python 3.12 -> 3.13 in Dockerfile (matches the venv, 3.13.7).
- nginx: `/` and `/admin/` were unreachable (only `/api/` proxied, `/` redirected). Now `location /` proxies to Django.
- compose: added `worker-rag` (plan lists it; patch had none). Note on creating `deploy/nginx/.htpasswd` before `up` (a missing bind-mount source becomes a directory).
- Dockerfile.ml: dropped unpinned `scikit-learn`/`pyarrow` (base image pins them; unpinned would upgrade).
- `.gitattributes`: `*.sh` and `Dockerfile*` forced LF (Windows autocrlf would break entrypoint.sh in the image).
- Root `.gitignore`: added `.env` (only backend/.gitignore covered it; compose uses a root .env).
- Makefile `test`: patch ran `manage.py test` (suite is pytest, pytest not in the image); now `cd backend && python -m pytest -q`.
- CI: added a `test` job (py3.13, no .env). Ruff NOT added: untested lint on this codebase would fail CI; decide a ruleset first.
- Checked OK against code: queue names match celery.py; Redis URL env names/DB numbers match settings.py; redis-cache 1gb/200mb/noeviction match the settings comments; uvicorn/celery flags match start_prod.sh; NOT matching: the Dockerfile healthcheck hit `/api/`, which is a 404 (no route; verified with the Django test client), so every container would be `unhealthy`. Now `/` (public api_root, 200). ALLOWED_HOSTS must include 127.0.0.1 (it does in .env.example).
- `docker compose config -q` passes (with and without `--profile ml`) using a dummy .env from .env.example (removed afterwards).

## Python 3.13 / wheels
- requirements.txt installs and the suite runs on 3.13.7 (Windows) in my own venv.
- structured-data-models 0.3.0 (PyPI JSON): pure-Python wheel, requires Python >=3.11, torch>=2.7. torch 2.15.0 on PyPI has cp313 manylinux_2_28 aarch64 and x86_64 wheels; download.pytorch.org/whl/cpu has cp313 aarch64 + x86_64 (2.9.x). So the ML image can use 3.13. Note the PyPI x86_64 torch wheel is the CUDA build, hence the CPU index on amd64 in Dockerfile.ml.
- Linux cp313 wheels for the pinned requirements: see report (pip install --dry-run --platform check; django-querycount is sdist-only but pure Python, built in the builder stage).

## Hygiene
- Moved to backend/scripts/: test_2010.py, test_guard.py, test_proxy_requests.py, test_results.py, test_session_load.py, warmup_cache.py. They are ad-hoc scripts (module-level code, live FastF1/proxy calls), not pytest tests. Paths fixed for the new location. `pytest.ini` now has `testpaths = api/tests` so they are not collected.
- SECURITY: test_proxy_requests.py had hard-coded webshare proxy credentials (in git history). Now read from env PROXY_USER/PROXY_PASS/PROXY_HOST/PROXY_PORT. Rotate that proxy password.
- misc_2/ removed; test_db.sqlite3, logs/, misc/*.txt, celerybeat-schedule* untracked + ignored.
- `django-background-tasks`: unused. Only references: migration 0010 (drops its tables, plain SQL), a docstring in api/services/tasks.py, and a logger name in settings.py LOGGING. Not in INSTALLED_APPS. CAN BE REMOVED from requirements.txt. Also removable: git-filter-repo, GitPython, gitdb, smmap (Dockerfile already strips them). Likely unused too, not verified: streamlit (+altair, pydeck, tornado, toml, watchdog).
- NEEDED in requirements (dev/test): pytest, pytest-django, pytest-asyncio are not listed.

## Tests
- Real cause of the 401s: `settings.INTERNAL_API_KEY` comes from decouple (env/.env, default ""), while test setUps read `os.environ["INTERNAL_API_KEY"]` to build the header; with no env the header was absent and settings key empty. Fix: `settings_test.py` sets SECRET_KEY, DATABASE_URL, INTERNAL_API_KEY into os.environ (setdefault) before importing settings. Production settings.py untouched.
- The 2 "pre-existing" failures: `DriverEndpointReadinessTests` did not patch `resolve_driver_metadata` / `get_season_driver_map` (live Jolpica). Patched in setUp.
- New `backend/conftest.py`: autouse guard that raises on any non-loopback socket connect, so live calls fail everywhere.
- Result, empty environment: 211 passed, 16 skipped, 0 failed. With the original .env loaded via the orchestration command: 211 passed, 16 skipped, 0 failed.

## DEFERRED-VM
- Building/running arm64 images, `docker compose up`, healthchecks on the VM, flower/beat/queue health, snapshot test of 10 routes, Kumo/torch import in the ml image.

## Open questions
- Healthcheck now `/` (200 in test client); not verified in a running container. Note settings has no SECURE_PROXY_SSL_HEADER and no static serving (no whitenoise): /admin/ and swagger static assets will lack CSS in prod unless handled.
- Memory limits: sum without ML = ~7.7 GB; with `--profile ml` (6g) ~13.7 GB, above the plan's ~12 GB. Suggest ML limit 4g.

## Needs from orchestrator
- requirements.txt: remove django-background-tasks, git-filter-repo, GitPython, gitdb, smmap (then the Dockerfile grep can go); add pytest, pytest-django, pytest-asyncio (dev); add flower==2.0.1 (currently appended in Dockerfile).
- Create `main` branch/tag v1.0 (not done by me). Decide ruff ruleset.
