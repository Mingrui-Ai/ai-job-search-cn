"""Drive a browser for `collect` with Playwright (docs/cn/collect.md).

Used only by `collect`. The rest of the package is standard library only and offline (ADR-4);
tests/test_cn_package.py names this file as the one exception. Playwright is imported when a
collection starts, so every other command works without it, and this module can be imported
(and its address check tested) without it too.

Two ways to get a tab:

* Default: start this machine's own Chrome (channel "chrome", nothing is downloaded) headless,
  with a fresh temporary profile that Playwright deletes when the browser closes. No window
  appears, nothing of the user's own browser is used, and the browser is closed at the end.
  For sites that show their jobs without signing in.
* --cdp: connect to a Chrome the user started with a debugging port on this machine and open
  one new tab in its window. Only for public pages in a dedicated browser. Only that tab is
  closed at the end; the browser and its other tabs stay as they were.

What it does with the tab either way: navigate it, scroll it, read the rendered page, and close
it. It also watches the status codes of the responses its own tab receives (passively, it does
not intercept them): after a 403 or 429 on a page, list or data request of the site, the tab is
not navigated or scrolled again and every snapshot carries that status, so the run stops.
For a site whose cards carry no link (collect's CAPTURE), it also keeps the responses to the
page's own data requests whose path the site names - the same origin, xhr or fetch only - and
reads their bodies and the bodies the page sent, as text, into the snapshot. It never sends a
request itself and never changes one.
Nothing else: no clicks, no typing, no request interception, no reading of cookies or storage,
never the user's other tabs.
"""

import re
import time
from urllib.parse import urlsplit

from jobsearch_cn.collect import DENIED_STATUSES, BrowserError, Response, Snapshot

DEFAULT_CDP = "http://127.0.0.1:9222"
# The whole address, nothing more: scheme, a loopback host, a port, an optional final slash.
# Anything else (user info, backslashes, paths, other hosts) is refused rather than normalised,
# because Python's and the browser's URL parsers do not agree on such input.
CDP_URL = re.compile(r"http://(127\.0\.0\.1|localhost|\[::1\]):([0-9]{1,5})/?")
WATCHED_REQUESTS = ("document", "xhr", "fetch")
CAPTURED_REQUESTS = ("xhr", "fetch")
MAX_CAPTURED = 50  # responses kept per page; a page that sends more is not one collect reads
MAX_CAPTURED_TEXT = 2_000_000  # characters of one body; a longer one is kept as unreadable (None)
CONNECT_TIMEOUT_MS = 10_000
LAUNCH_TIMEOUT_MS = 30_000
NAV_TIMEOUT_MS = 30_000
READY_TIMEOUT_MS = 15_000
MORE_TIMEOUT_S = 10.0
SETTLE_S = 1.0

INSTALL_HINT = ("没装 Playwright。采集要用它驱动浏览器：在 ai-job-search-cn 环境里运行 "
                "python -m pip install playwright（只要这个 Python 包，不用运行 playwright install，"
                "用的是本机已装的 Chrome）。别的命令不需要它。")


class BrowserUnavailable(Exception):
    """The browser could not be started, reached or driven; nothing was read."""


def check_cdp_url(url: str) -> str:
    """The debugging address as http://<host>:<port>, if it is one on this machine; else BrowserUnavailable."""
    match = CDP_URL.fullmatch(url or "")
    port = int(match.group(2)) if match else 0
    if not 1 <= port <= 65535:
        raise BrowserUnavailable(f"--cdp 只能是本机的调试地址，例如 {DEFAULT_CDP}；不连别的机器上的浏览器")
    return f"http://{match.group(1)}:{port}"


