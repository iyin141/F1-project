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
- Linux cp313 wheels for the pinned requirements (`pip install --dry-run --only-binary=:all: --platform manylinux_2_28/2_27/2_17_aarch64 --python-version 3.13`): resolved a cp313 aarch64 wheel for every package alphabetically through pyarrow-21.0.0 (contourpy 1.3.3, numpy 2.3.5, pandas 2.3.3, pikepdf 10.0.2, pillow, matplotlib, cryptography, fonttools, ...). The check then stalled on this machine's flaky TLS (repeated SSL DECRYPTION_FAILED), so packages after pyarrow (pydantic_core, psycopg2-binary, scipy, scikit-learn, uvicorn extras...) were NOT verified; x86_64 not completed either. Only sdist-only pin found: django-querycount (pure Python, builds in the builder stage via `pip wheel`). CI's buildx arm64 job will confirm the rest.

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

---

# Phase 0b

Status: done except items marked DEFERRED. Branch v2/infra rebased on v2/integration.

## Done
1. **Dockerfile**: grep-strip and flower append removed. `docker-compose` workers use the same `requirements.txt`. CI/`make test` install `requirements-dev.txt`, `requirements-rag.txt`, then `pip install --no-deps fastembed==0.9.1`. worker-ml limit 4g.
   Memory limits (sum): 9.1 GB without ml, 13.2 GB with the ml profile (above the ~12 GB target). Measured idle usage showed worker-t1 at 455 MiB of 512m, beat 155/192, flower 163/192, so t1 raised to 768m and beat/flower to 256m. Lower worker-ml (4g) or worker-t4 if the 12 GB cap is firm.
2. **Static files (whitenoise)**: verified locally in the stack (`/static/admin/css/base.css` 200, collectstatic runs in the entrypoint via `RUN_COLLECTSTATIC=1` on web). Diff below under "Needs from orchestrator". Not committed (settings.py / requirements.txt are orchestrator-owned).
3. **Ruff**: `backend/ruff.toml` (E9, F63, F7, F82). Passes. F401 is NOT enabled (169 unused imports). Five real F821 latent NameErrors are suppressed per file: `api/core/__init__.py` (`is_data_unavailable_error`), `api/services/store.py:609` (`Any`), `api/workers/tier3_medium/populate_laps.py:98-99` (`cache`, `canonical_task_key`, in a `finally`). CI `lint` job and `make lint` added.
4. **Local stack** (amd64 Docker Desktop, project `f1-infra`, dev overlay with pgvector postgres, dummy env, host ports 8010/8011/5440), torn down afterwards with `down -v`:
   - web healthy; through nginx: `/` 200, `/api/docs/` 200, `/api/schema/` 200, `/static/admin/css/base.css` 200.
   - flower: 401 without credentials, 200 with basic auth at `/flower/`. beat healthy, worker-t1..t6 healthy; `celery inspect active_queues` shows tier1_instant, tier2_fast, tier3_medium, tier4_telemetry, tier5_pagination, backfill, tier6_notifications each consumed.
   - migrations applied by the web entrypoint: api (to 0024), trackmap 0001, chaos 0001-0002, assistant 0001 (pgvector extension on `pgvector/pgvector:0.8.0-pg17`; pg16 could not be pulled on this network).
   - NOT run locally: worker-ml and worker-rag (their images need torch / onnxruntime / fastembed / npm downloads that this network corrupts). DEFERRED-VM.
