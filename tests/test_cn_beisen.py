"""Beisen portal rules and runs on fictional tenants (example.zhiye.com, 示例科技); offline.

Every list response, page and job text here is hand-written; none is copied from a real portal.
Their structure - the list response's keys, the cards, the empty result pages and both detail
pages - follows what was recorded on real portals on 2026-11-10
(docs/cn/worklog/2026-11-10-m6-3-beisen-live.md); every name, job and text is made up.
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
from tests.test_cn_collect import FakeError

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


def item(uuid, name, salary="面议", places=("广东省·广州市",), kind="实习"):
    """One job ad of the list response: Id is the UUID its detail page takes, JobAdId an internal number."""
    return {"Id": uuid, "HeadCount": 0, "JobAdId": 151000000 + int(uuid[-3:], 16), "PostDateInt": 1788746400000,
            "PostDate": "2026-09-07T10:00:00", "EndTimeInt": 0, "EndTime": "0001-01-01T00:00:00", "JobAdName": name,
            "OrgId": 3000001, "Org": None, "Category": "实习生招聘", "CategoryId": "3", "LocId": None,
            "LocNames": list(places), "Salary": salary or None, "Duty": "1. 参与示例平台开发。",
            "Require": "1. 熟悉 Python。", "Kind": kind, "Status": 1, "IsCollect": False, "IsDelivered": False}


def list_response(items, total=None, code=200, keyword="", page=0):
    """The page's own list request and its response: Count is the whole result's total, Total stays 0."""
    body = {"Code": code, "Message": "operation success" if code == 200 else "示例错误", "MoreMessage": "",
            "TipType": "Success" if code == 200 else "Error", "Count": len(items) if total is None else total,
            "ReturnUrl": None, "Data": items, "Total": 0}
    sent = {"PageIndex": page, "PageSize": 20, "LocId": ["4401"], "Category": ["3"], "KeyWords": keyword,
            "SpecialType": 0, "PortalId": "", "DisplayFields": ["Category", "Kind", "LocId", "PostDate"]}
    return collect.Response(url=f"{NEW_HOST}/api/Jobad/GetJobAdPageList", status=200,
                            request=json.dumps(sent, ensure_ascii=False), body=json.dumps(body, ensure_ascii=False))


def detail_response(uuid, name):
    """The detail page's own GET /api/JobAd/GetJobAdInfo: the job ad under Data."""
    body = {"Code": 200, "Message": "operation success", "MoreMessage": None, "TipType": None, "Count": 0,
            "ReturnUrl": None, "Data": item(uuid, name), "Total": 0}
    return collect.Response(url=f"{NEW_HOST}/api/JobAd/GetJobAdInfo?jobAdId={uuid}&category=3", status=200,
                            body=json.dumps(body, ensure_ascii=False))


def card(entry):
    """One card of the list page, as rendered: no link and no id anywhere in it."""
    salary = f'<div class="style__STJobSalary-editor__sc-x1-5 e">{entry["Salary"]}</div>' if entry.get("Salary") else ""
    labels = "".join(f'<div class="style__STJobLabel-editor__sc-x1-12 g"><div class="style__STLabelText-editor__sc-x1-13 h">'
                     f'{text}</div></div>' for text in (entry.get("Category"), entry.get("Kind"),
                                                       ",".join(entry.get("LocNames") or [])) if text)
    return ('<div class="style__STListItem-editor__sc-x1-0 a"><div class="style__STListItemContent-editor__sc-x1-1 b">'
            '<div class="style__STTitleSection-editor__sc-x1-2 c"><div class="style__STJobTitle-editor__sc-x1-4 d">'
            f'<span>{entry["JobAdName"]}</span></div>{salary}</div><div class="style__STOtherSection-editor__sc-x1-10 f">'
            f'<div class="style__STLabelSection-editor__sc-x1-11 g">{labels}</div>'
            f'<div class="style__STJobTime-editor__sc-x1-16 i">{(entry.get("PostDate") or "")[:10]} 发布</div></div></div>'
            '<div class="style__STDetailPanel-editor__sc-x1-17 j"><div class="style__STDetailTitle-editor__sc-x1-18 k">'
            f'工作职责</div><div class="style__STDetailDesc-editor__sc-x1-19 l">{entry.get("Duty") or ""}</div>'
            '<div class="style__STDetailFooter-editor__sc-x1-22 m"><div class="phoenix-button__content">立即投递</div>'
            '<div class="style__STDetailBtn-editor__sc-x1-29 n"><div>查看详情</div></div></div></div></div>')


