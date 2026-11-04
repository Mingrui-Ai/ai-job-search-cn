"""BOSS直聘 site rules for the collector: URLs, the selectors for each field, and page checks.

Everything that depends on how zhipin.com lays out its pages is in this file, most of it in
SELECTORS, so a layout change is fixed here (docs/cn/collect.md, "页面结构变了怎么办"). Each
rule is a list of selectors tried in order; the first that matches anything wins. The selector
syntax is the subset htmltext.py reads, which is also valid CSS for the browser to wait on.

Nothing here decodes, signs or builds platform identifiers. A job is opened by the link its
card carries; its id is the opaque path segment of that link, kept as it is. The only URL this
file builds is the search page, from the query and the city the user typed, the way the site's
own search box does.
"""

import re
from urllib.parse import urlencode, urljoin, urlsplit

from jobsearch_cn import htmltext

SITE = "boss"
HOST = "www.zhipin.com"
ORIGIN = "https://www.zhipin.com"
SEARCH_PATH = "/web/geek/jobs"
DETAIL_PATH = re.compile(r"/job_detail/([A-Za-z0-9._~-]{1,128})\.html")

# How the result list grows past the first screen: "scroll" (the list loads more as it is
# scrolled to the end) or "url" (a page=N parameter on the search URL).
PAGINATION = "scroll"

# City codes of the search page's city parameter, for the cities people ask for most. Any other
# city: pass its code with --city-code (it is in the address bar after picking the city on the
# site), or add it here.
CITY_CODES = {
    "全国": "100010000",
    "北京": "101010100",
    "上海": "101020100",
    "天津": "101030100",
    "重庆": "101040100",
    "广州": "101280100",
    "深圳": "101280600",
    "珠海": "101280700",
    "佛山": "101280800",
    "东莞": "101281600",
    "中山": "101281700",
    "惠州": "101280300",
    "杭州": "101210100",
    "宁波": "101210400",
    "南京": "101190100",
    "苏州": "101190400",
    "无锡": "101190200",
    "武汉": "101200100",
    "长沙": "101250100",
    "成都": "101270100",
    "西安": "101110100",
    "郑州": "101180100",
    "合肥": "101220100",
    "厦门": "101230200",
    "福州": "101230100",
    "济南": "101120100",
    "青岛": "101120200",
}

SELECTORS = {
    # Search results: one card per job, and inside it the link to the job's detail page.
    "card": ["li.job-card-box", "li.job-card-wrapper", "div.job-card-wrap"],
    "card_link": ["a.job-name[href]", "a.job-card-left[href]", "a[href*=\"/job_detail/\"]"],
    "card_title": [".job-name", ".job-title"],
    "card_salary": [".job-salary", ".salary"],
    "card_location": [".company-location", ".job-area"],
    # A search that really found nothing shows this instead of cards.
    "list_empty": [".job-empty-wrapper", ".job-empty-box", ".search-job-empty"],
    # Detail page fields, in the order they go into the inbox text.
    "detail_title": [".job-banner .name h1", ".info-primary .name h1", ".job-detail-box .job-name"],
    "detail_salary": [".job-banner .salary", ".info-primary .salary", ".job-detail-box .job-salary"],
    "detail_tags": [".info-primary > p > *", ".job-detail-box .tag-list > li"],
    "detail_keywords": [".job-keyword-list > li"],
    "detail_description": [".job-detail-section .job-sec-text", ".job-sec-text", ".job-detail-body .desc"],
    "detail_address": [".job-location .location-address", ".location-address", ".job-address-desc"],
    "detail_company": [".sider-company .company-info a", ".job-detail-company .company-name"],
    "detail_company_info": [".sider-company > p"],
    "detail_company_full": [".level-list .company-name"],
    # Removed from the detail page before any field is read: the recruiter (name, title, the
    # "刚刚活跃" online status), counters, recommendations and labels that are not the job. They
    # change from one visit to the next or describe other jobs, and the inbox text must not
    # (M6-4 design §3.3).
    "detail_remove": [
        ".job-boss-info", ".boss-info-attr", ".boss-active-time", ".boss-online-tag",
        ".look-job-list", ".similar-job-list", ".promotion-img",
        ".sider-company .title", ".level-list li > span", ".job-op", ".btn",
    ],
    # The job was taken down: counted and skipped, the run goes on.
    "detail_closed": [".job-closed", ".job-status-closed"],
    # A security check or captcha anywhere on a page: stop and hand over to the user.
    "blocked": ["[class*=captcha]", "[id*=captcha]", "[class*=geetest]", ".page-verify", "#verify-wrap"],
    # Signs of a signed-out page: stop and ask the user to sign in.
    "login": ["a[ka=header-login]", "[class*=login-dialog]", ".sign-form"],
}

# Address paths and page titles of the site's security check and sign-in pages.
BLOCKED_PATHS = ("/web/passport/", "/web/common/security")
LOGIN_PATHS = ("/web/user/",)
BLOCKED_TITLES = ("请稍候", "安全验证", "验证码", "访问异常")
CLOSED_STATUS_SELECTORS = [".job-status"]
CLOSED_WORDS = ("已关闭", "已下线", "停止招聘", "已失效", "已过期")

LIST_READY = SELECTORS["card"] + SELECTORS["list_empty"] + SELECTORS["blocked"] + SELECTORS["login"]
DETAIL_READY = SELECTORS["detail_title"] + SELECTORS["detail_closed"] + SELECTORS["blocked"] + SELECTORS["login"]


