from django.shortcuts import render
from pgvector.django import CosineDistance

from .embedding import embed_text
from .models import Opinion

# pgvector stores embeddings as float4, so a vector's distance from itself
# can land a hair above 0 instead of exactly 0. Padding the requested max
# distance by this much keeps an exact-text match from being filtered out.
DISTANCE_EPSILON = 1e-4


def search(request):
    """Search opinions by cosine distance to a typed-in statement.

    The query is embedded with the same (document) embedding function used
    for stored opinions, rather than a query-specific one, so that searching
    for an opinion's exact text reproduces its exact embedding -- see
    CLAUDE.md for why this doesn't yet use encode_queries.
    """
    query = request.GET.get("query", "").strip()
    max_distance = _parse_max_distance(request.GET.get("max_distance"))

    results = []
    if query:
        query_embedding = embed_text(query)
        matches = (
            Opinion.objects.annotate(
                distance=CosineDistance("embedding", query_embedding)
            )
            .filter(distance__lte=max_distance + DISTANCE_EPSILON)
            .order_by("distance")
        )
        results = [
            {
                "text": opinion.text,
                "topic": opinion.topic,
                "distance": opinion.distance,
                "similarity": 1 - opinion.distance,
            }
            for opinion in matches
        ]

    return render(
        request,
        "opinions/search.html",
        {"query": query, "max_distance": max_distance, "results": results},
    )


def _parse_max_distance(raw_value, default=0.5):
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return default
    return min(max(value, 0.0), 1.0)
