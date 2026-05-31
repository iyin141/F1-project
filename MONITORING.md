# Monitoring and alerts — f1-project backend

Key signals to monitor after deploying the auth and persistence parity changes.

- Auth DB queries: track rate of DB queries issued to `api_apikey` (or `APIKey` model lookups). Alert if spikes occur after deploying the env-key fast-path.

- Redis availability & cache miss rate: watch `app_cache`, `telemetry` and `rate_limiting` instances for failures or high miss rates (previous fallback warning logged `LocMemCache`).

- TaskManager / Celery: monitor task enqueue/success/failure counts and queue backlogs (task latency > threshold).

- Store parity discrepancies: create a periodic job (daily) that samples persisted rows and compares `payload['data']` with serializer output used by API views; alert if mismatches exceed a small threshold.

- Error/exception rates: monitor application error rate (5xx) and specific exceptions from populate commands (FastF1 load errors, network timeouts).

Suggested alert thresholds

- Auth DB queries: >3x baseline sustained for 5m
- Redis unavailable: any sustained unavailability >1 minute
- Task failure rate: >2% over 15m
- Parity mismatches: >1% of sample rows

Logging tips

- Ensure `event=` structured logs are emitted for key flows: `event=auth_env_fastpath`, `event=auth_db_check`, `event=extracted`, `event=completed`, `event=payload_mismatch`.
- Use JSON structured logging and ship to your log aggregator (ELK/CloudWatch/GCP). Include `year`, `round`, `session`, and `task_key` where applicable.

Dashboards

- Auth dashboard: DB queries over time, requests with `INTERNAL_API_KEY`, 95th percentile request latency.
- Persistence parity dashboard: sample comparisons, recent parity check failures, store calls per minute.
- Celery dashboard: queue depth, worker utilization, task latency histograms.
