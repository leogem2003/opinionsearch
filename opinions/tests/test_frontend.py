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
from django.utils.html import escape

from opinions.models import Cluster, Contribution, Opinion, User
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
    text = "\n  Housing 🏡\nSchöne Wohnungen.  \n"
    saved = submit(client, text)
    path, token = receipt_params(saved)
    assert len(token) == 43
    source = Contribution.objects.get()
    assert source.text == text
    assert source.publication == "public"
    assert source.submission_key_hash == hashlib.sha256(KEY.encode()).hexdigest()
    assert path == f"/contributions/{source.id}/"

    page = client.get(path, {"receipt": token})
    assert page.status_code == 200
    assert page.context["contribution"] == source
    assert page.context["searchable"] is True
    assert text in page.content.decode()
    assert token not in page.content.decode()

    assert Opinion.objects.count() == public_count + 1
    opinion = Opinion.objects.get(contribution=source)
    assert opinion.text == text
    assert opinion.author is None
    assert not opinion.clusters.exists()
    assert opinion.sentiment == 4
    assert list(opinion.embedding) == VECTOR
    embedding.assert_called_once_with(text)


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


@pytest.mark.django_db
def test_edited_failed_submission_reuses_its_source_and_effective_key(
    client, embedding
):
    embedding.side_effect = RuntimeError("Model unavailable")
    assert submit(client, text="Original draft").status_code == 503
    text = "\n  Edited <draft>.  \n"
    failed = submit(client, text=text)
    key = failed.context["submission_key"]
    assert failed.status_code == 503
    assert key != KEY
    assert f">\n{escape(text)}</textarea>" in failed.content.decode()
    source = Contribution.objects.get(text=text)
    assert b"Your original text is saved" in failed.content

    assert submit(client, text=text, key=key).status_code == 503
    # Replaying the preceding request must also recover the same source.
    assert submit(client, text=text, key=KEY).status_code == 503
    assert Contribution.objects.count() == 2

    embedding.side_effect = None
    saved = submit(client, text=text, key=key)
    assert receipt_params(saved)[0] == f"/contributions/{source.id}/"
    assert Opinion.objects.get(contribution=source).text == text
    assert Contribution.objects.count() == 2


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


@pytest.mark.parametrize(
    "text", ["", " \n ", "x" * 2001, " " + "x" * 2000, "bad\0text"]
)
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
        "author",
        "distance",
        "similarity",
        "sentiment",
        "sentiment_label",
        "sentiment_group",
        "sentiment_group_label",
        "topics",
        "topic_analysis",
    }
    assert match["author"] is None
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
def test_search_failure_preserves_query_and_shows_a_readable_error(client, monkeypatch):
    monkeypatch.setattr(
        "opinions.search.embed_text",
        Mock(side_effect=RuntimeError("Internal model details")),
    )
    response = client.get("/topics/", {"q": "Housing"})
    assert response.status_code == 503
    assert response.context["query"] == "Housing"
    assert b"Search is unavailable" in response.content
    assert b"Internal model details" not in response.content


@pytest.mark.django_db
def test_storage_failure_keeps_forms_and_topic_errors_readable(client, monkeypatch):
    failure = Mock(side_effect=DatabaseError("Internal storage details"))
    monkeypatch.setattr(Opinion.objects, "aggregate", failure)
    monkeypatch.setattr(Contribution.objects, "get_or_create", failure)
    home = client.get("/")
    assert home.context["directory_error"]
    assert b"No opinions yet" not in home.content
    failed = submit(client, text="Keep my draft.")
    assert failed.status_code == 503
    assert failed.context["text"] == "Keep my draft."
    for path in ("/topics/", "/topics/housing/"):
        response = client.get(path)
        assert response.status_code == 503
        assert b"could not be loaded" in response.content
        assert b"Internal storage details" not in response.content


