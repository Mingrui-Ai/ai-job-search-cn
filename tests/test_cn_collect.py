"""Tests for `collect boss` (docs/cn/collect.md): the HTML reader, the BOSS site rules, the run loop.

Offline: the browser is a fake that serves the fictional pages in tests/fixtures/cn/boss/.
What these pin is what the collector promised the user and the batch screening (M6-4):

* the inbox files are in the jobsearch_cn.inbox/1 format, one job each, and their text is the
  job's own content only - not the recruiter's "刚刚活跃", not the recommended jobs, not the
  navigation - laid out so that `jd parse --site boss` reads the fields;
* the run is slow and read only: a 4-9 s pause before every action but the first, nothing but
  open / load_more / close is ever asked of the browser, at most --max detail pages;
* it stops at a security check, captcha, sign-in page or unknown page, keeps what it saved,
  and says "请在浏览器里处理后重跑";
* a job already in the inbox or the job store is never opened again.
"""
import ast
import io
import json
import random
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "cn" / "boss"

sys.path.insert(0, str(REPO))
from jobsearch_cn import boss, browser, cli, collect, htmltext, jd_parser, schema  # noqa: E402

CST = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 5, 10, 30, 0, tzinfo=CST)
LIST_HTML = (FIXTURES / "list.html").read_text(encoding="utf-8")
MORE_HTML = (FIXTURES / "list-more.html").read_text(encoding="utf-8")
DETAIL_HTML = (FIXTURES / "detail.html").read_text(encoding="utf-8")
JOBS = {  # the cards of list-more.html: id -> title
    "fakeA001~": "Java开发实习生",
    "fakeB002-x": "后端开发实习生（Java方向）",
    "fakeC003_y": "Java实习生（日常实习）",
    "fakeD004.z": "测试开发实习生",
    "fakeE005": "Java后端实习生",
}
EXPECTED_TEXT = "\n".join([
    "Java开发实习生 150-200元/天",
    "广州 4天/周 6个月 本科",
    "职位描述",
    "Java MySQL Spring Boot",
    "岗位职责：",
    "1. 参与示例星图数据平台的后端开发；",
    "2. 编写单元测试，维护接口文档。",
    "任职要求：",
    "1. 2027届本科及以上学历，计算机相关专业；",
    "2. 熟悉 Java 和 MySQL，每周到岗4天，连续实习6个月以上。",
    "工作地址",
    "广州天河区示例大厦12层",
    "示例星图",
    "未融资 20-99人 互联网",
    "示例星图数据科技有限公司",
])
# What M6-4 accepts in an inbox JSON file (design §3.2).
INBOX_KEYS = {"format", "text", "fetched_at", "url", "site_job_id", "site", "extra"}
SECURITY = collect.Snapshot(url="https://www.zhipin.com/web/passport/zp/security.html?callbackUrl=x",
                            title="请稍候", html="<html><head><title>请稍候</title></head><body></body></html>")


def detail_page(title: str) -> str:
    return DETAIL_HTML.replace("Java开发实习生", title)


def detail_url(job_id: str) -> str:
    return f"https://www.zhipin.com/job_detail/{job_id}.html"


class FakeTab:
    """The browser interface collect.run uses, serving fixtures. It has no way to click or type."""

    def __init__(self, list_pages=None, details=None):
        self.list_pages = list(list_pages if list_pages is not None else [LIST_HTML])
        self.details = details or {}
        self.calls = []
        self.closed = False

    def next_list(self):
        """The next result page; once they run out the last one repeats, as a list with no more jobs does."""
        return self.list_pages.pop(0) if len(self.list_pages) > 1 else self.list_pages[0]

    def open(self, url, ready):
        self.calls.append(("open", url))
        if url.startswith(boss.ORIGIN + boss.SEARCH_PATH):
            return collect.Snapshot(url=url, title="搜索", html=self.next_list(), status=200)
        job_id = boss.job_id_from_url(url)
        page = self.details.get(job_id, "default")
        if page == "default":
            page = detail_page(JOBS[job_id])
        if isinstance(page, Exception):
            raise page
        if isinstance(page, collect.Snapshot):
            return page
        return collect.Snapshot(url=detail_url(job_id) + "?lid=FAKE", title="详情", html=page, status=200)

    def load_more(self, item_selectors, ready):
        self.calls.append(("load_more", tuple(item_selectors)))
        return collect.Snapshot(url=boss.ORIGIN + boss.SEARCH_PATH, title="搜索", html=self.next_list())

    def close(self):
        self.closed = True

    def opened(self):
        return [boss.job_id_from_url(url) for kind, url in self.calls if kind == "open" and boss.job_id_from_url(url)]


