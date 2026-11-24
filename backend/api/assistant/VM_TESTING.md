# Testing the Stewards assistant on the Oracle VM

A runbook you can follow without the agent. Everything runs from the repository root on the VM (branch `v2/integration`),
with the compose stack from `deploy/RUNBOOK_DB.md` (Postgres is the `postgres` service, not Neon). Commands marked
**[costs money]** use your Claude subscription quota. Each step says what "pass" looks like. Stop at the first failure and
use the troubleshooting table at the end.

Conventions: `dc` = `docker compose`. Python/Django commands run inside the worker: `dc exec worker-rag python manage.py ...`
(the worker has the database, Redis, model cache, data volume and the Claude login). Set once:

```bash
export KEY=$(grep '^INTERNAL_API_KEY=' .env | cut -d= -f2)     # API key for curl (never paste it into a chat or a log)
alias dc='docker compose'
```

Prerequisites (check once): `.env` is filled in (`POSTGRES_PASSWORD`, `INTERNAL_API_KEY`, `CLAUDE_CONFIG_DIR=/home/ubuntu/.claude`),
`ls -ld $CLAUDE_CONFIG_DIR` shows owner uid 1000 (`stat -c %u ~/.claude` prints `1000`; if not: `sudo chown -R 1000:1000 ~/.claude`),
`deploy/nginx/.htpasswd` exists, and you have logged in on the VM host once with `claude` (then `/login`).

---

## 1. Build the rag image on arm64

```bash
dc build worker-rag          # first build 10-20 min: builds wheels, installs requirements-rag.txt + fastembed (--no-deps), Node 20 and the claude CLI
```

Pass:

```bash
dc run --rm --no-deps worker-rag python -c "import fastembed, onnxruntime, langgraph, tokenizers; print('onnxruntime', onnxruntime.__version__)"
#   -> onnxruntime 1.32.0
dc run --rm --no-deps worker-rag claude --version
#   -> 2.1.305 (Claude Code)
dc run --rm --no-deps worker-rag python -c "import torch" ; echo "exit=$?"
#   -> ModuleNotFoundError ... exit=1   (torch must NOT be installed)
```

The web image must stay light: `dc run --rm --no-deps web python -c "import onnxruntime"` must FAIL.

**If a wheel fails on aarch64** (error like "No matching distribution found for onnxruntime==1.32.0" or a compile attempt
that dies because the image has no compiler). I could not check arm64 wheel availability from the Windows PC; do this:

1. Find out which pin is missing (inside any python 3.13 container on the VM):
   ```bash
   dc run --rm --no-deps --entrypoint sh web -c 'for p in onnxruntime==1.32.0 tokenizers==0.23.3 py-rust-stemmers==0.1.8 mmh3==5.3.1 orjson==3.13.0 ormsgpack==1.13.1 xxhash==4.1.0 zstandard==0.25.0; do pip download --no-deps --only-binary=:all: -d /tmp/w $p >/dev/null 2>&1 && echo "ok   $p" || echo "FAIL $p"; done'
   ```
2. For a failing pin, find the nearest version that has an aarch64 cp313 wheel (`pip index versions <pkg>`, then retry the loop with that version) and change that one line in `backend/requirements-rag.txt`. onnxruntime, fastembed and tokenizers do not need to match the versions used on the PC exactly; re-run step 5 afterwards to confirm retrieval did not move.
3. If a package only has an sdist, add the compiler back to the builder stage (A0 notes it was removed: `build-essential` in `backend/Dockerfile` stage 1) or use the offline wheelhouse (`backend/wheelhouse/*.whl`, tried first).
4. `fastembed` itself is installed with `--no-deps` on purpose (it caps pillow<12; the project pins 12). Do not "fix" that.

Bring the stack up (the web entrypoint applies migrations, including the pgvector one):

```bash
dc up -d
dc ps                         # postgres, redis-*, web, worker-rag, nginx: all "healthy"/"running"
dc exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c "\dx"      # vector 0.8.x listed
dc exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c "\d assistant_docchunk"   # has embedding vector(384), search_vector tsvector, hnsw + gin indexes
```

(`POSTGRES_USER`/`POSTGRES_DB` come from `.env`: `set -a; . ./.env; set +a`.)

## 2. Seed the model cache (`stewards_models` volume)

`worker-rag` runs with `HF_HUB_OFFLINE=1`, so the models must already be in the volume. The Hugging Face CDN is slow and
flaky from some networks; the reliable way is to copy the cache from the PC (about 200 MB: bge-small INT8 + the MiniLM reranker).

