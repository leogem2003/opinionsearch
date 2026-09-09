# Main structure

## Backend
### Databases
- Relational DB (use Django default)
    - Tables
        - User: username, uuid
        - Opinion: text, topic, User.uuid, VectorID
        - Argument: text, Opinion.pk
- Vector DB:
    - Opinions embeddings (VectorID) + timestamp + geo_coordinates
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
An user inputs some keywords and optionally filters on time and location.
The embedding parses the keywords.
The vector DB applies filters and searches the closest clusters.
The vector DB applies UMAP projection in a 2D space, returns vectorID, timestamp, geo_coordinates, projection coordinates, cluster_id.
The relational DB joins the vector IDs with the opinions, returns text, timestamp, geo_coordinates, projection coordinates, cluster_id.