def check_inbox_record(test, record):
    """The M6-4 inbox rules (design §3.2) a collected file must pass."""
    test.assertLessEqual(set(record), INBOX_KEYS)
    test.assertEqual(record["format"], "jobsearch_cn.inbox/1")
    test.assertEqual(record["site"], "boss")
    test.assertIsInstance(record["text"], str)
    test.assertTrue(record["text"].strip())
    test.assertLessEqual(len(record["text"]), schema.MAX_RAW_TEXT)
    fetched = datetime.fromisoformat(record["fetched_at"])
    test.assertIsNotNone(fetched.utcoffset(), "fetched_at needs a time zone")
    test.assertRegex(record["site_job_id"], r"^[A-Za-z0-9._~-]{1,128}$")
    test.assertEqual(record["url"], detail_url(record["site_job_id"]), "no per-visit query parameters")
    test.assertIsInstance(record["extra"], dict)


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sleeps = []

    def run_collect(self, tab, **options):
        options.setdefault("max_jobs", 30)
        opts = collect.make_options("Java 实习", city="广州", **options)
        return collect.run(tab, opts, self.root, sleep=self.sleeps.append, uniform=random.Random(7).uniform,
                           clock=lambda: NOW)

    def batch_dir(self):
        return self.root / "inbox" / "boss" / "20261105-103000"

    def saved(self):
        return {path.name: json.loads(path.read_text(encoding="utf-8")) for path in sorted(self.batch_dir().glob("*.json"))}


class HtmlText(unittest.TestCase):
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


