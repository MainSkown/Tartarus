FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS base

COPY --from=ghcr.io/astral-sh/uv:0.12@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a /uv /uvx /bin/

# The venv lives outside /app so `develop.watch` syncing source into /app never clobbers it.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN useradd --system --create-home --uid 1000 tartarus \
    && mkdir -p /app /opt/venv /data/samples /data/exports /imports \
    && chown tartarus:tartarus /app /opt/venv /data/samples /data/exports /imports

# WeasyPrint's text layout (Pango) and the report's print fonts: Liberation matches the design
# system's Courier New / Arial, DejaVu is the per-glyph fallback.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
USER tartarus
COPY --chown=tartarus:tartarus pyproject.toml uv.lock .python-version ./
COPY --chown=tartarus:tartarus docker-entrypoint.sh /usr/local/bin/
ENTRYPOINT ["docker-entrypoint.sh"]
EXPOSE 8000


FROM base AS dev

RUN uv sync --frozen --no-cache
COPY --chown=tartarus:tartarus app ./app
COPY --chown=tartarus:tartarus alembic ./alembic
COPY --chown=tartarus:tartarus alembic.ini ./
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


FROM base AS prod

RUN uv sync --frozen --no-dev --no-cache
COPY --chown=tartarus:tartarus app ./app
COPY --chown=tartarus:tartarus alembic ./alembic
COPY --chown=tartarus:tartarus alembic.ini ./
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
