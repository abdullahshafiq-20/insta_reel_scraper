from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseScraper(ABC):
    """Abstract interface for all scraper implementations."""

    @abstractmethod
    async def scrape(self, url: str, timeout_ms: Optional[int] = None, **kwargs: Any) -> Dict[str, Any]:
        """
        Scrape metadata and video CDN URLs for the given url.

        Returns a dict with keys:
            shortcode, url, username, caption, hashtags, mentions,
            like_count_raw, comment_count_raw, share_count_raw,
            video_url, video_urls_candidates, source
        """
        ...
