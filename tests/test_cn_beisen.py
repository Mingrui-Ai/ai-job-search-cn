"""Beisen portal rules and runs on fictional tenants (example.zhiye.com, 示例科技); offline.

Every list response, page and job text here is hand-written; none is copied from a real portal.
"""
import io
import json
import random
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from jobsearch_cn import beisen, browser, cli, collect, jd_parser, schema, screen, store

REPO = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 10, 21, 0, tzinfo=timezone(timedelta(hours=8)))
TODAY = date(2026, 11, 10)
A, B, C = (f"0f8e2c3a-1111-4abc-8def-00000000000{x}" for x in "abc")
CONFIG = {"format": beisen.CONFIG_FORMAT, "tenants": [
    {"subdomain": "example", "portal": "new", "company": "示例科技", "channels": ["intern", "campus"],
     "cities": ["广州"], "terms_url": "https://example.zhiye.com/privacy", "terms_checked": "2026-11-09"},
    {"subdomain": "example-legacy", "portal": "legacy", "company": "示例信息", "channels": ["campus"],
     "cities": ["广州"], "terms_url": "https://example-legacy.zhiye.com/Portal/Apply/PrivacyPolicy",
     "terms_checked": "2026-11-09"}]}
TENANTS = beisen.parse_tenants(CONFIG, TODAY)[0]
NEW_HOST = "https://example.zhiye.com"
OLD_HOST = "https://example-legacy.zhiye.com"


def item(uuid, name, salary="面议", places=("广州市",)):
    return {"JobAdId": uuid, "JobAdName": name, "Salary": salary, "LocNames": list(places), "Kind": "实习"}


def list_response(items, total=None, code=200, keyword=""):
    body = {"Code": code, "Message": "成功" if code == 200 else "示例错误", "Data": {
        "Total": len(items) if total is None else total, "List": items}}
    return collect.Response(url=f"{NEW_HOST}/api/Jobad/GetJobAdPageList", status=200,
                            request=json.dumps({"PageIndex": 1, "PageSize": 20, "KeyWords": keyword}),
                            body=json.dumps(body, ensure_ascii=False))


def new_list(url, *responses, total=None):
    count = total if total is not None else sum(len(json.loads(r.body)["Data"]["List"]) for r in responses)
    html = (f'<div class="style__STBreadJobInfo-editor__sc-x1 a"><div>全部职位（共 {count} 个）</div></div>'
            '<div class="style__STListItem-editor__sc-x2 b"><span>示例卡片</span></div>'
            '<div id="LIST_LAST_DOM"><div>没有更多了~</div></div>')
    return collect.Snapshot(url=url, title="实习生招聘", html=html, status=200, responses=tuple(responses))


def tag(text):
    return f'<span class="style__STJobTag-editor__sc-24"><span class="style__STJobTabInner-editor__sc-25">{text}</span></span>'


def new_detail(title, salary="面议", places=("广东省·广州市",), channel_label="实习生招聘"):
    salary_html = f'<div class="style__STJobNameRight-editor__sc-20 b">{salary}</div>' if salary else ""
    sections = "".join(
        f'<div class="style__STDutyContainer-editor__sc-28"><div class="style__STDutyTitle-editor__sc-29">{head}</div>'
        f'<div class="style__STDutyContent-editor__sc-31"><div class="style__STDutyItem-editor__sc-32">{body}</div></div></div>'
        for head, body in (("工作职责", "1. 参与示例 Agent 平台开发。<br>2. 编写 Python 服务。"),
                           ("任职资格", "熟悉 Python，每周到岗4天，实习3个月。")))
    return (f'<div class="sc-head">登录/注册</div><div class="style__STJobNameLeft-editor__sc-19 a"><span>{title}</span></div>'
            f'{salary_html}{tag(channel_label)}{tag("实习")}{"".join(tag(place) for place in places)}'
            f'<div class="style__STJobInfoRight-editor__sc-23">2026-09-07 发布</div>{sections}')


