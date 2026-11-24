# VM runbook: bring up v2 on the Oracle VM

One ordered checklist, top to bottom. It links the detailed runbooks instead of repeating them. Stop at the first
step whose "Pass" is not met. Everything runs on the VM (Ubuntu, aarch64, 24 GB) from the repository root, because anything
that needs real F1 data or a large download belongs here, not on the dev PC.

Conventions: `dc` = `docker compose` (set `alias dc='docker compose'`); `make` targets are in the root `Makefile`.
Never paste `.env` values into chats or logs.

Background (why some steps exist): the F1 livetiming archive has answered 401 to everyone since about 2026-10-15; FastF1 3.9
added an F1TV account login for it, and the old webshare proxy now returns 402. The VM already has a warm FastF1 cache
(`/home/ubuntu/F1-project/backend/f1_cache`), which is why most seeding below works without any login. See
`docs/v2/API_TEST_2026-11-24.md` for the first real-data test this runbook is meant to improve on.

---

## 0. Before you touch anything (keep the old stack running)

The old stack (`backend/start_prod.sh`, legacy, Neon) keeps serving until step 11. Note how it runs
(`ps aux | grep -E "uvicorn|celery"`), and that Neon is untouched by everything below except a read-only dump.

Pass: `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/` prints `200` (old API still up).

## 1. Get the code and the environment

```bash
cd ~/F1-project && git fetch && git checkout v2/integration && git pull
cp .env.example .env            # first time only; otherwise diff .env against .env.example and add new keys
chmod 600 .env
```

Fill in `.env` (never commit it): `SECRET_KEY`, `ALLOWED_HOSTS`, `SITE_BASE_URL`, `INTERNAL_API_KEY`, `ADMIN_SECRET`,
email keys, **`POSTGRES_PASSWORD`** (URL-safe: `openssl rand -hex 24`), `CLAUDE_CONFIG_DIR=/home/ubuntu/.claude`
(owner uid 1000: `stat -c %u ~/.claude` prints `1000`). Leave `FASTF1_AUTH=none` and `PROXY_*` empty for now. Create the Flower
login: `htpasswd -c deploy/nginx/.htpasswd admin` (or `openssl passwd -apr1`, see the compose comment).

Pass: `dc config -q` prints nothing (exit 0). `ls deploy/nginx/.htpasswd` exists.

## 2. Build the images

```bash
dc build web                       # base API image (plain: no torch/onnx/CLI). ~10 min first time on arm64
dc build worker-rag                # base + fastembed/onnxruntime + claude CLI   (details: backend/api/assistant/VM_TESTING.md step 1)
dc --profile ml build worker-ml    # base + torch (CPU) + structured-data-models + lightgbm==4.7.0
```

Pass: `dc images` lists `f1-control-room-api`, `f1-control-room-rag`, `f1-control-room-ml`. Wheel check on the arm64 base:
`dc run --rm --no-deps web python -c "import numpy, pandas, psycopg2, fastf1; print(fastf1.__version__)"` prints a version;
`dc run --rm --no-deps web python -c "import torch"` FAILS (torch must not be in the web image). If `pip wheel` stops on a
missing aarch64 wheel, VM_TESTING.md step 1 has the recovery procedure (and `backend/wheelhouse/`, see the Dockerfile header).

## 3. Start the stack on an empty database

```bash
make up                             # postgres, redis x4, web, workers t1-t6, beat, flower, nginx (+ pgbackup)
```

Pass: `dc ps` shows every service `healthy` (workers and beat included, ~2 min); `curl -s -o /dev/null -w '%{http_code}\n' http://localhost/`
prints `200` and the same for `/api/docs/`. Port 80 must be free (stop the old nginx or move it, see step 11).

## 4. Migrate the data from Neon

Follow `deploy/RUNBOOK_DB.md` ("Migrate from Neon"): `make migrate-from-neon NEON_DATABASE_URL='postgres://...'`.
It reads Neon only, stops the app services, restores Neon's `public` schema into an emptied schema, compares row counts, then runs
`migrate` (which adds trackmap, chaos, assistant and the pgvector extension) and `migrate --check`.

Pass: the output ends with `row counts identical for N Neon tables`, then no unapplied migrations; afterwards
`dc exec -T postgres psql -U f1 -d f1 -Atc "select count(*) from driver_lap_analysis"` (any big table) matches Neon, and
`dc exec -T postgres psql -U f1 -d f1 -Atc "select extname from pg_extension"` lists `vector` and `pg_trgm`.
Then `make backup` and `make backups` once to confirm the backup path works.

## 5. Copy the existing FastF1 cache into the stack

