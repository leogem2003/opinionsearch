"""Submission and search contracts against PostgreSQL, using fixed model outputs.

Real model checks live in integration/test_search.py.
"""

import hashlib
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

import pytest
from django.core.cache import cache
from django.db import DatabaseError, connections
from django.test import Client
from django.urls import reverse

from opinions.models import Cluster, Contribution, Opinion
from opinions.pipeline import index_contribution

KEY = "a" * 64
VECTOR = [1.0] + [0.0] * 1023


@pytest.fixture(autouse=True)
def embedding(monkeypatch):
    def unexpected_model():
        pytest.fail(
            "These tests use a fixed embedding; real inference is tested separately"
        )

    monkeypatch.setattr("opinions.embedding.get_embedder", unexpected_model)
    monkeypatch.setattr("opinions.sentiment.get_sentiment_pipeline", unexpected_model)
    monkeypatch.setattr("opinions.pipeline.score_text", Mock(return_value=4))
    monkeypatch.setattr(
        "opinions.topic_classification.classify_topics",
        Mock(return_value=(["housing"], {"method": "test"})),
    )
    embed = Mock(return_value=VECTOR)
    monkeypatch.setattr("opinions.pipeline.embed_text", embed)
    return embed


def submit(client, text="An issue worth understanding.", key=KEY):
    return client.post("/", {"text": text, "submission_key": key})


def receipt_url(response):
    """Extract the ``/contributions/<id>/?receipt=...`` target of a redirect."""
    assert response.status_code == 302
    return response.url


def receipt_params(response):
    parsed = urllib.parse.urlsplit(receipt_url(response))
    return parsed.path, urllib.parse.parse_qs(parsed.query).get("receipt", [None])[0]


@pytest.mark.django_db
def test_submit_creates_and_redirects_to_a_url_carrying_the_receipt(embedding):
    client = Client()
    public_count = Opinion.objects.count()
    text = "  Housing 🏡\nSchöne Wohnungen.  "
    saved = submit(client, text)
    path, token = receipt_params(saved)
    assert len(token) == 43
    source = Contribution.objects.get()
    assert source.text == text.strip()
    assert source.publication == "public"
    assert source.submission_key_hash == hashlib.sha256(KEY.encode()).hexdigest()
    assert path == f"/contributions/{source.id}/"

    page = client.get(path, {"receipt": token})
    assert page.status_code == 200
    assert page.context["contribution"] == source
    assert page.context["searchable"] is True
    assert text.strip() in page.content.decode()
    assert token not in page.content.decode()

    assert Opinion.objects.count() == public_count + 1
    opinion = Opinion.objects.get(contribution=source)
    assert opinion.author is None
    assert not opinion.clusters.exists()
    assert opinion.sentiment == 4
    assert list(opinion.embedding) == VECTOR
    embedding.assert_called_once_with(text.strip())


@pytest.mark.django_db
def test_receipt_denials_render_the_same_unavailable_response(client):
    saved = submit(client)
    path, token = receipt_params(saved)
    other_path, other_token = receipt_params(submit(client, key="b" * 64))

    denials = [
        client.get(path),
        client.get(path, {"receipt": "x" * 43}),
        client.get(path, {"receipt": "non-ascii-é"}),
        client.get(path, {"receipt": other_token}),
        client.get(
            "/contributions/00000000-0000-0000-0000-000000000000/", {"receipt": token}
        ),
        client.get("/contributions/not-a-uuid/", {"receipt": token}),
    ]
    for result in denials:
        assert result.status_code == 404
        assert result.context["contribution"] is None
        assert token not in result.content.decode()


@pytest.mark.django_db
def test_resubmitting_same_key_recovers_the_same_contribution(client, embedding):
    first = submit(client)
    replay = submit(Client())
    assert receipt_params(first) == receipt_params(replay)
    assert Contribution.objects.count() == 1
    assert Opinion.objects.filter(contribution__isnull=False).count() == 1
    embedding.assert_called_once()


@pytest.mark.django_db
def test_key_collision_with_different_text_starts_a_fresh_contribution(client):
    submit(client, text="An issue worth understanding.")
    second = submit(client, text="A different issue.")
    path, _ = receipt_params(second)
    assert Contribution.objects.count() == 2
    second_source = Contribution.objects.get(pk=path.split("/")[2])
    assert second_source.text == "A different issue."


