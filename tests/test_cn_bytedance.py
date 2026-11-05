"""Fictional campus DOM only. Real postings and holdout samples are never fixtures."""

import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest import mock

from jobsearch_cn import bytedance as site, browser, cli, collect, htmltext, jd_parser, screen, store, vocab
from tests.test_cn_collect import FakeError, FakePage, FakePlaywright, FakeResponse

NOW = datetime(2026, 11, 5, 22, 30, tzinfo=timezone(timedelta(hours=8)))


def listing(ids=("900001", "900002")):
    cards = "".join(
        f'<a href="/campus/position/{job_id}/detail?tracking=fictional">'
        '<div class="positionItem"><div class="positionItem-title-text">示例后端实习生</div>'
        '<div class="positionItem-subTitle"><span>广州</span><span>实习</span></div>'
        '<div class="positionItem-jobDesc">列表摘要，不是完整 JD</div></div></a>'
        for job_id in ids
    )
    return f'<a href="/campus/login">登录</a><div class="positionList-content">{cards}</div>'


DETAIL = '''<header>导航</header><div class="jobDetail">
<div class="job-header"><span class="job-title">示例后端实习生</span></div>
<div class="job-info"><span>北京、广州</span><span></span><span>实习</span>
<span>研发 - 后端</span><span>日常实习</span><span>职位 ID：EXAMPLE_A1</span></div>
<div class="block-title">职位描述</div><div class="block-content">参与示例系统开发。
维护 Java 服务。</div><div class="block-title">职位要求</div>
<div class="block-content">本科，每周到岗4天，实习3个月。<br>熟悉 Java 和 MySQL。</div>
<div class="apply-block"><button>投递</button></div></div>
<div class="relatedJobs"><span class="job-title">推荐岗位 999元/天</span>
<div class="block-title">职位要求</div><div class="block-content">仅限上海</div></div>
<footer>示例公司导航</footer>'''