EMPTY_BOX = ('<div class="style__STEmpty-editor__sc-x2-2 c"><div class="style__STEmptyIcon-editor__sc-x2-3 d">'
             '<svg width="200px" height="200px"><g id="搜索/筛选结果为空"></g></svg></div>'
             '<span>暂时没有符合条件的职位~</span></div>')


def new_list(url, *responses, total=None, cards=None):
    """The list page as rendered: "共 N 个", a card per job ad in the page's own responses (or the
    given cards) above a footer that says 没有更多了~ even when more would come by scrolling;
    with no card, an empty footer and the empty box."""
    entries, count = [], 0
    for response in responses:
        payload = beisen._json(response.body)
        if isinstance(payload, dict) and isinstance(payload.get("Data"), list):
            entries += [e for e in payload["Data"] if isinstance(e, dict) and isinstance(e.get("JobAdName"), str)]
            count = payload.get("Count", count)
    shown = "".join(card(entry) for entry in entries) if cards is None else cards
    footer = '<div id="LIST_LAST_DOM" class="style__STListFooter-editor__sc-x2-1 b">{}</div>'
    body = shown + footer.format("<div>没有更多了~</div>") if shown else footer.format("") + EMPTY_BOX
    html = (f'<div class="style__STBreadJobInfo-editor__sc-x3-1 a"><div>全部职位（共 {count if total is None else total} 个）'
            f'</div></div><div class="style__STJobList-editor__sc-x2-0 a">{body}</div>')
    return collect.Snapshot(url=url, title="实习生招聘", html=html, status=200, responses=tuple(responses))


def tag(text):
    return (f'<span class="style__STJobTag-editor__sc-y1-24 a"><span class="style__STJobTabInner-editor__sc-y1-25 b">'
            f'{text}</span></span><div class="style__STJobLabelSperator-editor__sc-y1-26 c"></div>')


def new_detail(title, salary="面议", places=("广东省·广州市",), channel_label="实习生招聘"):
    """A job's page as rendered: name and salary, tags, the date, and a container per section."""
    salary_html = f'<div class="style__STJobNameRight-editor__sc-y1-20 b">{salary}</div>' if salary else ""
    sections = "".join(
        f'<div class="style__STDutyContainer-editor__sc-y1-28 g"><div class="style__STDutyTitle-editor__sc-y1-29 h">{head}</div>'
        f'<div class="style__STDutyContent-editor__sc-y1-31 i"><div class="style__STDutyItem-editor__sc-y1-32 j">{body}</div></div></div>'
        for head, body in (("工作职责", "1. 参与示例 Agent 平台开发。<br>2. 编写 Python 服务。"),
                           ("任职资格", "熟悉 Python，每周到岗4天，实习3个月。")))
    return ('<div class="sc-head">登录/注册</div><div class="style__STJobList-editor__sc-y1-0 pc-job-detail">'
            '<div class="style__STComponentItemContainer-editor__sc-y1-10 style__STJobName-editor__sc-y1-18 a">'
            f'<div class="style__STJobNameLeft-editor__sc-y1-19 a"><span>{title}</span></div>{salary_html}</div>'
            '<div class="style__STJobInfo-editor__sc-y1-21 d"><span class="style__STJobInfoLeft-editor__sc-y1-22 e">'
            f'{tag(channel_label)}{tag("实习")}{"".join(tag(place) for place in places)}</span>'
            '<div class="style__STJobInfoRight-editor__sc-y1-23 f">2026-09-07 发布</div></div>'
            f'<div class="style__STJobDuty-editor__sc-y1-27 g">{sections}<div class="style__STButtonGroup-editor__sc-y1-33 k">'
            '<div class="phoenix-button__content">立即投递</div></div></div></div>')


