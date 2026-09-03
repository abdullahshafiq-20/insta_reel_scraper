"""
app/main.py
------------
FastAPI application factory.

Lifecycle
---------
• startup  — starts the shared Playwright browser pool
• shutdown — closes the browser pool cleanly

Routers registered
------------------
• /health         — liveness / config snapshot (no auth)
• /api/v1/jobs    — Stage 1 metadata extraction
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.health import router as health_router
from app.api.v1.jobs import router as jobs_router
from app.core.logging import setup_logging
from app.services.scraper.browser_pool import browser_pool

setup_logging()
logger = logging.getLogger("insta.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Startup — initialising browser pool…")
    await browser_pool.start()
    yield
    logger.info("Shutdown — closing browser pool and db pool…")
    await browser_pool.close()
    from app.db.repository import job_repo
    await job_repo.close()


app = FastAPI(
    title="Instagram Reel Scraper & Transcription Engine",
    description=(
        "Async multi-stage pipeline: "
        "Stage 1 → Metadata Extraction | "
        "Stage 2 → Media Download + Audio Conversion | "
        "Stage 3 → Switchable Transcription (local / OpenAI)"
    ),
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(jobs_router)


@app.get("/", tags=["Root"], include_in_schema=False)
async def root():
    return {
        "service": "Instagram Reel Scraper & Transcription Engine",
        "version": "2.0.0",
        "docs": "/docs",
    }

