# syntax=docker/dockerfile:1.7

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=1000 \
    PIP_RETRIES=10 \
    HOME=/home/app \
    XDG_CACHE_HOME=/home/app/.cache

WORKDIR /app

# System dependencies (including fontconfig for font rendering & cache)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fontconfig \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz0b \
    libharfbuzz-subset0 \
    libjpeg62-turbo \
    libopenjp2-7 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies using persistent cache
COPY requirements.txt .

RUN --mount=type=cache,id=pagewise-pip-cache,target=/root/.cache/pip,sharing=locked \
    pip install -r requirements.txt

# Copy application
COPY . .

# Run without root privileges
RUN useradd --create-home --user-group --uid 1000 app && \
    mkdir -p /home/app/.cache/fontconfig /var/cache/fontconfig /app/exports && \
    chown -R app:app /home/app /var/cache/fontconfig /app && \
    fc-cache -fv

USER app

EXPOSE 8000

# Exactly one worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
