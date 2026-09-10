"""Submission, identity-cookie, editing and search contracts against PostgreSQL,
using fixed model outputs.

Real model checks live in integration/test_search.py.
"""

from unittest.mock import Mock

import pytest
from django.core.cache import cache
from django.db import DatabaseError
from django.test import Client
from django.urls import reverse
from django.utils.html import escape

from opinions.models import Argument, Cluster, Opinion, User

VECTOR = [1.0] + [0.0] * 1023


@pytest.fixture(autouse=True)
def embedding(monkeypatch):
    """Fixed embedding/sentiment/predefined-topic outputs, wired into both
    places that call the real models: Opinion.save() (the create path, used
    by submission) imports embed_text/score_text directly into
    opinions.models's namespace and re-imports classify_topics fresh from
    opinions.topic_classification on every call; opinions.pipeline's
    reanalyze_opinion (the edit path) imports its own copies of all three at
    module load time, so it needs patching at opinions.pipeline instead.
    """

    def unexpected_model():
        pytest.fail(
            "These tests use a fixed embedding; real inference is tested separately"
        )

    monkeypatch.setattr("opinions.embedding.get_embedder", unexpected_model)
    monkeypatch.setattr("opinions.sentiment.get_sentiment_pipeline", unexpected_model)

    embed = Mock(return_value=VECTOR)
    score = Mock(return_value=4)
    classify = Mock(return_value=(["housing"], {"method": "test"}))

    monkeypatch.setattr("opinions.models.embed_text", embed)
    monkeypatch.setattr("opinions.models.score_text", score)
    monkeypatch.setattr("opinions.topic_classification.classify_topics", classify)
    monkeypatch.setattr("opinions.pipeline.embed_text", embed)
    monkeypatch.setattr("opinions.pipeline.score_text", score)
    monkeypatch.setattr("opinions.pipeline.classify_topics", classify)
    return embed


def submit(
    client, text="An issue worth understanding.", username="alice", lat=40.0, lon=-74.0
):
    """POST an opinion, supplying identity fields only if this client hasn't
    already identified itself (mirrors home.html only asking once).
    """
    data = {"text": text}
    if "hivemind_user" not in client.cookies:
        data["username"] = username
        data["lat"] = lat
        data["lon"] = lon
    return client.post("/", data)


@pytest.mark.django_db
def test_submit_creates_a_user_and_redirects_to_their_opinions_page(embedding):
    client = Client()
    text = "\n  Housing 🏡\nSchöne Wohnungen.  \n"
    saved = submit(client, text, username="alice", lat=40.7128, lon=-74.006)
    assert saved.status_code == 302

    user = User.objects.get(username="alice")
    assert saved.url == f"/users/{user.uuid}/"
    assert user.home_location.coords == (-74.006, 40.7128)
    assert "hivemind_user" in client.cookies

    opinion = Opinion.objects.get(author=user)
    assert opinion.text == text
    assert opinion.geo_coordinates.coords == (-74.006, 40.7128)
    assert not opinion.clusters.exists()
    assert opinion.sentiment == 4
    assert list(opinion.embedding) == VECTOR
    embedding.assert_called_once_with(text)


@pytest.mark.django_db
def test_second_submission_from_the_same_browser_reuses_the_identity(embedding):
    client = Client()
    first = submit(client, "First opinion.", username="alice", lat=1.0, lon=2.0)
    user = User.objects.get(username="alice")
    assert first.url == f"/users/{user.uuid}/"

    second = submit(client, "Second opinion, no identity fields resent.")
    assert second.status_code == 302
    assert second.url == f"/users/{user.uuid}/"
    assert User.objects.count() == 1

    opinions = Opinion.objects.filter(author=user).order_by("pk")
    assert [o.text for o in opinions] == [
        "First opinion.",
        "Second opinion, no identity fields resent.",
    ]
    assert opinions[1].geo_coordinates.coords == opinions[0].geo_coordinates.coords