def test_startup_prepares_models_before_serving_and_stops_on_failure(monkeypatch):
    from docker.app import serve

    calls = []
    monkeypatch.setattr(serve.django, "setup", Mock())
    monkeypatch.setattr(
        "opinions.embedding.embed_text",
        lambda text: calls.append("embedding") or VECTOR,
    )
    scorer = Mock(side_effect=lambda text: calls.append("sentiment"))
    monkeypatch.setattr("opinions.sentiment.score_text", scorer)
    monkeypatch.setattr(
        "opinions.topic_classification.classify_topics",
        lambda text, embedding: calls.append("topics"),
    )
    server = Mock(side_effect=lambda *args, **kwargs: calls.append("serve"))
    monkeypatch.setattr(serve, "call_command", server)
    serve.main()
    assert calls == ["embedding", "sentiment", "topics", "serve"]
    server.assert_called_once_with("runserver", "0.0.0.0:8000", use_reloader=False)

    server.reset_mock()
    calls.clear()
    scorer.side_effect = RuntimeError("Model unavailable")
    with pytest.raises(RuntimeError, match="Model unavailable"):
        serve.main()
    assert calls == ["embedding"]
    server.assert_not_called()


@pytest.mark.django_db
def test_opinion_rows_show_the_publishing_users_username_or_anonymous(client):
    author = User.objects.create(username="alex")
    authored = Opinion.objects.create(
        text="Housing needs more supply.",
        embedding=VECTOR,
        sentiment=4,
        author=author,
        topic_ids=["housing"],
    )
    anonymous = Opinion.objects.create(
        text="An anonymous take on housing.",
        embedding=VECTOR,
        sentiment=3,
        topic_ids=["housing"],
    )

    browse_rows = {
        row["id"]: row["author"]
        for row in client.get("/topics/", {"topic": "housing"}).context["results"]
    }
    assert browse_rows[authored.pk] == "alex"
    assert browse_rows[anonymous.pk] is None

    detail_rows = {
        row["id"]: row["author"]
        for row in client.get("/topics/housing/").context["results"]
    }
    assert detail_rows[authored.pk] == "alex"
    assert detail_rows[anonymous.pk] is None


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
    if clustered:
        row = html.context["results"][0]
        assert row["author"] is None
        assert row["text"] == opinion.text
        assert html.context["clusters_found"][0]["label"] == "rent, tenants"
    else:
        # No discovered hierarchy yet -- nothing to match a cluster against.
        assert html.context["results"] == []
        assert html.context["no_matches"] is True

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


VECTOR2 = [0.0, 1.0] + [0.0] * 1022


def _clear_corpus():
    # --reuse-db can leave rows from an earlier integration run in this test
    # database (see CLAUDE.md's gotchas); the tests below create clusters at
    # specific (layer, evoc_id) pairs, which collide with any leftovers.
    Opinion.objects.all().delete()
    Cluster.objects.all().delete()


@pytest.mark.django_db
def test_closest_clusters_orders_by_centroid_distance():
    from opinions.views import _closest_clusters

    _clear_corpus()
    near = Cluster.objects.create(
        layer=0, evoc_id=0, label="near", centroid=VECTOR, size=1
    )
    Cluster.objects.create(layer=0, evoc_id=1, label="far", centroid=VECTOR2, size=1)

    assert _closest_clusters(VECTOR, layer=0, n=1) == [near]
    assert [c.label for c in _closest_clusters(VECTOR, layer=0, n=2)] == [
        "near",
        "far",
    ]


@pytest.mark.django_db
def test_search_finds_opinions_via_the_closest_cluster(client, monkeypatch):
    cache.clear()
    _clear_corpus()
    monkeypatch.setattr("opinions.search.embed_text", Mock(return_value=VECTOR))
    monkeypatch.setattr("opinions.search.score_text", Mock(return_value=4))
    opinion = Opinion.objects.create(
        text="Housing needs more supply.", embedding=VECTOR, sentiment=4
    )
    cluster = Cluster.objects.create(
        layer=0, evoc_id=0, label="housing", centroid=VECTOR, size=1, exemplar=opinion
    )
    opinion.clusters.add(cluster)

    response = client.get("/search/", {"query": "affordable housing", "n": 1})
    assert response.status_code == 200
    assert response.context["clusters_found"] == [{"label": "housing", "size": 1}]
    assert [row["id"] for row in response.context["results"]] == [opinion.pk]
    assert response.context["no_matches"] is False
    assert response.context["weak_match"] is False
    cache.clear()


