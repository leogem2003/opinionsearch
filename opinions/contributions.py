"""Anonymous intake and URL-receipt-authenticated reads, as plain HTML forms."""

import hashlib
import logging
import re
import secrets
import uuid

from django.db import DatabaseError, transaction
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from .models import Contribution, Opinion
from .pipeline import (
    EmbeddingUnavailable,
    SentimentUnavailable,
    TopicsUnavailable,
    index_contribution,
)
from .topics import topic_summaries

logger = logging.getLogger(__name__)

SUBMISSION_KEY = re.compile(r"[A-Za-z0-9_-]{32,128}")
# Matches secrets.token_urlsafe(32)'s output length exactly.
RECEIPT = re.compile(r"[A-Za-z0-9_-]{43}")

RETRY_MESSAGE = (
    "We couldn't finish your submission. Your text is still here. Please try again."
)

# How many topics the home page teaser shows -- matches PublicTopicDirectory's
# `compact` mode in the retired React frontend.
TEASER_TOPIC_COUNT = 4


def _issue_text_error(text):
    if not text.strip():
        return "Describe an issue before sending."
    if len(text) > 2000 or "\0" in text:
        return "Use 2,000 characters or fewer. Your text is still here."
    try:
        text.encode("utf-8")
    except UnicodeError:
        return "Use valid Unicode text."
    return ""


def _teaser_topics():
    _, summaries = topic_summaries()
    visible = [
        topic
        for topic in summaries
        if topic["id"] != "unassigned" or topic["opinionCount"] > 0
    ]
    visible.sort(key=lambda topic: (-topic["opinionCount"], topic["title"]))
    return visible[:TEASER_TOPIC_COUNT]


def _render_issue_form(request, key, text, error="", status=200):
    try:
        topics, directory_error = _teaser_topics(), ""
    except DatabaseError:
        logger.exception("Topic preview unavailable")
        topics, directory_error = [], "Topics could not be loaded. Please try again."
    return render(
        request,
        "opinions/home.html",
        {
            "submission_key": key,
            "text": text,
            "error": error,
            "topics": topics,
            "directory_error": directory_error,
        },
        status=status,
    )


def _get_or_create_contribution(key, text):
    with transaction.atomic():
        contribution, _ = Contribution.objects.get_or_create(
            submission_key_hash=hashlib.sha256(key.encode("ascii")).hexdigest(),
            defaults={
                "text": text,
                "publication": "public",
                "access_token": secrets.token_urlsafe(32),
            },
        )
    if contribution.text == text and contribution.publication == "public":
        return contribution, key
    # Edited text is a new source. Derive its key from this form and draft so
    # replaying the previous request also recovers it if the response was lost.
    new_key = hashlib.sha256(f"{key}\0{text}".encode("utf-8")).hexdigest()
    with transaction.atomic():
        contribution, _ = Contribution.objects.get_or_create(
            submission_key_hash=hashlib.sha256(new_key.encode("ascii")).hexdigest(),
            defaults={
                "text": text,
                "publication": "public",
                "access_token": secrets.token_urlsafe(32),
            },
        )
    return contribution, new_key


@require_http_methods(["GET", "POST"])
def submit_issue(request):
    if request.method == "GET":
        return _render_issue_form(request, secrets.token_urlsafe(32), "")

    text = request.POST.get("text", "")
    key = request.POST.get("submission_key", "")
    if not SUBMISSION_KEY.fullmatch(key):
        key = secrets.token_urlsafe(32)

    error = _issue_text_error(text)
    if error:
        return _render_issue_form(request, key, text, error, status=400)

    contribution = None
    try:
        contribution, key = _get_or_create_contribution(key, text)
        index_contribution(contribution)
    except (
        DatabaseError,
        EmbeddingUnavailable,
        SentimentUnavailable,
        TopicsUnavailable,
    ):
        logger.exception("Issue submission could not finish")
        message = (
            "Your original text is saved, but analysis could not finish. Send it again to retry."
            if contribution is not None
            else RETRY_MESSAGE
        )
        return _render_issue_form(request, key, text, message, status=503)

    url = reverse("contribution-detail", args=[contribution.id])
    return HttpResponseRedirect(f"{url}?receipt={contribution.access_token}")


@require_GET
def contribution_detail(request, contribution_id):
    token = request.GET.get("receipt", "")
    contribution = None
    try:
        identifier = uuid.UUID(contribution_id)
    except ValueError:
        identifier = None
    if identifier is not None and RECEIPT.fullmatch(token):
        candidate = Contribution.objects.filter(pk=identifier).first()
        if candidate is not None and secrets.compare_digest(
            token, candidate.access_token
        ):
            contribution = candidate

    if contribution is None:
        return render(
            request,
            "opinions/contribution_detail.html",
            {"contribution": None},
            status=404,
        )

    searchable = (
        contribution.publication == "public"
        and Opinion.objects.filter(
            contribution=contribution, embedding__isnull=False
        ).exists()
    )
    return render(
        request,
        "opinions/contribution_detail.html",
        {"contribution": contribution, "searchable": searchable},
    )
