# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Early stage. The database layer is built: PostgreSQL with PostGIS and pgvector is wired up, the models from `design.md` exist in the `opinions` app, and migrations are applied. There are no views, URLs, templates, or tests yet, and no embedding or clustering code — `design.md` is still the specification being built toward, so read it before adding features and keep it in sync when the design changes.

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

- `User` — swappable auth model (`AUTH_USER_MODEL = "opinions.User"`), extending `AbstractUser` for `username` and auth plumbing, plus a `uuid` public identifier. Deliberately thin: the geo and time attributes belong to the opinion, not the author.
- `Opinion` — `text`, `topic`, `timestamp` (`auto_now_add`), a nullable PostGIS `geo_coordinates` point, an FK to `User` **by `uuid`** (`to_field="uuid"`, column `user_uuid`) rather than by primary key, and a nullable one-to-one `vector` to `OpinionEmbedding` (column `vector_id`). The vector is null until the embedding has been computed. `timestamp` and `geo_coordinates` are the columns the search filters on, so they sit on the row being filtered.
- `Argument` — `text` plus an FK to `Opinion`.
- `OpinionEmbedding` — the pgvector side: `vector_id` UUID primary key (the VectorID of `design.md`), a 1024-dim `embedding` (BGE-M3's dense width, `EMBEDDING_DIM`), and a nullable FK to `Cluster`. Carries an HNSW index using `vector_cosine_ops`, so similarity queries should use cosine distance to actually hit the index.
- `Cluster` — `centroid` vector plus `updated_at`.

`Opinion.vector` / `OpinionEmbedding.vector_id` is the join key between an opinion's text and its embedding.

- **Write path** (publishing an opinion): embed the opinion text (BGE-M3) → store the embedding → update clusters → write the vector ID back onto the `Opinion` row. An opinion may carry arguments.
- **Read path** (search): embed the user's keywords → the vector extension matches that embedding to the top-K closest clusters and applies a UMAP projection into 2D, returning `(vectorID, projection_coords)` → the relational side joins on vector ID, **then** applies the time and location filters directly against `Opinion.timestamp` and `Opinion.geo_coordinates`, returning text, timestamp, geo_coordinates, projection coordinates, and cluster_id.

Note the filter ordering in the read path: top-K cluster selection happens *before* the time/location filters are applied, so a heavily filtered search can return well under K results. Preserve that order when implementing, and revisit it deliberately if recall becomes a problem rather than silently reordering.

The 2D projection coordinates exist to drive the client-side visualization of the opinion space, which is the product's core feature.

## Not yet wired up

- `python-dotenv` now loads `.env`, but only the database settings read from it. `SECRET_KEY` is still the hardcoded insecure default and `DEBUG = True`; move both to the environment before any deployment.
- `django-debug-toolbar` is installed but absent from `INSTALLED_APPS` and `MIDDLEWARE`.
- No embedding model or clustering/UMAP library is in `pyproject.toml` yet. Both the write path (embed, cluster, write the vector ID back) and the read path (embed the query, top-K clusters, UMAP projection) are unimplemented — the schema is ready for them, the inference is not.
- The models are not registered in `opinions/admin.py`, so `/admin` currently shows only users and groups.

## Gotchas

- **Extensions are created inside the initial migration.** `opinions/migrations/0001_initial.py` runs `CreateExtension("postgis")` and `VectorExtension()` before the tables, so a fresh database — including the throwaway one pytest-django builds — sets itself up in one step. Keep those first in the operations list, and do not split them into an earlier separate migration: the swappable `AUTH_USER_MODEL` dependency resolves to the app's `__first__` migration, so if that is not the migration creating `User`, `admin.0001_initial` is ordered ahead of it and `migrate` fails with `Related model 'opinions.user' cannot be resolved`.
- Creating those extensions normally requires database superuser rights. The `opinionsearch` role is not a superuser, so a test database created by that role may fail on `CreateExtension` — the main database already has both extensions installed by `postgres`.
- `AUTH_USER_MODEL` is already swapped, and swapping it is only safe before the first migration. Changing the user model now means recreating the database.