def legacy_list(rows, page, pages, total):
    body = "".join(f'<tr><td class="tableleft joblsttitle"><a title="{title}" href="/zpdetail/{job}?c=4401">{title}</a>'
                   '</td><td></td><td title="广东省-广州市">广东省-广州市</td><td>2026-09-14</td></tr>'
                   for job, title in rows)
    return (f'<a class="loginlink" href="/Portal/Account/Login?returnUrl=%2Fsearch">登录</a>'
            f'<table class="listtable"><thead><tr><th>职位名称</th></tr></thead><tbody>{body}</tbody></table>'
            f'<span class="tablenote">共{total}条记录</span><div class="tablefooter"><span>当前第{page}/{pages}页</span></div>')


def legacy_detail(title):
    return (f'<div class="boxSupertitle"><span class="title">{title}</span></div>'
            '<ul><li>工作地点：广东省-广州市</li><li>发布时间：2026-09-14</li></ul>'
            '<div><p>职位描述</p><div>负责示例系统开发。</div><p>职位要求</p><div>本科及以上学历，熟悉 Java。</div></div>'
            '<div class="footer">隐私政策</div>')


class Tab:
    """Answers list loads in order per list path and detail pages by job; records every call."""

    headless = True

    def __init__(self, lists=None, scrolls=None, details=None):
        self.lists, self.scrolls, self.details = lists or {}, list(scrolls or []), details or {}
        self.calls, self.patterns = [], None

    def capture(self, patterns):
        self.patterns = patterns

    def open(self, url, ready):
        self.calls.append(url)
        parts = urlsplit(url)
        if parts.path.endswith("/jobs") or parts.path == "/search":
            found = self.lists[parts.path].pop(0)
            found = found(url) if callable(found) else found
            return collect.Snapshot(url, "职位搜索", found, 200) if isinstance(found, str) else found
        found = self.details[url]
        if isinstance(found, collect.Snapshot):
            return found
        return collect.Snapshot(url=url, title="职位详情", html=found, status=200)

    def load_more(self, selectors, ready):
        self.calls.append("scroll")
        return self.scrolls.pop(0)

    def close(self):
        pass


def detail_url(uuid, channel="intern"):
    return f"{NEW_HOST}/{channel}/detail?jobAdId={uuid}"


