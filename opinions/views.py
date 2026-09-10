import colorsys
import hashlib

import numpy as np
from django.shortcuts import get_object_or_404, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET
from pgvector.django import CosineDistance

from .clustering import DEFAULT_ASSIGNMENT_MAX_DISTANCE, layer_count
from .models import Cluster
from .projection import (
    DEFAULT_MIN_DIST,
    DEFAULT_N_NEIGHBORS,
    MIN_POINTS_TO_PROJECT,
    parse_min_dist,
    parse_n_neighbors,
    project_2d,
)
from .search import embed_query_cached
from .sentiment import SENTIMENT_LABELS, sentiment_label
from .topic_classification import TOPICS


def _civic_topics(opinion):
    """Predefined civic categories this opinion matched, as {id, title} dicts.

    Independent of the discovered EVōC cluster it was matched through -- see
    CLAUDE.md's note that the two systems don't map onto each other.
    """
    return [topic for topic in TOPICS if topic["id"] in opinion.topic_ids]


# A little headroom around the plot's centre point, so the single farthest
# point doesn't sit exactly on the edge -- see _build_cluster_plot_data.
AXIS_PADDING_FACTOR = 1.1

# How many opinions a single search/browse result shows at most -- same
# convention as opinions/topics.py's SEARCH_LIMIT.
SEARCH_LIMIT = 50

DEFAULT_N = 5
MIN_N = 1
MAX_N = 20


@require_GET
def search(request):
    """Render the cluster-search page: the N discovered topics closest to a
    typed query, their opinions' sentiment breakdown, and a 2D projection.

    Unlike the old per-opinion distance threshold, matching now happens at
    the topic level: the query is embedded once (``embed_query_cached``,
    cached so retuning a slider or picking a different level doesn't
    re-embed it), then ``_closest_clusters`` finds the N nearest ``Cluster``
    centroids at the chosen hierarchy layer, and every opinion belonging to
    any of them is shown together. ``_cluster_results_context`` (shared with
    ``browse`` below) turns that opinion set into the same plot/list shape
    the template already knows how to render.
    """
    query = request.GET.get("query", "").strip()
    n = _parse_n(request.GET.get("n"))
    n_neighbors = parse_n_neighbors(request.GET.get("n_neighbors"))
    min_dist = parse_min_dist(request.GET.get("min_dist"))
    date_from = parse_date(request.GET.get("date_from", ""))
    date_to = parse_date(request.GET.get("date_to", ""))
    n_layers = layer_count()
    topic_level = _parse_topic_level(request.GET.get("topic_level"), n_layers)

    context = {
        "query": query,
        "n": n,
        "n_neighbors": n_neighbors,
        "min_dist": min_dist,
        "date_from": date_from,
        "date_to": date_to,
        "topic_level": topic_level,
        "max_topic_level": max(n_layers - 1, 0),
        "level_range": range(n_layers),
        "has_topics": n_layers > 0,
        "clusters_found": [],
        "no_matches": False,
        "weak_match": False,
        **_empty_results_context(),
    }

    if query and n_layers > 0:
        query_embedding, query_sentiment = embed_query_cached(query)
        closest = _closest_clusters(query_embedding, topic_level, n)
        pairs = _opinions_for_clusters(closest, date_from=date_from, date_to=date_to)
        context["clusters_found"] = [
            {"label": cluster.label or f"topic {cluster.evoc_id}", "size": cluster.size}
            for cluster in closest
        ]
        context["no_matches"] = not pairs
        # "Closest" always returns something if any cluster exists at this
        # layer, however unrelated -- so a genuine "nothing close" warning
        # needs its own quality check, not just an empty result. Reusing
        # clustering.py's own conservative membership distance keeps this
        # project to one definition of "close enough", rather than a second,
        # untuned threshold living here.
        context["weak_match"] = bool(closest) and (
            closest[0].distance > DEFAULT_ASSIGNMENT_MAX_DISTANCE
        )
        context.update(
            _cluster_results_context(
                pairs,
                query=query,
                query_embedding=query_embedding,
                query_sentiment=query_sentiment,
                n_neighbors=n_neighbors,
                min_dist=min_dist,
            )
        )
    elif query:
        context["no_matches"] = True

    return render(request, "opinions/search.html", context)


