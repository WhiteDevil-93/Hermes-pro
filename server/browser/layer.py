"""Browser Layer — Playwright-based headless browser that executes Conduit commands.

The Browser Layer has no decision-making authority. It renders pages,
executes interactions, and returns DOM state. It accepts only typed
commands from the Conduit.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from server.config.settings import BrowserConfig


class ActionStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"


@dataclass
class ActionResult:
    """Result of a browser action."""

    status: ActionStatus
    detail: str = ""


@dataclass
class DOMSnapshot:
    """Cleaned DOM snapshot from the browser."""

    html: str
    url: str
    title: str
    dom_hash: str

    @staticmethod
    def compute_hash(html: str) -> str:
        return hashlib.sha256(html.encode()).hexdigest()[:16]


class BrowserLayer:
    """Playwright-based browser layer. Executes commands from the Conduit only.

    Contract:
    - Accepts only typed commands (click, scroll, fill, capture_dom, screenshot)
    - Returns typed results (DOMSnapshot, bytes, ActionResult)
    - Never initiates navigation or interaction on its own
    - Manages crash recovery (restarts browser context, reports to Conduit)
    """

    def __init__(self, config: BrowserConfig | None = None) -> None:
        self._config = config or BrowserConfig()
        self._playwright: Any = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def page(self) -> Page | None:
        return self._page

    async def start(self) -> None:
        """Launch browser and create an isolated context."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._config.headless,
        )
        self._context = await self._browser.new_context(
            viewport={
                "width": self._config.viewport_width,
                "height": self._config.viewport_height,
            },
            user_agent=self._config.user_agent,
            locale=self._config.locale,
        )
        self._page = await self._context.new_page()

    async def stop(self) -> None:
        """Clean up browser resources."""
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self._page = None

    async def navigate(self, url: str, timeout_ms: int = 30000) -> ActionResult:
        """Navigate to a URL and wait for page load."""
        if not self._page:
            return ActionResult(status=ActionStatus.FAILURE, detail="Browser not started")
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            return ActionResult(status=ActionStatus.SUCCESS, detail=f"Navigated to {url}")
        except Exception as e:
            return ActionResult(status=ActionStatus.FAILURE, detail=str(e))

    async def click(self, selector: str, wait_after_ms: int = 1000) -> ActionResult:
        """Click an element identified by CSS selector."""
        if not self._page:
            return ActionResult(status=ActionStatus.FAILURE, detail="Browser not started")
        try:
            await self._page.click(selector, timeout=10000)
            if wait_after_ms > 0:
                await self._page.wait_for_timeout(wait_after_ms)
            return ActionResult(status=ActionStatus.SUCCESS, detail=f"Clicked {selector}")
        except Exception as e:
            return ActionResult(status=ActionStatus.FAILURE, detail=str(e))

    async def scroll(
        self, direction: str = "down", amount: str = "page"
    ) -> ActionResult:
        """Scroll the viewport."""
        if not self._page:
            return ActionResult(status=ActionStatus.FAILURE, detail="Browser not started")
        try:
            if amount == "end":
                await self._page.evaluate(
                    "window.scrollTo(0, document.body.scrollHeight)"
                )
            elif amount == "page":
                delta = -720 if direction == "up" else 720
                await self._page.mouse.wheel(0, delta)
            else:
                # amount is pixels
                pixels = int(amount)
                delta = -pixels if direction == "up" else pixels
                await self._page.mouse.wheel(0, delta)
            await self._page.wait_for_timeout(500)
            return ActionResult(
                status=ActionStatus.SUCCESS,
                detail=f"Scrolled {direction} {amount}",
            )
        except Exception as e:
            return ActionResult(status=ActionStatus.FAILURE, detail=str(e))

    async def fill_form(self, selector: str, value: str) -> ActionResult:
        """Type a value into a form field."""
        if not self._page:
            return ActionResult(status=ActionStatus.FAILURE, detail="Browser not started")
        try:
            await self._page.fill(selector, value, timeout=10000)
            return ActionResult(
                status=ActionStatus.SUCCESS, detail=f"Filled {selector}"
            )
        except Exception as e:
            return ActionResult(status=ActionStatus.FAILURE, detail=str(e))

    async def hover(self, selector: str) -> ActionResult:
        """Hover over an element."""
        if not self._page:
            return ActionResult(status=ActionStatus.FAILURE, detail="Browser not started")
        try:
            await self._page.hover(selector, timeout=10000)
            return ActionResult(
                status=ActionStatus.SUCCESS, detail=f"Hovered {selector}"
            )
        except Exception as e:
            return ActionResult(status=ActionStatus.FAILURE, detail=str(e))

    async def press_key(self, key: str) -> ActionResult:
        """Press a keyboard key."""
        if not self._page:
            return ActionResult(status=ActionStatus.FAILURE, detail="Browser not started")
        try:
            await self._page.keyboard.press(key)
            return ActionResult(status=ActionStatus.SUCCESS, detail=f"Pressed {key}")
        except Exception as e:
            return ActionResult(status=ActionStatus.FAILURE, detail=str(e))

    async def wait_for(self, selector: str, timeout_ms: int = 10000) -> ActionResult:
        """Wait for an element to appear in DOM."""
        if not self._page:
            return ActionResult(status=ActionStatus.FAILURE, detail="Browser not started")
        try:
            await self._page.wait_for_selector(selector, timeout=timeout_ms)
            return ActionResult(
                status=ActionStatus.SUCCESS,
                detail=f"Element {selector} appeared",
            )
        except Exception as e:
            return ActionResult(status=ActionStatus.TIMEOUT, detail=str(e))

    async def capture_dom(self) -> DOMSnapshot | None:
        """Capture a cleaned DOM snapshot.

        Strips scripts, styles, and hidden elements to minimize size
        before any AI processing.
        """
        if not self._page:
            return None

        # Get cleaned HTML: remove script, style, and hidden elements
        html = await self._page.evaluate("""() => {
            const clone = document.documentElement.cloneNode(true);
            // Remove scripts
            clone.querySelectorAll('script, style, noscript, link[rel=stylesheet]')
                .forEach(el => el.remove());
            // Remove hidden elements
            clone.querySelectorAll('[style*="display: none"], [style*="display:none"], [hidden]')
                .forEach(el => el.remove());
            return clone.outerHTML;
        }""")

        url = self._page.url
        title = await self._page.title()
        dom_hash = DOMSnapshot.compute_hash(html)

        return DOMSnapshot(html=html, url=url, title=title, dom_hash=dom_hash)

    async def screenshot(self) -> bytes | None:
        """Capture a screenshot of the current viewport."""
        if not self._page:
            return None
        return await self._page.screenshot(type="png")

    async def restart_context(self) -> ActionResult:
        """Crash recovery: restart the browser context."""
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                self._context = await self._browser.new_context(
                    viewport={
                        "width": self._config.viewport_width,
                        "height": self._config.viewport_height,
                    },
                    user_agent=self._config.user_agent,
                    locale=self._config.locale,
                )
                self._page = await self._context.new_page()
                return ActionResult(
                    status=ActionStatus.SUCCESS, detail="Context restarted"
                )
            return ActionResult(
                status=ActionStatus.FAILURE, detail="No browser to restart context on"
            )
        except Exception as e:
            return ActionResult(status=ActionStatus.FAILURE, detail=str(e))
