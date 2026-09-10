# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Early stage. PostgreSQL with PostGIS and pgvector backs the `opinions` app. The feature branch incorporates main's UMAP projection and sentiment scoring. `/search/` retains the Django search page with UMAP and sentiment charts; `/api/v1/opinions/` feeds the React frontend with at most 50 fresh matches and stored sentiment scores. The issue form saves the original Contribution, computes BGE-M3 embedding and sentiment, matches predefined civic topics and stores one linked searchable Opinion. Receipt-protected reads and safe retries remain supported; older private inputs remain private. The React chart groups positive, negative and neutral tone, not topic-specific agreement. Read `design.md` before adding features and keep it in sync when the design changes.

## Commands

Dependencies are managed with `uv` (see `uv.lock`); `flake.nix` provides a Nix devShell with `python3` + `uv` and sets `UV_PYTHON_PREFERENCE=system`.

```bash
uv sync                                   # install deps (incl. dev group)
uv run python manage.py runserver         # dev server
uv run python manage.py makemigrations    # after model changes
uv run python manage.py migrate           # apply migrations
uv run python manage.py createsuperuser   # for /admin
uv run python manage.py backfill_sentiment  # score any Opinion with sentiment IS NULL
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

The search tests explicitly request the module-scoped `opinion_samples` fixture in `opinions/tests/conftest.py`. It loads `opinions/tests/fixtures/sample_opinions.json`, batching embeddings and sentiment into one real call per model. The module also checks submitting “i like coffee”, finding it for “coffee”, and receiving its stored sentiment. Contract tests use fixed model outputs to check indexing, model failures and retries quickly: `uv run pytest opinions/tests/test_contributions.py`. Clear Django's result cache between database-isolated tests; model loading uses separate process caches.

`docker-compose.yml` and `docker/` (`docker/db`, `docker/app`) ship the app and a Postgres+PostGIS+pgvector database as containers, so the whole stack can run without installing Nix/uv/Postgres locally — see README's Docker section for usage. Both images build their own Nix environment rather than reusing `flake.nix` directly (its devShell isn't exposed as a flake output to import elsewhere), but pin the same nixpkgs commit as `flake.lock` and install the same packages as the devShell (`postgresql.withPackages [ postgis pgvector ]`, `python3`/`uv`/`gdal`/`geos`/`proj`) — if `flake.lock` is ever updated, update `NIXPKGS_REV` in both Dockerfiles to match by hand. `docker/db`'s entrypoint bootstraps its Postgres superuser role under the app's own name (mirroring flake.nix's `createuser -s "$PGDATABASE"`) and creates *both* `opinionsearch` and `test_opinionsearch` with the extensions already installed, so the non-superuser gotcha below doesn't apply inside Docker.

## Architecture (per design.md)

Everything lives in **one PostgreSQL database**, extended rather than split: `pgvector` for embeddings and clusters, `PostGIS` for geo data. There is no separate vector service — "relational side" and "vector side" below are extensions of the same database, so a search is a single query path, not a cross-store round trip.

All of this lives in the `opinions` app (`opinions/models.py`):

- `Contribution` — original text, declared visibility, UUID, creation time, unique SHA-256 submission-key hash, and a random access receipt stored privately for retry recovery. `opinions/contributions.py` implements anonymous JSON create and receipt-authenticated reads. Source storage has no model-save embedding hook; public indexing is an explicit step in `opinions/pipeline.py`. The [intake contract](opinionsearch/frontend/API_CONTRACT.md) is the source for frontend/backend behaviour.
- `User` — a plain model, per `design.md`: just `username` (unique) and a `uuid` public identifier, no password/email/permissions. It is **not** `AUTH_USER_MODEL` — logging into `/admin` goes through Django's separate, default `django.contrib.auth.models.User`. The two are unrelated; don't conflate "an app user who publishes opinions" with "someone who can log into the admin site."
- `Opinion` — `text`, optional `topic`, `timestamp` (`auto_now_add`), nullable PostGIS `geo_coordinates`, nullable FK to `User` **by `uuid`** (`to_field="uuid"`, column `user_uuid`), a nullable 1024-dim `embedding` (BGE-M3's dense width, `EMBEDDING_DIM`), a nullable 1–5 `sentiment` score, indexed `topic_ids` array, `topic_analysis` decision JSON, and nullable FK to `Cluster`. A nullable, unique `contribution` FK links submitted opinions to their original source; deletion of that source is protected while the opinion refers to it. Anonymous intake leaves the author null and the topic empty. Carries an HNSW index using `vector_cosine_ops`.
- `Argument` — `text` plus an FK to `Opinion`.
- `Cluster` — `centroid` vector plus `updated_at`.

Opinion now holds both its text and embedding directly; there is no separate OpinionEmbedding model.

- **Write path** — `Opinion.save()` fills missing embedding and sentiment values before saving. New opinions also receive predefined topic assignments; a provided analysis prevents duplicate inference in the submission transaction. Editing already analysed text does not recompute these values. New opinions still have `cluster=None`.
- **Submission pipeline** — validate text, submission key and visibility → commit the original Contribution → for public input, call `index_contribution()` → return the ID and receipt after the linked Opinion is stored. Both `embed_text()` and `score_text()`, plus the topic classifier, run outside the write transaction, and their values are supplied to `Opinion.save()` to avoid duplicate inference. Source and opinion uniqueness constraints prevent duplicate rows on retries. Any inference step failing retains the source and returns a retryable 503. Legacy private requests skip both models; retries cannot change visibility.
- **Read path** — both frontends use `opinions.search.search_opinions()`. The JSON endpoint validates and caps results at 50, preserving fresh results after submission. It returns source IDs and stored sentiment, never embeddings or credentials. The HTML page uses the existing five-second result cache, scores the query, and runs UMAP when there are enough matches. Anonymous opinions have a null author; the HTML adapter must handle that. Time/location filters and topic-specific stance classification are not implemented.

`opinions/embedding.py` wraps `FlagEmbedding.FlagAutoModel.from_finetuned("BAAI/bge-m3", ...)`. `get_embedder()` is `lru_cache`d so the (multi-GB) model loads once per process, lazily on first use — never at import time, so `manage.py check`/migrations/etc. stay fast. `embed_text()` calls `embed_texts()` for a single string; `embed_texts()` does the real `encode_corpus` call (no query instruction — opinions are indexed documents, not search queries) and is what to use whenever more than one text needs embedding at once (e.g. loading a fixture), since one batched encoder call is much cheaper than one call per text. The read path above is what will eventually use `encode_queries` and the `query_instruction_for_retrieval` already configured on the same embedder.

`opinions/sentiment.py` mirrors that shape for sentiment: `get_sentiment_pipeline()` wraps a `transformers.pipeline("sentiment-analysis", model="nlptown/bert-base-multilingual-uncased-sentiment")`, `lru_cache`d and lazily loaded the same way as `get_embedder()`. That model is a 5-way star-rating classifier -- its own labels are the strings `"1 star"` .. `"5 stars"` -- so `score_texts()` (batched; `score_text()` wraps it for one string) reduces each to the star count alone, an int 1-5, which is what `Opinion.sentiment` stores. `sentiment_label(score)` turns a stored score back into a human-readable label ("very negative" .. "very positive", `SENTIMENT_LABELS`) -- kept separate from what's stored, same reasoning as `similarity` vs. `distance` in the search read path, so the wording can change without touching data. `opinions/management/commands/backfill_sentiment.py` scores every `Opinion` with `sentiment IS NULL` in batches (`python manage.py backfill_sentiment [--batch-size N]`) -- needed once, for rows that predate the `sentiment` field (a plain `AddField` migration, so it left existing rows at `NULL`); new opinions get scored automatically by `Opinion.save()`.

The Django `/search/` page displays UMAP coordinates using Chart.js. The React frontend instead shows simple selectable sentiment groups with one dot per returned opinion; dot positions are decorative and are not UMAP coordinates. A positive or negative score is not evidence of support or opposition to the searched topic.

`notebooks/umap_projection.ipynb` is where that projection was tried out before `opinions/projection.py` existed: it boots Django against the **development** database, loads `opinions/tests/fixtures/sample_opinions.json` into it (only removing rows whose text is in the fixture, so hand-made dev opinions survive), calls `search_opinions` with a query and slider value, and runs `umap.UMAP(n_components=2, metric="cosine", ...)` over the matched embeddings. It ends with a parameter sweep and a corpus-wide fit that highlights one search, since fitting UMAP per search would give coordinates that can't be compared between searches — the live `/search/` page deliberately does the cheaper, less faithful thing (reproject the current result set fresh on every request) rather than that corpus-wide fit, since there's nowhere yet to persist a corpus-wide one (see below). Caveat recorded in the notebook and still true of the live page: the fixture is 16-19 statements, below the size where `n_neighbors` is meaningful (it can't exceed `n_samples - 1`), so the default `n_neighbors=15` clamps down hard on small result sets — the sliders exist so this can be felt and corrected by hand until there's a real corpus to retune the defaults against. `matplotlib` and `jupyterlab` stay dev-only (notebook use only); `umap-learn` moved to the main dependency group once `opinions/projection.py` started importing it at request time.

Predefined topic matching is isolated in `opinions/topic_classification.py`, using the versioned `topic_catalogue.json`. It reuses the opinion vector and lazily caches the small catalogue’s reference embeddings. Membership is stored in a GIN-indexed PostgreSQL array, with scores, thresholds, input/vector hashes, catalogue hash/version, reference model revision and timestamp in JSON. `backfill_topics` classifies old opinions; `backfill_topics --all` replaces the current topic analysis after catalogue changes. No model runs in the topics browse API. These categories are independent of the `Cluster` model and the EVōC experiment on its own branch. See [TOPIC_PIPELINE.md](opinionsearch/frontend/TOPIC_PIPELINE.md) for method limits and the API.

## Not yet wired up

- `python-dotenv` now loads `.env`, but only the database settings read from it. `SECRET_KEY` is still the hardcoded insecure default and `DEBUG = True`; move both to the environment before any deployment.
- `django-debug-toolbar` is installed but absent from `INSTALLED_APPS` and `MIDDLEWARE`.
- UMAP is implemented for the HTML search page. Fixed topic classification and browsing now exist; discovered discussion clusters, stance/reason extraction and background scheduling are deferred. Indexing is synchronous; a durable worker can later call the repeatable `index_contribution()` helper.
- `opinions.User` has no signup/login flow of its own yet (it's not wired to Django auth at all); creating one is just `User.objects.create(username=...)` for now.

## Gotchas

- **Adding `Opinion.sentiment` (`opinions/migrations/0003_opinion_sentiment.py`) was a plain `AddField`, so it left every pre-existing row at `sentiment IS NULL`** rather than retroactively scoring them -- a data migration that calls into a multi-GB model at `migrate` time is the kind of thing this project avoids (see the BGE-M3 gotcha below on why that cost is deliberately never paid outside a request/command). `python manage.py backfill_sentiment` is the one-time fix for rows from before the field existed; it's idempotent (re-running it after every `Opinion` already has a score is a no-op), so it's always safe to run again after `migrate`.
- **`search_opinions_cached`'s cache is per-process.** It relies on Django's implicit default `CACHES` (`LocMemCache`) — fine for `runserver`/tests/a single container, but a multi-worker deployment (gunicorn with more than one worker, multiple app containers) would give each process its own cache, so the same `(query, max_distance)` could still re-embed once per worker. Move to a shared backend (e.g. Redis) before that matters.
- **Extensions are created inside the initial migration, and migrations are otherwise generated, not hand-written.** `opinions/migrations/0001_initial.py` runs `CreateExtension("postgis")` and `VectorExtension()` before the tables, so a fresh database — including the throwaway one pytest-django builds — sets itself up in one step. Use the `makemigrations`/`migrate` workflow for schema changes rather than editing migration files directly; if a migration genuinely needs hand-editing, keep those two operations first.
- Creating those extensions normally requires database superuser rights. The `opinionsearch` role is not a superuser, so a test database created by that role may fail on `CreateExtension` — the main database already has both extensions installed by `postgres`, and the test database needs the same one-time setup by hand (see Commands' Tests section) since `--reuse-db` is what lets `pytest` skip recreating it every run. (The `docker/db` setup sidesteps this by making its bootstrap role a superuser instead, like `flake.nix`'s devShell does — see Commands.)
- **GDAL/GEOS auto-discovery doesn't work inside the Nix-built Docker images.** `ctypes.util.find_library()` (what GeoDjango uses to locate them by default) resolves names via `ldconfig`'s cache, which never sees Nix store paths — confirmed empirically while building `docker/app`. `settings.py` reads `GDAL_LIBRARY_PATH`/`GEOS_LIBRARY_PATH` from the environment (unset by default, so local/`flake.nix` dev is unaffected either way), and `docker/app/Dockerfile` points both at the Nix profile's merged `lib/` directory.
- `opinions.User` is intentionally not `AUTH_USER_MODEL`. If that ever changes, note it's only safe to swap before the first migration touching it — changing it later means recreating the database (as happened once already in this project's history).
- **`Opinion.save()` calls into BGE-M3 synchronously**, so the first opinion created in a process pays the model's load time (weights are pulled from the Hugging Face Hub on first use and cached under `~/.cache/huggingface`; no `HF_TOKEN` is configured, so downloads run at the unauthenticated rate limit). There's no background task queue in this project, so every process that creates an opinion without an embedding pays this cost once, in-request. The search tests use real embeddings to verify retrieval. Contract tests use a fixed embedding; unrelated tests should supply a deterministic embedding or explicitly mock it when creating an `Opinion`.
- With `--reuse-db`, fixture rows may persist across separate `pytest` invocations. `opinions/tests/conftest.py` clears out `Opinion` (and re-`get_or_create`s `User`s) before loading the explicitly requested search fixture so repeated runs do not pile up duplicate opinions.
