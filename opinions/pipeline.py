"""The current contribution pipeline: original text -> embedding, sentiment, topics -> search."""

from .embedding import embed_text
from .models import Opinion
from .sentiment import score_text
from . import topic_classification


class EmbeddingUnavailable(Exception):
    pass


class SentimentUnavailable(Exception):
    pass


class TopicsUnavailable(Exception):
    pass


def index_contribution(contribution):
    """Index an explicitly public source, safely repeatable by a future worker.

    Inference runs outside the write transaction. Racing retries can compute
    the same embedding, but the unique source link permits only one opinion.
    Predefined topic IDs are estimated; no author, stance or reason is invented.
    """
    if contribution.publication != "public":
        raise ValueError("Only public contributions can enter opinion search")
    existing = Opinion.objects.filter(contribution=contribution).first()
    if existing is not None:
        if not existing.topic_analysis:
            try:
                topic_classification.assign_topics(existing)
            except Exception as exc:
                raise TopicsUnavailable from exc
        return existing
    try:
        embedding = embed_text(contribution.text)
    except Exception as exc:
        raise EmbeddingUnavailable from exc
    try:
        sentiment = score_text(contribution.text)
    except Exception as exc:
        raise SentimentUnavailable from exc
    try:
        topic_ids, topic_analysis = topic_classification.classify_topics(
            contribution.text, embedding
        )
    except Exception as exc:
        raise TopicsUnavailable from exc
    opinion, _ = Opinion.objects.get_or_create(
        contribution=contribution,
        defaults={
            "text": contribution.text,
            "embedding": embedding,
            "sentiment": sentiment,
            "topic_ids": topic_ids,
            "topic_analysis": topic_analysis,
        },
    )
    return opinion
