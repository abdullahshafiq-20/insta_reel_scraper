import logging
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from config import settings
from models import ScrapeRequest, ScrapeResponse, ReelMetadata, ErrorResponse
from security import verify_api_key
from scraper import scrape_instagram_reel

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("insta_scraper_api")

app = FastAPI(
    title="Instagram Reel Scraper API",
    description="FastAPI service to scrape metadata and direct progressive video CDN URLs from Instagram Reels without saving files to disk.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for web apps and external integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get(
    "/",
    tags=["General"],
    summary="API Health & Status",
    response_model=dict,
)
async def root():
    return {
        "status": "online",
        "service": "Instagram Reel Scraper API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.post(
    "/api/v1/reel",
    response_model=ScrapeResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid Instagram URL"},
        401: {"model": ErrorResponse, "description": "Missing or Invalid API Key"},
        504: {"model": ErrorResponse, "description": "Navigation Timeout"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
    tags=["Instagram Reel Scraper"],
    summary="Scrape Reel Metadata & Video CDN URL (POST)",
    description="Accepts a JSON body with the Instagram Reel URL and returns extracted metadata + CDN video URL in-memory.",
)
async def scrape_reel_post(
    request: ScrapeRequest,
    api_key: str = Depends(verify_api_key),
):
    try:
        logger.info(f"Processing scrape request for URL: {request.url}")
        data = await scrape_instagram_reel(request.url, timeout_ms=request.timeout_ms)
        return ScrapeResponse(success=True, data=ReelMetadata(**data))

    except ValueError as e:
        logger.warning(f"Validation error for URL {request.url}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid URL or shortcode: {str(e)}",
        )
    except PlaywrightTimeoutError:
        logger.error(f"Navigation timed out while scraping: {request.url}")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timeout while loading the Instagram Reel page.",
        )
    except Exception as e:
        logger.exception(f"Unexpected error scraping {request.url}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Scraper error: {str(e)}",
        )


@app.get(
    "/api/v1/reel",
    response_model=ScrapeResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid Instagram URL"},
        401: {"model": ErrorResponse, "description": "Missing or Invalid API Key"},
        504: {"model": ErrorResponse, "description": "Navigation Timeout"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
    tags=["Instagram Reel Scraper"],
    summary="Scrape Reel Metadata & Video CDN URL (GET)",
    description="Accepts URL query parameters (`?url=...&api_key=...`) to scrape and return data in pure JSON.",
)
async def scrape_reel_get(
    url: str = Query(
        ...,
        description="The Instagram Reel URL to scrape",
        examples=["https://www.instagram.com/reel/DE48s0_vG4v/"],
    ),
    timeout_ms: Optional[int] = Query(
        default=None,
        description="Optional timeout override in milliseconds",
        ge=5000,
        le=120000,
    ),
    api_key: str = Depends(verify_api_key),
):
    try:
        logger.info(f"Processing GET scrape request for URL: {url}")
        data = await scrape_instagram_reel(url, timeout_ms=timeout_ms)
        return ScrapeResponse(success=True, data=ReelMetadata(**data))

    except ValueError as e:
        logger.warning(f"Validation error for URL {url}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid URL or shortcode: {str(e)}",
        )
    except PlaywrightTimeoutError:
        logger.error(f"Navigation timed out while scraping: {url}")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timeout while loading the Instagram Reel page.",
        )
    except Exception as e:
        logger.exception(f"Unexpected error scraping {url}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Scraper error: {str(e)}",
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
    )

