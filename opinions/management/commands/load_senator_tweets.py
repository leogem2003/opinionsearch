"""Load a subset of real opinions (US Senator tweets) from the Hugging Face Hub.

m-newhauser/senator-tweets (huggingface.co/datasets/m-newhauser/senator-tweets)
is ~80k tweets from sitting US Senators' official accounts -- real, topically
diverse short-form political statements, which is exactly the shape of data
this project models an ``Opinion`` as. It ships its own 384-dim embeddings,
but those are from a different model than this project uses; they're ignored,
and every tweet is (re-)embedded with BGE-M3 like any other Opinion, so
search and clustering stay comparable across every opinion regardless of
where it came from.

``datasets.load_dataset`` (already a dependency via the FlagEmbedding/
transformers stack, and declared directly in pyproject.toml since this module
imports it itself) is the most convenient way to pull it: one call handles
the download, on-disk parquet caching under ``~/.cache/huggingface`` (the
same cache the embedding/sentiment model weights already use -- see
CLAUDE.md), and re-running this command is then instant on the fetch side.
"""

import re

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from opinions.embedding import embed_texts
from opinions.models import Opinion, User
from opinions.sentiment import score_texts

DATASET_NAME = "m-newhauser/senator-tweets"
DATASET_SPLIT = "train"

# A "sensible size" subset: enough for a multi-layer hierarchy with real
# topical variety (see opinions/clustering.py's MIN_OPINIONS_TO_CLUSTER),
# without an unreasonable load time on a CPU-only machine. BGE-M3 embeds at
# roughly 1.5 texts/s on this project's own dev machine (no GPU available),
# so the default is about 6 minutes end to end; --limit trades size for time.
DEFAULT_LIMIT = 1000
DEFAULT_SEED = 42
DEFAULT_MIN_LENGTH = 15

# Tweets are full of t.co link shorteners, which carry no text of their own
# and would otherwise sit in the embedding as noise.
URL_PATTERN = re.compile(r"https?://\S+")


class Command(BaseCommand):
    help = (
        "Load a subset of the m-newhauser/senator-tweets dataset as Opinions "
        "(replacing existing ones by default) and cluster them. See the "
        "module docstring for why this dataset and this method."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=DEFAULT_LIMIT,
            help=f"How many tweets to load (default: {DEFAULT_LIMIT}).",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=DEFAULT_SEED,
            help="Shuffle seed for the sample, so re-running with the same "
            f"--limit reproduces the same corpus (default: {DEFAULT_SEED}).",
        )
        parser.add_argument(
            "--min-length",
            type=int,
            default=DEFAULT_MIN_LENGTH,
            help="Drop tweets shorter than this after stripping links "
            f"(default: {DEFAULT_MIN_LENGTH}).",
        )
        parser.add_argument(
            "--keep-existing",
            action="store_true",
            help="Add to the current Opinions instead of replacing them. "
            "Without this, every existing Opinion (and its Arguments and "
            "cluster memberships) is deleted first, so re-running this "
            "command gives a clean, reproducible corpus rather than piling "
            "duplicates on top of the last run.",
        )
        parser.add_argument(
            "--skip-cluster",
            action="store_true",
            help="Load the opinions but don't run `recluster` afterwards.",
        )

    def handle(self, *args, **options):
        from datasets import load_dataset  # deferred: a slow, heavy import

        if not options["keep_existing"]:
            existing = Opinion.objects.count()
            if existing:
                self.stdout.write(f"Deleting {existing} existing opinion(s)...")
                Opinion.objects.all().delete()

        self.stdout.write(f"Fetching {DATASET_NAME} ({DATASET_SPLIT})...")
        dataset = load_dataset(DATASET_NAME, split=DATASET_SPLIT)

        texts, usernames = self._sample(
            dataset, options["limit"], options["seed"], options["min_length"]
        )
        self.stdout.write(
            f"Sampled {len(texts)} tweet(s) from {len(set(usernames))} senator(s)."
        )

        self.stdout.write(
            "Embedding with BGE-M3 (this is the slow part -- several minutes "
            "on a CPU-only machine)..."
        )
        embeddings = embed_texts(texts)
        self.stdout.write("Scoring sentiment...")
        sentiments = score_texts(texts)

        self._create_opinions(texts, usernames, embeddings, sentiments)
        self.stdout.write(self.style.SUCCESS(f"Created {len(texts)} opinion(s)."))

        if not options["skip_cluster"]:
            call_command("recluster")

    def _sample(self, dataset, limit, seed, min_length):
        """Pick ``limit`` unique, cleaned tweets, deterministic for a given seed.

        Iterates the dataset in shuffled order rather than pre-slicing it,
        since some rows get dropped (too short after cleaning, or exact
        duplicates -- senators' offices post identical press-release text
        from multiple accounts) and slicing first could come up short.
        """
        texts, usernames, seen = [], [], set()
        for row in dataset.shuffle(seed=seed):
            if len(texts) >= limit:
                break
            text = _clean(row["text"])
            if len(text) < min_length or text in seen:
                continue
            seen.add(text)
            texts.append(text)
            usernames.append(row["username"])
        return texts, usernames

    @transaction.atomic
    def _create_opinions(self, texts, usernames, embeddings, sentiments):
        """Bulk-create Users and Opinions, embedding/sentiment supplied up front.

        Same shape as ``opinions.tests.utils.load_opinions_fixture``: one
        get_or_create per distinct username (there are only ~100 senators, so
        this is cheap even at DEFAULT_LIMIT), then a single ``bulk_create`` for
        every Opinion so ``Opinion.save()`` -- and the per-row nearest-cluster
        lookup it would otherwise trigger, see models.py -- never runs here.
        That lookup is pointless mid-bulk-load anyway: the corpus-wide
        `recluster` this command runs afterwards supersedes it immediately.
        """
        users = {
            username: User.objects.get_or_create(username=username)[0]
            for username in set(usernames)
        }
        opinions = [
            Opinion(
                text=text,
                author=users[username],
                embedding=embedding,
                sentiment=sentiment,
            )
            for text, username, embedding, sentiment in zip(
                texts, usernames, embeddings, sentiments
            )
        ]
        Opinion.objects.bulk_create(opinions)


def _clean(text):
    """Strip t.co links and collapse whitespace left behind."""
    return re.sub(r"\s+", " ", URL_PATTERN.sub("", text)).strip()