def legacy_list(rows, page, pages, total, link="/zpdetail/{job}?r=2&c=4401"):
    """The server-rendered list: a table row per job, 共N条记录, a pager only when there are more
    pages; with no job and a count of 0, the table's no-results box."""
    body = "".join(
        f'<tr><td class="tableleft joblsttitle"><a title="{title}" jobadid="{job}" href="{link.format(job=job)}">{title}</a>'
        '</td><td class="tableleft joblsttitle" title=""></td><td title="广东省-广州市" class="tableleft joblsttitle">'
        '广东省-广州市</td><td class="tableleft joblsttitle">2026-09-14</td></tr>' for job, title in rows)
    if not rows and not total:
        body = ('<tr><td colspan="10"><div class="zx_nojob"><div class="imgNoResult"></div>'
                '<div class="txtNoResut">没有搜索到相关应聘职位。</div></div></td></tr>')
    pager = ""
    if pages > 1:
        after = (f'<a href="/search/?r=2&amp;c=4401&amp;PageIndex={page + 1}" class="next">下一页</a>' if page < pages
                 else '<a disabled="disabled" class="disabled next">下一页</a>')
        pager = (f'<div class="tablefooter"><span>当前第{page}/{pages}页</span><div class="pager clearfix">'
                 f'<span><a disabled="disabled" class="disabled next">首页</a></span><span>{after}</span></div></div>')
    return ('<a class="loginlink" href="/Portal/Account/Login?returnUrl=%2Fsearch">登录</a>'
            '<div class="clearfix tablecontain"><table class="listtable"><thead><tr class="tabletitle">'
            '<th class="tableleft">职位名称</th><th class="tableleft" title="职位类型">职位类型</th>'
            '<th class="tableleft">工作地点</th><th class="tableleft">发布时间</th></tr></thead>'
            f'<tbody>{body}</tbody></table><span class="tablenote">共{total}条记录</span></div>{pager}')


