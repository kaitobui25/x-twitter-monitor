"""
BinanceWatcher — fetches posts from Binance Square public profiles
                 using a Playwright-driven browser session.

Why Playwright?
  Binance deploys AWS WAF (gokuProps / CloudFront) that requires a real
  JavaScript engine to resolve the challenge page before content is served.
  Neither `requests` nor `curl-cffi` can pass it reliably.

Architecture:
  - A SINGLE persistent browser context is shared across all BinanceWatcher
    instances (one per process) to avoid the overhead of launching a new
    browser for every watch cycle.
  - On the first call to `get_posts()` the page is loaded and the actual
    BAPI endpoint + required headers + target UUID are discovered by
    intercepting network traffic. Subsequent calls reuse the captured
    endpoint and cookies so that only a lightweight request is needed.
"""
import asyncio
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("binance-watcher")

# ---------------------------------------------------------------------------
# Module-level singleton state
# ---------------------------------------------------------------------------

_event_loop: Optional[asyncio.AbstractEventLoop] = None


# ---------------------------------------------------------------------------
# Internal helpers — run in a dedicated asyncio event loop on a background thread
# ---------------------------------------------------------------------------

def _ensure_event_loop() -> asyncio.AbstractEventLoop:
    """Return (and lazily create) the module-level event loop."""
    global _event_loop
    if _event_loop is None or _event_loop.is_closed():
        _event_loop = asyncio.new_event_loop()
        t = threading.Thread(target=_event_loop.run_forever, daemon=True, name="binance-async")
        t.start()
    return _event_loop


def _run_async(coro):
    """Submit a coroutine to the background event loop and block until done."""
    loop = _ensure_event_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=120)


# ---------------------------------------------------------------------------
# API discovery via full page load
# ---------------------------------------------------------------------------

PROFILE_BASE_URL = "https://www.binance.com/vi/square/profile/{handle}"

# The API that actually returns the feed
_TARGET_API = "queryUserProfilePageContentsWithFilter"