@pytest.mark.django_db
def test_first_submission_without_identity_fields_is_rejected(client):
    result = client.post("/", {"text": "An issue."})
    assert result.status_code == 400
    assert User.objects.count() == 0
    assert Opinion.objects.count() == 0


@pytest.mark.django_db
def test_first_submission_with_a_taken_username_is_rejected(client):
    User.objects.create(username="alice")
    result = client.post(
        "/", {"text": "An issue.", "username": "alice", "lat": "1", "lon": "2"}
    )
    assert result.status_code == 400
    assert b"already taken" in result.content
    assert User.objects.count() == 1
    assert Opinion.objects.count() == 0


@pytest.mark.parametrize(
    "text", ["", " \n ", "x" * 2001, " " + "x" * 2000, "bad\0text"]
)
@pytest.mark.django_db
def test_invalid_text_is_rejected_without_storage(client, text):
    result = client.post(
        "/", {"text": text, "username": "alice", "lat": "1", "lon": "2"}
    )
    assert result.status_code == 400
    assert User.objects.count() == 0
    assert Opinion.objects.count() == 0


@pytest.mark.django_db
def test_2000_unicode_code_points_are_accepted(client):
    text = "🏡" * 2000
    saved = submit(client, text)
    assert saved.status_code == 302
    assert Opinion.objects.get().text == text


@pytest.mark.parametrize("path,method", [("/", "delete"), ("/", "put")])
def test_unsupported_methods_are_rejected(client, path, method):
    result = getattr(client, method)(path)
    assert result.status_code == 405


@pytest.mark.django_db
def test_storage_failure_leaves_no_half_written_user_or_opinion(client, monkeypatch):
    def fail(*args, **kwargs):
        raise DatabaseError("Private database details")

    monkeypatch.setattr(Opinion.objects, "create", fail)
    result = submit(client, username="alice", lat=1.0, lon=2.0)
    assert result.status_code == 503
    # User creation and Opinion creation share one transaction, so a failed
    # Opinion doesn't leave an orphaned User a retry could collide with.
    assert User.objects.count() == 0
    assert Opinion.objects.count() == 0


@pytest.mark.django_db
def test_embedding_failure_preserves_typed_text_and_retry_succeeds(client, embedding):
    embedding.side_effect = RuntimeError("Internal model details")
    text = "A submission awaiting its embedding."
    failed = submit(client, text=text, username="alice", lat=1.0, lon=2.0)
    assert failed.status_code == 503
    assert "Internal model details" not in failed.content.decode()
    assert escape(text) in failed.content.decode()
    assert User.objects.count() == 0
    assert Opinion.objects.count() == 0

    embedding.side_effect = None
    retried = submit(client, text=text, username="alice", lat=1.0, lon=2.0)
    assert retried.status_code == 302
    assert Opinion.objects.get().text == text


@pytest.mark.django_db
def test_sentiment_failure_preserves_typed_text_and_retry_succeeds(client, monkeypatch):
    scorer = Mock(side_effect=RuntimeError("Internal sentiment model details"))
    monkeypatch.setattr("opinions.models.score_text", scorer)
    response = submit(client, username="alice", lat=1.0, lon=2.0)
    assert response.status_code == 503
    assert User.objects.count() == 0

    scorer.side_effect = None
    scorer.return_value = 4
    assert submit(client, username="alice", lat=1.0, lon=2.0).status_code == 302
    assert Opinion.objects.get().sentiment == 4


@pytest.mark.django_db
def test_topic_classification_failure_preserves_typed_text_and_retry_succeeds(
    client, monkeypatch
):
    classifier = Mock(side_effect=RuntimeError("Internal model details"))
    monkeypatch.setattr("opinions.topic_classification.classify_topics", classifier)
    response = submit(client, username="alice", lat=1.0, lon=2.0)
    assert response.status_code == 503
    assert User.objects.count() == 0

    classifier.side_effect = None
    classifier.return_value = (["housing", "transport"], {"method": "test"})
    assert submit(client, username="alice", lat=1.0, lon=2.0).status_code == 302
    assert Opinion.objects.get().topic_ids == ["housing", "transport"]


