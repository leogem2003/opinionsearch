# Opinion search API

**Status:** minimal read integration, 10 September 2026.

`GET /api/v1/opinions/?query=affordable+housing&max_distance=0.5`

This JSON view and the Django `/search/` page share the same BGE-M3 retrieval function. The API reads fresh results without the HTML page’s cache or UMAP projection. It reads searchable `Opinion` records, including those generated from public issue submissions. It does not index input or expose private contributions itself.

- `query`: a topic or statement, trimmed; at most 2,000 Unicode code points, without NUL. With no topic filter, empty input returns an empty list without loading the model or querying the database. Invalid input returns 400.
- `max_distance`: optional cosine-distance threshold, default `0.5`. Finite values are clamped to `[0, 1]`; invalid or non-finite values use the default. The frontend uses the default.
- `topic`: optional catalogue ID (for example `housing`) or `unassigned`. Unknown IDs return 400. With a query, it filters stored topic membership before the limit; without a query it returns newest opinions by timestamp and ID, without model inference.
- Results are ordered by increasing cosine distance when searching and limited to 50. The limit bounds the response, not the number of opinions in the database.

```json
{
  "results": [
    {
      "id": "42",
      "contributionId": "6afd9045-2d94-4b9b-b728-526fd7d329b0",
      "text": "Housing costs make it difficult to live near my workplace.",
      "topic": "Housing",
      "distance": 0.2,
      "similarity": 0.8,
      "sentiment": 2,
      "sentimentLabel": "negative",
      "topics": [{ "id": "housing", "title": "Housing" }],
      "createdAt": "2026-09-10T12:00:00Z"
    }
  ],
  "limit": 50
}
```

The example is illustrative and omits the full `topicAnalysis` record, whose method, catalogue/model references, thresholds, input/vector hashes and per-topic scores are described in [TOPIC_PIPELINE.md](TOPIC_PIPELINE.md). `id` identifies the searchable opinion; `contributionId` links it to its original source, or is `null` for older/admin-created opinions without a source link. Neither is an access receipt. The legacy `topic` string remains for compatibility. `topics` contains predefined topic assignments; new inputs may match several or none. `createdAt` is the opinion creation timestamp. Topic-only browsing returns `null` for distance and similarity. Similarity is retrieval metadata, not agreement or a share of national opinion; the frontend displays original text and groups stored sentiment scores. Scores 1–2 map to **Negative**, 3 to **Neutral**, and 4–5 to **Positive**. A missing or invalid score remains **Not yet analysed**. `sentiment` is an integer from 1 to 5 or `null`; `sentimentLabel` is the backend description (`very negative`, `negative`, `neutral`, `positive`, `very positive`, or `unscored`). These are model estimates of tone, not topic-specific stance.

Selecting a chart group filters the original opinions. Each dot represents one returned opinion; its position is decorative, not a UMAP coordinate or a distance measurement. Counts cover these matches only, not unique people or the national population. The API returns no embedding vectors or projection coordinates.

Other methods return 405. Model/database failures remain server errors; the frontend shows a retry action and preserves the search. It never substitutes illustrative results after an API error. The contribution pipeline reuses this retrieval path and the same BGE-M3 embedding function; no second embedding model is introduced.

Use the same-origin `/api` proxy setup in [README.md](README.md). The [contribution contract](API_CONTRACT.md) describes submission, embedding, sentiment, provenance and retries. Successfully submitted public inputs are searchable and appear under assigned topics. `GET /api/v1/topics/` provides topic counts and titles; specific discussion visualisations still use explicitly labelled examples.
