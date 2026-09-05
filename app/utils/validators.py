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


# Broad list of common TLDs to detect bare domains (e.g. github.com/user, bit.ly/123, cal.diy)
_COMMON_TLDS = (
    r"com|org|net|edu|gov|mil|int|"
    r"io|ai|co|dev|app|diy|tech|me|ly|link|site|store|online|xyz|info|biz|pro|club|top|"
    r"tv|fm|cc|gg|to|sh|is|so|vc|im|ws|"
    r"uk|us|ca|de|fr|in|pk|eu|au|ru|ch|it|nl|se|no|es|br|jp|kr|cn|sg|ae|sa|za"
)

_URL_PATTERN = re.compile(
    rf"(?:https?://|www\.)[^\s<>()\"'`]+"
    rf"|"
    rf"\b(?:[a-zA-Z0-9-]+\.)+(?:{_COMMON_TLDS})(?:/[^\s<>()\"'`]*)?",
    re.IGNORECASE,
)

_TRAILING_PUNCTUATION = ".,;:!?')]}'\">"


def extract_links(text: Optional[str]) -> List[str]:
    """
    Extract all web links / URLs from text (with or without http/https/www).
    Examples:
      - https://github.com/username/reponame
      - github.com/username/reponame
      - bit.ly/xyz123
      - amberstudent.com
      - cal.diy
    Deduplicates while preserving first-seen order.
    """
    if not text or not isinstance(text, str):
        return []

    matches = _URL_PATTERN.findall(text)
    results: List[str] = []
    seen = set()

    for raw in matches:
        cleaned = raw.strip(_TRAILING_PUNCTUATION)
        if cleaned.endswith("/"):
            cleaned = cleaned.rstrip("/")
        # If an email was caught like user@github.com, keep domain or valid url part
        if "@" in cleaned and not cleaned.startswith("http"):
            parts = cleaned.split("@", 1)
            cleaned = parts[1]

        if cleaned and len(cleaned) >= 4 and "." in cleaned:
            norm = cleaned.lower()
            if norm not in seen:
                seen.add(norm)
                results.append(cleaned)

    return results
