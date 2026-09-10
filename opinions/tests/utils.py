"""Test utility to load a JSON fixture of users/statements as opinions.

The fixture format is:

    {
      "users": ["alice", "bob", ...],
      "topics": ["climate policy", ...],
      "statements": [
        {"user": "alice", "topic": "climate policy",
         "subtopic": "carbon pricing", "text": "..."},
        ...
      ]
    }

Each statement is stored as an ``Opinion`` authored by the named user, as if
that user had published it themselves.

``topic``/``subtopic`` are evaluation labels, not stored memberships or civic
topic assignments. The integration tests compare them with discovered clusters;
see ``opinions/tests/integration/test_clustering.py``.
"""

import json
from pathlib import Path

from opinions.embedding import embed_texts
from opinions.models import Opinion, User
from opinions.sentiment import score_texts


def load_opinions_fixture(path: Path) -> list[Opinion]:
    """Create Users and Opinions from a JSON fixture file.

    All statement texts are embedded, and separately sentiment-scored, in one
    batch call each (see ``opinions.embedding.embed_texts`` and
    ``opinions.sentiment.score_texts``) instead of one model call per
    statement, since fixtures can list many statements at once. The
    resulting Opinions are inserted with ``bulk_create``, so ``Opinion.save``
    is not invoked -- the embedding and sentiment are supplied up front
    instead of being computed on save.

    Clustering is *not* run here: it needs the whole corpus at once, so it's a
    separate step (``opinions.clustering.cluster_opinions``) that the caller
    runs once the fixture is in place.
    """
    data = json.loads(Path(path).read_text())
    statements = data["statements"]
    texts = [statement["text"] for statement in statements]

    users = {
        username: User.objects.get_or_create(username=username)[0]
        for username in data["users"]
    }
    embeddings = embed_texts(texts)
    sentiments = score_texts(texts)

    opinions = [
        Opinion(
            text=statement["text"],
            author=users[statement["user"]],
            embedding=embedding,
            sentiment=sentiment,
        )
        for statement, embedding, sentiment in zip(statements, embeddings, sentiments)
    ]
    return Opinion.objects.bulk_create(opinions)
