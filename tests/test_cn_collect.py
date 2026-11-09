"""Shared HTML and browser regressions from the reviewed collector; fictional origins only."""
import ast
import sys
import unittest
from pathlib import Path
from unittest import mock
from jobsearch_cn import browser, collect, htmltext
from tests.fixtures.collect_personal import example as site

REPO = Path(__file__).resolve().parent.parent
LIST_HTML = '<div class="example-list"></div>'

class HtmlText(unittest.TestCase):
    def test_security_visibility_is_separate_from_text_extraction(self):
        for tag in ("iframe", "canvas", "svg", "object"):
            node = htmltext.Node(tag, {"id": "captcha"})
            self.assertFalse(htmltext.visible(node))
            self.assertTrue(htmltext.visible(node, include_nontext=True))
            for attrs in ({"hidden": ""}, {"style": "display:none"}, {"style": "visibility:hidden !important"}):
                self.assertFalse(htmltext.visible(htmltext.Node(tag, attrs), include_nontext=True))
        for tag in ("script", "style", "noscript", "template", "head", "select"):
            with self.subTest(tag=tag):
                self.assertFalse(htmltext.visible(htmltext.Node(tag), include_nontext=True))
        markup = "<div>keep<canvas>omit</canvas><svg>omit</svg><object>omit</object></div>"
        self.assertEqual(htmltext.text(htmltext.parse(markup)), "keep")

    def test_selectors(self):
        root = htmltext.parse('<div id="a" class="x y"><p class="x"><a href="/job_detail/1.html" ka="k-1">t</a></p>'
                              '<span><a href="https://e.com/">u</a></span></div>')
        self.assertEqual([n.tag for n in htmltext.select(root, "div.x.y > p.x > a")], ["a"])
        self.assertEqual(len(htmltext.select(root, "#a a")), 2)
        self.assertEqual(len(htmltext.select(root, "div > a")), 0)
        self.assertEqual(len(htmltext.select(root, 'a[href*="/job_detail/"]')), 1)
        self.assertEqual(len(htmltext.select(root, "a[href^=https]")), 1)
        self.assertEqual(len(htmltext.select(root, "a[href$=.html]")), 1)
        self.assertEqual(len(htmltext.select(root, "a[ka=k-1]")), 1)
        self.assertEqual(len(htmltext.select(root, "[ka]")), 1)
        self.assertEqual(len(htmltext.select(root, "p > *")), 1)
        self.assertEqual(htmltext.first(root, [".missing", "span a"]).get("href"), "https://e.com/")
        self.assertIsNone(htmltext.first(root, [".missing"]))
        for bad in ("a, b", "a:hover", "> a", "a >", "a > > b", "a[title='x y']", "a~b"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                htmltext.compile_selector(bad)

    def test_text_is_like_inner_text(self):
        root = htmltext.parse(
            "<div>一 <b>二</b>\n  三<br>四<p>五</p>六<script>var x='不要';</script><style>.a{}</style>"
            "<span hidden>藏</span><span style='color:red; display: none'>藏</span><template>藏</template>"
            "<ul><li>甲</li><li>乙&nbsp;丙 &amp; 丁</li></ul></div>")
        self.assertEqual(htmltext.text(root), "一 二 三\n四\n五\n六\n甲\n乙 丙 & 丁")
        self.assertEqual(htmltext.text(htmltext.parse("<div>a\n\n b\r\nc</div>"), keep_newlines=True), "a\nb\nc")
        self.assertEqual(htmltext.page_title(htmltext.parse("<head><title> 请稍候 </title></head>")), "请稍候")

    def test_tolerates_stray_and_void_tags(self):
        root = htmltext.parse("<div><p>a</span>b<img src=x><br/>c</p></div></div><p>d")
        self.assertEqual(htmltext.text(root), "ab\nc\nd")



class FakeError(Exception):
    """Stands in for playwright.sync_api.Error."""


class FakeRequest:
    def __init__(self, resource_type):
        self.resource_type = resource_type


class FakeResponse:
    def __init__(self, url, status, resource_type="fetch"):
        self.url, self.status, self.request = url, status, FakeRequest(resource_type)


class FakeLocator:
    def __init__(self, page):
        self.page = page

    def count(self):
        return 3

    def nth(self, index):
        return self

    def scroll_into_view_if_needed(self, timeout):
        pass


class FakeMouse:
    def __init__(self, page):
        self.page = page

    def wheel(self, dx, dy):
        """Scrolling makes the site fetch the next cards; the fake site answers with page.more_status."""
        for listener in self.page.listeners:
            listener(FakeResponse("https://api.example.invalid/list.json", self.page.more_status))


class FakePage:
    """The few Playwright page calls browser.Tab makes."""

    def __init__(self, more_status=200):
        self.url = site.ORIGIN + site.SEARCH_PATH
        self.listeners, self.more_status, self.closed = [], more_status, False
        self.mouse = FakeMouse(self)

    def on(self, event, listener):
        assert event == "response"
        self.listeners.append(listener)

    def goto(self, url, wait_until, timeout):
        self.url = url
        return FakeResponse(url, 200, "document")

    def wait_for_selector(self, selector, state, timeout):
        pass

    def locator(self, selector):
        return FakeLocator(self)

    def title(self):
        return "搜索"

    def content(self):
        return LIST_HTML

    def is_closed(self):
        return self.closed

    def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, page):
        self.page, self.closed, self.contexts = page, False, [self]

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, browser):
        self.browser, self.calls = browser, []

    def launch(self, **options):
        self.calls.append(("launch", options))
        return self.browser

    def connect_over_cdp(self, url, timeout):
        self.calls.append(("connect_over_cdp", url))
        return self.browser


