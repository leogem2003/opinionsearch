from django.shortcuts import render

from .search import parse_max_distance, search_opinions


def search(request):
    """Render the search page for the query and slider value in the URL.

    The query itself lives in ``opinions.search`` so that it can be run
    outside a request too -- see that module.
    """
    query = request.GET.get("query", "").strip()
    max_distance = parse_max_distance(request.GET.get("max_distance"))

    results = []
    if query:
        results = [
            {
                "text": opinion.text,
                "topic": opinion.topic,
                "distance": opinion.distance,
                "distance": opinion.distance,
            }
            for opinion in search_opinions(query, max_distance)
        ]

    return render(
        request,
        "opinions/search.html",
        {"query": query, "max_distance": max_distance, "results": results},
    )
