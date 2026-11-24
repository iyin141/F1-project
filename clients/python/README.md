# f1controlroom

Typed Python client for the [F1 Control Room API](../../README.md): v1 data (schedules, results, laps, telemetry), v2 track map and mini-sectors, Chaos Point predictions, and the Stewards assistant's streaming answers.

Version 0.1.0, MIT. Not published to PyPI; install from the folder:

```bash
pip install ./clients/python            # needs Python 3.9+, pulls in httpx only
pip install "./clients/python[test]"    # plus pytest
```

Built on `httpx` rather than `requests`: one dependency covers a sync client, response streaming (the assistant answers over Server-Sent Events), per-phase timeouts, and a built-in `MockTransport`, so the tests need neither a network nor a mocking library.

## Use

```python
from f1controlroom import F1Client

c = F1Client("YOUR_API_KEY", "https://your-host")   # sends X-API-Key; base_url with or without /api

c.schedule(2026)
c.laps(2026, 5, driver="NOR")
c.telemetry(2026, 5, driver="NOR", lap=10,
            channels=["speed", "throttle", "brake"], format="columnar", start_m=1000, end_m=2000)
c.chaos_race(2026, 5, model="baseline")
c.chaos_circuits_summary()
```

Every public GET endpoint of v1 and v2 has a method (`results`, `qualifying`, `driver_career`, `stints`, `pace`, `tyre_strategy`, `weather`, `pit_stops`, `incidents`, `track_status`, `track_map`, `mini_sectors`, `telemetry_delta`, `chaos_drivers`, `chaos_laps`, `chaos_circuit_history`, `chaos_driver_profile`, `chaos_model`, and so on). Responses are the decoded JSON. For anything not wrapped, `c.get("some/path/", param=value)` does the same thing: `None` parameters are dropped and lists are joined with commas.

### 202 pending

The track map, mini-sectors, delta and Chaos views never block. When the work is queued they answer 202. By default the client raises `PendingError` (with `.task_key`); pass `wait=` to poll instead:

```python
from f1controlroom import PendingError, PendingTimeout

try:
    tm = c.track_map(2026, 5)
except PendingError as e:
    print("queued:", e.task_key)

tm = c.track_map(2026, 5, wait=120)       # polls (Retry-After if sent, else every 2 s); PendingTimeout after 120 s
c = F1Client(key, url, wait=60)           # or set a default for every call
```

### 503 and Retry-After

A recent build failure answers 503 with `Retry-After`. The client waits that long (capped by `max_retry_after`, default 30 s) and retries up to `retries` times (default 2), then raises `ServiceUnavailable` with `.retry_after`. Set `retries=0` to raise at once.

### Errors

All derive from `F1Error` (`.status`, `.body`): `BadRequest` (400), `AuthError` (401, 403), `NotFound` (404), `RateLimited` (429, `.retry_after`), `ServiceUnavailable` (503), `ServerError` (other 5xx), `PendingError` / `PendingTimeout` (202).

### Ask the stewards (SSE)

`ask()` is an iterator over the events: `status`, `token`, `citations`, then `done` or `error`.

```python
for ev in c.ask("What penalty applies for causing a collision?", year=2026):
    if ev.event == "token":
        print(ev.data["text"], end="", flush=True)
    elif ev.event == "citations":
        for cite in ev.data["citations"]:
            print("\n", cite)
    elif ev.event == "error":
        print("failed:", ev.data["code"])         # auth_expired, rate_limited, llm_failed, timeout, internal

answer = c.ask_answer("...", year=2026)           # or collect it: .text, .citations, .done
```

If the connection drops before `done`, `ask()` reconnects through `GET /api/assistant/ask/<task_key>/events` with `Last-Event-ID`, so no token is lost or repeated (up to `max_reconnects`, default 2). `c.ask_events(task_key, last_event_id)` does the same by hand. An `error` event is yielded, not raised; `ask_answer()` raises `F1Error` for it.

A question costs 10 request-units against your key's budget (telemetry costs 5), and answers took 77.5 s median in the project's evaluation.

## Tests

```bash
cd clients/python
pip install ".[test]"
python -m pytest -q          # 19 tests, mocked transport, no network
```
