"""
URL configuration for opinionsearch project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import include, path

from opinions.contributions import create_contribution, get_contribution
from opinions.views import search_api
from opinions.topics import topic_index

urlpatterns = [
    path("admin/", admin.site.urls),
    path("search/", include("opinions.urls")),
    path("api/v1/opinions/", search_api, name="opinion-search-api"),
    path("api/v1/topics/", topic_index, name="topic-index-api"),
    path("api/v1/contributions/", create_contribution, name="contribution-create"),
    path(
        "api/v1/contributions/<str:contribution_id>/",
        get_contribution,
        name="contribution-detail",
    ),
]
