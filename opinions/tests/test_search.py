"""Tests for the /search page.

Written before opinions.views.search / opinions/urls.py / the search
template exist -- they pin down the expected behavior (a max-cosine-distance
search over Opinion.embedding) that the implementation must satisfy.

The dataset backing these tests is loaded once per test session by
opinions/tests/conftest.py, from opinions/tests/fixtures/sample_opinions.json.
Statement index 0 and 2 in that fixture are exact-duplicate text (two
different users posting the same opinion), which is what lets the
distance == 0 test check for more than one matching row.
"""

import json
from pathlib import Path

import pytest
from django.urls import reverse

from opinions.models import Opinion
from opinions.sentiment import SENTIMENT_LABELS

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
