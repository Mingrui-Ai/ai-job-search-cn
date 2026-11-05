"""ByteDance's public campus pages: offline DOM rules for the shared collector.

Search parameters and selectors were observed on the site's own search UI. No API calls,
request headers, credentials, signed parameters or links inside descriptions are used.
Only the campus listing and its detail links are accepted; referral pages are excluded.
"""

import re
import unicodedata
from urllib.parse import urlencode, urljoin, urlsplit

from jobsearch_cn import htmltext

NAME = "字节跳动校招"
SITE = "official"
SOURCE_NAME = "bytedance"
COLLECTOR = "jobsearch_cn.collect.bytedance/1"
HOST = "jobs.bytedance.com"
ORIGIN = f"https://{HOST}"
SEARCH_PATH = "/campus/position"
DETAIL_PATH = re.compile(r"/campus/position/([0-9]{1,128})/detail/?")
PAGINATION = "url"
STRICT_LIST = True
CITY_CODES = {"广州": "CT_45"}
CITY_CODE = re.compile(r"CT_[0-9]{1,10}")
CITY_CODE_HELP = "--city-code 应为官网 location 参数中的 CT_数字；请先在官网选好城市核对"

# Whole-section UI notices may put the object before or after the status. A status
# signal is also required, so short duties such as "加载数据" remain valid content.
_DESCRIPTION_HEADINGS = re.compile(
    r"职位描述|岗位描述|职位详情|岗位详情|岗位职责|工作职责|工作内容|任职要求|任职资格|岗位要求|职位要求|"
    # Bound modifier lookback so repeated "job " in a long JD is still linear to scan.
    r"\b(?:(?:job|position|role|candidate|key|main|required|preferred|minimum|basic|essential|desired)[\s_-]+){0,4}"
    r"(?:descriptions?|details?|responsibilities|requirements|qualifications|duties|skills|overview|summary)\b", re.I)
_UI_OBJECT = ("职位|岗位|工作|描述|详情|要求|内容|信息|数据|页面|网络|系统|服务器|请求|jobs?|positions?|descriptions?|"
              "details?|requirements?|content|data|pages?|information|network|system|server|requests?")
_UI_STATE = ("正在|加载|载入|读取|获取|中|失败|错误|异常|暂无|超时|loading|loaded|load|failed|failure|error|"
             "unavailable|unable|couldnot|couldnt|cannot|cant|timeout|timedout|somethingwentwrong")
_UI_PROMPT = ("请|您|稍候|稍后|稍等|片刻|一下|一会儿?|一小会|几|秒钟?|分钟|耐心|等待|刷新|重试|再试|重新|为您|抱歉|"
              "点击|please|wait|waiting|a|an|the|your|this|for|while|we|are|is|be|to|of|and|just|moments?|seconds?|"
              "minutes?|few|short|little|bit|refresh|reload|retry|try|again|later|sorry")
_PLACEHOLDER_DESCRIPTION = re.compile(f"(?:{_UI_OBJECT}|{_UI_STATE}|{_UI_PROMPT})+", re.I)
_UI_STATUS_SIGNAL = re.compile(
    r"正在(?:为您)?(?:加载|载入|读取|获取)|(?:加载|载入|读取|获取)中|失败|错误|异常|超时|"
    r"请(?:您)?(?:稍候|稍后|稍等|耐心|等待|刷新|重试)|稍候|稍后|稍等|暂无|"
    r"loading|failed|failure|error|unavailable|unable|couldnot|couldnt|cannot|cant|pleasewait|waiting|wait(?:for)?a?moment|"
    r"justamoment|refresh|reload|retry|tryagain|timeout|timedout|somethingwentwrong", re.I)

SELECTORS = {
    "card": ['.positionList-content a[href*="/campus/position/"]'],
    "card_title": [".positionItem-title-text"],
    "card_location": [".positionItem-subTitle > span"],
    "list_empty": [".positionList-content .listNoData-text"],
    "detail_title": [".jobDetail > .job-header > .job-title"],
    "detail_tags": [".jobDetail > .job-info > span"],
    "detail_blocks": [".jobDetail > .block-content"],
    "blocked": ["[class*=captcha]", "[id*=captcha]", "[class*=geetest]", ".page-verify"],
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
        return "blocked", "页面离开了字节跳动官网的 HTTPS 地址"
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
    notices = htmltext.select(root, ".jobDetail") + htmltext.select(root, ".atsx-result-subtitle")
    return any(htmltext.text(node).strip("。！ ") in ("职位已关闭", "职位已下线", "该职位已下线", "该职位已停止招聘")
               for node in notices if _visible(node))


def _placeholder(content: str) -> bool:
    """Recognise an entire loading notice, not these words embedded in real duties."""
    # Only the check is normalised; accepted JD text is saved verbatim. Match headings
    # before removing separators so English word boundaries remain meaningful.
    normalized = unicodedata.normalize("NFKC", content)
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Cf")
    body = _DESCRIPTION_HEADINGS.sub("", normalized)
    compact = "".join(char for char in body.casefold() if char.isalpha())
    return not compact or bool(_UI_STATUS_SIGNAL.search(compact) and _PLACEHOLDER_DESCRIPTION.fullmatch(compact))


def parse_detail(root) -> dict:
    sections = []
    for block in _nodes(root, "detail_blocks"):
        siblings = block.parent.children
        previous = [node for node in siblings[:siblings.index(block)] if isinstance(node, htmltext.Node)]
        heading = previous[-1] if previous else None
        if heading is None or "block-title" not in heading.classes():
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