class BossRules(unittest.TestCase):
    def test_job_id_from_url(self):
        self.assertEqual(boss.job_id_from_url("https://www.zhipin.com/job_detail/ab-1_2.~X.html?lid=1&securityId=2"),
                         "ab-1_2.~X")
        self.assertEqual(boss.job_id_from_url("http://zhipin.com/job_detail/abc.html"), "abc")
        for url in ("https://www.zhipin.com.example.com/job_detail/abc.html", "https://evil.com/job_detail/abc.html",
                    "https://www.zhipin.com/gongsi/abc.html", "https://www.zhipin.com/job_detail/a%2Fb.html",
                    "https://www.zhipin.com/job_detail/.html", "javascript:alert(1)", "", None, 5):
            with self.subTest(url=url):
                self.assertIsNone(boss.job_id_from_url(url))

    def test_urls(self):
        self.assertEqual(boss.canonical_url("abc~"), "https://www.zhipin.com/job_detail/abc~.html")
        self.assertEqual(boss.search_url("Java 实习", "101280100"),
                         "https://www.zhipin.com/web/geek/jobs?query=Java+%E5%AE%9E%E4%B9%A0&city=101280100")

    def test_every_selector_compiles_and_is_one_css_selector(self):
        for rule, selectors in list(boss.SELECTORS.items()) + [("closed_status", boss.CLOSED_STATUS_SELECTORS)]:
            for selector in selectors:
                with self.subTest(rule=rule, selector=selector):
                    htmltext.compile_selector(selector)
                    self.assertNotIn(",", selector)

    def test_list_page(self):
        root = htmltext.parse(LIST_HTML)
        self.assertIsNone(boss.page_problem(boss.search_url("Java", "101280100"), "搜索", root, 200))
        cards, unreadable = boss.parse_cards(root, boss.search_url("Java", "101280100"))
        self.assertEqual(unreadable, 0)
        self.assertEqual([card["id"] for card in cards], list(JOBS)[:3])
        self.assertEqual(cards[0], {
            "id": "fakeA001~",
            "href": "https://www.zhipin.com/job_detail/fakeA001~.html?lid=FAKE-LID-1&securityId=FAKE-SEC-1&sessionId=",
            "title": "Java开发实习生", "salary": "150-200元/天", "location": "广州·天河区·珠江新城"})
        self.assertFalse(boss.list_is_empty(root))

    def test_detail_text_is_the_jobs_own_content(self):
        root = htmltext.parse(DETAIL_HTML)
        self.assertIsNone(boss.page_problem(detail_url("fakeA001~"), "详情", root, 200))
        self.assertFalse(boss.is_closed(root))
        text = boss.detail_text(boss.parse_detail(root))
        self.assertEqual(text, EXPECTED_TEXT)
        for left_out in ("刚刚活跃", "王女士", "招聘者", "看过该职位的人还看了", "300-400元/天", "深圳", "立即沟通", "感兴趣",
                         "示例用户", "首页", "页脚", "公司基本信息", "公司名称", "举报", "隐藏", "999", "总部在北京"):
            with self.subTest(left_out=left_out):
                self.assertNotIn(left_out, text)

    def test_jd_parser_reads_the_collected_text(self):
        [record], warnings = jd_parser.parse_text(EXPECTED_TEXT, site="boss", url=detail_url("fakeA001~"), now=NOW)
        self.assertEqual(warnings, [])
        self.assertEqual(record["title"], "Java开发实习生")
        self.assertEqual(record["company"], "示例星图数据科技有限公司")
        self.assertEqual(record["cities"], ["广州"])
        self.assertEqual(record["salary"]["unit"], "CNY/day")
        self.assertEqual((record["salary"]["min"], record["salary"]["max"]), (150, 200))
        self.assertEqual(record["requirements"]["days_per_week"], 4)
        self.assertEqual(record["requirements"]["min_months"], 6)
        self.assertEqual(record["requirements"]["education"]["min"], "bachelor")

    def test_page_problems(self):
        empty = htmltext.parse("<html><body><div>x</div></body></html>")
        cases = [
            (SECURITY.url, "", empty, None, "blocked"),
            ("https://www.zhipin.com/web/geek/jobs", "请稍候", empty, None, "blocked"),
            ("https://www.zhipin.com/web/geek/jobs", "", htmltext.parse('<div class="geetest_panel"></div>'), None, "blocked"),
            ("https://www.zhipin.com/web/geek/jobs", "", htmltext.parse('<div id="captcha-box"></div>'), None, "blocked"),
            ("https://www.zhipin.com/web/geek/jobs", "", empty, 403, "blocked"),
            ("https://www.zhipin.com/web/geek/jobs", "", empty, 429, "blocked"),
            ("https://passport.example.com/x", "", empty, None, "blocked"),
            ("https://www.zhipin.com/web/user/?ka=header-login", "", empty, None, "login"),
            ("https://www.zhipin.com/web/geek/jobs", "", htmltext.parse('<a ka="header-login" href="/web/user/">登录</a>'),
             None, "login"),
        ]
        for url, title, root, status, kind in cases:
            with self.subTest(url=url, title=title, status=status):
                self.assertEqual(boss.page_problem(url, title, root, status)[0], kind)

    def test_closed_job(self):
        root = htmltext.parse(DETAIL_HTML.replace("<span>招聘中</span>", "<span>职位已关闭</span>"))
        self.assertTrue(boss.is_closed(root))

    def test_same_job_and_city_checks(self):
        self.assertTrue(boss.same_job("Java开发实习生", "Java开发实习生"))
        self.assertTrue(boss.same_job("Java开发实习...", "Java开发实习生（日常）"))
        self.assertTrue(boss.same_job("", "任何"))
        self.assertFalse(boss.same_job("Java开发实习生", "销售代表"))
        self.assertTrue(boss.location_matches("广州·天河区", "广州"))
        self.assertFalse(boss.location_matches("深圳·南山区", "广州"))
        self.assertTrue(boss.location_matches("深圳", "全国"))