On the PC (Git Bash, repo root; a ready tarball may already exist at `backend/api/assistant/data/stewards-models.tgz`):

```bash
tar czf stewards-models.tgz -C backend/api/assistant/data/models models--Qdrant--bge-small-en-v1.5-onnx-Q models--Xenova--ms-marco-MiniLM-L-12-v2
scp stewards-models.tgz <vm>:/tmp/
```

On the VM:

```bash
dc up -d --no-start worker-rag                                  # creates <project>_stewards_models
VOL=$(docker volume ls -q | grep stewards_models)
docker run --rm -v $VOL:/m -v /tmp:/in alpine sh -c "tar xzf /in/stewards-models.tgz -C /m && chown -R 1000:1000 /m && ls /m"
dc up -d worker-rag
```

Pass (the worker can load the embedder offline and the vector has 384 dimensions):

```bash
dc exec worker-rag env | grep -E 'HF_HUB_OFFLINE|STEWARDS_'      # HF_HUB_OFFLINE=1, STEWARDS_MODEL_CACHE=/stewards/models, STEWARDS_DATA_DIR=/stewards/data
dc exec worker-rag python -c "
from api.assistant.embeddings import embed_query
v = embed_query('time penalty for causing a collision'); print(len(v))"
#   -> 384   (first call 1-3 s: model load; no network access attempted)
```

Alternative without the PC: Range download inside the container (resumable; ignore if the tarball worked):
`dc exec -e HF_HUB_OFFLINE=0 worker-rag python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/stewards/models')"`
(if it sits at 0 bytes for a minute, it is the known Hugging Face stall: use the tarball).

## 3. The Claude CLI uses the mounted login

One real call with exactly the flags `llm.py` uses for the planner **[costs money, about 0.2 cent]**:

```bash
dc exec -T worker-rag sh -c 'cd "$(mktemp -d)" && echo "Reply with exactly: pong" | claude -p --output-format json --model claude-haiku-5-5 --tools "" --no-session-persistence --disable-slash-commands --safe-mode --effort low --append-system-prompt "You are a connectivity test."'
```

Pass: one JSON object containing `"is_error":false` and `"result":"pong"`, plus `total_cost_usd` around 0.001.

Auth-expired symptom: `"is_error":true` with a result like `Not logged in · Please run /login` (or HTTP 401). In the app this becomes an
`error` SSE event with `"code":"auth_expired"` and the message "The assistant's Claude login has expired; the operator must renew it.". Fix: on the VM host
run `claude`, `/login` as the same user whose `~/.claude` is mounted, then repeat the call above (no restart needed; the file
is read per call). The mount must be writable (token refresh writes to it) and owned by uid 1000.

Rate limit symptom: `usage limit` text and an `error` event `rate_limited`: wait for the quota window; nothing to fix.

## 4. Corpus: fetch, ingest, counts

**Fast path (recommended): restore the exact corpus used for the evaluation.** The PC has a dump of the corpus tables
(`backend/api/assistant/data/stewards_corpus.dump`, 11 MB, made with `pg_dump -Fc --data-only -t assistant_documentsource -t assistant_docchunk`; contains vectors and FIA text, keep it private; gitignored). This reproduces the
eval snapshot byte for byte and skips hours of polite fetching.

PC -> VM: `scp backend/api/assistant/data/stewards_corpus.dump <vm>:/tmp/`. On the VM:

```bash
set -a; . ./.env; set +a
dc exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c "select count(*) from assistant_documentsource"       # 0 on a fresh stack
docker cp /tmp/stewards_corpus.dump $(dc ps -q postgres):/tmp/c.dump
dc exec -T postgres pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --data-only --no-owner /tmp/c.dump
dc exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c "select setval(pg_get_serial_sequence('assistant_documentsource','id'), max(id)) from assistant_documentsource; select setval(pg_get_serial_sequence('assistant_docchunk','id'), max(id)) from assistant_docchunk;"
dc exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c "select doc_type, count(*) sources, count(*) filter (where ingested_at is not null) ingested from assistant_documentsource group by 1 order by 1"
```

Pass: the same counts as the PC at dump time (2026-11-24): **616 sources registered, 387 ingested, 3,721 chunks** (`select count(*) from assistant_docchunk`); the 79
snapshot sources must be present and ingested: `dc exec worker-rag python manage.py assistant_eval check-gold` prints
`gold citations missing from the snapshot corpus: none`. The PDFs themselves are not needed to answer questions (only the
text and vectors in Postgres are); copy them only if you want to re-ingest.

