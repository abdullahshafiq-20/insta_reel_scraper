"""
app/services/scraper/browser_pool.py
Manages a single shared Playwright browser instance with semaphore-bounded pool.
Workers borrow a Page via `async with pool.borrow_page()`.
"""
import asyncio
import logging
import random
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.config import settings

logger = logging.getLogger("insta.browser_pool")


class PlaywrightBrowserPool:
    def __init__(
        self,
        pool_size: int = settings.SCRAPE_BROWSER_POOL_SIZE,
        headless: bool = settings.HEADLESS,
        user_agent: str = settings.USER_AGENT,
        viewport_width: int = settings.VIEWPORT_WIDTH,
        viewport_height: int = settings.VIEWPORT_HEIGHT,
        jitter_min_ms: int = settings.SCRAPE_REQUEST_JITTER_MIN_MS,
        jitter_max_ms: int = settings.SCRAPE_REQUEST_JITTER_MAX_MS,
    ) -> None:
        self.pool_size = pool_size
        self.headless = headless
        self.user_agent = user_agent
        self.viewport = {"width": viewport_width, "height": viewport_height}
        self.jitter_min_ms = jitter_min_ms
        self.jitter_max_ms = jitter_max_ms
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        logger.info("Starting browser pool (pool_size=%d, headless=%s)", self.pool_size, self.headless)
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-accelerated-2d-canvas",
            ],
        )
        self._semaphore = asyncio.Semaphore(self.pool_size)
        self._started = True
        logger.info("Browser pool ready.")

    async def close(self) -> None:
        if not self._started:
            return
        logger.info("Shutting down browser pool…")
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self._started = False

    @asynccontextmanager
    async def borrow_page(self) -> AsyncGenerator[Page, None]:
        if not self._started:
            await self.start()

        assert self._semaphore is not None
        assert self._browser is not None

        async with self._semaphore:
            if self.jitter_max_ms > 0:
                delay_s = random.uniform(self.jitter_min_ms, self.jitter_max_ms) / 1000.0
                await asyncio.sleep(delay_s)

            ctx: BrowserContext = await self._browser.new_context(
                user_agent=self.user_agent,
                viewport=self.viewport,
                locale="en-US",
            )
            page: Page = await ctx.new_page()
            try:
                yield page
            finally:
                await page.close()
                await ctx.close()


browser_pool = PlaywrightBrowserPool()
