"""Small, inspectable topic classifier using the existing document embeddings."""

import hashlib
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np

from .embedding import MODEL_NAME, embed_texts, get_embedder

CATALOGUE = json.loads(Path(__file__).with_name("topic_catalogue.json").read_text())
TOPICS = CATALOGUE["topics"]
TOPIC_IDS = {topic["id"] for topic in TOPICS}
CATALOGUE_HASH = hashlib.sha256(
    json.dumps(CATALOGUE, sort_keys=True, ensure_ascii=False).encode()
).hexdigest()
METHOD = "bge-m3-topic-examples-v1"


@lru_cache(maxsize=1)
def topic_vectors():
    # One small batched call per process, never per opinion or during browsing.
    texts = [
        text for topic in TOPICS for text in [topic["description"], *topic["examples"]]
    ]
    vectors = np.asarray(embed_texts(texts), dtype=np.float64)
    normalized = vectors / np.clip(
        np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12, None
    )
    config = getattr(getattr(get_embedder(), "model", None), "config", None)
    return normalized, getattr(config, "_commit_hash", None)


def classify_topics(text, embedding):
    """Return several matching topic IDs, or none, plus a decision record.

    Similarities are retrieval scores, not calibrated confidence. Every topic
    above the explicit threshold and near the best match is retained; no topic
    is forced when all matches are weak.
    The original opinion and source link remain unchanged.
    """
    vector = np.asarray(embedding, dtype=np.float64)
    if vector.ndim != 1 or not np.isfinite(vector).all() or np.linalg.norm(vector) == 0:
        raise ValueError("A finite, nonzero opinion embedding is required")
    references, revision = topic_vectors()
    similarities = references @ (vector / np.linalg.norm(vector))
    best_score = float(similarities.max())
    scores, assigned, offset = [], [], 0
    for topic in TOPICS:
        size = 1 + len(topic["examples"])
        candidates = similarities[offset : offset + size]
        best = int(np.argmax(candidates))
        score = float(candidates[best])
        accepted = (
            score >= CATALOGUE["minimumSimilarity"]
            and best_score - score <= CATALOGUE["maximumScoreGap"]
            and (
                score == best_score or score >= CATALOGUE["minimumSecondarySimilarity"]
            )
        )
        scores.append(
            {
                "topicId": topic["id"],
                "similarity": score,
                "referenceIndex": best,
                "assigned": accepted,
            }
        )
        if accepted:
            assigned.append(topic["id"])
        offset += size
    return assigned, {
        "method": METHOD,
        "model": MODEL_NAME,
        "referenceModelRevision": revision,
        "catalogueVersion": CATALOGUE["version"],
        "catalogueHash": CATALOGUE_HASH,
        "minimumSimilarity": CATALOGUE["minimumSimilarity"],
        "maximumScoreGap": CATALOGUE["maximumScoreGap"],
        "minimumSecondarySimilarity": CATALOGUE["minimumSecondarySimilarity"],
        "inputHash": hashlib.sha256(text.encode()).hexdigest(),
        "embeddingHash": hashlib.sha256(vector.astype("<f4").tobytes()).hexdigest(),
        "classifiedAt": datetime.now(timezone.utc).isoformat(),
        "scores": scores,
    }


def assign_topics(opinion):
    """Repeatable backfill/reclassification without rerunning sentiment."""
    ids, analysis = classify_topics(opinion.text, opinion.embedding)
    # Check the text and vector snapshot before writing so concurrent edits
    # cannot attach a classification to a different input.
    updated = (
        type(opinion)
        .objects.filter(pk=opinion.pk, text=opinion.text, embedding=opinion.embedding)
        .update(topic_ids=ids, topic_analysis=analysis)
    )
    if updated:
        opinion.topic_ids, opinion.topic_analysis = ids, analysis
    return bool(updated)
