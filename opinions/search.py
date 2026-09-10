"""The search query itself, kept apart from the view that renders it.

design.md's read path is "embed the keywords, match them against the stored
vectors, then filter" -- that part is independent of HTTP, so it lives here
and ``opinions.views.search`` is left with request parsing and rendering.
Anything else that needs the same result set (notably
``notebooks/umap_projection.ipynb``, which projects the matched embeddings
into 2D, and ``opinions.projection``, which does the same for the /search
page) can then run the query the page runs instead of a look-alike of it.
"""

import hashlib
import math

from django.core.cache import cache
from pgvector.django import CosineDistance

from .embedding import embed_text
from .models import Opinion
from .sentiment import score_text

# pgvector stores embeddings as float4, so a vector's distance from itself
# can land a hair above 0 instead of exactly 0. Padding the requested max
# distance by this much keeps an exact-text match from being filtered out.
DISTANCE_EPSILON = 1e-4

DEFAULT_MAX_DISTANCE = 0.5


def search_opinions(query, max_distance=DEFAULT_MAX_DISTANCE, query_embedding=None):
    """Return opinions within ``max_distance`` cosine distance of ``query``.

    The query is embedded with the same (document) embedding function used
    for stored opinions, rather than a query-specific one, so that searching
    for an opinion's exact text reproduces its exact embedding -- see
    CLAUDE.md for why this doesn't yet use encode_queries.

    ``query_embedding`` lets a caller that already has it (namely
    ``search_opinions_cached``, which also needs it on its own to place the
    query itself on the /search page's plot) skip embedding the same text
    twice; by default it's computed here as before.

    Yields a lazy ``QuerySet`` of ``Opinion`` rows ordered nearest-first, each
    annotated with a ``distance`` attribute. Callers that only need the text
    (the view) and callers that need the vectors too (the projection
    notebook) therefore share one definition of "what matched".
    """
    if query_embedding is None:
        query_embedding = embed_text(query)
    return (
        Opinion.objects.annotate(distance=CosineDistance("embedding", query_embedding))
        .filter(distance__lte=max_distance + DISTANCE_EPSILON)
        .order_by("distance")
    )


SEARCH_CACHE_TTL = 5  # seconds TODO: Only cache query's embedding, not the whole search


def _search_cache_key(query, max_distance):
    # Hashed rather than interpolated directly: an arbitrary search query
    # shouldn't end up embedded verbatim in a cache backend's key space.
    digest = hashlib.sha256(f"{query}\x1f{max_distance:.6f}".encode()).hexdigest()
    return f"opinions:search:{digest}"


def search_opinions_cached(query, max_distance=DEFAULT_MAX_DISTANCE):
    """Same result as ``search_opinions``, but cached on ``(query, max_distance)``.

    The /search page also lets the visitor retune the UMAP projection (see
    ``opinions.projection``) without changing the query or the distance
    slider -- that's a plain page reload with the same GET params for
    ``query``/``max_distance``, so re-embedding the query and re-running the
    CosineDistance scan on every such reload would be wasted work; only the
    projection actually needs to change. Caching here (rather than around the
    projection) is what makes that reload skip straight to reprojecting.

    Returns a dict with:

    - ``rows``: a list of plain dicts (id, text, topics, author, distance,
      similarity, sentiment, embedding) instead of ``search_opinions``'s lazy
      annotated QuerySet, since a QuerySet can't survive a round trip through
      the cache. ``sentiment`` is the raw 1-5 score stored on the Opinion (see
      ``opinions.sentiment``), not yet turned into a label -- that's a display
      concern, left to whatever renders these rows. ``topics`` is the row's
      whole discovered topic path (see ``_topic_path``) rather than one topic,
      so that changing which layer of the hierarchy the page shows doesn't
      have to invalidate this cache.
    - ``query_embedding``: the query's own embedding, cached alongside the
      rows for the same reason -- ``opinions.projection`` plots the query
      itself next to its matches, and shouldn't need to re-embed the query
      text to do that when only the UMAP sliders changed.
    - ``query_sentiment``: the query's own 1-5 sentiment score (see
      ``opinions.sentiment.score_text``), cached for the same reason as
      ``query_embedding`` -- the /search page shows it too, and a UMAP-only
      reload shouldn't re-score the same query text.
    """
    key = _search_cache_key(query, max_distance)
    cached = cache.get(key)
    if cached is None:
        query_embedding = embed_text(query)
        query_sentiment = score_text(query)
        opinions = (
            search_opinions(
                query, max_distance, query_embedding=query_embedding
            ).select_related("author")
            # One extra query for every row's cluster memberships, rather than
            # one per row while building the topic list below.
            .prefetch_related("clusters")
        )
        rows = [
            {
                "id": opinion.id,
                "text": opinion.text,
                "topics": _topic_path(opinion),
                "author": opinion.author.username if opinion.author_id else None,
                "distance": float(opinion.distance),
                "similarity": 1 - float(opinion.distance),
                "sentiment": opinion.sentiment,
                "embedding": [float(v) for v in opinion.embedding],
            }
            for opinion in opinions
        ]
        cached = {
            "rows": rows,
            "query_embedding": query_embedding,
            "query_sentiment": query_sentiment,
        }
        cache.set(key, cached, SEARCH_CACHE_TTL)
    return cached


def _topic_path(opinion):
    """This opinion's discovered topics, finest layer first.

    Returns ``[{"layer": 0, "label": "rent, tenants, ..."}, ...]``, one entry
    per layer of the hierarchy the opinion was placed in (see
    ``opinions.clustering``). Layers where it came out as noise are simply
    missing, so this can be shorter than the hierarchy is deep -- or empty,
    for an opinion published since the last clustering run.
    """
    return [
        {"layer": cluster.layer, "label": cluster.label}
        # Sorted in Python, not the database: the memberships are already
        # prefetched, and re-ordering them would re-query per row.
        for cluster in sorted(opinion.clusters.all(), key=lambda c: c.layer)
    ]


def parse_max_distance(raw_value, default=DEFAULT_MAX_DISTANCE):
    """Coerce the search form's slider value into a distance in [0, 1]."""
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return min(max(value, 0.0), 1.0)
