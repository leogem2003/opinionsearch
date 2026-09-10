# Main structure

## Backend
### Databases
Postgre with pgvector for vector DB, postGIS for geo data.
- Relational DB:
    - Tables
        - User: username, uuid.
        - Contribution: UUID, original text, creation time, declared visibility, unique submission-key hash, private access receipt.
        - Opinion: text, optional topic and author, embedding, timestamp, geo_coordinates, optional unique link to the original Contribution. Anonymous submissions do not create a fictitious user.
        - Argument: text, Opinion.pk
- pgvector extension:
    - Opinions embeddings (VectorID) 
    - Clusters

### Inference
- Embedding (BGE-M3)
- Sentiment (nlptown multilingual 1–5 score)
- UMAP projection on the Django search page; persistent vector clustering is deferred.

## UX
### Describing an issue — implemented
The frontend states that text will be publicly searchable and sends the original text, a random submission key and `publication: "public"` to `POST /api/v1/contributions/`.
The backend commits the original Contribution, then calls the existing BGE-M3 embedding and sentiment functions outside the write transaction and stores a linked Opinion. It returns the stable source ID and private receipt after indexing succeeds. Model failures retain the original source for retry.
Repeating the same key, text and visibility recovers the same records. Unique keys protect both source creation and the source-to-opinion link against concurrent retries. Failed embedding leaves the source intact and can be retried with the original request.
The saved-text page uses `GET /api/v1/contributions/{id}/` with the receipt in the Authorization header.
Search reads the generated Opinion through `/api/v1/opinions/` and includes `contributionId` for provenance. No account, LLM call, topic assignment or opinion interpretation is needed for this whole-input representation.
Earlier private inputs retain their visibility; a request that omits publication remains private and is not embedded. Publishing an existing private input requires an explicit decision, not a schema migration or retry side effect.
Inference runs synchronously outside the write transaction for the showcase. `opinions/pipeline.py` isolates the repeatable indexing step so a durable worker can run it later without changing original source IDs. Automatic processing status, queues and multi-statement extraction remain future work.
Receipts remain usable while the source exists; closing the browser tab does not delete server storage.
The [intake contract](opinionsearch/frontend/API_CONTRACT.md) defines validation, errors, privacy and retry behaviour. Future derived records can reference the contribution ID without changing the original text.

### Adding an opinion
A user publishes an opinion.
An opinion can have some arguments.
The opinion text is fed into the embedding.
The opinion embedding is stored in the vector DB.
Clusters are updated.
The vector ID is added to the opinion row.

### Searching for opinions
Both the React API and the Django page use the shared cosine-distance search in `opinions/search.py`. The React API caps results at 50 and includes the stored sentiment score. Its chart groups 1–2 as Negative, 3 as Neutral, and 4–5 as Positive, with missing scores kept separate. Selecting a group filters the original texts; these groups describe tone, not support for a topic. Counts cover returned opinions, not people or national opinion.

The Django page additionally provides a UMAP plot and sentiment histogram. The broader time/location-filtered read path below remains a design target:
An user inputs some keywords, maximum similarity distance [0,1] and optionally filters on time and location.
The embedder parses the keywords.
Filter for maximum similarity distance to keyword embedding and filters.
The vector extension applies UMAP projection in a 2D space, returns vectorID and projection coordinates.
The relational DB joins the vector IDs with the opinions, applies filters, and returns text, timestamp, geo_coordinates, projection coordinates.