**Slow path / adding documents: fetch from the FIA** (polite: robots.txt Crawl-delay 10 s, resumable, skips what is registered).
Run detached, one at a time; never two fetchers at once:

```bash
dc exec -d worker-rag sh -c 'python -u manage.py fetch_corpus --reg-years 2022 2023 2024 2025 2026 --limit 50 > /stewards/data/fetch_regs.log 2>&1'
dc exec worker-rag tail -n 5 /stewards/data/fetch_regs.log     # "stored  sporting_regs ..." lines
```

Expected: about 10 regulation PDFs (Sporting + Technical per year; 2026 gives Section B and C), 5-15 minutes. Then decisions and event notes (2-4 hours each season):

```bash
dc exec -d worker-rag sh -c 'python -u manage.py fetch_corpus --seasons 2026 --limit 2000 > /stewards/data/fetch_2026.log 2>&1; python -u manage.py fetch_corpus --seasons 2025 --limit 2000 > /stewards/data/fetch_2025.log 2>&1'
```

Expected from the 2026 season page about 650 decision/note PDFs (summons excluded; use `--include-summons` to add them). A TLS drop
on a large PDF prints `FAILED ... SSLError`; the run goes on and the next run retries it. To resume after a restart: run the same
commands again (already-registered URLs are skipped without a request). Then embed and store:

```bash
dc exec -d worker-rag sh -c 'python -u manage.py ingest_corpus > /stewards/data/ingest.log 2>&1'   # or enqueue: dc exec worker-rag python -c "from api.assistant.tasks import ingest_pending; ingest_pending.delay()"
dc exec worker-rag grep -c "'status': 'ingested'" /stewards/data/ingest.log
```

Pass: `select count(*) filter (where ingested_at is null) from assistant_documentsource` goes to 0 (a decision PDF is about 1-2 s on the PC; regulations
about 0.5 s per page, so the 2026 Sporting Regulations take 1-2 minutes; expect up to 2x slower on arm64).
Reference row counts from the PC (2026-11-24): 79 sources / 1,728 chunks in the evaluation snapshot; about 440 registered sources after the
2026 season fetch had run for several hours, ingested progressively. Regulations: 2022 Sporting about 213 chunks, 2024 Sporting about 223, 2025 Sporting about 243, 2023 Technical about 338, 2025 Technical about 342, 2026 Section B about 193.
`fetch_corpus --reg-years` could not download 2022 Technical, 2023 Sporting, 2024 Technical and 2026 Section C on the PC (TLS drops); try them again on the VM.

## 5. Retrieval checks

```bash
dc exec worker-rag python manage.py assistant_eval retrieval --pool 20        # 77 questions, no LLM, 10-25 min (CPU only)
```

It prints a table and saves `evals/results/<stamp>_retrieval.json` inside the container
(`dc cp worker-rag:/app/api/assistant/evals/results/ ./vm-results/` to keep it). It only works if the 79 snapshot sources are in the DB (step 4 fast path).

Pass, with the PC's numbers and a tolerance of +-0.03 (two questions of 77):

| Mode | recall@8 | MRR |
|---|---|---|
| FTS only | 0.714 | 0.546 |
| vector only | 0.818 | 0.514 |
| RRF | **0.870** (0.84 - 0.90) | 0.588 (0.54 - 0.64) |
| RRF + rerank 700 chars | 0.844 | 0.660 |
| RRF + rerank + year filter | **0.895** (0.865 - 0.925) | 0.795 (0.74 - 0.85) |

Larger differences mean the VM has a different corpus, different model files (the INT8 bge file must be the 66 MB `model_optimized.onnx`),
or a Postgres text-search config difference: stop and compare `dc exec worker-rag python manage.py assistant_eval check-gold` and the model cache listing.

Reranker latency on arm64 (only needed to decide about turning it on):

```bash
dc exec worker-rag python manage.py bench_reranker --pairs 20 30 --max-chars 700
```

PC reference (4 fast cores): 20 pairs about 1.9 s, 30 pairs about 2.7 s median. Keep `STEWARDS_RERANK=0` (the default). Turn it on
(`STEWARDS_RERANK=1` in the worker environment) only if 20 pairs take under 3 s on the VM and you want better ordering of the top
results (it raises recall@1 0.44 -> 0.56 but lowers recall@8 0.870 -> 0.844); memory then rises by about 300 MB per worker process.

