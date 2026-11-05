"""Drive the user's own signed-in Chrome over its local debugging port, with Playwright.

Used only by `collect` (docs/cn/collect.md). The rest of the package is standard library only
and offline (ADR-4); tests/test_cn_package.py names this file as the one exception. Playwright
is imported when a collection starts, so every other command works without it, and this
module can be imported (and its address check tested) without it too.

What it does with the browser: open one new tab in the window the user started, navigate it,
scroll it, read the rendered page, and close that tab. Nothing else: no clicks, no typing, no
request interception, no reading of cookies or storage, never the user's other tabs, and never
closing the browser itself (only the connection to it).
"""

import time
from urllib.parse import urlsplit

from jobsearch_cn.collect import BrowserError, Snapshot

DEFAULT_CDP = "http://127.0.0.1:9222"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
CONNECT_TIMEOUT_MS = 10_000
NAV_TIMEOUT_MS = 30_000
READY_TIMEOUT_MS = 15_000
MORE_TIMEOUT_S = 10.0
SETTLE_S = 1.0

INSTALL_HINT = ("没装 Playwright。采集要用它接管浏览器：在 ai-job-search-cn 环境里运行 "
                "python -m pip install playwright（只要这个 Python 包，不用运行 playwright install，"
                "用的是你自己的 Chrome）。别的命令不需要它。")


class BrowserUnavailable(Exception):
    """The browser could not be reached or driven; nothing was read."""


def check_cdp_url(url: str) -> str:
    """The debugging address, if it is an http address on this machine; else BrowserUnavailable."""
    try:
        parts = urlsplit(url or "")
        port = parts.port
    except ValueError:
        parts, port = None, None
    if parts is None or parts.scheme != "http" or (parts.hostname or "") not in LOOPBACK_HOSTS or not port:
        raise BrowserUnavailable(f"--cdp 只能是本机的调试地址，例如 {DEFAULT_CDP}；不连别的机器上的浏览器")
    return url


class CdpTab:
    """One tab of its own in the user's browser. Use open_tab() to get one."""

    def __init__(self, playwright, page, errors):
        self._playwright, self._page, self._errors = playwright, page, errors

    def _guard(self, action):
        try:
            return action()
        except self._errors as exc:
            message = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            raise BrowserError(message[:200]) from None

    def _wait_ready(self, ready) -> None:
        try:
            self._page.wait_for_selector(", ".join(ready), state="attached", timeout=READY_TIMEOUT_MS)
        except self._errors:
            pass  # the caller reads whatever the page shows and decides what it is
        time.sleep(SETTLE_S)

    def _snapshot(self, status=None) -> Snapshot:
        page = self._page
        return Snapshot(url=page.url, title=page.title(), html=page.content(), status=status)

    def open(self, url: str, ready) -> Snapshot:
        def go():
            response = self._page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            self._wait_ready(ready)
            return self._snapshot(response.status if response is not None else None)
        return self._guard(go)

    def load_more(self, item_selectors, ready) -> Snapshot:
        """Scroll the result list to its end so the site loads more cards, then read the page."""
        def scroll():
            items = self._page.locator(", ".join(item_selectors))
            before = items.count()
            if before:
                items.nth(before - 1).scroll_into_view_if_needed(timeout=5_000)
            self._page.mouse.wheel(0, 1_200)
            deadline = time.monotonic() + MORE_TIMEOUT_S
            while time.monotonic() < deadline and items.count() <= before:
                time.sleep(0.5)
            self._wait_ready(ready)
            return self._snapshot()
        return self._guard(scroll)

    def close(self) -> None:
        """Close this tab and drop the connection; the browser and its other tabs stay as they were."""
        try:
            if not self._page.is_closed():
                self._page.close()
        except self._errors:
            pass
        finally:
            self._playwright.stop()


def open_tab(cdp_url: str = DEFAULT_CDP) -> CdpTab:
    """Connect to the browser at cdp_url and open a new tab in its existing window."""
    check_cdp_url(cdp_url)
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise BrowserUnavailable(INSTALL_HINT) from None
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(cdp_url, timeout=CONNECT_TIMEOUT_MS)
        if not browser.contexts:
            raise BrowserUnavailable("连上了浏览器，但里面没有打开的窗口；先在那个 Chrome 里打开一个窗口")
        page = browser.contexts[0].new_page()
    except BrowserUnavailable:
        playwright.stop()
        raise
    except PlaywrightError:
        playwright.stop()
        raise BrowserUnavailable(f"连不上 {cdp_url} 的浏览器。先用带调试端口的专用快捷方式启动 Chrome"
                                 "（docs/cn/collect.md 第 2 节），再重跑；是否需要登录见对应来源说明") from None
    return CdpTab(playwright, page, PlaywrightError)
