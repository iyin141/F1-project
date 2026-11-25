# VM results, 2026-11-25

Written by the agent that took over on the Oracle VM (follows `docs/VM_TAKEOVER.md` and `docs/v2/VM_RUNBOOK.md`). The old stack ran untouched until the switch-over at the end of the day (see the Switch-over section); it is stopped, disabled and kept for rollback.

**Where it runs.** The v2 stack lives in `~/F1-project-v2` (project `f1-project-v2`), not in `~/F1-project`: that folder is the live legacy production on branch `phase-2/api-baseline` with local changes, so `git checkout v2/integration` there would have broken it. The code was sent from the PC (no `git pull` on the VM, so no GitHub token was needed). The stack's nginx listens on `127.0.0.1:8088` through a VM-only `docker-compose.override.yml`, because the host nginx owns ports 80 and 443 for nine other apps. The v2 `.env` was built on the VM (legacy keys copied by name, new `SECRET_KEY` and `POSTGRES_PASSWORD`, Flower login in `~/f1-v2-flower-login.txt`, mode 600).

## Runbook steps

| Step | Result | Notes |
|---|---|---|
| 0 Old stack | **Pass** | `http://127.0.0.1:8000/` 200 before and after every step; `f1-project.service` active |
| 1 Code and env | **Pass** | `docker compose config -q` clean |
| 2 Images | **Pass** | `f1-control-room-api` 1.98 GB, `-rag` 3.19 GB, `-ml` built; imports ok (fastf1 3.9.2); `import torch` fails in web as required |
| 3 Stack on empty DB | **Pass** | every service healthy; `/` and `/api/docs/` 200 on port 8088; stack adds about 3 GB of RAM |
| 4 Neon migration | **Pass, with one fix** | counts identical on `driver_lap_analysis` (2,266), `api_f1driver` (875), `api_f1champion` (77); `migrate --check` clean; `vector` present. **`pg_trgm` was missing** (migration 0024 is marked applied by the dump, but the restore does not carry extensions); created by hand. `make backup` and `make backups` work (11 MB dump) |
| 5 FastF1 cache | **Pass** | 26 GB copied in about 9 minutes. **The cache holds 2010 to 2017 and 2023 to 2026 only** |
| 6 F1TV login | **Skipped** | a paid subscription is the user's decision |
| 7a Schedules, results | Not run | the Neon copy already has 136 races (2021 to 2026) |
| 7b Track geometry | **Pass** | 136 tasks queued, 109 geometries, 28 distinct circuits (20+ needed). 2021: 21, 2022: 22, 2023: 22, 2024: 15, 2025: 24, 2026: 5. `track-map` for 2024 round 1 answers 503 (geometry could not be built) |
| 7c Chaos seed | **Pass** | 32 circuit profiles (4 without a track map), 290 `RaceEventLabel` rows, 136 `build_labels` tasks done, features built (`/features/*.parquet`). `link_circuit_keys` printed 0 for every season because the keys were already linked |
| 7d Kumo and backtest | **Pass, after three code fixes** | weights downloaded (688 MB; the runbook said they were already on the VM, they were not); offline smoke ok. Backtest `--seasons 2018-2025 --backfill-kumo` ran 34 minutes on 2 CPU cores (2024 and 2025 only), `ModelRun` saved, 45 races of raw Kumo predictions stored. `/api/chaos/model/` answers; `/api/chaos/races/2024/5/` and `/2026/5/` answer 200 and say `beta_binomial` produced them |
| 8 Stewards | **Pass, with setup fixes** | corpus restored (615 sources, 387 ingested, 3,721 chunks; `check-gold`: none missing); model cache seeded; embeddings 384 dimensions; Claude login works in the container (after the config-path fix, finding 10); retrieval eval reproduces the PC numbers; `ask` through nginx returns a grounded cited answer; 5 of 5 correct on the end-to-end eval. MCP not tested |
| 9 Snapshot | **9/10 identical** | `/api/schema/` differs only by v2 additions: 14 new paths, 2 existing telemetry routes gained optional query parameters (`channels`, `start_m`, `end_m`, `format`), 0 paths or components removed (one apparent removal, `/api/auth/internal-key/`, came from my `.env`: `INTERNAL_KEY_PATH` was a placeholder, now `internal-key` like the legacy default) |
| 10 Health | **Pass** | `dc ps` all healthy, `migrate --check` clean, consumers on tier1 to tier6, backfill, ml and rag, backups present, memory per service under its limit (worker-t1 about 420 MiB of 768) |
| 11 Switch-over | **Done 2026-11-25 ~13:40 UTC** | see the section below; rollback script `~/f1-rollback.sh` |