@pytest.mark.django_db
def test_search_level_tabs_switch_which_layer_is_matched(client, monkeypatch):
    cache.clear()
    _clear_corpus()
    monkeypatch.setattr("opinions.search.embed_text", Mock(return_value=VECTOR))
    monkeypatch.setattr("opinions.search.score_text", Mock(return_value=3))
    fine_opinion = Opinion.objects.create(
        text="A narrow topic opinion.", embedding=VECTOR, sentiment=3
    )
    broad_opinion = Opinion.objects.create(
        text="A broad topic opinion.", embedding=VECTOR, sentiment=3
    )
    broad_cluster = Cluster.objects.create(
        layer=1, evoc_id=0, label="broad", centroid=VECTOR, size=1
    )
    fine_cluster = Cluster.objects.create(
        layer=0, evoc_id=0, label="fine", centroid=VECTOR, size=1, parent=broad_cluster
    )
    fine_opinion.clusters.add(fine_cluster)
    broad_opinion.clusters.add(broad_cluster)

    at_layer0 = client.get("/search/", {"query": "topic", "n": 1, "topic_level": 0})
    assert [row["id"] for row in at_layer0.context["results"]] == [fine_opinion.pk]
    assert at_layer0.context["max_topic_level"] == 1

    at_layer1 = client.get("/search/", {"query": "topic", "n": 1, "topic_level": 1})
    assert [row["id"] for row in at_layer1.context["results"]] == [broad_opinion.pk]
    cache.clear()


@pytest.mark.django_db
def test_search_flags_a_weak_match_when_the_closest_cluster_is_far(client, monkeypatch):
    cache.clear()
    _clear_corpus()
    monkeypatch.setattr("opinions.search.embed_text", Mock(return_value=VECTOR))
    monkeypatch.setattr("opinions.search.score_text", Mock(return_value=3))
    opinion = Opinion.objects.create(
        text="Unrelated opinion.", embedding=VECTOR2, sentiment=3
    )
    cluster = Cluster.objects.create(
        layer=0, evoc_id=0, label="far", centroid=VECTOR2, size=1
    )
    opinion.clusters.add(cluster)

    response = client.get("/search/", {"query": "something else entirely", "n": 1})
    assert response.status_code == 200
    assert response.context["no_matches"] is False
    assert response.context["weak_match"] is True
    cache.clear()


@pytest.mark.django_db
def test_browse_root_lists_only_parentless_clusters(client):
    _clear_corpus()
    top = Cluster.objects.create(
        layer=1, evoc_id=0, label="top", centroid=VECTOR, size=2
    )
    Cluster.objects.create(
        layer=0, evoc_id=0, label="child", centroid=VECTOR, size=1, parent=top
    )
    # Never merged upward -- parent=None even though it isn't the top layer.
    orphan = Cluster.objects.create(
        layer=0, evoc_id=1, label="orphan", centroid=VECTOR2, size=1
    )

    response = client.get("/search/browse/")
    assert response.status_code == 200
    ids = {cluster.pk for cluster in response.context["options"]}
    assert ids == {top.pk, orphan.pk}


