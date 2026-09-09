# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Opinionsearch is at the scaffold stage: `django-admin startproject` output plus a design document. There are no Django apps, models, views, templates, tests, or migrations yet. `design.md` is the specification being built toward — read it before adding features, and keep it in sync when the design changes.

## Commands

Dependencies are managed with `uv` (see `uv.lock`); `flake.nix` provides a Nix devShell with `python3` + `uv` and sets `UV_PYTHON_PREFERENCE=system`.

```bash
uv sync                                   # install deps (incl. dev group)
uv run python manage.py runserver         # dev server
uv run python manage.py makemigrations    # after model changes
uv run python manage.py migrate           # apply migrations (creates db.sqlite3)
uv run python manage.py createsuperuser   # for /admin
uv run black .                            # format
```

Tests: `pytest` and `pytest-django` are in the dev group, but no pytest configuration exists yet. Before the first test can run, add a `[tool.pytest.ini_options]` section to `pyproject.toml` with `DJANGO_SETTINGS_MODULE = "opinionsearch.settings"` (and typically `python_files = "test_*.py"`). Then:

```bash
uv run pytest                             # all tests
uv run pytest path/to/test_file.py::test_name   # a single test
```

## Architecture (per design.md)

Everything lives in **one PostgreSQL database**, extended rather than split: `pgvector` for embeddings and clusters, `PostGIS` for geo data. There is no separate vector service — "relational side" and "vector side" below are extensions of the same database, so a search is a single query path, not a cross-store round trip.

Tables:

- `User`: username, uuid
- `Opinion`: text, topic, User.uuid, **VectorID**, timestamp, geo_coordinates
- `Argument`: text, FK to Opinion

`pgvector` stores opinion embeddings keyed by `VectorID`, plus cluster assignments. `VectorID` on the `Opinion` row is the join key between the relational tables and the embeddings.

- **Write path** (publishing an opinion): embed the opinion text (BGE-M3) → store the embedding → update clusters → write the vector ID back onto the `Opinion` row. An opinion may carry arguments.
- **Read path** (search): embed the user's keywords → the vector extension matches that embedding to the top-K closest clusters and applies a UMAP projection into 2D, returning `(vectorID, projection_coords)` → the relational side joins on vector ID, **then** applies the time and location filters, returning text, timestamp, geo_coordinates, projection coordinates, and cluster_id.

Note the filter ordering in the read path: top-K cluster selection happens *before* the time/location filters are applied, so a heavily filtered search can return well under K results. Preserve that order when implementing, and revisit it deliberately if recall becomes a problem rather than silently reordering.

The 2D projection coordinates exist to drive the client-side visualization of the opinion space, which is the product's core feature.

## Not yet wired up

Several declared dependencies are unused, so don't assume they are active:

- `python-dotenv` is a runtime dependency but `settings.py` reads no `.env`. `SECRET_KEY` is still the hardcoded insecure default and `DEBUG = True`; move these to environment variables when adding real configuration.
- `django-debug-toolbar` is installed but absent from `INSTALLED_APPS` and `MIDDLEWARE`.
- `settings.py` still uses the `django.db.backends.sqlite3` engine against `db.sqlite3`, while the design calls for PostgreSQL. Switching over means a Postgres driver (e.g. `psycopg[binary]`), the `pgvector` and `PostGIS` extensions enabled on the database, and — for PostGIS — the `django.contrib.gis.db.backends.postgis` engine with `django.contrib.gis` in `INSTALLED_APPS`.
- No embedding model, pgvector client, or clustering/UMAP library is in `pyproject.toml` yet — those dependencies still need to be chosen and added.
