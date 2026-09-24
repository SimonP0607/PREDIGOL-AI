# One image for the API and the worker (compose mode). The code is baked in:
# a container runs exactly the commit it was built from, and says which in
# FBI_CODE_VERSION - the image has no .git to read it from. Build it with
#   make image        (or: FBI_CODE_VERSION=$(git rev-parse --short=12 HEAD) docker compose --profile stack build)
# Nothing secret is in the image: .dockerignore keeps .env and data/ out, and
# the settings arrive at run time through env_file.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# Dependencies first, from pyproject alone, so a code change does not
# reinstall them. Wheels only (psycopg[binary], numpy, scipy): no compiler.
COPY pyproject.toml README.md ./
RUN mkdir -p src/fbi && touch src/fbi/__init__.py && pip install -e ".[analytics]"
COPY . .

# The same uid as the WSL user, so payloads written to the bind-mounted
# data/raw stay writable by host mode too (both modes share one raw store).
ARG FBI_UID=1000
RUN useradd --uid "${FBI_UID}" --create-home --shell /usr/sbin/nologin fbi \
    && mkdir -p data/raw && chown fbi data/raw
USER fbi

ARG FBI_CODE_VERSION=unknown
ENV FBI_CODE_VERSION=${FBI_CODE_VERSION}
