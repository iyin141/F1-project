"""Record and compare responses of representative routes on a running stack.

Plan 01 Phase 0 acceptance: "serves every existing endpoint with identical responses
(snapshot-test 10 representative routes before and after)". Stdlib only.

    # before (the legacy start_prod.sh stack) -- on the VM
    python snapshot_routes.py record  --base http://127.0.0.1:8000 --out before.json
    # after (docker compose up) -- on the VM
    python snapshot_routes.py compare --base http://127.0.0.1 --against before.json

The API key is read from $SNAPSHOT_API_KEY (any valid key; sent as X-API-Key).
Exit code 0 = identical, 1 = differences, 2 = a route was unreachable.

Responses are compared as JSON after dropping volatile keys (ids, timestamps, durations);
non-JSON bodies are compared by SHA-256. Edit ROUTES for the year/round you have warmed.
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

ROUTES = [
    "/",
    "/api/schema/",
    "/api/races/2024/",
    "/api/races/2024/1/results/",
    "/api/drivers/search/?q=ver",
    "/api/drivers/standings/2024/",
    "/api/drivers/VER/career/",
    "/api/unified/races/2024/1/weather/",
    "/api/analysis/races/2024/1/pace/",
    "/api/analysis/races/2024/1/tyre-strategy/",
]

# Keys whose values change between identical requests.
VOLATILE = {
    "task_id", "request_id", "timestamp", "generated_at", "created_at", "updated_at",
    "duration", "duration_ms", "elapsed", "elapsed_ms", "cached_at", "ttl", "stream_url",
}


def scrub(o):
    if isinstance(o, dict):
        return {k: scrub(v) for k, v in o.items() if k not in VOLATILE}
    if isinstance(o, list):
        return [scrub(v) for v in o]
    return o


def fetch(base, path, key):
    req = urllib.request.Request(base.rstrip("/") + path, headers={"X-API-Key": key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    body = raw.decode("utf-8", "replace")
    # SSE routes stream "data: {...}" frames; keep only the last frame (the result).
    if body.startswith("data:"):
        frames = [f[5:].strip() for f in body.split("\n\n") if f.startswith("data:")]
        body = frames[-1] if frames else body
    try:
        return {"status": status, "json": scrub(json.loads(body))}
    except ValueError:
        return {"status": status, "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["record", "compare"])
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", help="record: file to write")
    ap.add_argument("--against", help="compare: file written by record")
    a = ap.parse_args()
    key = os.environ.get("SNAPSHOT_API_KEY", "")
    if not key:
        sys.exit("set SNAPSHOT_API_KEY")

    got, unreachable = {}, False
    for path in ROUTES:
        try:
            got[path] = fetch(a.base, path, key)
        except Exception as e:  # connection refused, timeout...
            got[path] = {"error": str(e)}
            unreachable = True
        print(f"{path}  ->  {got[path].get('status', got[path].get('error'))}")

    if a.mode == "record":
        json.dump(got, open(a.out, "w"), indent=1, sort_keys=True)
        print(f"recorded {len(got)} routes to {a.out}")
        return 2 if unreachable else 0

    want = json.load(open(a.against))
    bad = [p for p in ROUTES if got.get(p) != want.get(p)]
    for p in bad:
        print(f"DIFF {p}\n  before: {json.dumps(want.get(p))[:300]}\n  after:  {json.dumps(got.get(p))[:300]}")
    print(f"{len(ROUTES) - len(bad)}/{len(ROUTES)} identical")
    return 2 if unreachable else (1 if bad else 0)


if __name__ == "__main__":
    sys.exit(main())
