"""Add sample Arguments to existing Opinions, for demoing the arguments UI.

Arguments have no frontend anywhere in this project's real data sources (the
hand-written fixture, `load_senator_tweets`) -- this command exists purely so
`/users/<uuid>/` has something to show while developing/demoing it, the same
role `add_fictional_geo_time` plays for the map/date filters. No model call,
no network: each opinion deterministically gets 1-3 texts drawn from a small
fixed pool of generic argument templates, picked the same way given the same
`--seed` and the same corpus (same opinions in the same pk order), mirroring
`add_fictional_geo_time`'s reproducibility.
"""

import random

from django.core.management.base import BaseCommand

from opinions.models import Argument, Opinion

DEFAULT_SEED = 42

# Generic, opinion-agnostic argument templates -- deliberately bland rather
# than invented reasoning about any specific opinion's content, since this
# command has no model in the loop to generate anything opinion-specific.
ARGUMENT_TEMPLATES = [
    "This matters because it affects a large number of people directly.",
    "There is broad public support for addressing this issue.",
    "Ignoring this now will make it more costly to fix later.",
    "Similar approaches have worked elsewhere and could work here too.",
    "This is a matter of basic fairness.",
    "The current situation places an unequal burden on some groups.",
    "Acting on this sends a clear signal about our shared priorities.",
    "There is credible evidence pointing in this direction.",
    "This would make the system more transparent and accountable.",
    "Doing nothing is itself a choice, and not a neutral one.",
]

MIN_ARGUMENTS_PER_OPINION = 1
MAX_ARGUMENTS_PER_OPINION = 3


class Command(BaseCommand):
    help = (
        "Add sample Arguments to existing Opinions, reproducibly, so the "
        "'my opinions' page has something to demo. See the module docstring."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--seed",
            type=int,
            default=DEFAULT_SEED,
            help=f"RNG seed, for a reproducible assignment (default: {DEFAULT_SEED}).",
        )
        parser.add_argument(
            "--only-missing",
            action="store_true",
            help="Only touch opinions that have no arguments yet, instead of "
            "adding more to every opinion.",
        )

    def handle(self, *args, **options):
        opinions = Opinion.objects.order_by("pk")
        if options["only_missing"]:
            opinions = opinions.filter(arguments__isnull=True)
        opinions = list(opinions.distinct())
        if not opinions:
            self.stdout.write("No opinions to add arguments to.")
            return

        rng = random.Random(options["seed"])
        arguments = []
        for opinion in opinions:
            count = rng.randint(MIN_ARGUMENTS_PER_OPINION, MAX_ARGUMENTS_PER_OPINION)
            for text in rng.sample(ARGUMENT_TEMPLATES, count):
                arguments.append(Argument(text=text, opinion=opinion))

        Argument.objects.bulk_create(arguments, batch_size=200)
        self.stdout.write(
            self.style.SUCCESS(
                f"Added {len(arguments)} argument(s) across {len(opinions)} opinion(s)."
            )
        )
