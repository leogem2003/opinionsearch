"""Tests for the /admin customizations in opinions/admin.py.

No database or model loading needed here -- these just check ModelAdmin
class attributes, which is where "sentiment can't be edited in /admin" is
actually enforced (see the comment in OpinionAdmin.readonly_fields).
"""

from opinions.admin import OpinionAdmin


def test_sentiment_field_is_readonly_in_admin():
    # Naming the real model field here (not just the sentiment_display
    # method) is what excludes it from the editable change-form -- see
    # opinions/admin.py.
    assert "sentiment" in OpinionAdmin.readonly_fields


def test_sentiment_label_shown_in_admin_list():
    # sentiment_display (a method, not the raw "sentiment" field) is what's
    # in list_display, so the admin list shows the label, not just the score.
    assert "sentiment_display" in OpinionAdmin.list_display
