# syntax=docker/dockerfile:1

FROM node:24-trixie-slim AS frontend-build

WORKDIR /build/frontend
RUN npm install --global pnpm@11.9.0
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.13-slim-trixie AS backend-build

COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

FROM python:3.13-slim-trixie AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/backend/.venv/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    APP_DATA_DIR=/data \
    APP_ENV_FILE=/data/.env \
    FRONTEND_DIST_DIR=/app/frontend/dist \
    FRONTEND_RENDER_BASE_URL=http://127.0.0.1:8000 \
    BACKEND_CORS_ORIGINS=""
WORKDIR /app/backend
COPY --from=backend-build /app/backend/.venv ./.venv
ARG DEBIAN_MIRROR=https://deb.debian.org/debian
RUN /usr/local/bin/python -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.13/ensurepip \
    && sed -i "s|http://deb.debian.org/debian$|${DEBIAN_MIRROR}|; s|http://deb.debian.org/debian-security|https://deb.debian.org/debian-security|" /etc/apt/sources.list.d/debian.sources \
    && playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/* /root/.cache \
    && groupadd --gid 10001 reseno \
    && useradd --uid 10001 --gid reseno --create-home --no-log-init reseno \
    && install -d -m 0700 -o reseno -g reseno /data
COPY backend/app ./app
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist
COPY LICENSE /usr/share/doc/reseno/LICENSE

USER reseno
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).close()"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
