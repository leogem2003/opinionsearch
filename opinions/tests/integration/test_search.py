"""Real embedding, sentiment and clustering checks for the shared search path.

The local conftest.py loads the sample corpus once for this module and
clusters it, so these exercise the real N-closest-cluster search and topic
browse against a real discovered hierarchy. Fast checks (fixed embeddings)
live in ../test_frontend.py.
"""

import json
from pathlib import Path

import pytest
from django.core.cache import cache
from django.urls import reverse

from opinions.models import Opinion
from opinions.sentiment import SENTIMENT_LABELS

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("opinion_samples")]


@pytest.fixture(autouse=True)
def isolated_search_cache():
    # Cached query embeddings must not outlive a test's database transaction.
    cache.clear()


FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "sample_opinions.json"
STATEMENTS = json.loads(FIXTURE_PATH.read_text())["statements"]


@pytest.fixture
def search_url():
    return reverse("opinions:search")


@pytest.mark.django_db
def test_searching_an_opinions_own_text_surfaces_its_own_cluster(client, search_url):
    # Picked by actual layer-0 membership, not a fixed STATEMENTS index --
    # EVōC leaves a real fraction of opinions as noise at the finest layer
    # (see CLAUDE.md), so an arbitrary statement isn't guaranteed to have one.
    own_opinion = Opinion.objects.filter(clusters__layer=0).first()
    assert own_opinion is not None  # sanity: conftest.py clusters everything
    query_text = own_opinion.text
    own_cluster = own_opinion.clusters.get(layer=0)

    # n=20 (the max), not the default 5: real embedding-space neighbours
    # don't always match human topic boundaries closely enough for a
    # statement's own fine-grained cluster to rank #1 against its own exact
    # text (two closely related sub-topics can be nearly equidistant) -- a
    # real EVōC nuance, not a bug. A generous N is what actually matters
    # here: that a real query reliably surfaces its own real cluster at all.
    response = client.get(search_url, {"query": query_text, "n": 20, "topic_level": 0})

    assert response.status_code == 200
    assert response.context["no_matches"] is False
    found_labels = {cluster["label"] for cluster in response.context["clusters_found"]}
    assert own_cluster.label in found_labels
    assert query_text in {row["text"] for row in response.context["results"]}


@pytest.mark.django_db
def test_topic_level_picks_a_broader_or_narrower_cluster(client, search_url):
    query_text = STATEMENTS[3]["text"]

    fine = client.get(search_url, {"query": query_text, "n": 1, "topic_level": 0})
    broad = client.get(search_url, {"query": query_text, "n": 1, "topic_level": 9})

    assert fine.context["topic_level"] == 0
    # Clamped to the deepest layer that actually exists.
    assert broad.context["topic_level"] == broad.context["max_topic_level"]
    assert broad.context["max_topic_level"] > 0
    # A broader layer's cluster covers at least as much of the corpus as a
    # narrower one -- coarser groupings only ever merge members in.
    assert (
        broad.context["clusters_found"][0]["size"]
        >= fine.context["clusters_found"][0]["size"]
    )


@pytest.mark.django_db
def test_results_carry_a_real_scored_sentiment(client, search_url):
    # The fixture is loaded via load_opinions_fixture (see conftest.py),
    # which -- like Opinion.save() -- scores sentiment for every opinion it
    # creates, so every result here should have one.
    query_text = STATEMENTS[3]["text"]

    response = client.get(search_url, {"query": query_text, "n": 3})

    results = response.context["results"]
    assert results  # otherwise the loop below would vacuously pass
    for result in results:
        assert result["sentiment"] in SENTIMENT_LABELS


@pytest.mark.django_db
def test_submitted_coffee_opinion_is_found_with_real_embeddings(client):
    created = client.post(
        "/",
        {"text": "i like coffee", "username": "coffee_fan", "lat": "1", "lon": "2"},
    )
    assert created.status_code == 302
    user_uuid = created.url.rstrip("/").rsplit("/", 1)[-1]
    result = client.get("/topics/", {"q": "coffee"})
    assert result.status_code == 200
    match = next(
        item
        for item in result.context["results"]
        if str(item["author_id"]) == user_uuid
    )
    assert match["text"] == "i like coffee"
    assert match["sentiment"] in SENTIMENT_LABELS
    assert match["sentiment_label"] == SENTIMENT_LABELS[match["sentiment"]]
    assert Opinion.objects.get(author__uuid=user_uuid).embedding is not None


@pytest.mark.django_db
def test_search_handles_anonymous_submitted_opinions(client, search_url):
    original = Opinion.objects.first()
    # Reuses the stored embedding rather than a fresh BGE-M3 call: cheap, and
    # assign_to_nearest_clusters (real code, runs on save) places it via the
    # same nearest-centroid distance original's own text was placed by.
    anonymous = Opinion.objects.create(
        text="Anonymous opinion for the shared search path.",
        author=None,
        embedding=original.embedding,
        sentiment=4,
    )
    response = client.get(search_url, {"query": original.text, "n": 1})
    assert response.status_code == 200
    match = next(
        (row for row in response.context["results"] if row["id"] == anonymous.pk),
        None,
    )
    assert match is not None, "expected the anonymous opinion in original's cluster"
    assert match["author"] is None


@pytest.mark.django_db
def test_browse_reaches_a_real_leaf_topic_from_the_root(client):
    root_response = client.get(reverse("opinions:browse"))
    assert root_response.status_code == 200
    root_options = list(root_response.context["options"])
    assert root_options

    # Walk down through children until reaching a cluster with none --
    # exercises the same drill-down path a visitor clicking through
    # opinions/browse.html would take. The hierarchy is only ever a handful
    # of layers deep, so this bound is generous, not tuned.
    current = root_options[0]
    for _ in range(20):
        response = client.get(reverse("opinions:browse"), {"cluster": current.pk})
        assert response.status_code == 200
        if response.context["options"] is None:
            assert response.context["results"]
            return
        current = list(response.context["options"])[0]
    pytest.fail("never reached a leaf cluster")