@pytest.mark.django_db(transaction=True)
def test_concurrent_retries_create_one_durable_contribution():
    text = "Same text"
    barrier = Barrier(4)

    def worker():
        try:
            barrier.wait(timeout=10)
            return submit(Client(), text=text)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: worker(), range(4)))

    assert Contribution.objects.count() == 1
    assert Opinion.objects.filter(contribution__isnull=False).count() == 1
    targets = {receipt_url(result) for result in results}
    assert len(targets) == 1


@pytest.mark.parametrize("text", ["", " \n ", "x" * 2001, "bad\0text"])
@pytest.mark.django_db
def test_invalid_text_is_rejected_without_storage(client, text):
    # Unlike the retired JSON endpoint, a plain HTML form can't submit a
    # non-string value or an unpaired UTF-16 surrogate at all -- the browser
    # (and Django's test client, which mirrors form encoding) rejects those
    # before any request is even sent.
    result = client.post("/", {"text": text, "submission_key": KEY})
    assert result.status_code == 400
    assert Contribution.objects.count() == 0


@pytest.mark.django_db
def test_malformed_submission_key_still_succeeds_with_a_generated_key(client):
    result = client.post("/", {"text": "An issue.", "submission_key": "too-short"})
    assert result.status_code == 302
    assert Contribution.objects.count() == 1


@pytest.mark.django_db
def test_2000_unicode_code_points_are_accepted(client):
    text = "🏡" * 2000
    saved = submit(client, text)
    path, token = receipt_params(saved)
    assert client.get(path, {"receipt": token}).context["contribution"].text == text


@pytest.mark.parametrize(
    "path,method",
    [("/", "delete"), ("/", "put"), ("/contributions/example/", "post")],
)
def test_unsupported_methods_are_rejected(client, path, method):
    result = getattr(client, method)(path)
    assert result.status_code == 405


@pytest.mark.django_db
def test_storage_failures_never_acknowledge_a_save(client, monkeypatch):
    def fail(*args, **kwargs):
        raise DatabaseError("Private database details")

    monkeypatch.setattr(Contribution.objects, "get_or_create", fail)
    result = submit(client)
    assert result.status_code == 503
    assert Contribution.objects.count() == 0


@pytest.mark.django_db
def test_index_contribution_rejects_non_public_sources(embedding):
    source = Contribution.objects.create(
        text="An earlier private input.",
        publication="private",
        submission_key_hash="x" * 64,
        access_token="y" * 43,
    )
    with pytest.raises(ValueError, match="Only public"):
        index_contribution(source)
    assert not Opinion.objects.filter(contribution=source).exists()
    embedding.assert_not_called()


@pytest.mark.django_db
def test_embedding_failure_preserves_source_and_retry_completes_indexing(
    client, embedding
):
    text = "A saved source awaiting its embedding."
    embedding.side_effect = RuntimeError("Internal model details")
    failed = submit(client, text=text)
    assert failed.status_code == 503
    assert "Internal model details" not in failed.content.decode()
    source = Contribution.objects.get()
    assert source.text == text
    assert not Opinion.objects.filter(contribution=source).exists()
    page = client.get(f"/contributions/{source.id}/", {"receipt": source.access_token})
    assert page.context["searchable"] is False

    embedding.side_effect = None
    retried = submit(client, text=text)
    assert retried.status_code == 302
    assert Contribution.objects.count() == 1
    assert Opinion.objects.get(contribution=source).text == text
    page = client.get(f"/contributions/{source.id}/", {"receipt": source.access_token})
    assert page.context["searchable"] is True


@pytest.mark.django_db
def test_sentiment_failure_keeps_source_and_retry_completes_it(client, monkeypatch):
    scorer = Mock(side_effect=RuntimeError("Internal sentiment model details"))
    monkeypatch.setattr("opinions.pipeline.score_text", scorer)
    response = submit(client)
    assert response.status_code == 503
    source = Contribution.objects.get()
    assert not Opinion.objects.filter(contribution=source).exists()
    scorer.side_effect = None
    scorer.return_value = 4
    assert submit(client).status_code == 302
    assert Opinion.objects.get(contribution=source).sentiment == 4


