"""Data model for opinions, their arguments, embeddings, and sentiment.

Layout follows design.md: a single PostgreSQL database where pgvector holds the
embeddings and clusters, PostGIS holds geo data. Opinion embeds both the text
and the vector directly. Sentiment isn't part of design.md; it's stored the
same way the embedding is (computed on first save, see ``Opinion.save``)
because it's the same kind of derived-from-text-at-write-time value.
"""

import uuid

# django.contrib.gis.db.models re-exports the standard field types alongside the
# geo ones, so this single import covers both.
from django.contrib.gis.db import models
from pgvector.django import HnswIndex, VectorField

from .embedding import embed_text
from .sentiment import score_text

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
    """One node of the discovered topic hierarchy -- a group of nearby embeddings.

    Topics aren't declared by whoever publishes an opinion; they're discovered
    by clustering the embeddings with EVōC (``opinions/clustering.py``), which
    produces several nested resolutions at once. Each row here is one cluster
    from one of those resolutions:

    - ``layer`` 0 is the finest grained (EVōC's ``cluster_layers_[0]``); higher
      layers are coarser, broader topics.
    - ``evoc_id`` is the cluster's id *within its layer*, as EVōC reports it, so
      ``(layer, evoc_id)`` is a node of its ``cluster_tree_``.
    - ``parent`` is that tree's edge towards the coarser layers. It is null for
      the top layer, and also for any cluster EVōC hangs straight off its
      synthetic root -- a narrow topic that never merges into a broader one.
      That root itself isn't stored: "everything" is not a useful topic.
    - ``label`` is derived from the member texts after the fact
      (``opinions/topic_labels.py``) -- EVōC only outputs ids, never words.

    Re-clustering replaces every row (see ``clustering.cluster_opinions``), so
    ids here are not stable identifiers across runs.
    """

    layer = models.PositiveSmallIntegerField()
    evoc_id = models.PositiveIntegerField()
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    label = models.CharField(max_length=200, blank=True)
    # The member opinion closest to every other member (its medoid): the
    # cluster's best single representative quote, which reads far better than
    # a keyword label alone. Nullable because a cluster outlives any one of
    # its opinions.
    exemplar = models.ForeignKey(
        "Opinion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="exemplar_of",
    )
    centroid = VectorField(dimensions=EMBEDDING_DIM)
    # Denormalised count of the opinions assigned to this cluster, so listing
    # topics doesn't need an aggregate over the membership table.
    size = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["layer", "evoc_id"], name="unique_cluster_per_layer"
            )
        ]
        ordering = ["layer", "evoc_id"]

    def __str__(self):
        return f"L{self.layer}: {self.label or f'cluster {self.evoc_id}'}"


class Opinion(models.Model):
    """A published opinion. Its text is the source of the embedding.

    ``timestamp`` and ``geo_coordinates`` sit here rather than on User: they
    describe the act of publishing, and the search read path filters on them
    directly after joining embeddings back to opinions.
    """

    text = models.TextField()
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
    # A 1-5 star rating from opinions/sentiment.py, null until computed. Not
    # editable in /admin (see OpinionAdmin.readonly_fields) for the same
    # reason embedding/cluster aren't: it's a derived value, not one to set
    # by hand. opinions.sentiment.sentiment_label() turns it into a label.
    sentiment = models.PositiveSmallIntegerField(null=True, blank=True)
    # One cluster per layer of the hierarchy, rather than a single FK: EVōC
    # labels every layer independently, and an opinion that is noise at the
    # finest layer can still fall inside a broader cluster higher up (measured
    # on this project's own corpus, not hypothetical). Walking parents from a
    # single finest-layer FK would silently drop those. Empty until
    # clustering has run at all -- see opinions/clustering.py.
    clusters = models.ManyToManyField(Cluster, blank=True, related_name="opinions")

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
        """Embed, score sentiment, and place into the topic hierarchy on first save.

        The opinion text is fed into BGE-M3 and into the sentiment model
        (opinions/sentiment.py); both results are stored directly on the
        Opinion row before it's written to the database. Editing an already
        embedded/scored opinion's text does not currently redo either.

        A full re-clustering (opinions/clustering.py's ``cluster_opinions``,
        run via ``manage.py recluster``) is a whole-corpus operation and far
        too slow to run per save, so it does *not* happen here. Instead, once
        the row exists, ``assign_to_nearest_clusters`` does a cheap
        nearest-centroid lookup against whatever hierarchy already exists --
        an approximation (it moves no centroids and creates no clusters) that
        gives a newly published opinion a topic immediately rather than
        leaving it unclustered until the next re-clustering run.
        """
        is_new = self.pk is None
        if self.embedding is None and self.text:
            self.embedding = embed_text(self.text)
        if self.sentiment is None and self.text:
            self.sentiment = score_text(self.text)
        super().save(*args, **kwargs)
        if is_new:
            # Local import: opinions.clustering imports this module (for
            # Cluster/Opinion), so importing it back at module level here
            # would be a circular import.
            from .clustering import assign_to_nearest_clusters

            assign_to_nearest_clusters(self)

    def cluster_at(self, layer):
        """This opinion's cluster in ``layer``, or None if it was noise there."""
        return self.clusters.filter(layer=layer).first()

    def __str__(self):
        return self.text[:60]


class Argument(models.Model):
    """A supporting argument attached to an opinion."""

    text = models.TextField()
    opinion = models.ForeignKey(
        Opinion, on_delete=models.CASCADE, related_name="arguments"
    )

    def __str__(self):
        return self.text[:50]
