"""Shared test-session fixtures for the opinions app.

Loading the sample opinions calls into BGE-M3 (opinions.embedding) and the
sentiment model (opinions.sentiment), which pay a real model-load cost the
first time they run, and clustering them calls into EVōC. Overriding
``django_db_setup`` (session-scoped) does all of that once for the whole test
run instead of once per test, batching every statement into a single call per
model (see opinions.tests.utils.load_opinions_fixture).

Clustering runs here too, rather than in individual tests, because topics are
discovered from the corpus as a whole -- the search tests need it to have
happened before they look at a result's topic.
"""

from pathlib import Path

import pytest

from opinions.tests.utils import load_opinions_fixture

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_opinions.json"


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    from opinions.clustering import cluster_opinions
    from opinions.models import Opinion

    with django_db_blocker.unblock():
        # --reuse-db (see pyproject.toml) keeps this database between runs,
        # so without clearing it out first each run would pile more copies
        # of the fixture's opinions on top of the last one.
        Opinion.objects.all().delete()
        load_opinions_fixture(FIXTURE_PATH)
        cluster_opinions()
