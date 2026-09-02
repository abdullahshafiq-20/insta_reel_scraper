from fastapi import APIRouter
from app.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Service health check")
async def health() -> dict:
    return {
        "status": "healthy",
        "service": "instagram-reel-scraper",
        "transcription_provider": settings.TRANSCRIPTION_PROVIDER,
        "scrape_pool_size": settings.SCRAPE_BROWSER_POOL_SIZE,
    }