## 6. End to end through nginx

```bash
curl -N -sS -X POST http://localhost/api/assistant/ask -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"question":"What is the minimum mass of an F1 car in the 2023 technical regulations?","year":2023}' | tee /tmp/ask.sse    # [costs money, about 5 CLI calls, about 4-6 cents]
```

Pass: events arrive as the work happens (the first one within a second, not all at the end: nginx has buffering off for `/api/`), in this order:

```
event: status   {"phase":"queued", ... "task_key":"ask-<32 hex>"}
event: status   {"phase":"solving"}      <- planner
event: status   {"phase":"searching", "tools":["search_documents"]}
event: status   {"phase":"solving"}      <- the planner may repeat solving/searching 1-3 times
event: status   {"phase":"composing"}
event: token    {"text":"..."}           <- many, a few words each
event: citations {"citations":[{"id":"E1","title":"2023 F1 Technical Regulations ...","article":"4.1","page":45,"url":"https://www.fia.com/...","extract":"...<=300 chars"}]}
event: done     {"grounded":true,"not_found":false,"answer":"... 798 kg ...","rounds":1-3,"cost_usd":0.03-0.06,"long_quotes":0}
```

Check: `done.grounded` is `true`, `invalid_citations` is `[]`, the answer says 798 kg and the citation points at article 4.1 of the 2023 Technical
Regulations. Expected time 50-120 s (planner rounds about 7 s each, the Sonnet answer 15-40 s). A question the corpus cannot answer
(`"What were the qualifying lap times at the 2023 British Grand Prix?"`) must end with `done` and `"answer":"Evidence not found."`.

Without a key you must get 401/403 (the same as `/api/analysis/...`); a malformed body gets 400 and no task is queued.

Reconnect (replays everything, or resumes after an event id; use the `task_key` from the first event):

```bash
TK=$(grep -o 'ask-[0-9a-f]\{32\}' /tmp/ask.sse | head -1)
curl -N -sS http://localhost/api/assistant/ask/$TK/events -H "X-API-Key: $KEY" | grep -c '^event:'            # same number of events as the first run
curl -N -sS http://localhost/api/assistant/ask/$TK/events -H "X-API-Key: $KEY" -H "Last-Event-ID: 3" | head -3  # starts at id 4
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost/api/assistant/ask/ask-00000000000000000000000000000000/events -H "X-API-Key: $KEY"   # 404
```

Throttle: an ask costs 10 tokens (`ENDPOINT_COSTS["assistant_ask"]`); a free-tier key (capacity 60) gets about 6 asks per burst, then HTTP 429.