@pytest.mark.django_db
def test_search_returns_indexed_input_with_author_but_no_credentials(
    client, monkeypatch
):
    text = "A submission to public opinion search."
    saved = submit(client, text, username="alice", lat=1.0, lon=2.0)
    assert saved.status_code == 302
    opinion = Opinion.objects.get()
    monkeypatch.setattr("opinions.search.embed_text", lambda _: VECTOR)
    result = client.get("/topics/", {"q": text})
    assert result.status_code == 200
    match = next(item for item in result.context["results"] if item["id"] == opinion.pk)
    assert match["text"] == text
    assert set(match) == {
        "id",
        "text",
        "author",
        "author_id",
        "distance",
        "similarity",
        "sentiment",
        "sentiment_label",
        "sentiment_group",
        "sentiment_group_label",
        "topics",
        "topic_analysis",
    }
    assert match["author"] == "alice"


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
    monkeypatch.setattr(Opinion.objects, "create", failure)
    home = client.get("/")
    assert home.context["directory_error"]
    assert b"No opinions yet" not in home.content
    failed = submit(client, text="Keep my draft.", username="alice", lat=1.0, lon=2.0)
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
def test_opinion_keeps_categories_and_search_result_when_clusters_are_added(
    client, monkeypatch, clustered
):
    # An opinion with no author (e.g. created outside the identified
    # submission form -- admin, a fixture, an older row) must keep working
    # through search and clustering the same as any other.
    Opinion.objects.all().delete()
    Cluster.objects.all().delete()
    cache.clear()
    monkeypatch.setattr("opinions.search.embed_text", Mock(return_value=VECTOR))
    monkeypatch.setattr("opinions.search.score_text", Mock(return_value=4))
    opinion = Opinion.objects.create(
        text="A housing opinion.",
        embedding=VECTOR,
        sentiment=4,
        topic_ids=["housing"],
    )
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
    assert result["text"] == opinion.text
    assert result["author_id"] is None
    cache.clear()


@pytest.mark.django_db
def test_user_opinions_page_lists_opinions_publicly_without_edit_forms(client):
    author = User.objects.create(username="alice")
    opinion = Opinion.objects.create(
        text="Housing needs more supply.",
        embedding=VECTOR,
        sentiment=4,
        author=author,
        topic_ids=["housing"],
    )
    Argument.objects.create(text="Supply and demand.", opinion=opinion)

    response = client.get(f"/users/{author.uuid}/")
    assert response.status_code == 200
    assert response.context["is_owner"] is False
    row = response.context["opinions"][0]
    assert row["text"] == opinion.text
    assert row["sentiment"] == 4
    assert [topic["id"] for topic in row["topics"]] == ["housing"]
    assert [argument.text for argument in row["arguments"]] == ["Supply and demand."]
    assert b"Save changes" not in response.content


@pytest.mark.django_db
def test_user_opinions_page_shows_edit_forms_to_its_own_identity_cookie(
    client, embedding
):
    submit(client, "Housing needs more supply.", username="alice", lat=1.0, lon=2.0)
    author = User.objects.get(username="alice")

    owner_view = client.get(f"/users/{author.uuid}/")
    assert owner_view.status_code == 200
    assert owner_view.context["is_owner"] is True
    assert b"Save changes" in owner_view.content

    visitor_view = Client().get(f"/users/{author.uuid}/")
    assert visitor_view.context["is_owner"] is False
    assert b"Save changes" not in visitor_view.content


