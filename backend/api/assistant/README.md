# Stewards and rules assistant

Answers questions about the FIA Formula 1 regulations and stewards' decisions from a local, cited corpus, and combines
them with the app's own race data (incidents, track status, Chaos Point predictions). Every answer cites document, page,
article and the FIA source URL, and says "Evidence not found." when the corpus does not contain the answer.

## Architecture

```
corpus (FIA PDFs, local only) --fetch_corpus--> DocumentSource rows + original PDFs (gitignored data dir)
        --ingest (rag queue)--> pypdf -> section-aware chunks (300-450 tokens, article numbers kept)
        --> bge-small-en-v1.5 embeddings (fastembed, ONNX, 384-d) --> DocChunk rows in Postgres:
            text, vector(384) + HNSW, tsvector + GIN, page, section, article, source FK

POST /api/assistant/ask  {question, year?, round?}          (web process: validates, enqueues, streams)
        -> Celery task api.assistant.tasks.ask_question on the `rag` queue
           LangGraph:  plan -> tools -> plan ... -> answer      (at most 4 tool rounds)
             planner  = `claude -p` (Haiku, --effort low, JSON schema): which tools to call, or answer
             tools    = in-process services: search_documents, similar_past_decisions, get_incidents,
                        get_track_status, get_chaos
             answer   = `claude -p` (Sonnet), streamed (stream-json), only from the numbered evidence items
        -> events appended to a Redis list -> text/event-stream
           status (queued, solving, searching, composing) | token | citations | done | error
GET  /api/assistant/ask/<task_key>/events                   replay / resume (Last-Event-ID or ?from=)
```

- **Retrieval** (`retrieval.py`): Postgres full-text (`ts_rank`, OR-joined terms) top 50 + pgvector cosine top 50,
  merged with reciprocal rank fusion (k = 60), optional filters (year, doc type, race), optional cross-encoder rerank.
  Raw SQL, Postgres only.
- **LLM** (`llm.py`): the `claude` CLI headless on the logged-in subscription, no API key. Flags: `-p
  --output-format json|stream-json --json-schema --model --append-system-prompt --tools "" --no-session-persistence
  --disable-slash-commands --safe-mode`, empty temp cwd, never `--bare`. Rate limits are retried, an expired login
  is never retried, bad JSON is retried once. Tests use a fake runner and never start `claude`.
- **Citations**: Python builds them from the evidence ids the answer cites, so a source cannot be invented. The
  answer sees at most 10 evidence items. `done` carries `grounded`, `not_found`, `invalid_citations` and `long_quotes`.
- **MCP server** (`mcp_server.py`, entry `backend/mcp/server.py`): see below.
- Runs on the `rag` worker, never in the web process (web does not import onnxruntime or load a model).

## Decisions (and why)

| Decision | Reason |
|---|---|
| fastembed (ONNX) with bge-small-en-v1.5, not sentence-transformers | no torch: about 100 MB instead of about 2 GB, arm64 wheels. The registry serves the INT8 export. |
| pypdf | pure Python, installs anywhere, quality is enough for these text PDFs; about 0.5 s per page. PyMuPDF is faster but AGPL. |
| No bge-reranker-v2-m3 | about 14x the compute of MiniLM-L-12 (estimate, about 80 s for 30 passages on a dev PC), multilingual for an English-only corpus. |
| Rerank off by default (`STEWARDS_RERANK=1` to enable) | on 77 gold questions it raises recall@1 (0.44 to 0.56) and MRR (+0.07) but lowers recall@8 (0.870 to 0.844) and costs about 2 s; the agent reads up to 10 items, so recall matters more than order. |
| Year filter inferred from the question | recall@8 0.895 and MRR 0.795 with a year filter (on top of rerank) against 0.844 and 0.660 without. Several regulation years have near-identical articles. |
| Planner first round must search | Haiku at low effort sometimes answered without looking, which can only give a false "Evidence not found." |
| Events in a Redis list, not pub/sub only | a reader that connects late or reconnects replays from the start. |
| Quote length counted, not enforced | the text is already streamed; `long_quotes` is reported in `done`; citation extracts are capped at 300 characters. |

## Evaluation