@pytest.mark.django_db
def test_browse_shows_children_then_the_shared_results_at_a_leaf(client):
    _clear_corpus()
    opinion = Opinion.objects.create(
        text="A leaf opinion.", embedding=VECTOR, sentiment=3
    )
    top = Cluster.objects.create(
        layer=1, evoc_id=0, label="top", centroid=VECTOR, size=1
    )
    leaf = Cluster.objects.create(
        layer=0, evoc_id=0, label="leaf", centroid=VECTOR, size=1, parent=top
    )
    opinion.clusters.add(leaf)

    at_top = client.get("/search/browse/", {"cluster": top.pk})
    assert at_top.status_code == 200
    assert list(at_top.context["options"]) == [leaf]
    assert at_top.context["breadcrumbs"] == []

    at_leaf = client.get("/search/browse/", {"cluster": leaf.pk})
    assert at_leaf.status_code == 200
    assert at_leaf.context["options"] is None
    assert [row["id"] for row in at_leaf.context["results"]] == [opinion.pk]
    assert [ancestor.pk for ancestor in at_leaf.context["breadcrumbs"]] == [top.pk]


@pytest.mark.django_db
def test_browse_unknown_cluster_404s(client):
    assert client.get("/search/browse/", {"cluster": 999999}).status_code == 404
    cache.clear()


@pytest.mark.django_db
def test_search_date_range_filters_results_and_carries_coordinates(client, monkeypatch):
    from datetime import datetime, timezone

    from django.contrib.gis.geos import Point

    cache.clear()
    # --reuse-db can leave rows from an earlier integration run in this test
    # database (see CLAUDE.md's gotchas); clear them so (layer=0, evoc_id=0)
    # below is free to create.
    Opinion.objects.all().delete()
    Cluster.objects.all().delete()
    monkeypatch.setattr("opinions.search.embed_text", Mock(return_value=VECTOR))
    monkeypatch.setattr("opinions.search.score_text", Mock(return_value=3))
    cluster = Cluster.objects.create(
        layer=0, evoc_id=0, label="dated", centroid=VECTOR, size=2
    )
    in_range = Opinion.objects.create(
        text="Published in range.",
        embedding=VECTOR,
        sentiment=3,
        geo_coordinates=Point(-122.4194, 37.7749),
    )
    out_of_range = Opinion.objects.create(
        text="Published out of range.", embedding=VECTOR, sentiment=3
    )
    Opinion.objects.filter(pk=in_range.pk).update(
        timestamp=datetime(2025, 6, 15, tzinfo=timezone.utc)
    )
    Opinion.objects.filter(pk=out_of_range.pk).update(
        timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc)
    )
    in_range.clusters.add(cluster)
    out_of_range.clusters.add(cluster)

    response = client.get(
        "/search/",
        {
            "query": "anything",
            "n": 1,
            "date_from": "2025-01-01",
            "date_to": "2025-12-31",
        },
    )
    assert response.status_code == 200
    assert [row["id"] for row in response.context["results"]] == [in_range.pk]
    cache.clear()


@pytest.mark.django_db
def test_add_fictional_geo_time_is_reproducible_for_a_given_seed(monkeypatch):
    from datetime import datetime, timezone as dt_timezone

    from django.core.management import call_command

    # The command anchors its date range to "now" (so re-running it later
    # still gives *recent* dates, not ones frozen at first use) -- freezing
    # it here isolates the part that's actually meant to be reproducible:
    # the seeded choice of city and offset into that range, not wall-clock
    # time elapsed between two command invocations.
    monkeypatch.setattr(
        "opinions.management.commands.add_fictional_geo_time.timezone.now",
        lambda: datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
    )
    first = Opinion.objects.create(text="A", embedding=VECTOR, sentiment=3)
    second = Opinion.objects.create(text="B", embedding=VECTOR, sentiment=3)

    call_command("add_fictional_geo_time", seed=7)
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.geo_coordinates is not None
    assert first.timestamp is not None
    first_run = (first.geo_coordinates.coords, first.timestamp, second.timestamp)

    call_command("add_fictional_geo_time", seed=7)
    first.refresh_from_db()
    second.refresh_from_db()
    assert (
        first.geo_coordinates.coords,
        first.timestamp,
        second.timestamp,
    ) == first_run
