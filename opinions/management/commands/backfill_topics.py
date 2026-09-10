from django.core.management.base import BaseCommand

from opinions.models import Opinion
from opinions.topic_classification import assign_topics


class Command(BaseCommand):
    help = "Assign predefined topics to embedded public opinions. Use --all after changing the catalogue."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Replace existing topic assignments using the current catalogue.",
        )

    def handle(self, *args, **options):
        opinions = Opinion.objects.filter(embedding__isnull=False)
        if not options["all"]:
            opinions = opinions.filter(topic_analysis={})
        count = 0
        for opinion in opinions.order_by("pk").iterator(chunk_size=100):
            count += assign_topics(opinion)
        self.stdout.write(self.style.SUCCESS(f"Classified {count} opinion(s)."))
