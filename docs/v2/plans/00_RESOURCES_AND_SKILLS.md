# Resources, Skills and Libraries (shared by all six plans)

Every plan file references this list. The `skills/` folder in this bundle contains the downloadable agent skills. Install them into your coding agent before starting (for Claude Code: copy each folder into `.claude/skills/` in the repo, or `~/.claude/skills/` for all projects).

## A. Agent skills in this bundle (`skills/`)

| Skill | Source | Use it for | Found via |
|---|---|---|---|
| `frontend-design` | anthropics/skills (official) | Distinctive, non-templated UI direction: palette, type, layout. Won a dashboard comparison of Claude design skills. | Reel: brochbuilds ("Anthropic's own frontend-design won") |
| `astryx` | facebook/astryx `plugins/astryx/skills/astryx` | Building UI with Meta's Astryx design system via its `astryx` CLI (templates, components, themes) | Reel: asharasjad ("Meta open-sources the design system behind 13,000 apps") |
| `archify` | tt-a1i/archify (Apache-2.0) | Architecture, data-flow, sequence and ERD diagrams as interactive HTML, read from the real codebase. Use for every README diagram. | Reel: techie_programmer ("Meet Archify") |
| `webapp-testing` | anthropics/skills | Playwright end-to-end checks of each UI page | Research (UI testing) |
| `mcp-builder` | anthropics/skills | Exposing the F1 API and both RAG engines as MCP servers for agents | Reels: duncanrogoff and saurabhs.builds (MCP and Code Mode) |
| `theme-factory` | anthropics/skills | Generating consistent theme tokens (dark and light) | Research (design system) |
| `claude-api` | anthropics/skills | Correct Claude API usage (streaming, tool use, prompt caching) for the RAG readers and agents | Research (LLM reader) |

Not downloadable: brochbuilds' "skills database", murphmaxxing's "5 skills", itstundeanthony's "skill", by.flowww's site pack and buildwaleesh's design guide are all comment-gated ("comment X for the link"). Comment on those posts yourself if you want them, then drop them into `skills/`.

## B. UI libraries

