# Main structure

## Local startup

`docker compose up --build` runs the Django/PostgreSQL stack at `localhost:8000`.
prints the URL when no browser opener is available. `docker/app/serve.py` prepares
embedding, sentiment and topic classification in the serving process before
starting Django; failed preparation stops startup. Model downloads persist in a
Docker volume. 

## Backend
### Databases
Postgre with pgvector for vector DB, postGIS for geo data.
- Relational DB:
    - Tables
        - User: username, uuid, home_location (picked once at signup, on a map; copied onto each new Opinion this user publishes).
        - Opinion: text, optional author, embedding, sentiment, timestamp, geo_coordinates, indexed civic topic IDs and an inspectable classification record. Anonymous submissions do not create a fictitious user.
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
`GET /` renders the issue form (`opinions/home.html`). Submitting it states
that the text will be publicly searchable and posts the text back to `/`
(at most 2,000 characters; validation checks for blank input using stripped
text, but stores the original text with its spaces and line breaks
unchanged).

A browser identifies itself once, the first time it submits an opinion:
alongside the text, the form asks for a username and a location picked on an
OpenStreetMap/Leaflet map (`opinions/identity.py`, `opinions/submissions.py`).
That identity — a `User` row plus a signed, password-less cookie naming its
uuid — is remembered for every later visit from the same browser, so
subsequent submissions show only the text box and reuse the same author and
location automatically, no re-asking. Losing the cookie (a different
browser/device, or clearing it) starts a new, unrelated identity; there is no
account recovery.

`Opinion.objects.create(text=..., author=user, geo_coordinates=user.home_location)`
does the rest — `Opinion.save()` already computes the BGE-M3 embedding,
sentiment and predefined-topic classification and assigns provisional
clusters (see "Adding an opinion" below), so there is no separate indexing
step: a submission either fully succeeds as one Opinion row (and, the first
time, one User row) or nothing is written at all. Creating the `User` and the
`Opinion` happens inside one transaction for exactly that reason — a failed
embedding/sentiment/topic call can't leave a `User` behind with nothing to
show for it. Model failures re-render the form with the submitted text
preserved and a retry message. On success the response redirects to the
publishing user's own opinions page, `/users/<uuid>/`.

### Managing your own opinions — implemented
`GET /users/<uuid>/` (`opinions/users.py::user_opinions`) lists a user's
opinions publicly — text, predefined category, sentiment score, and their
arguments — for anyone. Only when the visiting browser's identity cookie
names that same `uuid` do edit controls render: inline per-opinion forms to
change an opinion's text, and to add or edit its arguments, all on this one
page. Every such POST re-checks ownership from the cookie server-side
(`opinions.identity.get_current_user`) regardless of what the page happened
to render, so a forged request for someone else's uuid is rejected (403)
rather than trusted because a button existed.

Editing an opinion's text calls `opinions/pipeline.py::reanalyze_opinion`,
which forces a fresh embedding/sentiment/predefined-topic pass — deliberately
bypassing `Opinion.save()`'s normal "only once, on creation" guard, since
here a full re-run is exactly what was asked for — then
`opinions.clustering.reassign_to_nearest_clusters`, which drops the opinion's
old cluster memberships (from its previous text) before re-running the
nearest-centroid assignment against the new embedding.

Every "by `<username>`" reference across the site (search results, topic
browsing, the click-to-open detail panel) links to that user's `/users/<uuid>/`
page.

### Adding an opinion
A user publishes an opinion.
An opinion can have some arguments.
The opinion text is fed into the embedding.
The opinion embedding is stored in the vector DB.
The opinion text is also scored for sentiment.
The vector ID is added to the opinion row.
Predefined categories are assigned at submission time. Discovered clusters
are updated separately with `manage.py recluster`, a whole-corpus operation:
a topic is a property of the corpus, so the hierarchy is rediscovered in
batch, not on every publish. In between batch runs, a new opinion is
provisionally assigned to the nearest existing cluster (by centroid
distance) in each layer, rather than left with no topic until the next full
run.

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