@pytest.mark.django_db
def test_topic_failure_preserves_source_and_retry_completes_it(client, monkeypatch):
    classifier = Mock(side_effect=RuntimeError("Internal model details"))
    monkeypatch.setattr("opinions.topic_classification.classify_topics", classifier)
    response = submit(client)
    assert response.status_code == 503
    source = Contribution.objects.get()
    assert not Opinion.objects.filter(contribution=source).exists()
    classifier.side_effect = None
    classifier.return_value = (["housing", "transport"], {"method": "test"})
    assert submit(client).status_code == 302
    opinion = Opinion.objects.get(contribution=source)
    assert opinion.topic_ids == ["housing", "transport"]
    assert submit(client).status_code == 302
    assert Opinion.objects.filter(contribution=source).count() == 1
    assert classifier.call_count == 2


@pytest.mark.django_db
def test_search_returns_indexed_input_with_source_id_but_no_credentials(
    client, monkeypatch
):
    text = "A contribution to public opinion search."
    saved = submit(client, text)
    _, token = receipt_params(saved)
    source = Contribution.objects.get()
    monkeypatch.setattr("opinions.search.embed_text", lambda _: VECTOR)
    result = client.get("/topics/", {"q": text})
    assert result.status_code == 200
    match = next(
        item
        for item in result.context["results"]
        if item["contribution_id"] == source.id
    )
    assert match["text"] == text
    assert set(match) == {
        "id",
        "contribution_id",
        "text",
        "distance",
        "similarity",
        "sentiment",
        "sentiment_label",
        "sentiment_group",
        "sentiment_group_label",
        "topics",
        "topic_analysis",
    }
    assert token not in result.content.decode()


@pytest.mark.django_db
def test_search_page_without_a_query_shows_no_results(client):
    response = client.get(reverse("opinions:search"))
    assert response.status_code == 200
    assert response.context["results"] == []


@pytest.mark.django_db
def test_topics_browse_caps_results_at_fifty(client, monkeypatch):
    text = "An opinion about housing."
    Opinion.objects.bulk_create(
        [Opinion(text=text, embedding=VECTOR) for _ in range(60)]
    )
    monkeypatch.setattr("opinions.search.embed_text", lambda _: VECTOR)
    response = client.get("/topics/", {"q": text})
    assert response.status_code == 200
    assert len(response.context["results"]) == 50


@pytest.mark.parametrize("query", ["x" * 2001, "invalid\x00query"])
def test_topics_browse_rejects_invalid_queries_before_embedding(
    client, query, monkeypatch
):
    def unexpected_embedding(text):
        pytest.fail("Invalid input must not reach the model")

    monkeypatch.setattr("opinions.search.embed_text", unexpected_embedding)
    response = client.get("/topics/", {"q": query})
    assert response.status_code == 400


@pytest.mark.django_db
def test_topics_browse_idle_shows_directory_without_embedding_a_query(
    client, monkeypatch
):
    monkeypatch.setattr(
        "opinions.search.embed_text",
        Mock(side_effect=AssertionError("Idle browsing must not embed a query")),
    )
    response = client.get("/topics/")
    assert response.status_code == 200
    assert response.context["results"] is None
    assert response.context["directory"]


@pytest.mark.django_db
@pytest.mark.parametrize("clustered", [False, True])
def test_anonymous_input_keeps_categories_and_source_when_clusters_are_added(
    client, monkeypatch, clustered
):
    Opinion.objects.all().delete()
    Cluster.objects.all().delete()
    cache.clear()
    monkeypatch.setattr("opinions.search.embed_text", Mock(return_value=VECTOR))
    monkeypatch.setattr("opinions.search.score_text", Mock(return_value=4))
    saved = submit(client)
    source = Contribution.objects.get()
    opinion = Opinion.objects.get(contribution=source)
    if clustered:
        cluster = Cluster.objects.create(
            layer=0,
            evoc_id=0,
            label="rent, tenants",
            centroid=VECTOR,
            size=1,
            exemplar=opinion,
        )
        opinion.clusters.add(cluster)

    html = client.get("/search/", {"query": opinion.text})
    assert html.status_code == 200
    row = html.context["results"][0]
    assert row["author"] is None
    assert row["topic"] == ("rent, tenants" if clustered else "unclustered")
    assert row["topics"] == (
        [{"layer": 0, "label": "rent, tenants"}] if clustered else []
    )
    result = client.get("/topics/", {"topic": "housing"}).context["results"][0]
    assert result["topics"] == [{"id": "housing", "title": "Housing"}]
    assert result["contribution_id"] == source.id
    assert result["text"] == opinion.text
    _, token = receipt_params(saved)
    assert (
        client.get(f"/contributions/{source.id}/", {"receipt": token}).status_code
        == 200
    )
    cache.clear()