The stack's `f1_cache` volume is empty; the VM host has the warm cache. Copy it through the compose volume (no volume-name guessing):

```bash
dc run --rm --no-deps -v /home/ubuntu/F1-project/backend/f1_cache:/src:ro web sh -c 'cp -a /src/. /app/f1_cache/ && du -sh /app/f1_cache'
```

Pass: the printed size is close to `du -sh /home/ubuntu/F1-project/backend/f1_cache`; and
`dc exec -T web ls /app/f1_cache | head` shows `fastf1_http_cache.sqlite` and year folders. (If `cp` says permission denied, the host files are
not uid 1000: `sudo chown -R 1000:1000 /home/ubuntu/F1-project/backend/f1_cache` first.)

## 6. F1TV login for livetiming (optional, only if a session you need is not in the cache)

FastF1 3.9.2 needs an F1TV Bearer token for livetiming; "An active F1TV subscription is required". The app never logs in by itself and
`FASTF1_AUTH=none` is the default. To use it, once, on the VM (interactive; the password is typed, never stored in `.env` or git):

```bash
dc run --rm -it --no-deps web python -m fastf1 auth f1tv --authenticate   # prompts for the F1 account email and password
dc run --rm --no-deps web python -m fastf1 auth f1tv --status             # prints the expiry and 'Subscription Status'
sed -i 's/^FASTF1_AUTH=.*/FASTF1_AUTH=token/' .env && make up    # recreate the services with the new setting
```

The token is stored in the `fastf1_auth` volume (`/fastf1-auth/fastf1/f1auth_token.json`, mode 600), shared by every service, never in the image.
When it expires FastF1 logs "Failed to authenticate ... continuing without authentication" and live loads fail: repeat the first command.
`python -m fastf1 auth f1tv --clear` removes the stored token. The CLI is plain FastF1 (it does not go through `api/session/runtime.py`), so it logs in even while `FASTF1_AUTH=none`.

Pass: `--status` prints `Token Status: Expires ...` and a subscription status that is active. If you skip this step, nothing else changes; cached sessions keep working.

## 7. Seed the data the v2 features need

Real-data findings (`API_TEST_2026-11-24.md`): only two races had telemetry, no track status, no qualifying. Run these in order; each
is idempotent. Use the years you care about (`YEARS` below).

```bash
YEARS="2018 2019 2020 2021 2022 2023 2024 2025 2026"

# 7a. Schedules, results, standings (existing commands; see backend/api/management/commands/). Examples:
dc exec -T web python manage.py populate_schedule --year 2026
dc exec -T web python manage.py seed_historical_data        # see its --help for the year range

# 7b. Track geometry for every round (tier4 workers; reads the FastF1 cache, so step 5 matters)
dc exec -T web python manage.py shell -c "
from api.models import SeasonSchedule
from api.trackmap.tasks import build_track_geometry
for s in SeasonSchedule.objects.all():
    for r in s.payload.get('races', []):
        build_track_geometry.delay(s.year, r['round'])"
```

Pass 7b: after the tier4 queue drains (`dc logs -f --tail=20 worker-t4`; Flower shows 0 active/queued at `http://<vm>/flower/`),
`dc exec -T web python manage.py shell -c "from api.trackmap.models import TrackGeometry as T; print(T.objects.count())"` is about the
number of distinct circuits (20+); `curl -s -H "X-API-Key: $KEY" http://localhost/api/analysis/races/2024/1/track-map/` returns `"status":"ok"` data,
not "failed" (if a session loads without position data, see finding 1 of the API test: it needs live access, step 6).

```bash
# 7c. Chaos: circuit profiles, link them to track geometry, labels per race, features
dc exec -T web python manage.py shell -c "
from api.chaos.circuits import populate_circuit_profiles, link_circuit_keys
from api.chaos.tasks import build_labels, build_features
from api.models import SeasonSchedule
print('profiles', populate_circuit_profiles())
for s in SeasonSchedule.objects.all():
    print(s.year, 'linked', link_circuit_keys(s.year))
    for r in s.payload.get('races', []):
        build_labels.delay(s.year, r['round'])"
# when the tier3 queue is empty:
dc exec -T web python manage.py shell -c "from api.chaos.tasks import build_features; print(build_features.delay().id)"
```

Pass 7c: `CircuitProfile.objects.filter(circuit_key__isnull=True).count()` is small (circuits without a built track map);
`link_circuit_keys` printed non-zero for the seasons with built maps (finding 3: a location name that does not match the seed aliases is reported as 0 for that round);
`ChaosLabel`/features files exist: `dc exec -T worker-t3 ls /features` shows the Parquet feature files.

