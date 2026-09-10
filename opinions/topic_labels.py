"""Turning a cluster of opinions into something readable.

EVōC (``opinions/clustering.py``) is purely a vector clusterer: it hands back
cluster *ids*, never words. Naming those clusters is a separate step, and this
module is that step, kept apart from the clustering for the same reason
``sentiment_label`` is kept apart from the sentiment score: how a cluster is
worded should be changeable without touching how it was found.

The method here is **class-based TF-IDF** (c-TF-IDF), the standard cheap
approach used by BERTopic and friends: treat all the text in one cluster as a
single meta-document, then score each term by how characteristic it is of that
meta-document compared with the others. The top few terms become the label.

This is deliberately the crude option. Better labels (medoid exemplar
sentences, or an LLM asked for a three-word title) would slot in behind the
same ``label_clusters`` interface without anything else changing.
"""

import numpy as np
from sklearn.feature_extraction.text import CountVectorizer

from .text_cleaning import STOP_WORDS

# How many c-TF-IDF terms go into one label.
TERMS_PER_LABEL = 3


def label_clusters(texts_by_cluster):
    """Label each cluster from the words that set it apart from the others.

    Takes ``{cluster_key: [text, ...]}`` and returns ``{cluster_key: label}``,
    each label being the cluster's top ``TERMS_PER_LABEL`` c-TF-IDF terms
    joined with ", " (e.g. ``"rent, tenants, landlords"``). Cluster keys are
    opaque -- any hashable will do.

    Falls back to the empty string for a cluster whose text yields no usable
    terms at all (every word a stop word, say), rather than raising: an
    unlabelled cluster is still a perfectly good cluster.
    """
    if not texts_by_cluster:
        return {}

    keys = list(texts_by_cluster)
    meta_documents = [" ".join(texts_by_cluster[key]) for key in keys]

    vectorizer = CountVectorizer(
        stop_words=list(STOP_WORDS),
        # Keep alphabetic words of 3+ characters: numbers and one-off
        # fragments make for noisy labels.
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z-]{2,}\b",
    )
    try:
        counts = vectorizer.fit_transform(meta_documents).toarray()
    except ValueError:
        # Raised when the whole vocabulary is empty (e.g. every text is a stop
        # word). Nothing to name anything with.
        return {key: "" for key in keys}

    scores = _c_tf_idf(counts)
    terms = np.array(vectorizer.get_feature_names_out())

    labels = {}
    for row, key in enumerate(keys):
        # argsort ascending, so the last TERMS_PER_LABEL are the best; reverse
        # them so the strongest term comes first.
        top = np.argsort(scores[row])[-TERMS_PER_LABEL:][::-1]
        chosen = [terms[i] for i in top if scores[row][i] > 0]
        labels[key] = ", ".join(chosen)
    return labels


def _c_tf_idf(counts):
    """Class-based TF-IDF over a (n_clusters, n_terms) count matrix.

    Term frequency is taken within the cluster; the inverse document frequency
    compares against the *other clusters* rather than the other documents,
    which is what makes a term score highly for being characteristic of this
    cluster instead of merely common inside it.
    """
    counts = counts.astype(np.float64)
    words_per_cluster = counts.sum(axis=1, keepdims=True)
    # A cluster with no countable words would divide by zero; it scores 0s.
    term_frequency = np.divide(
        counts,
        words_per_cluster,
        out=np.zeros_like(counts),
        where=words_per_cluster > 0,
    )

    total_words = counts.sum()
    words_per_term = counts.sum(axis=0)
    average_words = total_words / counts.shape[0] if counts.shape[0] else 0.0
    inverse_frequency = np.log1p(
        np.divide(
            average_words,
            words_per_term,
            out=np.zeros_like(words_per_term, dtype=np.float64),
            where=words_per_term > 0,
        )
    )
    return term_frequency * inverse_frequency


def medoid_index(embeddings):
    """Index of the most central member of ``embeddings`` (its medoid).

    The opinion whose embedding is closest to all the others is the cluster's
    best single "representative quote" -- an alternative (or complement) to
    c-TF-IDF labels that ``clustering.py`` stores nothing for yet, but which
    the read path can use to show an exemplar. Cosine distance, matching how
    embeddings are compared everywhere else in this project.
    """
    vectors = np.asarray(embeddings, dtype=np.float64)
    normalized = vectors / np.clip(
        np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12, None
    )
    # Sum of cosine distances to every other member; smallest wins.
    distances = (1.0 - normalized @ normalized.T).sum(axis=1)
    return int(np.argmin(distances))
