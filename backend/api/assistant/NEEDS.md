# assistant (stewards) dependencies, Phase 3a

New, pinned (installed in the A3 venv, versions as resolved 2026-11-23):

```
pgvector==0.5.1        # Django VectorField + VectorExtension migration op
pypdf==7.1.1           # PDF text extraction (pure Python, BSD)
fastembed==0.9.1       # ONNX bge-small-en-v1.5 embeddings, no torch
onnxruntime==1.32.0    # fastembed runtime (arm64 wheels exist)
tokenizers==0.23.3
huggingface-hub==2.4.0
py-rust-stemmers==0.1.8
loguru==0.8.0
mmh3==5.3.1
```

Dev/test only (not in requirements.txt yet): `pytest==9.0.3`, `pytest-django==4.12.0`.

Already in requirements.txt and reused: `requests`, `celery`, `numpy`, `psycopg2-binary`.

Install note: `pip install fastembed` fails dependency resolution against the current requirements
(fastembed caps `pillow<12`, the project pins `pillow==12.0.0`; Pillow is only used by fastembed's
image models, which this app never loads). The orchestrator should install with
`pip install --no-deps fastembed==0.9.1` after the other pins, or keep `pillow` as is and add the
`--no-deps` line to the Dockerfile. No torch anywhere in this app.

Also for the orchestrator (shared files, not mine): none required for 3a. For 3b, `django.contrib.postgres`
is NOT needed (the tsvector column is a plain custom field); hybrid search will use raw SQL.

Runtime configuration (env, all optional):

| Variable | Default | Meaning |
|---|---|---|
| `STEWARDS_DATA_DIR` | `backend/api/assistant/data/` (gitignored) | original PDFs and the model cache |
| `STEWARDS_MODEL_CACHE` | `<data dir>/models` | where fastembed keeps the ONNX model |
| `STEWARDS_FETCH_DELAY` | `10` | seconds between requests to fia.com (robots.txt Crawl-delay) |
| `STEWARDS_PG_DSN` | unset | enables `tests/test_pgvector_live.py` (local container only) |

## Phase 3b additions

- Models (downloaded once into `STEWARDS_MODEL_CACHE`, never in git): `BAAI/bge-small-en-v1.5` (INT8, 66 MB) and the default reranker `Xenova/ms-marco-MiniLM-L-12-v2` (134 MB). Both come from Hugging Face. On networks where `huggingface_hub`/fastembed stall at 0 bytes, copy the files into the cache directory layout (`models--<org>--<name>/snapshots/<rev>/`), or download with HTTP Range requests.
- New env: `STEWARDS_RERANKER` (default MiniLM-L-12), `STEWARDS_RERANK_CHARS` (default 700, 0 = no truncation). `HF_HUB_OFFLINE=1` is safe once the models are cached.
- No new packages (psutil was used only for local measurements and is not needed).


## Phase 3c additions

New pinned dependencies (installed in the A3 venv; `pip freeze` after install):

```
langgraph==1.2.24
langchain-core==1.8.4
# pulled in by them: langgraph-checkpoint==4.3.2 langgraph-prebuilt==1.1.3 langgraph-sdk==0.4.14 langsmith==0.16.1
#   orjson==3.13.0 ormsgpack==1.13.1 xxhash==4.1.0 zstandard==0.25.0 tenacity==9.1.2 jsonpatch==1.48 requests-toolbelt==1.0.0
```
`jsonschema` (tool-argument validation) and `redis` are already in requirements.txt. LangSmith tracing stays off unless
`LANGSMITH_TRACING` is set in the environment (nothing sets it).

Runtime: the `rag` worker needs the `claude` CLI (npm `@anthropic-ai/claude-code`, version checked here: 2.1.305) and the
host's `~/.claude` mounted (`CLAUDE_CONFIG_DIR`), as in the stock-index project's compose. Env (optional):
`STEWARDS_PLANNER_MODEL` (default `claude-haiku-5-5`), `STEWARDS_ANSWER_MODEL` (default `claude-sonnet-5-5`),
`CLAUDE_BINARY` (path override). The web process does not need the CLI, onnxruntime or the models.

Orchestrator, shared file `backend/api/throttling.py`: add `"assistant_ask": 10,` to `ENDPOINT_COSTS` (see the progress file).

## Phase 3e additions: MCP server

```
mcp==2.3.0            # MCP Python SDK v2 (MCPServer, the renamed FastMCP; `from mcp.server.fastmcp import FastMCP` no longer exists)
# pulled in: anyio==4.14.2 httpx2 mcp-types opentelemetry-api PyJWT python-multipart==0.0.34 sse-starlette==3.7.1
#   starlette==1.10.0 typing-inspection==0.4.2 uvicorn==0.54.0 (pywin32 on Windows only)
```
(`jsonschema`, `pydantic`, `typing-extensions` are already pinned.) The SDK's in-memory `mcp.client.Client(server)` is used
by the tests, so no extra test dependency. Place the pin in `requirements-rag.txt` (only the worker/MCP image needs it; the
web image does not import it).

Should it run as its own compose service? As a long-running service, no: the server speaks stdio, which means a client
starts it as a child process (Claude Desktop, an IDE, `docker compose run -i`). A permanent container would expose nothing.
Provide it as an on-demand, profile-gated service (the block is in `docs/v2/progress/A3-stewards.md`), on the rag image
because `f1_search_documents` embeds the query (it needs the model cache; 1 GB is enough with `STEWARDS_RERANK=0`).
If a remote client is wanted later, the same server runs over streamable HTTP (`MCPServer.run("streamable-http")`) behind
nginx with the API key; not built.

The `backend/stewards_mcp/` folder must stay a non-package (no `__init__.py`): a package named `mcp` there would shadow the SDK.