class Options(unittest.TestCase):
    def test_limits(self):
        options = collect.make_options(" Java 实习 ", city="广州")
        self.assertEqual((options.query, options.city_code, options.max_jobs, options.max_pages),
                         ("Java 实习", "101280100", 30, 3))
        self.assertEqual(collect.make_options("x", city_code="101280600").city_code, "101280600")
        bad = [dict(query=""), dict(query="x" * 51), dict(city="火星"), dict(city=None), dict(city_code="12345"),
               dict(max_jobs=0), dict(max_jobs=51), dict(max_pages=0), dict(max_pages=11),
               dict(batch=".hidden"), dict(batch="a/b"), dict(batch="~x"), dict(batch="x" * 65)]
        for case in bad:
            arguments = {"query": "Java", "city": "广州", **case}
            with self.subTest(case=case), self.assertRaises(collect.CollectError):
                collect.make_options(arguments.pop("query"), **arguments)


class Collecting(Run):
    def test_saves_one_inbox_file_per_job(self):
        tab = FakeTab()
        summary = self.run_collect(tab, max_jobs=3)
        self.assertEqual(summary["status"], "done")
        self.assertEqual(collect.exit_code(summary), 0)
        self.assertEqual((summary["saved"], summary["skipped_known"], summary["finished"]), (3, 0, "max_jobs"))
        self.assertEqual(summary["batch_dir"], str(self.batch_dir()))
        saved = self.saved()
        self.assertEqual(sorted(saved), sorted(f"{job_id}.json" for job_id in list(JOBS)[:3]))
        for record in saved.values():
            check_inbox_record(self, record)
        first = saved["fakeA001~.json"]
        self.assertEqual(first["text"], EXPECTED_TEXT)
        self.assertEqual(first["fetched_at"], "2026-11-05T10:30:00+08:00")
        self.assertEqual(first["extra"]["query"], "Java 实习")
        self.assertNotIn("FAKE-SEC", json.dumps(saved, ensure_ascii=False), "per-visit link parameters are not kept")
        self.assertEqual([path.name for path in self.batch_dir().iterdir() if path.name.startswith(".")], [])

    def test_is_slow_and_read_only(self):
        tab = FakeTab(list_pages=[LIST_HTML, MORE_HTML])
        summary = self.run_collect(tab, max_jobs=30, max_pages=2)
        self.assertEqual(summary["saved"], 5)
        self.assertEqual({kind for kind, _ in tab.calls}, {"open", "load_more"})
        self.assertEqual(len(self.sleeps), len(tab.calls) - 1, "a pause before every action but the first")
        for seconds in self.sleeps:
            self.assertGreaterEqual(seconds, 4.0)
            self.assertLessEqual(seconds, 9.0)
        self.assertGreater(len(set(self.sleeps)), 1, "the pause is random")
        self.assertFalse(tab.closed, "the caller closes the tab")

    def test_max_limits_the_detail_pages(self):
        tab = FakeTab(list_pages=[LIST_HTML, MORE_HTML])
        summary = self.run_collect(tab, max_jobs=2)
        self.assertEqual(tab.opened(), list(JOBS)[:2])
        self.assertEqual(summary["finished"], "max_jobs")
        self.assertNotIn("load_more", [kind for kind, _ in tab.calls], "no list loads beyond what --max needs")

    def test_list_end_and_page_limit(self):
        tab = FakeTab(list_pages=[LIST_HTML, LIST_HTML])
        self.assertEqual(self.run_collect(tab, max_pages=3)["finished"], "end_of_list")
        tab = FakeTab(list_pages=[LIST_HTML])
        summary = self.run_collect(tab, max_pages=1, batch="second")
        self.assertEqual((summary["finished"], summary["saved"], summary["skipped_known"]), ("max_pages", 0, 3))

    def test_known_jobs_are_not_opened_again(self):
        older = self.root / "inbox" / "boss" / "20261104-090000"
        older.mkdir(parents=True)
        (older / "fakeA001~.json").write_text(json.dumps({"format": collect.INBOX_FORMAT, "site_job_id": "fakeA001~"}),
                                              encoding="utf-8")
        (older / "broken.json").write_text("{", encoding="utf-8")
        jobs = self.root / "jobs"
        jobs.mkdir()
        stored = {"id": "job_0123456789ab", "source": {"site": "boss", "url": detail_url("fakeB002-x") + "?ka=x"}}
        (jobs / "job_0123456789ab.json").write_text(json.dumps(stored), encoding="utf-8")
        tab = FakeTab()
        summary = self.run_collect(tab)
        self.assertEqual(tab.opened(), ["fakeC003_y"])
        self.assertEqual((summary["saved"], summary["skipped_known"]), (1, 2))
        self.assertTrue(any("broken.json" in warning for warning in summary["warnings"]))

    def test_rerun_into_the_same_batch_resumes(self):
        self.run_collect(FakeTab(), max_jobs=1, batch="20261105-103000")
        tab = FakeTab()
        summary = self.run_collect(tab, batch="20261105-103000")
        self.assertEqual(tab.opened(), list(JOBS)[1:3])
        self.assertEqual((summary["saved"], summary["skipped_known"]), (2, 1))
        self.assertEqual(len(self.saved()), 3)

    def test_security_check_stops_and_keeps_what_was_saved(self):
        tab = FakeTab(details={"fakeB002-x": SECURITY})
        summary = self.run_collect(tab)
        self.assertEqual(summary["status"], "needs_user")
        self.assertEqual(collect.exit_code(summary), collect.EXIT_NEEDS_USER)
        self.assertIn(collect.NEEDS_USER, summary["message"])
        self.assertIn("第 2 个新岗位", summary["stopped_at"])
        self.assertEqual(tab.opened(), ["fakeA001~", "fakeB002-x"], "nothing is opened after the check")
        self.assertEqual(list(self.saved()), ["fakeA001~.json"])

    def test_captcha_on_a_page_stops(self):
        captcha = detail_page(JOBS["fakeA001~"]).replace("<body>", '<body><div class="geetest_panel">验证</div>')
        summary = self.run_collect(FakeTab(details={"fakeA001~": captcha}))
        self.assertEqual(summary["status"], "needs_user")
        self.assertEqual(summary["saved"], 0)

    def test_signed_out_list_stops_before_anything_is_written(self):
        signed_out = LIST_HTML.replace('<div class="user-nav">', '<div class="user-nav"><a ka="header-login" href="/web/user/">登录</a>')
        tab = FakeTab(list_pages=[signed_out])
        summary = self.run_collect(tab)
        self.assertEqual(summary["status"], "needs_user")
        self.assertIn("登录", summary["message"])
        self.assertEqual(tab.opened(), [])
        self.assertIsNone(summary["batch_dir"])
        self.assertFalse((self.root / "inbox").exists())

    def test_browser_error_stops(self):
        summary = self.run_collect(FakeTab(details={"fakeA001~": collect.BrowserError("Target page closed")}))
        self.assertEqual(summary["status"], "needs_user")
        self.assertIn("Target page closed", summary["message"])

    def test_unknown_pages_stop_as_page_changed(self):
        cases = {
            "list without cards": FakeTab(list_pages=["<html><body><div>改版了</div></body></html>"]),
            "detail without description": FakeTab(details={"fakeA001~": "<html><body><h1>?</h1></body></html>"}),
            "detail of another job": FakeTab(details={"fakeA001~": collect.Snapshot(
                url=detail_url("other1"), title="详情", html=detail_page("Java开发实习生"))}),
            "detail with another title": FakeTab(details={"fakeA001~": detail_page("销售代表")}),
        }
        for name, tab in cases.items():
            with self.subTest(name):
                summary = self.run_collect(tab)
                self.assertEqual(summary["status"], "page_changed")
                self.assertEqual(collect.exit_code(summary), collect.EXIT_PAGE_CHANGED)
                self.assertEqual(summary["saved"], 0)

    def test_empty_search_and_closed_jobs(self):
        empty = LIST_HTML.replace('<ul class="rec-job-list">', '<div class="job-empty-wrapper">没有找到相关职位</div><ul>')
        empty = empty.replace('class="job-card-box"', 'class="other"')
        summary = self.run_collect(FakeTab(list_pages=[empty]))
        self.assertEqual((summary["status"], summary["finished"], summary["saved"]), ("done", "no_results", 0))
        closed = detail_page(JOBS["fakeB002-x"]).replace("<span>招聘中</span>", "<span>职位已关闭</span>")
        summary = self.run_collect(FakeTab(details={"fakeB002-x": closed}), batch="b2")
        self.assertEqual((summary["saved"], summary["closed"]), (2, 1))

    def test_city_mismatch_is_a_warning(self):
        elsewhere = LIST_HTML.replace("广州·", "深圳·")
        summary = self.run_collect(FakeTab(list_pages=[elsewhere]), max_jobs=1)
        self.assertTrue(any("城市代码" in warning for warning in summary["warnings"]))