class SiteRules(unittest.TestCase):
    def test_search_parameters_and_pagination(self):
        from urllib.parse import parse_qs, urlsplit
        parts = urlsplit(site.search_url("后端 & Java", "CT_45", 2))
        self.assertEqual(parts.path, "/campus/position")
        self.assertEqual(parse_qs(parts.query), {"keywords": ["后端 & Java"], "location": ["CT_45"],
                                               "current": ["2"], "limit": ["10"]})

    def test_detail_links_are_restricted_to_the_public_campus_host_and_path(self):
        good = site.canonical_url("900001")
        self.assertEqual(site.job_id_from_url(good + "?tracking=fictional"), "900001")
        for url in (good.replace("jobs.bytedance.com", "example.invalid"),
                    good.replace("/campus/", "/referral/"), good.replace("900001", "../bad"),
                    good.replace("https://", "http://"), good.replace(".com/", ".com:123/"),
                    good.replace("https://", "https://user@"), "https://[", None):
            with self.subTest(url=url):
                self.assertIsNone(site.job_id_from_url(url))

    def test_cards_use_actual_links_and_skip_malformed_cards(self):
        html = listing() + listing(("bad-id",))
        cards, unreadable = site.parse_cards(htmltext.parse(html), site.search_url("后端", "CT_45"))
        self.assertEqual([card["id"] for card in cards], ["900001", "900002"])
        self.assertEqual(unreadable, 1)
        self.assertEqual(cards[0]["href"], site.canonical_url("900001"))
        self.assertEqual(cards[0]["location"], "广州")

    def test_legacy_http_is_known_only_not_a_navigation_url(self):
        good = site.canonical_url("900001")
        for url in (good, good.replace("https:", "http:"),
                    good.replace("https://jobs.bytedance.com", "http://jobs.bytedance.com:80") + "?utm_source=x"):
            with self.subTest(url=url):
                self.assertEqual(site.known_job_id_from_url(url), "900001")
                if url.startswith("http:"):
                    self.assertIsNone(site.job_id_from_url(url))
                    self.assertIsNotNone(site.page_problem(url, "校园招聘", htmltext.parse(listing()), 200))
        for url in (good.replace("https:", "ftp:"), good.replace(".com/", ".com:80/"),
                    good.replace("https://", "http://user@"), good.replace(".com/", ".com.example.invalid/"),
                    good.replace("jobs.bytedance.com", "other.bytedance.com"),
                    good.replace("https://jobs.bytedance.com", "http://jobs.bytedance.com:443"),
                    good.replace("/campus/", "/referral/"), None, 42):
            with self.subTest(url=url):
                self.assertIsNone(site.known_job_id_from_url(url))

    def test_detail_keeps_requirements_and_omits_recommendations_and_controls(self):
        fields = site.parse_detail(htmltext.parse(DETAIL))
        text = site.detail_text(fields)
        for expected in ("示例后端实习生", "北京、广州", "职位描述", "职位要求", "熟悉 Java 和 MySQL。"):
            self.assertIn(expected, text)
        for excluded in ("999元", "仅限上海", "导航", "投递"):
            self.assertNotIn(excluded, text)
        self.assertEqual(fields["tags"][0], "北京、广州")
        self.assertNotIn("薪资", text)

    def test_partial_detail_is_not_saved_as_complete(self):
        fields = site.parse_detail(htmltext.parse(DETAIL.replace("职位要求", "未加载")))
        self.assertFalse(fields["description"])

    def test_loading_sections_are_not_complete_but_short_real_content_is(self):
        originals = ("参与示例系统开发。\n维护 Java 服务。", "本科，每周到岗4天，实习3个月。<br>熟悉 Java 和 MySQL。")
        for original in originals:
            for placeholder in ("正在加载，请稍候...", "加载中…", "请稍后", "Loading...", "Please wait…",
                                "Loading, please wait a moment...", "正在加载，请稍等片刻...",
                                "Loading job description, please wait...", "加载失败，请刷新重试。",
                                "职位描述正在加载中，请稍候...", "职位要求加载失败，请稍后重试。",
                                "Failed to load job requirements, please refresh the page and try again.",
                                "正在为您加载职位信息...", "加载中，请稍等几秒钟",
                                "Loading job requirements, please wait a few seconds...",
                                "Unable to load job description. Please try again later.",
                                "Sorry, we couldn't load your job details. Please reload this page.",
                                "<span>正在加载</span><span>，请稍候...</span>"):
                with self.subTest(original=original, placeholder=placeholder):
                    fields = site.parse_detail(htmltext.parse(DETAIL.replace(original, placeholder)))
                    self.assertFalse(fields["description"])
        for short_content in ("写测试", "Java", "加载数据", "读取数据", "刷新页面", "实现 Loading 状态与异步加载。",
                              "页面正在加载时显示请稍候提示。", "Implement loading job description and retry UI."):
            with self.subTest(short_content=short_content):
                html = DETAIL
                for original in originals:
                    html = html.replace(original, short_content)
                fields = site.parse_detail(htmltext.parse(html))
                self.assertIn(short_content, fields["description"])

    def test_login_link_is_public_but_login_wall_and_security_checks_stop(self):
        url = site.search_url("Java", "CT_45")
        self.assertIsNone(site.page_problem(url, "校园招聘", htmltext.parse(listing()), 200))
        for address, title, html, status in (
                (url, "校园招聘", listing(), 403), (url, "校园招聘", listing(), 429),
                (url, "安全验证", listing(), 200),
                (url, "校园招聘", '<div class="captcha">验证</div>', 200),
                (url, "校园招聘", '<div class="login-dialog">登录</div>', 200),
                (site.ORIGIN + "/campus/login", "登录", "", 200),
                (site.ORIGIN + "/referral/position", "内推", "", 200),
                ("https://example.invalid/", "", "", 200)):
            with self.subTest(address=address, title=title, status=status):
                self.assertIsNotNone(site.page_problem(address, title, htmltext.parse(html), status))
        hidden = '<div hidden><div class="captcha">占位</div></div>'
        self.assertIsNone(site.page_problem(url, "校园招聘", htmltext.parse(hidden), 200))

    def test_public_review_placeholders_are_rejected_in_either_required_section(self):
        originals = ("参与示例系统开发。\n维护 Java 服务。", "本科，每周到岗4天，实习3个月。<br>熟悉 Java 和 MySQL。")
        notices = ("Job description", "Requirements", "职位要求", "岗位职责", "任职资格", "工作内容",
                   "JOB_DESCRIPTION", "Required Qualifications", "Key Responsibilities", "Role Overview",
                   "Ｌｏａｄｉｎｇ...", "加载失败，点击重试", "网络异常，请稍后再试",
                   "Something went wrong. Please try again.", "请求超时，请稍后再试", "Server error. Please retry.",
                   "...", "&#8203;", "\u200bＬｏａｄｉｎｇ\u200d...", "职位描述：Job description...")
        for original in originals:
            for notice in notices:
                with self.subTest(section=original, notice=notice):
                    self.assertFalse(site.parse_detail(htmltext.parse(DETAIL.replace(original, notice)))["description"])

    def test_placeholder_normalization_does_not_rewrite_real_content(self):
        for content in ("Ｊａｖａ", "C++", "写测试", "加载数据", "读取数据", "刷新页面",
                        "维护网络异常诊断工具。", "Implement Job description rendering and retries.",
                        "开发\u200b工具", "Investigate something went wrong errors in the test suite."):
            with self.subTest(content=content):
                page = DETAIL.replace("参与示例系统开发。\n维护 Java 服务。", content)
                self.assertIn(content, site.parse_detail(htmltext.parse(page))["description"])

    def test_nontext_security_markers_only_ignore_explicit_hidden_markup(self):
        url = site.search_url("Java", "CT_45")
        for tag in ("iframe", "canvas", "svg", "object"):
            marker = f'<{tag} id="captcha-frame"></{tag}>'
            with self.subTest(tag=tag):
                problem = site.page_problem(url, "校园招聘", htmltext.parse(listing() + marker), 200)
                self.assertEqual(problem[0], "blocked")
                if tag != "iframe":  # iframe fallback markup is raw text, not child DOM
                    nested = f'<{tag}><div class="captcha">验证</div></{tag}>'
                    self.assertEqual(site.page_problem(url, "校园招聘", htmltext.parse(nested), 200)[0], "blocked")
            for hidden in ("hidden", 'style="display: none"', 'style="visibility: hidden !important"'):
                for html in (f'<div {hidden}>{marker}</div>', f'<{tag} id="captcha-frame" {hidden}></{tag}>'):
                    with self.subTest(tag=tag, html=html):
                        self.assertIsNone(site.page_problem(url, "校园招聘", htmltext.parse(html), 200))
        login = '<iframe class="login-dialog"></iframe>'
        self.assertEqual(site.page_problem(url, "校园招聘", htmltext.parse(login), 200)[0], "login")

    def test_empty_state_is_explicit_not_the_loading_zero(self):
        self.assertFalse(site.list_is_empty(htmltext.parse('<div class="listTitle">开启新的工作（0）</div>')))
        html = '<div class="positionList-content"><p class="listNoData-text">暂无职位，请尝试其他搜索条件…</p></div>'
        self.assertTrue(site.list_is_empty(htmltext.parse(html)))
        self.assertFalse(site.list_is_empty(htmltext.parse('<div hidden>' + html + '</div>')))

    def test_nonrendered_security_markers_and_ancestors_are_ignored(self):
        url = site.search_url("Java", "CT_45")
        for tag in ("script", "style", "noscript", "template", "head", "select"):
            for marker, kind in (('<iframe id="captcha-frame"></iframe>', "blocked"),
                                 ('<div class="login-dialog">登录</div>', "login")):
                for html in (f'<{tag} class="captcha login-dialog"></{tag}>',
                             f'<{tag}>{marker}</{tag}>'):
                    with self.subTest(tag=tag, html=html):
                        self.assertIsNone(site.page_problem(url, "校园招聘", htmltext.parse(listing() + html), 200))
                        problem = site.page_problem(url, "校园招聘", htmltext.parse(listing() + html + marker), 200)
                        self.assertEqual(problem[0], kind)

    def test_hidden_first_selector_does_not_mask_a_visible_security_or_login_wall(self):
        for kind, html in (
                ("blocked", '<div hidden class="captcha">占位</div><div id="captcha">验证</div>'),
                ("blocked", '<div hidden class="captcha">占位</div><div class="page-verify">验证</div>'),
                ("login", '<div hidden class="login-dialog">占位</div><div class="login-form">登录</div>')):
            with self.subTest(kind=kind, html=html):
                problem = site.page_problem(site.search_url("Java", "CT_45"), "校园招聘",
                                            htmltext.parse(listing() + html), 200)
                self.assertIsNotNone(problem)
                self.assertEqual(problem[0], kind)

    def test_standalone_closed_notices_but_not_a_phrase_inside_requirements(self):
        for notice in ("职位已关闭", "职位已下线", "该职位已下线", "该职位已停止招聘"):
            with self.subTest(notice=notice):
                html = f'<div class="atsx-result-subtitle">{notice}。</div>'
                self.assertTrue(site.is_closed(htmltext.parse(html)))
                self.assertFalse(site.is_closed(htmltext.parse('<div hidden>' + html + '</div>')))
        self.assertFalse(site.is_closed(htmltext.parse(DETAIL.replace("维护 Java 服务。", "识别职位已下线提示。"))))

    def test_title_identity_and_multiple_cities(self):
        self.assertTrue(site.same_job("示例 后端实习生", "示例后端实习生"))
        self.assertFalse(site.same_job("示例后端实习生", "示例后端实习生（算法）"))
        self.assertTrue(site.location_matches("北京、广州、深圳", "广州"))
        self.assertFalse(site.location_matches("北京、深圳", "广州"))


