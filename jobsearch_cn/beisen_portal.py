"""Read one allowlisted Beisen list or detail for /scrape, without opening the job store."""

import json
import re
from datetime import date

from jobsearch_cn import beisen, browser, collect, htmltext, schema, store
from jobsearch_cn.content import placeholder_description

MAX_RESULTS = 20
# Same Unicode output boundary as the portable portal CLIs. Newlines in JD sections are visible.
_INVISIBLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u00ad\u061c\u180e\u200b-\u200f"
                        r"\u202a-\u202e\u2060-\u206f\ufe00-\ufe0f\ufeff\U000e0000-\U000e007f\U000e0100-\U000e01ef]")
_COLUMNS = ("id", "title", "company", "location", "date", "url")


class PortalError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def bad_args(message):
    raise PortalError("BAD_ARGS", "北森门户参数无效，请查看 beisen-portal search 或 detail 的 --help")


def add_commands(parser):
    parser.error = bad_args
    commands = parser.add_subparsers(dest="action", required=True)
    search = commands.add_parser("search", allow_abbrev=False, help="读取一个城市的列表第一页")
    search.add_argument("-q", "--query", default="", help="搜索词；省略时读取该城市和频道的列表")
    search.add_argument("-l", "--location", help="白名单城市；白名单只有一个城市时可省略")
    search.add_argument("--jobage", type=int, help="按列表发布日期过滤，单位天，未知日期跳过")
    search.add_argument("--page", type=int, default=1, help="仅支持第 1 页")
    search.add_argument("--limit", type=int, default=MAX_RESULTS, help=f"最多返回 1 到 {MAX_RESULTS} 条")
    detail = commands.add_parser("detail", allow_abbrev=False, help="读取一个岗位的详情正文")
    detail.add_argument("posting", help="搜索返回的带租户前缀的 id 或规范详情 URL")
    for command in (search, detail):
        command.error = bad_args
        command.add_argument("--tenant", required=command is search, help="白名单中的北森子域名")
        command.add_argument("--channel", choices=tuple(beisen.CHANNELS), required=command is search)
        command.add_argument("--data-dir", help="数据根目录，本入口只读取 collect/beisen.json")
        command.add_argument("--format", choices=("json", "table", "plain"), default="json")
        command.set_defaults(handler=run)


def _page(site, url, ready):
    snapshot, policy, reason = browser.read_public_page(url, ready, getattr(site, "CAPTURE", ()))
    if not policy or policy["status"] != "allowed":
        raise PortalError("ROBOTS", "robots 未许可本次读取")
    if reason:
        raise PortalError("ACCESS_STOP", reason)
    if snapshot is None or snapshot.url != url:
        raise PortalError("PAGE_CHANGED", "没有可确认的请求页面")
    root = htmltext.parse(snapshot.html)
    kw = {"responses": snapshot.responses} if getattr(site, "CAPTURE", None) else {}
    problem = site.page_problem(snapshot.url, snapshot.title, root, snapshot.status, **kw)
    if problem:
        # API error messages can carry arbitrary third-party text.
        code = "PAGE_CHANGED" if problem[0] == "changed" else "ACCESS_STOP"
        raise PortalError(code, "页面结构或搜索条件无法确认" if code == "PAGE_CHANGED" else "门户限制访问或要求登录")
    return root, kw