class Browser(unittest.TestCase):
    def test_only_local_debugging_addresses(self):
        for url in ("http://127.0.0.1:9222", "http://localhost:9333", "http://[::1]:9222"):
            self.assertEqual(browser.check_cdp_url(url), url)
        for url in ("http://192.168.1.5:9222", "https://127.0.0.1:9222", "http://127.0.0.1", "ws://127.0.0.1:9222",
                    "http://127.0.0.1.example.com:9222", "", "http://127.0.0.1:99999"):
            with self.subTest(url=url), self.assertRaises(browser.BrowserUnavailable):
                browser.check_cdp_url(url)

    def test_missing_playwright_is_explained(self):
        with mock.patch.dict(sys.modules, {"playwright": None, "playwright.sync_api": None}):
            with self.assertRaises(browser.BrowserUnavailable) as caught:
                browser.open_tab("http://127.0.0.1:9222")
        self.assertIn("pip install playwright", str(caught.exception))

    def test_driver_only_reads(self):
        # Tripwire: the driver navigates, scrolls and reads. Calling anything that types, clicks,
        # submits, intercepts requests, runs page scripts or touches cookies is a reviewed change.
        forbidden = {"click", "dblclick", "fill", "type", "press", "press_sequentially", "check", "uncheck", "tap",
                     "select_option", "set_input_files", "dispatch_event", "keyboard", "route", "unroute", "cookies",
                     "add_cookies", "clear_cookies", "storage_state", "evaluate", "evaluate_handle", "add_init_script",
                     "expose_function", "set_extra_http_headers", "new_context", "launch", "launch_persistent_context"}
        tree = ast.parse((REPO / "jobsearch_cn" / "browser.py").read_text(encoding="utf-8"))
        used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertEqual(used & forbidden, set())


