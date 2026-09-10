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
from .sentiment import SENTIMENT_LABELS, sentiment_label

# A little headroom around the query on the scatter chart's axes, so the
# single farthest point doesn't sit exactly on the edge -- see _build_plot_data.
AXIS_PADDING_FACTOR = 1.1

# Size of the star marking the query itself (see _star_points), and of its
# smaller copy drawn in the legend.
QUERY_MARKER_RADII = (12, 5)
LEGEND_STAR_RADII = (6, 2.5)

def search(request):
    """Render the search page: results list, a sentiment histogram, and a
    2D plot of the results' embeddings.

    The query lives in ``opinions.search`` (cached on ``(query,
    max_distance)`` so that retuning the UMAP sliders below doesn't re-embed
    or re-score the query, or rescan the vector index -- see
    ``search.search_opinions_cached``), and the projection lives in
    ``opinions.projection``. Both charts are drawn client-side by Chart.js
    (see search.html) from JSON this view embeds via the ``json_script``
    template filter -- this view's job is fetching that data and, for the
    scatter chart, turning embeddings into 2D coordinates; Chart.js handles
    pixel placement, the query's star marker, legends, tooltips and
    click-to-select, none of which needs computing by hand here.
    """
    query = request.GET.get("query", "").strip()
    max_distance = parse_max_distance(request.GET.get("max_distance"))
    n_neighbors = parse_n_neighbors(request.GET.get("n_neighbors"))
    min_dist = parse_min_dist(request.GET.get("min_dist"))

    results = []
    plot_data = None
    query_sentiment = None
    query_sentiment_label = None
    too_few_to_plot = False

    if query:
        cached = search_opinions_cached(query, max_distance)
        rows = cached["rows"]
        query_sentiment = cached["query_sentiment"]
        query_sentiment_label = sentiment_label(query_sentiment)

        # Drop each row's embedding for the plain-text results list below --
        # it's only needed for the projection, computed separately below.
        # The sentiment label is added here rather than stored on the row:
        # it's a display concern derived from the stored 1-5 score, the same
        # way "similarity" is derived from "distance".
        results = [
            {
                **{k: v for k, v in row.items() if k != "embedding"},
                "sentiment_label": sentiment_label(row["sentiment"]),
            }
            for row in rows
        ]

        if len(rows) >= MIN_POINTS_TO_PROJECT:
            plot_data = _build_plot_data(
                query,
                rows,
                cached["query_embedding"],
                query_sentiment,
                query_sentiment_label,
                n_neighbors,
                min_dist,
            )
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
            "plot_data": plot_data,
            "query_sentiment": query_sentiment,
            "query_sentiment_label": query_sentiment_label,
            "sentiment_labels": SENTIMENT_LABELS,
            "too_few_to_plot": too_few_to_plot,
            "min_points_to_plot": MIN_POINTS_TO_PROJECT,
        },
    )


def _build_plot_data(
    query,
    rows,
    query_embedding,
    query_sentiment,
    query_sentiment_label,
    n_neighbors,
    min_dist,
):
    """Project ``rows``' embeddings and the query to 2D for Chart.js's scatter chart.

    UMAP's axes carry no absolute meaning on their own, so nothing is lost by
    leaving pixel placement to Chart.js (search.html): this only returns the
    projection's own (x, y) coordinates -- one dict per point Chart.js can
    use directly as a data point, extra keys riding along for its tooltip
    and click handler -- plus an axis range that keeps the chart centered on
    the query rather than on the result set's bounding box, with the same
    radius applied to both axes so Chart.js's square aspect ratio renders
    them at one true scale instead of two independently stretched ones.
    """
    coords, query_coord = project_2d(
        [row["embedding"] for row in rows],
        query_embedding=query_embedding,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
    )
    xs, ys = coords[:, 0], coords[:, 1]
    query_x, query_y = float(query_coord[0]), float(query_coord[1])

    points = [
        {
            "x": float(x),
            "y": float(y),
            "text": row["text"],
            "topic": row["topic"],
            "author": row["author"],
            "similarity": row["similarity"],
            "sentiment": row["sentiment"],
            "sentiment_label": sentiment_label(row["sentiment"]),
        }
        for row, x, y in zip(rows, xs, ys)
    ]

    # float(...) here, not just on the pieces above: numpy's .max() returns a
    # numpy scalar (float32), which json_script's json.dumps can't serialize
    # -- unlike the coordinates above, nothing downstream converts this one.
    radius = float(max(np.abs(xs - query_x).max(), np.abs(ys - query_y).max()) or 1.0)
    radius *= AXIS_PADDING_FACTOR

    return {
        "points": points,
        "query_point": {
            "x": query_x,
            "y": query_y,
            "is_query": True,
            "text": query,
            "sentiment": query_sentiment,
            "sentiment_label": query_sentiment_label,
        },
        "axis_range": {
            "min_x": query_x - radius,
            "max_x": query_x + radius,
            "min_y": query_y - radius,
            "max_y": query_y + radius,
        },
        "topics": [
            {"name": topic, "color": _topic_color(topic)}
            for topic in sorted({row["topic"] for row in rows})
        ],
    }

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