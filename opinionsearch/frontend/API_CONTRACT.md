# Contribution intake API — frontend handoff

**Version:** v1 prototype, 10 September 2026. **Status:** implemented by the frontend client and OpinionSearch's Django backend. The separate [opinion search API](SEARCH_API.md) is also connected.

The website now uses **save original text → BGE-M3 embedding and sentiment score → linked searchable opinion → receipt**. This connects the existing embedding and sentiment models to submissions. Sentiment estimates tone; it does not establish agreement with a searched topic. It does not infer topics, positions or reasons, and needs no LLM, account or processing queue. Receipts remain private; text explicitly submitted as public becomes visible in opinion search.

## Resource names

| Name | Meaning |
| --- | --- |
| **Contribution** | One original input. It can contain experiences, questions, positions and reasons. The form calls this “Describe an issue.” |
| **Opinion** | The existing searchable text-and-embedding record. This prototype creates one per public contribution and links it to the original source. The name does not mean the input has been classified as a single opinion. |
| **Topic** | A broad category such as Immigration. Its browsing API is deferred. |
| **Discussion** | A specific subject within a topic. Its formation and browsing API are deferred. |
| **Position / reason** | Later interpretation of a contribution in a particular discussion. Not required during intake. |

Use plural resource paths under `/api/v1/`, with trailing slashes. These two routes concern the same contribution; there is no separate `/issues` resource in this contract.

## 1. Create a contribution

```http
POST /api/v1/contributions/
Content-Type: application/json
```

```json
{
  "text": "Finding an affordable apartment has become difficult in my area.",
  "submissionKey": "1b69d7daedfc4bba883d9d8bdf3a1db1e663d812b5693ed1ae0194f677a08d63",
  "publication": "public"
}
```

The key above is illustrative. Generate a fresh, unpredictable key for each new submission; do not reuse the example value.

| Field | Required | Contract |
| --- | --- | --- |
| `text` | Yes | Nonblank UTF-8 text, at most 2,000 Unicode code points. Reject NUL and invalid Unicode. Store the text exactly as received. The form trims outer whitespace before sending. |
| `submissionKey` | Yes | 32–128 characters from `A–Z`, `a–z`, `0–9`, `_`, `-`. The frontend generates 32 random bytes encoded as 64 hexadecimal characters and reuses the key when retrying the same text. |
| `publication` | Sent by the current form | `public` sends the contribution through embedding and search. Omitted or `private` preserves the previous private-storage behaviour for older clients. No existing private submission is automatically published. |

The form states that submitted text will be publicly searchable and sends `publication: "public"`. Topic, discussion and inferred position remain backend concerns. A 32 KiB JSON body limit accommodates this contract even when Unicode characters are JSON-escaped.

### Success

After durable source storage and successful indexing of a public input, respond **201 Created** with JSON:

```json
{
  "id": "6afd9045-2d94-4b9b-b728-526fd7d329b0",
  "publication": "public",
  "searchable": true,
  "accessToken": "<opaque private receipt>"
}
```

Also return:

```http
Location: /api/v1/contributions/6afd9045-2d94-4b9b-b728-526fd7d329b0/
Cache-Control: no-store
```

- `id` is a stable, opaque URL-safe string, 1–128 characters from `A–Z`, `a–z`, `0–9`, `_`, `-`. UUIDs with or without hyphens work. The `example-` prefix is reserved for bundled frontend fixtures.
- `publication` records the requested visibility: `public` or `private`.
- `searchable` is `true` after the linked embedding record is stored. Private submissions return `false`. The current form requires `true` before showing successful completion.
- `accessToken` is an opaque, unguessable private receipt issued by the backend. It is not an account token. Its generation, storage and verification are backend implementation choices.

The original source is committed before inference, so either model failing does not lose the text. The synchronous prototype returns success only when public input is indexed; failed embedding or sentiment inference returns 503 and retrying the same request resumes this step. The frontend allows up to 120 seconds for submission because the first model load can be slow. Other API calls retain their 20-second timeout.

