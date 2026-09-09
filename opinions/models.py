"""Data model for opinions, their arguments, and their embeddings.

Layout follows design.md: a single PostgreSQL database where pgvector holds the
embeddings and clusters, PostGIS holds geo data. Opinion embeds both the text
and the vector directly.
"""

import uuid

# django.contrib.gis.db.models re-exports the standard field types alongside the
# geo ones, so this single import covers both.
from django.contrib.gis.db import models
from pgvector.django import HnswIndex, VectorField

from .embedding import embed_text

# Dense embedding width of BGE-M3, the model named in design.md.
EMBEDDING_DIM = 1024


class User(models.Model):
    """Publisher of opinions, per design.md: just a username and a uuid.

    Deliberately not Django's auth user and not AUTH_USER_MODEL -- no
    password, email, or permissions. Logging into /admin uses the separate,
    default django.contrib.auth.models.User instead.
    """

    username = models.CharField(max_length=150, unique=True)
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    def __str__(self):
        return self.username


class Cluster(models.Model):
    """A group of nearby opinion embeddings, recomputed as opinions arrive."""

    centroid = VectorField(dimensions=EMBEDDING_DIM)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cluster {self.pk}"


class Opinion(models.Model):
    """A published opinion. Its text is the source of the embedding.

    ``timestamp`` and ``geo_coordinates`` sit here rather than on User: they
    describe the act of publishing, and the search read path filters on them
    directly after joining embeddings back to opinions.
    """

    text = models.TextField()
    topic = models.CharField(max_length=200)
    timestamp = models.DateTimeField(auto_now_add=True)
    geo_coordinates = models.PointField(geography=True, null=True, blank=True)
    author = models.ForeignKey(
        User,
        to_field="uuid",
        db_column="user_uuid",
        on_delete=models.CASCADE,
        related_name="opinions",
    )
    # Null until the embedding has been computed and stored.
    embedding = VectorField(dimensions=EMBEDDING_DIM, null=True, blank=True)
    cluster = models.ForeignKey(
        Cluster,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="opinions",
    )

    class Meta:
        indexes = [
            # Cosine distance, matching how BGE-M3 embeddings are normally compared.
            HnswIndex(
                name="opinion_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            )
        ]

    def save(self, *args, **kwargs):
        """Embed on first save (design.md write path).

        The opinion text is fed into BGE-M3, the resulting vector is stored
        directly on the Opinion row before it's written to the database.
        Editing an already embedded opinion's text does not currently re-embed
        it; there's no re-clustering path yet either (clustering isn't implemented).
        """
        if self.embedding is None and self.text:
            self.embedding = embed_text(self.text)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.topic}: {self.text[:50]}"


class Argument(models.Model):
    """A supporting argument attached to an opinion."""

    text = models.TextField()
    opinion = models.ForeignKey(
        Opinion, on_delete=models.CASCADE, related_name="arguments"
    )

    def __str__(self):
        return self.text[:50]