class FakePlaywright:
    def __init__(self, page):
        self.browser = FakeBrowser(page)
        self.chromium = FakeChromium(self.browser)
        self.stopped = False

    def stop(self):
        self.stopped = True


class Browser(unittest.TestCase):
    def test_only_local_debugging_addresses(self):
        for url in ("http://127.0.0.1:9222", "http://localhost:9333", "http://[::1]:9222"):
            self.assertEqual(browser.check_cdp_url(url), url)
        self.assertEqual(browser.check_cdp_url("http://127.0.0.1:9222/"), "http://127.0.0.1:9222")
        for url in ("http://192.168.1.5:9222", "https://127.0.0.1:9222", "http://127.0.0.1", "ws://127.0.0.1:9222",
                    "http://127.0.0.1.example.com:9222", "", "http://127.0.0.1:99999", "http://127.0.0.1:0",
                    "http://user@127.0.0.1:9222", "http://127.0.0.1:9222/json/version", "http://127.0.0.1:9222?x=1",
                    "HTTP://127.0.0.1:9222", " http://127.0.0.1:9222", "http://127.0.0.1:9222\n"):
            with self.subTest(url=url), self.assertRaises(browser.BrowserUnavailable):
                browser.check_cdp_url(url)

    def test_cdp_address_python_and_the_browser_would_read_differently_is_refused(self):
        # Codex B, PR #142 P2-1: Python's urlsplit reads this host as 127.0.0.1, the WHATWG URL
        # parser Playwright uses reads it as 192.0.2.1. Such input is refused, not normalised.
        tricky = "http://192.0.2.1\\@127.0.0.1:9222"
        self.assertEqual(browser.urlsplit(tricky).hostname, "127.0.0.1", "sanity: Python is fooled")
        with self.assertRaises(browser.BrowserUnavailable):
            browser.check_cdp_url(tricky)
        page = FakePage()
        playwright = FakePlaywright(page)
        with mock.patch.object(browser, "_playwright", return_value=(playwright, FakeError)):
            with self.assertRaises(browser.BrowserUnavailable):
                browser.open_tab(tricky)
            browser.open_tab("http://localhost:9222/")
        self.assertEqual(playwright.chromium.calls, [("connect_over_cdp", "http://localhost:9222")],
                         "the browser gets the checked address, rebuilt, never the raw string")

    def test_default_is_a_headless_local_chrome_closed_afterwards(self):
        page = FakePage()
        playwright = FakePlaywright(page)
        with mock.patch.object(browser, "_playwright", return_value=(playwright, FakeError)):
            tab = browser.open_tab()
        self.assertEqual(playwright.chromium.calls, [("launch", {"channel": "chrome", "headless": True,
                                                                  "timeout": browser.LAUNCH_TIMEOUT_MS})])
        self.assertTrue(tab.headless)
        tab.close()
        self.assertTrue(page.closed and playwright.browser.closed and playwright.stopped)

    def test_cdp_tab_leaves_the_users_browser_open(self):
        page = FakePage()
        playwright = FakePlaywright(page)
        with mock.patch.object(browser, "_playwright", return_value=(playwright, FakeError)):
            tab = browser.open_tab("http://127.0.0.1:9222")
        self.assertFalse(tab.headless)
        tab.close()
        self.assertTrue(page.closed and playwright.stopped)
        self.assertFalse(playwright.browser.closed)

    def test_denied_data_request_while_scrolling_shows_in_the_snapshot(self):
        # Codex B, PR #142 P2-2: the scroll's own fetch got 403/429 while the page kept its old
        # cards; the snapshot must carry the status so the run stops (see Collecting).
        for status in (403, 429):
            with self.subTest(status=status), mock.patch.object(browser, "SETTLE_S", 0), \
                    mock.patch.object(browser, "MORE_TIMEOUT_S", 0):
                tab = browser.Tab(FakePlaywright(None), FakePage(more_status=status), FakeError)
                self.assertEqual(tab.open(site.search_url("Java", "CITY_45"), site.LIST_READY).status, 200)
                self.assertEqual(tab.load_more(site.SELECTORS["card"], site.LIST_READY).status, status)
        with mock.patch.object(browser, "SETTLE_S", 0), mock.patch.object(browser, "MORE_TIMEOUT_S", 0):
            page = FakePage()
            tab = browser.Tab(FakePlaywright(None), page, FakeError)
            tab.open(site.search_url("Java", "CITY_45"), site.LIST_READY)
            for listener in page.listeners:  # other sites' requests and images do not count
                listener(FakeResponse("https://analytics.example.com/collect", 403))
                listener(FakeResponse("https://img.example.invalid/a.png", 403, "image"))
            self.assertIsNone(tab.load_more(site.SELECTORS["card"], site.LIST_READY).status)

    def test_missing_playwright_is_explained(self):
        with mock.patch.dict(sys.modules, {"playwright": None, "playwright.sync_api": None}):
            for cdp in (None, "http://127.0.0.1:9222"):
                with self.subTest(cdp=cdp), self.assertRaises(browser.BrowserUnavailable) as caught:
                    browser.open_tab(cdp)
                self.assertIn("pip install playwright", str(caught.exception))

    def test_driver_only_reads(self):
        # Tripwire: the driver starts a headless browser or connects to the user's, then navigates,
        # scrolls and reads. Calling anything that types, clicks, submits, intercepts requests, runs
        # page scripts, touches cookies or reuses a profile is a reviewed change.
        forbidden = {"click", "dblclick", "fill", "type", "press", "press_sequentially", "check", "uncheck", "tap",
                     "select_option", "set_input_files", "dispatch_event", "keyboard", "route", "unroute", "cookies",
                     "add_cookies", "clear_cookies", "storage_state", "evaluate", "evaluate_handle", "add_init_script",
                     "expose_function", "set_extra_http_headers", "new_context", "launch_persistent_context"}
        tree = ast.parse((REPO / "jobsearch_cn" / "browser.py").read_text(encoding="utf-8"))
        used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertEqual(used & forbidden, set())
        launches = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute) and node.func.attr == "launch"]
        self.assertEqual(len(launches), 1)
        options = {keyword.arg: ast.literal_eval(keyword.value) for keyword in launches[0].keywords
                   if keyword.arg in ("channel", "headless")}
        self.assertEqual(options, {"channel": "chrome", "headless": True}, "headless, this machine's Chrome only")
