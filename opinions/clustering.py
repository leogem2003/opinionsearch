"""Hierarchical topic discovery over the opinion embeddings, via EVōC.

design.md's write path ends with "clusters are updated", and its read path
starts by matching a query against clusters. This module is that clustering
step. Topics are *discovered* here rather than declared by whoever publishes
an opinion -- there is no topic field on ``Opinion`` any more, only membership
of clusters found in the embedding space.

EVōC (https://github.com/TutteInstitute/evoc) is a high-dimensional vector
clusterer that produces a whole *hierarchy* in one fit rather than a single
flat partition:

- ``cluster_layers_`` -- one label array per resolution, ``[0]`` finest,
  later ones coarser. Each is an independent labelling: an opinion that is
  noise (``-1``) in the finest layer can still land inside a broader cluster
  further up, which is why ``Opinion.clusters`` is many-to-many rather than a
  single finest-layer foreign key.
- ``cluster_tree_`` -- ``{(layer, id): [(child_layer, child_id), ...]}``,
  the edges between those layers. It also contains a synthetic single root
  one layer above the coarsest; that root isn't stored, since "everything"
  is not a topic. The edges do not always step exactly one layer at a time:
  a cluster that never merges into anything broader hangs off the root
  directly, whatever layer it lives in.

EVōC outputs ids only, never words. Labelling happens afterwards, in
``opinions/topic_labels.py``.

A full re-fit is too slow to run on every publish, so a newly created opinion
doesn't wait for it: ``assign_to_nearest_clusters`` (called from
``Opinion.save()``) does a cheap nearest-centroid lookup against the
*existing* hierarchy instead, an approximation that a later ``recluster``
supersedes rather than depends on.
"""

from concurrent.futures import ThreadPoolExecutor

import evoc
import numpy as np
from django.db import models, transaction
from django.db.models import F
from pgvector.django import CosineDistance

from .models import Cluster, Opinion
from .topic_labels import label_clusters, medoid_index

# Defaults for the corpus sizes this project currently has (low hundreds of
# opinions). EVōC's own defaults (base_min_cluster_size=5, n_neighbors=15,
# min_samples=5) are tuned for far larger corpora and, measured on this
# project's sample corpus, collapse the finest two layers into near-duplicates
# while leaving ~30% of opinions as noise. Raise these towards EVōC's defaults
# as the corpus grows.
DEFAULT_MIN_CLUSTER_SIZE = 4
DEFAULT_N_NEIGHBORS = 10
DEFAULT_MIN_SAMPLES = 3

# Fixed seed so re-running clustering on unchanged data gives the same
# hierarchy, the same reasoning as the UMAP projection's random_state.
RANDOM_STATE = 42

# Below this, clustering is meaningless -- EVōC needs enough neighbours to
# build a graph at all, and returns a single all-noise layer well before it
# errors outright.
MIN_OPINIONS_TO_CLUSTER = 20

# Maximum cosine distance to a cluster's centroid for assign_to_nearest_clusters
# to place a new opinion there rather than leaving it unclustered -- see that
# function. Measured against the 500-tweet real corpus (manage.py
# load_senator_tweets): a genuine member sits, on average, 0.23 (layer 0) to
# 0.32 (the broadest layer) from its own centroid, 90% of them within 0.31-0.39
# depending on layer. 0.3 sits below most of that range on purpose -- it's
# deliberately conservative, favouring leaving an opinion unclustered over
# force-fitting it: at 0.35, over 60% of the opinions EVōC itself had called
# noise at the finest layer would get pulled into a cluster anyway, which
# would make "noise" mean much less. Revisit if that trade-off is wrong.
DEFAULT_ASSIGNMENT_MAX_DISTANCE = 0.3


class NotEnoughOpinions(RuntimeError):
    """Raised when the corpus is too small to discover topics in."""


