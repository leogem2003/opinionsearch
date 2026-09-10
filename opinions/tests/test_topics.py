"""Focused topic decisions, browse contracts and reclassification checks."""

import hashlib
from unittest.mock import Mock

import numpy as np
import pytest
from django.core.management import call_command

from opinions import topic_classification as classification
from opinions.models import Opinion

VECTOR = [1.0] + [0.0] * 1023


@pytest.fixture
def empty_opinions(db):
    # --reuse-db may retain the search module's separately loaded fixtures.
    Opinion.objects.all().delete()


@pytest.mark.parametrize(
    "scores,expected",
    [([0.8, 0.78, 0.6] + [0.2] * 7, ["housing", "immigration"]), ([0.2] * 10, [])],
)
def test_classification_retains_close_topics_or_abstains_with_provenance(
    monkeypatch, scores, expected
):
    refs = [[score, np.sqrt(1 - score**2)] for score in scores for _ in range(3)]
    monkeypatch.setattr(
        classification, "topic_vectors", lambda: (np.array(refs), "test-revision")
    )
    ids, analysis = classification.classify_topics("Original input", [1.0, 0.0])
    assert ids == expected
    assert analysis["inputHash"] == hashlib.sha256(b"Original input").hexdigest()
    assert analysis["referenceModelRevision"] == "test-revision"
    assert analysis["catalogueHash"] == classification.CATALOGUE_HASH
    assert [row["topicId"] for row in analysis["scores"] if row["assigned"]] == ids
    assert len(analysis["scores"]) == len(classification.TOPICS)


@pytest.mark.django_db
def test_topic_counts_and_browsing_use_stored_membership_without_inference(
    client, monkeypatch, empty_opinions
):
    monkeypatch.setattr(
        "opinions.search.embed_text",
        Mock(side_effect=AssertionError("Browsing must not embed a query")),
    )
    shared = Opinion.objects.create(
        text="Housing and transport.",
        embedding=VECTOR,
        sentiment=3,
        topic_ids=["housing", "transport"],
        topic_analysis={"method": "test"},
    )
    other = Opinion.objects.create(
        text="An unassigned opinion.",
        embedding=VECTOR,
        sentiment=4,
        topic_analysis={"method": "test"},
    )
    response = client.get("/topics/")
    assert response.status_code == 200
    counts = {
        topic["id"]: topic["opinionCount"] for topic in response.context["directory"]
    }
    assert response.context["total_opinions"] == 2
    assert counts["housing"] == counts["transport"] == counts["unassigned"] == 1
    assert counts["healthcare"] == 0
    for topic in ["housing", "transport"]:
        results = client.get("/topics/", {"topic": topic}).context["results"]
        assert [row["id"] for row in results] == [shared.pk]
        assert results[0]["distance"] is None
        assert {row["id"] for row in results[0]["topics"]} == {"housing", "transport"}
    unassigned = client.get("/topics/", {"topic": "unassigned"}).context["results"]
    assert unassigned[0]["id"] == other.pk


def test_unknown_topic_is_rejected_without_inference(client):
    assert client.get("/topics/", {"topic": "invented"}).status_code == 404
    assert client.get("/topics/invented/").status_code == 404


@pytest.mark.django_db
def test_backfill_is_repeatable_and_all_replaces_only_topic_analysis(
    monkeypatch, empty_opinions
):
    item = Opinion.objects.bulk_create(
        [
            Opinion(
                text="Original input",
                embedding=VECTOR,
                sentiment=4,
            )
        ]
    )[0]
    classifier = Mock(return_value=(["housing"], {"method": "test"}))
    monkeypatch.setattr(classification, "classify_topics", classifier)
    call_command("backfill_topics")
    call_command("backfill_topics")
    assert classifier.call_count == 1
    classifier.return_value = (["transport"], {"method": "test-v2"})
    call_command("backfill_topics", all=True)
    item.refresh_from_db()
    assert item.topic_ids == ["transport"]
    assert (item.text, item.sentiment) == (
        "Original input",
        4,
    )
