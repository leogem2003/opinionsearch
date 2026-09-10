# Opinionsearch

## Features
TODO: screeshots

1. Discover and visualize other opinions
2. Filter by categories, location and time
   
# Setup
> [!NOTE]  
> This is only meant for **development** and not suitable for production.

## Dependincies
- `python3` with Astral `uv`
- `gdal`, `geos` and `proj` system libraries
- `postgresql` with `postgis` and `pgvector` extensions
See [flake.nix](flake.nix) for initial postgresql setup.
  
# Running
(Dev server)
```bash
uv run python manage.py runserver 
```

## Docker
> [!WARNING]  
> The default managemant user will be `admin`, passwd:`admin` and runs the **development server**


Start the Django webapp
```bash
docker compose up --build
```

The app listens at `http://localhost:8000`. The first build could take a while.
`docker compose down -v` clears caches and the database.

The [frontend](opinionsearch/frontend/README.md) runs separately and proxies `/api` to this backend. Its issue form saves the original contribution, runs the existing BGE-M3 embedding and sentiment models, and makes the linked opinion searchable. The [intake API](opinionsearch/frontend/API_CONTRACT.md) records visibility, provenance and retry behaviour.

Run the tests:
```bash
docker compose run --rm web uv run pytest
```

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

### Developers
- [@leogem2003](https://github.com/leogem2003), architecture design design, prompt engineering, programming
- [@ttlns](https://github.com/leogem2003), code review, testing, bugfix
- [@galtendorfer][https://github.com/galtendorfer] Initial frontent draft, presentation
