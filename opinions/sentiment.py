"""Sentiment scoring for opinions, via nlptown/bert-base-multilingual-uncased-sentiment.

Mirrors ``opinions/embedding.py``: a single lazily-loaded, process-wide model
(``get_sentiment_pipeline()``, ``lru_cache``d so the weights load once), a
single-text convenience wrapper (``score_text``) built on a batched one
(``score_texts``) for callers -- fixture loading, in particular -- that have
more than one text to score at once.

The model itself is a 5-way star-rating classifier (its own labels are the
strings ``"1 star"`` through ``"5 stars"``), not a positive/negative/neutral
one. ``score_texts`` reduces each label to the star count alone (an int,
1-5) -- that's what ``Opinion.sentiment`` stores. Turning a stored score back
into a human-readable label ("very negative" .. "very positive") is a
separate, cheap step (``sentiment_label``), kept out of what's stored so the
wording can change without touching any data.
"""

from functools import lru_cache

from transformers import pipeline

MODEL_NAME = "nlptown/bert-base-multilingual-uncased-sentiment"

# The model's outputs (1-5 stars) mapped onto a label for display. Deliberately
# a function of the stored integer rather than something stored alongside it --
# see the module docstring.
SENTIMENT_LABELS = {
    1: "very negative",
    2: "negative",
    3: "neutral",
    4: "positive",
    5: "very positive",
}


@lru_cache(maxsize=1)
def get_sentiment_pipeline():
    """Return the process-wide sentiment pipeline, loading it on first use.

    Lazy and cached for the same reason as ``embedding.get_embedder``: the
    weights are multi-GB-adjacent and downloaded from the Hugging Face Hub on
    first use, so this must never run at import time, and every caller in the
    process should share the one loaded pipeline.
    """
    return pipeline("sentiment-analysis", model=MODEL_NAME, tokenizer=MODEL_NAME)


def score_texts(texts: list[str]) -> list[int]:
    """Score a batch of texts in one pipeline call, each as a 1-5 star rating.

    Batching matters here for the same reason it does in
    ``embedding.embed_texts``: one pipeline call over many texts (e.g. a
    fixture's worth of statements) is much cheaper than calling
    ``score_text`` once per text.
    """
    if not texts:
        return []
    pipe = get_sentiment_pipeline()
    return [int(result["label"].split()[0]) for result in pipe(texts, truncation=True)]


def score_text(text: str) -> int:
    """Score a single passage of text as a 1-5 star rating."""
    return score_texts([text])[0]


def sentiment_label(score) -> str:
    """The display label for a stored 1-5 sentiment score.

    Returns ``"unscored"`` for ``None`` (an Opinion saved before this field
    existed, or with empty text) rather than raising, since this is meant to
    be called straight from a template.
    """
    if score is None:
        return "unscored"
    return SENTIMENT_LABELS.get(score, "unknown")
