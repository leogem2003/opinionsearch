"""A user's own opinions: view everyone's, edit and add arguments to your own.

Everything lives on one page (``opinions/templates/opinions/user_opinions.html``)
per its design -- editing an opinion's text, and viewing/editing/adding its
arguments, all happen inline there rather than on separate pages. Ownership
(``opinions.identity.get_current_user`` matching the profile being viewed) is
what decides whether the edit/add forms render at all, and is re-checked on
every POST regardless of what the page happened to render, since a visitor
could always submit a forged request for someone else's uuid.
"""

import logging

from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .identity import get_current_user
from .models import Argument, Opinion, User
from .pipeline import (
    EmbeddingUnavailable,
    SentimentUnavailable,
    TopicsUnavailable,
    reanalyze_opinion,
)
from .sentiment import sentiment_label
from .submissions import _issue_text_error
from .topic_classification import TOPICS

logger = logging.getLogger(__name__)

ARGUMENT_MAX_LENGTH = 1000


def _argument_text_error(text):
    if not text.strip():
        return "Write the argument before adding it."
    if len(text) > ARGUMENT_MAX_LENGTH or "\0" in text:
        return f"Use {ARGUMENT_MAX_LENGTH} characters or fewer."
    return ""


def _opinion_row(opinion):
    return {
        "id": opinion.pk,
        "text": opinion.text,
        "timestamp": opinion.timestamp,
        "sentiment": opinion.sentiment,
        "sentiment_label": sentiment_label(opinion.sentiment),
        "topics": [topic for topic in TOPICS if topic["id"] in opinion.topic_ids],
        "arguments": list(opinion.arguments.order_by("pk")),
    }


def _context(profile_user, is_owner, error="", error_opinion_id=None, error_text=""):
    opinions = profile_user.opinions.order_by("-timestamp", "-pk").prefetch_related(
        "clusters", "arguments"
    )
    return {
        "profile_user": profile_user,
        "is_owner": is_owner,
        "opinions": [_opinion_row(opinion) for opinion in opinions],
        "error": error,
        "error_opinion_id": error_opinion_id,
        "error_text": error_text,
    }


@require_GET
def user_opinions(request, user_uuid):
    profile_user = get_object_or_404(User, uuid=user_uuid)
    is_owner = get_current_user(request) == profile_user
    return render(
        request,
        "opinions/user_opinions.html",
        _context(profile_user, is_owner),
    )


def _require_ownership(request, user_uuid):
    """The owning ``User`` if this request's identity matches ``user_uuid``, else None."""
    profile_user = get_object_or_404(User, uuid=user_uuid)
    current_user = get_current_user(request)
    if current_user is None or current_user.pk != profile_user.pk:
        return None
    return profile_user


@require_POST
def edit_opinion(request, user_uuid, opinion_id):
    profile_user = _require_ownership(request, user_uuid)
    if profile_user is None:
        return HttpResponseForbidden("You can only edit your own opinions.")
    opinion = get_object_or_404(Opinion, pk=opinion_id, author=profile_user)

    text = request.POST.get("text", "")
    error = _issue_text_error(text)
    if not error:
        try:
            reanalyze_opinion(opinion, text)
        except (EmbeddingUnavailable, SentimentUnavailable, TopicsUnavailable):
            logger.exception("Opinion edit could not finish")
            error = "Could not finish updating this opinion. Please try again."

    if error:
        return render(
            request,
            "opinions/user_opinions.html",
            _context(
                profile_user,
                is_owner=True,
                error=error,
                error_opinion_id=opinion.pk,
                error_text=text,
            ),
            status=400,
        )
    return HttpResponseRedirect(
        f"{reverse('user-opinions', args=[profile_user.uuid])}#opinion-{opinion.pk}"
    )


@require_POST
def add_argument(request, user_uuid, opinion_id):
    profile_user = _require_ownership(request, user_uuid)
    if profile_user is None:
        return HttpResponseForbidden("You can only add arguments to your own opinions.")
    opinion = get_object_or_404(Opinion, pk=opinion_id, author=profile_user)

    text = request.POST.get("text", "")
    error = _argument_text_error(text)
    if error:
        return render(
            request,
            "opinions/user_opinions.html",
            _context(
                profile_user,
                is_owner=True,
                error=error,
                error_opinion_id=opinion.pk,
                error_text=text,
            ),
            status=400,
        )
    Argument.objects.create(text=text, opinion=opinion)
    return HttpResponseRedirect(
        f"{reverse('user-opinions', args=[profile_user.uuid])}#opinion-{opinion.pk}"
    )


@require_POST
def edit_argument(request, user_uuid, opinion_id, argument_id):
    profile_user = _require_ownership(request, user_uuid)
    if profile_user is None:
        return HttpResponseForbidden("You can only edit your own arguments.")
    opinion = get_object_or_404(Opinion, pk=opinion_id, author=profile_user)
    argument = get_object_or_404(Argument, pk=argument_id, opinion=opinion)

    text = request.POST.get("text", "")
    error = _argument_text_error(text)
    if error:
        return render(
            request,
            "opinions/user_opinions.html",
            _context(
                profile_user,
                is_owner=True,
                error=error,
                error_opinion_id=opinion.pk,
                error_text=text,
            ),
            status=400,
        )
    argument.text = text
    argument.save()
    return HttpResponseRedirect(
        f"{reverse('user-opinions', args=[profile_user.uuid])}#opinion-{opinion.pk}"
    )