def cluster_opinions(
    min_cluster_size=DEFAULT_MIN_CLUSTER_SIZE,
    n_neighbors=DEFAULT_N_NEIGHBORS,
    min_samples=DEFAULT_MIN_SAMPLES,
):
    """Re-discover the topic hierarchy over every embedded opinion.

    Runs EVōC over the whole corpus, then replaces the ``Cluster`` table and
    every opinion's cluster membership with the result, in one transaction --
    a half-applied hierarchy would be worse than the previous one. Returns the
    list of created ``Cluster`` objects.

    This is a whole-corpus operation by nature (a topic is a property of the
    corpus, not of a statement), so it is *not* called from ``Opinion.save``;
    ``manage.py recluster`` is how it gets run.
    """
    opinions = list(Opinion.objects.exclude(embedding=None).order_by("pk"))
    if len(opinions) < MIN_OPINIONS_TO_CLUSTER:
        raise NotEnoughOpinions(
            f"{len(opinions)} embedded opinion(s); need at least "
            f"{MIN_OPINIONS_TO_CLUSTER} for clustering to mean anything."
        )

    embeddings = np.vstack([opinion.embedding for opinion in opinions]).astype(
        np.float32
    )
    clusterer = evoc.EVoC(
        base_min_cluster_size=min_cluster_size,
        n_neighbors=n_neighbors,
        min_samples=min_samples,
        random_state=RANDOM_STATE,
    )
    clusterer.fit(embeddings)
    layers = [np.asarray(layer) for layer in clusterer.cluster_layers_]

    labels = _labels_for(layers, [opinion.text for opinion in opinions])

    with transaction.atomic():
        # Cascades to the membership table; opinions keep their embeddings.
        Cluster.objects.all().delete()
        clusters = _create_clusters(layers, labels, opinions, embeddings)
        _link_parents(clusters, clusterer.cluster_tree_, n_layers=len(layers))
        _assign_memberships(layers, clusters, opinions)
    return list(clusters.values())


def assign_to_nearest_clusters(opinion, max_distance=DEFAULT_ASSIGNMENT_MAX_DISTANCE):
    """Attach ``opinion`` to its nearest existing cluster in every layer.

    A full ``cluster_opinions()`` re-fits EVōC over the whole corpus and is
    too slow to run on every single publish. This is the cheap alternative
    called from ``Opinion.save()`` instead (see there): for each layer of the
    *already-discovered* hierarchy, find the cluster whose centroid is
    closest by cosine distance and join it, provided that distance is within
    ``max_distance`` -- otherwise the opinion is left unclustered in that
    layer, the same outcome EVōC's own noise label would give it. Nothing
    here moves a centroid or relabels a cluster, so this is only ever an
    approximation of what the next real ``cluster_opinions()`` run would find;
    it exists so a newly published opinion shows a topic immediately instead
    of waiting for that run.

    Does nothing (and returns an empty list) if there is no hierarchy yet, or
    the opinion has no embedding.
    """
    if opinion.embedding is None:
        return []

    assigned = []
    for layer in Cluster.objects.order_by().values_list("layer", flat=True).distinct():
        nearest = (
            Cluster.objects.filter(layer=layer)
            .annotate(distance=CosineDistance("centroid", opinion.embedding))
            .order_by("distance")
            .first()
        )
        if nearest is not None and nearest.distance <= max_distance:
            opinion.clusters.add(nearest)
            Cluster.objects.filter(pk=nearest.pk).update(size=F("size") + 1)
            assigned.append(nearest)
    return assigned


def reassign_to_nearest_clusters(opinion, max_distance=DEFAULT_ASSIGNMENT_MAX_DISTANCE):
    """Drop ``opinion``'s current memberships and re-run ``assign_to_nearest_clusters``.

    ``assign_to_nearest_clusters`` only ever adds -- called from
    ``Opinion.save()`` on a brand new row, it never has anything to remove.
    Editing an existing opinion's text is different: its embedding changes,
    so its old memberships (picked for the *previous* text) would otherwise
    linger alongside whatever the new text is assigned to. This clears them
    first, decrementing each old cluster's denormalised ``size`` by one to
    match, then reassigns from scratch.
    """
    old_clusters = list(opinion.clusters.all())
    opinion.clusters.clear()
    if old_clusters:
        Cluster.objects.filter(pk__in=[c.pk for c in old_clusters]).update(
            size=F("size") - 1
        )
    return assign_to_nearest_clusters(opinion, max_distance=max_distance)