5. **Snapshot harness**: `backend/scripts/snapshot_routes.py record|compare` (stdlib, 10 routes, volatile keys scrubbed). Proven locally against the stack: 10/10 identical on record vs compare (empty database, so most routes return the "no data" payload). The real before/after run is DEFERRED-VM.
6. **Claude CLI**: build arg `INSTALL_CLAUDE_CLI=1` (Node 20 via nodesource, `@anthropic-ai/claude-code@2.1.305`, the version on this machine). Enabled only on worker-rag (per later instruction web gets neither the CLI nor rag deps). Host `~/.claude` mounted via `CLAUDE_CONFIG_DIR` at `/home/app/.claude`; the image user is uid 1000. No live call made. Image build not run locally (DEFERRED-VM).
7. **worker-rag / stewards** (later instructions): build arg `INSTALL_RAG=1` installs `requirements-rag.txt` then `fastembed==0.9.1 --no-deps`. Volumes `stewards_models` (`STEWARDS_MODEL_CACHE=/stewards/models`) and `stewards_data` (`STEWARDS_DATA_DIR=/stewards/data`, private, never served by nginx) on worker-rag only. `HF_HUB_OFFLINE=1` on worker-rag. worker-rag limit 1g.
8. **Chaos features**: `CHAOS_FEATURES_DIR=/features`, `ml_features` volume mounted on worker-t3 and worker-ml. `/features` and `/models` are created app-owned in the image so the named volumes are writable by uid 1000.
9. `lightgbm==4.7.0` pinned in Dockerfile.ml.

## Bugs found and fixed along the way
- entrypoint.sh had CRLF in the Windows working copy (git index was LF), giving `exec entrypoint.sh failed` in the container. `.gitattributes` forces LF on checkout; I converted the working copy.
- beat and flower inherited the image HEALTHCHECK (uvicorn on 8000) and were permanently unhealthy: each now has its own healthcheck.
- The apt-based image could not be built on this machine's network (apt signatures "manipulated", pip SSL record errors). The image is now apt-free: no compilers (all pins have wheels), `psycopg2-binary` bundles libpq, tini replaced by compose `init: true`, healthcheck uses python instead of curl. If CI's arm64 build needs a compiler, add build-essential back to the builder stage.
- Optional offline wheelhouse: `backend/wheelhouse/*.whl` (git-ignored), tried first with `--no-index`, then PyPI.

## Seeding the Stewards model cache on the VM
Hugging Face downloads can stall, and worker-rag runs offline (`HF_HUB_OFFLINE=1`), so seed the volume from a machine that already has the models (about 200 MB: bge-small-en-v1.5 and the MiniLM-L-12 reranker):
```
# on the machine that has them (the STEWARDS_MODEL_CACHE dir; default <STEWARDS_DATA_DIR>/models)
tar czf stewards-models.tgz -C <STEWARDS_MODEL_CACHE> .
scp stewards-models.tgz vm:/tmp/
# on the VM
docker volume create f1_stewards_models   # compose names it <project>_stewards_models
docker run --rm -v <project>_stewards_models:/m -v /tmp:/in alpine sh -c "tar xzf /in/stewards-models.tgz -C /m && chown -R 1000:1000 /m"
```
Same for `stewards_data` (FIA PDFs) if the corpus is copied rather than fetched.

## Needs from orchestrator
Apply to `backend/f1_project/settings.py` and `backend/requirements.txt` (tested in the local stack; pytest also passes: 335):
```diff
diff --git a/backend/f1_project/settings.py b/backend/f1_project/settings.py
index ecd66c3..550bc05 100644
--- a/backend/f1_project/settings.py
+++ b/backend/f1_project/settings.py
@@ -65,6 +65,7 @@ MIDDLEWARE = [
     'api.common.request_id.RequestIdMiddleware',
     'corsheaders.middleware.CorsMiddleware',
     'django.middleware.security.SecurityMiddleware',
+    'whitenoise.middleware.WhiteNoiseMiddleware',  # serves /static/ (admin CSS) from STATIC_ROOT
     'django.contrib.sessions.middleware.SessionMiddleware',
     'django.middleware.common.CommonMiddleware',
     'api.middleware.csrf_exempt.CsrfExemptSessionMiddleware',  # Must run before CsrfViewMiddleware
@@ -170,6 +171,11 @@ USE_TZ = True
 # https://docs.djangoproject.com/en/6.0/howto/static-files/
 
 STATIC_URL = 'static/'
+STATIC_ROOT = BASE_DIR / 'staticfiles'  # filled by `collectstatic` in docker/entrypoint.sh
+STORAGES = {
+    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
+    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
+}
 
 # ---------------------------------------------------------------------------
 # ---------------------------------------------------------------------------
diff --git a/backend/requirements.txt b/backend/requirements.txt
index 8df971c..cd19cb7 100644
--- a/backend/requirements.txt
+++ b/backend/requirements.txt
@@ -98,3 +98,4 @@ django-cors-headers==4.7.0
 flower==2.0.1
 pgvector==0.5.1
 pypdf==7.1.1
+whitenoise==6.12.0
```
Neither touches the test settings (settings_test overrides MIDDLEWARE/uses its own storage defaults).

