"""
app/workers/scrape_worker.py
----------------------------
Asynchronously orchestrates the multi-stage job processing pipeline:

Two-Check Pipeline Classification:
  1. First Check (URL Path): Preliminary hint ('reel' vs 'post').
  2. Second Check (Live Scraping / DOM Inspection):
     - If the page contains a Carousel Next button (<button aria-label="Next">),
       dot indicators, or 'edge_sidecar_to_children', it is GUARANTEED to be a
       carousel of images -> routes to Image Crawling + PaddleOCR Pipeline.
     - If the page has NO carousel next button and contains a video stream,
       it is GUARANTEED to be a Reel / Video -> routes to Video + FFmpeg + Whisper Pipeline.
     - If the page has no carousel next button and no video, it is a single image post
       -> routes to PaddleOCR Pipeline.
"""
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import settings
from app.db.repository import job_repo
from app.schemas.job import JobStage, JobStatus
from app.services.media.audio_converter import audio_converter
from app.services.media.downloader import downloader
from app.services.ocr.paddle_ocr_service import paddle_ocr_service
from app.services.scraper.instagram_post_scraper import get_instagram_post_scraper
from app.services.scraper.instagram_scraper import get_instagram_scraper
from app.services.transcription.openai_whisper import openai_transcription_service
from app.services.webhook.dispatcher import dispatcher
from app.utils.validators import extract_links, get_instagram_url_type

logger = logging.getLogger("insta.worker.pipeline")


async def _process_post_ocr(
    job_id: str,
    url: str,
    post_metadata: Dict[str, Any],
    effective_webhook: Optional[str],
    existing_record: Optional[Dict[str, Any]] = None,
) -> None:
    """Executes the Carousel / Image Post pipeline with incremental PaddleOCR and webhook updates."""
    # 1. Update metadata in DB
    await job_repo.update_job(
        job_id,
        status=JobStatus.PROCESSING.value,
        stage=JobStage.METADATA_EXTRACTED.value,
        content_type="post",
        metadata=post_metadata,
    )
    await dispatcher.dispatch(
        webhook_url=effective_webhook,
        event="job.stage_updated",
        job_id=job_id,
        status=JobStatus.PROCESSING.value,
        stage=JobStage.METADATA_EXTRACTED.value,
        data={"metadata": post_metadata, "content_type": "post"},
    )

    # 2. PaddleOCR Per-Image Extraction (Incremental & Resumable)
    images = post_metadata.get("images", [])
    total_images = len(images) if images else 1

    existing_ocr = (existing_record.get("ocr") or {}) if existing_record else {}
    completed_slides: Dict[int, Dict[str, Any]] = {
        item["index"]: item for item in existing_ocr.get("slides", []) if "index" in item
    }

    logger.info(
        "[Job %s] Starting PaddleOCR phase (%d total images, %d already processed)",
        job_id,
        total_images,
        len(completed_slides),
    )

    for img_item in images:
        idx = img_item.get("index", 1)
        img_src = img_item.get("src")
        if not img_src:
            continue

        if idx in completed_slides:
            logger.info("[Job %s] Image %d already OCR processed; skipping", job_id, idx)
            continue

        logger.info("[Job %s] OCR processing image %d/%d", job_id, idx, total_images)
        slide_ocr = await paddle_ocr_service.extract_text_from_url(
            image_url=img_src,
            job_id=job_id,
            index=idx,
        )
        completed_slides[idx] = slide_ocr

        # Immediately commit partial OCR progress to database
        partial_ocr_payload = {
            "total_images": total_images,
            "completed_count": len(completed_slides),
            "slides": sorted(completed_slides.values(), key=lambda x: x["index"]),
        }
        await job_repo.update_job(
            job_id,
            status=JobStatus.PROCESSING.value,
            stage=JobStage.OCR_PROCESSING.value,
            ocr=partial_ocr_payload,
        )

        # Real-time webhook update for this specific image index
        await dispatcher.dispatch(
            webhook_url=effective_webhook,
            event="job.stage_updated",
            job_id=job_id,
            status=JobStatus.PROCESSING.value,
            stage=JobStage.OCR_PROCESSING.value,
            data={
                "image_index": idx,
                "total_images": total_images,
                "image_url": img_src,
                "extracted_texts": slide_ocr["texts"],
                "full_text": slide_ocr["full_text"],
                "completed_count": len(completed_slides),
            },
        )

    # 3. Final Aggregation & Link Extraction
    all_slides = sorted(completed_slides.values(), key=lambda x: x["index"])
    combined_text = "\n\n".join(
        [f"--- Image {s['index']} ---\n{s['full_text']}" for s in all_slides if s.get("full_text")]
    )

    # Extract all links across caption, OCR text, and image alts
    all_text_sources = [post_metadata.get("caption") or ""]
    for s in all_slides:
        all_text_sources.append(s.get("full_text") or "")
        all_text_sources.extend(s.get("texts") or [])
    for img in post_metadata.get("images", []):
        if img.get("alt"):
            all_text_sources.append(img["alt"])

    extracted_links = extract_links("\n".join(all_text_sources))
    post_metadata["extracted_links"] = extracted_links

    final_ocr_payload = {
        "total_images": total_images,
        "combined_text": combined_text,
        "slides": all_slides,
    }
    final_post_data = {
        "metadata": post_metadata,
        "ocr": final_ocr_payload,
        "extracted_links": extracted_links,
    }

    await job_repo.update_job(
        job_id,
        status=JobStatus.COMPLETED.value,
        stage=JobStage.FINISHED.value,
        metadata=post_metadata,
        ocr=final_ocr_payload,
        completed=True,
        webhook_status="sent",
    )

    logger.info(
        "[Job %s] Carousel/Post pipeline with OCR completed successfully (%d images). Emitting final webhook",
        job_id,
        total_images,
    )
    await dispatcher.dispatch(
        webhook_url=effective_webhook,
        event="job.completed",
        job_id=job_id,
        status=JobStatus.COMPLETED.value,
        stage=JobStage.FINISHED.value,
        data=final_post_data,
    )