| Library | License | Role | Source |
|---|---|---|---|
| **Astryx** (`@astryxdesign/core`, `@astryxdesign/cli`, a theme package, `@stylexjs/stylex`) | MIT | App shell, forms, tables, navigation, dark mode: 150+ accessible components on React 19 and StyleX. Beta. Its chart packages are canary-only, so don't use them for charts. | Reel (asharasjad), [repo](https://github.com/facebook/astryx), [docs](https://astryx.atmeta.com) |
| **thinking-orbs** | MIT | Animated agent-state indicators: `working`, `searching`, `solving`, `listening`, `connecting`, `weaving`, `composing`, `breathing`, `shaping`. Use them instead of spinners in every AI flow. Canvas 2D, monochrome. | Reel (adilet.fndr), [repo](https://github.com/Jakubantalik/thinking-orbs) |
| **uPlot** | MIT | High-frequency telemetry traces (about 22 kB, canvas) | Research ([TanStack comparison](https://tanstack.com/charts/latest/docs/comparison)) |
| **Apache ECharts** | Apache-2.0 | General charts, heat strips, eval dashboards | Research |
| **d3-zoom / d3-shape** | ISC | Pan and zoom, plus SVG track paths | Research |
| **react-three-fiber + drei** | MIT | 3D track and replay showcase | Research |
| **deck.gl** | MIT | WebGL scatter of large embedding maps (Folio "book galaxy") | Research ([freeCodeCamp](https://www.freecodecamp.org/news/high-frequency-real-time-data-in-react-from-ring-buffers-to-offscreencanvas/)) |
| **sigma.js** or **react-force-graph** | MIT | Citation graph (Paperlens) | Research |
| **PDF.js** (`react-pdf`) | Apache-2.0 | Paper viewer with evidence highlights | Research |
| **KaTeX** | MIT | Math rendering in answers | Research |
| **TanStack Query and Table** | MIT | Data fetching, leaderboards | Research |
| **Framer Motion** | MIT | Transitions | Research |

Palette rule, from the diego.a.does reel: two colours that get along, plus one that doesn't, used only on the primary action. Example: charcoal and sand plus an accent. Each project picks its own accent: F1 red for F1 Control Room, burnt orange for Folio, electric blue for Paperlens.

## C. Backend and ML libraries

| Library | Role | Source |
|---|---|---|
| **NVIDIA structured-data-models** (`pip install structured-data-models`, `from sdm.models import KumoTabular`) | Chaos Point predictions by in-context learning, no training step. Code Apache-2.0, weights OpenMDW-1.1. Sizes small, medium, large (27M to 215M parameters). Also has `KumoRelational` for multi-table input. | Reel (mar_antaya, "No more need to train our ML models"), [repo](https://github.com/NVIDIA/structured-data-models) |
| **FastF1** | F1 timing, telemetry, positions, circuit info | Existing |
| **LangChain + LangGraph** | RAG pipelines and agents | User's chosen stack |
| **Qdrant** | Vector database with dense and sparse (hybrid) search and quantization, for Folio and Paperlens | Research |
| **pgvector** (on Neon Postgres) | Vectors for the F1 stewards assistant, kept in the existing database | Research |
| **BGE models** (`bge-small-en-v1.5`, `bge-m3`, `bge-reranker-v2-m3`) | Embeddings and cross-encoder reranking | Research |
| **Docling** (IBM, MIT) | PDF to structured document: sections, tables, figures, reading order (Paperlens) | Research |
| **GROBID** (optional) | Reference and citation extraction (Paperlens) | Research |
| **Langfuse** (self-hosted) | Tracing every retrieval and LLM call, and storing eval runs | Research |
| **RAGAS / custom evaluators** | Retrieval and answer metrics | Research |
| **FastAPI + Pydantic v2** | API for Folio and Paperlens, and fills the FastAPI and Pydantic gap on your resume | Research (genieX requirements) |
| **Celery or arq** | Background ingestion and embedding jobs | Existing pattern |
| **Cloudflare Code Mode pattern** | Agents get one `run_code` tool over a typed API instead of dozens of tools. Apply it to the MCP servers when the tool count grows. | Reels (duncanrogoff, saurabhs.builds), [blog](https://blog.cloudflare.com/code-mode/) |

## D. Datasets

| Dataset | Use | Notes |
|---|---|---|
| FastF1 data (2018 onward) and race-control messages | Track maps, telemetry, Chaos Point labels | Track status codes: 4 = SC, 5 = red flag, 6 = VSC |
| Mendeley "Multi-Season F1 Lap Dataset with SC labels (2022–2025)" | 89,980 laps. Use to validate Chaos Point SC labels. | [link](https://data.mendeley.com/datasets/djr8rnjtjp/1), CC BY 4.0 |
| bacinger/f1-circuits, TUMFTM/racetrack-database | Backup circuit geometry | via [awesome-f1](https://github.com/subinium/awesome-f1) |
| Project Gutenberg | Folio corpus, thousands of books | Use official mirrors or offline catalog dumps. Don't crawl gutenberg.org pages. |
| NarrativeQA | Folio eval: questions over whole books and scripts (test set: 10,557 Qs, 355 stories) | Book IDs map to Gutenberg |
| QuALITY | Folio eval: multiple-choice long-document comprehension (dev set: 2,086 Qs) | |
| QASPER | Paperlens eval: 5,049 Qs over 1,585 NLP papers, with gold evidence paragraphs and unanswerable questions | |
| arXiv metadata and PDFs | Paperlens corpus and distractors | Respect arXiv API limits (one request per ~3 s). Prefer bulk metadata dumps. |
| Semantic Scholar API | Citation edges (Paperlens graph) | Free API key |

## E. Research findings to design around

- Simple methods are strong. Retrieving passages and reordering them in document order ("DOS RAG") matched or beat RAPTOR and ReadAgent ([Laitenberger et al. 2025](https://arxiv.org/html/2506.03989v2)). Flat chunks beat RAPTOR on most QASPER and QuALITY settings ([DISRetrieval](https://arxiv.org/pdf/2506.06313)). Always ship the simple baseline and report it.
- The research gap: published long-document benchmarks retrieve inside one document. Corpus-scale retrieval across thousands of books is untested. Folio's headline result is exactly that.
- None of the four papers tests BM25 + dense hybrid with a cross-encoder reranker as a standalone method. Both RAG projects include it.
- Structure-aware indexes help on structured documents: BookRAG beat its best baseline by 12.9 points on QASPER ([BookRAG](https://arxiv.org/pdf/2512.03413)). Paperlens's section, table and figure index tests this.
- Hiring signal: show calibrated, measured results, failure cases and what AI got wrong, not just a demo ([GovTech](https://www.govtech.com/education/higher-ed/ai-is-changing-what-employers-want-from-entry-level-tech-workers), [Wellfound](https://wellfound.com/blog/proof-beats-polish-how-to-stand-out-when-500-people-apply-from-writer-ais)).

## F. Shared infrastructure facts

- Server: Oracle Cloud A1 Flex, **4 ARM (aarch64) cores, 24 GB RAM**. Every Docker image must be built for `linux/arm64` (build on the VM, or use `docker buildx --platform linux/arm64`).
- F1 Control Room's Postgres is **Neon** (managed, external). Neon supports `CREATE EXTENSION vector`.
- Heavy embedding or backtest jobs can run on a free Kaggle or Colab GPU. Export the results (Qdrant snapshot, Parquet) and load them on the VM.
