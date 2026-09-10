"""Tests for the discovered topic hierarchy (opinions/clustering.py).

The hierarchy under test is the one built once per session by conftest.py,
over opinions/tests/fixtures/sample_opinions.json -- these tests read it
rather than re-clustering, since a run costs real EVōC time.

Clustering is unsupervised, so these assert *structure* (layers exist, parents
link them, every membership is one-per-layer) rather than specific clusters,
plus one deliberately loose check that the discovered clusters resemble the
themes the fixture was actually written around.
"""

import collections
import json
from pathlib import Path

import pytest

from opinions.clustering import assign_to_nearest_clusters, layer_count
from opinions.models import Cluster, Opinion

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_opinions.json"
STATEMENTS = json.loads(FIXTURE_PATH.read_text())["statements"]


@pytest.mark.django_db
def test_clustering_produces_a_hierarchy_of_layers():
    n_layers = layer_count()
    assert n_layers >= 2, "expected more than one resolution of topics"

    for layer in range(n_layers):
        assert Cluster.objects.filter(layer=layer).exists()

    # Coarser layers group the finer ones, so they can't have more clusters.
    sizes = [Cluster.objects.filter(layer=layer).count() for layer in range(n_layers)]
    assert sizes == sorted(sizes, reverse=True), sizes


@pytest.mark.django_db
def test_parents_always_point_at_a_coarser_layer():
    top_layer = layer_count() - 1

    for cluster in Cluster.objects.select_related("parent"):
        if cluster.parent is not None:
            assert cluster.parent.layer > cluster.layer, f"{cluster} has a finer parent"

    # EVōC's synthetic root above the coarsest layer is deliberately not
    # stored (see clustering.py), so the top layer's clusters have no parent.
    for cluster in Cluster.objects.filter(layer=top_layer):
        assert cluster.parent is None

    # ...but the layers below it must actually be joined up, or there is no
    # hierarchy to speak of.
    for layer in range(top_layer):
        assert Cluster.objects.filter(layer=layer, parent__isnull=False).exists()


@pytest.mark.django_db
def test_a_cluster_may_attach_straight_to_the_root_instead_of_a_broader_topic():
    """Some fine clusters never merge upwards, and that is not a bug.

    EVōC's cluster_tree_ hangs those off its synthetic root rather than off a
    coarser cluster -- measured on this corpus, not hypothetical -- so they
    are stored with no parent even though they are not in the top layer.
    Asserting the opposite (every non-top cluster has a parent) is what an
    earlier version of this test got wrong.
    """
    top_layer = layer_count() - 1
    unparented = Cluster.objects.filter(parent__isnull=True).exclude(layer=top_layer)

    for cluster in unparented:
        # It is a topic in its own right: it still has members, and nothing
        # coarser claims them.
        assert cluster.size > 0
        assert not cluster.children.exists() or cluster.layer > 0


@pytest.mark.django_db
def test_clusters_carry_a_label_a_size_and_an_exemplar():
    for cluster in Cluster.objects.all():
        assert cluster.label, f"{cluster} has no label"
        assert cluster.size == cluster.opinions.count()
        assert cluster.exemplar is not None
        assert cluster.exemplar in cluster.opinions.all()


@pytest.mark.django_db
def test_an_opinion_belongs_to_at_most_one_cluster_per_layer():
    for opinion in Opinion.objects.prefetch_related("clusters"):
        layers = [cluster.layer for cluster in opinion.clusters.all()]
        assert len(layers) == len(set(layers)), f"{opinion} is in two clusters at once"


@pytest.mark.django_db
def test_most_opinions_are_assigned_at_the_broadest_layer():
    # EVōC labels every layer independently and calls some points noise; the
    # broadest layer should still cover most of the corpus, or the hierarchy
    # is not describing the corpus at all.
    top_layer = layer_count() - 1
    total = Opinion.objects.count()
    assigned = Opinion.objects.filter(clusters__layer=top_layer).distinct().count()

    assert assigned > total / 2, f"only {assigned}/{total} opinions got a broad topic"


@pytest.mark.django_db
def test_finest_clusters_broadly_line_up_with_the_fixture_themes():
    """A loose sanity check against the fixture's hand-written themes.

    The themes are ground truth the clustering never sees (they aren't stored
    -- see opinions/tests/utils.py). Perfect agreement isn't the point and
    would make this test a tripwire for harmless parameter changes; the
    threshold only catches clustering that has stopped tracking the corpus's
    actual subject matter.
    """
    theme_by_text = {s["text"]: s["topic"] for s in STATEMENTS}

    members_by_cluster = collections.defaultdict(list)
    for opinion in Opinion.objects.filter(clusters__layer=0).prefetch_related(
        "clusters"
    ):
        cluster = opinion.cluster_at(0)
        members_by_cluster[cluster.pk].append(theme_by_text[opinion.text])

    assert members_by_cluster, "no opinions were clustered at the finest layer"

    in_majority_theme = sum(
        collections.Counter(themes).most_common(1)[0][1]
        for themes in members_by_cluster.values()
    )
    clustered = sum(len(themes) for themes in members_by_cluster.values())

    assert in_majority_theme / clustered > 0.6, (
        f"only {in_majority_theme}/{clustered} clustered opinions share their "
        "cluster's majority theme"
    )


@pytest.mark.django_db
def test_publishing_an_opinion_assigns_it_without_a_recluster():
    """Opinion.save() calls assign_to_nearest_clusters (see models.py), so a
    freshly published opinion gets a topic immediately rather than waiting
    for the next `manage.py recluster`.

    Republishing an already-clustered statement verbatim, rather than some
    new text, sidesteps guessing at the assignment threshold: BGE-M3 is
    deterministic, so the new row's embedding -- and its distance to that
    statement's own cluster centroid -- is (numerically) identical to the
    original's, which is certain to be well inside it.
    """
    source_text = STATEMENTS[3]["text"]
    source = Opinion.objects.filter(text=source_text, clusters__isnull=False).first()
    assert source is not None, "fixture sanity: expected this statement to be clustered"
    layer = source.clusters.first().layer
    cluster = source.cluster_at(layer)

    clusters_before = Cluster.objects.count()
    size_before = cluster.size

    republished = Opinion.objects.create(text=source_text, author=source.author)

    # No re-clustering happened -- same clusters, just one more member.
    assert Cluster.objects.count() == clusters_before
    assert republished.cluster_at(layer) == cluster
    cluster.refresh_from_db()
    assert cluster.size == size_before + 1


@pytest.mark.django_db
def test_assign_to_nearest_clusters_is_a_noop_without_a_hierarchy():
    Cluster.objects.all().delete()
    opinion = Opinion.objects.filter(embedding__isnull=False).first()

    assert assign_to_nearest_clusters(opinion) == []


def test_assign_to_nearest_clusters_is_a_noop_without_an_embedding():
    # No @pytest.mark.django_db: an unsaved instance is never written, and
    # assign_to_nearest_clusters must return before it would need to be.
    unsaved = Opinion(text="not yet embedded")

    assert assign_to_nearest_clusters(unsaved) == []
