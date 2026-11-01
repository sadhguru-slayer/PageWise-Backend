
# syntax=docker/dockerfile:1.7

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=1000 \
    PIP_RETRIES=10

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
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
RUN useradd --system --no-create-home app && \
    chown -R app:app /app

USER app

EXPOSE 8000

# Exactly one worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
