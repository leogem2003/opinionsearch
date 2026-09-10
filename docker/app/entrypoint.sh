#!/bin/sh
# Waits for the database, applies migrations, then either runs the given
# command or prepares models and starts the website with installed dependencies.
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
uv run manage.py migrate --noinput

echo "==> Creating admin user if needed"
uv run manage.py shell << 'DJANGO_EOF'
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

uv run -m docker.app.serve
