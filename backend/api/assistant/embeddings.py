"""bge-small-en-v1.5 embeddings through fastembed (ONNX Runtime, no torch).

Why fastembed: the `rag` worker runs on a 4-core arm64 box. fastembed needs only onnxruntime + tokenizers
(arm64 wheels exist, ~100 MB installed) where sentence-transformers would pull torch (~2 GB). Same model,
same 384-d vectors. Caveat: fastembed's registry maps "BAAI/bge-small-en-v1.5" to the INT8-quantised export
(Qdrant/bge-small-en-v1.5-onnx-Q, ~67 MB); recall differences vs fp32 are small but unmeasured here (Phase 3e eval).

The model is downloaded once from Hugging Face into STEWARDS_MODEL_CACHE (default: next to the corpus data
dir) so a worker never re-downloads. Nothing here loads at import time.
Passages are embedded as-is; BGE queries need the instruction prefix, which `embed_query` adds (Phase 3b).
"""
from __future__ import annotations

import os
from pathlib import Path

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIM = 384
BATCH = 32
_model = None


def _cache_dir() -> str:
    from .fetch import data_dir

    return os.environ.get("STEWARDS_MODEL_CACHE") or str(Path(data_dir()) / "models")


def _get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        _model = TextEmbedding(model_name=MODEL_NAME, cache_dir=_cache_dir())
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Passage embeddings, one 384-float list per text, L2-normalised (so cosine = inner product)."""
    if not texts:
        return []
    return [v.tolist() for v in _get_model().embed(texts, batch_size=BATCH)]


def embed_query(text: str) -> list[float]:
    return [v.tolist() for v in _get_model().query_embed([text])][0]
