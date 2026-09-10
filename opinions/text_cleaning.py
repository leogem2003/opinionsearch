"""Conservative text cleanup shared by embedding and topic labelling.

Both ``opinions/embedding.py`` (a cleaner embedding separates clusters
better) and ``opinions/topic_labels.py`` (c-TF-IDF label terms) need to
discount the same kind of noise: generic English stopwords, plus a handful of
words common to nearly every *opinion* regardless of topic (e.g. "should",
"think") that a generic list doesn't cover. One shared list is a single
answer to "what counts as noise here" instead of two that could drift apart.
"""

import string

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

# Negation flips an opinion's meaning ("not real" vs. "real"), so these stay
# in even though scikit-learn's list otherwise treats them as noise -- being
# conservative matters more here than a marginally cleaner embedding.
_NEGATIONS = frozenset({"no", "not", "nor", "never", "against"})

# What an opinion *sounds like* regardless of its topic, not what any one
# topic is about, so these characterise nothing -- added on top of the
# generic list.
OPINION_FILLER = frozenset(
    {
        "just",
        "make",
        "makes",
        "need",
        "needs",
        "new",
        "people",
        "really",
        "say",
        "should",
        "think",
        "way",
        "would",
    }
)

STOP_WORDS = (frozenset(ENGLISH_STOP_WORDS) - _NEGATIONS) | OPINION_FILLER


def clean_for_embedding(text: str) -> str:
    """Lowercase ``text`` and drop stopwords/opinion filler, for embedding.

    Deliberately conservative: words are dropped, never stemmed or
    reordered, and a kept word keeps its own punctuation (so contractions
    like "don't" survive) -- a whitespace-separated token is only dropped if
    itself, lowercased and stripped of surrounding punctuation, is in
    STOP_WORDS. Falls back to the plain lowercased text if that would empty
    it out entirely (a very short opinion, say), rather than embedding "".
    """
    words = text.split()
    kept = [w for w in words if w.strip(string.punctuation).lower() not in STOP_WORDS]
    return " ".join(kept).lower() if kept else text.lower()