Evaluation end to end **[costs money]** (the budget is the harness's `--max-calls`; each question is about 5 calls and 4-6 cents):

```bash
dc exec worker-rag python manage.py assistant_eval e2e --ids q011 q022 q038 q053 q090 --max-calls 30      # about 25 calls, about $0.25, about 7 min
```

Pass (PC reference, 10 questions, 53 calls, $0.45): correctness at least 8 of 10, `citation_hit_rate` 1.0 on answerable questions,
both unanswerable questions answered "Evidence not found." (`evidence_not_found` precision and recall 1.0), median 75-95 s per question.
Full 10-question set: `--ids q011 q022 q038 q053 q060 q075 q090 q093 q007 q077 --max-calls 60`.

## 7. MCP server

The server speaks stdio: a client starts it as a child process. On the VM, from the repo root:

```bash
dc run --rm -T --no-deps worker-rag python -c "import mcp; print(mcp.__file__)"      # the SDK must be in the image (see note)
```

Note: `mcp==2.3.0` is listed in `backend/api/assistant/NEEDS.md`; until it is in `requirements-rag.txt` and the image is rebuilt, install it for this
test only: `dc run --rm -T --no-deps worker-rag sh -c "pip install --user mcp==2.3.0 && python ..."` (or add the line to `requirements-rag.txt` and `dc build worker-rag`).

One tool call over stdio (this starts `python mcp/server.py` inside the container and calls the document search):

```bash
dc run --rm -T --no-deps worker-rag python - <<'PY'
import asyncio, json
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
async def main():
    p = StdioServerParameters(command="python", args=["mcp/server.py"], cwd="/app")
    async with Client(p) as c:
        print(sorted(t.name for t in (await c.list_tools()).tools))
        r = await c.call_tool("f1_search_documents", {"query": "penalty for causing a collision", "year": 2026, "limit": 2})
        print(r.is_error, json.loads(r.content[0].text)["results"][0]["article"])
        r = await c.call_tool("f1_get_incidents", {"year": 2026, "round": 1})
        print(r.is_error, r.content[0].text[:120])
asyncio.run(main())
PY
```

Pass: the first line lists seven tools starting with `f1_` (`f1_get_chaos`, `f1_get_incidents`, `f1_get_race_results`,
`f1_get_race_schedule`, `f1_get_track_map`, `f1_get_track_status`, `f1_search_documents`); the search prints `False B1.9.5` (or a nearby article of
the 2026 Sporting Regulations); the incidents call prints `True` plus a message that names the web endpoint to populate the data when
nothing is stored (and `False` plus rows once the race data exists). No tool writes anything or calls FastF1.

Using it from a client (Claude Desktop / an IDE), register: command `docker`, args `["compose","-f","/path/to/docker-compose.yml","run","--rm","-T","--no-deps","worker-rag","python","mcp/server.py"]`.

## 8. Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| `FAILED ... SSLError DECRYPTION_FAILED_OR_BAD_RECORD_MAC` while fetching a large PDF, or a curl `SEC_E_DECRYPT_FAILURE` | long TLS streams drop on some networks (seen on the PC, possibly not on the VM) | nothing to fix: the fetcher already downloads in 2 MB Range chunks and retries 6 times; run the same fetch command again, it resumes. If it never completes, download that PDF elsewhere and register it with `store_pdf` via a shell, or skip it. |
| Model download sits at 0 bytes / `huggingface_hub` hangs | Hugging Face CDN stall | seed the volume from the tarball (step 2); never rely on the download. `HF_HUB_OFFLINE=1` is on purpose. |
| `LocalEntryNotFoundError` / "cannot find the requested files in the local cache" | the model cache volume is empty or has the wrong ownership/layout | redo step 2; `dc exec worker-rag ls /stewards/models` must show `models--Qdrant--bge-small-en-v1.5-onnx-Q` (and the Xenova one); `chown -R 1000:1000`. |
| `error` event `auth_expired` or `claude` JSON `Not logged in` | login expired or mount not readable/writable by uid 1000 | step 3: log in again on the host; `stat -c %u ~/.claude` must print 1000; `CLAUDE_CONFIG_DIR` in `.env` must be the host path. |
| `error` event `rate_limited` | the subscription usage window is used up | wait; reduce `--max-calls`; asks are 5 CLI calls each. |
| worker killed, `docker inspect` shows `OOMKilled=true`, or `Killed` in the worker log | `worker-rag` limit is 1 GB: each of the 2 prefork children holds Django + the embedder (about 300 MB) and each running question adds a Node `claude` process (200-300 MB, estimate) | check `docker stats worker-rag` during a question. Either set `-c 1` in the worker command or raise `deploy.resources.limits.memory` to 2g (compose edit; keep `STEWARDS_RERANK=0`, the reranker adds about 300 MB per child). |
| no SSE events until the end, or the stream stops at about 60 s | a proxy buffers or times out | nginx for `/api/` has `proxy_buffering off` and a 300 s read timeout; a Cloudflare/other proxy in front must not buffer `text/event-stream`. |
| HTTP 429 from `/api/assistant/ask` | token bucket: an ask costs 10 | wait or use a higher-tier key. |
| `assistant_eval` says "N snapshot sources are not in this database" | corpus not restored from the dump, or the FIA re-published a PDF (different sha256) | use the step 4 fast path. |
| The answer is "Evidence not found." for a question that the corpus should answer | no year filter and near-identical articles across years, or the source is not ingested | pass `"year"` in the request (also inferred when the question names one year); check `select count(*) from assistant_docchunk` and `ingested_at is null`. |
| Slow first answer after a restart | the embedder loads on the first question (1-3 s) and the Claude CLI cold start | expected; later questions are faster. |
| `migrate` fails on `CREATE EXTENSION vector` | the Postgres image is not `pgvector/pgvector` | the stack uses `pgvector/pgvector:0.8.0-pg17`; a plain postgres image cannot run the assistant migration. |

Expected latency (PC, 4 cores; the VM is similar because the time is spent in the Claude calls): query embedding about 7 ms (arm64 maybe 20-30 ms),
retrieval without rerank about 30 ms, with rerank about 2 s, a full answer 50-120 s (3 planner rounds at about 7 s plus the Sonnet answer), ingestion about 0.5 s
per regulation page.
