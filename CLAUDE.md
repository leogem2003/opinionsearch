# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Early stage. The database layer is built: PostgreSQL with PostGIS and pgvector is wired up, the models from `design.md` exist in the `opinions` app, and migrations are applied. Publishing an opinion now generates its embedding (`opinions/embedding.py`, BGE-M3 via FlagEmbedding). A first cut of search exists at `/search/` (see Architecture below) — plain Django template, no CSS, no clustering/projection yet. There's a real test suite (`opinions/tests/`) exercising it. `design.md` is still the specification being built toward, so read it before adding features and keep it in sync when the design changes.

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

## Architecture (per design.md)

Everything lives in **one PostgreSQL database**, extended rather than split: `pgvector` for embeddings and clusters, `PostGIS` for geo data. There is no separate vector service — "relational side" and "vector side" below are extensions of the same database, so a search is a single query path, not a cross-store round trip.

All of this lives in the `opinions` app (`opinions/models.py`):

- `User` — a plain model, per `design.md`: just `username` (unique) and a `uuid` public identifier, no password/email/permissions. It is **not** `AUTH_USER_MODEL` — logging into `/admin` goes through Django's separate, default `django.contrib.auth.models.User`. The two are unrelated; don't conflate "an app user who publishes opinions" with "someone who can log into the admin site."
- `Opinion` — `text`, `topic`, `timestamp` (`auto_now_add`), a nullable PostGIS `geo_coordinates` point, an FK to `User` **by `uuid`** (`to_field="uuid"`, column `user_uuid`) rather than by primary key, a nullable `embedding` vector field (1024-dim, `EMBEDDING_DIM`, BGE-M3's dense width), and a nullable FK to `Cluster`. `embedding` is null until it's been computed. `OpinionEmbedding` as a separate table (design.md's VectorID) was merged directly onto `Opinion`; the vector and the row it belongs to are the same row now, there's no separate join. Carries an HNSW index on `embedding` using `vector_cosine_ops`, so similarity queries should use cosine distance (`pgvector.django.CosineDistance`) to actually hit the index. `timestamp` and `geo_coordinates` are the columns the search filters on, so they sit on the row being filtered.
- `Argument` — `text` plus an FK to `Opinion`.
- `Cluster` — `centroid` vector plus `updated_at`.

- **Write path** (publishing an opinion) — **implemented**: `Opinion.save()` (`opinions/models.py`) embeds `self.text` via `opinions/embedding.py` before the row is written, so a plain `Opinion.objects.create(...)` already does the right thing, no separate call needed. It only runs once, on creation (`embedding is None`); editing an opinion's text afterward does not re-embed it. Clustering ("update clusters" in design.md) is not implemented — new embeddings are stored with `cluster=None`.
- **Read path** (search) — **partially implemented**, at `/search/` (`opinions/views.py::search`, `opinions/templates/opinions/search.html`): a user types a statement and picks a max cosine distance on a `[0, 1]` slider; the view embeds the statement, annotates every `Opinion` with `CosineDistance("embedding", query_embedding)`, filters to `distance <= max_distance` (plus a small epsilon — pgvector's float4 storage means a vector's distance from itself isn't always bit-exact 0), and orders by distance ascending. It returns text, topic, distance, and similarity (`1 - distance`) for each match. **Not yet implemented**: top-K/cluster-based candidate selection, the UMAP 2D projection, and the time/location filters design.md describes — this is a straight full-table cosine-distance scan with no clustering step in front of it yet.
- The search view currently embeds the query with `embed_text` (the same `encode_corpus` path used for stored opinions), not `encode_queries` — deliberately, so that searching for an opinion's exact text reproduces its exact embedding (distance 0), which `opinions/tests/test_search.py` relies on. Switching to `encode_queries`/`query_instruction_for_retrieval` for real semantic search later will break that exact-text-match guarantee unless the tests are adjusted for it too.

`opinions/embedding.py` wraps `FlagEmbedding.FlagAutoModel.from_finetuned("BAAI/bge-m3", ...)`. `get_embedder()` is `lru_cache`d so the (multi-GB) model loads once per process, lazily on first use — never at import time, so `manage.py check`/migrations/etc. stay fast. `embed_text()` calls `embed_texts()` for a single string; `embed_texts()` does the real `encode_corpus` call (no query instruction — opinions are indexed documents, not search queries) and is what to use whenever more than one text needs embedding at once (e.g. loading a fixture), since one batched encoder call is much cheaper than one call per text.

The 2D projection coordinates design.md describes exist to drive the client-side visualization of the opinion space, which is the product's core feature — the current `/search/` page is plain text output, not that visualization.

## Not yet wired up

- `python-dotenv` now loads `.env`, but only the database settings read from it. `SECRET_KEY` is still the hardcoded insecure default and `DEBUG = True`; move both to the environment before any deployment.
- `django-debug-toolbar` is installed but absent from `INSTALLED_APPS` and `MIDDLEWARE`.
- No clustering/UMAP library is in `pyproject.toml` yet, and there's no re-clustering step anywhere. `Opinion.cluster` is always `None` right now. `/search/` does a plain cosine-distance scan over every `Opinion` with no top-K/cluster prefilter and no 2D projection — see Architecture above.
- `/search/` doesn't filter on time or location at all yet; `Opinion.timestamp`/`geo_coordinates` aren't exposed on the page.
- `opinions.User` has no signup/login flow of its own yet (it's not wired to Django auth at all); creating one is just `User.objects.create(username=...)` for now.

## Gotchas

- **Extensions are created inside the initial migration.** `opinions/migrations/0001_initial.py` runs `CreateExtension("postgis")` and `VectorExtension()` before the tables, so a fresh database — including the throwaway one pytest-django builds — sets itself up in one step. Keep those first in the operations list if you regenerate this migration.
- Creating those extensions normally requires database superuser rights. The `opinionsearch` role is not a superuser, so a test database created by that role may fail on `CreateExtension` — the main database already has both extensions installed by `postgres`, and the test database needs the same one-time setup by hand (see Commands' Tests section) since `--reuse-db` is what lets `pytest` skip recreating it every run.
- `opinions.User` is intentionally not `AUTH_USER_MODEL`. If that ever changes, note it's only safe to swap before the first migration touching it — changing it later means recreating the database (as happened once already in this project's history).
- **`Opinion.save()` calls into BGE-M3 synchronously**, so the first opinion created in a process pays the model's load time (weights are pulled from the Hugging Face Hub on first use and cached under `~/.cache/huggingface`; no `HF_TOKEN` is configured, so downloads run at the unauthenticated rate limit). There's no background task queue in this project, so every `runserver`/`pytest`/shell process that creates an opinion eats this cost once, in-request. `opinions/tests/` deliberately does *not* mock the embedder — it pays this cost once per test session (see the `conftest.py` fixture) because the search tests need real, deterministic embeddings (identical text must embed identically) to assert on. Don't add an unrelated test that creates an `Opinion` without being ready for that same real model load, unless `opinions.embedding.get_embedder`/`embed_text`/`embed_texts` is mocked for it specifically.
- With `--reuse-db`, the test database's rows persist across separate `pytest` invocations. `opinions/tests/conftest.py` clears out `Opinion` (and re-`get_or_create`s `User`s) before loading the fixture every session specifically so repeated runs don't pile up duplicate opinions.
