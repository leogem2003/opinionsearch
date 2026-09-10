"""Real embedding, sentiment and clustering checks for the shared search path.

The local conftest.py loads the sample corpus once for this module.
Statements 0 and 2 duplicate the same text under different authors, so the
distance-zero check must return both rows. Fast checks live in ../test_frontend.py.
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
    # Cached HTML results must not outlive a test's database transaction.
    cache.clear()


FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "sample_opinions.json"
STATEMENTS = json.loads(FIXTURE_PATH.read_text())["statements"]


@pytest.fixture
def search_url():
    return reverse("opinions:search")


@pytest.mark.django_db
def test_zero_max_distance_returns_only_identical_statements(client, search_url):
    duplicated_text = STATEMENTS[0]["text"]
    assert STATEMENTS[2]["text"] == duplicated_text  # fixture sanity check

    response = client.get(search_url, {"query": duplicated_text, "max_distance": "0"})

    assert response.status_code == 200
    results = response.context["results"]

    expected_count = Opinion.objects.filter(text=duplicated_text).count()
    assert expected_count >= 2
    assert len(results) == expected_count
    assert {result["text"] for result in results} == {duplicated_text}
    for result in results:
        assert result["distance"] == pytest.approx(0.0, abs=1e-4)


@pytest.mark.django_db
def test_max_distance_one_returns_every_statement(client, search_url):
    query_text = STATEMENTS[1]["text"]

    response = client.get(search_url, {"query": query_text, "max_distance": "1"})

    assert response.status_code == 200
    results = response.context["results"]

    assert len(results) == Opinion.objects.count()
    assert {result["text"] for result in results} == {
        statement["text"] for statement in STATEMENTS
    }


@pytest.mark.django_db
def test_results_are_sorted_by_ascending_distance(client, search_url):
    query_text = STATEMENTS[3]["text"]

    response = client.get(search_url, {"query": query_text, "max_distance": "1"})

    distances = [result["distance"] for result in response.context["results"]]
    assert distances == sorted(distances)


@pytest.mark.django_db
def test_results_carry_a_discovered_topic_at_the_requested_level(client, search_url):
    # Discovered topics come from the
    # hierarchy conftest.py clusters into existence (opinions/clustering.py),
    # and the topic_level slider picks which layer of it the page shows.
    query_text = STATEMENTS[3]["text"]

    fine = client.get(
        search_url, {"query": query_text, "max_distance": "1", "topic_level": "0"}
    )
    broad = client.get(
        search_url, {"query": query_text, "max_distance": "1", "topic_level": "9"}
    )

    assert fine.context["topic_level"] == 0
    # Clamped to the deepest layer that actually exists.
    assert broad.context["topic_level"] == broad.context["max_topic_level"]
    assert broad.context["max_topic_level"] > 0

    for result in fine.context["results"]:
        assert result["topic"]
        assert isinstance(result["topics"], list)

    fine_topics = {result["topic"] for result in fine.context["results"]}
    broad_topics = {result["topic"] for result in broad.context["results"]}
    assert len(broad_topics) < len(fine_topics), (fine_topics, broad_topics)


@pytest.mark.django_db
def test_results_carry_a_scored_sentiment_and_matching_label(client, search_url):
    # The fixture is loaded via load_opinions_fixture (see conftest.py),
    # which -- like Opinion.save() -- scores sentiment for every opinion it
    # creates, so every result here should have one.
    query_text = STATEMENTS[3]["text"]

    response = client.get(search_url, {"query": query_text, "max_distance": "1"})

    results = response.context["results"]
    assert results  # otherwise the loop below would vacuously pass
    for result in results:
        assert result["sentiment"] in SENTIMENT_LABELS
        assert result["sentiment_label"] == SENTIMENT_LABELS[result["sentiment"]]


@pytest.mark.django_db
def test_submitted_coffee_opinion_is_found_with_real_embeddings(client):
    created = client.post("/", {"text": "i like coffee", "submission_key": "c" * 64})
    assert created.status_code == 302
    contribution_id = created.url.split("/")[2]
    result = client.get("/topics/", {"q": "coffee"})
    assert result.status_code == 200
    match = next(
        item
        for item in result.context["results"]
        if str(item["contribution_id"]) == contribution_id
    )
    assert match["text"] == "i like coffee"
    assert match["sentiment"] in SENTIMENT_LABELS
    assert match["sentiment_label"] == SENTIMENT_LABELS[match["sentiment"]]
    assert Opinion.objects.get(contribution_id=contribution_id).embedding is not None


@pytest.mark.django_db
def test_html_search_handles_anonymous_submitted_opinions(client, search_url):
    original = Opinion.objects.first()
    anonymous = Opinion.objects.create(
        text="Anonymous opinion for the shared search path.",
        author=None,
        embedding=original.embedding,
        sentiment=4,
    )
    response = client.get(search_url, {"query": original.text, "max_distance": "0"})
    assert response.status_code == 200
    match = next(
        item for item in response.context["results"] if item["id"] == anonymous.pk
    )
    assert match["author"] is None