class FakeTab:
    headless = True

    def __init__(self, pages=None, details=None):
        self.pages = list(pages or [listing()])
        self.details = details or {}
        self.calls = []
        self.closed = False

    def open(self, url, ready):
        self.calls.append(url)
        job_id = site.job_id_from_url(url)
        body = self.details.get(job_id, DETAIL) if job_id else self.pages.pop(0)
        if isinstance(body, collect.Snapshot):
            return body
        return collect.Snapshot(url=url, title="校园招聘", html=body, status=200)

    def close(self):
        self.closed = True


class SharedCollector(unittest.TestCase):
    def test_cli_selects_adapter_and_closes_its_tab(self):
        tab = FakeTab()
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()) as output:
            with mock.patch.object(cli.browser, "open_tab", return_value=tab), mock.patch.object(collect._Pacer, "before_action"):
                code = cli.main(["collect", "bytedance", "--query", "后端", "--city", "广州", "--max", "1",
                                 "--data-dir", directory])
        self.assertEqual(code, 0)
        self.assertTrue(tab.closed)
        self.assertEqual(json.loads(output.getvalue())["saved"], 1)
        self.assertIn("location=CT_45", tab.calls[0])

    def test_cli_headless_default_and_explicit_cdp_use_checked_address(self):
        for extra, expected in (([], None), (["--cdp", "http://localhost:9333/"], "http://localhost:9333")):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                tab = FakeTab()
                with redirect_stdout(io.StringIO()), mock.patch.object(browser, "open_tab", return_value=tab) as opened, \
                        mock.patch.object(collect._Pacer, "before_action"):
                    code = cli.main(["collect", "bytedance", "--query", "后端", "--city", "广州", "--max", "1",
                                     "--data-dir", directory, *extra])
                self.assertEqual(code, 0)
                opened.assert_called_once_with(expected)
                self.assertTrue(tab.closed)

    def test_city_code_override_and_invalid_arguments_before_browser(self):
        options = collect.make_options("Java", city_code="CT_45", site=site)
        self.assertIs(options.site, site)
        self.assertEqual(options.city_code, "CT_45")
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()) as output:
            tab = FakeTab()
            with mock.patch.object(browser, "open_tab", return_value=tab), mock.patch.object(collect._Pacer, "before_action"):
                code = cli.main(["collect", "bytedance", "--query", "Java", "--city-code", "CT_45", "--max", "1",
                                 "--data-dir", directory])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["city_code"], "CT_45")
            self.assertIn("location=CT_45", tab.calls[0])
        for extra in (["--city-code", "101280100"], ["--city-code", "CT_"], ["--city-code", "CT_12345678901"],
                      ["--city", "广州", "--cdp", "http://192.0.2.1\\@127.0.0.1:9222"]):
            with self.subTest(extra=extra), redirect_stderr(io.StringIO()) as error, \
                    mock.patch.object(browser, "open_tab") as opened:
                self.assertEqual(cli.main(["collect", "bytedance", "--query", "Java", *extra]), 2)
                self.assertIn("error", json.loads(error.getvalue()))
                opened.assert_not_called()

    def run_batch(self, root, tab, **kwargs):
        kwargs.setdefault("batch", "bytedance-example")
        options = collect.make_options("后端", city="广州", site=site, **kwargs)
        self.pauses = []
        return collect.run(tab, options, root, sleep=self.pauses.append, uniform=lambda a, b: a, clock=lambda: NOW)

    def test_inbox_is_master_compatible_and_resume_is_scoped_by_host(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_batch(root, FakeTab(), max_jobs=2)
            self.assertEqual(result["saved"], 2)
            self.assertEqual(self.pauses, [4.0, 4.0])
            batch = Path(result["batch_dir"])
            item = json.loads((batch / "900001.json").read_text(encoding="utf-8"))
            self.assertEqual(item["site"], "official")
            self.assertNotIn("site_job_id", item)
            self.assertEqual(item["extra"]["site_job_id"], "900001")
            self.assertEqual(item["url"], site.canonical_url("900001"))
            self.assertEqual(screen.check(batch, site.SITE, vocab.load())["failed"], 0)
            tab = FakeTab()
            resumed = self.run_batch(root, tab, max_jobs=2, max_pages=1)
            self.assertEqual(resumed["saved"], 0)
            self.assertEqual(resumed["skipped_known"], 2)
            self.assertEqual(len(tab.calls), 1)
            self.assertEqual(collect._job_ids_in({"site": "official", "site_job_id": "900001",
                                                "url": "https://example.invalid/job/900001"}, site), set())

    def test_metadata_overrides_and_default_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_batch(Path(directory), FakeTab(), max_jobs=1, batch=None)
            self.assertEqual(result["batch"], "bytedance-20261105-223000")
            batch = Path(result["batch_dir"])
            self.assertEqual(batch.parent.name, "official")
            item = json.loads((batch / "900001.json").read_text(encoding="utf-8"))
            self.assertEqual(item["extra"]["collector"], "jobsearch_cn.collect.bytedance/1")
            self.assertEqual(item["extra"]["site_job_id"], "900001")
            self.assertEqual(item["fetched_at"], NOW.isoformat(timespec="seconds"))
            self.assertNotIn("site_job_id", item)
        fallback = SimpleNamespace(**{key: value for key, value in vars(site).items()
                                      if not key.startswith("_") and key not in ("SOURCE_NAME", "COLLECTOR")})
        with tempfile.TemporaryDirectory() as directory:
            options = collect.make_options("后端", city="广州", site=fallback, max_jobs=1)
            result = collect.run(FakeTab(), options, Path(directory), sleep=lambda _: None, clock=lambda: NOW)
            self.assertEqual(result["batch"], "20261105-223000")
            item = json.loads((Path(result["batch_dir"]) / "900001.json").read_text(encoding="utf-8"))
            self.assertEqual(item["extra"]["collector"], "jobsearch_cn.collect.official/1")

    def test_other_official_same_id_does_not_hide_a_new_bytedance_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            other = root / "inbox" / "official" / "another-company"
            other.mkdir(parents=True)
            (other / "900001.json").write_text(json.dumps({
                "format": "jobsearch_cn.inbox/1", "site": "official", "site_job_id": "900001",
                "url": "https://example.invalid/job/900001", "extra": {"site_job_id": "900001"},
            }), encoding="utf-8")
            for text, url in (("其他官网虚构实习生\n维护示例文档。", "https://example.invalid/job/900001"),
                              ("已保存字节虚构实习生\n维护虚构测试。", site.canonical_url("900002"))):
                records, _ = jd_parser.parse_text(text, site="official", url=url, now=NOW)
                store.Store(root).save(records[0])
            tab = FakeTab()
            result = self.run_batch(root, tab, max_jobs=2, max_pages=1)
            self.assertEqual((result["saved"], result["skipped_known"]), (1, 1))
            self.assertEqual([site.job_id_from_url(url) for url in tab.calls[1:]], ["900001"])

    def test_http_known_sources_are_skipped_and_cannot_replace_complete_text(self):
        for location in ("inbox", "jobs"):
            for authority in ("jobs.bytedance.com", "jobs.bytedance.com:80"):
                with self.subTest(location=location, authority=authority), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    url = f"http://{authority}/campus/position/900001/detail"
                    if location == "inbox":
                        folder = root / "inbox" / "official" / "older"
                        folder.mkdir(parents=True)
                        original = folder / "900001.json"
                        original.write_text(json.dumps({"site": "official", "url": url,
                                                       "text": "完整虚构正文：维护示例服务。"}), encoding="utf-8")
                    else:
                        records, _ = jd_parser.parse_text("示例实习生\n完整虚构正文：维护示例服务。",
                                                         site="official", url=url, now=NOW)
                        store.Store(root).save(records[0])
                        original = next((root / "jobs").glob("job_*.json"))
                    before = original.read_bytes()
                    partial = DETAIL.replace("参与示例系统开发。\n维护 Java 服务。", "Job description")
                    tab = FakeTab(pages=[listing(("900001",))], details={"900001": partial})
                    result = self.run_batch(root, tab, max_jobs=1, max_pages=1, batch="older")
                    self.assertEqual((result["saved"], result["skipped_known"]), (0, 1))
                    self.assertEqual(len(tab.calls), 1, "known HTTP source must not be requested again")
                    self.assertEqual(original.read_bytes(), before)

    def test_same_batch_collisions_preserve_other_sources_and_unreadable_originals(self):
        other = json.dumps({"site": "official", "url": "https://example.invalid/job/900002",
                            "text": "完整虚构的另一官网原件"}).encode("utf-8")
        for original in (other, b"{broken-json", b"\xff\xfe"):
            with self.subTest(original=original), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                batch = root / "inbox" / "official" / "shared"
                batch.mkdir(parents=True)
                target = batch / "900002.json"
                target.write_bytes(original)
                tab = FakeTab(pages=[listing(("900001", "900002", "900003"))])
                result = self.run_batch(root, tab, batch="shared", max_jobs=3)
                self.assertEqual((collect.exit_code(result), result["saved"]), (3, 1))
                self.assertIn("同名文件", result["message"])
                self.assertIn("--batch", result["message"])
                self.assertEqual(target.read_bytes(), original)
                self.assertEqual(result["files"], ["900001.json"])
                self.assertNotIn(site.canonical_url("900003"), tab.calls)
                self.assertFalse(list(batch.glob(".tmp-*")))

    def test_file_created_after_collection_started_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "inbox" / "official" / "shared" / "900001.json"

            class OtherWriter(FakeTab):
                def open(self, url, ready):
                    if site.job_id_from_url(url):
                        target.parent.mkdir(parents=True)
                        target.write_bytes(b"complete original from another writer")
                    return super().open(url, ready)

            result = self.run_batch(root, OtherWriter(), batch="shared", max_jobs=1)
            self.assertEqual((collect.exit_code(result), result["saved"]), (3, 0))
            self.assertEqual(target.read_bytes(), b"complete original from another writer")
            self.assertFalse(list(target.parent.glob(".tmp-*")))

    def test_unsupported_atomic_publication_stops_without_a_partial_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tab = FakeTab()
            with mock.patch.object(store.os, "link", side_effect=OSError("hard links unavailable")):
                result = self.run_batch(root, tab, max_jobs=2)
            self.assertEqual((collect.exit_code(result), result["saved"]), (3, 0))
            self.assertIn("无法安全写入", result["message"])
            self.assertNotIn(site.canonical_url("900002"), tab.calls)
            self.assertFalse(list(root.rglob("*.json")))

    def test_headless_login_advice_does_not_suggest_waiting_as_a_login_fix(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_batch(Path(directory), FakeTab(pages=['<div class="login-dialog">登录</div>']), max_jobs=1)
            self.assertEqual((result["status"], result["saved"]), ("needs_user", 0))
            self.assertIn(collect.SIGN_IN_HEADLESS, result["message"])
            self.assertNotIn(collect.NEEDS_USER_HEADLESS, result["message"])

    def test_deferred_same_site_data_denial_prevents_next_navigation_and_preserves_file(self):
        class CampusPage(FakePage):
            def __init__(self):
                super().__init__()
                self.url, self.pending, self.visited = "about:blank", None, []

            def goto(self, url, wait_until, timeout):
                self.visited.append(url)
                return super().goto(url, wait_until, timeout)

            def title(self):
                # Model Playwright dispatching responses only when control re-enters its API.
                pending, self.pending = self.pending, None
                if pending is not None:
                    for listener in self.listeners:
                        listener(pending)
                return "校园招聘"

            def content(self):
                return DETAIL if site.job_id_from_url(self.url) else listing()

        for status in (403, 429):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root, page = Path(directory), CampusPage()
                playwright = FakePlaywright(page)
                tab = browser.Tab(playwright, page, FakeError, browser=playwright.browser, headless=True)
                options = collect.make_options("后端", city="广州", site=site, max_jobs=2, batch="bytedance-denied")
                first_file = root / "inbox" / "official" / options.batch / "900001.json"

                def during_pause(_):
                    if first_file.exists():
                        page.pending = FakeResponse("https://api.bytedance.com/fictional-data", status)

                try:
                    with mock.patch.object(browser, "SETTLE_S", 0):
                        result = collect.run(tab, options, root, sleep=during_pause, clock=lambda: NOW)
                finally:
                    tab.close()
                self.assertEqual((result["status"], result["saved"], collect.exit_code(result)), ("needs_user", 1, 3))
                self.assertIn(f"HTTP {status}", result["message"])
                self.assertEqual([site.job_id_from_url(url) for url in page.visited], [None, "900001"])
                self.assertEqual(json.loads(first_file.read_text(encoding="utf-8"))["extra"]["site_job_id"], "900001")
                self.assertFalse((first_file.parent / "900002.json").exists())
                self.assertTrue(page.closed and playwright.browser.closed and playwright.stopped)

    def test_blocked_detail_keeps_already_saved_jobs(self):
        blocked = collect.Snapshot(url=site.canonical_url("900002"), title="安全验证", html="", status=429)
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_batch(Path(directory), FakeTab(details={"900002": blocked}), max_jobs=2)
            self.assertEqual(result["status"], "needs_user")
            self.assertEqual(result["saved"], 1)
            self.assertEqual(collect.exit_code(result), 3)

    def test_unknown_second_list_is_not_end_of_list(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_batch(Path(directory), FakeTab(pages=[listing(), '<div>未加载</div>']), max_jobs=3)
            self.assertEqual(result["status"], "page_changed")
            self.assertEqual(result["saved"], 0)

    def test_visible_wall_after_hidden_placeholder_stops_before_detail_navigation(self):
        page = listing() + '<div hidden class="captcha">占位</div><div class="page-verify">验证</div>'
        with tempfile.TemporaryDirectory() as directory:
            tab = FakeTab(pages=[page])
            result = self.run_batch(Path(directory), tab, max_jobs=1)
            self.assertEqual((collect.exit_code(result), result["saved"]), (3, 0))
            self.assertEqual(len(tab.calls), 1)
            self.assertIsNone(result["batch_dir"])

    def test_nontext_captcha_stops_navigation_and_keeps_prior_saved_job(self):
        for tag in ("iframe", "canvas", "svg", "object"):
            marker = f'<{tag} id="captcha-frame"></{tag}>'
            for phase in ("list", "detail"):
                with self.subTest(tag=tag, phase=phase), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    tab = (FakeTab(pages=[listing() + marker]) if phase == "list" else
                           FakeTab(pages=[listing(("900001", "900002", "900003"))],
                                   details={"900002": DETAIL + marker}))
                    result = self.run_batch(root, tab, max_jobs=2 if phase == "list" else 3)
                    self.assertEqual(collect.exit_code(result), 3)
                    self.assertEqual(result["saved"], 0 if phase == "list" else 1)
                    self.assertEqual(len(tab.calls), 1 if phase == "list" else 3)
                    self.assertNotIn(site.canonical_url("900003"), tab.calls)

    def test_closed_detail_is_counted_and_never_imported(self):
        with tempfile.TemporaryDirectory() as directory:
            tab = FakeTab(details={"900001": '<div class="atsx-result-subtitle">该职位已下线</div>'})
            result = self.run_batch(Path(directory), tab, max_jobs=2)
            self.assertEqual((collect.exit_code(result), result["saved"], result["closed"]), (0, 1, 1))
            self.assertEqual(result["files"], ["900002.json"])

    def test_nonrendered_captcha_placeholders_do_not_stop_normal_collection(self):
        for marker in ('<script id="captcha-sdk" type="application/json">{}</script>',
                       '<template id="captcha-placeholder">...</template>',
                       '<template><iframe id="captcha-frame"></iframe></template>'):
            for phase in ("list", "detail"):
                with self.subTest(marker=marker, phase=phase), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    tab = FakeTab(pages=[listing(("900001",)) + (marker if phase == "list" else "")],
                                  details={"900001": DETAIL + (marker if phase == "detail" else "")})
                    result = self.run_batch(root, tab, max_jobs=1, max_pages=1)
                    self.assertEqual((collect.exit_code(result), result["saved"]), (0, 1))
                    self.assertEqual([site.job_id_from_url(url) for url in tab.calls], [None, "900001"])
                    saved = json.loads((Path(result["batch_dir"]) / "900001.json").read_text(encoding="utf-8"))
                    self.assertIn("维护 Java 服务。", saved["text"])

    def test_placeholder_detail_stops_without_saving_and_keeps_previous_record(self):
        partial = DETAIL.replace("参与示例系统开发。\n维护 Java 服务。", "正在加载，请稍候...")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tab = FakeTab(details={"900002": partial})
            result = self.run_batch(root, tab, max_jobs=2)
            self.assertEqual((collect.exit_code(result), result["saved"]), (4, 1))
            first = Path(result["batch_dir"]) / "900001.json"
            self.assertIn("维护 Java 服务。", json.loads(first.read_text(encoding="utf-8"))["text"])
            self.assertFalse((first.parent / "900002.json").exists())

    def test_public_review_placeholder_stops_after_first_complete_detail(self):
        for notice in ("Job description", "Ｌｏａｄｉｎｇ...", "网络异常，请稍后再试", "...", "&#8203;"):
            with self.subTest(notice=notice), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                partial = DETAIL.replace("参与示例系统开发。\n维护 Java 服务。", notice)
                tab = FakeTab(pages=[listing(("900001", "900002", "900003"))], details={"900002": partial})
                result = self.run_batch(root, tab, max_jobs=3)
                self.assertEqual((collect.exit_code(result), result["saved"]), (4, 1))
                self.assertEqual(result["files"], ["900001.json"])
                self.assertNotIn(site.canonical_url("900003"), tab.calls)

    def test_empty_result_does_not_create_batch_and_wrong_detail_stops(self):
        empty = '<div class="positionList-content"><p class="listNoData-text">暂无职位</p></div>'
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_batch(Path(directory), FakeTab(pages=[empty]), max_jobs=1)
            self.assertEqual(result["finished"], "no_results")
            self.assertIsNone(result["batch_dir"])
            bad = DETAIL.replace("示例后端实习生", "不同岗位")
            result = self.run_batch(Path(directory), FakeTab(details={"900001": bad}), max_jobs=1)
            self.assertEqual(result["status"], "page_changed")
            self.assertEqual(result["saved"], 0)


if __name__ == "__main__":
    unittest.main()
