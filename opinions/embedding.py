"""Text embedding backend for opinions.

design.md's Inference section names BGE-M3 as the embedding model, and the
write path feeds an opinion's text straight into it. This module owns loading
that model and turning text into the dense vectors ``Opinion.save()`` stores.
"""

from functools import lru_cache

from FlagEmbedding import FlagAutoModel

MODEL_NAME = "BAAI/bge-m3"


@lru_cache(maxsize=1)
def get_embedder():
    """Return the process-wide BGE-M3 embedder, loading it on first use.

    Loading pulls multi-GB model weights, so this must stay lazy (never called
    at import time) and cached -- every caller in the process shares the one
    instance instead of reloading per request.
    """
    return FlagAutoModel.from_finetuned(
        MODEL_NAME,
        query_instruction_for_retrieval="Represent this sentence for searching relevant passages:",
        use_fp16=True,
    )


def embed_text(text: str) -> list[float]:
    """Embed a single passage of text as a dense vector.

    Uses ``encode_corpus`` rather than plain ``encode``: opinions are the
    indexed documents in design.md's write path, not search queries, so no
    instruction is prepended. ``query_instruction_for_retrieval`` above is for
    the read path (embedding a user's search keywords), not this one.
    """
    embedder = get_embedder()
    dense_vecs = embedder.encode_corpus(
        [text],
        return_dense=True,
        return_sparse=False,
        return_colbert_vecs=False,
    )["dense_vecs"]
    return dense_vecs[0].tolist()