## Measured numbers

Backtest, seasons 2024 and 2025, 66 races, leave one season out. Columns: n, base rate, Brier, log-loss, AUC, ECE.

| Model | Cell | n | Base | Brier | Log-loss | AUC | ECE |
|---|---|---|---|---|---|---|---|
| beta_binomial | race / sc_vsc_red | 46 | 0.413 | 0.312 | 0.842 | 0.302 | 0.317 |
| beta_binomial | lap_window / sc_vsc_red | 579 | 0.055 | 0.155 | 0.471 | 0.483 | 0.243 |
| lightgbm | race / sc_vsc_red | 46 | 0.413 | 0.264 | 0.721 | 0.433 | 0.239 |
| lightgbm | lap_window / sc_vsc_red | 579 | 0.055 | 0.0585 | 0.230 | 0.724 | 0.039 |
| kumo | race / sc_vsc_red | 46 | 0.413 | 0.133 | 0.408 | 0.852 | 0.085 |
| kumo | lap_window / sc_vsc_red | 579 | 0.055 | 0.070 | 0.285 | 0.446 | 0.114 |

Mean over all five cells (the `unlucky_stop` ones included): beta_binomial Brier 0.1653, log-loss 0.4648, ECE 0.2587; lightgbm 0.0817, 0.2524, 0.0902; kumo 0.1087, 0.3676, 0.1429.

**Caveat on `unlucky_stop`:** all three `unlucky_stop` cells (driver, lap window, race) have a base rate of 0.000, so there are no positive labels, AUC is undefined, and those cells flatter every model's mean. The cause is the empty track-status table: without safety-car timing a pit stop cannot be called unlucky. The means above are therefore not comparable to a run with real labels. The sample is also small: 46 races, and the race-level AUCs swing between 0.30 and 0.85 on it.

