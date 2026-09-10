# Main structure

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
- Predefined civic topics: reuse each opinion’s BGE-M3 vector to match versioned descriptions; retain several strong matches or none. See [topic pipeline](opinionsearch/frontend/TOPIC_PIPELINE.md).
- Hierarchical vector clustering (EVōC) for topic discovery
- Cluster labelling from the member texts (class-based TF-IDF, plus a medoid
  exemplar quote): EVōC outputs cluster ids only, never words.
- UMAP projection on the Django search page; coordinates are not persisted.

## UX
### Describing an issue — implemented
The frontend states that text will be publicly searchable and sends the original text, a random submission key and `publication: "public"` to `POST /api/v1/contributions/`.
The backend commits the original Contribution, then calls the existing BGE-M3 embedding and sentiment functions and predefined-topic classifier outside the write transaction, then stores a linked Opinion. It returns the stable source ID and private receipt after indexing succeeds. Model failures retain the original source for retry.
Repeating the same key, text and visibility recovers the same records. Unique keys protect both source creation and the source-to-opinion link against concurrent retries. Failed embedding leaves the source intact and can be retried with the original request.
The saved-text page uses `GET /api/v1/contributions/{id}/` with the receipt in the Authorization header.
Search reads the generated Opinion through `/api/v1/opinions/` and includes `contributionId` for provenance. The prototype assigns broad topics from a fixed catalogue. No account, LLM call, stance extraction or reasoning analysis is required.
Earlier private inputs retain their visibility; a request that omits publication remains private and is not embedded. Publishing an existing private input requires an explicit decision, not a schema migration or retry side effect.
Inference runs synchronously outside the write transaction for the showcase. `opinions/pipeline.py` isolates the repeatable indexing step so a durable worker can run it later without changing original source IDs. Automatic processing status, queues and multi-statement extraction remain future work.
Receipts remain usable while the source exists; closing the browser tab does not delete server storage.
The [intake contract](opinionsearch/frontend/API_CONTRACT.md) defines validation, errors, privacy and retry behaviour. Future derived records can reference the contribution ID without changing the original text.

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
`GET /api/v1/topics/` lists the fixed catalogue with stored membership counts and latest contribution times. `GET /api/v1/opinions/?topic=housing` returns the newest 50 opinions assigned to that topic without running a model. A topic may contain overlapping opinions; totals are submissions, not unique people. The live React path is Home → Topics → Topic sentiment and original opinions. Example discussions remain separate.

### Searching for opinions
Both the React API and the Django page use the shared cosine-distance search in `opinions/search.py`. The React API caps results at 50 and includes the stored sentiment score. Its chart groups 1–2 as Negative, 3 as Neutral, and 4–5 as Positive, with missing scores kept separate. Selecting a group filters the original texts; these groups describe tone, not support for a topic. Counts cover returned opinions, not people or national opinion.

The Django page additionally provides a UMAP plot and sentiment histogram. The broader time/location-filtered read path below remains a design target:
An user inputs some keywords, maximum similarity distance [0,1] and optionally filters on time and location.
The embedder parses the keywords.
Filter for maximum similarity distance to keyword embedding and filters.
The vector extension applies UMAP projection in a 2D space, returns vectorID and projection coordinates.
The relational DB joins the vector IDs with the opinions, applies filters, and returns text, timestamp, geo_coordinates, projection coordinates, sentiment, and the opinion's topic at each layer of the hierarchy.
The user picks which layer of the topic hierarchy the results are grouped by: the narrowest discovered topics, or progressively broader ones.
