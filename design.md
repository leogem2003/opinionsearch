# Main structure

## Backend
### Databases
Postgre with pgvector for vector DB, postGIS for geo data.
- Relational DB:
    - Tables
        - User: username, uuid.
        - Opinion: text, User.uuid, VectorID, timestamp, geo_coordinates, sentiment.
        - Argument: text, Opinion.pk
        - Cluster: layer, evoc_id, parent (self), label, centroid, size, exemplar (Opinion).
        - Opinion/Cluster membership: one cluster per hierarchy layer the opinion falls in.
- pgvector extension:
    - Opinions embeddings (VectorID)
    - Cluster centroids

Topics are **not** a field on an opinion. They are discovered by clustering the
embeddings (see Inference), so a topic is a Cluster row and an opinion's topic
is its membership of one. The clustering is hierarchical: several nested
resolutions exist at once, layer 0 being the narrowest, and an opinion can be
noise (in no cluster) at one layer while belonging to a broader one above it,
which is why membership is many-to-many rather than a single foreign key.

### Inference
- Embedding (BGE-M3)
- Sentiment scoring (nlptown/bert-base-multilingual-uncased-sentiment, 1-5 stars)
- Hierarchical vector clustering (EVōC) for topic discovery
- Cluster labelling from the member texts (class-based TF-IDF, plus a medoid
  exemplar quote): EVōC outputs cluster ids only, never words.

## UX
### Adding an opinion
A user publishes an opinion.
An opinion can have some arguments.
The opinion text is fed into the embedding.
The opinion embedding is stored in the vector DB.
The opinion text is also scored for sentiment.
The vector ID is added to the opinion row.
Clusters are updated. This is a whole-corpus operation, not a per-opinion one:
a topic is a property of the corpus, so the hierarchy is rediscovered in batch
and a new opinion has no topic until that runs again.

### Searching for opinions
An user inputs some keywords, maximum similarity distance [0,1] and optionally filters on time and location.
The embedder parses the keywords.
Filter for maximum similarity distance to keyword embedding and filters.
The vector extension applies UMAP projection in a 2D space, returns vectorID and projection coordinates.
The relational DB joins the vector IDs with the opinions, applies filters, and returns text, timestamp, geo_coordinates, projection coordinates, sentiment, and the opinion's topic at each layer of the hierarchy.
The user picks which layer of the topic hierarchy the results are grouped by: the narrowest discovered topics, or progressively broader ones.