Timing: whole backtest 34 minutes; Kumo toy fit (300 rows, 8 columns, 4 estimators) 3.9 s and predict (100 rows) 1.6 s on 2 CPU cores. torch is `2.15.0+cu132` (PyPI's default aarch64 wheel is the CUDA build, not CPU-only as `KUMO_SETUP.md` says; it runs on CPU).

Not measured: Canada sanity line (only two Canada races in 2024 and 2025), Lighthouse.

## Switch-over (step 11), done 2026-11-25 about 13:40 UTC

The user asked for it. No downtime: the host nginx upstream `f1_gunicorn` in `/etc/nginx/sites-available/f1project` now points to `127.0.0.1:8088` (the compose nginx) instead of `127.0.0.1:8000`, and `/static/` is proxied to the stack instead of the legacy `staticfiles` folder (the host nginx keeps TLS and every other app). Before the change: stack backup (23 MB dump), restart policy `unless-stopped` on all 18 services (they now come back after a reboot), and a check that Neon and the stack differ only by v2 additions (4 of 23 tables: permissions, content types, migrations, plus the v2 Celery task records) with one legacy task-record row written since the copy, so no re-copy was needed. After the change: `/`, `/api/docs/` and `/static/admin/css/base.css` answered 200 through the public domain, the 10-route snapshot against the pre-switch recording was 9 of 10 identical (only `/api/schema/`, which grew), all other apps still answered 200. Then the legacy stack was stopped and disabled: `systemctl disable --now f1-project`.

**Rollback** (one command, kept at `~/f1-rollback.sh`): restores the nginx backup `/etc/nginx/f1project.bak-f1switch-20261125-1340`, enables and starts `f1-project`, and stops the v2 beat and workers so nothing runs twice. Neon was not written to by v2, so the legacy stack still has its data; anything v2 wrote after 13:40 (task records, API-key usage) stays in the stack's own Postgres, dump in `pg_backups`. Keep the Neon project and `~/F1-project` (including the 26 GB host cache) until you are sure.

## Disk analysis (2026-11-25, after clearing the build cache)

135 GB used of 194 GB (70%). Before: 156 GB (81%), 21 GB of it Docker build cache (cleared). What is left: Docker 39 GB (images 41.6 GB shared across layers: `f1-control-room-ml` 11 GB because PyPI's aarch64 `torch` is the CUDA build, `firecrawl-camoufox-service` 9.5 GB, rag 3.2 GB, api 2 GB, then Learnly, Oja and Stock-index images of 1 to 1.8 GB each; volumes 38 GB of which `f1-project-v2_f1_cache` is 29 GB), `/home/ubuntu` 30 GB (`F1-project/backend/f1_cache` 26 GB, which duplicates the volume, plus a 0.9 GB venv, a 1.1 GB `testfile` and 0.9 GB `.local`), swap file 21 GB, `/var/log` 3.4 GB (journal 3.2 GB), snap 1.3 GB. A single container log is 2.5 GB. Easy wins: the 26 GB host cache once the rollback window is over; the `ml` image would shrink by several GB with the CPU wheel (`pip install torch --index-url https://download.pytorch.org/whl/cpu`, which also exists for aarch64); `journalctl --vacuum-size=500M` about 2.7 GB; `rm ~/testfile` 1.1 GB; 16 unused volumes (vidgen's 3 GB and 0.7 GB are the video pipeline's, not ours).

## Stewards numbers (step 8)

Retrieval (77 questions, pool 20, no LLM): matches the PC reference to the third decimal, so the corpus, the model files and the Postgres text-search config are the same.

| Mode | recall@8 | recall@20 | MRR |
|---|---|---|---|
| FTS only | 0.714 | 0.792 | 0.546 |
| vector only | 0.818 | 0.883 | 0.514 |
| RRF | 0.870 | 0.909 | 0.588 |
| RRF + rerank (700 chars) | 0.844 | 0.909 | 0.660 |
| RRF + rerank (full) | 0.857 | 0.909 | 0.667 |
| RRF + rerank + year filter (76 questions) | 0.895 | 0.947 | 0.795 |

Reranker on arm64 (2 CPU cores, other apps running): 20 pairs median 4.35 s (max 5.6 s), 30 pairs median 6.2 s (max 7.5 s). The runbook's switch-on limit is 3 s for 20 pairs, so **keep `STEWARDS_RERANK=0`**.

End to end, five questions (`q011 q022 q038 q053 q090`): answer correctness 1.0 (5 of 5), citation hit rate 1.0 on the four answerable ones, citation precision 0.75, the one unanswerable question answered "Evidence not found." (precision and recall 1.0), 26 Claude calls, $0.167, median 31.3 s per question (the PC reference was 75 to 95 s), mean 2.2 planner rounds. Only five of the ten questions of the full set were run.

Through nginx (`POST /api/assistant/ask`): "What is the minimum mass of an F1 car in the 2023 technical regulations?" took 37 s, 5 status events, 39 token events, 2 citations (2023 Technical Regulations, article 4 page 45 and article 4.5 page 45), `grounded: true`, answer "798 kg ... (Article 4.1, page 45)", cost $0.0325. The out-of-corpus question about 2023 British Grand Prix qualifying times took 56 s and ended with "Evidence not found." (`not_found: true`, no citations, $0.030). Replaying a finished task returned the same number of events (46 and 40). No key gives 401, an empty body gives 400, an unknown task gives 404.

## Frontend (takeover guide 4.2), partly done

Source of `v2/ui` (commit `5b8f101`) was sent to `~/F1-frontend-v2`. `docker build` with `NEXT_PUBLIC_API_MODE=live` and `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8088` succeeded on arm64 in 1 min 48 s (`f1-control-room-frontend:latest`). A test container on `127.0.0.1:8089` started ("Ready in 0ms") and answered 200 for `/`, `/chaos` and `/stewards`; `/races` and `/lab` answered 404 (those paths may simply not exist in the app, not checked). The test container was removed afterwards; the image stays.

Not done: merging `v2/ui-3d` (3D replay, needs `npm install` of three, react-three/fiber, drei; the listed files conflict), Playwright (never run; needs `@playwright/test` and Chromium on the VM), adding the frontend service to compose and nginx at `/`, Lighthouse, the live-mode click-through. A browser is needed for the last three.

## Findings and code fixes (all on `v2/integration`)

1. **`pg_trgm` missing after the Neon restore.** The dump carries migration 0024 as applied but not the extension. Fix used: `create extension pg_trgm`. Recommended: make `migrate-from-neon` run `CREATE EXTENSION IF NOT EXISTS pg_trgm` after the restore.
2. **`Dockerfile.ml` lacked `libgomp1`**: LightGBM failed with `libgomp.so.1: cannot open shared object file`. Fixed (separate layer after the torch layer).
3. **Kumo adapter read the output with `.detach()`**, which `TableTensor` forbids. The real layout, found on the VM: `out.to_pandas()` has columns `'0'` and `'1'`, each row sums to 1. `KumoAdapter._class1` now uses it; a test was added (`test_kumo_adapter_class1_reads_tabletensor_via_to_pandas`; it could not run on the VM because the image has no pytest).
4. **`ModelRun.race_key` was `varchar(12)` but a backtest saves `loso-2018-2025` (14 characters).** SQLite does not enforce the length, so the unit tests passed. Migration `chaos/0003_modelrun_race_key_len` widens it to 32.
5. **The stored 2026 schedule has no round 5**, so `[chaos] UNMATCHED CIRCUIT 2026 R5 (no schedule row)` appears, and `chaos/races/2026/5/` reports circuit `unknown`. This is missing data, not a missing alias.
6. **Nginx keeps the old address of `web` after `web` is recreated** and answers 502 until `docker compose restart nginx`. Anyone recreating `web` must restart nginx (a resolver with a variable in `deploy/nginx/default.conf` would remove the need).
7. **The FastF1 cache has no 2018 to 2022 folders**, and 2024 has only 15 of its races as geometries. Those seasons need the FastF1 mirror or the F1TV login.
8. **`~/.claude` on the VM belongs to uid 1001, not 1000** as the runbook expects; the Stewards step needs a permission fix.
10. **`CLAUDE_CONFIG_DIR` leaks into the container.** `.env` holds the HOST folder (it feeds the bind mount), the same file is the container's environment, so the CLI looked for its login at the host path inside the container and answered "Not logged in" although the mounted login was fine. Fixed in `docker-compose.yml`: `worker-rag` now sets `CLAUDE_CONFIG_DIR: /home/app/.claude`.
11. **The VM's `~/.claude` belongs to uid 1001 and the container user is uid 1000.** The runbook says to `chown` it to 1000, which would lock the host user out of its own login. Instead `~/f1-claude` (owner 1000, mode 700) holds a copy of `.credentials.json` and `CLAUDE_CONFIG_DIR` in the VM `.env` points to it. The access token in the file had expired 26 days ago, and the CLI refreshed it on the first call. **A refresh rotates the token, so the original `~/.claude` login on the VM may now be invalid: run `claude` and `/login` there if you use it.** Running the container as uid 1001 was tried and failed (the shared `app_logs` volume belongs to uid 1000).
12. **`worker-rag` is capped at 1 GB and the retrieval eval gets OOM-killed at that size** (it needs about 1.7 GB). The cap was raised to 3 GB with `docker update` only while the evals ran and restored afterwards. For routine runs use a one-off container or raise the limit in compose.
13. **`python -c "from api.assistant.embeddings import embed_query ..."` in the runbook fails** with `AppRegistryNotReady`; use `python manage.py shell -c`. The image has no `ps`, `pgrep` or `pytest`.
9. **Runbook step 1 is unsafe on this VM** (`git checkout` inside the live legacy folder); step 3 needs port 80 which the host nginx holds. Use a separate folder and the loopback override as done here.

## Not done (needs budget or a decision)

- **Stewards leftovers:** the other five questions of the 10-question end-to-end set, the MCP server (not wired into compose), and the corpus fetch of 2022 Technical, 2024 Technical and 2026 Section C (the restored corpus already covers the evaluation snapshot).
- **Frontend, remaining:** 3D replay merge, Playwright, compose and nginx wiring, Lighthouse, live-mode check (see the Frontend section).
- **Seasons 2018 to 2023** for the backtest, and `unlucky_stop` labels (needs track status).
- **README numbers** were updated for the model card and the DEFERRED-VM table; the 15-row table still lists Stewards, MCP, reranker, corpus and F1TV rows as open.

## Decisions waiting on the user

When to delete Neon and the legacy `~/F1-project` folder (the switch-over itself is done); `main` and the `v1.0` tag; a root LICENSE; PyPI for the Python client; the F1TV subscription (needed for live position data and for seasons missing from the cache); whether to keep the new random `SECRET_KEY` of the v2 `.env` or reuse the legacy one (it was exposed during the build); the webshare proxy password. The VM stack currently uses about 3 GB more RAM than before and is left running beside the legacy stack.
