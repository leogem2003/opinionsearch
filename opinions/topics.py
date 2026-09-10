"""Read-only catalogue and stored membership; browsing never runs a model."""

from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import Opinion
from .topic_classification import CATALOGUE, TOPICS


@require_GET
def topic_index(request):
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
    return JsonResponse(
        {
            "catalogueVersion": CATALOGUE["version"],
            "totalOpinions": counts["total"],
            "topics": [
                {
                    "id": topic["id"],
                    "title": topic["title"],
                    "description": topic["description"],
                    "opinionCount": counts[f"count_{index}"],
                    "lastContributionAt": (
                        counts[f"latest_{index}"].isoformat()
                        if counts[f"latest_{index}"]
                        else None
                    ),
                }
                for index, topic in enumerate(definitions)
            ],
        }
    )