```bash
# 7d. Kumo + backtest (ml worker; weights already on the VM)
```

Kumo weights go into the `ml_models` volume at `/models/hf` (`docs/v2/plans/KUMO_SETUP.md`). If they are only in the host Hugging Face cache, copy them like step 5:

```bash
dc --profile ml run --rm --no-deps -v ~/.cache/huggingface:/src:ro worker-ml sh -c 'mkdir -p /models/hf && cp -a /src/. /models/hf/'
dc --profile ml run --rm --no-deps -e HF_HUB_OFFLINE=1 worker-ml python -c "import sdm, torch; print(torch.__version__)"      # smoke
dc --profile ml up -d worker-ml
dc --profile ml exec -T -e HF_HUB_OFFLINE=1 worker-ml python manage.py chaos_backtest --seasons 2018-2025 --backfill-kumo
```

Pass: the smoke prints a torch version offline (no download attempt); the backtest ends with a per-model table (Brier, log-loss, AUC, ECE) and a `ModelRun`
row; `curl -s -H "X-API-Key: $KEY" http://localhost/api/chaos/model/` shows the run; `/api/chaos/races/2026/5/` is built from stored labels and says which model produced it.
Expect the first Kumo run to take minutes per race on CPU; record the timing.

## 8. Stewards (document Q&A)

Follow `backend/api/assistant/VM_TESTING.md` start to finish (model cache seeding, Claude login mount, corpus fetch/ingest, retrieval checks,
end-to-end ask through nginx, MCP). It already states what passes at each step; it costs subscription quota where marked.

Pass: its section 6 (end to end through nginx) returns a cited answer, and "Evidence not found" for an out-of-corpus question.

## 9. Snapshot: old stack vs new stack (10 routes)

`backend/scripts/snapshot_routes.py` records the status and scrubbed JSON of 10 representative routes. Record on the old stack BEFORE the switch, compare on the new.

```bash
export SNAPSHOT_API_KEY=$(grep '^INTERNAL_API_KEY=' .env | cut -d= -f2)
python3 backend/scripts/snapshot_routes.py record  --base http://127.0.0.1:8000 --out ~/snapshot_old.json     # old stack
python3 backend/scripts/snapshot_routes.py compare --base http://127.0.0.1     --against ~/snapshot_old.json   # new stack via nginx :80
```

Pass: `10/10 identical` (exit 0). Differences are expected only where v2 intentionally changed behaviour (none of these 10 routes should); investigate any diff.
Both stacks must hold the same data: do the comparison right after step 4 (before new writes) or accept diffs in time-dependent routes.

## 10. Final health check of the new stack

Pass: `dc ps` all healthy; Flower (`/flower/`, basic auth) shows every queue (tier1-6, backfill, ml, rag) with a consumer
(`dc exec -T worker-t1 celery -A f1_project inspect active_queues` lists tier1_instant tier2_fast tier3_medium tier4_telemetry tier5_pagination backfill
tier6_notifications, plus `ml` and `rag` when those workers are up); `dc exec -T web python manage.py migrate --check` exits 0; `make backups` lists a recent dump;
`dc stats --no-stream` memory per service is under its limit (worker-t1 about 450 MiB of 768).

## 11. Switch over

1. Announce a short write freeze; `make backup`.
2. Stop the old stack (the processes from step 0: uvicorn, `celery multi`/workers, beat, flower; `pkill -f "celery -A f1_project"; pkill -f uvicorn`).
3. Free port 80 if a host nginx holds it (disable it or point it at `127.0.0.1:80` of the compose nginx; TLS stays wherever it is today).
4. `make migrate-from-neon ...` once more only if the old stack wrote to Neon after step 4 (it re-copies; the stack restarts).
5. `make up`; repeat the step 9 compare against the saved old snapshot, then `curl https://<your-domain>/api/docs/`.

Pass: public URL serves `/api/docs/` 200 from the compose stack; Flower is healthy; no errors in `dc logs --since 10m web | grep -i error`.

## 12. Rollback

Neon is untouched, so rollback is "start the old stack again":

1. `make backup` (so nothing written since the switch is lost), then `dc down` (keep volumes; no `-v`).
2. Restore the old nginx/port setup and run `backend/start_prod.sh` with the old `.env` (its `DATABASE_URL` still points at Neon).
3. Data written to the stack's Postgres after the switch is NOT in Neon: copy it back by hand from the dump in `pg_backups` if it matters, or accept the loss.

Pass: `curl http://127.0.0.1:8000/` is 200 on the old stack and the snapshot compare against `~/snapshot_old.json` is 10/10.
Keep the Neon project for a few days after switching, then delete it.
