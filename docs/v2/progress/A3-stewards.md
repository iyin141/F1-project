# A3 stewards progress

## Phase 3a: corpus and ingestion

Status: done, awaiting review. One gap: the real bge model could not be downloaded here (see Local ingestion).

Files (all under `backend/api/assistant/`): `models.py`, `migrations/0001_initial.py`, `fetch.py`, `chunking.py`, `embeddings.py`, `ingest.py`, `tasks.py`, `management/commands/fetch_corpus.py`, `tests/` (4 files + `pdf_fixture.py`), `NEEDS.md`, `.gitignore` (`data/`).

Tests: full suite 314 passed, 2 failed (known readiness pair), 17 skipped. Baseline 295/2/16, so +19 passed, +1 skipped (the live pgvector test, which runs only with `STEWARDS_PG_DSN`, and passed against the local container), no new failures.

### Sources and terms
- Regulations: `https://www.fia.com/regulation/category/110` lists every issue as a PDF (`/system/files/documents/fia_<year>_f1_regulations_-_section_<a-f>_..._iss_NN_...pdf`). The fetcher keeps the latest issue per (year, section).
- Stewards' decisions and event notes: `https://www.fia.com/documents/championships/fia-formula-one-world-championship-14` lists the current event's `/system/files/decision-document/<year>_<event>_-_<subject>.pdf`. Typed by file name (infringement/decision/summons = stewards_decision; competition/race director notes = event_notes). Results sheets are skipped. Older events: the per-season pages are linked from the same listing (not crawled in 3a).
- robots.txt: only `/user/*` is disallowed; `Crawl-delay: 10`. The fetcher checks robots per host, waits 10 s between requests, sends `F1ControlRoomCorpusFetcher/1.0 (small research corpus; polite, rate-limited)`, retries 3 times, rejects non-PDF and truncated bodies.
- **Terms and conditions risk (flag for the user).** FIA site T&C (https://www.fia.com/file/83930/download, clauses 3.4, 3.5, 3.9) say the copyright in FIA Publications vests in the FIA and that reproducing or using content in any way needs prior written consent, with only private non-commercial printing and short quoted extracts (with reference) allowed. So: the PDFs stay in a gitignored local dir, are never committed or served, and the assistant should answer with short quoted extracts plus citation, never dump full text. For a public deployment, ask the FIA for permission or keep the corpus private. This is a legal call for the user, not me.

### Choices
- PDF parser: `pypdf` (BSD, pure Python, arm64 trivially, no native lib). Slow (about 0.5 s per page; the 101-page Sporting Regulations take about a minute), acceptable as a one-off background task. PyMuPDF is about 50x faster but AGPL; pdfplumber/pdfminer are slower. The PDFs are single-column text PDFs, so extraction quality is fine.
- Chunking: paragraph packing driven by the FIA numbering (`B5.10.1`, `33.4`, `ARTICLE B9:` headings). Running headers/footers removed statistically (short lines on at least 40 % of pages), contents pages dropped. Chunks close at 450 estimated tokens, never mix top-level articles, and close early (once at 300) at a new numbered sub-heading. Token count is words x 1.3 (no tokenizer download: the reference pipeline lost time to tiktoken fetching its vocabulary). On the real Sporting Regulations: 193 chunks, median about 345 tokens, max 450; 9 chunks under 30 tokens (very short articles such as B5.16). `article` = number of the first paragraph in the chunk; `section` = nearest heading; `page` = start page. Known limit: appendix sub-numbering without a letter prefix ("1.1 Brake friction...") gives article "1.1".
- Embeddings: `fastembed` (ONNX Runtime) with `BAAI/bge-small-en-v1.5`, 384-d, no torch (about 100 MB installed versus about 2 GB with sentence-transformers). Caveat found: fastembed's registry serves the INT8-quantised export (`Qdrant/bge-small-en-v1.5-onnx-Q`), not fp32. Recall effect is unmeasured (Phase 3e eval). Queries need the BGE instruction prefix (`embed_query` does it, for 3b).
- Storage: `DocChunk.embedding` is pgvector `VectorField(384)`; `search_vector` is a bare custom `tsvector` column (`django.contrib.postgres` is not in INSTALLED_APPS and settings are not mine), filled by `UPDATE ... to_tsvector('english', text)` after insert. HNSW (`vector_cosine_ops`, m 16, ef_construction 64) and GIN indexes are in the migration only (`RunSQL`), not `Meta.indexes`, so the SQLite test DB still builds the tables from models (`vector`/`tsvector` are just type names on SQLite).
- Idempotency (lessons from the reference pipeline's ledger): `DocumentSource.sha256` is unique (same bytes under another URL = same source); embedding runs before the transaction; chunks and `ingested_at` are written in ONE transaction, so there is never a half-ingested document; a source with `ingested_at` is skipped with no embedding call; `unique(source, chunk_index)`; `force=True` replaces the chunks. Tasks: `api.assistant.tasks.ingest_document` and `ingest_pending` (rag queue by module route).
- Download robustness: curl/schannel on this Windows machine truncates large downloads (`SEC_E_DECRYPT_FAILURE`), so `store_pdf` requires `%PDF` header and `%%EOF` tail, and the fetcher checks Content-Length.

### Local Postgres
Container `f1-stewards-pg`, image `pgvector/pgvector:0.8.0-pg17` (already on the machine; Docker Hub pulls failed on this network), port 5433, db `f1_stewards`, volume `f1-stewards-pgdata`. Migration `assistant.0001` applied there. Never Neon. Run commands with `SECRET_KEY=dummy DATABASE_URL=postgres://postgres:stewards@localhost:5433/f1_stewards` (settings need both; the real `.env` was not used).

### Local ingestion
Fetched for real (5 files, 10 s apart, robots-checked): Sporting Regulations 2026 Section B issue 09 (101 pages), three Las Vegas GP 2026 stewards' documents (infringement car 6, race deleted lap times, infringement car 11), one event note (Pirelli competition notes v3). Stored under `backend/api/assistant/data/` (gitignored).

Local `f1-stewards-pg` after `ingest`: 5 `DocumentSource` rows, **200 `DocChunk` rows** (193 regulations, 5 decisions, 2 event notes), all with vector(384) and tsvector filled, HNSW and GIN indexes present, full-text query `time penalty collision` matches. Chunk size 12-450 estimated tokens (decisions 118-449).

**Caveat: those vectors are NOT bge vectors.** The Hugging Face CDN (`us.aws.cdn.hf.co`) delivered about 4-7 KB/s here and the DNS failed intermittently, so the 67 MB ONNX file did not finish (partial parts are in `data/models/...onnx.parts`; `fastembed` itself stalled at 0 bytes). To prove the pipeline, the five sources were ingested with a deterministic hash-based stand-in embedder (same 384 dims, L2-normalised, no semantic meaning). `embeddings.py` and the fastembed path are therefore untested against the real model (unit tests mock it). To replace them with real vectors, once the model is cached or on a machine with normal network: `python manage.py ingest_corpus --force` (default model cache `api/assistant/data/models`, or `STEWARDS_MODEL_CACHE`). Retrieval work (3b) must not start from these vectors.

DEFERRED-VM: ingestion speed and onnxruntime on arm64 (not measured); Docker image changes for the rag worker (fastembed install with `--no-deps`, see NEEDS.md).
DEFERRED (approval): `CREATE EXTENSION vector` and migration 0001 on Neon (production DB). Migration 0001 must not be run against Neon until the user approves.

Open questions
- Use fp32 bge-small (register a custom fastembed model from `BAAI/bge-small-en-v1.5` `onnx/model.onnx`, 133 MB) instead of the INT8 default? Decide after the 3e recall numbers.
- Which years/sections to ingest for real (all F1 Sections A-F per year, how many past years of decisions)? The listing pages expose only the current event's documents; past events need the per-season pages (not crawled yet).
- FIA T&C question above.

Needs from orchestrator
- `requirements.txt`: add the pins in `api/assistant/NEEDS.md`; `fastembed` must be installed `--no-deps` (it caps `pillow<12`; the project pins 12.0.0 and fastembed never loads Pillow for text models).
- Dockerfile for the rag worker: HF model cache must be a persistent volume (`STEWARDS_MODEL_CACHE`), and the HF download is slow/flaky from some networks.
- Optional: `django.contrib.postgres` in INSTALLED_APPS would allow `SearchVectorField`; not required.

## Phase 3b: hybrid retrieval

Status: code, tests and measurements done, awaiting review. Corpus growth: see "Corpus scope" below.

Files (under `backend/api/assistant/`): `retrieval.py`, `fetch.py` (ranged downloads, older regulation names, season/event discovery), `management/commands/fetch_corpus.py` (more options), `management/commands/bench_reranker.py`, `tests/test_retrieval.py`, `tests/test_fetch_scope.py`.

Tests: assistant app 28 passed, 3 skipped without `STEWARDS_PG_DSN`; with the local container DSN, all 31 pass.

### Real model
bge-small (INT8 ONNX, 66 MB) downloaded after the PC restart with a parallel, resumable HTTP-range downloader (huggingface_hub and fastembed's own download stall at 0 bytes on this network; plain requests with ranges works). `ingest_corpus --force` then replaced the stand-in vectors: the 200 local chunks now hold real bge-small vectors. Measured (this dev PC, not the VM): query embedding 7 ms median, model load 1.4 s, retrieval without rerank (embed + FTS + vector + RRF + load) 26 ms median on 200 chunks. Quoted recall numbers: none. There is no eval set yet (3e), so nothing here is a recall number.

### Pipeline (`retrieval.py`)
`retrieve(question, year=, doc_type=, race=, top_k=8, pool=30, rerank=True)`: FTS top-50 (`ts_rank` over the tsvector, OR-joined terms because AND-ing a natural question returns nothing) and pgvector cosine top-50 (HNSW, `ef_search` 100, `iterative_scan` when pgvector >= 0.8 so filters do not starve the result), raw SQL; RRF with k = 60 (Cormack 2009; `score = sum 1/(60 + rank)`, ties broken by best rank then id); the top `pool` fused hits go to the reranker; top 8 returned. Each `Hit` has full `text` (for reranking and prompting only), `extract` (at most 300 characters, cut at a word), page, article, section, source URL and title, doc type, year, race, reranker score, FTS rank, vector rank, RRF score. `search(cur, ...)` is the same pipeline on any cursor (used by the live test on TEMP tables).

### Reranker: numbers (CPU, this PC, MiniLM-L-12, ms per query)
| Setting | 20 pairs | 30 pairs | 50 pairs |
|---|---|---|---|
| full passages (about 345 tokens) | - | 5,850 | 10,500 |
| first 700 characters (about 170 tokens) | 1,870 | 2,690 | - |
| first 350 characters | 910 | 1,470 | - |
(medians of 9 runs, noisy because the corpus fetch ran in the background; the ARM VM will be slower, plan on 1.5x or more.)
- `BAAI/bge-reranker-v2-m3` was NOT measured: the int8 file is 570 MB and the fp32 2.27 GB. From parameter counts it is about 14x the compute of MiniLM-L-12 (24 layers x 1024 hidden against 12 x 384), so 30 full pairs would be about 80 s on this machine. That is an estimate, not a measurement. It is also multilingual, which this English corpus does not need. Not viable for interactive CPU use; keep it for offline eval runs on a GPU.
- Proposal: `Xenova/ms-marco-MiniLM-L-12-v2` (134 MB), pool 20, first 700 characters of each passage (`STEWARDS_RERANK_CHARS`), which is about 1.9 s here. Truncation may cost ranking quality on long chunks (the heading and the rule's opening are at the start); 3e's eval must compare with and without. Smaller option: MiniLM-L-6 (about half the time, not downloaded or measured). Re-run `python manage.py bench_reranker --model <name> --pairs 20 30 --max-chars 700` on the VM before fixing the default.
- Sanity check on the real corpus: "What is the penalty for causing a collision?" returns B1.9.5, B1.9.4, B1.9.6; "overtake during the formation lap behind the safety car" returns B5.10.6 first. Two questions, not an evaluation.

### Where retrieval runs: recommendation
Run retrieval (and the 3c agent) in the `rag` worker, not in the web process.
- Memory (RSS measured): Django process 144 MB; with bge-small loaded 307 MB; with the reranker also loaded about 570-670 MB. Each web process would carry that, times the number of gunicorn workers, on a 24 GB box that also runs Postgres-side work, Redis and the other workers.
- CPU: reranking 20 pairs is about 2 s of 100 percent CPU on this PC. Inside web it blocks a worker thread for those seconds; in `rag` the concurrency is bounded (set `--concurrency 1-2`).
- Celery round trip: not measured (no Redis here); with Redis it is single-digit to tens of milliseconds, negligible against 2 s of reranking and against a Claude call of many seconds. The agent in 3c calls `claude -p` as a subprocess, so it is long-running work that belongs in the worker anyway; its tools (`search_documents`) then call `retrieve()` in-process with zero extra hop.
- So: the web process only enqueues the question and streams tokens and citations over the existing SSE/pubsub path (as the populate tasks already do); it never imports onnxruntime. Cost: one warm model per rag worker (load 1.4 s once), a worker slot per concurrent question.

### Quoted-extract cap
`EXTRACT_CAP = 300` characters per result (`Hit.extract`), plus the FIA source URL, per the FIA terms decision pending with the user. Full chunk text exists only for the reranker and the agent prompt.

### Corpus scope
Asked for: Sporting and Technical Regulations 2022-2026 (latest issue per year and section) and stewards' decisions for the 2025 and 2026 seasons. **Only partly done**, because the FIA site is the bottleneck from this machine, not the code: large PDFs die mid-transfer with TLS `bad record MAC` (curl/schannel shows the same fault), each request waits the 10 s Crawl-delay, and responses took 5-9 s each. The fetcher was changed to download in 2 MB HTTP-Range chunks with per-chunk retries, which works but is slow.
Landed in the local DB (all with real bge-small vectors): 2022 Sporting Regulations (213 chunks), 2025 Technical Regulations (364), 2026 Section B (193), plus 3 stewards' decisions and 1 event note from the Las Vegas 2026 weekend (7 chunks): **7 sources, 777 chunks**.
NOT fetched (next, resumable, already-registered URLs are skipped without a request): 2022 Technical, 2023 Sporting/Technical, 2024 Sporting/Technical, 2025 Sporting, 2026 Section C; all 2025 and 2026 season decisions. Discovery works (per-event pages found; summons notices are excluded by default, `--include-summons` adds them). Estimate: about 50 event pages and several hundred decision PDFs at 10 s each is 2-4 hours of polite fetching. Commands, in order:
`manage.py fetch_corpus --reg-years 2022 2023 2024 2025 2026 --limit 50`, then `--seasons 2026 --limit 1000`, then `--seasons 2025 --limit 1000`, then `manage.py ingest_corpus`. A better place to run this is the VM (or any machine with a clean path to fia.com).

DEFERRED-VM: reranker and embedding latency on arm64 (use `bench_reranker`).


## Phase 3c: agent and endpoint

Status: done, awaiting review. Rebased on v2/integration (1460442). Full suite (empty env): 503 passed, 0 failed, 20 skipped (3b baseline 454/0/20, so +49).

Files (`backend/api/assistant/`): `llm.py`, `tools.py`, `agent.py`, `sse.py`, `views.py`, `urls.py`, `tasks.py` (`ask_question`), `tests/test_llm.py`, `tests/test_agent.py`, `tests/test_ask_endpoint.py`, `NEEDS.md` (langgraph, langchain-core).

Decision recorded: **bge-reranker-v2-m3 is dropped from the plan.** Reason: on CPU it is about 14x the compute of MiniLM-L-12 (estimated from parameter counts, about 80 s for 30 full passages on this PC; not measured because the 570 MB int8 file was not downloaded), it is multilingual while the corpus is English only, and the interactive budget is a couple of seconds. The default stays MiniLM-L-12 (pool 20, 700 characters), provisional until the VM bench and the 3e eval.

### Headless runner (`llm.py`)
Flags checked against `claude --help` (Claude Code 2.1.305) and two live calls. argv: `claude -p --output-format json --json-schema <inline json> --model <id> --append-system-prompt <text> --tools "" --no-session-persistence --disable-slash-commands --safe-mode`, prompt on stdin, cwd an empty temp dir, never `--bare`. `--tools ""` removes the built-in tools (Bash, Read...) so a call is text in, text out; `--safe-mode` keeps the subscription login but drops the host user's hooks, skills and CLAUDE.md. Models: planner `claude-haiku-5-5`, answer `claude-sonnet-5-5` (both accepted by the CLI; configurable by env). Error classes: rate limit (backoff, 2 retries), auth expired (never retried), bad JSON (retried once), timeout (retried once). Wrapped as a LangChain `RunnableLambda` for the planner node. The Windows npm shim is resolved to the real `claude.exe`.

**Token streaming works.** `--output-format stream-json --verbose --include-partial-messages` emits one JSON object per line. Text deltas are `{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"..."}}}` (chunks of a few words); the last line is `{"type":"result","result":"<full text>","total_cost_usd":...,"is_error":false}`; other lines (`system init`, `rate_limit_event`, `assistant`, thinking deltas) are ignored. The answer uses this (plain text with `[E1]` markers, no JSON schema); the planner uses `--output-format json` with `--json-schema`.

What the real JSON looked like (planner call, `--output-format json`): top-level keys include `type: "result"`, `subtype: "success"`, `is_error: false`, `result` (the structured output as a JSON string), **`structured_output`** (the same, already parsed: the runner prefers it and falls back to parsing `result`), `total_cost_usd` (0.0014 for that call), `usage` (input/output/cache tokens), `modelUsage` (per model, with `claude-haiku-5-5`), `num_turns: 2`, `stop_reason: "tool_use"` (the schema is delivered through an internal structured-output tool, so this value is expected), `session_id`, `duration_ms` (about 6 s; Haiku spent 311 thinking tokens on a trivial plan), plus timing fields. The first call also paid for about 5,100 cache-creation input tokens (the default system prompt).

### Agent (`agent.py`, LangGraph)
`plan -> tools -> plan ... -> answer`, at most 4 tool rounds (a 5th planner call is never made; after round 4 the graph goes to the answer) and at most 3 tool calls per round. The planner (Haiku, JSON schema: action `tools|answer`, `tool_calls[{tool,args}]`) sees the question, the request's year and round, the calls already made, the evidence so far (id, tool, label, article, page, 160-character extract) and problems with earlier calls. Python validates every call against the tool's JSON schema (unknown tool, missing or out-of-range arguments, extra keys) and reports violations back to the planner as observations instead of executing them; repeated identical calls are skipped; a crashing tool is reported, not fatal. Tools (`tools.py`), all in-process: `search_documents(query, year?, doc_type?)` and `similar_past_decisions(offence, n)` call `retrieval.retrieve`; `get_incidents` and `get_track_status` read the persisted race data (`api.services.persistence`); `get_chaos` calls `api.chaos.service.select_run/race_payload` (compacted to 3,000 characters). A data tool with no stored data returns nothing (never live FastF1, never invented). Year and round default from the request.

The answer node gets the evidence items (`[E1] (document) title | article | page | section` plus text) and must answer only from them, cite `[E#]`, state article and page, quote at most 300 characters, and otherwise reply "Evidence not found." Python builds the citations from the ids the text cites (title, page, article, section, FIA URL, 300-character extract, order of first appearance). No evidence at all means "Evidence not found." with no model call. The `done` event carries `grounded` (false when there is no valid citation or a cited id does not exist), `not_found`, `invalid_citations`, `long_quotes` (quotations over 300 characters: counted, not removable because the text is already streamed), `rounds`, `tools_used`, `cost_usd`.

### Endpoint (`POST /api/assistant/ask`)
Body `{question (3-1000 chars), year? (2018-2030), round? (1-30, needs year)}`; 400 on anything else. Web validates, publishes a `queued` status, enqueues `api.assistant.tasks.ask_question` (rag queue by module route) and returns `text/event-stream`. Events (frame `id`, `event`, `data` JSON): `status` (`phase`: queued, solving, searching, composing), `token` (`text`), `citations`, then `done` or `error` (`code`: auth_expired, rate_limited, llm_failed, timeout, internal; no `done` after an error). The task always ends the stream (soft time limit 240 s; a final `error` if nothing else was emitted).

Reuse note: `api/services/streaming.py` delivers exactly ONE frame per task and stops, so it cannot carry five event types. `sse.py` keeps its conventions (shared publish client and `REDIS_URL` from `api/services/pubsub.py`, async generator in a `StreamingHttpResponse`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`) and stores events in a Redis list (15-minute TTL) that the stream reads, so a late or reconnecting reader replays from the start (plain pub/sub drops messages published before the subscriber is ready). No existing file was changed. Not built: a reconnect endpoint (the events are replayable by `task_key`, but no GET route exposes them yet).

Auth, permission and throttle are the project defaults; a test asserts the class lists equal `AnalysisTelemetryAPIView`'s and that a keyless request gets the same status as `/laps/`.

**Finding for the orchestrator (affects existing views):** DRF runs throttles in `initial()`, before the handler. The existing views set `request.endpoint_type = "..."` inside `get()`, i.e. after `APIKeyThrottle` has already priced the request, so their `ENDPOINT_COSTS` entries never apply (cost falls back to the URL-path guess in `get_endpoint_cost`). My view sets it in an `initial()` override before `super().initial()`, and a test proves the throttle sees it. Fixing the old views is a one-line `initial()` change or mixin each; I did not touch them.

Needs: add `"assistant_ask": 10,` to `ENDPOINT_COSTS` in `api/throttling.py`. An answer is several CLI calls (about 7 s per Haiku planner round plus a Sonnet call) and on the subscription it spends the user's quota, so price it above telemetry's 5.

### Live smoke checks (6 `claude` calls: one over the cap of 5; the end-to-end run made 4 because the planner took 3 rounds; I ran no more)
1. Planner-style JSON call (Haiku): ok, shape above. 2. Streamed answer (Sonnet): ok, deltas as above.
3-6. One real question through the whole agent with real retrieval on the local DB ("What is the penalty if a driver is judged to have caused a collision, and when can the formation lap overtaking rule apply?"): 3 planner calls and 1 answer call; 18 evidence items; 106 token events; 48 s wall clock; $0.066 total (nearly all the Sonnet answer, which read 18 passages). The answer was grounded in 2022 art. 54.2-54.3 (p. 58-59) and 2026 B1.9.5 (p. 14), cited with page, article and FIA URL, and said what the evidence did not contain.

Problems seen: (a) the planner takes 2-3 rounds for a two-part question: about 7 s per round, and Haiku thinks even for trivial plans; (b) 18 evidence items is more than the answer needs (cost): cap the answer prompt to about 8-10 items; (c) the `section` on a 2022 citation was stale ("30.6 Testing of tyres" for art. 54.1): the chunker's sub-heading detection mis-fires on the older numbering. Article and page were correct. Candidates for 3d/3e: planner `--effort low`, an evidence cap, a chunker fix for pre-2026 numbering. No recall number is claimed.

### Corpus fetch (background, this machine)
The fetch chain has been running since this phase began (polite, resumable). Landed so far: 2022 Sporting, 2023 Technical, 2024 Sporting, 2025 Sporting and Technical, 2026 Section B, and 6 stewards' decisions of 2026 (the Australian GP so far). The 2026 season lists 651 decision/note PDFs (summons excluded), roughly 2 hours at the Crawl-delay; the 2025 season follows. Whatever is stored is ingested with `manage.py ingest_corpus`.

DEFERRED-VM: agent latency on arm64; the `claude` CLI in the rag image with the host `~/.claude` mounted.
