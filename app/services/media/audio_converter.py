"""
app/services/media/audio_converter.py
-------------------------------------
Extracts normalized 16kHz mono audio from video files using FFmpeg.
"""
import asyncio
import logging
import re
from pathlib import Path
from typing import Optional, Tuple

from app.config import settings

logger = logging.getLogger("insta.media.audio")


class AudioConverter:
    """Executes FFmpeg subprocesses to extract clean, normalized audio."""

    def __init__(self, storage_dir: Optional[str] = None) -> None:
        self.storage_dir = Path(storage_dir or settings.STORAGE_DIR) / "audio"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    async def extract_audio(self, video_path: str, job_id: str) -> Tuple[str, float]:
        output_file = self.storage_dir / f"{job_id}.mp3"
        logger.info("Extracting audio from %s to %s", video_path, output_file)

        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(video_path),
            "-vn",
            "-acodec", "libmp3lame",
            "-ar", "16000",
            "-ac", "1",
            "-b:a", "64k",
            str(output_file),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()
        stderr_text = stderr.decode(errors="replace")

        if process.returncode != 0:
            logger.error("FFmpeg conversion failed (exit %d): %s", process.returncode, stderr_text)
            raise RuntimeError(f"FFmpeg audio extraction failed: {stderr_text[-300:]}")

        if not output_file.exists() or output_file.stat().st_size == 0:
            raise RuntimeError("FFmpeg generated an empty audio file.")

        duration_seconds = 0.0
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", stderr_text)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            seconds = float(match.group(3))
            duration_seconds = round(hours * 3600 + minutes * 60 + seconds, 2)

        logger.info("Audio extracted successfully for job %s (duration: %.2fs)", job_id, duration_seconds)
        return str(output_file.resolve()), duration_seconds


audio_converter = AudioConverter()