class Command(Run):
    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_bad_arguments_exit_2_before_touching_the_browser(self):
        with mock.patch.object(browser, "open_tab") as open_tab:
            for argv in (["--city", "火星"], ["--city", "广州", "--max", "100"], ["--city", "广州", "--cdp", "http://10.0.0.1:9222"]):
                with self.subTest(argv=argv):
                    code, out, err = self.call("collect", "boss", "--query", "Java", "--data-dir", str(self.root), *argv)
                    self.assertEqual(code, 2)
                    self.assertIn("error", json.loads(err))
            open_tab.assert_not_called()

    def test_unreachable_browser_exits_2(self):
        with mock.patch.object(browser, "open_tab", side_effect=browser.BrowserUnavailable("连不上")):
            code, out, err = self.call("collect", "boss", "--query", "Java", "--city", "广州", "--data-dir", str(self.root))
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(json.loads(err), {"error": "连不上"})

    def test_runs_and_closes_its_tab(self):
        tab = FakeTab(details={"fakeB002-x": SECURITY})
        with mock.patch.object(browser, "open_tab", return_value=tab), mock.patch.object(collect, "DELAY_RANGE", (0, 0)):
            code, out, err = self.call("collect", "boss", "--query", "Java 实习", "--city", "广州", "--max", "3",
                                       "--data-dir", str(self.root))
        self.assertEqual(code, 3, err)
        summary = json.loads(out)
        self.assertEqual((summary["status"], summary["saved"]), ("needs_user", 1))
        self.assertTrue(tab.closed)


if __name__ == "__main__":
    unittest.main()
