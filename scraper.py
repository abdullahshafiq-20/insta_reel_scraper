import json
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from config import settings

# JavaScript extractor running in the live page context
JS_EXTRACTOR = r"""
() => {
  const result = {
    username: null,
    caption: null,
    like_count_raw: null,
    comment_count_raw: null,
    share_count_raw: null,
    video_src: null,
    all_video_sources: []
  };

  // 1. Dismiss potential login dialog / prompt if present
  try {
    const closeBtns = Array.from(document.querySelectorAll('div[role="dialog"] button, svg[aria-label="Close"]'));
    for (const b of closeBtns) {
      const btn = b.tagName === 'BUTTON' ? b : b.closest('button, div[role="button"]');
      if (btn) btn.click();
    }
  } catch (e) {}

  // 2. Expand "... more" if caption is collapsed
  try {
    const moreButtons = Array.from(document.querySelectorAll('span[role="button"], button, div[role="button"], a[role="button"]'));
    for (const btn of moreButtons) {
      const text = (btn.textContent || '').trim().toLowerCase();
      if (text === 'more' || text === '... more' || text.endsWith('more')) {
        btn.click();
      }
    }
  } catch (e) {}

  // 3. Extract Username from DOM
  try {
    const nonUsernames = ['sign up', 'log in', 'login', 'signup', 'instagram', 'home', 'explore', 'reels', 'threads', 'meta'];
    const headerLinks = Array.from(document.querySelectorAll('header a[role="link"], header a[href^="/"], article header a, main header a'));
    for (const link of headerLinks) {
      const txt = (link.textContent || '').trim();
      const href = link.getAttribute('href') || '';
      if (txt && !nonUsernames.includes(txt.toLowerCase()) && !href.includes('/accounts/')) {
        result.username = txt;
        break;
      }
    }
  } catch (e) {}

  // 4. Extract Caption from DOM
  try {
    const spans = Array.from(document.querySelectorAll('main span, article span, div[role="dialog"] span, section span'));
    for (const span of spans) {
      const style = span.getAttribute('style') || '';
      const className = span.className || '';
      const isCaptionStyle = /line-height:\s*18px/i.test(style) || 
                             (className.includes('x193iq5w') && className.includes('xeuugli') && className.includes('x13faqbe'));
      if (isCaptionStyle) {
        const text = span.innerText ? span.innerText.trim() : span.textContent.trim();
        if (text && text.length > 3 && !/^[\d,.]+\s*[KMBkmb]?$/.test(text) && !text.startsWith('Never miss a post')) {
          result.caption = text;
          break;
        }
      }
    }
  } catch (e) {}

  // 5. Extract Stats (Likes, Comments, Shares) from button row
  try {
    function svgMatches(svg, regex) {
      const aria = svg.getAttribute('aria-label') || '';
      const title = svg.querySelector('title')?.textContent || '';
      return regex.test(aria) || regex.test(title);
    }

    function findSiblingCount(svg) {
      let curr = svg;
      while (curr && curr.parentElement) {
        const parent = curr.parentElement;
        if (parent.children.length > 1) {
          let next = curr.nextElementSibling;
          if (next) {
            const txt = (next.innerText || next.textContent || '').trim();
            if (/^[\d,.]+\s*[KMBkmb]?$/.test(txt)) {
              return txt;
            }
          }
        }
        if (['SECTION', 'MAIN', 'BODY', 'ARTICLE'].includes(parent.tagName)) break;
        curr = parent;
      }
      return null;
    }

    const allSvgs = Array.from(document.querySelectorAll('svg'));

    // Likes
    for (const svg of allSvgs) {
      if (svgMatches(svg, /^like$/i) || svgMatches(svg, /^unlike$/i)) {
        const count = findSiblingCount(svg);
        if (count) {
          result.like_count_raw = count;
          break;
        }
      }
    }

    // Comments
    for (const svg of allSvgs) {
      if (svgMatches(svg, /^comment$/i)) {
        const count = findSiblingCount(svg);
        if (count) {
          result.comment_count_raw = count;
          break;
        }
      }
    }

    // Shares
    for (const svg of allSvgs) {
      if (svgMatches(svg, /^share/i)) {
        const count = findSiblingCount(svg);
        if (count) {
          result.share_count_raw = count;
          break;
        }
      }
    }
  } catch (e) {}

  // 6. Extract Video Source URLs from DOM
  try {
    const videos = Array.from(document.querySelectorAll('video'));
    for (const v of videos) {
      const src = v.currentSrc || v.src || v.getAttribute('src');
      if (src && src.startsWith('http')) {
        result.all_video_sources.push(src);
      }
      const sources = Array.from(v.querySelectorAll('source'));
      for (const s of sources) {
        const sSrc = s.src || s.getAttribute('src');
        if (sSrc && sSrc.startsWith('http')) {
          result.all_video_sources.push(sSrc);
        }
      }
    }
  } catch (e) {}

  return result;
}
"""


def extract_shortcode(url: str) -> str:
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    for i, p in enumerate(parts):
        if p in ("reel", "reels", "p", "tv") and i + 1 < len(parts):
            return parts[i + 1]
    if parts:
        return parts[-1]
    raise ValueError(f"Could not extract a valid shortcode from URL: {url}")


def parse_hashtags(text: Optional[str]) -> List[str]:
    if not text:
        return []
    return re.findall(r"#(\w+)", text)


def parse_mentions(text: Optional[str]) -> List[str]:
    if not text:
        return []
    return re.findall(r"@([\w.]+)", text)


