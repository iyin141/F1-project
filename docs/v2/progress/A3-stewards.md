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
