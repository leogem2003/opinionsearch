"""The search query itself, kept apart from the view that renders it.

design.md's read path is "embed the keywords, match them against the stored
vectors, then filter" -- that part is independent of HTTP, so it lives here
and ``opinions.views.search`` is left with request parsing and rendering.
Anything else that needs the same result set (notably
``notebooks/umap_projection.ipynb``, which projects the matched embeddings
into 2D) can then run the query the page runs instead of a look-alike of it.
"""

from pgvector.django import CosineDistance

from .embedding import embed_text
from .models import Opinion

# pgvector stores embeddings as float4, so a vector's distance from itself
# can land a hair above 0 instead of exactly 0. Padding the requested max
# distance by this much keeps an exact-text match from being filtered out.
DISTANCE_EPSILON = 1e-4

DEFAULT_MAX_DISTANCE = 0.5


def search_opinions(query, max_distance=DEFAULT_MAX_DISTANCE):
    """Return opinions within ``max_distance`` cosine distance of ``query``.

    The query is embedded with the same (document) embedding function used
    for stored opinions, rather than a query-specific one, so that searching
    for an opinion's exact text reproduces its exact embedding -- see
    CLAUDE.md for why this doesn't yet use encode_queries.

    Yields a lazy ``QuerySet`` of ``Opinion`` rows ordered nearest-first, each
    annotated with a ``distance`` attribute. Callers that only need the text
    (the view) and callers that need the vectors too (the projection
    notebook) therefore share one definition of "what matched".
    """
    query_embedding = embed_text(query)
    return (
        Opinion.objects.annotate(distance=CosineDistance("embedding", query_embedding))
        .filter(distance__lte=max_distance + DISTANCE_EPSILON)
        .order_by("distance")
    )


def parse_max_distance(raw_value, default=DEFAULT_MAX_DISTANCE):
    """Coerce the search form's slider value into a distance in [0, 1]."""
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return default
    return min(max(value, 0.0), 1.0)
