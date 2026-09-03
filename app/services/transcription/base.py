from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseTranscriptionService(ABC):
    """Abstract interface for speech-to-text transcription engines."""

    @abstractmethod
    async def transcribe(
        self,
        audio_path: str,
        duration_seconds: Optional[float] = None,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Transcribes the given audio file.
        Returns a dict containing text, language, duration, cost, and segments.
        """
        ...