def _site_of(url: str) -> str:
    """The last two labels of the address's host: www.example.com and api.example.com are one site."""
    try:
        host = (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return ""
    return ".".join(host.split(".")[-2:])


def _origin_of(url: str) -> tuple | None:
    """Keep hosted tenants separate when capturing data, including scheme and port."""
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return None
        return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return None


class Tab:
    """One tab of its own. Use open_tab() to get one.

    headless is True when the tab is in a browser this module started (the user cannot see it
    or sign in there); collect uses it to word its advice when a run stops.
    """

    def __init__(self, playwright, page, errors, *, browser=None, headless=False):
        self._playwright, self._page, self._errors = playwright, page, errors
        self._browser = browser  # set only when this module started the browser, so close() closes it
        self.headless = headless
        self.denied = None  # the first 403/429 this tab's own list or data requests got
        self._capture = ()  # path patterns of the data responses to keep (capture())
        self._captured = []  # the kept responses of the current page, in arrival order
        page.on("response", self._watch)

    def capture(self, patterns) -> None:
        """Keep this tab's same-origin xhr/fetch responses whose path matches a pattern."""
        self._capture = tuple(patterns)

    def _watch(self, response) -> None:
        try:
            same_site = _site_of(response.url) == _site_of(self._page.url)
            kind = response.request.resource_type
            if self.denied is None and response.status in DENIED_STATUSES and kind in WATCHED_REQUESTS and same_site:
                self.denied = response.status
            origin = _origin_of(response.url)
            if (self._capture and origin is not None and origin == _origin_of(self._page.url)
                    and kind in CAPTURED_REQUESTS and len(self._captured) < MAX_CAPTURED):
                path = urlsplit(response.url).path
                if any(pattern.search(path) for pattern in self._capture):
                    self._captured.append(response)
        except (self._errors, ValueError):
            pass

    def _text(self, read):
        try:
            text = read()
        except (self._errors, UnicodeDecodeError, ValueError):
            return None
        return text if isinstance(text, str) and len(text) <= MAX_CAPTURED_TEXT else None

    def _responses(self) -> tuple:
        """The kept responses as plain values: address, status, the body sent and the body received."""
        kept = []
        for response in self._captured:
            kept.append(Response(url=response.url, status=response.status,
                                 request=self._text(lambda: response.request.post_data),
                                 body=self._text(response.text)))
        return tuple(kept)

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
        return Snapshot(url=page.url, title=page.title(), html=page.content(), status=self.denied or status,
                        responses=self._responses() if self._capture else ())

    def _was_denied(self) -> bool:
        """True once this tab got a 403/429. Playwright hands over the responses that came in
        during the pause before an action only inside a call to it, hence the title() call."""
        if self.denied is None:
            self._page.title()
        return self.denied is not None

    def open(self, url: str, ready) -> Snapshot:
        def go():
            if self._was_denied():  # go nowhere; the snapshot carries the status and the run stops
                return self._snapshot()
            self._captured = []  # a new page: only its own responses count
            response = self._page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            self._wait_ready(ready)
            return self._snapshot(response.status if response is not None else None)
        return self._guard(go)

    def load_more(self, item_selectors, ready) -> Snapshot:
        """Scroll the result list to its end so the site loads more cards, then read the page."""
        def scroll():
            if self._was_denied():
                return self._snapshot()
            items = self._page.locator(", ".join(item_selectors))
            before = items.count()
            if before:
                items.nth(before - 1).scroll_into_view_if_needed(timeout=5_000)
            self._page.mouse.wheel(0, 1_200)
            deadline = time.monotonic() + MORE_TIMEOUT_S
            while time.monotonic() < deadline and items.count() <= before and self.denied is None:
                time.sleep(0.5)
            if self.denied is None:
                self._wait_ready(ready)
            return self._snapshot()
        return self._guard(scroll)

    def close(self) -> None:
        """Close this tab, and the browser too if this module started it; then drop Playwright."""
        try:
            if not self._page.is_closed():
                self._page.close()
            if self._browser is not None:
                self._browser.close()
        except self._errors:
            pass
        finally:
            self._playwright.stop()


def _playwright():
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise BrowserUnavailable(INSTALL_HINT) from None
    return sync_playwright().start(), PlaywrightError


def open_tab(cdp_url: str | None = None) -> Tab:
    """A tab in a headless Chrome started for this run, or, with cdp_url, a new tab in the user's Chrome."""
    if cdp_url is not None:
        cdp_url = check_cdp_url(cdp_url)
    playwright, errors = _playwright()
    try:
        if cdp_url is None:
            chrome = playwright.chromium.launch(channel="chrome", headless=True, timeout=LAUNCH_TIMEOUT_MS)
            page = chrome.new_page()
            return Tab(playwright, page, errors, browser=chrome, headless=True)
        connected = playwright.chromium.connect_over_cdp(cdp_url, timeout=CONNECT_TIMEOUT_MS)
        if not connected.contexts:
            raise BrowserUnavailable("连上了浏览器，但里面没有打开的窗口；先在那个 Chrome 里打开一个窗口")
        return Tab(playwright, connected.contexts[0].new_page(), errors)
    except BrowserUnavailable:
        playwright.stop()
        raise
    except errors as exc:
        playwright.stop()
        if cdp_url is None:
            detail = str(exc).strip().splitlines()[0][:200] if str(exc).strip() else type(exc).__name__
            raise BrowserUnavailable(f"启动不了本机的 Chrome（{detail}）。采集用的是本机装的 Google Chrome，"
                                     "先确认装了 Chrome") from None
        raise BrowserUnavailable(f"连不上 {cdp_url} 的浏览器。先用带调试端口的专用快捷方式启动 Chrome"
                                 "（docs/cn/collect.md 第 2 节），只读取免登录的公开页面") from None
