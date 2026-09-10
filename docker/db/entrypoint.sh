#!/bin/sh
# Bootstraps a PostgreSQL data directory on first start, mirroring the setup
# flake.nix's devShell hook does for local dev: create a superuser role named
# after the app database, create that database, and enable postgis/vector.
# On top of that, also create a second database for the test suite (see
# CLAUDE.md's Gotchas -- pytest-django's --reuse-db expects test_opinionsearch
# to already have the extensions, since a non-superuser role can't create them
# itself; here the bootstrap role is a superuser, same as flake.nix, so this
# is just done up front for both databases).
set -eu

: "${PGDATA:=/var/lib/postgresql/data}"
: "${POSTGRES_USER:=opinionsearch}"
: "${POSTGRES_DB:=opinionsearch}"
: "${POSTGRES_TEST_DB:=test_opinionsearch}"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "==> Initializing PostgreSQL data directory at $PGDATA"
    initdb --auth=trust --no-locale --encoding=UTF8 --username="$POSTGRES_USER"

    echo "==> Starting PostgreSQL temporarily to create databases and extensions"
    pg_ctl start -w -D "$PGDATA" -l "$PGDATA/init.log" -o "-c listen_addresses='' -k $PGDATA"

    for db in "$POSTGRES_DB" "$POSTGRES_TEST_DB"; do
        echo "==> Creating database: $db"
        createdb -h "$PGDATA" -U "$POSTGRES_USER" -O "$POSTGRES_USER" "$db"
        psql -h "$PGDATA" -U "$POSTGRES_USER" -d "$db" \
            -c "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS vector;"
    done

    pg_ctl stop -D "$PGDATA" -m fast

    # Allow connections from other containers on the compose network. Trust
    # auth mirrors flake.nix's local devShell setup -- fine for this project's
    # current dev-only posture (see CLAUDE.md's "Not yet wired up"), not
    # something to carry into a real deployment.
    echo "host all all all trust" >> "$PGDATA/pg_hba.conf"
fi

echo "==> Starting PostgreSQL"
exec postgres -D "$PGDATA" -c listen_addresses='*'
