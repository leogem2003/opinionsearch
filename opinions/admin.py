from django.contrib import admin

from .models import Argument, Cluster, Opinion, User
from .sentiment import sentiment_label


class ArgumentInline(admin.TabularInline):
    model = Argument
    extra = 0


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "uuid")
    search_fields = ("username",)


@admin.register(Opinion)
class OpinionAdmin(admin.ModelAdmin):
    list_display = (
        "text",
        "author",
        "topics_display",
        "sentiment_display",
        "timestamp",
    )
    list_filter = ("sentiment", "timestamp", "clusters")
    search_fields = ("text", "author__username")
    autocomplete_fields = ("author",)
    # Opinion.save() generates embedding/sentiment from the text, and
    # opinions/clustering.py assigns the clusters; none of the three is
    # something to pick by hand, but all are worth seeing on the change page.
    # Naming the real "sentiment" field here (not just sentiment_display
    # below) is what makes Django drop it from the editable form -- a readonly
    # *method* alone wouldn't stop the plain field from also appearing as an
    # editable input.
    readonly_fields = ("embedding", "sentiment", "clusters")
    inlines = [ArgumentInline]

    @admin.display(description="sentiment", ordering="sentiment")
    def sentiment_display(self, opinion):
        if opinion.sentiment is None:
            return "—"
        return f"{opinion.sentiment}/5 ({sentiment_label(opinion.sentiment)})"

    @admin.display(description="topics (fine → broad)")
    def topics_display(self, opinion):
        """The discovered topics this opinion belongs to, finest layer first."""
        clusters = opinion.clusters.order_by("layer")
        if not clusters:
            return "—"
        return " / ".join(str(cluster) for cluster in clusters)


@admin.register(Argument)
class ArgumentAdmin(admin.ModelAdmin):
    list_display = ("text", "opinion")
    search_fields = ("text",)


@admin.register(Cluster)
class ClusterAdmin(admin.ModelAdmin):
    list_display = ("__str__", "layer", "label", "size", "parent", "updated_at")
    list_filter = ("layer",)
    search_fields = ("label",)
    # Everything here is discovered by opinions/clustering.py and replaced
    # wholesale on the next run, so there is nothing to edit by hand.
    readonly_fields = (
        "layer",
        "evoc_id",
        "parent",
        "label",
        "centroid",
        "size",
        "exemplar",
    )