async def _process_reel_media(
    job_id: str,
    url: str,
    metadata: Dict[str, Any],
    effective_webhook: Optional[str],
) -> None:
    """Executes the Reel / Video pipeline with progressive download, FFmpeg, and OpenAI Whisper."""
    video_path: Optional[str] = None
    audio_path: Optional[str] = None

    try:
        # Stage 1 complete
        await job_repo.update_job(
            job_id,
            status=JobStatus.PROCESSING.value,
            stage=JobStage.METADATA_EXTRACTED.value,
            content_type="reel",
            metadata=metadata,
        )
        await dispatcher.dispatch(
            webhook_url=effective_webhook,
            event="job.stage_updated",
            job_id=job_id,
            status=JobStatus.PROCESSING.value,
            stage=JobStage.METADATA_EXTRACTED.value,
            data={"metadata": metadata, "content_type": "reel"},
        )

        # Stage 2: Media Download & Audio Conversion
        video_url = metadata.get("video_url")
        if not video_url and metadata.get("video_urls_candidates"):
            video_url = metadata["video_urls_candidates"][0]

        if not video_url:
            raise ValueError("No downloadable video CDN URL found in the extracted metadata.")

        logger.info("[Job %s] Stage 2: Downloading video stream", job_id)
        video_path = await downloader.download_video(url=video_url, job_id=job_id)

        logger.info("[Job %s] Stage 2: Converting video to 16kHz mono audio via FFmpeg", job_id)
        audio_path, duration_seconds = await audio_converter.extract_audio(video_path=video_path, job_id=job_id)

        await job_repo.update_job(
            job_id,
            status=JobStatus.PROCESSING.value,
            stage=JobStage.AUDIO_CONVERTED.value,
            video_path=video_path,
            audio_path=audio_path,
        )
        await dispatcher.dispatch(
            webhook_url=effective_webhook,
            event="job.stage_updated",
            job_id=job_id,
            status=JobStatus.PROCESSING.value,
            stage=JobStage.AUDIO_CONVERTED.value,
            data={"duration_seconds": duration_seconds},
        )

        # Stage 3: Transcription via OpenAI Whisper (with $0.0045/min cost)
        logger.info("[Job %s] Stage 3: Transcribing audio via OpenAI", job_id)
        transcription_result = await openai_transcription_service.transcribe(
            audio_path=audio_path,
            duration_seconds=duration_seconds,
        )

        # Stage 4: Completion & Link Extraction across caption & transcript
        caption_text = metadata.get("caption") or ""
        transcript_text = transcription_result.get("text") or ""
        extracted_links = extract_links(f"{caption_text}\n{transcript_text}")
        metadata["extracted_links"] = extracted_links

        final_payload = {
            "metadata": metadata,
            "transcription": transcription_result,
            "extracted_links": extracted_links,
        }

        await job_repo.update_job(
            job_id,
            status=JobStatus.COMPLETED.value,
            stage=JobStage.FINISHED.value,
            metadata=metadata,
            transcription=transcription_result,
            completed=True,
            webhook_status="sent",
        )

        logger.info("[Job %s] Reel pipeline finished successfully. Emitting final webhook", job_id)
        await dispatcher.dispatch(
            webhook_url=effective_webhook,
            event="job.completed",
            job_id=job_id,
            status=JobStatus.COMPLETED.value,
            stage=JobStage.FINISHED.value,
            data=final_payload,
        )

    finally:
        if settings.CLEANUP_TEMP_FILES:
            try:
                if video_path and Path(video_path).exists():
                    Path(video_path).unlink(missing_ok=True)
                if audio_path and Path(audio_path).exists():
                    Path(audio_path).unlink(missing_ok=True)
                logger.debug("[Job %s] Cleaned up temporary media files", job_id)
            except Exception as clean_err:
                logger.warning("[Job %s] Error cleaning temporary files: %s", job_id, clean_err)


