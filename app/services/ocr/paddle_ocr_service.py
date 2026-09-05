"""
app/services/ocr/paddle_ocr_service.py
--------------------------------------
Optical Character Recognition service wrapping PaddleOCR.
Downloads images and runs OCR in an asynchronous background thread.
"""
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger("insta.ocr")


class PaddleOCRService:
    """Wrapper around PaddleOCR for asynchronous image text extraction."""

    def __init__(self, lang: str = "en") -> None:
        self.lang = lang
        self._ocr = None
        self._initialized = False
        self._lock = asyncio.Lock()
        self.storage_dir = Path(settings.STORAGE_DIR) / "images"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_ocr_instance(self):
        if self._ocr is None:
            logger.info("Initializing PaddleOCR engine (lang=%s)...", self.lang)
            try:
                from paddleocr import PaddleOCR
                self._ocr = PaddleOCR(use_angle_cls=True, lang=self.lang)
                try:
                    self._ocr = PaddleOCR(use_textline_orientation=True, lang=self.lang)
                except TypeError:
                    self._ocr = PaddleOCR(use_angle_cls=True, lang=self.lang)
                logger.info("PaddleOCR engine initialized successfully.")
            except Exception as exc:
                logger.error("Failed to initialize PaddleOCR: %s", exc)
                raise RuntimeError(f"PaddleOCR initialization failed: {exc}")
        return self._ocr

    def _run_ocr_sync(self, image_path: str) -> Dict[str, Any]:
        """Runs OCR synchronously on local image path."""
        ocr = self._get_ocr_instance()
        raw = None
        try:
            raw = ocr.ocr(image_path, cls=True)
        except TypeError:
            raw = ocr.ocr(image_path)
            if hasattr(ocr, "predict"):
                raw = ocr.predict(image_path)
            else:
                raw = ocr.ocr(image_path)
        except Exception:
            try:
                raw = ocr.ocr(image_path)
            except Exception as exc:
                logger.error("Error executing OCR on %s: %s", image_path, exc)
                raw = None

        texts: List[str] = []
        scores: List[float] = []

        if raw:
            # Format A: dictionary response (PaddleX style: {'res': {'rec_texts': [...], 'rec_scores': [...]}})
            if isinstance(raw, dict) and "res" in raw:
                res_data = raw["res"]
                rec_texts = res_data.get("rec_texts", [])
                rec_scores = res_data.get("rec_scores", [])
                texts = [str(t) for t in rec_texts if t]
                scores = [round(float(s), 4) for s in rec_scores] if rec_scores is not None else []
            # Format B: list containing dict
            elif isinstance(raw, list) and len(raw) > 0 and isinstance(raw[0], dict) and "res" in raw[0]:
                res_data = raw[0]["res"]
                texts = [str(t) for t in res_data.get("rec_texts", []) if t]
                scores = [round(float(s), 4) for s in res_data.get("rec_scores", [])]
            # Format C: classic list of [[box, (text, score)], ...]
            elif isinstance(raw, list) and len(raw) > 0 and isinstance(raw[0], list):
                for line in raw[0]:
                    if line and len(line) >= 2 and isinstance(line[1], (tuple, list)):
                        txt, score = line[1][0], line[1][1]
                        if txt:
                            texts.append(str(txt))
                            scores.append(round(float(score), 4))
        if raw is not None:
            raw_list = raw if isinstance(raw, (list, tuple)) else [raw]

            for item in raw_list:
                # 1. PaddleOCR 3.x / PaddleX OCRResult object or dict
                rec_texts = None
                rec_scores = None

                if hasattr(item, "get"):
                    rec_texts = item.get("rec_texts")
                    rec_scores = item.get("rec_scores")
                    if rec_texts is None and "res" in item:
                        rec_texts = item["res"].get("rec_texts")
                        rec_scores = item["res"].get("rec_scores")

                if rec_texts is None and hasattr(item, "rec_texts"):
                    rec_texts = getattr(item, "rec_texts", None)
                    rec_scores = getattr(item, "rec_scores", None)

                if rec_texts:
                    for t in rec_texts:
                        if t:
                            texts.append(str(t).strip())
                    if rec_scores:
                        for s in rec_scores:
                            try:
                                scores.append(round(float(s), 4))
                            except Exception:
                                pass
                    continue

                # 2. Classic PaddleOCR 2.x format: [[box, (text, score)], ...]
                if isinstance(item, list):
                    for line in item:
                        if line and len(line) >= 2 and isinstance(line[1], (tuple, list)):
                            txt, score = line[1][0], line[1][1]
                            if txt:
                                texts.append(str(txt).strip())
                                try:
                                    scores.append(round(float(score), 4))
                                except Exception:
                                    pass

        full_text = " ".join(texts).strip()
        return {
            "texts": texts,
            "full_text": full_text,
            "scores": scores,
            "word_count": len(full_text.split()) if full_text else 0,
        }

    async def extract_text_from_url(
        self,
        image_url: str,
        job_id: str,
        index: int,
        timeout_seconds: float = 30.0,
    ) -> Dict[str, Any]:
        """
        Downloads image from CDN and executes PaddleOCR asynchronously.
        Returns parsed texts, full combined text, and confidence scores.
        """
        temp_file = self.storage_dir / f"{job_id}_{index}.jpg"
        logger.info("[Job %s] Downloading image %d for OCR from %s", job_id, index, image_url[:80])

        headers = {
            "User-Agent": settings.USER_AGENT,
            "Accept": "image/*,*/*",
            "Referer": "https://www.instagram.com/",
        }

        # 1. Download image stream
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=timeout_seconds) as client:
            response = await client.get(image_url)
            if not response.is_success:
                raise RuntimeError(f"Failed to download image {index} (HTTP {response.status_code})")
            temp_file.write_bytes(response.content)

        # 2. Run OCR in non-blocking thread
        logger.info("[Job %s] Running PaddleOCR on image %d (%d bytes)", job_id, index, temp_file.stat().st_size)
        ocr_result = await asyncio.to_thread(self._run_ocr_sync, str(temp_file))

        # 3. Cleanup temp file if configured
        if settings.CLEANUP_TEMP_FILES:
            try:
                temp_file.unlink(missing_ok=True)
            except Exception:
                pass

        logger.info(
            "[Job %s] OCR completed for image %d: found %d text elements (%d words)",
            job_id,
            index,
            len(ocr_result["texts"]),
            ocr_result["word_count"],
        )

        return {
            "index": index,
            "image_url": image_url,
            "texts": ocr_result["texts"],
            "full_text": ocr_result["full_text"],
            "scores": ocr_result["scores"],
            "word_count": ocr_result["word_count"],
        }


paddle_ocr_service = PaddleOCRService()

