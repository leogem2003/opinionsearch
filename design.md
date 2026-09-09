# Main structure

## Backend
### Databases
Postgre with pgvector for vector DB, postGIS for geo data.
- Relational DB:
    - Tables
        - User: username, uuid.
        - Opinion: text, topic, User.uuid, VectorID, timestamp, geo_coordinates.
        - Argument: text, Opinion.pk
- pgvector extension:
    - Opinions embeddings (VectorID) 
    - Clusters

### Inference
- Embedding (BGE-M3)
- Vector clustering

## UX
### Adding an opinion
A user publishes an opinion.
An opinion can have some arguments.
The opinion text is fed into the embedding.
The opinion embedding is stored in the vector DB.
Clusters are updated.
The vector ID is added to the opinion row.

### Searching for opinions
An user inputs some keywords, maximum similarity distance [0,1] and optionally filters on time and location.
The embedder parses the keywords.
Filter for maximum similarity distance to keyword embedding and filters.
The vector extension applies UMAP projection in a 2D space, returns vectorID and projection coordinates.
The relational DB joins the vector IDs with the opinions, applies filters, and returns text, timestamp, geo_coordinates, projection coordinates.
