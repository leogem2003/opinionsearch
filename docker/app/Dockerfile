# Django app for opinionsearch. Native deps (python3, uv, gdal, geos, proj)
# come from Nix, pinned to the same nixpkgs commit as flake.lock and mirroring
# flake.nix's devShell; Python dependencies are installed the same way local
# dev does it, via `uv sync` against pyproject.toml + uv.lock.
#
# Build context is the repo root (see ../../docker-compose.yml) since this
# needs the whole project, not just docker/app/.
FROM nixos/nix:2.35.2

RUN mkdir -p /etc/nix \
 && echo "experimental-features = nix-command flakes" >> /etc/nix/nix.conf

# Same nixpkgs commit as the "nixpkgs" node in ../../flake.lock. Keep
# NIXPKGS_REV in sync by hand if flake.lock is ever updated.
ARG NIXPKGS_REV=d6524aaca2ff07876657ae2b323f24be4874944b
RUN nix profile install --impure --expr \
      "let pkgs = import (builtins.fetchTarball \"https://github.com/NixOS/nixpkgs/archive/${NIXPKGS_REV}.tar.gz\") {}; in pkgs.buildEnv { name = \"opinionsearch-env\"; paths = with pkgs; [ python3 uv gdal geos proj ]; }" \
 && nix-collect-garbage -d

# ctypes.util.find_library() (what GeoDjango uses to locate GDAL/GEOS by
# default) can't see Nix store paths since they're never registered in
# ldconfig's cache -- confirmed empirically when this image was put together.
# GDAL_LIBRARY_PATH/GEOS_LIBRARY_PATH (settings.py) sidestep that by pointing
# straight at the Nix profile's merged lib/ directory.
ENV PATH=/root/.nix-profile/bin:/nix/var/nix/profiles/default/bin:$PATH \
    UV_PYTHON_PREFERENCE=system \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    LD_LIBRARY_PATH=/root/.nix-profile/lib \
    GDAL_LIBRARY_PATH=/root/.nix-profile/lib/libgdal.so \
    GEOS_LIBRARY_PATH=/root/.nix-profile/lib/libgeos_c.so \
    HF_HOME=/data/hf-cache \
    DJANGO_SETTINGS_MODULE=opinionsearch.settings

WORKDIR /app

# Installing deps before copying the rest of the source means a source-only
# change doesn't bust this layer -- worth it here since the ML dependency
# stack (FlagEmbedding/torch/...) is multiple GB.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

# Stdout is fully block-buffered (not line-buffered) when it isn't a TTY, so
# without this, `runserver`'s own banner and any print()-based logging can
# sit invisible in `docker compose logs` well after the server is actually up.
ENV PYTHONUNBUFFERED=1

COPY docker/app/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Docker exec/healthchecks cannot resolve the base image's account-file symlinks.
# Keep plain copies, as docker/db already does for its postgres user.
RUN cp -L /etc/passwd /tmp/passwd && rm /etc/passwd && mv /tmp/passwd /etc/passwd \
 && cp -L /etc/group /tmp/group && rm /etc/group && mv /tmp/group /etc/group

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