def legacy_detail(title, salary="8000-12000 元/月"):
    """A job's page: the site's search form (with a 工作地点： of its own) beside the job's block,
    whose title carries the apply status and whose labels and values are separate elements."""
    return ('<div class="searchbox"><table><tr><td class="listtitle">工作地点：</td><td><a href="/search?c=-1">全部</a>'
            '<a href="/search?c=1100">北京市</a></td></tr></table></div>'
            '<div class="positiondetail-simple "><div class="xiangqingtitle">'
            f'<span>{title}<b class="applyStatus" style="font-weight: normal;">(未申请)</b></span></div>'
            '<div class="xiangqingcontain"><div class="xiangqingline"></div><ul class="xiangqinglist clearfix">'
            '<li class="ntitle td-HasRecruitCategories">招聘类别：</li><li class="nvalue">校园招聘</li>'
            '<li class="ntitle td-HasKind">工作性质：</li><li class="nvalue">全职</li>'
            f'<li class="ntitle td-HasSalaries">薪资范围：</li><li class="nvalue">{salary}</li>'
            '<li class="ntitle td-HasHeadCount">招聘人数：</li><li class="nvalue">2</li></ul>'
            '<ul class="xiangqinglist clearfix"><li class="ntitle td-HasPostDate">发布时间：</li>'
            '<li class="nvalue">2026-09-14</li><li class="ntitle td-HasEndTime">截止时间：</li><li class="nvalue"></li><br>'
            '<div class="xiangqingtext"><p>工作地点：</p><p>广东省-广州市</p><br><p>工作职责：</p>'
            '<p>1.负责示例系统开发。<br>2.参与示例接口联调。</p><br><p>任职资格：</p><p>本科及以上学历，熟悉 Java。</p></div>'
            '<div class="xiangqingfooter clearfix"><div class="footerbtn fl"><a href="#this" id="apply">现在申请</a></div>'
            '<a href="javascript:ReturnToJobList()" class="returnlist">返回职位列表</a></div></ul></div></div>'
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


class DeferredErrorPage:
    """Reviewer's fictional Page: deliver a failure only after the first good snapshot.

    title() dispatches queued responses as Playwright does after the pacing pause. No browser
    or network is used; collect still runs through the real browser.Tab wrapper.
    """

    def __init__(self, failure, next_action):
        self.failure, self.next_action = failure, next_action
        self.url, self.html = "about:blank", ""
        self.pending, self.gotos, self.scrolls = [], [], []
        self.deferred = False
        self.mouse = SimpleNamespace(wheel=lambda *args: self.scrolls.append(args))

    def on(self, event, listener):
        self.listener = listener

    def title(self):
        pending, self.pending = self.pending, []
        for response in pending:
            self.listener(response)
        return "示例门户"

    def content(self):
        return self.html

    def emit(self, response, defer=False):
        def read():
            if defer and not self.deferred:
                self.deferred = True
                self.queue_failure()
            return response.body

        self.listener(SimpleNamespace(url=response.url, status=response.status, text=read,
                                     request=SimpleNamespace(resource_type="fetch", post_data=response.request)))

    def queue_failure(self):
        response = self.failure
        self.pending.append(SimpleNamespace(url=response.url, status=response.status, text=lambda: response.body,
                                            request=SimpleNamespace(resource_type="fetch", post_data=response.request)))

    def goto(self, url, **kwargs):
        self.gotos.append(url)
        self.url = url
        if urlsplit(url).path.endswith("/jobs"):
            rows = [item(A, "示例开发实习生")]
            if self.next_action == "next_detail":
                rows.append(item(B, "示例测试实习生"))
            good = list_response(rows, total=2 if self.next_action == "scroll" else len(rows))
            self.html = new_list(url, good).html
            self.emit(good, defer=self.next_action != "next_detail")
        else:
            self.html = new_detail("示例开发实习生" if url == detail_url(A) else "示例测试实习生")
            good = detail_response(A if url == detail_url(A) else B, "示例开发实习生")
            self.emit(good, defer=self.next_action == "next_detail")
        return SimpleNamespace(status=200)

    def wait_for_selector(self, *args, **kwargs):
        pass

    def locator(self, selector):
        # The old driver can get this far; the regression asserts that no scroll was made.
        return SimpleNamespace(count=lambda: 1, nth=lambda _: SimpleNamespace(
            scroll_into_view_if_needed=lambda **kwargs: None))


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

    def test_non_2xx_main_documents_stop_before_parsing_or_saving(self):
        # PR #149 P2-2: recognisable list/detail content must never override HTTP failure.
        for tenant, channel, path, portal in (("example", "intern", "/intern/jobs", beisen.NewPortal),
                                              ("example-legacy", "campus", "/search", beisen.LegacyPortal)):
            rules = beisen.tenant_rules(TENANTS[tenant], channel)
            url = detail_url(A) if tenant == "example" else rules.canonical_url("beisen.example-legacy.151000001")
            for phase in ("list", "detail"):
                for status in (199, 300, 302, 400, 404, 500, 503):
                    with self.subTest(portal=tenant, phase=phase, status=status), tempfile.TemporaryDirectory() as root:
                        def listing(address):
                            if tenant == "example":
                                snapshot = new_list(address, list_response([item(A, "示例开发实习生")]))
                            else:
                                snapshot = collect.Snapshot(address, "职位列表", legacy_list(
                                    [("151000001", "示例开发实习生")], 1, 1, 1), 200)
                            snapshot.status = status if phase == "list" else 200
                            return snapshot

                        html = (new_detail if tenant == "example" else legacy_detail)("示例开发实习生")
                        tab = Tab(lists={path: [listing]}, details={url: collect.Snapshot(url, "职位详情", html, status)})
                        options = collect.make_search_options(beisen.searches(TENANTS[tenant], channel=channel))
                        method = "parse_cards" if phase == "list" else "parse_detail"
                        with mock.patch.object(portal, method, autospec=True, side_effect=getattr(portal, method)) as parse:
                            summary = collect.run(tab, options, root, sleep=lambda _: None, clock=lambda: NOW)
                        self.assertEqual((summary["status"], summary["saved"], len(tab.calls)),
                                         ("needs_user", 0, 1 if phase == "list" else 2))
                        self.assertIn(f"HTTP {status}", summary["message"])
                        parse.assert_not_called()
                        self.assertFalse((Path(root) / "inbox").exists())

    def check_deferred_errors(self, next_action):
        for delivery in ("next_read", "pause"):
            failures = [
                    (403, "{}", "needs_user", "HTTP 403"),
                    (429, "{}", "needs_user", "HTTP 429"),
                    (500, "{}", "needs_user", "HTTP 500"),
                    (503, "{}", "needs_user", "HTTP 503"),
                    (200, '{"Success":false,"Message":"示例错误"}', "needs_user", "接口报错"),
                    (200, "<html>示例错误</html>", "page_changed", "JSON"),
                    (200, None, "page_changed", "JSON"),
                    (200, "[]", "page_changed", "JSON")]
            if next_action != "next_detail":
                failures += [(200, '{"Data":{"Unknown":true}}', "page_changed", "列表接口响应里没有岗位列表"),
                             (200, '{"Code":200,"Data":[],"Total":0}', "page_changed", "列表接口响应里没有岗位列表")]
            for status, body, result, reason in failures:
                with self.subTest(next_action=next_action, delivery=delivery, status=status, body=body), \
                        tempfile.TemporaryDirectory() as root, mock.patch.object(browser, "SETTLE_S", 0), \
                        mock.patch.object(browser, "MORE_TIMEOUT_S", 0):
                    path = "GetJobAdInfo" if next_action == "next_detail" else "GetJobAdPageList"
                    failure = collect.Response(f"{NEW_HOST}/api/Jobad/{path}", status, body=body)
                    page = DeferredErrorPage(failure, next_action)
                    tab = browser.Tab(SimpleNamespace(stop=lambda: None), page, FakeError, headless=True)
                    options = collect.make_search_options(beisen.searches(
                        TENANTS["example"], channel=None if next_action == "channel" else "intern"))
                    summary = collect.run(tab, options, root, clock=lambda: NOW,
                                          sleep=lambda _: page.title() if delivery == "pause" else None)
                    saved = 1 if next_action == "next_detail" else 0
                    self.assertEqual((summary["status"], summary["saved"], len(page.gotos), page.scrolls),
                                     (result, saved, saved + 1, []))
                    self.assertIn(reason, summary["message"])
                    self.assertEqual(len(list(Path(root).glob("inbox/ats/*/*.json"))), saved)

    def test_deferred_api_errors_stop_before_detail_navigation(self):
        self.check_deferred_errors("detail")

    def test_deferred_api_errors_stop_before_channel_navigation(self):
        self.check_deferred_errors("channel")

    def test_deferred_api_errors_stop_before_scroll(self):
        self.check_deferred_errors("scroll")

    def test_deferred_detail_api_errors_preserve_saved_job_and_stop(self):
        self.check_deferred_errors("next_detail")

    def test_deferred_valid_response_allows_navigation_and_save(self):
        good = list_response([item(A, "示例开发实习生")])
        page = DeferredErrorPage(good, "detail")
        tab = browser.Tab(SimpleNamespace(stop=lambda: None), page, FakeError, headless=True)
        with mock.patch.object(browser, "SETTLE_S", 0):
            summary = self.run_tenant(tab, channel="intern")
        self.assertEqual((summary["status"], summary["saved"], len(page.gotos)), ("done", 1, 2))

    def test_two_channels_negotiable_missing_salary_multi_city_and_last_page(self):
        first = list_response([item(A, "示例Agent开发实习生(J10001)", places=("广东省·广州市", "湖北省·武汉市")),
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
        # The page's footer says 没有更多了~ and every response's Total is 0: Count alone asked for the scroll.
        self.assertEqual((tab.calls.count("scroll"), json.loads(first.body)["Total"]), (1, 0))
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

    def test_a_list_whose_total_says_jobs_but_shows_none_is_a_changed_page(self):
        # Neither portal's explicit "no results": stop at the first load, never call it the end of the list.
        new = Tab(lists={"/intern/jobs": [lambda url: new_list(url, list_response([], total=3), total=3)]})
        old = Tab(lists={"/search": [legacy_list([], 1, 3, 3)]})
        for tenant, channel, tab in (("example", "intern", new), ("example-legacy", "campus", old)):
            with self.subTest(tenant=tenant):
                summary = self.run_tenant(tab, tenant=tenant, channel=channel)
                self.assertEqual((collect.exit_code(summary), summary["list_loads"], summary["saved"]), (4, 1, 0))
                self.assertIn("找不到岗位卡片", summary["message"])
                self.assertNotEqual(summary["searches"][0]["finished"], "no_results")

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
        details = {f"{OLD_HOST}/zpdetail/{job}": legacy_detail(title, salary) for job, title, salary in (
            ("151000002", "示例Java开发（校招,广州）", "8000-12000 元/月"), ("151000001", "示例前端开发（校招，广州）", ""),
            ("151000000", "示例测试（校招，广州）", "面议"))}
        tab = Tab(lists={"/search": [first, last]}, details=details)
        summary = self.run_tenant(tab, tenant="example-legacy")
        self.assertEqual((summary["status"], summary["saved"], summary["list_loads"], summary["finished"]),
                         ("done", 3, 2, "end_of_list"))
        self.assertEqual([parse_qs(urlsplit(url).query) for url in tab.calls[:2]],
                         [{"r": ["2"], "c": ["4401"]}, {"r": ["2"], "c": ["4401"], "PageIndex": ["2"]}])
        records = self.saved(summary)
        record = records["beisen.example-legacy.151000002.json"]
        # The title without its apply status; the job's own facts, not the search form's 工作地点：.
        self.assertEqual(record["text"].split("\n")[:7],
                         ["示例Java开发（校招,广州）", "招聘频道：校园招聘", "工作地点：广东省-广州市", "工作性质：全职",
                          "薪资：8000-12000 元/月", "发布时间：2026-09-14", "公司名称：示例信息"])
        self.assertEqual(record["text"].split("\n")[7:],
                         ["工作职责", "1.负责示例系统开发。", "2.参与示例接口联调。", "任职资格", "本科及以上学历，熟悉 Java。"])
        self.assertEqual(record["extra"]["list_published"], "2026-09-14")
        parsed = jd_parser.parse_text(record["text"], source_type="portal", site="ats", single=True)[0][0]
        self.assertEqual((parsed["title"], parsed["cities"], parsed["published_at"], record["url"]),
                         ("示例Java开发（校招,广州）", ["广州"], "2026-09-14", f"{OLD_HOST}/zpdetail/151000002"))
        self.assertEqual((parsed["salary"]["min"], parsed["salary"]["max"], parsed["salary"]["unit"]),
                         (8000, 12000, "CNY/month"))
        self.assertNotIn("薪资：", records["beisen.example-legacy.151000001.json"]["text"])
        self.assertIn("薪资：面议", records["beisen.example-legacy.151000000.json"]["text"])

    def test_legacy_empty_result_needs_the_portals_own_sign(self):
        # The recorded empty page: 共0条记录 and the no-results box in the table. Rows whose links are
        # not recognised, or no rows under a count above 0, are a changed page, not "no results".
        no_box = legacy_list([], 1, 1, 0).replace('<div class="zx_nojob">', '<div class="other">')
        no_count = legacy_list([], 1, 1, 0).replace("共0条记录", "")
        for html, finished in ((legacy_list([], 1, 1, 0), "no_results"), (no_box, "no_results"),
                               (no_count, "no_results"),
                               (legacy_list([("151000002", "示例甲")], 1, 1, 1, link="/jobdetail/{job}"), None),
                               (legacy_list([], 1, 1, 2), None)):
            with self.subTest(html=html[-160:]):
                summary = self.run_tenant(Tab(lists={"/search": [html]}), tenant="example-legacy")
                self.assertEqual(summary["finished"], finished)
                self.assertEqual(collect.exit_code(summary), 0 if finished else 4)

    def test_new_empty_result_needs_the_response_and_the_page_to_say_so(self):
        # The recorded empty page: Count 0 and no job ad in the page's own response, the empty box and
        # no card on the page. Anything less, or a page and a response that disagree, is a changed page.
        empty = list_response([])
        one = card(item(A, "示例甲"))
        no_box = new_list(f"{NEW_HOST}/intern/jobs", empty).html.replace("STEmpty-editor", "STOther-editor")
        for snapshot, finished in (
                (lambda url: new_list(url, empty), "no_results"),
                (lambda url: new_list(url, empty, cards=one), None),  # a card the response does not have
                (lambda url: collect.Snapshot(url, "实习生招聘", no_box, 200, (empty,)), None),  # no empty box
                (lambda url: new_list(url, list_response([], total=2)), None),  # Count says there are jobs
                (lambda url: new_list(url), None),  # the list response never came
                (lambda url: new_list(url, list_response([{"JobAdId": 151000001, "JobAdName": "示例甲"}])), None)):
            with self.subTest(finished=finished):
                summary = self.run_tenant(Tab(lists={"/intern/jobs": [snapshot]}), channel="intern")
                self.assertEqual((summary["finished"], collect.exit_code(summary)), (finished, 0 if finished else 4))
                if not finished:
                    self.assertIn("找不到岗位卡片", summary["message"])

    def test_job_ads_without_a_uuid_id_are_a_changed_page_not_no_results(self):
        # The first live run: Id holds the UUID; JobAdId, an internal number, is not the job's id.
        misread = [{**item(A, "示例甲"), "Id": None}, {**item(B, "示例乙"), "Id": "151000002"}]
        tab = Tab(lists={"/intern/jobs": [lambda url: new_list(url, list_response(misread, keyword="示例"))]})
        summary = self.run_tenant(tab, keywords=["示例"], channel="intern")
        self.assertEqual((collect.exit_code(summary), summary["status"], summary["searches"][0]["finished"]),
                         (4, "page_changed", "stopped"))
        self.assertIn("找不到岗位卡片", summary["message"])
        rules = beisen.tenant_rules(TENANTS["example"], "intern")
        both = list_response([item(A, "示例甲(J10001)"), item(B, "示例乙", salary="")], total=3)
        cards, unreadable = rules.parse_cards(beisen.htmltext.parse(""), f"{NEW_HOST}/intern/jobs", responses=(both,))
        self.assertEqual(([c["id"] for c in cards], unreadable), ([f"beisen.example.{A}", f"beisen.example.{B}"], 0))
        self.assertEqual([(c["title"], c["salary"], c["location"], c["extra"].get("job_code")) for c in cards],
                         [("示例甲", "面议", "广东省·广州市", "J10001"), ("示例乙", "", "广东省·广州市", None)])
        self.assertTrue(rules.has_more(beisen.htmltext.parse(""), responses=(both,)))  # Count 3, Total 0
        rest = list_response([item(C, "示例丙")], total=3, page=1)
        self.assertFalse(rules.has_more(beisen.htmltext.parse(""), responses=(both, rest)))

    def test_the_empty_box_is_not_a_ready_signal(self):
        # The box (and 共 0 个) can show before the list response arrives: waiting for it would read too early.
        self.assertFalse(any("Empty" in selector or "BreadJobInfo" in selector
                             for selector in beisen.NewPortal.LIST_READY))


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