@pytest.mark.django_db
def test_edit_opinion_regenerates_embedding_sentiment_topics_and_clusters(
    client, embedding
):
    submit(client, "Original text.", username="alice", lat=1.0, lon=2.0)
    author = User.objects.get(username="alice")
    opinion = Opinion.objects.get(author=author)

    old_cluster = Cluster.objects.create(
        layer=0, evoc_id=0, label="old", centroid=VECTOR, size=1
    )
    opinion.clusters.add(old_cluster)

    new_vector = [0.0, 1.0] + [0.0] * 1022
    embedding.return_value = new_vector
    new_cluster = Cluster.objects.create(
        layer=0, evoc_id=1, label="new", centroid=new_vector, size=0
    )

    response = client.post(
        f"/users/{author.uuid}/opinions/{opinion.pk}/edit/",
        {"text": "Updated text."},
    )
    assert response.status_code == 302
    assert response.url == f"/users/{author.uuid}/#opinion-{opinion.pk}"

    opinion.refresh_from_db()
    assert opinion.text == "Updated text."
    assert list(opinion.embedding) == new_vector
    assert list(opinion.clusters.all()) == [new_cluster]

    old_cluster.refresh_from_db()
    assert old_cluster.size == 0
    new_cluster.refresh_from_db()
    assert new_cluster.size == 1


@pytest.mark.django_db
def test_edit_opinion_rejects_a_request_from_a_different_identity(client, embedding):
    submit(client, "Original text.", username="alice", lat=1.0, lon=2.0)
    author = User.objects.get(username="alice")
    opinion = Opinion.objects.get(author=author)

    intruder = Client()
    submit(intruder, "Bob's own opinion.", username="bob", lat=3.0, lon=4.0)
    response = intruder.post(
        f"/users/{author.uuid}/opinions/{opinion.pk}/edit/", {"text": "Hijacked!"}
    )
    assert response.status_code == 403
    opinion.refresh_from_db()
    assert opinion.text == "Original text."


@pytest.mark.django_db
def test_add_and_edit_argument_require_ownership(client, embedding):
    submit(client, "Original text.", username="alice", lat=1.0, lon=2.0)
    author = User.objects.get(username="alice")
    opinion = Opinion.objects.get(author=author)

    add_url = f"/users/{author.uuid}/opinions/{opinion.pk}/arguments/add/"
    added = client.post(add_url, {"text": "A good reason."})
    assert added.status_code == 302
    argument = Argument.objects.get(opinion=opinion)
    assert argument.text == "A good reason."

    edit_url = (
        f"/users/{author.uuid}/opinions/{opinion.pk}/arguments/{argument.pk}/edit/"
    )
    edited = client.post(edit_url, {"text": "A better reason."})
    assert edited.status_code == 302
    argument.refresh_from_db()
    assert argument.text == "A better reason."

    intruder = Client()
    submit(intruder, "Bob's own opinion.", username="bob", lat=3.0, lon=4.0)
    denied = intruder.post(add_url, {"text": "Sneaky."})
    assert denied.status_code == 403
    assert Argument.objects.filter(opinion=opinion).count() == 1


@pytest.mark.django_db
def test_identity_cookie_is_tamper_evident(rf):
    from opinions.identity import IDENTITY_COOKIE, get_current_user

    user = User.objects.create(username="alice")
    request = rf.get("/")
    request.COOKIES[IDENTITY_COOKIE] = str(user.uuid)  # unsigned, not a real cookie
    assert get_current_user(request) is None


@pytest.mark.django_db
def test_identity_cookie_round_trips_through_remember(rf):
    from django.http import HttpResponse

    from opinions.identity import IDENTITY_COOKIE, get_current_user, remember

    user = User.objects.create(username="alice")
    response = HttpResponse()
    remember(response, user)
    cookie_value = response.cookies[IDENTITY_COOKIE].value

    request = rf.get("/")
    request.COOKIES[IDENTITY_COOKIE] = cookie_value
    assert get_current_user(request) == user


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
