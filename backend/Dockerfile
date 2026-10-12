FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/

# The venv lives outside /app so `develop.watch` syncing source into /app never clobbers it.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN useradd --system --create-home --uid 1000 tartarus \
    && mkdir /app /opt/venv \
    && chown tartarus:tartarus /app /opt/venv

WORKDIR /app
USER tartarus
COPY --chown=tartarus:tartarus pyproject.toml uv.lock .python-version ./
EXPOSE 8000


FROM base AS dev

RUN uv sync --frozen
COPY --chown=tartarus:tartarus app ./app
COPY --chown=tartarus:tartarus alembic ./alembic
COPY --chown=tartarus:tartarus alembic.ini ./
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


FROM base AS prod

RUN uv sync --frozen --no-dev
COPY --chown=tartarus:tartarus app ./app
COPY --chown=tartarus:tartarus alembic ./alembic
COPY --chown=tartarus:tartarus alembic.ini ./
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
