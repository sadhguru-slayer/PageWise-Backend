# PageWise Studio — Operational Commands Guide

Quick reference for Docker, Alembic migrations, database administration, and deployment.

---

## 🛠️ Development Environment

### Start Local Dev Containers (FastAPI + Redis + PostgreSQL)
```bash
# Build and run with hot-reload enabled (no Caddy proxy in dev)
docker compose up --build

# Run in detached mode (background)
docker compose up -d

# View live service logs
docker compose logs -f

# Stop and remove development containers
docker compose down
```

---

## 🗄️ Database Migrations (Alembic)

> **Note:** Alembic runs on an isolated migration profile. It is **never built or run automatically** on default `docker compose up`. It runs solely on-demand and terminates immediately upon completion.

### 1. Generate a New Autodetected Migration
```bash
# Development
docker compose --profile migration run --rm alembic alembic revision --autogenerate -m "add_new_feature_columns"

# Production
docker compose -f docker-compose.prod.yaml --profile migration run --rm alembic alembic revision --autogenerate -m "add_new_feature_columns"
```

### 2. Apply Migrations (Upgrade Head)
```bash
# Development
docker compose --profile migration run --rm alembic alembic upgrade head

# Production
docker compose -f docker-compose.prod.yaml --profile migration run --rm alembic alembic upgrade head
```

### 3. Check Migration Status & History
```bash
# View current database revision
docker compose --profile migration run --rm alembic alembic current

# View complete revision history
docker compose --profile migration run --rm alembic alembic history --verbose
```

### 4. Rollback Migrations
```bash
# Rollback the last migration
docker compose --profile migration run --rm alembic alembic downgrade -1

# Rollback to a specific revision hash
docker compose --profile migration run --rm alembic alembic downgrade <revision_id>
```

---

## 🔍 Database & Redis Direct CLI Access

### PostgreSQL Terminal (`psql`)
```bash
# Connect directly to the PageWise PostgreSQL database
docker exec -it pagewise-postgres psql -U pagewiseuser -d pagewisedb

# Useful psql shortcuts inside prompt:
#   \dt          List all tables
#   \d users     Inspect 'users' table schema
#   \q           Exit psql
```

### Redis Terminal (`redis-cli`)
```bash
# Access the PageWise Redis in-memory cache
docker exec -it pagewise-redis redis-cli

# Useful redis-cli commands:
#   KEYS *                 List all active keys
#   KEYS pagewise_otp:*    List all active OTP verification keys
#   TTL <key>              Check expiration seconds remaining
#   GET <key>              Inspect key value
```

---

## 🚀 Production Deployment (With Caddy & SSL)

### 1. Build and Start Production Services
```bash
# Build and launch FastAPI, Redis, Postgres, and Caddy reverse proxy
docker compose -f docker-compose.prod.yaml up -d --build
```

### 2. Execute Production Migrations
```bash
docker compose -f docker-compose.prod.yaml --profile migration run --rm alembic
```

### 3. Production Monitoring & Logs
```bash
# Follow live logs for all production containers
docker compose -f docker-compose.prod.yaml logs -f

# Follow logs for FastAPI backend only
docker compose -f docker-compose.prod.yaml logs -f fastapi

# Follow logs for Caddy reverse proxy
docker compose -f docker-compose.prod.yaml logs -f caddy
```

### 4. Stop Production Services
```bash
docker compose -f docker-compose.prod.yaml down
```

---

## 💻 Standalone Local Execution (Without Docker)

```bash
# Activate virtual environment
.\venv\Scripts\activate   # Windows
source venv/bin/activate  # macOS / Linux

# Run backend with auto-reload
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
