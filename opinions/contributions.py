"""Anonymous intake and URL-receipt-authenticated reads, as plain HTML forms."""

import hashlib
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
    stripped = text.strip()
    if not stripped:
        return "Describe an issue before sending."
    if len(stripped) > 2000 or "\0" in text:
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
        return contribution
    # The hidden submission key is generated fresh on every GET /, so this
    # only happens if a visitor edited previously-failed text before
    # resubmitting the same page. Start over with a new key rather than
    # surfacing a conflict there is no useful way for them to resolve.
    new_key = secrets.token_urlsafe(32)
    with transaction.atomic():
        contribution, _ = Contribution.objects.get_or_create(
            submission_key_hash=hashlib.sha256(new_key.encode("ascii")).hexdigest(),
            defaults={
                "text": text,
                "publication": "public",
                "access_token": secrets.token_urlsafe(32),
            },
        )
    return contribution


@require_http_methods(["GET", "POST"])
def submit_issue(request):
    if request.method == "GET":
        return render(
            request,
            "opinions/home.html",
            {
                "submission_key": secrets.token_urlsafe(32),
                "text": "",
                "topics": _teaser_topics(),
            },
        )

    text = request.POST.get("text", "")
    key = request.POST.get("submission_key", "")
    if not SUBMISSION_KEY.fullmatch(key):
        key = secrets.token_urlsafe(32)

    error = _issue_text_error(text)
    if error:
        return render(
            request,
            "opinions/home.html",
            {
                "submission_key": key,
                "text": text,
                "error": error,
                "topics": _teaser_topics(),
            },
            status=400,
        )

    text = text.strip()
    try:
        contribution = _get_or_create_contribution(key, text)
        index_contribution(contribution)
    except (
        DatabaseError,
        EmbeddingUnavailable,
        SentimentUnavailable,
        TopicsUnavailable,
    ):
        return render(
            request,
            "opinions/home.html",
            {
                "submission_key": key,
                "text": text,
                "error": RETRY_MESSAGE,
                "topics": _teaser_topics(),
            },
            status=503,
        )

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