async def _discover_api(handle: str) -> Tuple[Optional[str], Optional[str], Dict, List[Dict]]:
    """
    Launch a temporary browser, open the profile page, intercept network calls,
    identify the BAPI post-list endpoint + targetUid, and return gathered data.
    The browser is closed immediately after.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        logger.info("Launching temporary Playwright/Chromium for discovery...")
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--js-flags='--max-old-space-size=256'"
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="vi-VN",
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        found_endpoint: Optional[str]  = None
        found_uid:      Optional[str]  = None
        found_posts:    List[Dict]     = []
        found_headers:  Dict[str, str] = {}

        async def on_response(response):
            nonlocal found_endpoint, found_uid, found_headers, found_posts
            url = response.url
            if _TARGET_API not in url:
                return
            if response.status != 200:
                return
            
            # Parse url to extract targetSquareUid and the base URL
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            
            uid = qs.get("targetSquareUid", [None])[0]
            if not uid:
                return

            found_endpoint = url.split("?")[0]
            found_uid      = uid
            
            # Try to capture headers
            req_headers = dict(response.request.headers)
            found_headers = {
                k: v for k, v in req_headers.items()
                if k.lower() in (
                    "clienttype", "lang", "user-agent", "cookie",
                    "content-type", "bnc-uuid", "device-info",
                    "x-trace-id", "fvideo-id", "bdt-client-id",
                    "csrftoken"
                )
            }
            
            # Try to get initial posts (optional during discovery)
            try:
                body_bytes = await response.body()
                data = json.loads(body_bytes.decode("utf-8", errors="replace"))
                posts = _extract_posts_from_response(data)
                if posts:
                    found_posts = posts
            except Exception:
                pass # Not critical if body parsing fails here

            logger.info(
                "Discovered feed API via URL: %s (UID: %s)", found_endpoint, found_uid
            )

        page.on("response", on_response)

        url = PROFILE_BASE_URL.format(handle=handle)
        logger.info("Loading profile page: %s", url)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # Handle Cookie Consent Popup if it appears
            try:
                # Look for "Chấp nhận mọi cookie" or "Accept All Cookies"
                cookie_button = page.get_by_role("button", name="Chấp nhận mọi cookie")
                if await cookie_button.is_visible(timeout=5000):
                    await cookie_button.click()
                    logger.info("Cookie consent accepted.")
                    await asyncio.sleep(2)
            except Exception:
                pass # Popup might not be there, that's fine
                
        except Exception as e:
            logger.warning("Page load warning (may be ok): %s", e)

        # Allow network to settle so API calls are captured
        await asyncio.sleep(10)
        
        # Scroll to trigger lazy-loaded posts
        await page.evaluate("window.scrollBy(0, 800)")
        await asyncio.sleep(5)

        await context.close()
        return found_endpoint, found_uid, found_headers, found_posts


def _extract_posts_from_response(data: dict) -> Optional[List[Dict]]:
    """
    Navigate the Binance API response tree to find the post list.
    """
    inner = data.get("data")
    if not inner:
        return None

    if isinstance(inner, dict) and "contents" in inner:
        return inner["contents"]

    # Try common fallback structures
    for key in ("list", "postList", "articles", "items", "feeds"):
        if isinstance(inner, dict) and key in inner:
            candidate = inner[key]
            if isinstance(candidate, list):
                return candidate

    if isinstance(inner, list):
        return inner

    return None


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class BinanceWatcher:
    """
    Fetches the latest posts from a Binance Square profile.
    """

    def __init__(self, handle: str, max_posts: int = 20):
        self.handle    = handle
        self.max_posts = max_posts
        
        self._endpoint: Optional[str]  = None
        self._targetUid: Optional[str] = None
        self._headers:  Dict[str, str] = {}
        
        self.logger = logging.getLogger("binance-watcher")

    def get_posts(self) -> Optional[List[Dict]]:
        """
        Return a list of post dicts for this handle.
        """
        if not self._endpoint or not self._targetUid:
            posts = self._discover()
            if posts is None:
                return None
            return posts

        return self._fetch_posts()

    def _discover(self) -> Optional[List[Dict]]:
        """Full page load to find endpoint + uid + first batch of posts."""
        try:
            endpoint, targetUid, headers, posts = _run_async(
                _discover_api(self.handle)
            )
        except Exception as e:
            import traceback
            self.logger.error("Browser discovery failed: %s\n%s", e, traceback.format_exc())
            return None

        if not endpoint or not targetUid:
            self.logger.error(
                "Could not discover feed API for handle '%s'.",
                self.handle,
            )
            return None

        self._endpoint  = endpoint
        self._targetUid = targetUid
        self._headers   = headers
        self.logger.info("Endpoint locked: %s (UID: %s)", self._endpoint, self._targetUid)
        return posts

    def _fetch_posts(self) -> Optional[List[Dict]]:
        """
        Lightweight GET to the discovered BAPI endpoint using targetSquareUid.
        """
        import requests

        params = {
            "targetSquareUid": self._targetUid,
            "timeOffset": "-1",
            "filterType": "ALL"
        }

        headers = {
            "clienttype":   "web",
            "lang":         "vi",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": PROFILE_BASE_URL.format(handle=self.handle),
            **self._headers,
        }

        try:
            resp = requests.get(
                self._endpoint, params=params, headers=headers, timeout=30
            )
        except Exception as e:
            self.logger.error("GET request failed: %s", e)
            return None

        if resp.status_code != 200:
            self.logger.warning(
                "BAPI returned HTTP %d — will re-discover on next call.", resp.status_code
            )
            self._endpoint = None  # force re-discovery
            return None

        try:
            data = resp.json()
        except Exception as e:
            self.logger.error("JSON decode failed: %s", e)
            return None

        if data.get("code") != "000000":
            self.logger.warning(
                "BAPI non-success code=%s msg=%s", data.get("code"), data.get("message")
            )
            return None

        posts = _extract_posts_from_response(data)
        if posts is None:
            self.logger.error("Could not extract post list from response. Structure may have changed.")
            return None

        return posts
