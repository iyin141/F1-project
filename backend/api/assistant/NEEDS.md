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
