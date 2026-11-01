FROM python:3.12-slim-bookworm

# Prevent Python from writing pyc files
ENV PYTHONDONTWRITEBYTECODE=1

# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1

ENV PIP_DEFAULT_TIMEOUT=1000
ENV PIP_RETRIES=10

WORKDIR /app

# Install Python dependencies with high timeout and retries
COPY requirements.txt .

RUN pip install \
    --no-cache-dir \
    --default-timeout=1000 \
    --retries=10 \
    -r requirements.txt

# Install Playwright Chromium browser
RUN python -m playwright install chromium

# Copy project
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
