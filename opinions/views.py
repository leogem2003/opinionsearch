import hashlib
import math
import colorsys

import numpy as np
from django.shortcuts import render

from .projection import (
    MIN_POINTS_TO_PROJECT,
    parse_min_dist,
    parse_n_neighbors,
    project_2d,
)
from .search import parse_max_distance, search_opinions_cached
from .sentiment import sentiment_label

# The plot is an inline SVG in the template; these define its coordinate
# space (viewBox) and how far points are kept from the edges. Drawing the
# query's star marker itself (turning a center point into a polygon) is left
# to the template/JS -- see search.html's starPoints() -- since it's pure
# presentation, not something derived from the data.
PLOT_WIDTH = 760
PLOT_HEIGHT = 520
PLOT_PADDING = 24

# Size of the star marking the query itself (see _star_points), and of its
# smaller copy drawn in the legend.
QUERY_MARKER_RADII = (12, 5)
LEGEND_STAR_RADII = (6, 2.5)

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
        # it's only needed for the projection, computed separately. Add the
        # sentiment label here rather than storing it on the row: it's a
        # display concern derived from the stored 1-5 score, same as
        # "similarity" is derived from "distance".
        results = [
            {
                **{k: v for k, v in row.items() if k != "embedding"},
                "sentiment_label": sentiment_label(row["sentiment"]),
            }
            for row in rows
        ]

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
                "sentiment": row["sentiment"],
                "sentiment_label": sentiment_label(row["sentiment"]),
                "color": _topic_color(row["topic"]),
                "x": screen_x,
                "y": screen_y,
            }
        )

    query_x, query_y = to_screen(*query_coord)
    query_point = {"x": query_x, "y": query_y}
    return points, query_point

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
    lightness = 0.35 + (lightness_step * 0.08) # Yields 0.35, 0.43, or 0.51
    
    # 3. Lock Saturation
    saturation = 0.70 
    
    # Convert HLS to RGB
    r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)
    
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))