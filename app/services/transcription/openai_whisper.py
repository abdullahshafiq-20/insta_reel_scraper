"""
app/services/transcription/openai_whisper.py
--------------------------------------------
Transcribes audio using OpenAI's Audio Transcription API.
Calculates duration and estimated cost ($0.0045/min) and packages structured segments.
"""
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from app.config import settings
from app.services.transcription.base import BaseTranscriptionService

logger = logging.getLogger("insta.transcription.openai")


class OpenAITranscriptionService(BaseTranscriptionService):
    """OpenAI-backed speech-to-text service."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        cost_per_minute: Optional[float] = None,
    ) -> None:
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model or settings.OPENAI_TRANSCRIPTION_MODEL
        self.cost_per_minute = cost_per_minute or settings.TRANSCRIPTION_COST_PER_MINUTE

    async def transcribe(
        self,
        audio_path: str,
        duration_seconds: Optional[float] = None,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Uploads audio to OpenAI audio transcriptions endpoint and returns
        transcribed text, language, segments, duration, and calculated cost.
        """
        if not self.api_key:
            raise ValueError(
                "OPENAI_API_KEY is not configured. Please set it in .env to enable audio transcription."
            )

        file_path = Path(audio_path)
        if not file_path.exists() or file_path.stat().st_size == 0:
            raise FileNotFoundError(f"Audio file does not exist or is empty: {audio_path}")

        logger.info("Transcribing %s using model %s", file_path.name, self.model)

        url = "https://api.openai.com/v1/audio/transcriptions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        data = {
            "model": self.model,
            "response_format": "verbose_json",
        }
        if language:
            data["language"] = language

        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(file_path, "rb") as f:
                files = {
                    "file": (file_path.name, f, "audio/mpeg"),
                }
                response = await client.post(url, headers=headers, data=data, files=files)

        if not response.is_success:
            err_text = response.text
            logger.error("OpenAI transcription API returned %d: %s", response.status_code, err_text)
            raise RuntimeError(f"OpenAI transcription failed ({response.status_code}): {err_text}")

        result = response.json()

        # Extract duration
        detected_duration = result.get("duration")
        if detected_duration is not None and float(detected_duration) > 0:
            actual_duration = float(detected_duration)
        else:
            actual_duration = duration_seconds or 0.0

        duration_minutes = round(actual_duration / 60.0, 4)
        cost_usd = round(duration_minutes * self.cost_per_minute, 6)

        return {
            "provider": "openai",
            "model": self.model,
            "text": result.get("text", "").strip(),
            "language": result.get("language", "unknown"),
            "duration_seconds": round(actual_duration, 2),
            "duration_minutes": duration_minutes,
            "cost_usd": cost_usd,
            "rate_per_minute": self.cost_per_minute,
            "segments": result.get("segments", []),
        }


openai_transcription_service = OpenAITranscriptionService()

