"""Anonymous-to-identified issue intake: the public `/` form.

A browser identifies itself once, the first time it submits an opinion (a
username plus a position picked on a map -- see ``opinions/identity.py``),
and every later submission from that browser reuses the same ``User`` and
location automatically. There is no separate "commit the source, then index
it" step the way the old Contribution-based flow had: ``Opinion.save()``
already runs embedding/sentiment/predefined-topic inference and cluster
assignment synchronously (opinions/models.py), so a single
``Opinion.objects.create(...)`` either fully succeeds or the row never
exists at all -- nothing left to reconcile on retry.
"""

import logging

from django.contrib.gis.geos import Point
from django.db import DatabaseError, transaction
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .embedding import embed_text
from .identity import get_current_user, remember
from .models import Opinion, User
from .sentiment import score_text
from .topics import topic_summaries

logger = logging.getLogger(__name__)

RETRY_MESSAGE = (
    "We couldn't finish your submission. Your text is still here. Please try again."
)

# How many topics the home page teaser shows.
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


def _identity_error(username, lat, lon):
    if not username.strip():
        return "Tell us what to call you."
    if len(username) > 150:
        return "Use a shorter name (150 characters or fewer)."
    if User.objects.filter(username=username).exists():
        return "That name is already taken. Try another."
    if lat is None or lon is None:
        return "Click your approximate location on the map."
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return "That location doesn't look valid. Click the map again."
    return ""


def _parse_coordinate(raw_value):
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None


def _teaser_topics():
    _, summaries = topic_summaries()
    visible = [
        topic
        for topic in summaries
        if topic["id"] != "unassigned" or topic["opinionCount"] > 0
    ]
    visible.sort(key=lambda topic: (-topic["opinionCount"], topic["title"]))
    return visible[:TEASER_TOPIC_COUNT]


def _render_issue_form(
    request, text, error="", status=200, current_user=None, username=""
):
    try:
        topics, directory_error = _teaser_topics(), ""
    except DatabaseError:
        logger.exception("Topic preview unavailable")
        topics, directory_error = [], "Topics could not be loaded. Please try again."
    return render(
        request,
        "opinions/home.html",
        {
            "text": text,
            "error": error,
            "topics": topics,
            "directory_error": directory_error,
            "current_user": current_user,
            "username": username,
        },
        status=status,
    )


@require_http_methods(["GET", "POST"])
def submit_issue(request):
    current_user = get_current_user(request)

    if request.method == "GET":
        return _render_issue_form(request, "", current_user=current_user)

    text = request.POST.get("text", "")
    error = _issue_text_error(text)
    if error:
        return _render_issue_form(
            request, text, error, status=400, current_user=current_user
        )

    username = request.POST.get("username", "").strip()
    home_location = None
    if current_user is None:
        lat = _parse_coordinate(request.POST.get("lat"))
        lon = _parse_coordinate(request.POST.get("lon"))
        error = _identity_error(username, lat, lon)
        if error:
            return _render_issue_form(
                request, text, error, status=400, username=username
            )
        home_location = Point(lon, lat)

    try:
        # Atomic so a brand new User never survives a failed first Opinion:
        # otherwise a retry (no cookie yet, since remember() below never
        # ran) would hit "that name is already taken" against a User with
        # no opinions that the visitor can't see or recover.
        with transaction.atomic():
            if current_user is None:
                current_user = User.objects.create(
                    username=username, home_location=home_location
                )
            Opinion.objects.create(
                text=text,
                author=current_user,
                geo_coordinates=current_user.home_location,
            )
    except Exception:
        logger.exception("Issue submission could not finish")
        return _render_issue_form(
            request,
            text,
            RETRY_MESSAGE,
            status=503,
            current_user=get_current_user(request),
            username=username,
        )

    url = reverse("user-opinions", args=[current_user.uuid])
    response = HttpResponseRedirect(url)
    remember(response, current_user)
    return response
