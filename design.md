# Main structure

## Local startup

`docker compose up --build` runs the Django/PostgreSQL stack at `localhost:8000`.
Django serves the frontend directly as server-rendered HTML/CSS, with a little
framework-free JavaScript for minor interactivity (no separate Node process or
build step). This keeps prototype startup in one existing configuration file;
production hosting remains separate work.

## Backend
### Databases
Postgre with pgvector for vector DB, postGIS for geo data.
- Relational DB:
    - Tables
        - User: username, uuid.
        - Contribution: UUID, original text, creation time, declared visibility, unique submission-key hash, private access receipt.
        - Opinion: text, optional author, embedding, sentiment, timestamp, geo_coordinates, optional unique link to the original Contribution, indexed civic topic IDs and an inspectable classification record. Anonymous submissions do not create a fictitious user.
        - Argument: text, Opinion.pk
        - Cluster: layer, evoc_id, parent (self), label, centroid, size, exemplar (Opinion).
        - Opinion/Cluster membership: one cluster per hierarchy layer the opinion falls in.
- pgvector extension:
    - Opinions embeddings (VectorID)
    - Cluster centroids

Predefined civic categories are stored in `Opinion.topic_ids`. Separately,
EVōC discovers clusters from the opinion embeddings and stores memberships in
`Opinion.clusters`. No category-to-cluster mapping is inferred by this merge.
The clustering is hierarchical: several nested
resolutions exist at once, layer 0 being the narrowest, and an opinion can be
noise (in no cluster) at one layer while belonging to a broader one above it,
which is why membership is many-to-many rather than a single foreign key.

### Inference
- Embedding (BGE-M3)
- Sentiment (nlptown multilingual 1–5 score)
- Predefined civic topics: reuse each opinion’s BGE-M3 vector to match versioned descriptions; retain several strong matches or none.
- Hierarchical vector clustering (EVōC) for topic discovery
- Cluster labelling from the member texts (class-based TF-IDF, plus a medoid
  exemplar quote): EVōC outputs cluster ids only, never words.
- UMAP projection on the Django search page; coordinates are not persisted.

## UX
### Describing an issue — implemented
`GET /` renders the issue form (`opinions/home.html`) with a server-generated,
hidden submission key. Submitting it states that the text will be publicly
searchable and posts the text back to `/` alongside that key, always as
`publication: "public"`.
The view commits the original Contribution (`Contribution.objects.get_or_create`
keyed on the submission key's hash, so a resubmission after a failure reuses the
same row instead of duplicating it), then calls `opinions/pipeline.py`'s
`index_contribution()` — the existing BGE-M3 embedding and sentiment functions
and predefined-topic classifier, run outside the write transaction — and stores
a linked Opinion. On success it redirects to
`/contributions/<id>/?receipt=<access_token>`; the access token travels in the
URL rather than a cookie or client-side storage, since a server-rendered page
has no script-managed store to keep it in. Model failures retain the original
source and re-render the form (same hidden key, submitted text preserved) with
a retry message, so submitting again completes indexing without a duplicate row.
The saved-text page (`/contributions/<id>/?receipt=...`) looks the receipt up
the same way the old `Authorization: Bearer` header check did — comparing the
query parameter against the stored access token with `secrets.compare_digest` —
and renders the same "unavailable" response whether the id is unknown or the
receipt is missing/wrong, so neither leaks which case occurred.
Search reads the generated Opinion through `/topics/?q=...` and shows
`contributionId` for provenance. The prototype assigns broad topics from a fixed
catalogue. No account, LLM call, stance extraction or reasoning analysis is
required.
Earlier private inputs retain their visibility; a request that omits publication
remains private and is not embedded — the issue form itself has no visibility
control and always submits public text, so this only affects contributions
created before this form existed. Publishing an existing private input requires
an explicit decision, not a schema migration or retry side effect.
Inference runs synchronously outside the write transaction for the showcase.
`opinions/pipeline.py` isolates the repeatable indexing step so a durable worker
can run it later without changing original source IDs. Automatic processing
status, queues and multi-statement extraction remain future work.
Receipts remain usable while the source exists and the visitor keeps the saved
link; closing the browser tab does not delete server storage.

### Adding an opinion
A user publishes an opinion.
An opinion can have some arguments.
The opinion text is fed into the embedding.
The opinion embedding is stored in the vector DB.
The opinion text is also scored for sentiment.
The vector ID is added to the opinion row.
Predefined categories are assigned at submission time. Discovered clusters
are updated separately with `manage.py recluster`, a whole-corpus operation.
A new opinion has no discovered cluster memberships until that command runs.

### Browsing topics
`GET /topics/` lists the fixed catalogue with stored membership counts and
latest contribution times (idle, no query); `GET /topics/<id>/` shows one
topic's stored membership and sentiment breakdown, newest 50 opinions, without
running a model. A topic may contain overlapping opinions; totals are
submissions, not unique people. The live path is Home → Topics → Topic
sentiment and original opinions.

### Searching for opinions
`GET /topics/?q=...` (and the Django `/search/` page) both use the shared
cosine-distance search in `opinions/search.py`. `/topics/` caps results at 50
and includes the stored sentiment score. Its breakdown groups 1–2 as Negative,
3 as Neutral, and 4–5 as Positive, with missing scores kept separate. Selecting
a group filters the original texts (a small vanilla-JS enhancement — the full
list still renders without it); these groups describe tone, not support for a
topic. Counts cover returned opinions, not people or national opinion.

The Django page additionally provides a UMAP plot and sentiment histogram. The broader time/location-filtered read path below remains a design target:
An user inputs some keywords, maximum similarity distance [0,1] and optionally filters on time and location.
The embedder parses the keywords.
Filter for maximum similarity distance to keyword embedding and filters.
The vector extension applies UMAP projection in a 2D space, returns vectorID and projection coordinates.
The relational DB joins the vector IDs with the opinions, applies filters, and returns text, timestamp, geo_coordinates, projection coordinates, sentiment, and the opinion's topic at each layer of the hierarchy.
The user picks which layer of the topic hierarchy the results are grouped by: the narrowest discovered topics, or progressively broader ones.