class Runs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.delays = []

    def run_tenant(self, tab, tenant="example", keywords=(), channel=None, **limits):
        options = collect.make_search_options(beisen.searches(TENANTS[tenant], keywords, channel), **limits)
        return collect.run(tab, options, self.root, sleep=self.delays.append, uniform=random.Random(3).uniform,
                           clock=lambda: NOW)

    def saved(self, summary):
        return {name: json.loads((Path(summary["batch_dir"]) / name).read_text(encoding="utf-8"))
                for name in summary["files"]}

    def test_two_channels_negotiable_missing_salary_multi_city_and_last_page(self):
        first = list_response([item(A, "示例Agent开发实习生(J10001)", places=("广州市", "武汉市")),
                               item(B, "示例测试实习生", salary="")], total=3)
        second = list_response([item(C, "示例后端实习生", salary="15K-18K 元/月")], total=3)
        intern = f"{NEW_HOST}/intern/jobs"
        tab = Tab(lists={"/intern/jobs": [lambda url: new_list(url, first, total=3)],
                         "/campus/jobs": [lambda url: new_list(url, list_response([]), total=0)]},
                  scrolls=[new_list(intern, first, second, total=3)],
                  details={detail_url(A): new_detail("示例Agent开发实习生(J10001)", places=("广东省·广州市", "湖北省·武汉市")),
                           detail_url(B): new_detail("示例测试实习生", salary=None),
                           detail_url(C): new_detail("示例后端实习生", salary="15K-18K 元/月")})
        summary = self.run_tenant(tab)
        self.assertEqual((summary["status"], summary["saved"], summary["finished"], summary["list_loads"]),
                         ("done", 3, "end_of_list", 3))
        self.assertEqual([s["finished"] for s in summary["searches"]], ["end_of_list", "no_results"])
        self.assertEqual(tab.patterns, beisen.NewPortal.CAPTURE)
        self.assertTrue(all(4 <= delay <= 9 for delay in self.delays) and len(self.delays) == len(tab.calls) - 1)
        list_url = urlsplit(tab.calls[0])
        self.assertEqual(json.loads(parse_qs(list_url.query)["LocId"][0]), [{"id": "4401", "label": "广州市"}])
        self.assertNotIn("KeyWords", parse_qs(list_url.query))
        records = self.saved(summary)
        self.assertEqual(sorted(records), sorted(f"beisen.example.{x}.json" for x in (A, B, C)))
        a = records[f"beisen.example.{A}.json"]
        self.assertEqual((a["site"], a["site_job_id"], a["url"]), ("ats", f"beisen.example.{A}", detail_url(A)))
        self.assertEqual((a["extra"]["job_code"], a["extra"]["channel"], a["extra"]["tenant"]), ("J10001", "intern", "example"))
        for name, record in records.items():
            screen.read_item(json.dumps(record, ensure_ascii=False).encode("utf-8"), "ats")  # the inbox format holds
        parsed = {name: jd_parser.parse_text(r["text"], source_type="portal", site="ats", url=r["url"], single=True,
                                             site_job_id=r["site_job_id"], fetched_at=r["fetched_at"])[0][0]
                  for name, r in records.items()}
        a, b, c = (parsed[f"beisen.example.{x}.json"] for x in (A, B, C))
        self.assertEqual((a["title"], a["company"], a["cities"], a["employment_type"], a["published_at"]),
                         ("示例Agent开发实习生", "示例科技", ["广州", "武汉"], "internship", "2026-09-07"))
        self.assertEqual(a["salary"], {"min": None, "max": None, "unit": None, "months": None, "negotiable": True})
        self.assertIsNone(b["salary"])
        self.assertEqual((c["salary"]["min"], c["salary"]["max"], c["salary"]["unit"]), (15000, 18000, "CNY/month"))
        self.assertEqual(schema.validate(a), [])

    def test_keywords_run_one_search_each_and_dedup_between_them(self):
        both = list_response([item(A, "示例Agent开发实习生")], keyword="Agent")
        python = list_response([item(A, "示例Agent开发实习生")], keyword="Python")
        tab = Tab(lists={"/intern/jobs": [lambda url: new_list(url, both), lambda url: new_list(url, python)]},
                  details={detail_url(A): new_detail("示例Agent开发实习生")})
        summary = self.run_tenant(tab, keywords=["Agent", "Python"], channel="intern")
        self.assertEqual((summary["saved"], summary["cards_seen"], [s["label"] for s in summary["searches"]]),
                         (1, 1, ["实习生招聘·广州·Agent", "实习生招聘·广州·Python"]))
        self.assertEqual([parse_qs(urlsplit(url).query)["KeyWords"] for url in tab.calls[:2]], [["Agent"], ["Python"]])
        ignored = Tab(lists={"/intern/jobs": [lambda url: new_list(url, list_response([item(A, "示例")], keyword=""))]})
        summary = self.run_tenant(ignored, keywords=["Agent"], channel="intern")
        self.assertEqual((collect.exit_code(summary), summary["saved"]), (4, 0))
        self.assertIn("--all", summary["message"])

    def test_page_cap_counts_every_search(self):
        def answer(url):  # the page sends the keyword it was given in its address
            return new_list(url, list_response([item(A, "示例甲")], keyword=parse_qs(urlsplit(url).query)["KeyWords"][0]))
        lists = {"/intern/jobs": [answer] * 3}
        summary = self.run_tenant(Tab(lists=lists, details={detail_url(A): new_detail("示例甲")}),
                                  keywords=["一", "二", "三"], channel="intern", max_pages=2)
        self.assertEqual((summary["list_loads"], summary["finished"], summary["searches"][2]["finished"]),
                         (2, "max_pages", "not_run"))
        with self.assertRaises(collect.CollectError):
            collect.make_search_options(beisen.searches(TENANTS["example"]), max_pages=6)
        with self.assertRaises(collect.CollectError):
            collect.make_search_options(beisen.searches(TENANTS["example"]), max_jobs=31)

    def test_stops_on_403_api_error_login_and_two_empty_loads(self):
        intern = f"{NEW_HOST}/intern/jobs"
        denied = Tab(lists={"/intern/jobs": [lambda url: collect.Snapshot(url, "", "", 403)]})
        failed = Tab(lists={"/intern/jobs": [lambda url: new_list(url, list_response([], code=500))]})
        for tab, code, words in ((denied, 3, "HTTP 403"), (failed, 3, "接口报错")):
            summary = self.run_tenant(tab, channel="intern")
            self.assertEqual((collect.exit_code(summary), summary["saved"], len(tab.calls)), (code, 0, 1))
            self.assertIn(words, summary["message"])
        two = list_response([item(A, "示例甲"), item(B, "示例乙")], total=5)
        empty = Tab(lists={"/intern/jobs": [lambda url: new_list(url, two, total=5)]},
                    scrolls=[new_list(intern, two, total=5), new_list(intern, two, total=5)])
        summary = self.run_tenant(empty, channel="intern")
        self.assertEqual((collect.exit_code(summary), summary["saved"], empty.calls.count("scroll")), (4, 0, 2))
        self.assertIn("连续 2 次加载都没有新岗位", summary["message"])
        login = collect.Snapshot(f"{NEW_HOST}/login?returnUrl=%2Fintern%2Fdetail", "登录", "<form></form>", 200)
        both = list_response([item(A, "示例甲"), item(B, "示例乙")])
        tab = Tab(lists={"/intern/jobs": [lambda url: new_list(url, both)]},
                  details={detail_url(A): new_detail("示例甲"), detail_url(B): login})
        summary = self.run_tenant(tab, channel="intern")
        self.assertEqual((collect.exit_code(summary), summary["saved"]), (3, 1))
        self.assertIn("要求登录", summary["message"])

    def test_rerun_skips_jobs_known_by_site_job_id(self):
        tab = Tab(lists={"/intern/jobs": [lambda url: new_list(url, list_response([item(A, "示例甲")]))]},
                  details={detail_url(A): new_detail("示例甲")})
        self.assertEqual(self.run_tenant(tab, channel="intern")["saved"], 1)
        again = Tab(lists={"/intern/jobs": [lambda url: new_list(url, list_response([item(A, "示例甲"), item(B, "示例乙")]))]},
                    details={detail_url(B): new_detail("示例乙")})
        # B is in the job store with its id only, no URL: the id alone finds it.
        text = "示例乙\n工作职责\n参与示例开发。"
        record = jd_parser.parse_text(text, source_type="portal", site="ats", single=True,
                                      site_job_id=f"beisen.example.{B}", fetched_at=NOW.isoformat())[0][0]
        store.Store(self.root).save(record)
        summary = self.run_tenant(again, channel="intern")
        self.assertEqual((summary["saved"], summary["skipped_known"], again.calls[1:]), (0, 2, []))

    def test_recognised_empty_loads_with_remaining_total_stop_after_two(self):
        empty = list_response([], total=3)
        new = Tab(lists={"/intern/jobs": [lambda url: new_list(url, empty, total=3)]},
                  scrolls=[new_list(f"{NEW_HOST}/intern/jobs", empty, empty, total=3)])
        old = Tab(lists={"/search": [legacy_list([], 1, 3, 3), legacy_list([], 2, 3, 3)]})
        for tenant, channel, tab in (("example", "intern", new), ("example-legacy", "campus", old)):
            with self.subTest(tenant=tenant):
                summary = self.run_tenant(tab, tenant=tenant, channel=channel)
                self.assertEqual((collect.exit_code(summary), summary["list_loads"], summary["saved"]), (4, 2, 0))
                self.assertIn("连续 2 次加载", summary["message"])

    def test_overlapping_keyword_pages_still_reach_unseen_jobs(self):
        fourth = A[:-1] + "d"
        ids = [A, B, C, fourth]
        names = ["示例甲", "示例乙", "示例丙", "示例丁"]
        rows = [item(job, name) for job, name in zip(ids, names)]
        first = list_response(rows[:3], keyword="first")
        pages = [list_response([row], total=4, keyword="second") for row in rows]
        url = f"{NEW_HOST}/intern/jobs?KeyWords=second"
        tab = Tab(lists={"/intern/jobs": [lambda url: new_list(url, first),
                                          lambda url: new_list(url, pages[0], total=4)]},
                  scrolls=[new_list(url, *pages[:count], total=4) for count in (2, 3, 4)],
                  details={detail_url(job): new_detail(name) for job, name in zip(ids, names)})
        summary = self.run_tenant(tab, keywords=["first", "second"], channel="intern")
        self.assertEqual((summary["saved"], summary["list_loads"], summary["finished"]), (4, 5, "end_of_list"))

    def test_unreadable_responses_and_missing_keyword_evidence_stop(self):
        good = list_response([item(A, "示例甲")], total=2, keyword="Agent")
        for body, request, status, expected in (
                ("<html>示例错误</html>", good.request, 200, 4),
                ('{"Data":{"Unknown":true}}', good.request, 200, 4),
                (good.body, None, 200, 4),
                (good.body, "{}", 200, 4),
                (good.body, good.request, 429, 3),
                (good.body, good.request, 500, 3)):
            bad = collect.Response(good.url, status, request, body)
            with self.subTest(body=body, request=request, status=status):
                tab = Tab(lists={"/intern/jobs": [lambda url: new_list(url, good, bad, total=2)]})
                summary = self.run_tenant(tab, keywords=["Agent"], channel="intern")
                self.assertEqual((collect.exit_code(summary), summary["saved"], len(tab.calls)), (expected, 0, 1))

    def test_429_captcha_and_detail_api_errors_stop_the_tenant(self):
        for tenant, channel, path in (("example", "intern", "/intern/jobs"),
                                      ("example-legacy", "campus", "/search")):
            for status, html in ((429, ""), (200, '<div id="captcha">验证</div>')):
                with self.subTest(tenant=tenant, status=status):
                    tab = Tab(lists={path: [lambda url: collect.Snapshot(url, "", html, status)]})
                    summary = self.run_tenant(tab, tenant=tenant, channel=channel)
                    self.assertEqual((collect.exit_code(summary), summary["saved"], len(tab.calls)), (3, 0, 1))
        failure = collect.Response(f"{NEW_HOST}/api/JobAd/GetJobAdInfo", 200,
                                   body='{"Success":false,"Message":"示例错误"}')
        tab = Tab(lists={"/intern/jobs": [lambda url: new_list(url, list_response([item(A, "示例甲")]))]},
                  details={detail_url(A): collect.Snapshot(detail_url(A), "", new_detail("示例甲"),
                                                          200, (failure,))})
        summary = self.run_tenant(tab, channel="intern")
        self.assertEqual((collect.exit_code(summary), summary["saved"]), (3, 0))
        self.assertIn("接口报错", summary["message"])

    def test_default_detail_budget_never_opens_more_than_thirty(self):
        ids = [f"0f8e2c3a-1111-4abc-8def-{index:012x}" for index in range(35)]
        rows = [item(job, f"示例岗位{index}") for index, job in enumerate(ids)]
        tab = Tab(lists={"/intern/jobs": [lambda url: new_list(url, list_response(rows))]},
                  details={detail_url(job): new_detail(f"示例岗位{index}") for index, job in enumerate(ids[:30])})
        summary = self.run_tenant(tab)
        self.assertEqual((summary["saved"], summary["finished"], len(tab.calls)), (30, "max_jobs", 31))
        self.assertEqual(summary["searches"][1]["finished"], "not_run")

    def test_configured_cities_each_get_their_own_search(self):
        config = {**CONFIG, "tenants": [{**CONFIG["tenants"][0], "channels": ["intern"],
                                        "cities": ["广州", "武汉"]}]}
        tenant = beisen.parse_tenants(config, TODAY)[0]["example"]
        tab = Tab(lists={"/intern/jobs": [lambda url: new_list(url, list_response([]))] * 2})
        summary = collect.run(tab, collect.make_search_options(beisen.searches(tenant)), self.root,
                              sleep=self.delays.append, clock=lambda: NOW)
        self.assertEqual(summary["list_loads"], 2)
        self.assertEqual([json.loads(parse_qs(urlsplit(url).query)["LocId"][0])[0]["id"] for url in tab.calls],
                         ["4401", "4201"])

    def test_legacy_portal_pages_rows_and_sections(self):
        first = legacy_list([("151000002", "示例Java开发（校招,广州）"), ("151000001", "示例前端开发（校招，广州）")], 1, 2, 3)
        last = legacy_list([("151000000", "示例测试（校招，广州）")], 2, 2, 3)
        details = {f"{OLD_HOST}/zpdetail/{job}": legacy_detail(title) for job, title in (
            ("151000002", "示例Java开发（校招,广州）"), ("151000001", "示例前端开发（校招，广州）"),
            ("151000000", "示例测试（校招，广州）"))}
        tab = Tab(lists={"/search": [first, last]}, details=details)
        summary = self.run_tenant(tab, tenant="example-legacy")
        self.assertEqual((summary["status"], summary["saved"], summary["list_loads"], summary["finished"]),
                         ("done", 3, 2, "end_of_list"))
        self.assertEqual([parse_qs(urlsplit(url).query) for url in tab.calls[:2]],
                         [{"r": ["2"], "c": ["4401"]}, {"r": ["2"], "c": ["4401"], "PageIndex": ["2"]}])
        record = self.saved(summary)["beisen.example-legacy.151000002.json"]
        parsed = jd_parser.parse_text(record["text"], source_type="portal", site="ats", single=True)[0][0]
        self.assertEqual((parsed["title"], parsed["cities"], parsed["employment_type"], parsed["published_at"],
                          parsed["salary"], record["url"]),
                         ("示例Java开发（校招,广州）", ["广州"], "campus", "2026-09-14", None, f"{OLD_HOST}/zpdetail/151000002"))
        self.assertIn("本科及以上学历", record["text"])
        empty = Tab(lists={"/search": [legacy_list([], 1, 1, 0)]})
        self.assertEqual(self.run_tenant(empty, tenant="example-legacy")["finished"], "no_results")


