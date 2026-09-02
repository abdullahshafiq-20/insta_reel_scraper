"""
app/services/scraper/instagram_scraper.py
------------------------------------------
Stage 1 — Metadata Extraction.

Ported from the working v1.py / scraper.py proof-of-concept; adapted to:
 • Use the shared PlaywrightBrowserPool (no per-job browser spawn)
 • Import utils from app.utils.validators
 • Expose a clean async `scrape()` method via BaseScraper
 • Stay 100 % in-memory (no file I/O)
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.config import settings
from app.services.scraper.base import BaseScraper
from app.services.scraper.browser_pool import PlaywrightBrowserPool, browser_pool
from app.utils.validators import extract_shortcode, parse_hashtags, parse_mentions

logger = logging.getLogger("insta.scraper")

# ---------------------------------------------------------------------------
# JavaScript snippet injected into the live DOM
# ---------------------------------------------------------------------------
_JS_EXTRACTOR = r"""
() => {
  const result = {
    username: null,
    caption: null,
    like_count_raw: null,
    comment_count_raw: null,
    share_count_raw: null,
    all_video_sources: []
  };

  // 1. Dismiss login dialog if present
  try {
    const closeBtns = Array.from(
      document.querySelectorAll('div[role="dialog"] button, svg[aria-label="Close"]')
    );
    for (const b of closeBtns) {
      const btn = b.tagName === 'BUTTON' ? b : b.closest('button, div[role="button"]');
      if (btn) btn.click();
    }
  } catch (_) {}

  // 2. Expand "… more" so we get the full caption
  try {
    for (const btn of document.querySelectorAll(
      'span[role="button"], button, div[role="button"], a[role="button"]'
    )) {
      const t = (btn.textContent || '').trim().toLowerCase();
      if (t === 'more' || t === '... more' || t.endsWith('more')) btn.click();
    }
  } catch (_) {}

  // 3. Username — first header link that isn't a nav item
  try {
    const skip = new Set(['sign up','log in','login','signup','instagram','home','explore','reels','threads','meta']);
    for (const a of document.querySelectorAll(
      'header a[role="link"], header a[href^="/"], article header a, main header a'
    )) {
      const txt = (a.textContent || '').trim();
      const href = a.getAttribute('href') || '';
      if (txt && !skip.has(txt.toLowerCase()) && !href.includes('/accounts/')) {
        result.username = txt;
        break;
      }
    }
  } catch (_) {}

  // 4. Caption — span with known Instagram caption CSS
  try {
    for (const span of document.querySelectorAll(
      'main span, article span, div[role="dialog"] span, section span'
    )) {
      const style = span.getAttribute('style') || '';
      const cls   = span.className || '';
      const isCaption =
        /line-height:\s*18px/i.test(style) ||
        (cls.includes('x193iq5w') && cls.includes('xeuugli') && cls.includes('x13faqbe'));
      if (isCaption) {
        const text = (span.innerText || span.textContent || '').trim();
        if (text.length > 3 && !/^[\d,.]+\s*[KMBkmb]?$/.test(text) && !text.startsWith('Never miss')) {
          result.caption = text;
          break;
        }
      }
    }
  } catch (_) {}

  // 5. Engagement counters (Likes / Comments / Shares)
  try {
    const svgMatch = (svg, re) => re.test(svg.getAttribute('aria-label') || '') ||
                                  re.test(svg.querySelector('title')?.textContent || '');
    const siblingCount = svg => {
      let cur = svg;
      while (cur && cur.parentElement) {
        const p = cur.parentElement;
        if (p.children.length > 1 && cur.nextElementSibling) {
          const t = (cur.nextElementSibling.innerText || cur.nextElementSibling.textContent || '').trim();
          if (/^[\d,.]+\s*[KMBkmb]?$/.test(t)) return t;
        }
        if (['SECTION','MAIN','BODY','ARTICLE'].includes(p.tagName)) break;
        cur = p;
      }
      return null;
    };
    const svgs = Array.from(document.querySelectorAll('svg'));
    for (const s of svgs) {
      if ((svgMatch(s, /^like$/i) || svgMatch(s, /^unlike$/i)) && !result.like_count_raw)
        result.like_count_raw = siblingCount(s);
    }
    for (const s of svgs) {
      if (svgMatch(s, /^comment$/i) && !result.comment_count_raw)
        result.comment_count_raw = siblingCount(s);
    }
    for (const s of svgs) {
      if (svgMatch(s, /^share/i) && !result.share_count_raw)
        result.share_count_raw = siblingCount(s);
    }
  } catch (_) {}

  // 6. Video source URLs from DOM
  try {
    for (const v of document.querySelectorAll('video')) {
      const src = v.currentSrc || v.src || v.getAttribute('src');
      if (src?.startsWith('http')) result.all_video_sources.push(src);
      for (const s of v.querySelectorAll('source')) {
        const ss = s.src || s.getAttribute('src');
        if (ss?.startsWith('http')) result.all_video_sources.push(ss);
      }
    }
  } catch (_) {}

  return result;
}
"""


# ---------------------------------------------------------------------------
# Pure-Python HTML / JSON metadata parser (no Playwright dependency)
# ---------------------------------------------------------------------------

def _parse_page_data(html: str, shortcode: str, url: str, dom: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge OpenGraph / Twitter meta-tags, embedded video_versions JSON,
    and live DOM data into a single clean metadata dict.
    """
    result: Dict[str, Any] = {
        "shortcode": shortcode,
        "url": url,
        "username": None,
        "caption": None,
        "hashtags": [],
        "mentions": [],
        "like_count_raw": None,
        "comment_count_raw": None,
        "share_count_raw": dom.get("share_count_raw"),
        "video_url": None,
        "video_urls_candidates": [],
        "source": "headless_browser_dom",
    }

    # --- Meta tags ---
    meta_desc = meta_og_url = meta_tw_title = None
    for m in re.finditer(r"<meta\s+([^>]+)>", html):
        attrs = m.group(1)
        p = re.search(r'(?:property|name)=["\']([^"\']+)["\']', attrs)
        c = re.search(r'content=["\'](.*?)["\']', attrs, re.DOTALL)
        if not (p and c):
            continue
        prop = p.group(1).lower()
        val  = c.group(1).replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
        if prop in ("og:description", "description"):
            meta_desc = val
        elif prop == "og:url":
            meta_og_url = val
        elif prop == "twitter:title":
            meta_tw_title = val

    # Username
    if meta_og_url:
        m = re.search(r"instagram\.com/([^/]+)/(?:reel|p|reels)/", meta_og_url)
        if m and m.group(1) not in ("reel", "p", "reels", "explore", "stories"):
            result["username"] = m.group(1)
    if not result["username"] and meta_tw_title:
        m = re.search(r"\(@([a-zA-Z0-9._]+)\)", meta_tw_title)
        if m:
            result["username"] = m.group(1)
    if not result["username"] and meta_desc:
        m = re.search(r"-\s*([a-zA-Z0-9._]+)\s+on\s+", meta_desc)
        if m:
            result["username"] = m.group(1)
    if not result["username"]:
        result["username"] = dom.get("username")

    # Caption
    if meta_desc:
        m = re.search(r':\s*[""](.*)[""][.\s]*$', meta_desc, re.DOTALL)
        if m:
            result["caption"] = m.group(1).strip()
    if not result["caption"]:
        result["caption"] = dom.get("caption")

    # Stats
    if meta_desc:
        m = re.search(r"([\d,.]+\s*[KMBkmb]?)\s+likes", meta_desc, re.I)
        if m:
            result["like_count_raw"] = m.group(1)
        m = re.search(r"([\d,.]+\s*[KMBkmb]?)\s+comments", meta_desc, re.I)
        if m:
            result["comment_count_raw"] = m.group(1)
    if not result["like_count_raw"]:
        result["like_count_raw"] = dom.get("like_count_raw")
    if not result["comment_count_raw"]:
        result["comment_count_raw"] = dom.get("comment_count_raw")

    # Video URLs — embedded JSON script first (highest quality / most stable)
    progressive: List[str] = []
    dash: List[str] = []
    for vm in re.finditer(r'"video_versions":\s*(\[[^\]]+\])', html):
        raw = vm.group(1).replace(r"\/", "/").replace(r"\u0026", "&")
        try:
            for item in json.loads(raw):
                v = item.get("url", "")
                if not v:
                    continue
                (dash if "bytestart=" in v else progressive).append(v)
        except Exception:
            pass
    # Then DOM sources
    for src in dom.get("all_video_sources", []):
        (dash if "bytestart=" in src else progressive).append(src)

    # Deduplicate while preserving order (progressive first = best for direct play)
    seen: set = set()
    candidates: List[str] = []
    for u in progressive + dash:
        if u not in seen:
            seen.add(u)
            candidates.append(u)

    result["video_urls_candidates"] = candidates
    result["video_url"] = candidates[0] if candidates else None

    # Caption JSON fallback
    if not result["caption"]:
        for cm in re.finditer(r'"caption":\s*\{\s*"text":\s*"([^"]+)"', html):
            try:
                text = cm.group(1).encode().decode("unicode_escape")
                if len(text) > 3:
                    result["caption"] = text
                    break
            except Exception:
                pass

    # Enrich caption
    if result["caption"]:
        result["hashtags"] = parse_hashtags(result["caption"])
        result["mentions"] = parse_mentions(result["caption"])

    return result


