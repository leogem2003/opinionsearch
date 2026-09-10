# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Early stage. The database layer is built: PostgreSQL with PostGIS and pgvector is wired up, the models from `design.md` exist in the `opinions` app, and migrations are applied. Publishing an opinion now generates its embedding (`opinions/embedding.py`, BGE-M3 via FlagEmbedding). A first cut of search exists at `/search/` (see Architecture below) — plain Django template, no CSS, no clustering yet; the 2D projection is being prototyped in `notebooks/umap_projection.ipynb`, not in the app. There's a real test suite (`opinions/tests/`) exercising it. A Docker Compose setup (`docker-compose.yml`, `docker/`) ships this same state as containers for local use — see Commands below. `design.md` is still the specification being built toward, so read it before adding features and keep it in sync when the design changes.

## Commands

Dependencies are managed with `uv` (see `uv.lock`); `flake.nix` provides a Nix devShell with `python3` + `uv` and sets `UV_PYTHON_PREFERENCE=system`.

```bash
uv sync                                   # install deps (incl. dev group)
uv run python manage.py runserver         # dev server
uv run python manage.py makemigrations    # after model changes
uv run python manage.py migrate           # apply migrations
uv run python manage.py createsuperuser   # for /admin
uv run black .                            # format
uv run jupyter lab                        # notebooks/ (UMAP projection experiment)
```

Local admin login is `admin` / `admin` — development only; never carry it into a deployed instance.

Database connection settings are read from a gitignored `.env` at the repo root (`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`), loaded via `python-dotenv` in `settings.py`. To provision a database from scratch:

```bash
sudo -u postgres createdb -O opinionsearch opinionsearch
sudo -u postgres psql -d opinionsearch -c "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS vector;"
```

GeoDjango needs the native GDAL and GEOS libraries present on the system in addition to the Python packages.

Tests: `pytest` and `pytest-django` are in the dev group, configured in `pyproject.toml` (`[tool.pytest.ini_options]`). `addopts = "--reuse-db"` is set there because the `opinionsearch` role can't `CREATE EXTENSION` on a database Django builds from scratch (see Gotchas) — so the test database is created once, by hand, the same way as the main one:

```bash
sudo -u postgres createdb -O opinionsearch test_opinionsearch
sudo -u postgres psql -d test_opinionsearch -c "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS vector;"
```

After that, `--reuse-db` keeps reusing it. Pass `--create-db` (or drop and redo the two commands above) when migrations change and the schema needs rebuilding. Then:

```bash
uv run pytest                             # all tests
uv run pytest path/to/test_file.py::test_name   # a single test
```

`opinions/tests/` (a package, not a single `tests.py`) has a session-scoped `conftest.py` fixture that loads `opinions/tests/fixtures/sample_opinions.json` — a small set of users/topics/statements — via `opinions.tests.utils.load_opinions_fixture`, once per test run, batching every statement into a single BGE-M3 call. See the `Opinion.save()` gotcha below: this genuinely loads the model and runs real inference, it isn't mocked.

