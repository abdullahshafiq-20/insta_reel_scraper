"""
app/services/media/downloader.py
--------------------------------
Streams and downloads progressive MP4 video files directly from CDN URLs.
"""
import logging
from pathlib import Path
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger("insta.media.downloader")


class MediaDownloader:
    """Downloads media files from CDN URLs to local storage."""

    def __init__(self, storage_dir: Optional[str] = None) -> None:
        self.storage_dir = Path(storage_dir or settings.STORAGE_DIR) / "video"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    async def download_video(self, url: str, job_id: str, timeout_seconds: float = 60.0) -> str:
        output_file = self.storage_dir / f"{job_id}.mp4"
        logger.info("Downloading video for job %s to %s", job_id, output_file)

        headers = {
            "User-Agent": settings.USER_AGENT,
            "Accept": "*/*",
            "Referer": "https://www.instagram.com/",
        }

        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=timeout_seconds) as client:
            async with client.stream("GET", url) as response:
                if not response.is_success:
                    raise RuntimeError(f"Failed to download video stream. HTTP {response.status_code} from CDN.")

                with open(output_file, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        if chunk:
                            f.write(chunk)

        file_size = output_file.stat().st_size
        if file_size == 0:
            output_file.unlink(missing_ok=True)
            raise RuntimeError(f"Downloaded video file for job {job_id} is 0 bytes.")

        logger.info("Downloaded video for job %s successfully (%d bytes)", job_id, file_size)
        return str(output_file.resolve())


downloader = MediaDownloader()
