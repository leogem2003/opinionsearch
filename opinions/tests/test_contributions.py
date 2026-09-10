"""Intake and indexing guarantees against PostgreSQL, with a fixed embedding.

The real BGE-M3 submission-to-search check lives in test_search.py.
"""

import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

import pytest
from django.db import DatabaseError, connections
from django.test import Client

from opinions.models import Contribution, Opinion
from opinions.pipeline import index_contribution

URL = "/api/v1/contributions/"
KEY = "a" * 64
VECTOR = [1.0] + [0.0] * 1023


@pytest.fixture
def client():
    return Client(enforce_csrf_checks=True)


@pytest.fixture(autouse=True)
def embedding(monkeypatch):
    def unexpected_model():
        pytest.fail(
            "These tests use a fixed embedding; real inference is tested separately"
        )

    monkeypatch.setattr("opinions.embedding.get_embedder", unexpected_model)
    monkeypatch.setattr("opinions.sentiment.get_sentiment_pipeline", unexpected_model)
    monkeypatch.setattr("opinions.pipeline.score_text", Mock(return_value=4))
    embed = Mock(return_value=VECTOR)
    monkeypatch.setattr("opinions.pipeline.embed_text", embed)
    return embed


def create(client, text="An issue worth understanding.", key=KEY, publication="public"):
    return client.post(
        URL,
        {"text": text, "submissionKey": key, "publication": publication},
        content_type="application/json",
    )


def read(client, receipt):
    return client.get(
        f"{URL}{receipt['id']}/",
        HTTP_AUTHORIZATION=f"Bearer {receipt['accessToken']}",
    )


@pytest.mark.django_db
def test_create_indexes_exact_original_text_without_cookies(embedding):
    client = Client(enforce_csrf_checks=True)
    public_count = Opinion.objects.count()
    text = "  Housing 🏡\nSchöne Wohnungen.  "
    saved = create(client, text)
    receipt = saved.json()
    assert saved.status_code == 201
    assert saved["Location"] == f"{URL}{receipt['id']}/"
    assert saved["Cache-Control"] == "no-store"
    assert receipt["publication"] == "public"
    assert receipt["searchable"] is True
    assert len(receipt["accessToken"]) == 43
    source = Contribution.objects.get(pk=receipt["id"])
    assert source.text == text
    assert source.submission_key_hash == hashlib.sha256(KEY.encode()).hexdigest()

    result = read(client, receipt)
    assert result.status_code == 200
    assert result.json() == {
        "id": receipt["id"],
        "text": text,
        "createdAt": source.created_at.isoformat(),
        "publication": "public",
        "searchable": True,
    }
    assert result["Cache-Control"] == "no-store"
    assert "Authorization" in result["Vary"]
    assert Opinion.objects.count() == public_count + 1
    opinion = Opinion.objects.get(contribution=source)
    assert opinion.text == source.text
    assert opinion.author is None
    assert opinion.topic == ""
    assert opinion.sentiment == 4
    assert list(opinion.embedding) == VECTOR
    embedding.assert_called_once_with(text)


@pytest.mark.django_db
def test_receipt_is_required_and_denials_do_not_reveal_the_source(client):
    receipt = create(client).json()
    other = create(client, key="b" * 64).json()
    url = f"{URL}{receipt['id']}/"
    responses = [
        client.get(url),
        client.get(url, HTTP_AUTHORIZATION="Bearer " + "x" * 43),
        client.get(url, HTTP_AUTHORIZATION="Bearer non-ascii-é"),
        client.get(url, HTTP_AUTHORIZATION=f"Bearer {other['accessToken']}"),
        client.get(
            f"{URL}{uuid.uuid4()}/",
            HTTP_AUTHORIZATION=f"Bearer {receipt['accessToken']}",
        ),
        client.get(
            f"{URL}not-a-uuid/", HTTP_AUTHORIZATION=f"Bearer {receipt['accessToken']}"
        ),
    ]
    for result in responses:
        assert result.status_code == 404
        assert result.json() == {
            "error": {"code": "not_found", "message": "Contribution unavailable."}
        }
        assert result["Cache-Control"] == "no-store"
        assert "Authorization" in result["Vary"]