@require_GET
def browse(request):
    """Click-through topic browser: pick a cluster, see its subtopics, repeat.

    Reaching a cluster with no children means there's nowhere narrower to
    go -- that's a leaf, so its opinions are shown with the same plot/list
    as ``search`` above (``_cluster_results_context``), just without a typed
    query or a query point on the plot. The breadcrumb trail is derived by
    walking ``Cluster.parent`` back from the current cluster rather than
    carried in the URL, so a bookmarked ``?cluster=`` link always renders
    the same trail.
    """
    cluster_id = request.GET.get("cluster")
    cluster = get_object_or_404(Cluster, pk=cluster_id) if cluster_id else None

    if cluster is None:
        # Every cluster EVōC never merged upward hangs directly off the
        # (unstored) root, not necessarily at the broadest layer -- see
        # opinions/clustering.py's module docstring -- so "top level" is
        # every parentless cluster, not just layer == top_layer.
        options = Cluster.objects.filter(parent__isnull=True).order_by(
            "-layer", "-size"
        )
        return render(
            request,
            "opinions/browse.html",
            {"current": None, "breadcrumbs": [], "options": options},
        )

    breadcrumbs = _ancestors(cluster)
    children = cluster.children.order_by("-size")
    if children.exists():
        return render(
            request,
            "opinions/browse.html",
            {"current": cluster, "breadcrumbs": breadcrumbs, "options": children},
        )

    pairs = _opinions_for_clusters([cluster])
    context = {"current": cluster, "breadcrumbs": breadcrumbs, "options": None}
    context.update(
        _cluster_results_context(
            pairs, n_neighbors=DEFAULT_N_NEIGHBORS, min_dist=DEFAULT_MIN_DIST
        )
    )
    return render(request, "opinions/browse.html", context)


def _ancestors(cluster):
    """``cluster``'s parent chain, broadest first, for a breadcrumb trail."""
    trail = []
    node = cluster.parent
    while node is not None:
        trail.append(node)
        node = node.parent
    trail.reverse()
    return trail


def _closest_clusters(query_embedding, layer, n):
    """The N ``Cluster``s at ``layer`` whose centroid is nearest ``query_embedding``.

    Same annotate/order_by/CosineDistance pattern already proven against
    Opinion in opinions/search.py and against Cluster.centroid in
    opinions/clustering.py's assign_to_nearest_clusters.
    """
    return list(
        Cluster.objects.filter(layer=layer)
        .annotate(distance=CosineDistance("centroid", query_embedding))
        .order_by("distance")[:n]
    )


def _opinions_for_clusters(clusters, limit=SEARCH_LIMIT, date_from=None, date_to=None):
    """(opinion, cluster) pairs for every member of any of ``clusters``, up
    to ``limit`` total.

    EVōC labels each layer as a single partition, so an opinion belongs to
    at most one cluster per layer -- these clusters' memberships can't
    overlap, so no de-duplication is needed across them. Members are drawn
    round-robin across clusters, nearest cluster first within each round,
    rather than filling the nearest cluster's whole quota before touching
    the next: a single large nearby topic would otherwise crowd every other
    closest topic out of the limit entirely, so the plotted opinions (and
    the topic colours drawn from them) would cover far fewer distinct
    topics than "closest topics" actually found. ``date_from``/``date_to``
    (inclusive, either or both optional) narrow each cluster's members by
    ``Opinion.timestamp`` before the round-robin draw.
    """
    queues = []
    for cluster in clusters:
        members = cluster.opinions.select_related("author").prefetch_related(
            "arguments"
        )
        if date_from is not None:
            members = members.filter(timestamp__date__gte=date_from)
        if date_to is not None:
            members = members.filter(timestamp__date__lte=date_to)
        queues.append((cluster, iter(members.order_by("-timestamp", "-pk")[:limit])))

    pairs = []
    while len(pairs) < limit and queues:
        still_going = []
        for cluster, queue in queues:
            if len(pairs) >= limit:
                still_going.append((cluster, queue))
                continue
            opinion = next(queue, None)
            if opinion is not None:
                pairs.append((opinion, cluster))
                still_going.append((cluster, queue))
        queues = still_going
    return pairs


