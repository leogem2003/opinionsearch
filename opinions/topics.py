"""Predefined civic topic browsing/search pages. Browsing never runs a model."""

import logging
import math

from django.db import DatabaseError
from django.db.models import Count, Max, Q
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import Opinion
from .search import DEFAULT_MAX_DISTANCE, search_opinions
from .sentiment import sentiment_label
from .topic_classification import TOPIC_IDS, TOPICS

logger = logging.getLogger(__name__)

SEARCH_LIMIT = 50

SORT_OPTIONS = [
    ("popular", "Most opinions"),
    ("recent", "Recently active"),
    ("title", "Alphabetical"),
]

# Mirrors the retired React frontend's SearchSentiment.jsx GROUPS, including
# its colours, so the ported CSS/markup stays visually identical.
SENTIMENT_GROUPS = [
    ("positive", "Positive", "#8fdbb6"),
    ("negative", "Negative", "#ffa596"),
    ("neutral", "Neutral", "#d0bcf4"),
    ("unscored", "Not yet analysed", "#b9ccd5"),
]
SENTIMENT_GROUP_LABELS = {key: label for key, label, _ in SENTIMENT_GROUPS}


def _sentiment_group(score):
    if not isinstance(score, int) or score < 1 or score > 5:
        return "unscored"
    if score < 3:
        return "negative"
    if score > 3:
        return "positive"
    return "neutral"


def _dot_positions(count):
    """Same golden-angle scatter as the retired SearchSentiment.jsx DotCluster."""
    positions = []
    for index in range(count):
        angle = index * 2.39996323
        radius = 0 if count == 1 else math.sqrt(index + 0.5) * 8.6
        positions.append(
            {
                "cx": round(120 + math.cos(angle) * radius * 1.4, 2),
                "cy": round(83 + math.sin(angle) * radius, 2),
            }
        )
    return positions


def topic_summaries():
    """(total_opinions, [{id, title, description, opinionCount, lastContributionAt}, ...])."""
    definitions = [
        *TOPICS,
        {
            "id": "unassigned",
            "title": "Other / unassigned",
            "description": "Opinions without a matching topic, including those awaiting classification.",
        },
    ]
    aggregates = {"total": Count("pk")}
    for index, topic in enumerate(definitions):
        matching = (
            Q(topic_ids=[])
            if topic["id"] == "unassigned"
            else Q(topic_ids__contains=[topic["id"]])
        )
        aggregates[f"count_{index}"] = Count("pk", filter=matching)
        aggregates[f"latest_{index}"] = Max("timestamp", filter=matching)
    counts = Opinion.objects.aggregate(**aggregates)
    return counts["total"], [
        {
            "id": topic["id"],
            "title": topic["title"],
            "description": topic["description"],
            "opinionCount": counts[f"count_{index}"],
            "lastContributionAt": counts[f"latest_{index}"],
        }
        for index, topic in enumerate(definitions)
    ]


def _sort_key(sort):
    if sort == "recent":
        return lambda topic: (
            topic["lastContributionAt"] is None,
            topic["lastContributionAt"] and -topic["lastContributionAt"].timestamp(),
            topic["title"],
        )
    if sort == "title":
        return lambda topic: topic["title"]
    return lambda topic: (-topic["opinionCount"], topic["title"])


def _opinion_rows(matches, has_query):
    return [
        {
            "id": item.pk,
            "text": item.text,
            "author": item.author.username if item.author_id else None,
            "author_id": item.author_id,
            "distance": float(item.distance) if has_query else None,
            "similarity": 1 - float(item.distance) if has_query else None,
            "sentiment": item.sentiment,
            "sentiment_label": sentiment_label(item.sentiment),
            "sentiment_group": _sentiment_group(item.sentiment),
            "sentiment_group_label": SENTIMENT_GROUP_LABELS[
                _sentiment_group(item.sentiment)
            ],
            "topics": [
                {"id": topic["id"], "title": topic["title"]}
                for topic in TOPICS
                if topic["id"] in item.topic_ids
            ],
            "topic_analysis": item.topic_analysis,
        }
        for item in matches
    ]


