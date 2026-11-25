# VM results, 2026-11-25

Written by the agent that took over on the Oracle VM (follows `docs/VM_TAKEOVER.md` and `docs/v2/VM_RUNBOOK.md`). The old stack was never stopped. Nothing was switched over.

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
| 8 Stewards | **Not run** | see "Not done" |
| 9 Snapshot | **9/10 identical** | `/api/schema/` differs only by v2 additions: 14 new paths, 2 existing telemetry routes gained optional query parameters (`channels`, `start_m`, `end_m`, `format`), 0 paths or components removed (one apparent removal, `/api/auth/internal-key/`, came from my `.env`: `INTERNAL_KEY_PATH` was a placeholder, now `internal-key` like the legacy default) |
| 10 Health | **Pass** | `dc ps` all healthy, `migrate --check` clean, consumers on tier1 to tier6, backfill, ml and rag, backups present, memory per service under its limit (worker-t1 about 420 MiB of 768) |
| 11 Switch-over | **Not done, by design** | the user decides |

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

Not measured: Canada sanity line (only two Canada races in 2024 and 2025), arm64 reranker bench, Stewards numbers, Lighthouse.

## Findings and code fixes (all on `v2/integration`)

1. **`pg_trgm` missing after the Neon restore.** The dump carries migration 0024 as applied but not the extension. Fix used: `create extension pg_trgm`. Recommended: make `migrate-from-neon` run `CREATE EXTENSION IF NOT EXISTS pg_trgm` after the restore.
2. **`Dockerfile.ml` lacked `libgomp1`**: LightGBM failed with `libgomp.so.1: cannot open shared object file`. Fixed (separate layer after the torch layer).
3. **Kumo adapter read the output with `.detach()`**, which `TableTensor` forbids. The real layout, found on the VM: `out.to_pandas()` has columns `'0'` and `'1'`, each row sums to 1. `KumoAdapter._class1` now uses it; a test was added (`test_kumo_adapter_class1_reads_tabletensor_via_to_pandas`; it could not run on the VM because the image has no pytest).
4. **`ModelRun.race_key` was `varchar(12)` but a backtest saves `loso-2018-2025` (14 characters).** SQLite does not enforce the length, so the unit tests passed. Migration `chaos/0003_modelrun_race_key_len` widens it to 32.
5. **The stored 2026 schedule has no round 5**, so `[chaos] UNMATCHED CIRCUIT 2026 R5 (no schedule row)` appears, and `chaos/races/2026/5/` reports circuit `unknown`. This is missing data, not a missing alias.
6. **Nginx keeps the old address of `web` after `web` is recreated** and answers 502 until `docker compose restart nginx`. Anyone recreating `web` must restart nginx (a resolver with a variable in `deploy/nginx/default.conf` would remove the need).
7. **The FastF1 cache has no 2018 to 2022 folders**, and 2024 has only 15 of its races as geometries. Those seasons need the FastF1 mirror or the F1TV login.
8. **`~/.claude` on the VM belongs to uid 1001, not 1000** as the runbook expects; the Stewards step needs a permission fix.
9. **Runbook step 1 is unsafe on this VM** (`git checkout` inside the live legacy folder); step 3 needs port 80 which the host nginx holds. Use a separate folder and the loopback override as done here.

## Not done (needs budget or a decision)

- **Step 8 Stewards** (model cache, corpus fetch, ingest, retrieval eval, one end-to-end eval of about 60 Claude calls and about $0.45, MCP). Skipped because the weekly usage limit was close and the end-to-end eval spends subscription quota. Needs the `~/.claude` permission fix first.
- **Frontend** (section 4.2 of the takeover guide): 3D replay merge, Playwright, Docker image, Lighthouse, live-mode check.
- **Seasons 2018 to 2023** for the backtest, and `unlucky_stop` labels (needs track status).
- **README numbers** were updated for the model card and the DEFERRED-VM table; the 15-row table still lists Stewards, MCP, reranker, corpus and F1TV rows as open.

## Decisions waiting on the user

Switch-over time and when to delete Neon; `main` and the `v1.0` tag; a root LICENSE; PyPI for the Python client; the F1TV subscription (needed for live position data and for seasons missing from the cache); whether to keep the new random `SECRET_KEY` of the v2 `.env` or reuse the legacy one (it was exposed during the build); the webshare proxy password. The VM stack currently uses about 3 GB more RAM than before and is left running beside the legacy stack.