def _search(args, site):
    if args.page != 1:
        raise PortalError("BAD_ARGS", "本入口每次只读取第一页，--page 只支持 1")
    if not 1 <= args.limit <= MAX_RESULTS:
        raise PortalError("BAD_ARGS", f"--limit 范围是 1 到 {MAX_RESULTS}")
    if args.jobage is not None and args.jobage < 0:
        raise PortalError("BAD_ARGS", "--jobage 要写非负整数")
    if len(args.query) > collect.MAX_QUERY or args.query != args.query.strip():
        raise PortalError("BAD_ARGS", f"搜索词最多 {collect.MAX_QUERY} 个字，前后不能有空格")
    cities = site.tenant.cities
    if args.location is None and len(cities) == 1:
        city_code = cities[0][1]
    else:
        city_code = next((code for city, code, label in cities if args.location in (city, label)), None)
    if city_code is None:
        raise PortalError("BAD_ARGS", "--location 需指定该租户白名单中的一个城市")
    url = site.search_url(args.query, city_code)
    root, kw = _page(site, url, site.LIST_READY)
    cards, _ = site.parse_cards(root, url, visible_only=True, **kw)
    if not cards and not site.list_is_empty(root, **kw):
        raise PortalError("PAGE_CHANGED", "无法从列表确认岗位或空结果")
    results, seen = [], set()
    today = date.today()
    for card in cards:
        published = card["extra"].get("list_published")
        if args.jobage is not None:
            if not published or not 0 <= (today - date.fromisoformat(published)).days <= args.jobage:
                continue
        if card["id"] in seen:
            continue
        seen.add(card["id"])
        row = _clean({"id": card["id"], "title": card["title"], "company": site.tenant.company,
                      "location": card["location"] or None, "date": published, "url": card["href"]})
        if not row["title"]:
            continue
        results.append(row)
        if len(results) == args.limit:
            break
    return {"meta": {"count": len(results), "page": 1}, "results": results}


def _detail(args, tenants):
    value = args.posting
    try:
        if value.startswith("beisen."):
            if not args.tenant or not args.channel:
                raise PortalError("BAD_ARGS", "按岗位 id 读取时请指定 --tenant 和 --channel")
            site = _site(tenants, args.tenant, args.channel)
            url = site.canonical_url(value)
        else:
            url = value
        subdomain, _, _ = beisen.detail_address(url)
        if args.tenant is not None and args.tenant != subdomain:
            raise PortalError("BAD_ARGS", "显式租户和详情链接不一致")
        if subdomain not in tenants:
            raise PortalError("WHITELIST", "租户未列入本机白名单")
        site, source = beisen.detail_rules(tenants[subdomain], url, args.channel)
    except collect.CollectError as exc:
        raise PortalError("BAD_ARGS", str(exc)) from None
    except ValueError:
        raise PortalError("BAD_ARGS", "请使用该租户和频道的完整岗位 id 或规范详情 URL") from None
    root, kw = _page(site, url, site.DETAIL_READY)
    if site.is_closed(root, **kw):
        raise PortalError("CLOSED", "岗位页面已显示关闭")
    fields = site.parse_detail(root, publication_only=True, **kw)
    if (not _INVISIBLE.sub("", fields["title"]).strip()
            or placeholder_description(_INVISIBLE.sub("", fields["description"]))
            or len(site.detail_text(fields)) > schema.MAX_RAW_TEXT):
        raise PortalError("PAGE_CHANGED", "无法从详情页确认完整岗位正文")
    return _clean({
        "id": site.job_id_from_url(url), "title": fields["title"], "company": site.tenant.company,
        "location": "、".join(fields["places"]) or None, "date": fields["published"], "url": url,
        "description": fields["description"], "salary": fields["salary"] or None,
        "company_source": "whitelist", "channel_source": source,
    })


def _clean(row):
    return {key: (_INVISIBLE.sub("", value).strip() or None) if isinstance(value, str) else value
            for key, value in row.items()}


def _site(tenants, subdomain, channel):
    tenant = tenants.get(subdomain)
    if tenant is None or channel not in tenant.channels:
        raise PortalError("WHITELIST", "租户或频道未列入本机白名单")
    return beisen.tenant_rules(tenant, channel)


def run(args):
    try:
        tenants = beisen.load_tenants(store.data_dir(args.data_dir))
    except collect.CollectError:
        raise PortalError("WHITELIST", "请按 docs/cn/collect.md 检查本机 collect/beisen.json 白名单") from None
    try:
        if args.action == "search":
            payload = _search(args, _site(tenants, args.tenant, args.channel))
            rows = payload["results"]
        else:
            payload = _detail(args, tenants)
            rows = [payload]
    except browser.BrowserUnavailable as exc:
        raise PortalError("BROWSER_UNAVAILABLE", str(exc)) from None
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False))
    else:
        separator = "\t" if args.format == "table" else " | "
        if args.format == "table":
            print(separator.join(_COLUMNS))
        for row in rows:
            print(separator.join(" ".join((row[key] or "").split()) for key in _COLUMNS))
            if args.action == "detail":
                print(row["description"])
    return 0