### Retries and duplicate prevention

An identical `submissionKey`, text and visibility return the **same contribution ID and usable receipt**, without creating another contribution or opinion. Return **200 OK** for that replay. Different text or visibility with an existing key returns **409 Conflict** and leaves the original unchanged. An already indexed contribution does not run either model again on replay.

This must survive concurrent retries and service restarts. It covers a lost response after a successful write. Keep the key confidential: replaying an identical request recovers its receipt. Identical text with a different key is a separate submission; this key is not a content-deduplication mechanism.

The prototype keeps the receipt and retry record for as long as the contribution exists, with no automatic expiry. Closing the browser tab can lose the local receipt; it does not delete the server's stored text.

## 2. Read a saved contribution

```http
GET /api/v1/contributions/6afd9045-2d94-4b9b-b728-526fd7d329b0/
Authorization: Bearer <accessToken>
```

Return **200 OK**:

```json
{
  "id": "6afd9045-2d94-4b9b-b728-526fd7d329b0",
  "text": "Finding an affordable apartment has become difficult in my area.",
  "createdAt": "2026-09-09T10:15:30Z",
  "publication": "public",
  "searchable": true
}
```

`createdAt` is an ISO 8601 timestamp with an explicit time zone, preferably UTC. `searchable` reflects whether the public source has a stored embedding record. A source retained after failed indexing returns `false`; there is no automatic background retry yet. Additional response fields may be added later; no placeholder interpretations or topic lists are required.

Return `Cache-Control: no-store` and `Vary: Authorization`. Missing, invalid or unrelated receipts receive the same **404 Not Found** response as an unknown contribution. This saved-source endpoint always requires a receipt and never returns that receipt. Public text is also available through the separate search API; receipt protection does not make that text private. Private submissions remain excluded from search.

The frontend keeps receipts in tab-scoped session storage, with history state as a fallback. Neither receipts nor submission keys appear in URLs. Requests do not use session-cookie authentication. If the backend later introduces cookie-based owner authentication, coordinate the corresponding frontend and CSRF contract before changing it.

## Errors

All API errors should use JSON:

```json
{
  "error": {
    "code": "invalid_text",
    "message": "Describe an issue using 1 to 2,000 characters."
  }
}
```

| HTTP status | Example code | Meaning |
| --- | --- | --- |
| 400 | `invalid_text`, `invalid_submission_key`, `invalid_publication`, `invalid_json` | The input is invalid; nothing was created. |
| 404 | `not_found` | The source is unknown or the receipt does not grant access. |
| 405 | `method_not_allowed` | Use the method named in the `Allow` header. |
| 409 | `submission_conflict` | The same key was used for different text or visibility. |
| 413 | `request_too_large` | The JSON body exceeds the accepted size. |
| 415 | `unsupported_media_type` | The request is not JSON. |
| 503 | `storage_unavailable` | Storage could not be confirmed; retry the same request and key. |
| 503 | `embedding_unavailable` | The original text is saved, but embedding failed. Retry the same request and key to finish indexing. |
| 503 | `sentiment_unavailable` | The original text is saved, but sentiment scoring failed. Retry the same request and key to finish indexing. |

Do not echo private text or receipts in errors. An unsupported HTTP method should return 405. API routes should return JSON rather than the frontend HTML fallback.

The form preserves the input and key after a failed, timed-out or malformed response. Changing the input creates a new key. The read page offers retry after a service error. Editing, visibility changes and withdrawal are not exposed. Retrying the original POST is sufficient to retry inference in this prototype.

## Backend acceptance scenarios