def _bucket_by_sentiment(rows):
    grouped = {key: [] for key, _, _ in SENTIMENT_GROUPS}
    for row in rows:
        grouped[row["sentiment_group"]].append(row)
    groups = [
        {"id": key, "label": label, "colour": colour, "items": grouped[key]}
        for key, label, colour in SENTIMENT_GROUPS
    ]
    for group in groups[:2]:
        group["dots"] = _dot_positions(len(group["items"]))
    return groups[:2], groups[2:]


def _search_results(query, topic_param):
    matches = (
        search_opinions(query, DEFAULT_MAX_DISTANCE)
        if query
        else Opinion.objects.order_by("-timestamp", "-pk")
    ).select_related("author")
    if topic_param:
        matches = (
            matches.filter(topic_ids=[])
            if topic_param == "unassigned"
            else matches.filter(topic_ids__contains=[topic_param])
        )
    return _opinion_rows(list(matches[:SEARCH_LIMIT]), has_query=bool(query))


@require_GET
def topics_browse(request):
    query = request.GET.get("q", "").strip()
    topic_param = request.GET.get("topic", "")
    sort = request.GET.get("sort", "popular")
    if sort not in dict(SORT_OPTIONS):
        sort = "popular"

    if topic_param and topic_param not in TOPIC_IDS | {"unassigned"}:
        return render(
            request,
            "opinions/topics_browse.html",
            {"topic_unavailable": True},
            status=404,
        )

    context = {"query": query, "sort": sort, "sorts": SORT_OPTIONS}

    if len(query) > 2000 or "\0" in query:
        context["query_error"] = "Use a search of at most 2,000 characters."
        return render(request, "opinions/topics_browse.html", context, status=400)

    if not query and not topic_param:
        try:
            total, summaries = topic_summaries()
        except DatabaseError:
            logger.exception("Topic directory unavailable")
            context["page_error"] = "Topics could not be loaded. Please try again."
            return render(request, "opinions/topics_browse.html", context, status=503)
        directory = [
            topic
            for topic in summaries
            if topic["id"] != "unassigned" or topic["opinionCount"] > 0
        ]
        directory.sort(key=_sort_key(sort))
        context.update(
            {"results": None, "directory": directory, "total_opinions": total}
        )
        return render(request, "opinions/topics_browse.html", context)

    try:
        rows = _search_results(query, topic_param)
    except Exception:
        logger.exception("Opinion search unavailable")
        context["page_error"] = "Search is unavailable right now. Please try again."
        return render(request, "opinions/topics_browse.html", context, status=503)
    primary_groups, secondary_groups = _bucket_by_sentiment(rows)
    context.update(
        {
            "results": rows,
            "result_limit": SEARCH_LIMIT,
            "primary_groups": primary_groups,
            "secondary_groups": secondary_groups,
        }
    )
    return render(request, "opinions/topics_browse.html", context)


@require_GET
def topic_detail(request, topic_id):
    if topic_id not in TOPIC_IDS | {"unassigned"}:
        raise Http404("Unknown topic.")
    try:
        _, summaries = topic_summaries()
        topic = next(item for item in summaries if item["id"] == topic_id)
        rows = _search_results("", topic_id)
    except DatabaseError:
        logger.exception("Topic unavailable")
        return render(
            request,
            "opinions/topics_browse.html",
            {"page_error": "This topic could not be loaded. Please try again."},
            status=503,
        )
    primary_groups, secondary_groups = _bucket_by_sentiment(rows)
    return render(
        request,
        "opinions/topic_detail.html",
        {
            "topic": topic,
            "results": rows,
            "result_limit": SEARCH_LIMIT,
            "primary_groups": primary_groups,
            "secondary_groups": secondary_groups,
        },
    )
