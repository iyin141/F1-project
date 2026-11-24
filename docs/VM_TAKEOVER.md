# F1 Control Room v2: VM takeover guide (for the agent that runs the VM)

You take over F1 Control Room v2 from the build that ran on the user's Windows PC. All the code-only work is finished, reviewed, merged and pushed. What's left needs the real VM: real data, large downloads, arm64 builds and the production switch-over.

**Start only when `docs/GO` exists on `v2/integration` and contains "go".** If it is missing, stop and tell the user.

## 0. Rules you must follow (from the user)

- **The VM is shared.** It runs other apps: the video-gen pipeline in `~/vidgen` and Firecrawl in `~/Local-firecrawl`. Never stop, restart, prune or reconfigure anything that isn't F1. No `docker system prune` and no global `docker compose down`. Always use the F1 compose project name.
- **SSH:** `ssh -i ~/.ssh/oracle_f1.key ubuntu@140.245.40.75`. The VM is Oracle A1 Flex: arm64, 4 cores, 24 GB RAM.
- **Old production keeps running** until step 11 of the runbook. Production today is the legacy `start_prod.sh` stack in `/home/ubuntu/F1-project`, serving `api.f1controlroomdocs.com` from Neon Postgres.
- **Git:** a GitHub token appeared in chat before. **Ask the user for a fresh token before any `git pull` on the VM.** Never force-push, never create `main` or tags, and never merge to `main` without the user saying so. Commit messages never carry Claude co-author or attribution lines.
- **Secrets:** never print `.env` values, tokens or connection strings; redact them in logs and reports. Never `source` a `.env` in a shell, because an error can echo the value.
- **Usage caps** (the user's subscription): stop all work at **98% of the 5-hour window** and at **85% of the weekly window**. Read both with:
  ```
  echo ok | claude -p --output-format stream-json --verbose --model claude-haiku-5-5 --tools "" --no-session-persistence | grep rate_limit_event
  ```
  This gives `unifiedWindows.five_hour.utilization` and `seven_day.utilization`. Check before each step that spends Claude calls (stewards evals).
- **Decisions belong to the user:** switch-over timing, deleting the Neon project, publishing the Python client to PyPI, adding a root LICENSE, and anything that costs money (F1TV subscription). Ask; don't default.
- **Report after each major step:** one short status, what passed, what failed with the exact error, and the decision needed.

## 1. Repos and branches

| Repo | Remote | Branch to deploy | Notes |
|---|---|---|---|
| Backend | `github.com/iyin141/F1-project` | `v2/integration` | Feature branches `v2/infra`, `v2/trackmap`, `v2/chaos`, `v2/stewards` and `v2/docs` are all merged into it. The remote `v2/stewards` is stale and fully merged; ignore it. |
| Frontend | `github.com/iyin141/F1-PROJECT-FRONTEND` | `v2/ui` | The 3D replay is parked on `v2/ui-3d` (needs `npm install` on the VM, see 4.2). |

The user's original checkout on the PC was `All_Endpoints_integrated` (backend) and `master` (frontend). Merging v2 into those, or creating `main`, is the user's decision.

## 2. Read these, in this order

1. `docs/v2/VM_RUNBOOK.md`: **the master checklist for the backend**, 12 steps, each with a "Pass:" line. Follow it exactly.
2. `deploy/RUNBOOK_DB.md`: Postgres inside the stack, backups, and the Neon migration (step 4 of the runbook).
3. `backend/api/assistant/VM_TESTING.md`: Stewards build, model cache, corpus, retrieval and e2e evals, and MCP (step 8 of the runbook).
4. `docs/v2/plans/KUMO_SETUP.md`: Kumo weights. They are **already downloaded on the VM**, so run with `HF_HUB_OFFLINE=1`.
5. `docs/v2/API_TEST_2026-11-24.md`: what the real-data API test on the PC found. Use it as the baseline for comparison.
6. `README.md`: what the system is, the endpoints, and the measured numbers. Update its numbers from your VM results.
7. `docs/v2/progress/*.md`: each feature's decisions and deferred items, if you need detail.
8. Frontend: `docs/v2-ui/PROGRESS.md` and `docs/v2-ui/U1F_VM_FINISH.md` (on `v2/ui-3d`).

## 3. Known facts that change how you run things

- **F1 data:**
  - F1's livetiming static archive has returned **401 to unauthenticated requests since about 2026-10-15**, and the FastF1 mirror has no 2025 or 2026 data.
  - The old webshare proxy in `.env` returns **402**, out of credit, so don't rely on it.
  - Use the **existing FastF1 cache** at `/home/ubuntu/F1-project/backend/f1_cache` (runbook step 5).
  - Only if a needed session isn't cached: FastF1 3.9.2 supports an F1TV login, `FASTF1_AUTH=token` (runbook step 6). It needs an active F1TV subscription, which is the user's decision.
- **Neon data:** stored telemetry exists only for 2026 R1 and R5 (race), `track_status_data` is empty, and race results span 3 seasons. The v2 features need the seeding in runbook step 7 before they show anything real.
- **The migration script** was fixed after a real test: it dumps only Neon's `public` schema, wipes, restores, migrates, then compares counts on Neon's own tables. A rehearsal is available as `make test-neon-migration`.
- **Circuit matching** was verified on PC against the real stored schedule: 136 races, 0 unmatched. If logs show `[chaos] UNMATCHED CIRCUIT ...`, add that exact text as an alias in `backend/api/chaos/data/circuits.yaml`, with a test case.
- **Track map:** the build tries sessions Q, then SQ, then R, then S. A miss returns 202 quickly. A recent failure returns 503 with `Retry-After`, so retry after the cache TTL (300 s).
- **Stewards** run only on `worker-rag`, never web. Retrieval rerank is OFF by default; turn it on only if the arm64 bench (`bench_reranker`) and the eval justify it. The LLM is the `claude` CLI on the user's subscription, with the host `~/.claude` mounted. There is no API key.
- **Memory budget:** limits total about 10.9 GB without the `ml` profile and about 14.9 GB with it. The VM has other apps, so check `free -h` before `make up-ml`, and lower `worker-ml` if needed.

## 4. What to do, in order

### 4.1 Backend (the main job)

Follow `docs/v2/VM_RUNBOOK.md` steps 0-10 exactly. Stop at step 11 (switch-over) and ask the user. Then:
- **Chaos:**
  - run `chaos_backtest --backfill-kumo` per the runbook;
  - put the real Brier, log-loss, AUC and ECE numbers and the calibration plot data into the README model card;
  - check that the Canada sanity line is near 60%.
- **Stewards:**
  - finish the corpus fetch and `ingest_corpus`;
  - run `assistant_eval retrieval`, expecting recall@8 around 0.87, or about 0.895 with the year filter;
  - run one `assistant_eval e2e`: about 60 Claude calls and about $0.45, so check the usage caps first;
  - run `bench_reranker` on arm64.
- **Snapshot:** run the 10-route before/after (runbook step 9). Every default response must be identical. Explain any diff before switch-over.
- **Fill in the README** "DEFERRED-VM" table with the results (it has 15 rows).

### 4.2 Frontend

1. **3D replay:** follow `docs/v2-ui/U1F_VM_FINISH.md` on `v2/ui-3d`:
   - `npm install --save-exact --legacy-peer-deps three@0.187.0 @react-three/fiber@9.8.2 @react-three/drei@10.7.9 @types/three@0.187.0`, or the documented overrides entry, but not both;
   - then `tsc`, lint and build, and confirm the 3D chunk is split;
   - take the WebGL screenshot;
   - merge into `v2/ui`. The listed files will conflict.
2. **Playwright:**
   - `npm install --save-dev --save-exact @playwright/test` and `npx playwright install chromium`, then commit the lockfile;
   - run `e2e/` against a mock-mode build first, then live against the new backend;
   - the specs have never run, so selectors may need small fixes.
3. **Build** the frontend Docker image (standalone, arm64), add it to the deployment behind nginx at `/`, and point `BACKEND_URL` at the new API.
4. **Lighthouse:** `scripts/perf.sh` with `lighthouse/lighthouserc.json`. The budgets are race hub LCP under 2.5 s on 4G, and the lab interaction under 100 ms (via `e2e/perf.spec.ts`).
5. **Live-mode check:** set `NEXT_PUBLIC_API_MODE=live` and click through the race hub, lab, chaos and stewards pages against real data.

### 4.3 Open items waiting on the user (ask; don't decide)

- Switch-over time, and when to delete the Neon project afterwards.
- `main` branch and `v1.0` tag; merging v2 into `All_Endpoints_integrated`/`master`.
- Root LICENSE (MIT suggested).
- Publishing `clients/python/f1controlroom` to PyPI.
- The existing views' throttle-cost bug. They set `request.endpoint_type` after the throttle runs, so the `ENDPOINT_COSTS` table is dead config. Costs today match the URL fallback, and the fix is optional.
- The track-status endpoint loads FastF1 live (slow, 200 with a failed body). That's existing behaviour, and fixing it is optional.
- Rotating `SECRET_KEY` and the webshare proxy password: both were exposed during the build.
- The MCP server compose service isn't wired in yet. The README documents running it.

## 5. When you finish

- Update the README numbers and the DEFERRED-VM table.
- Commit on `v2/integration` with no attribution lines, and push with the user's fresh token.
- Write `docs/v2/VM_RESULTS_<date>.md`: every runbook step's Pass/Fail, the measured numbers, and the decisions still pending.
- Report to the user in a few lines.
