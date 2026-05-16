# Container image for openbourse — used by the docker-compose `scheduler`
# service to force-sync the universe before the US market opens. It bundles
# the CLI, Alembic migrations, and the seed data, so `bourse db migrate`
# and `bourse universe sync` run unchanged inside the container.
FROM python:3.12-slim

# PYTHONUNBUFFERED keeps scheduler logs flowing to `docker compose logs`.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Files the poetry-core build backend needs to resolve and build the
# package. `tzdata` (PyPI) backs zoneinfo's America/New_York lookup so the
# scheduler keeps correct ET time without an apt install.
COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
RUN pip install . tzdata

# Default command: the pre-market sync loop. Override per-invocation, e.g.
# `docker compose run --rm scheduler python -m openbourse universe sync`.
CMD ["python", "scripts/market_sync_scheduler.py"]
