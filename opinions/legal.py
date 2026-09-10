"""Static, factual prototype information pages (no model, no database)."""

from django.shortcuts import render
from django.views.decorators.http import require_GET

PRIVACY = {
    "title": "Privacy in this prototype",
    "intro": (
        "This page describes the current prototype. A privacy policy for a "
        "public service has not yet been established."
    ),
    "sections": [
        {
            "id": "issue-input",
            "heading": "Your issue input",
            "paragraphs": [
                "Submitting the form makes your text publicly searchable. "
                "HiveMind stores your original words and uses an embedding "
                "to find related text and models to estimate its sentiment "
                "and matching predefined topics. Sentiment describes tone, "
                "not agreement with a topic.",
            ],
        },
        {
            "id": "identity-cookie",
            "heading": "Your identity cookie",
            "paragraphs": [
                "The first time you submit an opinion, HiveMind asks for a "
                "name and an approximate location, then remembers you with "
                "a cookie in your browser -- there is no password or "
                "account. That cookie is what lets you come back later to "
                "edit your own opinions and their arguments; it is not sent "
                "anywhere except back to this site.",
                "Your name, chosen location and everything you publish "
                "under them are public: anyone can view the opinions listed "
                "on your page, though only your own browser's cookie can "
                "edit them. Clearing cookies, or using a different browser "
                "or device, starts a new, separate identity -- this "
                "prototype has no account recovery.",
            ],
        },
    ],
}

TERMS = {
    "title": "About this prototype",
    "intro": (
        "HiveMind is a prototype for exploring people’s views and the "
        "reasons behind them. This page explains its current scope; it is "
        "not a final set of service terms."
    ),
    "sections": [
        {
            "id": "current-experience",
            "heading": "What you can explore",
            "paragraphs": [
                "Search original opinions and explore their model-estimated "
                "sentiment, or browse topics by predefined civic category. "
                "The issue form lets you submit your own text; from then on "
                "an identity cookie lets you come back to your own opinions "
                "page to edit them and their arguments.",
            ],
        },
        {
            "id": "current-scope",
            "heading": "What is still being developed",
            "paragraphs": [
                "Submissions pass through an embedding model for "
                "related-text search and a sentiment model for the "
                "Positive, Negative and Neutral overview. Sentiment "
                "estimates tone, not support for the searched topic. "
                "Predefined topics are estimated automatically. Discussion "
                "discovery and position or reason analysis are not "
                "implemented yet.",
                "Operator details, contact information and policies for a "
                "public deployment remain to be established.",
            ],
        },
    ],
}


@require_GET
def privacy_policy(request):
    return render(request, "opinions/legal.html", {"doc": "privacy", "page": PRIVACY})


@require_GET
def terms(request):
    return render(request, "opinions/legal.html", {"doc": "terms", "page": TERMS})
