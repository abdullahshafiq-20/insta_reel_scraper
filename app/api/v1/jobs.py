"""
app/api/v1/jobs.py
-------------------
POST /api/v1/jobs  — Asynchronously enqueues a scrape job; immediately returns 202 Accepted + job_id.
GET  /api/v1/jobs/{job_id} — Returns the current state, progress, and extracted metadata for a job.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import verify_api_key
from app.config import settings
from app.db.repository import job_repo
from app.schemas.job import (
    ErrorResponse,
    JobCreate,
    JobQueued,
    JobStage,
    JobStatus,
    JobStatusResponse,
    ReelMetadata,
)
from app.utils.validators import is_valid_instagram_url
from app.workers.scrape_worker import process_scrape_job

logger = logging.getLogger("insta.api.jobs")
router = APIRouter(prefix="/api/v1", tags=["Jobs"])


@router.post(
    "/jobs",
    summary="Submit scrape job — Stage 1: Asynchronous Metadata Extraction",
    description=(
        "Accepts an Instagram Reel / Post URL, validates it, and immediately returns "
        "a job_id with status: 'queued'. The scraping process runs in the background "
        "and dispatches real-time stage progress and completion payloads to the configured webhook."
    ),
    response_model=JobQueued,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid Instagram URL"},
        401: {"model": ErrorResponse, "description": "Missing or invalid API Key"},
    },
)
async def submit_job(
    body: JobCreate,
    _api_key: str = Depends(verify_api_key),
) -> JobQueued:
    # 1. Validate Instagram URL
    if not is_valid_instagram_url(body.url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Not a valid Instagram Reel / Post URL: {body.url!r}",
        )

    # 2. Determine effective webhook URL (payload override > environment setting)
    effective_webhook = (body.webhook_url or settings.WEBHOOK_URL or "").strip() or None

    # 3. Generate unique job identifier
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # 4. Persist job in database
    await job_repo.create_job(
        job_id=job_id,
        url=body.url,
        transcription_provider=body.transcription_provider,
        webhook_url=effective_webhook,
    )

    # 5. Spawn background task for Stage 1 processing
    asyncio.create_task(process_scrape_job(job_id=job_id, url=body.url, webhook_url=effective_webhook))

    logger.info("Enqueued scrape job %s for url: %s (webhook: %s)", job_id, body.url, effective_webhook)

    # 6. Return immediate 202 response
    return JobQueued(
        success=True,
        job_id=job_id,
        status=JobStatus.QUEUED,
        stage=JobStage.INITIALIZED,
        created_at=now,
    )


@router.get(
    "/jobs/{job_id}",
    summary="Get job status and result",
    description="Retrieves current status, stage, metadata, and error details for a given job.",
    response_model=JobStatusResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid API Key"},
        404: {"model": ErrorResponse, "description": "Job not found"},
    },
)
async def get_job(
    job_id: str,
    _api_key: str = Depends(verify_api_key),
) -> JobStatusResponse:
    record = await job_repo.get_job(job_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )

    meta_obj = None
    if record.get("metadata"):
        try:
            meta_obj = ReelMetadata(**record["metadata"])
        except Exception as exc:
            logger.warning("Could not parse stored metadata into ReelMetadata schema for job %s: %s", job_id, exc)

    return JobStatusResponse(
        success=True,
        job_id=record["id"],
        status=JobStatus(record["status"]),
        stage=JobStage(record["stage"]),
        current_queue=record.get("current_queue"),
        created_at=record["created_at"],
        updated_at=record.get("updated_at"),
        completed_at=record.get("completed_at"),
        metadata=meta_obj,
        video_path=record.get("video_path"),
        audio_path=record.get("audio_path"),
        transcription=record.get("transcription"),
        error=record.get("error_message"),
    )
