"""
app/workers/scrape_worker.py
----------------------------
Asynchronously executes Stage 1 (Metadata Extraction) for a given job.
Updates database state and dispatches stage progress and completion/failure webhooks.
"""
import logging
from typing import Optional

from app.config import settings
from app.db.repository import job_repo
from app.schemas.job import JobStage, JobStatus
from app.services.scraper.instagram_scraper import get_instagram_scraper
from app.services.webhook.dispatcher import dispatcher

logger = logging.getLogger("insta.worker.scrape")


async def process_scrape_job(
    job_id: str,
    url: str,
    webhook_url: Optional[str] = None,
) -> None:
    """
    Background worker task for Stage 1:
    1. Mark job as PROCESSING (stage: initialized).
    2. Dispatch initial progress webhook.
    3. Run Playwright scraper via shared browser pool.
    4. Save extracted metadata and mark COMPLETED (stage: metadata_extracted).
    5. Dispatch completion webhook with full metadata payload.
    """
    effective_webhook = (webhook_url or settings.WEBHOOK_URL or "").strip() or None
    logger.info("Starting Stage 1 processing for job %s (url=%s, webhook=%s)", job_id, url, effective_webhook)

    # Transition to PROCESSING
    await job_repo.update_job(
        job_id,
        status=JobStatus.PROCESSING.value,
        stage=JobStage.INITIALIZED.value,
    )

    # Optional progress event
    await dispatcher.dispatch(
        webhook_url=effective_webhook,
        event="job.stage_updated",
        job_id=job_id,
        status=JobStatus.PROCESSING.value,
        stage=JobStage.INITIALIZED.value,
    )

    try:
        scraper = get_instagram_scraper()
        metadata = await scraper.scrape(url)

        # Update database with extracted metadata
        await job_repo.update_job(
            job_id,
            status=JobStatus.COMPLETED.value,
            stage=JobStage.METADATA_EXTRACTED.value,
            metadata=metadata,
            completed=True,
        )

        logger.info("Stage 1 completed successfully for job %s", job_id)

        # Dispatch final completion webhook
        await dispatcher.dispatch(
            webhook_url=effective_webhook,
            event="job.completed",
            job_id=job_id,
            status=JobStatus.COMPLETED.value,
            stage=JobStage.METADATA_EXTRACTED.value,
            data=metadata,
        )

    except Exception as exc:
        err_msg = str(exc)
        logger.exception("Stage 1 failed for job %s: %s", job_id, err_msg)

        await job_repo.update_job(
            job_id,
            status=JobStatus.FAILED.value,
            error=err_msg,
            completed=True,
        )

        await dispatcher.dispatch(
            webhook_url=effective_webhook,
            event="job.failed",
            job_id=job_id,
            status=JobStatus.FAILED.value,
            stage=JobStage.INITIALIZED.value,
            error=err_msg,
        )

