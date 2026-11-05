"""Fictional campus DOM only. Real postings and holdout samples are never fixtures."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest import mock

from jobsearch_cn import bytedance as site, cli, collect, htmltext, screen, vocab


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

    def test_empty_state_is_explicit_not_the_loading_zero(self):
        self.assertFalse(site.list_is_empty(htmltext.parse('<div class="listTitle">开启新的工作（0）</div>')))
        html = '<div class="positionList-content"><p class="listNoData-text">暂无职位，请尝试其他搜索条件…</p></div>'
        self.assertTrue(site.list_is_empty(htmltext.parse(html)))
        self.assertFalse(site.list_is_empty(htmltext.parse('<div hidden>' + html + '</div>')))

    def test_title_identity_and_multiple_cities(self):
        self.assertTrue(site.same_job("示例 后端实习生", "示例后端实习生"))
        self.assertFalse(site.same_job("示例后端实习生", "示例后端实习生（算法）"))
        self.assertTrue(site.location_matches("北京、广州、深圳", "广州"))
        self.assertFalse(site.location_matches("北京、深圳", "广州"))


class FakeTab:
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

    def run_batch(self, root, tab, **kwargs):
        options = collect.make_options("后端", city="广州", adapter=site, batch="bytedance-example", **kwargs)
        self.pauses = []
        return collect.run(tab, options, root, adapter=site, sleep=self.pauses.append, uniform=lambda a, b: a)

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
