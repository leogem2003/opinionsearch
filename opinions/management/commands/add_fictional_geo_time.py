"""Backfill fictional but plausible location/time metadata onto Opinions.

`Opinion.geo_coordinates` and `Opinion.timestamp` exist on the model (see
design.md's read path: time/location filters against them), but nothing in
this project's real data sources -- the hand-written fixture, or
`load_senator_tweets` -- provides either: senator tweets have no reliable
public geotag, and every bulk-loaded opinion gets the same `timestamp`
(auto_now_add, set at load time). This command is what makes the map/time
filters on `/search/` and `/search/browse/` demonstrable against a real
corpus, by assigning FICTIONAL but geographically sensible values -- real US
city coordinates (`opinions/fictional_locations.json`), never a real claim
about any actual author's location -- and timestamps spread over a plausible
recent date range.

Reproducible by construction: given the same `--seed`, the same corpus (same
opinions in the same pk order) gets the same fictional data every time, the
same way `load_senator_tweets --seed` is reproducible. The same author (by
`User`, not per-opinion) always gets the same fictional city, so their own
opinions don't jump around the map -- anonymous opinions (no author) each
get their own independent, still-deterministic pick.
"""

import json
import random
from datetime import timedelta
from pathlib import Path

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.utils import timezone

from opinions.models import Opinion

LOCATIONS_PATH = (
    Path(__file__).resolve().parent.parent.parent / "fictional_locations.json"
)
LOCATIONS = json.loads(LOCATIONS_PATH.read_text())["cities"]

DEFAULT_SEED = 42
# ~2 years, deliberately unremarkable -- see the module docstring.
DEFAULT_DAYS = 730


class Command(BaseCommand):
    help = (
        "Assign fictional but plausible geo_coordinates/timestamp values to "
        "existing Opinions, for demonstrating the map/time-filtered search. "
        "See the module docstring for why, and README's 'Fictional geography "
        "and timestamps' section for the full picture."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--seed",
            type=int,
            default=DEFAULT_SEED,
            help=f"RNG seed, for a reproducible assignment (default: {DEFAULT_SEED}).",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=DEFAULT_DAYS,
            help="How many days back from now the fictional timestamps span "
            f"(default: {DEFAULT_DAYS}).",
        )
        parser.add_argument(
            "--only-missing",
            action="store_true",
            help="Only touch opinions that don't have a location yet, "
            "instead of reassigning every opinion's location and time.",
        )

    def handle(self, *args, **options):
        opinions = Opinion.objects.order_by("pk")
        if options["only_missing"]:
            opinions = opinions.filter(geo_coordinates__isnull=True)
        opinions = list(opinions.select_related("author"))
        if not opinions:
            self.stdout.write("No opinions to update.")
            return

        rng = random.Random(options["seed"])
        span_seconds = options["days"] * 86400
        earliest = timezone.now() - timedelta(days=options["days"])

        location_by_author = {}

        def location_for(opinion):
            # Anonymous opinions (author is None) have no shared identity to
            # group by, so each one is its own independent, still
            # deterministic (rng is already seeded) pick.
            key = opinion.author_id or f"anon-{opinion.pk}"
            if key not in location_by_author:
                location_by_author[key] = rng.choice(LOCATIONS)
            return location_by_author[key]

        for opinion in opinions:
            city = location_for(opinion)
            opinion.geo_coordinates = Point(city["lon"], city["lat"])
            opinion.timestamp = earliest + timedelta(
                seconds=rng.uniform(0, span_seconds)
            )

        Opinion.objects.bulk_update(
            opinions, ["geo_coordinates", "timestamp"], batch_size=200
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Assigned fictional geo/time data to {len(opinions)} opinion(s) "
                f"across {len(location_by_author)} author(s)/location(s)."
            )
        )
