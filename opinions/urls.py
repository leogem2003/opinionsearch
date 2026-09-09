from django.urls import path

from . import views

app_name = "opinions"

urlpatterns = [
    path("", views.search, name="search"),
]
