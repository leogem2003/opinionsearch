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
                "not agreement with a topic. Submissions previously saved "
                "as private remain private unless explicitly made public.",
            ],
        },
        {
            "id": "access-receipt",
            "heading": "Your access receipt",
            "paragraphs": [
                "After you submit, the website links you to a saved-text "
                "page whose address includes an access receipt. It uses the "
                "receipt to reopen your saved-text page without an account. "
                "Keep that link; the receipt does not make publicly "
                "submitted text private.",
                "Losing the link can prevent access to your contribution; "
                "it does not delete the text stored on the server. This "
                "prototype has no automatic expiry, account recovery, or "
                "contribution editing or deletion in its interface.",
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
                "The issue form lets you submit your own text and reopen it "
                "with a saved link.",
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