@pytest.mark.django_db
def test_retry_recovers_receipt_and_conflict_preserves_original(client, embedding):
    first = create(client)
    replay = create(Client())
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert read(Client(), replay.json()).status_code == 200
    conflict = create(client, text="Different text")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "submission_conflict"
    assert Contribution.objects.count() == 1
    assert Opinion.objects.filter(contribution__isnull=False).count() == 1
    assert embedding.call_count == 1
    assert read(client, first.json()).json()["text"] == "An issue worth understanding."
    assert create(client, key="b" * 64).status_code == 201
    assert Contribution.objects.count() == 2
    assert Opinion.objects.filter(contribution__isnull=False).count() == 2
    assert embedding.call_count == 2


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("texts", [["Same text"] * 4, ["First text", "Second text"]])
def test_concurrent_retries_create_one_durable_contribution(texts):
    barrier = Barrier(len(texts))

    def submit(text):
        try:
            barrier.wait(timeout=10)
            result = create(Client(enforce_csrf_checks=True), text=text)
            return result.status_code, result.json()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(texts)) as pool:
        results = list(pool.map(submit, texts))
    assert Contribution.objects.count() == 1
    assert Opinion.objects.filter(contribution__isnull=False).count() == 1
    assert [status for status, _ in results].count(201) == 1
    winner = next(data for status, data in results if status == 201)
    if len(set(texts)) == 1:
        assert all(status in (200, 201) and data == winner for status, data in results)
    else:
        assert [status for status, _ in results].count(409) == 1
    # Reconnect after all submitting connections have closed: the source and
    # replay credential must live in the database, not in process memory.
    connections.close_all()
    assert read(Client(), winner).status_code == 200
    original = Contribution.objects.get().text
    assert create(Client(), text=original).json() == winner


@pytest.mark.parametrize(
    "text", [None, False, [], "", " \n ", "x" * 2001, "bad\0text", "\ud800"]
)
def test_invalid_text_is_rejected_without_storage(client, text):
    result = create(client, text=text)
    assert result.status_code == 400
    assert result.json()["error"]["code"] == "invalid_text"


@pytest.mark.parametrize("key", [None, False, [], "x" * 31, "x" * 129, "!" * 64])
def test_invalid_key_is_rejected_without_storage(client, key):
    result = create(client, key=key)
    assert result.status_code == 400
    assert result.json()["error"]["code"] == "invalid_submission_key"


@pytest.mark.parametrize("publication", [None, False, [], {}, "published", "PUBLIC"])
def test_invalid_publication_is_rejected_without_storage(client, publication):
    result = create(client, publication=publication)
    assert result.status_code == 400
    assert result.json()["error"]["code"] == "invalid_publication"


@pytest.mark.parametrize(
    "body", [b"{", b"[]", b"null", b"\xff", b'{"text": NaN}', b"[" * 2000 + b"]" * 2000]
)
def test_invalid_json_is_rejected_without_storage(client, body):
    result = client.post(URL, body, content_type="application/json")
    assert result.status_code == 400
    assert result.json()["error"]["code"] == "invalid_json"


def test_body_and_media_type_limits(client):
    result = client.post(URL, b" " * 32769, content_type="application/json")
    assert result.status_code == 413
    assert result.json()["error"]["code"] == "request_too_large"
    result = client.post(
        URL, "text=issue", content_type="application/x-www-form-urlencoded"
    )
    assert result.status_code == 415
    assert result.json()["error"]["code"] == "unsupported_media_type"


@pytest.mark.django_db
def test_2000_escaped_unicode_code_points_are_accepted(client):
    text = "🏡" * 2000
    body = json.dumps(
        {"text": text, "submissionKey": KEY, "publication": "public"}, ensure_ascii=True
    )
    assert len(body) > len(text.encode("utf-8"))
    saved = client.post(URL, body, content_type="application/json")
    assert saved.status_code == 201
    assert read(client, saved.json()).json()["text"] == text


