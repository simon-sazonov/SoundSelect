# SoundSelect in a container: the same image runs the app and the job worker (see compose.yaml).
FROM python:3.11-slim

# Pango draws the PDFs; the fonts cover Latin and Cyrillic.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH \
    SOUNDSELECT_HOME=/data

# dependencies first, so changing the code doesn't reinstall them
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --all-extras --no-dev --no-install-project
COPY backend backend
COPY frontend frontend
RUN uv sync --locked --all-extras --no-dev

VOLUME /data
EXPOSE 8000
CMD ["soundselect", "serve", "--host", "0.0.0.0", "--port", "8000"]
