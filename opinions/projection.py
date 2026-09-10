"""2D UMAP projection of opinion embeddings, for the /search page's plot.

``opinions.search`` answers "what matched"; this answers "where do the
matches sit on a 2D map" -- design.md's read path calls for both. The
parameter choices (``metric="cosine"``, the ``n_neighbors`` clamp) follow the
same reasoning worked out against this project's data in
``notebooks/umap_projection.ipynb`` (see its section 4 and 7): opinions are
compared everywhere else in this project by cosine distance (the search view,
the HNSW index's ``vector_cosine_ops``), and ``n_neighbors`` can't exceed
``n_samples - 1`` -- with the small result sets this app deals with today,
that ceiling is routinely the binding constraint, not a corner case.
"""

import warnings

import numpy as np
import umap

DEFAULT_N_NEIGHBORS = 15
DEFAULT_MIN_DIST = 0.1

MIN_N_NEIGHBORS = 2
MAX_N_NEIGHBORS = 50

# Below this, a 2D UMAP layout stops meaning anything (n_neighbors would
# clamp to a value close to n_samples itself -- see the notebook's section 7).
MIN_POINTS_TO_PROJECT = 4


def project_2d(
    embeddings,
    query_embedding=None,
    n_neighbors=DEFAULT_N_NEIGHBORS,
    min_dist=DEFAULT_MIN_DIST,
):
    """Project a list of embedding vectors to 2D coordinates.

    ``n_neighbors`` is clamped to what the dataset can support rather than
    passed straight to UMAP, which would otherwise just warn and clamp it
    itself -- silencing that warning here means callers only see the
    clamped-or-not distinction if they choose to check it.

    When ``query_embedding`` is given, it's fit together with ``embeddings``
    in one UMAP call rather than transformed separately afterward, so the
    query's position is directly comparable to the opinions' rather than the
    result of a second, independent fit (see
    ``notebooks/umap_projection.ipynb`` section 8, which does the same for
    the same reason). Returns ``(coords, query_coord)``, with
    ``query_coord`` ``None`` when no ``query_embedding`` was given.
    """
    vectors = list(embeddings)
    if query_embedding is not None:
        vectors = vectors + [query_embedding]

    n_samples = len(vectors)
    effective_neighbors = max(MIN_N_NEIGHBORS, min(n_neighbors, n_samples - 1))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=UserWarning)
        reducer = umap.UMAP(
            n_neighbors=effective_neighbors,
            min_dist=min_dist,
            n_components=2,
            metric="cosine",
            random_state=42,
        )
        coords = reducer.fit_transform(np.asarray(vectors, dtype=np.float32))

    if query_embedding is not None:
        return coords[:-1], coords[-1]
    return coords, None


def parse_n_neighbors(raw_value, default=DEFAULT_N_NEIGHBORS):
    """Coerce the n_neighbors slider's value into [MIN_N_NEIGHBORS, MAX_N_NEIGHBORS]."""
    try:
        value = int(float(raw_value))
    except (TypeError, ValueError):
        return default
    return min(max(value, MIN_N_NEIGHBORS), MAX_N_NEIGHBORS)


def parse_min_dist(raw_value, default=DEFAULT_MIN_DIST):
    """Coerce the min_dist slider's value into [0, 0.99] (UMAP's own range)."""
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return default
    return min(max(value, 0.0), 0.99)
