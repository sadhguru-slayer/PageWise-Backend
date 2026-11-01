FROM python:3.12-slim-bookworm

# Prevent Python from writing pyc files
ENV PYTHONDONTWRITEBYTECODE=1

# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1

ENV PIP_DEFAULT_TIMEOUT=120
ENV PIP_RETRIES=5

WORKDIR /app

# Install Python dependencies (all wheels, no gcc/apt-get required)
COPY requirements.txt .

RUN pip install -v --no-cache-dir -r requirements.txt

# Install Playwright Chromium browser
RUN python -m playwright install chromium

# Copy project
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
