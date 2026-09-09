# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Early stage. The database layer is built: PostgreSQL with PostGIS and pgvector is wired up, the models from `design.md` exist in the `opinions` app, and migrations are applied. Publishing an opinion now generates its embedding (`opinions/embedding.py`, BGE-M3 via FlagEmbedding). There are no views, URLs, or templates yet, no tests, and no clustering/search code — `design.md` is still the specification being built toward, so read it before adding features and keep it in sync when the design changes.

## Commands

Dependencies are managed with `uv` (see `uv.lock`); `flake.nix` provides a Nix devShell with `python3` + `uv` and sets `UV_PYTHON_PREFERENCE=system`.

```bash
uv sync                                   # install deps (incl. dev group)
uv run python manage.py runserver         # dev server
uv run python manage.py makemigrations    # after model changes
uv run python manage.py migrate           # apply migrations
uv run python manage.py createsuperuser   # for /admin
uv run black .                            # format
```

Local admin login is `admin` / `admin` — development only; never carry it into a deployed instance.

Database connection settings are read from a gitignored `.env` at the repo root (`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`), loaded via `python-dotenv` in `settings.py`. To provision a database from scratch:

```bash
sudo -u postgres createdb -O opinionsearch opinionsearch
sudo -u postgres psql -d opinionsearch -c "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS vector;"
```

GeoDjango needs the native GDAL and GEOS libraries present on the system in addition to the Python packages.

Tests: `pytest` and `pytest-django` are in the dev group, but no pytest configuration exists yet. Before the first test can run, add a `[tool.pytest.ini_options]` section to `pyproject.toml` with `DJANGO_SETTINGS_MODULE = "opinionsearch.settings"` (and typically `python_files = "test_*.py"`). Then:

```bash
uv run pytest                             # all tests
uv run pytest path/to/test_file.py::test_name   # a single test
```

## Architecture (per design.md)

Everything lives in **one PostgreSQL database**, extended rather than split: `pgvector` for embeddings and clusters, `PostGIS` for geo data. There is no separate vector service — "relational side" and "vector side" below are extensions of the same database, so a search is a single query path, not a cross-store round trip.

All of this lives in the `opinions` app (`opinions/models.py`):

- `User` — a plain model, per `design.md`: just `username` (unique) and a `uuid` public identifier, no password/email/permissions. It is **not** `AUTH_USER_MODEL` — logging into `/admin` goes through Django's separate, default `django.contrib.auth.models.User`. The two are unrelated; don't conflate "an app user who publishes opinions" with "someone who can log into the admin site."
- `Opinion` — `text`, `topic`, `timestamp` (`auto_now_add`), a nullable PostGIS `geo_coordinates` point, an FK to `User` **by `uuid`** (`to_field="uuid"`, column `user_uuid`) rather than by primary key, a nullable 1024-dim `embedding` (BGE-M3's dense width, `EMBEDDING_DIM`), and a nullable FK to `Cluster`. The embedding is null until computed. `timestamp` and `geo_coordinates` are the columns the search filters on, so they sit on the row being filtered. Carries an HNSW index using `vector_cosine_ops`, so similarity queries should use cosine distance.
- `Argument` — `text` plus an FK to `Opinion`.
- `Cluster` — `centroid` vector plus `updated_at`.

Opinion now holds both its text and embedding directly; there is no separate OpinionEmbedding model.

- **Write path** (publishing an opinion) — **implemented**: `Opinion.save()` (`opinions/models.py`) embeds `self.text` via `opinions/embedding.py` and stores the vector directly on the `Opinion` row, all before the row is written — so a plain `Opinion.objects.create(...)` already does the right thing, no separate call needed. It only runs once, on creation (`embedding is None`); editing an opinion's text afterward does not re-embed it. Clustering ("update clusters" in design.md) is not implemented — new opinions are created with `cluster=None`.
- **Read path** (search) — **not implemented**: embed the user's keywords → the vector extension matches that embedding to the top-K closest clusters and applies a UMAP projection into 2D, returning `(vectorID, projection_coords)` → the relational side joins on vector ID, **then** applies the time and location filters directly against `Opinion.timestamp` and `Opinion.geo_coordinates`, returning text, timestamp, geo_coordinates, projection coordinates, and cluster_id.

`opinions/embedding.py` wraps `FlagEmbedding.FlagAutoModel.from_finetuned("BAAI/bge-m3", ...)`. `get_embedder()` is `lru_cache`d so the (multi-GB) model loads once per process, lazily on first use — never at import time, so `manage.py check`/migrations/etc. stay fast. `embed_text()` calls `encode_corpus` (no query instruction — opinions are indexed documents, not search queries); the read path above is what will eventually use `encode_queries` and the `query_instruction_for_retrieval` already configured on the same embedder.

Note the filter ordering in the read path: top-K cluster selection happens *before* the time/location filters are applied, so a heavily filtered search can return well under K results. Preserve that order when implementing, and revisit it deliberately if recall becomes a problem rather than silently reordering.

The 2D projection coordinates exist to drive the client-side visualization of the opinion space, which is the product's core feature.

## Not yet wired up

- `python-dotenv` now loads `.env`, but only the database settings read from it. `SECRET_KEY` is still the hardcoded insecure default and `DEBUG = True`; move both to the environment before any deployment.
- `django-debug-toolbar` is installed but absent from `INSTALLED_APPS` and `MIDDLEWARE`.
- No clustering/UMAP library is in `pyproject.toml` yet, and there's no re-clustering step anywhere. `Opinion.cluster` is always `None` right now. The read path (search) is entirely unimplemented — the schema and the embedder are both ready for it.
- `opinions.User` has no signup/login flow of its own yet (it's not wired to Django auth at all); creating one is just `User.objects.create(username=...)` for now.

## Gotchas

- **Extensions are created inside the initial migration.** `opinions/migrations/0001_initial.py` runs `CreateExtension("postgis")` and `VectorExtension()` before the tables, so a fresh database — including the throwaway one pytest-django builds — sets itself up in one step. Keep those first in the operations list if you regenerate this migration.
- Creating those extensions normally requires database superuser rights. The `opinionsearch` role is not a superuser, so a test database created by that role may fail on `CreateExtension` — the main database already has both extensions installed by `postgres`.
- `opinions.User` is intentionally not `AUTH_USER_MODEL`. If that ever changes, note it's only safe to swap before the first migration touching it — changing it later means recreating the database (as happened once already in this project's history).
- **`Opinion.save()` calls into BGE-M3 synchronously**, so the first opinion created in a process pays the model's load time (weights are pulled from the Hugging Face Hub on first use and cached under `~/.cache/huggingface`; no `HF_TOKEN` is configured, so downloads run at the unauthenticated rate limit). There's no background task queue in this project, so every `runserver`/`pytest`/shell process that creates an opinion eats this cost once, in-request. Don't add a `pytest` test that creates an `Opinion` without being ready for a real (slow, network-dependent) model load, unless `opinions.embedding.get_embedder`/`embed_text` is mocked.
