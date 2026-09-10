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
    ``embed_query_cached``, used by the cluster-search page) skip embedding
    the same text twice; by default it's computed here as before.

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


SEARCH_CACHE_TTL = 5  # seconds


def _query_cache_key(query):
    # Hashed rather than interpolated directly: an arbitrary search query
    # shouldn't end up embedded verbatim in a cache backend's key space.
    digest = hashlib.sha256(query.encode()).hexdigest()
    return f"opinions:query-embedding:{digest}"


def embed_query_cached(query):
    """The query's own embedding and sentiment, cached briefly on the query text.

    The cluster-search page (``opinions.views.search``) lets a visitor
    re-run the same query against a different topic level or re-tune the
    UMAP sliders without retyping it -- that's a plain page reload with the
    same ``query`` GET param, so re-embedding and re-scoring it on every such
    reload would be wasted work; only the cluster lookup and/or projection
    actually need to change. Returns ``(embedding, sentiment)``.
    """
    key = _query_cache_key(query)
    cached = cache.get(key)
    if cached is None:
        cached = (embed_text(query), score_text(query))
        cache.set(key, cached, SEARCH_CACHE_TTL)
    return cached