async def process_scrape_job(
    job_id: str,
    url: str,
    webhook_url: Optional[str] = None,
    resume: bool = False,
) -> None:
    effective_webhook = (webhook_url or settings.WEBHOOK_URL or "").strip() or None
    initial_content_type = get_instagram_url_type(url)
    logger.info(
        "Pipeline started for job %s (url=%s, initial_type=%s, resume=%s, webhook=%s)",
        job_id,
        url,
        initial_content_type,
        resume,
        effective_webhook,
    )

    try:
        # 1. INITIALIZE / RESUME JOB
        initial_stage = JobStage.INITIALIZED.value
        await job_repo.update_job(
            job_id,
            status=JobStatus.PROCESSING.value,
            stage=initial_stage,
            content_type=initial_content_type,
        )
        await dispatcher.dispatch(
            webhook_url=effective_webhook,
            event="job.stage_updated",
            job_id=job_id,
            status=JobStatus.PROCESSING.value,
            stage=initial_stage,
            data={"content_type": initial_content_type, "resumed": resume},
        )

        existing_record = await job_repo.get_job(job_id) if resume else None

        # -------------------------------------------------------------
        # 2. TWO-CHECK CLASSIFICATION & SCRAPING
        # -------------------------------------------------------------
        # We always run the unified InstagramScraper first to inspect page metadata,
        # detect progressive video CDN streams, and check for Carousel Next buttons (<button aria-label="Next">).
        scraped_metadata = existing_record.get("metadata") if (existing_record and existing_record.get("metadata")) else None
        if not scraped_metadata:
            logger.info("[Job %s] Stage 1: Inspecting page with InstagramScraper", job_id)
            scraper = get_instagram_scraper()
            scraped_metadata = await scraper.scrape(url)

        # SECOND CHECK: Check if the live page is a Carousel of images or a Reel/Video
        is_carousel = bool(scraped_metadata.get("is_carousel"))
        has_video = bool(scraped_metadata.get("video_url") or scraped_metadata.get("video_urls_candidates"))

        if is_carousel:
            logger.info(
                "[Job %s] SECOND CHECK: Detected Carousel of images (found Next button/dots/sidecar)! Routing to Carousel + PaddleOCR pipeline.",
                job_id,
            )
            post_scraper = get_instagram_post_scraper()
            post_metadata = await post_scraper.scrape(url)
            for k in ("username", "caption", "like_count_raw", "comment_count_raw"):
                if not post_metadata.get(k) and scraped_metadata.get(k):
                    post_metadata[k] = scraped_metadata[k]

            await _process_post_ocr(
                job_id=job_id,
                url=url,
                post_metadata=post_metadata,
                effective_webhook=effective_webhook,
                existing_record=existing_record,
            )

        elif has_video:
            logger.info(
                "[Job %s] SECOND CHECK: Detected Reel/Video stream (no Carousel Next button). Routing to Reel media pipeline.",
                job_id,
            )
            await _process_reel_media(
                job_id=job_id,
                url=url,
                metadata=scraped_metadata,
                effective_webhook=effective_webhook,
            )

        else:
            logger.info(
                "[Job %s] SECOND CHECK: Detected single image post (no video, no Next button). Routing to PaddleOCR pipeline.",
                job_id,
            )
            post_scraper = get_instagram_post_scraper()
            post_metadata = await post_scraper.scrape(url)
            for k in ("username", "caption", "like_count_raw", "comment_count_raw"):
                if not post_metadata.get(k) and scraped_metadata.get(k):
                    post_metadata[k] = scraped_metadata[k]

            await _process_post_ocr(
                job_id=job_id,
                url=url,
                post_metadata=post_metadata,
                effective_webhook=effective_webhook,
                existing_record=existing_record,
            )

    except Exception as exc:
        err_msg = str(exc)
        logger.exception("[Job %s] Pipeline encountered an error: %s", job_id, err_msg)

        await job_repo.update_job(
            job_id,
            status=JobStatus.FAILED.value,
            error=err_msg,
            completed=True,
            webhook_status="failed",
        )

        await dispatcher.dispatch(
            webhook_url=effective_webhook,
            event="job.failed",
            job_id=job_id,
            status=JobStatus.FAILED.value,
            stage=JobStage.INITIALIZED.value,
            error=err_msg,
        )