class Rules(unittest.TestCase):
    def test_same_native_id_on_different_tenants_is_not_known(self):
        with tempfile.TemporaryDirectory() as directory:
            text = "示例平台开发\n公司名称：示例甲公司\n工作职责\n维护示例系统。"
            record = jd_parser.parse_text(text, source_type="portal", site="ats", single=True,
                                          site_job_id="beisen.other.151000002")[0][0]
            store.Store(directory).save(record)
            rules = beisen.tenant_rules(TENANTS["example-legacy"], "campus")
            known, warnings = collect.known_job_ids(Path(directory), rules)
            self.assertEqual(warnings, [])
            self.assertNotIn(rules.job_id_from_url(f"{OLD_HOST}/zpdetail/151000002"), known)

    def test_ids_addresses_and_titles(self):
        rules = beisen.tenant_rules(TENANTS["example"], "intern")
        self.assertEqual(beisen.split_job_code("示例开发（J12345）"), ("示例开发", "J12345"))
        self.assertEqual(beisen.split_job_code("示例开发(C++)"), ("示例开发(C++)", None))
        self.assertEqual(rules.job_id_from_url(detail_url(A.upper(), "campus")), f"beisen.example.{A}")
        for url in (detail_url(A).replace("example.", "other."), detail_url(A).replace("https", "http"),
                    detail_url(A).replace("/detail", "/jobs"), detail_url("not-a-uuid"),
                    detail_url(A).replace(".com/", ".com:8443/"), None):
            with self.subTest(url=url):
                self.assertIsNone(rules.job_id_from_url(url))
        self.assertEqual(rules.known_job_id_from_url(detail_url(A).replace("https", "http")), f"beisen.example.{A}")
        legacy = beisen.tenant_rules(TENANTS["example-legacy"], "campus")
        self.assertEqual(legacy.job_id_from_url(f"{OLD_HOST}/zpdetail/151000002?c=4401"), "beisen.example-legacy.151000002")
        self.assertIsNone(legacy.job_id_from_url(f"{NEW_HOST}/zpdetail/151000002"))
        self.assertEqual(legacy.page_problem(f"{OLD_HOST}/Portal/Account/Login?returnUrl=%2F", "", beisen.htmltext.parse(""))[0],
                         "login")
        page = beisen.htmltext.parse('<div class="geetest_panel">验证</div>')
        self.assertEqual(rules.page_problem(f"{NEW_HOST}/intern/jobs", "", page, 200, responses=())[0], "blocked")

    def test_site_job_ids_are_scoped_by_platform_and_tenant(self):
        for site, value, allowed in (("ats", "beisen.example.151000002", True), ("ats", f"beisen.example.{A}", True),
                                     ("ats", "151000002", False), ("ats", "beisen..1", False),
                                     ("official", "beisen.example.1", False), ("boss", "a1B2", True)):
            with self.subTest(site=site, value=value):
                self.assertEqual(schema.site_job_id_allowed(site, value), allowed)
        errors = []
        schema._check_source({"type": "portal", "site": "ats", "url": None, "imported_at": NOW.isoformat(),
                              "site_job_id": "151000002", "fetched_at": None}, errors)
        self.assertIn("<platform>.<tenant>.<id>", errors[0])


