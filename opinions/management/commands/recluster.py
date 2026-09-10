"""Re-discover the topic hierarchy over every embedded opinion.

Clustering is a whole-corpus operation, so unlike embedding and sentiment it
can't happen in ``Opinion.save()`` -- a single new statement has no topic
until the corpus is clustered around it again. This command is how that
happens; run it after a batch of opinions has been published (or after
loading a fixture).
"""

from django.core.management.base import BaseCommand, CommandError

from opinions.clustering import (
    DEFAULT_MIN_CLUSTER_SIZE,
    DEFAULT_MIN_SAMPLES,
    DEFAULT_N_NEIGHBORS,
    NotEnoughOpinions,
    cluster_opinions,
)
from opinions.models import Cluster


class Command(BaseCommand):
    help = "Re-run EVōC clustering over all embedded opinions and store the topic hierarchy."

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-cluster-size",
            type=int,
            default=DEFAULT_MIN_CLUSTER_SIZE,
            help="Smallest group EVōC will call a cluster in the finest layer "
            f"(default: {DEFAULT_MIN_CLUSTER_SIZE}).",
        )
        parser.add_argument(
            "--n-neighbors",
            type=int,
            default=DEFAULT_N_NEIGHBORS,
            help=f"Neighbourhood size for EVōC's graph (default: {DEFAULT_N_NEIGHBORS}).",
        )
        parser.add_argument(
            "--min-samples",
            type=int,
            default=DEFAULT_MIN_SAMPLES,
            help="How conservative EVōC is about calling a point noise "
            f"(default: {DEFAULT_MIN_SAMPLES}).",
        )

    def handle(self, *args, **options):
        self.stdout.write("Clustering opinions with EVōC...")
        try:
            cluster_opinions(
                min_cluster_size=options["min_cluster_size"],
                n_neighbors=options["n_neighbors"],
                min_samples=options["min_samples"],
            )
        except NotEnoughOpinions as error:
            raise CommandError(str(error)) from error

        layers = (
            Cluster.objects.values_list("layer", flat=True).distinct().order_by("layer")
        )
        for layer in layers:
            clusters = Cluster.objects.filter(layer=layer).order_by("-size")
            self.stdout.write(
                f"\nlayer {layer}: {clusters.count()} cluster(s)"
                + ("  (finest)" if layer == 0 else "")
            )
            for cluster in clusters:
                self.stdout.write(
                    f"  [{cluster.size:>3}] {cluster.label or f'cluster {cluster.evoc_id}'}"
                )

        total = Cluster.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"\nStored {total} cluster(s) across {len(layers)} layer(s)."
            )
        )