def _empty_results_context():
    return {
        "results": [],
        "result_limit": SEARCH_LIMIT,
        "plot_data": None,
        "too_few_to_plot": False,
        "min_points_to_plot": MIN_POINTS_TO_PROJECT,
        "query_sentiment": None,
        "query_sentiment_label": None,
        "sentiment_labels": SENTIMENT_LABELS,
    }


def _cluster_results_context(
    pairs,
    query=None,
    query_embedding=None,
    query_sentiment=None,
    n_neighbors=DEFAULT_N_NEIGHBORS,
    min_dist=DEFAULT_MIN_DIST,
):
    """The results list + plot context shared by ``search`` and ``browse``.

    ``pairs`` is a list of ``(Opinion, Cluster)`` -- the cluster each opinion
    was matched through, already known (see ``_opinions_for_clusters``)
    rather than looked up again per opinion. The results list omits
    technical fields (distance/similarity/topic path) on purpose -- cluster
    membership is the match now, not a per-opinion score -- keeping only
    what a reader wants: the text, who published it, and when.
    """
    context = _empty_results_context()
    if not pairs:
        return context

    context["results"] = [
        {
            "id": opinion.pk,
            "text": opinion.text,
            "author": opinion.author.username if opinion.author_id else None,
            "author_id": opinion.author_id,
            "date": opinion.timestamp,
            # Not shown in the list itself (see the template) -- only read
            # client-side to count the sentiment bar chart's bars.
            "sentiment": opinion.sentiment,
            "sentiment_label": sentiment_label(opinion.sentiment),
            "topics": _civic_topics(opinion),
            "argument_count": len(opinion.arguments.all()),
        }
        for opinion, _ in pairs
    ]
    context["query_sentiment"] = query_sentiment
    context["query_sentiment_label"] = (
        sentiment_label(query_sentiment) if query_sentiment is not None else None
    )

    if len(pairs) >= MIN_POINTS_TO_PROJECT:
        context["plot_data"] = _build_cluster_plot_data(
            pairs, query, query_embedding, query_sentiment, n_neighbors, min_dist
        )
    else:
        context["too_few_to_plot"] = True
    return context