class Whitelist(unittest.TestCase):
    def test_config_problems_are_named(self):
        def problems(**changes):
            entry = {**CONFIG["tenants"][0], **changes}
            return beisen.parse_tenants({"format": beisen.CONFIG_FORMAT, "tenants": [entry]}, TODAY)[1]
        self.assertEqual(problems(), [])
        for changes, words in (({"subdomain": "Example.com"}, "subdomain"), ({"portal": "v2"}, "portal"),
                               ({"channels": ["jobs"]}, "channels"), ({"channels": [{}]}, "channels"),
                               ({"channels": [[]]}, "channels"), ({"cities": ["火星"]}, "city_codes"),
                               ({"terms_checked": "2026-12-01"}, "terms_checked"), ({"terms_url": "privacy"}, "terms_url"),
                               ({"company": ""}, "company"), ({"extra": 1}, "不认识")):
            with self.subTest(changes=changes):
                self.assertTrue(any(words in problem for problem in problems(**changes)), problems(**changes))
        added = {"format": beisen.CONFIG_FORMAT, "city_codes": {"韶关": "4402"},
                 "tenants": [{**CONFIG["tenants"][0], "cities": ["韶关"]}]}
        self.assertEqual(beisen.parse_tenants(added, TODAY)[0]["example"].cities, (("韶关", "4402", "韶关市"),))

    def test_documented_example_is_a_valid_whitelist_of_fictional_tenants(self):
        doc = (REPO / "docs" / "cn" / "collect.md").read_text(encoding="utf-8")
        block = next(b for b in re.findall(r"```json\n(.*?)```", doc, re.S) if beisen.CONFIG_FORMAT in b)
        tenants, errors = beisen.parse_tenants(json.loads(block), TODAY)
        self.assertEqual(errors, [])
        self.assertTrue(all(name.startswith("example") for name in tenants))

    def test_cli_refuses_unlisted_tenant_and_missing_whitelist_before_the_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            for write in (False, True):
                if write:
                    (Path(directory) / "collect").mkdir()
                    (Path(directory) / "collect" / "beisen.json").write_text(json.dumps(CONFIG), encoding="utf-8")
                with self.subTest(write=write), mock.patch.object(cli.browser, "open_tab") as opened, \
                        redirect_stderr(io.StringIO()) as err:
                    code = cli.main(["collect", "beisen", "--tenant", "unlisted", "--data-dir", directory])
                self.assertEqual(code, 2)
                self.assertIn("白名单", json.loads(err.getvalue())["error"])
                opened.assert_not_called()

    def test_cli_reads_profile_keywords_or_all(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "collect").mkdir()
            (root / "collect" / "beisen.json").write_text(json.dumps(CONFIG), encoding="utf-8")
            (root / "profile").mkdir()
            (root / "profile" / "profile.json").write_text(json.dumps({"target": {"search_keywords": ["Agent", "agent"]}}),
                                                           encoding="utf-8")
            for extra, keyword in (([], ["Agent"]), (["--all"], None), (["--query", "Python"], ["Python"])):
                tab = Tab(lists={"/intern/jobs": [lambda url: new_list(url, list_response([], keyword=(keyword or [""])[0]))]})
                with self.subTest(extra=extra), mock.patch.object(cli.browser, "open_tab", return_value=tab), \
                        mock.patch.object(collect._Pacer, "before_action"), redirect_stdout(io.StringIO()) as out:
                    code = cli.main(["collect", "beisen", "--tenant", "example", "--channel", "intern",
                                     "--data-dir", directory, *extra])
                summary = json.loads(out.getvalue())
                self.assertEqual((code, summary["finished"], summary["tenant"]["company"]), (0, "no_results", "示例科技"))
                self.assertEqual(parse_qs(urlsplit(tab.calls[0]).query).get("KeyWords"), keyword)


