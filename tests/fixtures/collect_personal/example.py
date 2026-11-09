"""Fictional test-only adapter at example.invalid; never a real source."""

import re
import unicodedata
from urllib.parse import urlencode, urljoin, urlsplit

from jobsearch_cn import htmltext
from jobsearch_cn.content import placeholder_description as _placeholder

NAME = "虚构示例校招"
SITE = "official"
SOURCE_NAME = "example"
COLLECTOR = "jobsearch_cn.collect.example/1"
HOST = "jobs.example.invalid"
ORIGIN = f"https://{HOST}"
SEARCH_PATH = "/openings"
DETAIL_PATH = re.compile(r"/openings/([0-9]{1,128})/detail/?")
PAGINATION = "url"
STRICITY_LIST = True
CITY_CODES = {"广州": "CITY_45"}
CITY_CODE = re.compile(r"CITY_[0-9]{1,10}")
CITY_CODE_HELP = "--city-code 应为官网 location 参数中的 CITY_数字；请先在官网选好城市核对"

SELECTORS = {
    "card": ['.example-list a[href*="/openings/"]'],
    "card_title": [".example-title"],
    "card_location": [".example-location > span"],
    "list_empty": [".example-list .example-empty"],
    "detail_title": [".example-detail > .example-header > .example-title"],
    "detail_tags": [".example-detail > .example-meta > span"],
    "detail_blocks": [".example-detail > .example-content"],
    "blocked": ["[class*=captcha]", "[id*=captcha]", "[class*=example-check]", ".page-verify"],
    "login": [".login-dialog", ".login-form", 'form[action*="/login"]'],
}
LIST_READY = SELECTORS["card"] + SELECTORS["list_empty"] + SELECTORS["blocked"] + SELECTORS["login"]
DETAIL_READY = SELECTORS["detail_blocks"] + SELECTORS["blocked"] + SELECTORS["login"]


def _parts(url, *, allow_http=False):
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
        schemes = ("https", "http") if allow_http else ("https",)
        default_port = 80 if parts.scheme == "http" else 443
        if (parts.scheme not in schemes or parts.hostname != HOST or parts.port not in (None, default_port)
                or parts.username is not None or parts.password is not None):
            return None
        return parts
    except ValueError:
        return None


def search_url(query: str, city_code: str, page: int = 1) -> str:
    return f"{ORIGIN}{SEARCH_PATH}?{urlencode({'keywords': query, 'location': city_code, 'current': page, 'limit': 10})}"


def job_id_from_url(url):
    parts = _parts(url)
    match = DETAIL_PATH.fullmatch(parts.path) if parts else None
    return match.group(1) if match else None


def known_job_id_from_url(url):
    """Legacy stored HTTP URLs name the same job, but are never accepted for navigation."""
    parts = _parts(url, allow_http=True)
    match = DETAIL_PATH.fullmatch(parts.path) if parts else None
    return match.group(1) if match else None


def canonical_url(job_id: str) -> str:
    return f"{ORIGIN}{SEARCH_PATH}/{job_id}/detail"


def _visible(node, *, include_nontext=False) -> bool:
    while node is not None:
        if not htmltext.visible(node, include_nontext=include_nontext):
            return False
        node = node.parent
    return True


def _nodes(root, rule):
    # A hidden placeholder for the first selector must not mask a visible fallback.
    for selector in SELECTORS[rule]:
        nodes = [node for node in htmltext.select(root, selector)
                 if _visible(node, include_nontext=rule in ("blocked", "login"))]
        if nodes:
            return nodes
    return []


def _text(root, rule):
    return next((htmltext.text(node) for node in _nodes(root, rule)), "")


def page_problem(url: str, title: str, root, status=None):
    if status in (401, 403, 429):
        return "blocked", f"网站返回 HTTP {status}"
    parts = _parts(url)
    if parts is None:
        return "blocked", "页面离开了虚构示例官网的 HTTPS 地址"
    if any(word in (title or "") for word in ("安全验证", "验证码", "访问异常", "请稍候")):
        return "blocked", "页面标题显示安全检查"
    if any(word in parts.path.lower() for word in ("/verify", "/captcha", "/security")) or _nodes(root, "blocked"):
        return "blocked", "页面上有验证码或安全验证"
    if "/login" in parts.path.lower() or _nodes(root, "login"):
        return "login", "页面要求登录"
    if parts.path.rstrip("/") != SEARCH_PATH and not DETAIL_PATH.fullmatch(parts.path):
        return "blocked", "页面离开了公开的校招列表和详情路径"
    # The public site's header always has a login link; it is not a login wall.
    return None


def parse_cards(root, page_url: str):
    cards, unreadable = [], 0
    for link in _nodes(root, "card"):
        href = urljoin(page_url, link.get("href", ""))
        job_id, title = job_id_from_url(href), _text(link, "card_title")
        if job_id is None or not title:
            unreadable += 1
            continue
        cards.append({"id": job_id, "href": canonical_url(job_id), "title": title,
                      "salary": "", "location": _text(link, "card_location")})
    return cards, unreadable


def list_is_empty(root) -> bool:
    return any("暂无职位" in htmltext.text(node) for node in _nodes(root, "list_empty"))


def is_closed(root) -> bool:
    # Only an explicit standalone notice counts, never a phrase inside the JD.
    notices = htmltext.select(root, ".example-detail") + htmltext.select(root, ".example-closed")
    return any(htmltext.text(node).strip("。！ ") in ("职位已关闭", "职位已下线", "该职位已下线", "该职位已停止招聘")
               for node in notices if _visible(node))


def parse_detail(root) -> dict:
    sections = []
    for block in _nodes(root, "detail_blocks"):
        siblings = block.parent.children
        previous = [node for node in siblings[:siblings.index(block)] if isinstance(node, htmltext.Node)]
        heading = previous[-1] if previous else None
        if heading is None or "example-heading" not in heading.classes():
            continue
        label, content = htmltext.text(heading), htmltext.text(block, keep_newlines=True)
        if label in ("职位描述", "职位要求") and content and not _placeholder(content):
            sections.append((label, content))
    # A partial render must not become a complete JD.
    description = "\n".join(value for section in sections for value in section)
    if {label for label, _ in sections} != {"职位描述", "职位要求"}:
        description = ""
    return {"title": _text(root, "detail_title"), "description": description,
            "tags": [htmltext.text(node) for node in _nodes(root, "detail_tags") if htmltext.text(node)]}


def detail_text(fields: dict) -> str:
    # No inferred salary or company label: missing fields remain unknown in jd screen.
    return "\n".join([fields["title"], *fields["tags"], fields["description"]])


def same_job(card_title: str, detail_title: str) -> bool:
    return re.sub(r"\s+", "", card_title) == re.sub(r"\s+", "", detail_title)


def location_matches(location: str, city: str) -> bool:
    return not location or not city or city in re.split(r"[、,，/\s]+", location)
