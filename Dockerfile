FROM python:3.12-slim-bookworm

# Prevent Python from writing pyc files
ENV PYTHONDONTWRITEBYTECODE=1

# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1

ENV PIP_DEFAULT_TIMEOUT=1000
ENV PIP_RETRIES=10

WORKDIR /app

# Install system dependencies for WeasyPrint (lightweight pango/cairo, no heavy browser)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz0b \
    libharfbuzz-subset0 \
    libjpeg62-turbo \
    libopenjp2-7 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies: uses pre-downloaded wheels if present in ./wheels, otherwise falls back to PyPI
COPY requirements.txt .
COPY . /tmp/build_context/

RUN if [ -d "/tmp/build_context/wheels" ] && [ "$(ls -A /tmp/build_context/wheels 2>/dev/null)" ]; then \
        echo "--> Installing dependencies from local wheels directory..." && \
        pip install --no-cache-dir --no-index --find-links=/tmp/build_context/wheels -r requirements.txt; \
    else \
        echo "--> Local wheels not found, installing dependencies normally from PyPI..." && \
        pip install --no-cache-dir -r requirements.txt; \
    fi && \
    rm -rf /tmp/build_context

# Copy application
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]