@pytest.mark.parametrize(
    "path,method,allowed",
    [
        (URL, "get", "POST"),
        (URL, "put", "POST"),
        (URL + "example/", "post", "GET"),
        (URL + "example/", "delete", "GET"),
    ],
)
def test_unsupported_methods_return_json(client, path, method, allowed):
    result = getattr(client, method)(path)
    assert result.status_code == 405
    assert result["Allow"] == allowed
    assert result.json()["error"]["code"] == "method_not_allowed"
    assert result["Cache-Control"] == "no-store"


@pytest.mark.django_db
def test_storage_failures_never_acknowledge_a_save(client, monkeypatch):
    def fail(*args, **kwargs):
        raise DatabaseError("Private database details")

    monkeypatch.setattr(Contribution.objects, "get_or_create", fail)
    result = create(client)
    assert result.status_code == 503
    assert result.json() == {
        "error": {
            "code": "storage_unavailable",
            "message": "Storage is unavailable. Please retry.",
        }
    }
    assert Contribution.objects.count() == 0


@pytest.mark.django_db
def test_legacy_private_input_is_not_indexed_or_published_by_retry(client, embedding):
    public_count = Opinion.objects.count()
    text = "An earlier private input."
    receipt = client.post(
        URL, {"text": text, "submissionKey": KEY}, content_type="application/json"
    ).json()
    assert receipt["publication"] == "private"
    assert receipt["searchable"] is False
    assert read(client, receipt).json()["publication"] == "private"
    assert create(client, text=text).status_code == 409
    source = Contribution.objects.get(pk=receipt["id"])
    assert source.publication == "private"
    with pytest.raises(ValueError, match="Only public"):
        index_contribution(source)
    assert Opinion.objects.count() == public_count
    embedding.assert_not_called()


@pytest.mark.django_db
def test_embedding_failure_preserves_source_and_retry_completes_indexing(
    client, embedding
):
    text = "A saved source awaiting its embedding."
    embedding.side_effect = RuntimeError("Internal model details")
    failed = create(client, text=text)
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "embedding_unavailable"
    assert "Internal model details" not in failed.content.decode()
    source = Contribution.objects.get()
    assert source.text == text
    assert not Opinion.objects.filter(contribution=source).exists()
    receipt = {"id": str(source.id), "accessToken": source.access_token}
    assert read(client, receipt).json()["searchable"] is False

    embedding.side_effect = None
    retried = create(client, text=text)
    assert retried.status_code == 200
    assert retried.json()["id"] == str(source.id)
    assert retried.json()["searchable"] is True
    assert Contribution.objects.count() == 1
    assert Opinion.objects.get(contribution=source).text == text
    assert read(client, receipt).json()["searchable"] is True


@pytest.mark.django_db
def test_search_returns_indexed_input_with_source_id_but_no_credentials(
    client, monkeypatch
):
    text = "A contribution to public opinion search."
    receipt = create(client, text=text).json()
    monkeypatch.setattr("opinions.search.embed_text", lambda _: VECTOR)
    result = client.get("/api/v1/opinions/", {"query": text, "max_distance": "0"})
    assert result.status_code == 200
    match = next(
        item
        for item in result.json()["results"]
        if item["contributionId"] == receipt["id"]
    )
    assert match["text"] == text
    assert set(match) == {
        "id",
        "contributionId",
        "text",
        "topic",
        "distance",
        "similarity",
        "sentiment",
        "sentimentLabel",
    }
    assert receipt["accessToken"] not in result.content.decode()


@pytest.mark.django_db
def test_sentiment_failure_keeps_source_and_retry_completes_it(client, monkeypatch):
    scorer = Mock(side_effect=RuntimeError("Internal sentiment model details"))
    monkeypatch.setattr("opinions.pipeline.score_text", scorer)
    response = create(client)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "sentiment_unavailable"
    source = Contribution.objects.get()
    assert not Opinion.objects.filter(contribution=source).exists()
    scorer.side_effect = None
    scorer.return_value = 4
    assert create(client).status_code == 200
    assert Opinion.objects.get(contribution=source).sentiment == 4
