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
        "topic",
        "text",
        "author",
        "sentiment_display",
        "timestamp",
        "cluster",
    )
    list_filter = ("topic", "sentiment", "timestamp", "cluster")
    search_fields = ("text", "topic", "author__username")
    autocomplete_fields = ("author",)
    # Opinion.save() generates embedding/sentiment from the text; neither is
    # something to pick by hand, but both are still worth seeing on the change
    # page. Naming the real "sentiment" field here (not just sentiment_display
    # below) is what makes Django drop it from the editable form -- a readonly
    # *method* alone wouldn't stop the plain field from also appearing as an
    # editable input.
    readonly_fields = ("embedding", "sentiment", "cluster")
    inlines = [ArgumentInline]

    @admin.display(description="sentiment", ordering="sentiment")
    def sentiment_display(self, opinion):
        if opinion.sentiment is None:
            return "—"
        return f"{opinion.sentiment}/5 ({sentiment_label(opinion.sentiment)})"


@admin.register(Argument)
class ArgumentAdmin(admin.ModelAdmin):
    list_display = ("text", "opinion")
    search_fields = ("text",)


@admin.register(Cluster)
class ClusterAdmin(admin.ModelAdmin):
    list_display = ("id", "updated_at")
