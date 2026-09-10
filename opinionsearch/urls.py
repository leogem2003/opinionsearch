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

from opinions.legal import privacy_policy, terms
from opinions.submissions import submit_issue
from opinions.topics import topic_detail, topics_browse
from opinions.users import add_argument, edit_argument, edit_opinion, user_opinions

urlpatterns = [
    path("admin/", admin.site.urls),
    path("search/", include("opinions.urls")),
    path("", submit_issue, name="home"),
    path("topics/", topics_browse, name="topics"),
    path("topics/<str:topic_id>/", topic_detail, name="topic-detail"),
    path("users/<uuid:user_uuid>/", user_opinions, name="user-opinions"),
    path(
        "users/<uuid:user_uuid>/opinions/<int:opinion_id>/edit/",
        edit_opinion,
        name="edit-opinion",
    ),
    path(
        "users/<uuid:user_uuid>/opinions/<int:opinion_id>/arguments/add/",
        add_argument,
        name="add-argument",
    ),
    path(
        "users/<uuid:user_uuid>/opinions/<int:opinion_id>/arguments/<int:argument_id>/edit/",
        edit_argument,
        name="edit-argument",
    ),
    path("privacy-policy/", privacy_policy, name="privacy-policy"),
    path("terms-and-conditions/", terms, name="terms"),
]
