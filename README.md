# Opinionsearch

## Run the website

Install and start Docker with Compose support (Docker Desktop includes both).
From the repository root, run:

```bash
docker compose up --build
```

Once the healthcheck passes, open **[http://localhost:8000](http://localhost:8000)**.
This starts the database, applies migrations and starts Django, which serves the
whole website (issue form, topic search/browse, saved-contribution pages) directly
as server-rendered HTML — no separate frontend process, Node or `.env` setup is
needed. The first build downloads sizeable dependencies, and the first search or
submission also downloads model weights.

Press **Ctrl+C** to stop. Run the same command to start again. Database contents
and model downloads persist in Docker volumes; `docker compose down` also keeps
them. If port 8000 is occupied, stop the previous server first.

This is a **local development/showcase setup**, bound to localhost. Django admin
is at [http://localhost:8000/admin/](http://localhost:8000/admin/) with the existing
development login `admin` / `admin`.

## What it includes

- Submit an issue and search the original opinions with BGE-M3 embeddings.
- Browse predefined civic topics and positive/negative/neutral sentiment.
- Discover hierarchical clusters with EVōC and inspect them on the Django
  [search page](http://localhost:8000/search/).

After loading a corpus, run `docker compose run --rm web uv run python manage.py recluster`
to refresh discovered clusters.

## Develop without Docker

The backend needs Python with `uv`, GDAL/GEOS/PROJ, and PostgreSQL with PostGIS
and pgvector. See [flake.nix](flake.nix) for the native environment and database
setup. Apply migrations with `uv run python manage.py migrate`, then start Django
with `uv run python manage.py runserver` and open
[http://localhost:8000](http://localhost:8000) — the frontend is served by the
same process, so there is nothing else to start.

## Tests

Everyday checks use fixed model outputs; they still exercise the PostgreSQL
database and API. Real-model checks live in one opt-in integration folder.

```text
opinions/tests/
├── test_frontend.py     # submission, receipts, retries and search contracts
├── test_topics.py       # topic decisions, browsing and backfill
├── test_admin.py        # admin field protections
├── integration/
│   ├── test_search.py   # retrieval and submission with real models
│   ├── test_clustering.py
│   └── conftest.py      # expensive sample-corpus setup, only for this group
├── fixtures/           # shared sample opinions
└── utils.py            # fixture loader, also used by the notebook
```

From the repository root:

```bash
docker compose run --rm --entrypoint uv web run pytest                 # everyday checks
docker compose run --rm --entrypoint uv web run pytest -m integration  # real models
```

The entrypoint override runs pytest directly without the web startup's migrations
or admin creation. Docker starts the database dependency; tests use
`test_opinionsearch`, separate from the application database. Rebuild the web
image after changing tests (`docker compose build web`).

In the local development environment, use `uv run pytest` or
`uv run pytest -m integration`. To run everything, use `uv run pytest -m ''`.
The default marker selection follows [pytest's standard configuration](https://docs.pytest.org/en/stable/example/simple.html#how-to-change-command-line-options-defaults).
Real-model checks may download model weights on their first run; they are not
needed for ordinary frontend changes.

## Notebooks
[`notebooks/umap_projection.ipynb`](notebooks/umap_projection.ipynb) prototypes the 2D UMAP
projection that the opinion-space visualization will be drawn from: it loads the sample
opinions into the **development** database, runs the same query `/search/` runs
(`opinions.search.search_opinions`, with the query text and the distance slider as its two
knobs), and projects the matched embeddings.

```bash
uv run jupyter lab
```

## Limitations
1. Since this is a website, it is centralized and controlled by a single entity
2. There is currently no bot protection implemented to prevent inauthentic behavior
3. Language always is ambiguous to some degree
4. The embeddings can also pick up sentiment, topics might also include sentiment, e.g. "I hate cars" close to "I hate cheese", even though they're unrelated.
## License
See [LICENSE.txt](LICENSE.txt)


## Acknowledgement
#### Inspirations: 
- [github.com/Carbon-copy-PS/murmi](https://github.com/Carbon-copy-PS/murmi)
- Lectures by *Herr Prof. Dr Helbing Dirk* and many others from the course *Hacking Democracy: Co-Creating Innovative Tools for Participatory Politics HS2026* at ETHZ Zurich
- [pol.is](https://pol.is/) as inspiration

### Developers
- [@leogem2003](https://github.com/leogem2003), architecture design design, prompt engineering, programming
- [@ttlns](https://github.com/leogem2003), code review, testing, bugfix
- [@galtendorfer][https://github.com/galtendorfer] Initial frontent draft, presentation
