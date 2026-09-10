import hashlib
import math

import numpy as np
from django.shortcuts import render

from .projection import (
    MIN_POINTS_TO_PROJECT,
    parse_min_dist,
    parse_n_neighbors,
    project_2d,
)
from .search import parse_max_distance, search_opinions_cached

# The plot is an inline SVG in the template; these define its coordinate
# space (viewBox) and how far points are kept from the edges.
PLOT_WIDTH = 760
PLOT_HEIGHT = 520
PLOT_PADDING = 24

# Size of the star marking the query itself (see _star_points), and of its
# smaller copy drawn in the legend.
QUERY_MARKER_RADII = (12, 5)
LEGEND_STAR_RADII = (6, 2.5)

# Fixed, tab10-like palette. A topic maps onto one of these by hashing its
# name (see _topic_color) rather than by position in this request's result
# set, so a topic keeps the same colour from one search to the next.
TOPIC_PALETTE = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
]


def search(request):
    """Render the search page: results list, plus a 2D plot of their embeddings.

    The query lives in ``opinions.search`` (cached on ``(query,
    max_distance)`` so that retuning the UMAP sliders below doesn't re-embed
    the query or rescan the vector index -- see
    ``search.search_opinions_cached``), and the projection lives in
    ``opinions.projection``. This view is just request parsing, calling
    both, and laying the projected points (including the query itself) out
    in the SVG's coordinate space.
    """
    query = request.GET.get("query", "").strip()
    max_distance = parse_max_distance(request.GET.get("max_distance"))
    n_neighbors = parse_n_neighbors(request.GET.get("n_neighbors"))
    min_dist = parse_min_dist(request.GET.get("min_dist"))

    results = []
    points = []
    query_point = None
    topics = []
    too_few_to_plot = False

    if query:
        cached = search_opinions_cached(query, max_distance)
        rows = cached["rows"]
        # Drop each row's embedding for the plain-text results list below --
        # it's only needed for the projection, computed separately.
        results = [{k: v for k, v in row.items() if k != "embedding"} for row in rows]

        if len(rows) >= MIN_POINTS_TO_PROJECT:
            points, query_point = _project_points(
                rows, cached["query_embedding"], n_neighbors, min_dist
            )
            topics = sorted({row["topic"] for row in rows})
        else:
            too_few_to_plot = bool(rows)

    return render(
        request,
        "opinions/search.html",
        {
            "query": query,
            "max_distance": max_distance,
            "n_neighbors": n_neighbors,
            "min_dist": min_dist,
            "results": results,
            "points": points,
            "query_point": query_point,
            "legend_star_points": _star_points(7, 7, *LEGEND_STAR_RADII),
            "topics": [
                {"name": topic, "color": _topic_color(topic)} for topic in topics
            ],
            "too_few_to_plot": too_few_to_plot,
            "min_points_to_plot": MIN_POINTS_TO_PROJECT,
            "plot_width": PLOT_WIDTH,
            "plot_height": PLOT_HEIGHT,
        },
    )


def _project_points(rows, query_embedding, n_neighbors, min_dist):
    """Project ``rows``' embeddings and the query to 2D, centered on the query.

    UMAP's axes carry no absolute meaning on their own, so nothing is lost by
    choosing our own origin and scale for the plot rather than the usual
    min/max-to-viewBox mapping: centering on the query -- what was actually
    searched for -- puts it in the middle of the picture, with every match
    laid out around it at a screen distance that (loosely; a 2D projection is
    lossy) tracks its distance from the query. One scale is used for both
    axes so that those screen distances stay comparable in x and y, rather
    than each axis being stretched independently to fill the plot.
    """
    coords, query_coord = project_2d(
        [row["embedding"] for row in rows],
        query_embedding=query_embedding,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
    )
    xs, ys = coords[:, 0], coords[:, 1]

    radius = max(np.abs(xs - query_coord[0]).max(), np.abs(ys - query_coord[1]).max())
    radius = radius or 1.0
    scale = (min(PLOT_WIDTH, PLOT_HEIGHT) / 2 - PLOT_PADDING) / radius

    def to_screen(x, y):
        return (
            PLOT_WIDTH / 2 + (x - query_coord[0]) * scale,
            # SVG y grows downward; flipped to match the notebook's plots.
            PLOT_HEIGHT / 2 - (y - query_coord[1]) * scale,
        )

    points = []
    for row, x, y in zip(rows, xs, ys):
        screen_x, screen_y = to_screen(x, y)
        points.append(
            {
                "text": row["text"],
                "topic": row["topic"],
                "author": row["author"],
                "similarity": row["similarity"],
                "color": _topic_color(row["topic"]),
                "x": screen_x,
                "y": screen_y,
            }
        )

    query_x, query_y = to_screen(*query_coord)
    query_point = {
        "x": query_x,
        "y": query_y,
        "star_points": _star_points(query_x, query_y, *QUERY_MARKER_RADII),
    }
    return points, query_point


def _star_points(cx, cy, outer_r, inner_r):
    """The ``points`` attribute for a 5-point SVG ``<polygon>`` star.

    Used both for the query's marker on the plot and for its match in the
    legend, so the legend swatch is recognisably the same shape.
    """
    coords = []
    for i in range(10):
        angle = math.pi / 2 + i * math.pi / 5
        r = outer_r if i % 2 == 0 else inner_r
        coords.append(f"{cx + r * math.cos(angle):.1f},{cy - r * math.sin(angle):.1f}")
    return " ".join(coords)


def _topic_color(topic):
    """A stable palette colour for a topic, independent of any one request's results."""
    digest = hashlib.md5(topic.encode()).hexdigest()
    return TOPIC_PALETTE[int(digest, 16) % len(TOPIC_PALETTE)]