1. Create → read with the receipt: exact input and creation date are returned.
2. Read without the receipt, with the wrong receipt or another contribution's receipt: all return 404 without revealing the text.
3. Lose the first successful response, then retry: one stored contribution, the same ID and usable receipt.
4. Retry after a restart: the same behaviour persists.
5. Reuse a key with different text or visibility: 409, original unchanged.
6. Send empty, invalid or over-limit input: validation error, no contribution created.
7. Send 2,000 valid Unicode code points: accepted even when the JSON representation is longer.
8. Fail storage: no successful-save response is issued.
9. Fail embedding or sentiment scoring: retain the source, return 503, and allow retry without duplicate sources or search records.
10. Submit “i like coffee” publicly: the existing BGE-M3 search finds it for “coffee” and includes its original contribution ID.
11. Submit through a legacy private client: no embedding or search record is created, including after retries.

The PostgreSQL tests in [test_contributions.py](../../opinions/tests/test_contributions.py) cover the API, concurrency and failure recovery with fixed embedding and sentiment outputs. [test_search.py](../../opinions/tests/test_search.py) additionally checks the coffee submission through the real BGE-M3 and sentiment models. A live service restart remains a separate integration check.

## Current backend implementation

[contributions.py](../../opinions/contributions.py) handles both routes. The [Contribution model](../../opinions/models.py) stores a UUID, original text, creation time, visibility, a unique SHA-256 hash of the submission key, and a random 256-bit access receipt in PostgreSQL. Migration `0003_contribution` creates the source table; `0004_contribution_search` adds visibility and the unique source link on `Opinion`. Existing contributions retain private visibility. Main’s `0003_opinion_sentiment` adds the nullable score, and generated migration `0005_merge_0003_opinion_sentiment_0004_contribution_search` joins the two histories without rewriting applied migrations. Run `backfill_sentiment` after migrating to score existing public opinions; this does not publish private contributions.

The receipt itself is stored as a secret in the private table so identical retries can recover it after a lost response or restart. It is not a receipt hash or encrypted field. Database access and backups therefore include these credentials as well as the original text. Reads compare receipts in constant time. Neither read responses nor error messages include credentials, and these handlers do not log request bodies or authorization headers.

A database uniqueness constraint resolves source retries. For public input, [index_contribution](../../opinions/pipeline.py) calls the existing `embed_text()` and `score_text()` functions outside the database write transaction, then creates an `Opinion` with the original text, vector and sentiment score. A unique `Opinion.contribution` link prevents duplicate search records. Simultaneous requests may compute model outputs more than once, but store one opinion. Anonymous input has no invented author, and its topic is blank until a classification step exists. Search exposes `contributionId` for provenance, never receipts or submission keys.

For higher throughput, move this repeatable indexing function into a durable background worker and add explicit processing status/retry scheduling. Do not start detached request threads or move inference into a database migration. The current whole-input, one-to-one representation is intentionally limited; later statement extraction can add multiple derived records without replacing the original source or its ID.

## Frontend delivery and extension boundary

- This client belongs to OpinionSearch. Requests use same-origin `/api/v1/contributions/` paths. For local development, `OPINIONSEARCH_API_TARGET` explicitly selects the OpinionSearch backend; there is no default proxy target. Production hosting must route `/api` to that project's backend.
- [contributions.js](src/components/understanding/contributions.js) is the API boundary. It checks required success fields before opening a saved-text page.
- [LandingPage.jsx](src/components/LandingPage.jsx) submits the input; [ContributionPage.jsx](src/components/understanding/ContributionPage.jsx) reads it. The page route remains `/contributions/:id`.
- `npm run dev:demo` uses tab-local demonstration records with prominent demo labels. It implements no server, database, durable guarantee or security boundary. Production builds use the real HTTP API and never silently fall back to this demo.
- Topic/discussion examples remain separate fixtures. Public exploration can search existing backend opinions through [SEARCH_API.md](SEARCH_API.md); organised discussions and position analysis remain deferred. The former session/report frontend has been removed; it creates no additional API requirements.

The later backend can add interpretations and discussion membership while keeping contribution IDs and original text stable. Specify editing/version history and publication transitions when those user actions are introduced. Embedding models, databases, queue technology and internal processing routes are deliberately left to the backend team.