## Other notes
- The 5 F821 findings above are real latent bugs for their owners.
- Wheel check (earlier): linux x86_64 cp313 wheels for every pin were downloaded for the local wheelhouse (102 files, all resolved). aarch64 still verified only up to pyarrow; CI buildx arm64 will confirm.
- Ports used locally: 8010 (web), 8011 (nginx), 5440 (postgres); not 5433/8001-8003.


---

# Phase 0c: Postgres inside the stack (no Neon)

Status: done, tested locally with the production compose (project `f1-infra`, ports 8010/8011; postgres has no host port), torn down.

- `postgres` service in `docker-compose.yml`: `pgvector/pgvector:0.8.0-pg17`, tag verified multi-arch with `docker buildx imagetools inspect` (linux/amd64 + linux/arm64). Named volume `pg_data`, `pg_isready` healthcheck, limit 1536m (`shared_buffers` 384MB, `max_connections` 150), no published port. All app services `depends_on` it healthy and get `DATABASE_URL` (YAML anchor `*database-url`) from `POSTGRES_*` in `.env`. Dev overlay now only publishes 127.0.0.1:5432 and hot reload.
- `pgbackup` service (same image, so client = server version): `pg_dump -Fc` at start and every `BACKUP_INTERVAL_HOURS`, retention `BACKUP_RETENTION_DAYS`, volume `pg_backups`. `make backup | backups | restore f=...`, `make migrate-check`.
- `deploy/backup/{backup,restore,migrate_from_neon}.sh`, `deploy/RUNBOOK_DB.md`. `make migrate-from-neon NEON_DATABASE_URL=...` (read-only dump from Neon, restore, row counts per table, version guard). Not run against Neon.
- Memory budget: total limits now about 9.1 GB + 1.75 GB = 10.9 GB without ml, 15.0 GB with ml (4g). The plan's ~12 GB holds only without the ml profile; the VM has 24 GB.
- Proven locally: stack up with internal postgres; migrations applied (api, trackmap, chaos, assistant), extensions `vector`, `pg_trgm`; `/` and `/api/docs/` 200 via nginx; `backup.sh once` produced a 116K dump; restore into a scratch DB gave 46 migrations / 38 tables identical to the live DB; `migrate_from_neon.sh` mechanics proven against a fake "Neon" (second DB on the same server): versions, dump, restore, row counts identical (38 tables); `migrate --check` clean.
- Caveat: a Git Bash on Windows rewrites `/scripts/...` paths in `docker compose exec`; run with `MSYS_NO_PATHCONV=1` there. Linux (the VM) is unaffected.

## Other places that assume Neon (not edited, owned by others)
- `backend/api/management/commands/hard_reset_db.py`: docstring and safety text say "Neon only" and check the DB vendor; review if it should work on the stack DB.
- `backend/api/assistant/migrations/0001_initial.py:18` comment "NOT yet applied to Neon".
- `backend/api/assistant/tests/test_pgvector_live.py` docstring (local container, port 5433).
- `backend/start_prod.sh` lines 39 and 127: legacy path, comments say Neon is external.
- `settings.py`: nothing Neon-specific (`dj_database_url.parse`, `conn_max_age=600`); no `ssl_require`, so the in-stack DB works as is. With 19 prefork workers plus 2 uvicorn workers holding connections, `max_connections=150` is enough.
- docs: `docs/v2/ARCHITECTURE_V2.md` section 8 ("postgres Neon"), `docs/v2/ORCHESTRATION.md` (DEFERRED-VM: "Enabling pgvector on Neon"; "Never connect to Neon" still valid for agents), `docs/v2/plans/00_*.md`, `docs/v2/plans/01_*.md`, `docs/v2/progress/A3-stewards.md`.
- `.env.example` (updated by me): no `sslmode=require` any more; `NEON_DATABASE_URL` is only for the one-off migration.
