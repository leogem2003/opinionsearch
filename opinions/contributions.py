"""Anonymous intake, embedding for public inputs, and private receipt handling."""

import hashlib
import json
import re
import secrets
import uuid

from django.db import DatabaseError, transaction
from django.http import JsonResponse, UnreadablePostError
from django.views.decorators.csrf import csrf_exempt

from .models import Contribution, Opinion
from .pipeline import EmbeddingUnavailable, SentimentUnavailable, index_contribution

MAX_BODY_BYTES = 32 * 1024
SUBMISSION_KEY = re.compile(r"[A-Za-z0-9_-]{32,128}")
RECEIPT = re.compile(r"[A-Za-z0-9_-]{43}")


def response(data, status=200, **headers):
    return JsonResponse(
        data,
        status=status,
        headers={"Cache-Control": "no-store", "Vary": "Authorization", **headers},
    )


def error(code, message, status, **headers):
    return response({"error": {"code": code, "message": message}}, status, **headers)


def unavailable():
    return error("storage_unavailable", "Storage is unavailable. Please retry.", 503)


def reject_constant(value):
    raise ValueError("Non-finite values are not JSON")


# This anonymous JSON endpoint does not authenticate with session cookies.
# Receipt-authenticated reads also ignore the logged-in Django admin user.
@csrf_exempt
def create_contribution(request):
    if request.method != "POST":
        return error(
            "method_not_allowed", "Use POST for this endpoint.", 405, Allow="POST"
        )
    if request.content_type != "application/json":
        return error("unsupported_media_type", "Send a JSON request.", 415)
    try:
        raw = request.read(MAX_BODY_BYTES + 1)
        if len(raw) > MAX_BODY_BYTES:
            return error("request_too_large", "The request is too large.", 413)
        data = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
    except (UnicodeError, ValueError, RecursionError, UnreadablePostError):
        return error("invalid_json", "Send a valid UTF-8 JSON object.", 400)
    if not isinstance(data, dict):
        return error("invalid_json", "Send a JSON object.", 400)

    text = data.get("text")
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text) > 2000
        or "\0" in text
    ):
        return error(
            "invalid_text", "Describe an issue using 1 to 2,000 characters.", 400
        )
    try:
        text.encode("utf-8")
    except UnicodeError:
        return error("invalid_text", "Use valid Unicode text.", 400)
    key = data.get("submissionKey")
    if not isinstance(key, str) or not SUBMISSION_KEY.fullmatch(key):
        return error("invalid_submission_key", "Use a valid submission key.", 400)
    # Older clients promised private storage. Only the updated form explicitly
    # requests public search; a replay must not change an earlier promise.
    publication = data.get("publication", "private")
    if publication not in ("private", "public"):
        return error("invalid_publication", "Choose public or private visibility.", 400)

    try:
        # The unique key and get_or_create handle racing retries. Exit the
        # transaction before returning a successful-save response.
        with transaction.atomic():
            contribution, created = Contribution.objects.get_or_create(
                submission_key_hash=hashlib.sha256(key.encode("ascii")).hexdigest(),
                defaults={
                    "text": text,
                    "publication": publication,
                    "access_token": secrets.token_urlsafe(32),
                },
            )
    except DatabaseError:
        return unavailable()
    if contribution.text != text or contribution.publication != publication:
        return error(
            "submission_conflict", "This key was used for a different submission.", 409
        )
    if publication == "public":
        try:
            index_contribution(contribution)
        except EmbeddingUnavailable:
            return error(
                "embedding_unavailable",
                "Your text is saved, but search preparation failed. Please retry.",
                503,
            )
        except SentimentUnavailable:
            return error(
                "sentiment_unavailable",
                "Your text is saved, but sentiment scoring failed. Please retry.",
                503,
            )
        except DatabaseError:
            return unavailable()
    return response(
        {
            "id": str(contribution.id),
            "publication": contribution.publication,
            "searchable": publication == "public",
            "accessToken": contribution.access_token,
        },
        201 if created else 200,
        Location=f"/api/v1/contributions/{contribution.id}/",
    )


@csrf_exempt
def get_contribution(request, contribution_id):
    if request.method != "GET":
        return error(
            "method_not_allowed", "Use GET for this endpoint.", 405, Allow="GET"
        )
    not_found = error("not_found", "Contribution unavailable.", 404)
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not RECEIPT.fullmatch(token):
        return not_found
    try:
        identifier = uuid.UUID(contribution_id)
    except ValueError:
        return not_found
    try:
        contribution = Contribution.objects.filter(pk=identifier).first()
        if contribution is None or not secrets.compare_digest(
            token, contribution.access_token
        ):
            return not_found
        searchable = (
            contribution.publication == "public"
            and Opinion.objects.filter(
                contribution=contribution, embedding__isnull=False
            ).exists()
        )
    except DatabaseError:
        return unavailable()
    return response(
        {
            "id": str(contribution.id),
            "text": contribution.text,
            "createdAt": contribution.created_at.isoformat(),
            "publication": contribution.publication,
            "searchable": searchable,
        }
    )
