"""Explicit sample-data fixture for the search tests.

Loading the sample opinions calls into BGE-M3 (opinions.embedding), which
pays a real model-load cost the first time it runs. The explicit
``opinion_samples`` loads the fixture once per search test module and batches
every statement into a single embedding call. Contract tests use a fixed
embedding; the search module also checks intake through the real model.
"""

from pathlib import Path

import pytest

from opinions.tests.utils import load_opinions_fixture

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_opinions.json"


@pytest.fixture(scope="module")
def opinion_samples(django_db_setup, django_db_blocker):
    from opinions.models import Opinion

    with django_db_blocker.unblock():
        # --reuse-db (see pyproject.toml) keeps this database between runs,
        # so without clearing it out first each run would pile more copies
        # of the fixture's opinions on top of the last one.
        Opinion.objects.all().delete()
        load_opinions_fixture(FIXTURE_PATH)