def _build_cluster_plot_data(
    pairs, query, query_embedding, query_sentiment, n_neighbors, min_dist
):
    """Project ``pairs``' embeddings (and the query, if any) to 2D for Chart.js.

    Mirrors the old _build_plot_data's shape (points/axis_range/topics[/query_point])
    so search.html's existing Chart.js code keeps working; the difference is
    where each point's topic label comes from -- directly off the cluster it
    was matched through, rather than re-derived from a stored per-opinion
    topic path.
    """
    coords, query_coord = project_2d(
        [opinion.embedding for opinion, _ in pairs],
        query_embedding=query_embedding,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
    )
    xs, ys = coords[:, 0], coords[:, 1]

    points = [
        {
            "x": float(x),
            "y": float(y),
            # The map layout (see _cluster_results.html) plots these instead
            # of x/y when the opinion has one; null when it doesn't, so that
            # layout simply skips it rather than guessing a placement.
            "lat": opinion.geo_coordinates.y if opinion.geo_coordinates else None,
            "lon": opinion.geo_coordinates.x if opinion.geo_coordinates else None,
            "text": opinion.text,
            # Grouped/coloured by cluster identity (topic_id), not by label
            # text: two distinct clusters can end up with the same c-TF-IDF
            # label (see topic_labels.py), and merging them by text would
            # under-count the topics actually plotted relative to
            # "clusters_found" above them on the page.
            "topic_id": cluster.pk,
            "topic": cluster.label or f"topic {cluster.evoc_id}",
            "id": opinion.pk,
            "author": opinion.author.username if opinion.author_id else None,
            "author_id": opinion.author_id,
            "sentiment": opinion.sentiment,
            "sentiment_label": sentiment_label(opinion.sentiment),
            # Predefined civic categories (opinions/topic_classification.py),
            # independent of "topic"/"topic_id" above, which are the
            # *discovered* EVōC cluster this point was matched through --
            # see CLAUDE.md's note that the two systems don't map onto each
            # other.
            "categories": _civic_topics(opinion),
            "argument_count": len(opinion.arguments.all()),
        }
        for (opinion, cluster), x, y in zip(pairs, xs, ys)
    ]

    if query_coord is not None:
        center_x, center_y = float(query_coord[0]), float(query_coord[1])
    else:
        center_x, center_y = float(xs.mean()), float(ys.mean())

    # float(...) here, not just on the pieces above: numpy's .max() returns a
    # numpy scalar (float32), which json_script's json.dumps can't serialize.
    radius = float(max(np.abs(xs - center_x).max(), np.abs(ys - center_y).max()) or 1.0)
    radius *= AXIS_PADDING_FACTOR

    plot_data = {
        "points": points,
        "axis_range": {
            "min_x": center_x - radius,
            "max_x": center_x + radius,
            "min_y": center_y - radius,
            "max_y": center_y + radius,
        },
        # One entry per distinct cluster present (by id, see the "topic_id"
        # comment above), for Chart.js to turn into one dataset each (which
        # is also what draws the legend).
        "topics": [
            {"id": topic_id, "name": name, "color": _topic_color(name)}
            for topic_id, name in sorted(
                {point["topic_id"]: point["topic"] for point in points}.items(),
                key=lambda pair: pair[1],
            )
        ],
    }
    if query_coord is not None:
        plot_data["query_point"] = {
            "x": center_x,
            "y": center_y,
            "is_query": True,
            "text": query,
            "sentiment": query_sentiment,
            "sentiment_label": (
                sentiment_label(query_sentiment)
                if query_sentiment is not None
                else None
            ),
        }
    return plot_data


def _parse_n(raw_value):
    """Coerce the "max related topics" field into [MIN_N, MAX_N]."""
    try:
        value = int(float(raw_value))
    except (TypeError, ValueError):
        return DEFAULT_N
    return min(max(value, MIN_N), MAX_N)


def _parse_topic_level(raw_value, n_layers):
    """Coerce the topic-level control into a layer of the stored hierarchy.

    0 is the finest layer, higher numbers are broader topics -- the same
    direction as ``Cluster.layer``. Clamped to what has actually been
    discovered, so a stale bookmark can't ask for a layer that no longer
    exists after re-clustering.
    """
    try:
        value = int(float(raw_value))
    except (TypeError, ValueError):
        return 0
    return min(max(value, 0), max(n_layers - 1, 0))


def _topic_color(topic, num_hues=24):
    """
    Generates a stable, dynamic hex color for a topic.
    Uses quantization to ensure a minimum visual difference between colors.
    """
    digest = hashlib.md5(topic.encode()).hexdigest()

    # Grab a large enough integer from the hash to use for math
    hash_val = int(digest[:8], 16)

    # 1. Quantize the Hue
    # Snaps the color to one of `num_hues` distinct points on the color wheel.
    # 24 hues = a minimum of 15 degrees of separation between colors.
    hue_step = hash_val % num_hues
    hue = hue_step / num_hues

    # 2. Quantize the Lightness
    # Use a different part of the hash to pick between 3 safe lightness levels.
    # We keep them between 0.35 and 0.51 to ensure dark text contrast on white.
    lightness_step = (hash_val // num_hues) % 3
    lightness = 0.35 + (lightness_step * 0.08)  # Yields 0.35, 0.43, or 0.51

    # 3. Lock Saturation
    saturation = 0.70

    # Convert HLS to RGB
    r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)

    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))
