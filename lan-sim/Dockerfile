# Build from the repository root, as the cape image is: docker build -f lan-sim/Dockerfile .
# The daemon parses hostile network input from a guest under analysis, so the image holds the Python
# base, the locked dependencies and the daemon, and nothing else (docker-compose.yml confines it further).
FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS build

COPY --from=ghcr.io/astral-sh/uv:0.12@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a /uv /bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /build
COPY lan-sim/pyproject.toml lan-sim/uv.lock ./
RUN uv sync --frozen --no-dev --no-cache


FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704

# A fixed id: the shared volume's status/ and logs/ directories are made for it by the cape entrypoint.
RUN groupadd --system --gid 10001 lan-sim \
    && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin lan-sim

COPY --from=build /opt/venv /opt/venv

WORKDIR /app
COPY lan-sim/lan_sim ./lan_sim
# The one file the control service and the daemon share (the contract of /run/lan-sim).
COPY cape/guest_engine/lan_session.py ./
RUN python -m compileall -q /app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LAN_SIM_ROOT=/run/lan-sim

USER 10001:10001
ENTRYPOINT ["python", "-m", "lan_sim"]
