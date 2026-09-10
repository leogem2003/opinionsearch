"""Explicit sample-data fixture for search and clustering tests.

``opinion_samples`` batches embeddings and sentiment once per requesting
module, then clusters the corpus with EVōC. Contract tests use fixed model
outputs and do not request this expensive fixture.
"""

from pathlib import Path

import pytest

from opinions.tests.utils import load_opinions_fixture

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "sample_opinions.json"


@pytest.fixture(scope="module")
def opinion_samples(django_db_setup, django_db_blocker):
    from opinions.clustering import cluster_opinions
    from opinions.models import Cluster, Opinion

    with django_db_blocker.unblock():
        # --reuse-db (see pyproject.toml) keeps this database between runs,
        # so without clearing it out first each run would pile more copies
        # of the fixture's opinions on top of the last one.
        Opinion.objects.all().delete()
        Cluster.objects.all().delete()
        load_opinions_fixture(FIXTURE_PATH)
        cluster_opinions()
