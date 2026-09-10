"""The current contribution pipeline: original text -> BGE-M3 -> search."""

from .embedding import embed_text
from .models import Opinion
from .sentiment import score_text


class EmbeddingUnavailable(Exception):
    pass


class SentimentUnavailable(Exception):
    pass


def index_contribution(contribution):
    """Index an explicitly public source, safely repeatable by a future worker.

    Inference runs outside the write transaction. Racing retries can compute
    the same embedding, but the unique source link permits only one opinion.
    No author, topic, stance or reason is inferred by this embedding step.
    """
    if contribution.publication != "public":
        raise ValueError("Only public contributions can enter opinion search")
    existing = Opinion.objects.filter(contribution=contribution).first()
    if existing is not None:
        return existing
    try:
        embedding = embed_text(contribution.text)
    except Exception as exc:
        raise EmbeddingUnavailable from exc
    try:
        sentiment = score_text(contribution.text)
    except Exception as exc:
        raise SentimentUnavailable from exc
    opinion, _ = Opinion.objects.get_or_create(
        contribution=contribution,
        defaults={
            "text": contribution.text,
            "topic": "",
            "embedding": embedding,
            "sentiment": sentiment,
        },
    )
    return opinion
