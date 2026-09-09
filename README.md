# Opinionsearch

## Features
TODO: screeshots

1. Discover and visualize other opinions
2. Filter by categories, location and time
   
# Setup

## Dependincies
- python3 with uv
- postgresql with `postgis` and `pgvector` extensions
  
# Running
(Dev server)
```bash
uv run python manage.py runserver 
```

## Limitations
1. Since this is a website, it is centralized and controlled by a single entity
2. There is currently no bot protection implemented to prevent inauthentic behavior
3. Language always is ambiguous to some degree
## License
See [LICENSE.txt](LICENSE.txt)