def search_url(query: str, city_code: str, page: int = 1) -> str:
    params = {"query": query, "city": city_code}
    if PAGINATION == "url" and page > 1:
        params["page"] = str(page)
    return f"{ORIGIN}{SEARCH_PATH}?{urlencode(params)}"


def job_id_from_url(url):
    """The job id in a detail page link on www.zhipin.com, or None for anything else."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or (parts.hostname or "").lower() not in (HOST, "zhipin.com"):
        return None
    match = DETAIL_PATH.fullmatch(parts.path)
    return match.group(1) if match else None


def canonical_url(job_id: str) -> str:
    """The detail page link without its query string, which carries per-visit parameters."""
    return f"{ORIGIN}/job_detail/{job_id}.html"


def _text_of(root, rule, **options) -> str:
    node = htmltext.first(root, SELECTORS[rule])
    return htmltext.text(node, **options) if node is not None else ""


def _texts_of(root, rule) -> list:
    return [value for value in (htmltext.text(node) for node in htmltext.select_first_rule(root, SELECTORS[rule])) if value]


def page_problem(url: str, title: str, root, status=None):
    """("blocked" | "login", reason) when the page is a security check or signed out, else None."""
    path = urlsplit(url or "").path
    host = (urlsplit(url or "").hostname or "").lower()
    if status in (403, 429):
        return "blocked", f"网站返回 HTTP {status}"
    if host and host not in (HOST, "zhipin.com") and not host.endswith(".zhipin.com"):
        return "blocked", f"页面跳到了别的网站（{host}）"
    if any(path.startswith(prefix) for prefix in BLOCKED_PATHS):
        return "blocked", "跳到了安全检查页"
    if any(word in (title or "") for word in BLOCKED_TITLES):
        return "blocked", f"页面标题是\"{title}\"，像是安全检查页"
    if htmltext.select_first_rule(root, SELECTORS["blocked"]):
        return "blocked", "页面上有验证码或安全验证"
    if any(path.startswith(prefix) for prefix in LOGIN_PATHS):
        return "login", "跳到了登录页"
    if htmltext.select_first_rule(root, SELECTORS["login"]):
        return "login", "页面显示没有登录"
    return None


def parse_cards(root, page_url: str):
    """(cards, unreadable count). A card is a dict: id, href (absolute), title, salary, location."""
    cards, unreadable = [], 0
    for card in htmltext.select_first_rule(root, SELECTORS["card"]):
        link = htmltext.first(card, SELECTORS["card_link"])
        href = urljoin(page_url or ORIGIN, link.get("href", "")) if link is not None else ""
        job_id = job_id_from_url(href)
        if job_id is None:
            unreadable += 1
            continue
        cards.append({
            "id": job_id,
            "href": href,
            "title": _text_of(card, "card_title"),
            "salary": _text_of(card, "card_salary"),
            "location": _text_of(card, "card_location"),
        })
    return cards, unreadable


def list_is_empty(root) -> bool:
    return bool(htmltext.select_first_rule(root, SELECTORS["list_empty"]))


def is_closed(root) -> bool:
    if htmltext.select_first_rule(root, SELECTORS["detail_closed"]):
        return True
    status = " ".join(htmltext.text(node) for node in htmltext.select_first_rule(root, CLOSED_STATUS_SELECTORS))
    return any(word in status for word in CLOSED_WORDS)


def _remove(root, selectors) -> None:
    doomed = [node for selector in selectors for node in htmltext.select(root, selector)]
    for node in doomed:
        if node.parent is not None and node in node.parent.children:
            node.parent.children.remove(node)


def parse_detail(root) -> dict:
    """The job's own fields from a detail page. Changes the tree (drops the parts that are not the job)."""
    _remove(root, SELECTORS["detail_remove"])
    company = next(iter(_texts_of(root, "detail_company")), "")
    return {
        "title": _text_of(root, "detail_title"),
        "salary": _text_of(root, "detail_salary"),
        "tags": _texts_of(root, "detail_tags"),
        "keywords": _texts_of(root, "detail_keywords"),
        "description": _text_of(root, "detail_description", keep_newlines=True),
        "address": _text_of(root, "detail_address"),
        "company": company,
        "company_info": _texts_of(root, "detail_company_info"),
        "company_full": _text_of(root, "detail_company_full"),
    }


def detail_text(fields: dict) -> str:
    """The inbox text: the page's own wording in reading order, one block per line.

    Laid out like a whole-page copy, which `jd parse --site boss` reads (jd-parse.md): the title
    and salary on the first line, the tag line (city, schedule, duration, degree) under it, the
    description, the work address, then the company.
    """
    lines = [" ".join(part for part in (fields["title"], fields["salary"]) if part)]
    if fields["tags"]:
        lines.append(" ".join(fields["tags"]))
    lines.append("职位描述")
    if fields["keywords"]:
        lines.append(" ".join(fields["keywords"]))
    lines.append(fields["description"])
    if fields["address"]:
        lines += ["工作地址", fields["address"]]
    if fields["company"]:
        lines.append(fields["company"])
    if fields["company_info"]:
        lines.append(" ".join(fields["company_info"]))
    if fields["company_full"] and fields["company_full"] != fields["company"]:
        lines.append(fields["company_full"])
    return "\n".join(line for line in lines if line)


def _squash(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def same_job(card_title: str, detail_title: str) -> bool:
    """Whether the detail page is the job the card named. List titles may be cut short."""
    card, detail = _squash(card_title).rstrip(".…"), _squash(detail_title)
    return not card or not detail or card in detail or detail in card


def location_matches(location: str, city: str) -> bool:
    return not location or not city or city == "全国" or location.startswith(city)
