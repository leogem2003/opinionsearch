"""Backfill opinions/sentiment.py scores onto existing Opinion rows.

A newly-created Opinion gets scored automatically by ``Opinion.save()`` (see
``opinions/models.py``). This command is for rows that predate the
``sentiment`` field -- it's a plain ``AddField`` migration (see
``opinions/migrations/0003_opinion_sentiment.py``), so it doesn't touch
existing data -- or that otherwise ended up with ``sentiment IS NULL``.
"""

from django.core.management.base import BaseCommand

from opinions.models import Opinion
from opinions.sentiment import score_texts

DEFAULT_BATCH_SIZE = 64


class Command(BaseCommand):
    help = "Score sentiment (opinions/sentiment.py) for every Opinion that doesn't have one yet."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help="How many opinions to run through the sentiment model per call "
            f"(default: {DEFAULT_BATCH_SIZE}).",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        total = Opinion.objects.filter(sentiment__isnull=True).count()
        if not total:
            self.stdout.write(
                "Nothing to do -- every Opinion already has a sentiment score."
            )
            return

        self.stdout.write(f"Scoring {total} opinion(s) in batches of {batch_size}...")
        scored = 0
        # Re-querying sentiment__isnull=True each iteration (rather than
        # paging through one queryset) means opinions scored by an earlier
        # batch simply drop out of the next one.
        while True:
            batch = list(
                Opinion.objects.filter(sentiment__isnull=True).order_by("pk")[
                    :batch_size
                ]
            )
            if not batch:
                break
            sentiments = score_texts([opinion.text for opinion in batch])
            for opinion, sentiment in zip(batch, sentiments):
                opinion.sentiment = sentiment
            Opinion.objects.bulk_update(batch, ["sentiment"])
            scored += len(batch)
            self.stdout.write(f"  {scored}/{total}")

        self.stdout.write(self.style.SUCCESS(f"Scored {scored} opinion(s)."))