def parse_page_data(html: str, shortcode: str, url: str, dom_data: dict) -> dict:
    """
    Combines OpenGraph/Twitter meta tags, embedded script JSON,
    and DOM extraction into a clean metadata dictionary.
    """
    result = {
        "shortcode": shortcode,
        "url": url,
        "username": None,
        "caption": None,
        "hashtags": [],
        "mentions": [],
        "like_count_raw": None,
        "comment_count_raw": None,
        "share_count_raw": dom_data.get("share_count_raw"),
        "video_url": None,
        "video_urls_candidates": [],
        "source": "headless_browser_dom",
    }

    # 1. Parse Meta Tags
    meta_desc = None
    meta_og_url = None
    meta_tw_title = None

    for m in re.finditer(r'<meta\s+([^>]+)>', html):
        attr_str = m.group(1)
        prop_m = re.search(r'(?:property|name)=["\']([^"\']+)["\']', attr_str)
        cont_m = re.search(r'content=["\'](.*?)["\']', attr_str, re.DOTALL)
        if prop_m and cont_m:
            prop = prop_m.group(1).lower()
            content = cont_m.group(1).replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
            if prop in ["og:description", "description"]:
                meta_desc = content
            elif prop == "og:url":
                meta_og_url = content
            elif prop == "twitter:title":
                meta_tw_title = content

    # Username resolution
    if meta_og_url:
        u_match = re.search(r"instagram\.com/([^/]+)/(?:reel|p|reels)/", meta_og_url)
        if u_match and u_match.group(1) not in ["reel", "p", "reels", "explore", "stories"]:
            result["username"] = u_match.group(1)

    if not result["username"] and meta_tw_title:
        u_match = re.search(r"\(@([a-zA-Z0-9._]+)\)", meta_tw_title)
        if u_match:
            result["username"] = u_match.group(1)

    if not result["username"] and meta_desc:
        u_match = re.search(r"-\s*([a-zA-Z0-9._]+)\s+on\s+", meta_desc)
        if u_match:
            result["username"] = u_match.group(1)

    if not result["username"] and dom_data.get("username"):
        result["username"] = dom_data["username"]

    # Caption resolution
    if meta_desc:
        cap_match = re.search(r':\s*["“](.*)["”][.\s]*$', meta_desc, re.DOTALL)
        if cap_match:
            result["caption"] = cap_match.group(1).strip()

    if not result["caption"] and dom_data.get("caption"):
        result["caption"] = dom_data["caption"]

    # Stats resolution (Likes & Comments)
    if meta_desc:
        like_m = re.search(r"([\d,.]+\s*[KMBkmb]?)\s+likes", meta_desc, re.IGNORECASE)
        if like_m:
            result["like_count_raw"] = like_m.group(1)

        comment_m = re.search(r"([\d,.]+\s*[KMBkmb]?)\s+comments", meta_desc, re.IGNORECASE)
        if comment_m:
            result["comment_count_raw"] = comment_m.group(1)

    if not result["like_count_raw"] and dom_data.get("like_count_raw"):
        result["like_count_raw"] = dom_data["like_count_raw"]

    if not result["comment_count_raw"] and dom_data.get("comment_count_raw"):
        result["comment_count_raw"] = dom_data["comment_count_raw"]

    # 2. Parse Embedded JSON Scripts for Progressive Video URLs
    progressive_urls = []
    dash_urls = []

    for vmatch in re.finditer(r'"video_versions":\s*(\[[^\]]+\])', html):
        raw = vmatch.group(1).replace(r"\/", "/").replace(r"\u0026", "&")
        try:
            arr = json.loads(raw)
            for item in arr:
                v_url = item.get("url")
                if v_url:
                    if "bytestart=" in v_url:
                        dash_urls.append(v_url)
                    elif v_url not in progressive_urls:
                        progressive_urls.append(v_url)
        except Exception:
            pass

    # DOM video sources
    for src in dom_data.get("all_video_sources", []):
        if "bytestart=" in src:
            dash_urls.append(src)
        elif src not in progressive_urls:
            progressive_urls.append(src)

    # Candidate URLs ordered by priority (progressive full MP4 first)
    candidate_urls = progressive_urls + dash_urls
    result["video_urls_candidates"] = candidate_urls
    if candidate_urls:
        result["video_url"] = candidate_urls[0]

    # Caption fallback from JSON if still empty
    if not result["caption"]:
        for cmatch in re.finditer(r'"caption":\s*\{\s*"text":\s*"([^"]+)"', html):
            try:
                text = cmatch.group(1).encode().decode("unicode_escape")
                if text and len(text) > 3:
                    result["caption"] = text
                    break
            except Exception:
                pass

    if result["caption"]:
        result["hashtags"] = parse_hashtags(result["caption"])
        result["mentions"] = parse_mentions(result["caption"])

    return result


async def scrape_instagram_reel(url: str, timeout_ms: Optional[int] = None) -> dict:
    """
    Scrapes metadata and progressive video CDN URL asynchronously via headless Playwright.
    Operates 100% in-memory without creating or writing any files to disk.
    """
    timeout = timeout_ms or settings.TIMEOUT_MS
    shortcode = extract_shortcode(url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=settings.HEADLESS)
        try:
            context = await browser.new_context(
                user_agent=settings.USER_AGENT,
                viewport={"width": settings.VIEWPORT_WIDTH, "height": settings.VIEWPORT_HEIGHT},
                locale="en-US",
            )
            page = await context.new_page()

            # Navigate to Instagram Reel
            await page.goto(url, wait_until="networkidle", timeout=timeout)

            # Wait briefly for dynamic elements
            try:
                await page.wait_for_selector("video, main, article", timeout=5000)
            except Exception:
                pass

            await page.wait_for_timeout(2000)

            # Extract live DOM and HTML
            html_content = await page.content()
            dom_data = await page.evaluate(JS_EXTRACTOR)

            parsed_result = parse_page_data(html_content, shortcode, url, dom_data)
            return parsed_result
        finally:
            await browser.close()

