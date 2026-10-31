import sys
import asyncio

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.database import engine, Base
from app.routers import auth, resumes, exports

# Initialize SQLite database tables automatically
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Resumo API",
    description="Backend API for Resumo Resume Builder application",
    version="2.0.0"
)

# Configure CORS for Next.js frontend
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]

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
app.include_router(exports.router)


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "Resumo API",
        "version": "2.0.0",
        "docs": "/docs"
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}
