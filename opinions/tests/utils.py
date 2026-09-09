"""Test utility to load a JSON fixture of users/topics/statements as opinions.

The fixture format is:

    {
      "users": ["alice", "bob", ...],
      "topics": ["climate policy", ...],
      "statements": [
        {"user": "alice", "topic": "climate policy", "text": "..."},
        ...
      ]
    }

Each statement is stored as an ``Opinion`` authored by the named user, as if
that user had published it themselves. ``topics`` is only descriptive of what
the fixture covers -- ``Opinion.topic`` is a plain string, so it isn't looked
up against anything.
"""

import json
from pathlib import Path

from opinions.embedding import embed_texts
from opinions.models import Opinion, User


def load_opinions_fixture(path: Path) -> list[Opinion]:
    """Create Users and Opinions from a JSON fixture file.

    All statement texts are embedded in a single batch call (see
    ``opinions.embedding.embed_texts``) instead of one BGE-M3 call per
    statement, since fixtures can list many statements at once. The
    resulting Opinions are inserted with ``bulk_create``, so ``Opinion.save``
    is not invoked -- embeddings are supplied up front instead of being
    computed on save.
    """
    data = json.loads(Path(path).read_text())
    statements = data["statements"]

    users = {
        username: User.objects.get_or_create(username=username)[0]
        for username in data["users"]
    }
    embeddings = embed_texts([statement["text"] for statement in statements])

    opinions = [
        Opinion(
            text=statement["text"],
            topic=statement["topic"],
            author=users[statement["user"]],
            embedding=embedding,
        )
        for statement, embedding in zip(statements, embeddings)
    ]
    return Opinion.objects.bulk_create(opinions)
