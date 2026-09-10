"""Recomputing an opinion's derived data when its text is edited.

``Opinion.save()`` only fills embedding/sentiment/predefined topics *once*,
on creation (see its docstring in models.py) -- editing already-analysed
text does not, by design, silently redo expensive model calls on every save.
Editing an opinion's own text through ``opinions/users.py``'s "my opinions"
page is the one place that *should* redo them, explicitly: the user asked to
regenerate everything, not just change a string. ``reanalyze_opinion`` is
that explicit path.
"""

from .clustering import reassign_to_nearest_clusters
from .embedding import embed_text
from .sentiment import score_text
from .topic_classification import classify_topics


class EmbeddingUnavailable(Exception):
    pass


class SentimentUnavailable(Exception):
    pass


class TopicsUnavailable(Exception):
    pass


def reanalyze_opinion(opinion, text):
    """Recompute embedding, sentiment and predefined topics for edited text.

    Mirrors what ``Opinion.save()`` does for a brand new row, but forced
    rather than guarded by "only if still empty", and followed by
    ``reassign_to_nearest_clusters`` (rather than the plain, add-only
    ``assign_to_nearest_clusters``) since this opinion may already belong to
    clusters picked for its *previous* text.
    """
    opinion.text = text
    try:
        opinion.embedding = embed_text(text)
    except Exception as exc:
        raise EmbeddingUnavailable from exc
    try:
        opinion.sentiment = score_text(text)
    except Exception as exc:
        raise SentimentUnavailable from exc
    try:
        opinion.topic_ids, opinion.topic_analysis = classify_topics(
            text, opinion.embedding
        )
    except Exception as exc:
        raise TopicsUnavailable from exc
    opinion.save()
    reassign_to_nearest_clusters(opinion)
    return opinion