def layer_count():
    """How many layers deep the stored hierarchy is (0 if never clustered)."""
    deepest = Cluster.objects.aggregate(models.Max("layer"))["layer__max"]
    return 0 if deepest is None else deepest + 1


def _labels_for(layers, texts):
    """c-TF-IDF labels for every cluster in every layer, keyed ``(layer, id)``.

    All layers are labelled in a single pass so that a term's inverse document
    frequency is computed against every other cluster, coarse and fine alike;
    labelling each layer separately would let the same word describe a broad
    topic and its own sub-topic.
    """
    texts_by_cluster = {}
    for layer_index, layer in enumerate(layers):
        for cluster_id in sorted(set(layer[layer >= 0].tolist())):
            members = [text for text, label in zip(texts, layer) if label == cluster_id]
            texts_by_cluster[(layer_index, cluster_id)] = members
    return label_clusters(texts_by_cluster)


def _create_clusters(layers, labels, opinions, embeddings):
    """Create one Cluster row per (layer, id), with centroid, size and exemplar.

    EVōC's own fit already uses every core (its numba routines default to
    one thread per core); the one loop left running on a single core was
    this one. Finding each cluster's medoid is otherwise independent
    per-cluster work, so it's farmed out to a thread pool -- plain numpy
    matrix multiplication (inside ``medoid_index``) releases the GIL while it
    runs, so real cores are used, without a process pool's cost of pickling
    the embedding arrays across process boundaries.
    """
    members_by_key = {
        (layer_index, int(cluster_id)): np.flatnonzero(layer == cluster_id)
        for layer_index, layer in enumerate(layers)
        for cluster_id in sorted(set(layer[layer >= 0].tolist()))
    }
    keys = list(members_by_key)

    with ThreadPoolExecutor() as pool:
        medoids = pool.map(
            lambda key: medoid_index(embeddings[members_by_key[key]]), keys
        )

    clusters = {}
    for key, medoid in zip(keys, medoids):
        layer_index, cluster_id = key
        members = members_by_key[key]
        clusters[key] = Cluster(
            layer=layer_index,
            evoc_id=cluster_id,
            label=labels.get(key, ""),
            centroid=embeddings[members].mean(axis=0).tolist(),
            size=len(members),
            exemplar=opinions[members[medoid]],
        )
    Cluster.objects.bulk_create(clusters.values())
    return clusters


def _link_parents(clusters, cluster_tree, n_layers):
    """Wire each cluster to its parent, from EVōC's cluster_tree_.

    Edges into the synthetic root above the coarsest layer are skipped: that
    root has no row (see the module docstring). Two kinds of cluster are
    therefore left with ``parent=None`` -- the top layer's, and any narrower
    cluster the tree hangs directly off the root because it never merges into
    a broader topic. Parents are also not necessarily exactly one layer up.
    """
    updated = []
    for (parent_layer, parent_id), children in cluster_tree.items():
        if parent_layer >= n_layers:
            continue
        parent = clusters.get((parent_layer, int(parent_id)))
        if parent is None:
            continue
        for child_layer, child_id in children:
            child = clusters.get((child_layer, int(child_id)))
            if child is not None:
                child.parent = parent
                updated.append(child)
    Cluster.objects.bulk_update(updated, ["parent"])


def _assign_memberships(layers, clusters, opinions):
    """Attach each opinion to its cluster in every layer where it isn't noise.

    Rows are written straight into the many-to-many's own table in one
    ``bulk_create`` rather than through ``opinion.clusters.add(...)`` per
    opinion, which would be one query each. Clearing it first isn't needed:
    deleting the clusters already cascaded these rows away.
    """
    through = Opinion.clusters.through
    links = []
    for layer_index, layer in enumerate(layers):
        for index, cluster_id in enumerate(layer.tolist()):
            if cluster_id < 0:  # noise in this layer
                continue
            cluster = clusters.get((layer_index, int(cluster_id)))
            if cluster is not None:
                links.append(
                    through(opinion_id=opinions[index].pk, cluster_id=cluster.pk)
                )
    through.objects.bulk_create(links)
