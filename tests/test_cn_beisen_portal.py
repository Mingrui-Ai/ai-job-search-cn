"""The portable Beisen CLI reads one page and only the synthetic whitelist on disk."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from jobsearch_cn import beisen, browser, cli, collect, htmltext
from tests.test_cn_beisen import (A, B, CONFIG, NEW_HOST, OLD_HOST, TENANTS, card, item, legacy_detail,
                                  legacy_list, list_response, new_detail, new_list)
from tests.test_cn_single_link import FakeSingle


class Portal(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / "collect" / "beisen.json"
        self.config.parent.mkdir()
        self.config.write_text(json.dumps(CONFIG), encoding="utf-8")
        self.new = beisen.tenant_rules(TENANTS["example"], "intern")
        self.old = beisen.tenant_rules(TENANTS["example-legacy"], "campus")

    def call(self, site, *args, tab=None, code=None):
        tab = tab or FakeSingle()
        scope = ["--tenant", site.tenant.subdomain, "--channel", site.channel] if site else []
        argv = ["beisen-portal", *args, *scope, "--data-dir", str(self.root)]
        with mock.patch.object(browser, "open_single_tab", return_value=tab), \
                mock.patch.object(collect.time, "sleep"), \
                mock.patch.object(cli.personal, "load_adapters", side_effect=AssertionError), \
                mock.patch.object(beisen, "profile_keywords", side_effect=AssertionError), \
                mock.patch.object(collect, "known_job_ids", side_effect=AssertionError), \
                redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            status = cli.main(argv)
        self.assertEqual({p for p in self.root.rglob("*")}, {self.config.parent, self.config})
        if code:
            self.assertEqual((status, out.getvalue()), (1, ""))
            failure = json.loads(err.getvalue())
            self.assertEqual(set(failure), {"error", "code"})
            self.assertEqual(failure["code"], code)
        else:
            self.assertEqual((status, err.getvalue()), (0, ""))
        return out.getvalue()

    def test_new_search_one_document_only_visible_cards_and_dates(self):
        url = self.new.search_url("工程", "4401")
        entry = item(A, "测试\u200b工程师(J12345)")
        hidden = item(B, "页面没有的岗位")
        visible = card(entry).replace("2026-09-07", date.today().isoformat())
        snap = new_list(url, list_response([entry, hidden], keyword="工程"), cards=visible)
        tab = FakeSingle(snap)
        payload = json.loads(self.call(self.new, "search", "-q", "工程", "-l", "广州市", "--jobage", "0",
                                       "--page", "1", "--limit", "1", tab=tab))
        self.assertEqual(tab.calls, ["robots", url, "close"])
        self.assertEqual(payload, {"meta": {"count": 1, "page": 1}, "results": [
            {"id": "beisen.example." + A, "title": "测试工程师", "company": "示例科技", "location": "广东省·广州市",
             "date": date.today().isoformat(), "url": self.new.canonical_url("beisen.example." + A)}]})

    def test_legacy_date_filter_is_applied_before_limit(self):
        url = self.old.search_url("", "4401")
        html = legacy_list([("21", "旧岗位"), ("22", "未知日期"), ("23", "新岗位")], 1, 1, 3)
        for value in ((date.today() - timedelta(days=15)).isoformat(), "未知", date.today().isoformat()):
            html = html.replace("2026-09-14</td>", value + "</td>", 1)
        tab = FakeSingle(collect.Snapshot(url, "", html.replace('title="新岗位"', 'title="内部文字"'), 200))
        data = json.loads(self.call(self.old, "search", "--jobage", "14", "--limit", "1", tab=tab))
        self.assertEqual([row["title"] for row in data["results"]], ["新岗位"])
        self.assertEqual(data["results"][0]["url"], OLD_HOST + "/zpdetail/23")

    def test_empty_and_unrecognised_pages_are_distinct(self):
        url = self.new.search_url("", "4401")
        tab = FakeSingle(new_list(url, list_response([])))
        self.assertEqual(json.loads(self.call(self.new, "search", tab=tab))["results"], [])
        for snap in (new_list(url, list_response([item(A, "页内不可见")]), cards=""),
                     collect.Snapshot(url, "", "<main/>", 200),
                     collect.Snapshot(url + "&another=1", "", "changed", 200)):
            self.call(self.new, "search", tab=FakeSingle(snap), code="PAGE_CHANGED")

    def test_new_card_must_uniquely_identify_one_response_and_one_dom_card(self):
        url = self.new.search_url("", "4401")
        first, second = item(A, "重名岗位(J12345)"), item(B, "重名岗位(J12345)")
        for entries, visible in (([first, second], card(first)), ([first], card(first) * 2)):
            snap = new_list(url, list_response(entries), cards=visible)
            self.call(self.new, "search", tab=FakeSingle(snap), code="PAGE_CHANGED")

    def test_date_requires_a_publication_label_but_collect_retains_its_original_dates(self):
        for site, job, body in (
                (self.old, self.old.prefix + "123", legacy_detail("岗位").replace("发布时间：", "更新时间：")),
                (self.new, self.new.prefix + A, new_detail("岗位").replace(" 发布", " 更新")),
                (self.new, self.new.prefix + A, new_detail("岗位").replace(" 发布", ""))):
            url = site.canonical_url(job)
            self.assertIsNotNone(site.parse_detail(htmltext.parse(body))["published"])
            result = self.call(site, "detail", job, tab=FakeSingle(collect.Snapshot(url, "", body, 200)))
            self.assertIsNone(json.loads(result)["date"])
        url = self.new.search_url("", "4401")
        entry = item(A, "示例岗位")
        snap = new_list(url, list_response([entry]), cards=card(entry).replace(" 发布", " 更新"))
        rows = json.loads(self.call(self.new, "search", tab=FakeSingle(snap)))["results"]
        self.assertIsNone(rows[0]["date"])
        url = self.old.search_url("", "4401")
        html = legacy_list([("21", "虚构岗位")], 1, 1, 1).replace("发布时间", "更新时间")
        rows = json.loads(self.call(self.old, "search", tab=FakeSingle(collect.Snapshot(url, "", html, 200))))["results"]
        self.assertIsNone(rows[0]["date"])
        rows = self.call(self.old, "search", "--jobage", "99999", tab=FakeSingle(collect.Snapshot(url, "", html, 200)))
        self.assertEqual(json.loads(rows)["results"], [])

    def test_apply_detail_with_url_only_uses_strict_whitelist_and_unambiguous_channel(self):
        for site, job, body, source in (
                (self.old, self.old.prefix + "123", legacy_detail("岗位"), "whitelist_single"),
                (self.new, self.new.prefix + A, new_detail("岗位"), "url")):
            url = site.canonical_url(job)
            tab = FakeSingle(collect.Snapshot(url, "", body, 200))
            self.assertIn("任职资格", self.call(None, "detail", url, "--format", "plain", tab=tab))
            self.assertEqual(json.loads(self.call(None, "detail", url, tab=tab))["channel_source"], source)
        config = json.loads(self.config.read_text(encoding="utf-8"))
        config["tenants"][1]["channels"].append("intern")
        self.config.write_text(json.dumps(config), encoding="utf-8")
        tab = FakeSingle()
        url = self.old.canonical_url(self.old.prefix + "123")
        for value in (url, url + "#extra", self.old.prefix + "123"):
            self.call(None, "detail", value, tab=tab, code="BAD_ARGS")
        self.call(None, "detail", url.replace("example-legacy.", "unlisted."), tab=tab, code="WHITELIST")
        self.assertEqual(tab.calls, [])

    def test_id_and_url_detail_have_source_and_only_visible_text(self):
        for site, job, body, source in (
                (self.new, self.new.prefix + A, new_detail("测试岗位"), "url"),
                (self.old, self.old.prefix + "123", legacy_detail("测试岗位"), "argument")):
            url = site.canonical_url(job)
            html = body.replace("测试岗位", "测\u202e试岗位<span hidden>不可见</span>")
            for value in (url, job):
                tab = FakeSingle(collect.Snapshot(url, "", html, 200))
                raw = self.call(site, "detail", value, tab=tab)
                self.assertNotIn("不可见", raw)
                data = json.loads(raw)
                self.assertEqual((data["id"], data["url"], data["title"]), (job, url, "测试岗位"))
                self.assertEqual((data["company_source"], data["channel_source"]), ("whitelist", source))
                self.assertIn("任职资格", data["description"])
                self.assertEqual(tab.calls, ["robots", url, "close"])

    def test_robots_restrictions_and_late_denial_are_final(self):
        for args in (["search"], ["detail", self.new.prefix + A]):
            tab = FakeSingle(body=b"User-agent: *\nDisallow: /")
            self.call(self.new, *args, tab=tab, code="ROBOTS")
            self.assertEqual(tab.calls, ["robots", "close"])
            tab = FakeSingle(closing_reason="网站返回 HTTP 429")
            self.call(self.new, *args, tab=tab, code="ACCESS_STOP")
            self.assertEqual(len(tab.calls), 3)
            self.assertTrue(tab.closed)

    def test_closed_or_incomplete_details_and_tables(self):
        url = self.old.canonical_url(self.old.prefix + "123")
        incomplete = legacy_detail("岗位").replace("本科及以上学历，熟悉 Java。", "正在加载")
        for html, code in (("<p>职位已下线</p>", "CLOSED"), (incomplete, "PAGE_CHANGED")):
            self.call(self.old, "detail", url, tab=FakeSingle(collect.Snapshot(url, "", html, 200)), code=code)
        for fmt, separator in (("table", "\t"), ("plain", " | ")):
            text = self.call(self.old, "detail", url, "--format", fmt,
                             tab=FakeSingle(collect.Snapshot(url, "", legacy_detail("岗位"), 200)))
            self.assertIn(separator, text)
            self.assertIn("任职资格", text)

    def test_unverified_or_invalid_inputs_never_open_browser(self):
        tab = FakeSingle()
        for args in (["search", "--page", "2"], ["search", "--limit", "21"], ["search", "-l", "深圳"],
                     ["search", "--jobage", "-1"], ["search", "--bogus"], ["search", "--query", "x" * 51],
                     ["detail", "beisen.example.invalid"], ["detail", OLD_HOST + "/zpdetail/123"],
                     ["detail", NEW_HOST + "/campus/detail?jobAdId=" + A], ["detail", "beisen.elsewhere." + A],
                     ["detail", self.new.canonical_url(self.new.prefix + A) + "&extra=1"]):
            with self.subTest(args=args):
                self.call(self.new, *args, tab=tab, code="BAD_ARGS")
        self.config.write_text(json.dumps({**CONFIG, "tenants": CONFIG["tenants"][1:]}), encoding="utf-8")
        self.call(self.new, "search", tab=tab, code="WHITELIST")
        self.assertEqual(tab.calls, [])
