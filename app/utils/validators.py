import re
from typing import List, Optional
from urllib.parse import urlparse

_VALID_HOSTS = {"www.instagram.com", "instagram.com", "instagr.am"}
_REEL_SEGMENTS = {"reel", "reels", "p", "tv"}


def is_valid_instagram_url(url: str) -> bool:
    """Return True if url points to a public Instagram Reel / Post."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False
    if parsed.netloc not in _VALID_HOSTS:
        return False
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if not parts:
        return False
    for seg in parts:
        if seg in _REEL_SEGMENTS:
            return True
    return False


def get_instagram_url_type(url: str) -> str:
    """
    Classify Instagram URL as 'reel' or 'post'.
    Returns 'post' if path segment is 'p', otherwise 'reel' (reel, reels, tv).
    """
    try:
        path = urlparse(url.strip()).path.strip("/").lower()
        parts = [p for p in path.split("/") if p]
        for part in parts:
            if part in ("reel", "reels", "tv"):
                return "reel"
            if part == "p":
                return "post"
    except Exception:
        pass
    return "reel"


def extract_shortcode(url: str) -> str:
    """Extract the unique Instagram shortcode from a Reel / Post URL."""
    path = urlparse(url).path.strip("/")
    parts = [p for p in path.split("/") if p]
    for i, part in enumerate(parts):
        if part in _REEL_SEGMENTS and i + 1 < len(parts):
            return parts[i + 1]
    if parts:
        return parts[-1]
    raise ValueError(f"Cannot extract shortcode from URL: {url!r}")


def parse_hashtags(text: Optional[str]) -> List[str]:
    """Return list of hashtag words (without #) found in text."""
    if not text:
        return []
    return re.findall(r"#(\w+)", text)


def parse_mentions(text: Optional[str]) -> List[str]:
    """Return list of mentioned handles (without @) found in text."""
    if not text:
        return []
    return re.findall(r"@([\w.]+)", text)
