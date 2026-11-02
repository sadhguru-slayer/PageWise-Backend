import sys
import asyncio

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

import os
import logging
from dotenv import load_dotenv

# Initialize logging so stdout captures info logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Load environment configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(BASE_DIR)
load_dotenv(os.path.join(BASE_DIR, ".env"))
load_dotenv(os.path.join(ROOT_DIR, ".env"))
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, Base, run_auto_migrations
from app.routers import auth, resumes, exports, payments, admin

# Initialize database tables automatically if not already present
try:
    Base.metadata.create_all(bind=engine)
    run_auto_migrations()
except Exception:
    pass

app = FastAPI(
    title="PageWise Studio API",
    description="Backend API for PageWise Resume Studio application",
    version="2.5.0",
)

# Configure CORS for Next.js frontend
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    os.getenv("FRONTEND_URL"),
    os.getenv("FRONTEND_URL_2"),
]

origins = [origin for origin in origins if origin]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:[0-9]+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth.router)
app.include_router(resumes.router)
app.include_router(resumes.legacy_router)
app.include_router(resumes.templates_router)
app.include_router(exports.router)
app.include_router(payments.router)
app.include_router(admin.router)


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "PageWise Studio API",
        "version": "2.5.0",
        "docs": "/docs",
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}
