FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=1000 \
    PIP_RETRIES=10

WORKDIR /app

COPY requirements.txt .

# Install Python dependencies
# --mount=type=cache persists pip's download cache across builds so a failed/retried
# build does NOT re-download packages that already landed in the cache.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
        --default-timeout=1000 \
        --retries=10 \
        --only-binary=:all: \
        -r requirements.txt

# Install Playwright Chromium with its Linux system dependencies
RUN python -m playwright install --with-deps chromium

# Copy application
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
