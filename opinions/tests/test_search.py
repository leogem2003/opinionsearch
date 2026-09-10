"""Tests for the /search page.

Written before opinions.views.search / opinions/urls.py / the search
template exist -- they pin down the expected behavior (a max-cosine-distance
search over Opinion.embedding) that the implementation must satisfy.

The dataset backing these tests is loaded once for this module by
opinions/tests/conftest.py, from opinions/tests/fixtures/sample_opinions.json.
Statement index 0 and 2 in that fixture are exact-duplicate text (two
different users posting the same opinion), which is what lets the
distance == 0 test check for more than one matching row.
"""

import json
from pathlib import Path

import pytest
from django.core.cache import cache
from django.urls import reverse

from opinions.models import Opinion
from opinions.sentiment import SENTIMENT_LABELS

pytestmark = pytest.mark.usefixtures("opinion_samples")


@pytest.fixture(autouse=True)
def isolated_search_cache():
    # Cached HTML results must not outlive a test's database transaction.
    cache.clear()


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_opinions.json"
STATEMENTS = json.loads(FIXTURE_PATH.read_text())["statements"]


@pytest.fixture
def search_url():
    return reverse("opinions:search")


@pytest.mark.django_db
def test_search_page_without_a_query_shows_no_results(client, search_url):
    response = client.get(search_url)

    assert response.status_code == 200
    assert response.context["results"] == []


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
def test_search_api_returns_the_same_matches_as_html(client, search_url):
    params = {"query": STATEMENTS[0]["text"], "max_distance": "0"}
    expected = client.get(search_url, params).context["results"]
    response = client.get(reverse("opinion-search-api"), params)

    assert response.status_code == 200
    assert response.json()["limit"] == 50
    api_matches = {item["id"]: item for item in response.json()["results"]}
    assert set(api_matches) == {str(item["id"]) for item in expected}
    for item in expected:
        match = api_matches[str(item["id"])]
        for field in ("text", "topic", "distance", "similarity", "sentiment"):
            assert match[field] == item[field]
        assert match["sentimentLabel"] == item["sentiment_label"]
    assert all(isinstance(item["id"], str) for item in api_matches.values())


@pytest.mark.django_db
def test_search_api_caps_results(client):
    original = Opinion.objects.first()
    Opinion.objects.bulk_create(
        [
            Opinion(
                text=original.text,
                topic=original.topic,
                author=original.author,
                embedding=original.embedding,
            )
            for _ in range(60)
        ]
    )
    response = client.get(
        reverse("opinion-search-api"),
        {"query": original.text, "max_distance": "1"},
    )

    assert response.status_code == 200
    assert len(response.json()["results"]) == 50


@pytest.mark.parametrize("query", ["x" * 2001, "invalid\x00query"])
def test_search_api_rejects_invalid_queries_before_embedding(
    client, query, monkeypatch
):
    def unexpected_embedding(text):
        pytest.fail("Invalid input must not reach the model")

    monkeypatch.setattr("opinions.search.embed_text", unexpected_embedding)
    response = client.get(reverse("opinion-search-api"), {"query": query})
    assert response.status_code == 400
    assert response.json()["error"]["message"]


def test_search_api_empty_query_needs_no_database_or_model(client):
    response = client.get(reverse("opinion-search-api"))
    assert response.status_code == 200
    assert response.json() == {"results": [], "limit": 50}


def test_search_api_is_read_only(client):
    response = client.post(reverse("opinion-search-api"), {"query": "housing"})
    assert response.status_code == 405
    assert response["Allow"] == "GET"


@pytest.mark.django_db
def test_submitted_coffee_opinion_is_found_with_real_embeddings(client):
    created = client.post(
        "/api/v1/contributions/",
        {"text": "i like coffee", "submissionKey": "c" * 64, "publication": "public"},
        content_type="application/json",
    )
    assert created.status_code == 201
    receipt = created.json()
    assert receipt["searchable"] is True
    result = client.get(reverse("opinion-search-api"), {"query": "coffee"})
    assert result.status_code == 200
    match = next(
        item
        for item in result.json()["results"]
        if item["contributionId"] == receipt["id"]
    )
    assert match["text"] == "i like coffee"
    assert match["sentiment"] in SENTIMENT_LABELS
    assert match["sentimentLabel"] == SENTIMENT_LABELS[match["sentiment"]]
    assert Opinion.objects.get(contribution_id=receipt["id"]).embedding is not None


@pytest.mark.django_db
def test_html_search_handles_anonymous_submitted_opinions(client, search_url):
    original = Opinion.objects.first()
    anonymous = Opinion.objects.create(
        text="Anonymous opinion for the shared search path.",
        topic="",
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