# ---------------------------------------------------------------------------
# InstagramScraper — Stage 1 service
# ---------------------------------------------------------------------------

class InstagramScraper(BaseScraper):
    """
    Playwright-based Instagram Reel / Post scraper.

    Uses the shared browser pool so the Chromium process is not spawned /
    torn down per request.  Operates 100 % in-memory.
    """

    def __init__(self, pool: Optional[PlaywrightBrowserPool] = None) -> None:
        self._pool = pool or browser_pool

    async def scrape(self, url: str, timeout_ms: Optional[int] = None, **_: Any) -> Dict[str, Any]:
        timeout = timeout_ms or settings.TIMEOUT_MS
        shortcode = extract_shortcode(url)
        logger.info("Scraping %s (shortcode=%s)", url, shortcode)

        async with self._pool.borrow_page() as page:
            await page.goto(url, wait_until="networkidle", timeout=timeout)

            # Give dynamic content a moment to render
            try:
                await page.wait_for_selector("video, main, article", timeout=5_000)
            except Exception:
                pass
            await page.wait_for_timeout(2_000)

            html = await page.content()
            dom  = await page.evaluate(_JS_EXTRACTOR)

        result = _parse_page_data(html, shortcode, url, dom)
        logger.info(
            "Scraped shortcode=%s username=%s has_video=%s",
            shortcode,
            result.get("username"),
            bool(result.get("video_url")),
        )
        return result


# Module-level singleton used by the API
_scraper: Optional[InstagramScraper] = None


def get_instagram_scraper() -> InstagramScraper:
    global _scraper
    if _scraper is None:
        _scraper = InstagramScraper()
    return _scraper
