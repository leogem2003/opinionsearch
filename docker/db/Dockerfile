# Postgres + PostGIS + pgvector for opinionsearch, built with Nix so the
# extensions match what `nix develop` gives you locally (see ../../flake.nix).
FROM nixos/nix:2.35.2

RUN mkdir -p /etc/nix \
 && echo "experimental-features = nix-command flakes" >> /etc/nix/nix.conf

# Same nixpkgs commit as the "nixpkgs" node in ../../flake.lock, and the same
# postgresql.withPackages combination as flake.nix's devShell. Keep
# NIXPKGS_REV in sync by hand if flake.lock is ever updated.
ARG NIXPKGS_REV=d6524aaca2ff07876657ae2b323f24be4874944b
RUN nix profile install --impure --expr \
      "(import (builtins.fetchTarball \"https://github.com/NixOS/nixpkgs/archive/${NIXPKGS_REV}.tar.gz\") {}).postgresql.withPackages (p: with p; [ postgis pgvector ])" \
 && nix-collect-garbage -d

# Postgres refuses to run as root. The base image's /etc/passwd and /etc/group
# are symlinks into the (read-only-by-convention) Nix store, so swap them for
# plain files before adding a "postgres" user to them.
RUN cp -L /etc/passwd /tmp/passwd && rm /etc/passwd && mv /tmp/passwd /etc/passwd \
 && cp -L /etc/group /tmp/group && rm /etc/group && mv /tmp/group /etc/group \
 && echo "postgres:x:999:999::/var/lib/postgresql:/bin/sh" >> /etc/passwd \
 && echo "postgres:x:999:" >> /etc/group \
 && mkdir -p /var/lib/postgresql/data /run/postgresql \
 && chown -R postgres:postgres /var/lib/postgresql /run/postgresql

ENV HOME=/var/lib/postgresql \
    PATH=/root/.nix-profile/bin:/nix/var/nix/profiles/default/bin:$PATH \
    PGDATA=/var/lib/postgresql/data \
    POSTGRES_USER=opinionsearch \
    POSTGRES_DB=opinionsearch \
    POSTGRES_TEST_DB=test_opinionsearch

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER postgres
EXPOSE 5432
ENTRYPOINT ["/entrypoint.sh"]