77 gold questions (rule lookups, penalty precedents, event notes), 10 unanswerable, 10 race-data questions (not scored
locally: they need stored race data). Corpus snapshot `59dbbf22...` (79 sources, 1,728 chunks; `evals/snapshot.json`).
Details: `evals/questions.jsonl`, `evals/results/`, `management/commands/assistant_eval.py`.

Retrieval only, no LLM (recall@8, MRR over the gold article or decision):

| Mode | recall@8 | MRR |
|---|---|---|
| FTS only | 0.714 | 0.546 |
| vector only | 0.818 | 0.514 |
| RRF | 0.870 | 0.588 |
| RRF + rerank (700 chars) | 0.844 | 0.660 |
| RRF + rerank (full text) | 0.857 | 0.669 |
| RRF + rerank + year filter | 0.895 | 0.795 |

End-to-end (live `claude`, small sample): see "Phase 3e" in `docs/v2/progress/A3-stewards.md` for the latest run
(citation accuracy, LLM-judged correctness, evidence-not-found, latency, cost).

## FIA terms caveat

The FIA site terms (clauses 3.4, 3.5, 3.9) say the FIA owns the copyright in its publications and that reproducing or
using them needs prior written consent, allowing only private non-commercial copies and short quoted extracts with a
reference. So: the PDFs stay in a gitignored local folder and are never committed or served; results carry extracts of
at most 300 characters plus the FIA URL; full chunk text is used only inside the worker (reranking, the answer prompt).
Running this publicly needs the FIA's permission or a private corpus; that is the operator's call.
The fetcher honours robots.txt (Crawl-delay 10 s), identifies itself generically, and is resumable.

## How to run

```bash
# one-time: Postgres with pgvector (local container used in development)
docker run -d --name f1-stewards-pg -p 5433:5432 -e POSTGRES_PASSWORD=stewards -e POSTGRES_DB=f1_stewards pgvector/pgvector:0.8.0-pg17
export DATABASE_URL=postgres://postgres:stewards@localhost:5433/f1_stewards SECRET_KEY=dev
cd backend && python manage.py migrate assistant          # NEVER on Neon until the pgvector extension is approved

# corpus (polite, resumable): regulations, then a season of decisions, then embed and store
python manage.py fetch_corpus --reg-years 2022 2023 2024 2025 2026
python manage.py fetch_corpus --seasons 2026
python manage.py ingest_corpus                            # or the rag-queue task api.assistant.tasks.ingest_pending

# models are cached in STEWARDS_MODEL_CACHE (default api/assistant/data/models); HF_HUB_OFFLINE=1 once cached
# worker: celery -A f1_project worker -Q rag -c 1           (needs the `claude` CLI logged in; CLAUDE_CONFIG_DIR)
curl -N -X POST localhost:8000/api/assistant/ask -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
     -d '{"question": "What penalty applies for causing a collision?", "year": 2026}'

# evaluation
python manage.py assistant_eval check-gold && python manage.py assistant_eval retrieval
python manage.py assistant_eval e2e --ids q011 q022 --max-calls 30      # live claude calls, costs money
```

Environment: `STEWARDS_DATA_DIR`, `STEWARDS_MODEL_CACHE`, `STEWARDS_FETCH_DELAY` (10), `STEWARDS_RERANK` (0),
`STEWARDS_RERANKER`, `STEWARDS_RERANK_CHARS` (700), `STEWARDS_PLANNER_MODEL` (claude-haiku-5-5),
`STEWARDS_ANSWER_MODEL` (claude-sonnet-5-5), `STEWARDS_PLANNER_EFFORT` (low), `CLAUDE_BINARY`.

## MCP server

Seven read-only tools over stored data, no writes, no live FastF1, stdio transport (MCP Python SDK v2, `MCPServer`):
`f1_search_documents`, `f1_get_chaos`, `f1_get_track_map`, `f1_get_incidents`, `f1_get_track_status`,
`f1_get_race_results`, `f1_get_race_schedule`. A tool whose data is not stored returns an error that names the web
endpoint that populates it.

```bash
cd backend && python mcp/server.py        # stdio; register in a client as: command "python", args ["mcp/server.py"], cwd backend
```

The folder is called `mcp/` but is deliberately not a Python package (it would shadow the SDK); the server code is
`api/assistant/mcp_server.py`. Tests use the SDK's in-memory client plus one real stdio round trip.
