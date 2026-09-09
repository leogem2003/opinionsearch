# Contribution intake API — frontend handoff

**Version:** v1 draft, 9 September 2026. **Status:** implemented by the frontend client; backend implementation pending.

This contract covers **save original text → receive a private receipt → read the saved text**. It does not require embeddings, LLM calls, discussion assignment, accounts or a processing queue. A successful response means the input has been stored, without implying interpretation or publication.

## Resource names

| Name | Meaning |
| --- | --- |
| **Contribution** | One original input. It can contain experiences, questions, positions and reasons. The form calls this “Describe an issue.” |
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
  "submissionKey": "1b69d7daedfc4bba883d9d8bdf3a1db1e663d812b5693ed1ae0194f677a08d63"
}
```

The key above is illustrative. Generate a fresh, unpredictable key for each new submission; do not reuse the example value.

| Field | Required | Contract |
| --- | --- | --- |
| `text` | Yes | Nonblank UTF-8 text, at most 2,000 Unicode code points. Reject NUL and invalid Unicode. Store the text exactly as received. The form trims outer whitespace before sending. |
| `submissionKey` | Yes | 32–128 characters from `A–Z`, `a–z`, `0–9`, `_`, `-`. The frontend generates 32 random bytes encoded as 64 hexadecimal characters and reuses the key when retrying the same text. |

The client sends only these fields. Topic, discussion, inferred position and publication decisions are not submission inputs. Bound request sizes; a 32 KiB JSON body limit accommodates this contract even when Unicode characters are JSON-escaped.

### Success

After durable storage, respond **201 Created** with JSON:

```json
{
  "id": "con_6afd90452d944b9bb728526fd7d329b0",
  "publication": "private",
  "accessToken": "<opaque private receipt>"
}
```

Also return:

```http
Location: /api/v1/contributions/con_6afd90452d944b9bb728526fd7d329b0/
Cache-Control: no-store
```

- `id` is a stable, opaque URL-safe string, 1–128 characters from `A–Z`, `a–z`, `0–9`, `_`, `-`. UUIDs with or without hyphens work. The `example-` prefix is reserved for bundled frontend fixtures.
- `publication` is `private` for this contract. The frontend has no publication action yet.
- `accessToken` is an opaque, unguessable private receipt issued by the backend. It is not an account token. Its generation, storage and verification are backend implementation choices.

Do not acknowledge a successful save before the contribution is stored. The frontend will show a saved confirmation immediately after success. A deferred processing status is unnecessary; there may be no processing pipeline at all yet.

### Retries and duplicate prevention

An identical `submissionKey` and identical text must return the **same contribution ID and usable receipt**, without creating another contribution. Return **200 OK** for that replay. Different text with an existing key returns **409 Conflict** and leaves the original unchanged.

This must survive concurrent retries and service restarts. It covers a lost response after a successful write. Keep the key confidential: replaying an identical request recovers its receipt. Identical text with a different key is a separate submission; this key is not a content-deduplication mechanism.

## 2. Read a saved contribution

```http
GET /api/v1/contributions/con_6afd90452d944b9bb728526fd7d329b0/
Authorization: Bearer <accessToken>
```

Return **200 OK**:

```json
{
  "id": "con_6afd90452d944b9bb728526fd7d329b0",
  "text": "Finding an affordable apartment has become difficult in my area.",
  "createdAt": "2026-09-09T10:15:30Z",
  "publication": "private"
}
```

`createdAt` is an ISO 8601 timestamp with an explicit time zone, preferably UTC. These are the only required read fields. Do not require placeholder interpretations, topic lists, model settings or processing statuses. Additional response fields may be added later; the frontend ignores fields it does not use.

Return `Cache-Control: no-store` and `Vary: Authorization`. Missing, invalid or unrelated receipts receive the same **404 Not Found** response as an unknown contribution. The contribution ID alone must not reveal the text. Do not return the access token in this response or expose a public list of these private inputs.

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
| 400 | `invalid_text`, `invalid_submission_key`, `invalid_json` | The input is invalid; nothing was created. |
| 404 | `not_found` | The source is unknown or the receipt does not grant access. |
| 409 | `submission_conflict` | The same key was used for different text. |
| 413 | `request_too_large` | The JSON body exceeds the accepted size. |
| 415 | `unsupported_media_type` | The request is not JSON. |
| 503 | `storage_unavailable` | Storage could not be confirmed; retry the same request and key. |

Do not echo private text or receipts in errors. An unsupported HTTP method should return 405. API routes should return JSON rather than the frontend HTML fallback.

The form preserves the input and key after a failed, timed-out or malformed response. Changing the input creates a new key. The read page offers retry after a service error. No editing, publication, withdrawal or analysis retry endpoint is required for this frontend revision.

## Backend acceptance scenarios

1. Create → read with the receipt: exact input and creation date are returned.
2. Read without the receipt, with the wrong receipt or another contribution's receipt: all return 404 without revealing the text.
3. Lose the first successful response, then retry: one stored contribution, the same ID and usable receipt.
4. Retry after a restart: the same behaviour persists.
5. Reuse a key with different text: 409, original unchanged.
6. Send empty, invalid or over-limit input: validation error, no contribution created.
7. Send 2,000 valid Unicode code points: accepted even when the JSON representation is longer.
8. Fail storage: no successful-save response is issued.

These are requirements for the backend team, not claims that backend tests currently pass.

## Frontend delivery and extension boundary

- This client belongs to OpinionSearch. Requests use same-origin `/api/v1/contributions/` paths. For local development, `OPINIONSEARCH_API_TARGET` explicitly selects the OpinionSearch backend; there is no default proxy target. Production hosting must route `/api` to that project's backend.
- [contributions.js](src/components/understanding/contributions.js) is the API boundary. It checks required success fields before opening a saved-text page.
- [LandingPage.jsx](src/components/LandingPage.jsx) submits the input; [ContributionPage.jsx](src/components/understanding/ContributionPage.jsx) reads it. The page route remains `/contributions/:id`.
- `npm run dev:demo` uses tab-local demonstration records with prominent demo labels. It implements no server, database, durable guarantee or security boundary. Production builds use the real HTTP API and never silently fall back to this demo.
- Topic/discussion examples remain separate fixtures. The public index stays empty until its own contract is implemented. The former session/report frontend has been removed; it creates no additional API requirements.

The later backend can add interpretations and discussion membership while keeping contribution IDs and original text stable. Specify editing/version history and publication transitions when those user actions are introduced. Embedding models, databases, queue technology and internal processing routes are deliberately left to the backend team.
