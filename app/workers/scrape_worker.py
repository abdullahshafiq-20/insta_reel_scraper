"""
app/workers/scrape_worker.py
----------------------------
Asynchronously orchestrates the multi-stage job processing pipeline:
1. Stage 1: Metadata Extraction (Playwright)
2. Stage 2: Media Download & FFmpeg Audio Conversion
3. Stage 3: Speech-to-Text Transcription via OpenAI Whisper ($0.0045/min cost calculation)
4. Stage 4: Result Aggregation, DB update, Cleanup, and Webhook Dispatch
"""
import logging
from pathlib import Path
from typing import Optional

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
from app.utils.validators import get_instagram_url_type

logger = logging.getLogger("insta.worker.pipeline")


async def process_scrape_job(
    job_id: str,
    url: str,
    webhook_url: Optional[str] = None,
    resume: bool = False,
) -> None:
    effective_webhook = (webhook_url or settings.WEBHOOK_URL or "").strip() or None
    content_type = get_instagram_url_type(url)
    logger.info("Pipeline started for job %s (url=%s, type=%s, resume=%s, webhook=%s)", job_id, url, content_type, resume, effective_webhook)

    video_path: Optional[str] = None
    audio_path: Optional[str] = None

    try:
        # 1. INITIALIZE / RESUME JOB
        initial_stage = JobStage.INITIALIZED.value
        await job_repo.update_job(
            job_id,
            status=JobStatus.PROCESSING.value,
            stage=initial_stage,
            content_type=content_type,
        )
        await dispatcher.dispatch(
            webhook_url=effective_webhook,
            event="job.stage_updated",
            job_id=job_id,
            status=JobStatus.PROCESSING.value,
            stage=initial_stage,
            data={"content_type": content_type, "resumed": resume},
        )

        # -------------------------------------------------------------
        # BRANCH A: INSTAGRAM POST / CAROUSEL PIPELINE + OCR
        # -------------------------------------------------------------
        if content_type == "post":
            existing_record = await job_repo.get_job(job_id) if resume else None
            post_metadata = existing_record.get("metadata") if existing_record else None

            # Stage 1: Extract post metadata and carousel images if needed
            if not post_metadata or not post_metadata.get("images"):
                logger.info("[Job %s] Running Post/Carousel scraper", job_id)
                post_scraper = get_instagram_post_scraper()
                post_metadata = await post_scraper.scrape(url)

                await job_repo.update_job(
                    job_id,
                    status=JobStatus.PROCESSING.value,
                    stage=JobStage.METADATA_EXTRACTED.value,
                    metadata=post_metadata,
                )
                await dispatcher.dispatch(
                    webhook_url=effective_webhook,
                    event="job.stage_updated",
                    job_id=job_id,
                    status=JobStatus.PROCESSING.value,
                    stage=JobStage.METADATA_EXTRACTED.value,
                    data={"metadata": post_metadata},
                )
            else:
                logger.info("[Job %s] Resuming post with %d existing images", job_id, len(post_metadata.get("images", [])))

            # Stage 2: PaddleOCR Per-Image Extraction (Incremental & Resumable)
            images = post_metadata.get("images", [])
            total_images = len(images) if images else 1

            existing_ocr = (existing_record.get("ocr") or {}) if existing_record else {}
            completed_slides: dict = {
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

                # Immediately commit partial OCR state to database
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

                # Real-time webhook progress for this image index
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

            # Stage 3: Final Aggregation & Completion
            all_slides = sorted(completed_slides.values(), key=lambda x: x["index"])
            combined_text = "\n\n".join(
                [f"--- Image {s['index']} ---\n{s['full_text']}" for s in all_slides if s.get("full_text")]
            )
            final_ocr_payload = {
                "total_images": total_images,
                "combined_text": combined_text,
                "slides": all_slides,
            }
            final_post_data = {
                "metadata": post_metadata,
                "ocr": final_ocr_payload,
            }

            await job_repo.update_job(
                job_id,
                status=JobStatus.COMPLETED.value,
                stage=JobStage.FINISHED.value,
                ocr=final_ocr_payload,
                completed=True,
                webhook_status="sent",
            )

            logger.info(
                "[Job %s] Post pipeline with OCR completed successfully (%d images). Emitting final webhook",
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
            return

        # -------------------------------------------------------------
        # BRANCH B: INSTAGRAM REEL PIPELINE (Original & Untouched)
        # -------------------------------------------------------------
        # 2. STAGE 1: METADATA EXTRACTION
        logger.info("[Job %s] Stage 1: Extracting Instagram metadata", job_id)
        scraper = get_instagram_scraper()
        metadata = await scraper.scrape(url)

        await job_repo.update_job(
            job_id,
            status=JobStatus.PROCESSING.value,
            stage=JobStage.METADATA_EXTRACTED.value,
            metadata=metadata,
        )
        await dispatcher.dispatch(
            webhook_url=effective_webhook,
            event="job.stage_updated",
            job_id=job_id,
            status=JobStatus.PROCESSING.value,
            stage=JobStage.METADATA_EXTRACTED.value,
            data={"metadata": metadata},
        )

        # 3. STAGE 2: MEDIA DOWNLOAD & AUDIO CONVERSION
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

        # 4. STAGE 3: TRANSCRIPTION VIA OPENAI (WITH COST CALCULATION)
        logger.info("[Job %s] Stage 3: Transcribing audio via OpenAI", job_id)
        transcription_result = await openai_transcription_service.transcribe(
            audio_path=audio_path,
            duration_seconds=duration_seconds,
        )

        # 5. STAGE 4: COMPLETION & AGGREGATION
        final_payload = {
            "metadata": metadata,
            "transcription": transcription_result,
        }

        await job_repo.update_job(
            job_id,
            status=JobStatus.COMPLETED.value,
            stage=JobStage.FINISHED.value,
            transcription=transcription_result,
            completed=True,
            webhook_status="sent",
        )

        logger.info("[Job %s] Pipeline finished successfully. Emitting final webhook", job_id)
        await dispatcher.dispatch(
            webhook_url=effective_webhook,
            event="job.completed",
            job_id=job_id,
            status=JobStatus.COMPLETED.value,
            stage=JobStage.FINISHED.value,
            data=final_payload,
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