class Capture(unittest.TestCase):
    def test_tab_keeps_only_matching_same_origin_data_responses_of_the_current_page(self):
        def response(url, kind="fetch", body='{"Code":200}'):
            return SimpleNamespace(url=url, status=200, text=lambda: body,
                                   request=SimpleNamespace(resource_type=kind, post_data='{"PageIndex":1}'))

        class Page:
            url = f"{NEW_HOST}/intern/jobs"
            pending = [response(f"{NEW_HOST}/api/Jobad/GetJobAdPageList"),
                       response(f"{NEW_HOST}/api/Common/GetPortalAIRobot"),
                       response("https://tracker.example.net/api/Jobad/GetJobAdPageList"),
                       response("https://other.zhiye.com/api/Jobad/GetJobAdPageList"),
                       response(f"{NEW_HOST}:8443/api/Jobad/GetJobAdPageList"),
                       response(f"{NEW_HOST}/api/Jobad/GetJobAdPageList".replace("https:", "http:")),
                       response(f"{NEW_HOST}/api/Jobad/GetJobAdPageList", kind="image")]

            def on(self, event, listener):
                self.listener = listener

            def goto(self, url, wait_until, timeout):
                self.url = url
                for each in self.pending:
                    self.listener(each)
                self.pending = []
                return SimpleNamespace(status=200)

            def wait_for_selector(self, selector, state, timeout):
                pass

            def title(self):
                return "实习生招聘"

            def content(self):
                return "<div></div>"

        with mock.patch.object(browser, "SETTLE_S", 0):
            tab = browser.Tab(SimpleNamespace(stop=lambda: None), Page(), Exception)
            self.assertEqual(tab.open(f"{NEW_HOST}/intern/jobs", ["div"]).responses, ())  # nothing asked for
            tab._page.pending = Page.pending
            tab.capture(beisen.NewPortal.CAPTURE)
            kept = tab.open(f"{NEW_HOST}/intern/jobs", ["div"]).responses
            self.assertEqual([(r.url, r.body, r.request) for r in kept],
                             [(f"{NEW_HOST}/api/Jobad/GetJobAdPageList", '{"Code":200}', '{"PageIndex":1}')])
            self.assertEqual(tab.open(f"{NEW_HOST}/intern/jobs", ["div"]).responses, ())  # a new page starts empty


if __name__ == "__main__":
    unittest.main()
