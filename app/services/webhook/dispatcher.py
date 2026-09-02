"""
app/services/webhook/dispatcher.py
-----------------------------------
Asynchronously dispatches webhook events to the configured webhook URL.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from app.config import settings

logger = logging.getLogger("insta.webhook")


class WebhookDispatcher:
    def __init__(self, max_retries: int = settings.WEBHOOK_MAX_RETRIES) -> None:
        self.max_retries = max_retries

    async def dispatch(
        self,
        webhook_url: Optional[str],
        event: str,
        job_id: str,
        status: str,
        stage: str,
        data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> bool:
        """
        Send a webhook event payload to the target URL with automatic retries.
        If webhook_url is empty, logs and returns False safely.
        """
        url = (webhook_url or settings.WEBHOOK_URL or "").strip()
        if not url:
            logger.debug("No webhook URL configured for job %s; skipping dispatch", job_id)
            return False

        payload: Dict[str, Any] = {
            "event": event,
            "job_id": job_id,
            "status": status,
            "stage": stage,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if data is not None:
            payload["data"] = data
        if error is not None:
            payload["error"] = error

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(
                    "Dispatching webhook event '%s' for job %s to %s (attempt %d/%d)",
                    event,
                    job_id,
                    url,
                    attempt,
                    self.max_retries,
                )
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(
                        url,
                        json=payload,
                        headers={"Content-Type": "application/json", "User-Agent": "InstaScraper-Webhook/2.0"},
                    )
                    if response.is_success:
                        logger.info("Webhook delivered successfully for job %s (status %d)", job_id, response.status_code)
                        return True
                    else:
                        logger.warning(
                            "Webhook endpoint returned status %d on attempt %d: %s",
                            response.status_code,
                            attempt,
                            response.text[:200],
                        )
            except Exception as exc:
                logger.warning("Webhook dispatch error on attempt %d for job %s: %s", attempt, job_id, exc)

        logger.error("Failed to deliver webhook for job %s after %d attempts", job_id, self.max_retries)
        return False


dispatcher = WebhookDispatcher()

