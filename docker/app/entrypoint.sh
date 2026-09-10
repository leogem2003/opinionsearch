#!/bin/sh
# Waits for the database, applies migrations, then either runs the given
# command (e.g. `uv run pytest`, for the testing setup) or falls back to the
# dev server -- so this same image/entrypoint serves both `docker compose up`
# and `docker compose run --rm web uv run pytest`.
set -eu

: "${DB_HOST:=db}"
: "${DB_PORT:=5432}"

echo "==> Waiting for database at $DB_HOST:$DB_PORT"
until python3 -c "
import os, socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(1)
try:
    s.connect((os.environ['DB_HOST'], int(os.environ['DB_PORT'])))
except OSError:
    sys.exit(1)
"; do
    sleep 1
done

echo "==> Applying migrations"
uv run python manage.py migrate --noinput

echo "==> Creating admin user if needed"
uv run python manage.py shell << 'DJANGO_EOF'
from django.contrib.auth.models import User
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'admin')
    print("Created admin user (admin/admin)")
else:
    print("Admin user already exists")
DJANGO_EOF

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

echo "==> Starting development server"
exec uv run python manage.py runserver 0.0.0.0:8000
