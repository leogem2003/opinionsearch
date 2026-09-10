"""Prepare inference in the serving process before accepting requests."""

import django
from django.core.management import call_command


def main():
    django.setup()
    from opinions.embedding import embed_text
    from opinions.sentiment import score_text
    from opinions.topic_classification import classify_topics

    sample = "Public transport should be reliable."
    print(
        "==> Preparing embedding model (first startup may download weights)", flush=True
    )
    embedding = embed_text(sample)
    print("==> Preparing sentiment model", flush=True)
    score_text(sample)
    print("==> Preparing topic classifier", flush=True)
    classify_topics(sample, embedding)
    print("==> Models ready; starting website", flush=True)
    # Autoreload would start a new process and discard the prepared models.
    # This sample only warms inference; it is never saved as an opinion.
    call_command("runserver", "0.0.0.0:8000", use_reloader=False)


if __name__ == "__main__":
    main()