`docker-compose.yml` and `docker/` (`docker/db`, `docker/app`) ship the app and a Postgres+PostGIS+pgvector database as containers, so the whole stack can run without installing Nix/uv/Postgres locally — see README's Docker section for usage. Both images build their own Nix environment rather than reusing `flake.nix` directly (its devShell isn't exposed as a flake output to import elsewhere), but pin the same nixpkgs commit as `flake.lock` and install the same packages as the devShell (`postgresql.withPackages [ postgis pgvector ]`, `python3`/`uv`/`gdal`/`geos`/`proj`) — if `flake.lock` is ever updated, update `NIXPKGS_REV` in both Dockerfiles to match by hand. `docker/db`'s entrypoint bootstraps its Postgres superuser role under the app's own name (mirroring flake.nix's `createuser -s "$PGDATABASE"`) and creates *both* `opinionsearch` and `test_opinionsearch` with the extensions already installed, so the non-superuser gotcha below doesn't apply inside Docker.

## Architecture (per design.md)

Everything lives in **one PostgreSQL database**, extended rather than split: `pgvector` for embeddings and clusters, `PostGIS` for geo data. There is no separate vector service — "relational side" and "vector side" below are extensions of the same database, so a search is a single query path, not a cross-store round trip.

All of this lives in the `opinions` app (`opinions/models.py`):

- `User` — a plain model, per `design.md`: just `username` (unique) and a `uuid` public identifier, no password/email/permissions. It is **not** `AUTH_USER_MODEL` — logging into `/admin` goes through Django's separate, default `django.contrib.auth.models.User`. The two are unrelated; don't conflate "an app user who publishes opinions" with "someone who can log into the admin site."
- `Opinion` — `text`, `topic`, `timestamp` (`auto_now_add`), a nullable PostGIS `geo_coordinates` point, an FK to `User` **by `uuid`** (`to_field="uuid"`, column `user_uuid`) rather than by primary key, a nullable 1024-dim `embedding` (BGE-M3's dense width, `EMBEDDING_DIM`), and a nullable FK to `Cluster`. The embedding is null until computed. `timestamp` and `geo_coordinates` are the columns the search filters on, so they sit on the row being filtered. Carries an HNSW index using `vector_cosine_ops`, so similarity queries should use cosine distance.
- `Argument` — `text` plus an FK to `Opinion`.
- `Cluster` — `centroid` vector plus `updated_at`.

Opinion now holds both its text and embedding directly; there is no separate OpinionEmbedding model.

- **Write path** (publishing an opinion) — **implemented**: `Opinion.save()` (`opinions/models.py`) embeds `self.text` via `opinions/embedding.py` and stores the vector directly on the `Opinion` row, all before the row is written — so a plain `Opinion.objects.create(...)` already does the right thing, no separate call needed. It only runs once, on creation (`embedding is None`); editing an opinion's text afterward does not re-embed it. Clustering ("update clusters" in design.md) is not implemented — new opinions are created with `cluster=None`.
- **Read path** (search) — **partially implemented** at `/search/`. The query itself lives in `opinions/search.py`, deliberately apart from the view: `search_opinions(query, max_distance)` embeds the typed statement (with the same *document* embedder used for stored opinions, so searching an opinion's exact text reproduces its exact vector), annotates every `Opinion` with `CosineDistance("embedding", ...)`, filters to `distance <= max_distance + DISTANCE_EPSILON` and orders nearest-first, returning a lazy annotated `QuerySet`. `opinions/views.py` is then only request parsing and rendering. Anything needing the page's result set outside a request (the projection notebook below) imports `search_opinions` instead of rebuilding a look-alike query. **Still missing** from design.md's read path: the top-K closest-clusters lookup, the UMAP 2D projection, and the time/location filters against `Opinion.timestamp`/`geo_coordinates` — today's search is a full-table cosine scan with no clustering step in front of it.

`opinions/embedding.py` wraps `FlagEmbedding.FlagAutoModel.from_finetuned("BAAI/bge-m3", ...)`. `get_embedder()` is `lru_cache`d so the (multi-GB) model loads once per process, lazily on first use — never at import time, so `manage.py check`/migrations/etc. stay fast. `embed_text()` calls `embed_texts()` for a single string; `embed_texts()` does the real `encode_corpus` call (no query instruction — opinions are indexed documents, not search queries) and is what to use whenever more than one text needs embedding at once (e.g. loading a fixture), since one batched encoder call is much cheaper than one call per text. The read path above is what will eventually use `encode_queries` and the `query_instruction_for_retrieval` already configured on the same embedder.

The 2D projection coordinates design.md describes exist to drive the client-side visualization of the opinion space, which is the product's core feature — the current `/search/` page is plain text output, not that visualization.

`notebooks/umap_projection.ipynb` is where that projection is being tried out before it goes anywhere near the app: it boots Django against the **development** database, loads `opinions/tests/fixtures/sample_opinions.json` into it (only removing rows whose text is in the fixture, so hand-made dev opinions survive), calls `search_opinions` with a query and slider value, and runs `umap.UMAP(n_components=2, metric="cosine", ...)` over the matched embeddings — `metric="cosine"` to match `CosineDistance` and the `vector_cosine_ops` HNSW index rather than UMAP's `euclidean` default. It ends with a parameter sweep and a corpus-wide fit that highlights one search, since fitting UMAP per search would give coordinates that can't be compared between searches. Caveat recorded in the notebook: the fixture is 16 statements, below the size where `n_neighbors` is meaningful (it can't exceed `n_samples - 1`), so the parameters need re-tuning against a real corpus. `umap-learn`, `matplotlib` and `jupyterlab` are in the **dev** group only — nothing the app serves imports them yet.

## Not yet wired up

- `python-dotenv` now loads `.env`, but only the database settings read from it. `SECRET_KEY` is still the hardcoded insecure default and `DEBUG = True`; move both to the environment before any deployment.
- `django-debug-toolbar` is installed but absent from `INSTALLED_APPS` and `MIDDLEWARE`.
- No clustering step exists anywhere and `Opinion.cluster` is always `None`. `umap-learn` is installed (dev group) and exercised in `notebooks/umap_projection.ipynb`, but nothing persists projection coordinates — there's no field for them on `Opinion` yet, and the app itself never imports UMAP.
- `opinions.User` has no signup/login flow of its own yet (it's not wired to Django auth at all); creating one is just `User.objects.create(username=...)` for now.

## Gotchas

- **Extensions are created inside the initial migration, and migrations are otherwise generated, not hand-written.** `opinions/migrations/0001_initial.py` runs `CreateExtension("postgis")` and `VectorExtension()` before the tables, so a fresh database — including the throwaway one pytest-django builds — sets itself up in one step. Use the `makemigrations`/`migrate` workflow for schema changes rather than editing migration files directly; if a migration genuinely needs hand-editing, keep those two operations first.
- Creating those extensions normally requires database superuser rights. The `opinionsearch` role is not a superuser, so a test database created by that role may fail on `CreateExtension` — the main database already has both extensions installed by `postgres`, and the test database needs the same one-time setup by hand (see Commands' Tests section) since `--reuse-db` is what lets `pytest` skip recreating it every run. (The `docker/db` setup sidesteps this by making its bootstrap role a superuser instead, like `flake.nix`'s devShell does — see Commands.)
- **GDAL/GEOS auto-discovery doesn't work inside the Nix-built Docker images.** `ctypes.util.find_library()` (what GeoDjango uses to locate them by default) resolves names via `ldconfig`'s cache, which never sees Nix store paths — confirmed empirically while building `docker/app`. `settings.py` reads `GDAL_LIBRARY_PATH`/`GEOS_LIBRARY_PATH` from the environment (unset by default, so local/`flake.nix` dev is unaffected either way), and `docker/app/Dockerfile` points both at the Nix profile's merged `lib/` directory.
- `opinions.User` is intentionally not `AUTH_USER_MODEL`. If that ever changes, note it's only safe to swap before the first migration touching it — changing it later means recreating the database (as happened once already in this project's history).
- **`Opinion.save()` calls into BGE-M3 synchronously**, so the first opinion created in a process pays the model's load time (weights are pulled from the Hugging Face Hub on first use and cached under `~/.cache/huggingface`; no `HF_TOKEN` is configured, so downloads run at the unauthenticated rate limit). There's no background task queue in this project, so every `runserver`/`pytest`/shell process that creates an opinion eats this cost once, in-request. `opinions/tests/` deliberately does *not* mock the embedder — it pays this cost once per test session (see the `conftest.py` fixture) because the search tests need real, deterministic embeddings (identical text must embed identically) to assert on. Don't add an unrelated test that creates an `Opinion` without being ready for that same real model load, unless `opinions.embedding.get_embedder`/`embed_text`/`embed_texts` is mocked for it specifically.
- With `--reuse-db`, the test database's rows persist across separate `pytest` invocations. `opinions/tests/conftest.py` clears out `Opinion` (and re-`get_or_create`s `User`s) before loading the fixture every session specifically so repeated runs don't pile up duplicate opinions.
