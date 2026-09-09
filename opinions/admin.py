from django.contrib import admin

from .models import Argument, Cluster, Opinion, User


class ArgumentInline(admin.TabularInline):
    model = Argument
    extra = 0


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "uuid")
    search_fields = ("username",)


@admin.register(Opinion)
class OpinionAdmin(admin.ModelAdmin):
    list_display = ("topic", "text", "author", "timestamp", "cluster")
    list_filter = ("topic", "timestamp", "cluster")
    search_fields = ("text", "topic", "author__username")
    autocomplete_fields = ("author",)
    # Opinion.save() generates embedding from the text; it isn't something to pick
    # by hand, but it's still worth seeing on the change page.
    readonly_fields = ("embedding", "text")
    inlines = [ArgumentInline]


@admin.register(Argument)
class ArgumentAdmin(admin.ModelAdmin):
    list_display = ("text", "opinion")
    search_fields = ("text",)


@admin.register(Cluster)
class ClusterAdmin(admin.ModelAdmin):
    list_display = ("id", "updated_at")
