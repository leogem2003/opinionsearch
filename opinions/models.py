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
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from pgvector.django import HnswIndex, VectorField

from .embedding import embed_text
from .sentiment import score_text

# Dense embedding width of BGE-M3, the model named in design.md.
EMBEDDING_DIM = 1024


class Contribution(models.Model):
    """Original input and its declared visibility; receipts are always private."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    # Preserve the visibility promised to submissions made before public intake.
    publication = models.CharField(
        max_length=7,
        choices=[("private", "Private"), ("public", "Public")],
        default="private",
    )
    submission_key_hash = models.CharField(max_length=64, unique=True, editable=False)
    # Persist the private receipt so a lost response can be recovered on retry.
    # Neither this field nor the submission key is exposed by the read endpoint.
    access_token = models.CharField(max_length=64, editable=False)


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
    # Fixed civic categories are independent of discovered EVōC clusters.
    topic_ids = ArrayField(
        models.SlugField(max_length=40), default=list, blank=True, editable=False
    )
    topic_analysis = models.JSONField(default=dict, blank=True, editable=False)
    # One searchable representation per source in this prototype. The stable
    # source link preserves provenance and makes indexing retries idempotent.
    contribution = models.OneToOneField(
        Contribution,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="opinion",
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    geo_coordinates = models.PointField(geography=True, null=True, blank=True)
    author = models.ForeignKey(
        User,
        to_field="uuid",
        db_column="user_uuid",
        on_delete=models.CASCADE,
        related_name="opinions",
        null=True,
        blank=True,
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
            GinIndex(fields=["topic_ids"], name="opinion_topic_ids_gin"),
            # Cosine distance, matching how BGE-M3 embeddings are normally compared.
            HnswIndex(
                name="opinion_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def save(self, *args, **kwargs):
        """Embed and score sentiment on first save (design.md write path, plus sentiment).

        The opinion text is fed into BGE-M3 and into the sentiment model
        (opinions/sentiment.py); both results are stored directly on the
        Opinion row before it's written to the database. Editing an already
        embedded/scored opinion's text does not currently redo either.

        Predefined civic categories are assigned here for new opinions.
        Discovered clusters are computed separately over the whole corpus --
        see opinions/clustering.py and ``manage.py recluster``. A new opinion
        has no discovered cluster memberships until the next clustering run.
        """
        if self.embedding is None and self.text:
            self.embedding = embed_text(self.text)
        if self.sentiment is None and self.text:
            self.sentiment = score_text(self.text)
        if (
            self._state.adding
            and not self.topic_analysis
            and self.embedding is not None
        ):
            from .topic_classification import classify_topics

            self.topic_ids, self.topic_analysis = classify_topics(
                self.text, self.embedding
            )
        super().save(*args, **kwargs)

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
