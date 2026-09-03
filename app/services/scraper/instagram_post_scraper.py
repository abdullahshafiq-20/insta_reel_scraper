"""
app/services/scraper/instagram_post_scraper.py
----------------------------------------------
Instagram Post & Multi-Image Carousel Scraper.

Strictly follows POSITIONAL, STRUCTURAL, and EMBEDDED JSON extraction.
Does NOT rely on fragile, obfuscated CSS class names.

Extracts:
• shortcode, url, post_type: 'post'
• username, caption, hashtags, mentions
• like_count_raw, comment_count_raw
• total_images count
• images array with index, src (CDN URL), and alt (description/accessibility text)
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.config import settings
from app.services.scraper.base import BaseScraper
from app.services.scraper.browser_pool import PlaywrightBrowserPool, browser_pool
from app.utils.validators import extract_shortcode, parse_hashtags, parse_mentions

logger = logging.getLogger("insta.post_scraper")

# ---------------------------------------------------------------------------
# JavaScript snippet for DOM metadata & active media extraction (NO class names)
# ---------------------------------------------------------------------------
_JS_POST_EXTRACTOR = r"""
() => {
  const result = {
    username: null,
    caption: null,
    like_count_raw: null,
    comment_count_raw: null,
    total_dots: 0,
    has_next_button: false,
    active_image: null
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

  // 2. Expand "... more" in caption
  try {
    for (const btn of document.querySelectorAll(
      'span[role="button"], button, div[role="button"], a[role="button"]'
    )) {
      const t = (btn.textContent || '').trim().toLowerCase();
      if (t === 'more' || t === '... more' || t.endsWith('more')) btn.click();
    }
  } catch (_) {}

  // 3. Username — positional: first link in header that isn't navigation
  try {
    const skip = new Set(['sign up','log in','login','signup','instagram','home','explore','reels','threads','meta']);
    for (const a of document.querySelectorAll(
      'article header a, main header a, header a[role="link"], header a[href^="/"]'
    )) {
      const txt = (a.textContent || '').trim();
      const href = a.getAttribute('href') || '';
      if (txt && !skip.has(txt.toLowerCase()) && !href.includes('/accounts/')) {
        result.username = txt;
        break;
      }
    }
  } catch (_) {}

  // 4. Caption — span inside main/article with content
  try {
    for (const span of document.querySelectorAll('article span, main span, section span')) {
      const style = span.getAttribute('style') || '';
      const text = (span.innerText || span.textContent || '').trim();
      if (
        /line-height:\s*18px/i.test(style) ||
        (text.length > 5 && !/^[\d,.]+\s*[KMBkmb]?$/.test(text) && !text.startsWith('Never miss'))
      ) {
        if (!span.closest('header') && !span.closest('nav')) {
          result.caption = text;
          break;
        }
      }
    }
  } catch (_) {}

  // 5. Engagement counters — SVG traversal by aria-label
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
    for (const s of document.querySelectorAll('svg')) {
      if ((svgMatch(s, /^like$/i) || svgMatch(s, /^unlike$/i)) && !result.like_count_raw)
        result.like_count_raw = siblingCount(s);
      if (svgMatch(s, /^comment$/i) && !result.comment_count_raw)
        result.comment_count_raw = siblingCount(s);
    }
  } catch (_) {}

  // 6. Detect Carousel dots by structure (position-based: row of small sibling dot divs)
  try {
    const mediaContainer = document.querySelector('article, main');
    if (mediaContainer) {
      // Look for a parent holding 2+ small identical elements (< 20px size)
      const candidates = Array.from(mediaContainer.querySelectorAll('div'));
      for (const parent of candidates) {
        const children = Array.from(parent.children);
        if (children.length >= 2 && children.length <= 20) {
          const first = children[0];
          const w = first.offsetWidth || parseInt(window.getComputedStyle(first).width);
          const h = first.offsetHeight || parseInt(window.getComputedStyle(first).height);
          if (w > 0 && w <= 20 && h > 0 && h <= 20) {
            result.total_dots = children.length;
            break;
          }
        }
      }
    }
  } catch (_) {}

  // 7. Check for Next button (indicates carousel)
  try {
    const nextBtn = document.querySelector(
      'button[aria-label*="Next" i], button[aria-label*="next" i], svg[aria-label*="Next" i]'
    );
    if (nextBtn) result.has_next_button = true;
  } catch (_) {}

  // 8. Extract currently visible / active main image
  try {
    const imgs = Array.from(document.querySelectorAll('article img, main img'));
    let bestImg = null;
    let maxArea = 0;

    for (const img of imgs) {
      // Skip header profile pictures or icons
      if (img.closest('header') || img.closest('nav')) continue;
      const w = img.naturalWidth || img.offsetWidth || 0;
      const h = img.naturalHeight || img.offsetHeight || 0;
      // Skip small icons or avatars (< 120px)
      if (w > 0 && w < 120 && h > 0 && h < 120) continue;

      const src = img.currentSrc || img.src || img.getAttribute('src');
      if (src && src.startsWith('http')) {
        const area = (w || 300) * (h || 300);
        if (area > maxArea) {
          maxArea = area;
          bestImg = {
            src: src,
            alt: img.getAttribute('alt') || null
          };
        }
      }
    }
    result.active_image = bestImg;
  } catch (_) {}

  return result;
}
"""


# ---------------------------------------------------------------------------
# SSR JSON & HTML Parser
# ---------------------------------------------------------------------------

def _extract_embedded_carousel(html: str) -> List[Dict[str, Any]]:
    """
    Parses SSR embedded GraphQL JSON objects (edge_sidecar_to_children / carousel_media)
    to deterministically extract all carousel images, CDN URLs, and alt captions.
    """
    images: List[Dict[str, Any]] = []

    # Pattern 1: edge_sidecar_to_children (standard Instagram GraphQL carousel)
    match = re.search(r'"edge_sidecar_to_children":\s*\{\s*"edges":\s*(\[[^\]]+\])', html)
    if match:
        try:
            edges = json.loads(match.group(1))
            for i, edge in enumerate(edges, start=1):
                node = edge.get("node", {})
                src = node.get("display_url") or node.get("display_src")
                alt = node.get("accessibility_caption")
                if src:
                    images.append({
                        "index": i,
                        "src": src,
                        "alt": alt,
                    })
            if images:
                return images
        except Exception:
            pass

    # Pattern 2: carousel_media (Instagram API JSON format)
    match2 = re.search(r'"carousel_media":\s*(\[[^\]]+\])', html)
    if match2:
        try:
            items = json.loads(match2.group(1))
            for i, item in enumerate(items, start=1):
                img_vers = item.get("image_versions2", {}).get("candidates", [])
                src = img_vers[0].get("url") if img_vers else item.get("display_url")
                alt = item.get("accessibility_caption")
                if src:
                    images.append({
                        "index": i,
                        "src": src,
                        "alt": alt,
                    })
            if images:
                return images
        except Exception:
            pass

    return images


def _parse_post_meta_tags(html: str) -> Dict[str, Any]:
    """Extracts OpenGraph / Twitter meta-tags for username, stats, and caption."""
    meta_info: Dict[str, Any] = {
        "username": None,
        "caption": None,
        "like_count_raw": None,
        "comment_count_raw": None,
    }
    meta_desc = meta_og_url = meta_tw_title = None

    for m in re.finditer(r"<meta\s+([^>]+)>", html):
        attrs = m.group(1)
        p = re.search(r'(?:property|name)=["\']([^"\']+)["\']', attrs)
        c = re.search(r'content=["\'](.*?)["\']', attrs, re.DOTALL)
        if not (p and c):
            continue
        prop = p.group(1).lower()
        val = c.group(1).replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
        if prop in ("og:description", "description"):
            meta_desc = val
        elif prop == "og:url":
            meta_og_url = val
        elif prop == "twitter:title":
            meta_tw_title = val

    # Username
    if meta_og_url:
        m = re.search(r"instagram\.com/([^/]+)/(?:p|reel|reels)/", meta_og_url)
        if m and m.group(1) not in ("p", "reel", "reels", "explore"):
            meta_info["username"] = m.group(1)
    if not meta_info["username"] and meta_tw_title:
        m = re.search(r"\(@([a-zA-Z0-9._]+)\)", meta_tw_title)
        if m:
            meta_info["username"] = m.group(1)
    if not meta_info["username"] and meta_desc:
        m = re.search(r"-\s*([a-zA-Z0-9._]+)\s+on\s+", meta_desc)
        if m:
            meta_info["username"] = m.group(1)

    # Caption
    if meta_desc:
        m = re.search(r':\s*[""](.*)[""][.\s]*$', meta_desc, re.DOTALL)
        if m:
            meta_info["caption"] = m.group(1).strip()

    # Engagement
    if meta_desc:
        m = re.search(r"([\d,.]+\s*[KMBkmb]?)\s+likes", meta_desc, re.I)
        if m:
            meta_info["like_count_raw"] = m.group(1)
        m = re.search(r"([\d,.]+\s*[KMBkmb]?)\s+comments", meta_desc, re.I)
        if m:
            meta_info["comment_count_raw"] = m.group(1)

    return meta_info


# ---------------------------------------------------------------------------
# InstagramPostScraper Class
# ---------------------------------------------------------------------------

class InstagramPostScraper(BaseScraper):
    """
    Playwright-based Instagram Post & Multi-Image Carousel Scraper.
    Uses positional DOM & embedded SSR JSON (no obfuscated class names).
    """

    def __init__(self, pool: Optional[PlaywrightBrowserPool] = None) -> None:
        self._pool = pool or browser_pool

    async def scrape(self, url: str, timeout_ms: Optional[int] = None, **_: Any) -> Dict[str, Any]:
        timeout = timeout_ms or settings.TIMEOUT_MS
        shortcode = extract_shortcode(url)
        # Clean base URL without query parameters
        clean_url = f"https://www.instagram.com/p/{shortcode}/"
        logger.info("Scraping Instagram Post %s (shortcode=%s)", clean_url, shortcode)

        async with self._pool.borrow_page() as page:
            # 1. Load initial post page
            await page.goto(clean_url, wait_until="networkidle", timeout=timeout)
            try:
                await page.wait_for_selector("article, main", timeout=5_000)
            except Exception:
                pass
            await page.wait_for_timeout(2_000)

            html = await page.content()
            dom = await page.evaluate(_JS_POST_EXTRACTOR)

            meta_info = _parse_post_meta_tags(html)

            username = meta_info["username"] or dom.get("username")
            caption = meta_info["caption"] or dom.get("caption")
            like_count = meta_info["like_count_raw"] or dom.get("like_count_raw")
            comment_count = meta_info["comment_count_raw"] or dom.get("comment_count_raw")

            # 2. Try Embedded SSR JSON extraction first
            images = _extract_embedded_carousel(html)

            # 3. If embedded JSON didn't return all images, inspect DOM & crawl via ?img_index=n
            if not images:
                # Determine total slides
                total_slides = 1
                if dom.get("total_dots", 0) > 1:
                    total_slides = dom["total_dots"]
                elif dom.get("has_next_button"):
                    total_slides = 2  # At least 2 slides

                # First slide image from initial page
                first_img = dom.get("active_image")
                if first_img:
                    images.append({
                        "index": 1,
                        "src": first_img["src"],
                        "alt": first_img.get("alt"),
                    })

                # If carousel has multiple slides, crawl subsequent slides via ?img_index=n
                if total_slides > 1:
                    logger.info("Detected carousel with %d slides. Crawling via ?img_index=...", total_slides)
                    for idx in range(2, total_slides + 1):
                        slide_url = f"{clean_url}?img_index={idx}"
                        try:
                            await page.goto(slide_url, wait_until="networkidle", timeout=15_000)
                            await page.wait_for_timeout(1_200)
                            slide_dom = await page.evaluate(_JS_POST_EXTRACTOR)
                            active_img = slide_dom.get("active_image")
                            if active_img and active_img.get("src"):
                                images.append({
                                    "index": idx,
                                    "src": active_img["src"],
                                    "alt": active_img.get("alt"),
                                })
                        except Exception as crawl_err:
                            logger.warning("Failed to crawl slide %d for %s: %s", idx, shortcode, crawl_err)

            total_images = len(images) if images else 1

        hashtags = parse_hashtags(caption) if caption else []
        mentions = parse_mentions(caption) if caption else []

        result = {
            "post_type": "post",
            "shortcode": shortcode,
            "url": clean_url,
            "username": username,
            "caption": caption,
            "hashtags": hashtags,
            "mentions": mentions,
            "like_count_raw": like_count,
            "comment_count_raw": comment_count,
            "total_images": total_images,
            "images": images,
            "source": "embedded_json_and_positional_dom",
        }

        logger.info(
            "Scraped Post shortcode=%s username=%s total_images=%d",
            shortcode,
            username,
            total_images,
        )
        return result


_post_scraper: Optional[InstagramPostScraper] = None


def get_instagram_post_scraper() -> InstagramPostScraper:
    global _post_scraper
    if _post_scraper is None:
        _post_scraper = InstagramPostScraper()
    return _post_scraper

