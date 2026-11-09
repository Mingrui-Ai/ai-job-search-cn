"""Beisen (北森) recruitment portals at <tenant>.zhiye.com: collect's site rules (docs/cn/collect.md).

Only the tenants the user lists in a local whitelist are read: <data dir>/collect/beisen.json
(load_tenants), each with the link to that portal's own terms and the day the user read them.
A tenant not on the list is refused before a browser starts. The whitelist lives in the user's
data directory, never in the repository.

Two portal generations, both public and read without signing in:

* "new": a single-page app. A channel's list is /{campus|intern|social}/jobs, filtered by
  ?LocId=[{"id":"4401","label":"广州市"}] and searched by ?KeyWords=. Its cards carry no link or
  id, so the job ad ids come from the page's own list request (/api/Jobad/GetJobAdPageList),
  whose response the tab keeps (CAPTURE); nothing here builds or sends a request. More cards
  come by scrolling. A job's page, /{channel}/detail?jobAdId=<uuid>, is read from its DOM.
* "legacy": server-rendered. The list is /search?r=<channel>&c=<city code>&k=<keyword>&PageIndex=<n>,
  a table whose rows link /zpdetail/<number>; a job's page is read from its own block: the
  title, the "label：" / value pairs and the sections under their headings.

The list response, the cards, the empty result pages and both detail pages are as recorded on
the whitelisted portals on 2026-11-10 (docs/cn/worklog/2026-11-10-m6-3-beisen-live.md).

A job's id is beisen.<tenant>.<the portal's id> (schema.ATS_SITE_JOB_ID), so two companies' ids
never meet. City codes are the first four digits of the administrative division code (GB/T 2260),
which both generations use: 4401 is 广州. Standard library only.
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from jobsearch_cn import htmltext, schema
from jobsearch_cn.collect import CollectError, Search
from jobsearch_cn.content import placeholder_description

PLATFORM = "beisen"
DOMAIN = "zhiye.com"
CONFIG_FORMAT = "jobsearch_cn.beisen/1"
CONFIG_PARTS = ("collect", "beisen.json")  # under the data directory
MAX_CONFIG_BYTES = 200_000
PORTALS = ("new", "legacy")
CHANNELS = {"campus": "校园招聘", "intern": "实习生招聘", "social": "社会招聘"}
LEGACY_CHANNEL = {"social": "1", "campus": "2", "intern": "3"}  # the r= of the legacy /search
MAX_JOBS = 30  # details per run
MAX_PAGES = 5  # list loads per run, over all channels, cities and keywords
TENANT_KEYS = ("subdomain", "portal", "company", "channels", "cities", "terms_url", "terms_checked")
TENANT_OPTIONAL = ("note",)

# Short name -> (code, the name the portal shows). Municipalities use their province-level code,
# as the legacy portal's own city filter does (北京市 is c=1100). The whitelist's city_codes adds others.
CITY_TABLE = {
    "北京": ("1100", "北京市"), "天津": ("1200", "天津市"), "上海": ("3100", "上海市"), "重庆": ("5000", "重庆市"),
    "石家庄": ("1301", "石家庄市"), "太原": ("1401", "太原市"), "呼和浩特": ("1501", "呼和浩特市"),
    "沈阳": ("2101", "沈阳市"), "大连": ("2102", "大连市"), "长春": ("2201", "长春市"), "哈尔滨": ("2301", "哈尔滨市"),
    "南京": ("3201", "南京市"), "无锡": ("3202", "无锡市"), "苏州": ("3205", "苏州市"), "杭州": ("3301", "杭州市"),
    "宁波": ("3302", "宁波市"), "温州": ("3303", "温州市"), "合肥": ("3401", "合肥市"), "福州": ("3501", "福州市"),
    "厦门": ("3502", "厦门市"), "南昌": ("3601", "南昌市"), "济南": ("3701", "济南市"), "青岛": ("3702", "青岛市"),
    "郑州": ("4101", "郑州市"), "武汉": ("4201", "武汉市"), "长沙": ("4301", "长沙市"), "广州": ("4401", "广州市"),
    "深圳": ("4403", "深圳市"), "珠海": ("4404", "珠海市"), "汕头": ("4405", "汕头市"), "佛山": ("4406", "佛山市"),
    "江门": ("4407", "江门市"), "惠州": ("4413", "惠州市"), "东莞": ("4419", "东莞市"), "中山": ("4420", "中山市"),
    "南宁": ("4501", "南宁市"), "海口": ("4601", "海口市"), "成都": ("5101", "成都市"), "贵阳": ("5201", "贵阳市"),
    "昆明": ("5301", "昆明市"), "拉萨": ("5401", "拉萨市"), "西安": ("6101", "西安市"), "兰州": ("6201", "兰州市"),
    "西宁": ("6301", "西宁市"), "银川": ("6401", "银川市"), "乌鲁木齐": ("6501", "乌鲁木齐市"),
}

_SUBDOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_CITY_NAME = re.compile(r"[一-鿿]{2,10}")
_CITY_CODE = re.compile(r"[1-9][0-9]{3}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_LEGACY_ID = re.compile(r"[0-9]{1,20}")
_JOB_CODE = re.compile(r"\s*[（(]\s*(J[0-9]{3,10})\s*[)）]\s*$")
_DAY = re.compile(r"(20[0-9]{2})\s*[-/.年]\s*([0-9]{1,2})\s*[-/.月]\s*([0-9]{1,2})")
_PLACE = re.compile(r"[省市区县州]$|[·・]|^[一-鿿]+-[一-鿿]+$")
_APPLY_STATUS = re.compile(r"\s*[（(]\s*(?:未申请|已申请)\s*[)）]\s*$")
_CLOSED = ("职位已下线", "该职位已下线", "职位已关闭", "该职位已关闭", "职位已失效", "该职位已失效", "职位已过期",
           "该职位已过期", "职位已停止招聘", "该职位已停止招聘", "职位不存在", "该职位不存在")
_SECTION_HEADINGS = ("职位描述", "岗位描述", "工作职责", "岗位职责", "职位职责", "工作内容", "职位要求", "岗位要求",
                     "任职要求", "任职资格", "职位详情", "岗位详情")
_HEADING_TRIM = "：:【】[] 　"
_BLOCKED = ["[class*=captcha]", "[id*=captcha]", "[class*=geetest]", "[class*=yidun]", "[class*=tcaptcha]",
            "[id*=tcaptcha]", "[class*=slide-verify]", "[class*=slider-verify]", "[class*=nc-container]",
            "[id^=nc_]"]
_LOGIN = ["input[type=password]", "form[action*=Login]", "form[action*=login]"]
_TITLE_WORDS = ("安全验证", "验证码", "访问异常", "访问受限", "请稍候", "人机验证")


# -- the whitelist -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Tenant:
    """One company portal the user allowed: <subdomain>.zhiye.com."""

    subdomain: str
    portal: str
    company: str
    channels: tuple
    cities: tuple  # (short name, code, the name the portal shows), in the whitelist's order
    terms_url: str
    terms_checked: str


def config_path(data_root) -> Path:
    return Path(data_root).joinpath(*CONFIG_PARTS)


def load_tenants(data_root, today=None) -> dict:
    """{subdomain: Tenant} from the user's whitelist; CollectError says what is missing or wrong."""
    path = config_path(data_root)
    if not path.is_file():
        raise CollectError(f"没有北森租户白名单 {path}。先读该公司门户自己的条款，确认没有禁止自动采集，"
                           "再按 docs/cn/collect.md 写这个文件；不在名单里的门户一律不读")
    try:
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise CollectError(f"北森租户白名单 {path} 超过 {MAX_CONFIG_BYTES} 字节")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CollectError(f"北森租户白名单 {path} 读不了：{exc}") from None
    tenants, errors = parse_tenants(data, today)
    if errors:
        raise CollectError(f"北森租户白名单 {path} 有问题：" + "；".join(errors[:8]))
    return tenants


def parse_tenants(data, today=None) -> tuple:
    """({subdomain: Tenant}, errors) from the whitelist's JSON."""
    today = today or date.today()
    if not isinstance(data, dict):
        return {}, ["整个文件要是一个 JSON 对象"]
    errors = [f"{key}: 不认识的键" for key in data if key not in ("format", "city_codes", "tenants")]
    if data.get("format") != CONFIG_FORMAT:
        errors.append(f"format: 要写 {CONFIG_FORMAT!r}")
    extra_cities = data.get("city_codes", {})
    if not isinstance(extra_cities, dict) or any(
            not isinstance(name, str) or not _CITY_NAME.fullmatch(name)
            or not isinstance(code, str) or not _CITY_CODE.fullmatch(code) for name, code in extra_cities.items()):
        errors.append("city_codes: 要写 {\"城市名\": \"四位城市代码\"}，城市名 2 到 10 个汉字")
        extra_cities = {}
    known = {**CITY_TABLE, **{name: (code, name + ("" if name.endswith("市") else "市"))
                              for name, code in extra_cities.items()}}
    entries = data.get("tenants")
    if not isinstance(entries, list) or not entries:
        errors.append("tenants: 要写至少一个租户的列表")
        entries = []
    tenants = {}
    for number, entry in enumerate(entries, 1):
        where = f"tenants[{number}]"
        if not isinstance(entry, dict):
            errors.append(f"{where}: 要是一个对象")
            continue
        problems = [f"{key}: 不认识的键" for key in entry if key not in TENANT_KEYS + TENANT_OPTIONAL]
        problems += [f"{key}: 缺少" for key in TENANT_KEYS if key not in entry]
        subdomain = entry.get("subdomain")
        if not isinstance(subdomain, str) or not _SUBDOMAIN.fullmatch(subdomain) or subdomain == "www":
            problems.append("subdomain: 要写门户地址 https://<子域名>.zhiye.com 里的子域名（小写字母、数字和 -）")
        elif subdomain in tenants:
            problems.append(f"subdomain: {subdomain} 写了两次")
        if entry.get("portal") not in PORTALS:
            problems.append("portal: 要写 new（新版门户）或 legacy（旧版门户）")
        company = entry.get("company")
        if not isinstance(company, str) or not company.strip() or len(company) > 60 or "\n" in company:
            problems.append("company: 要写公司名，最多 60 个字")
        channels = entry.get("channels")
        if (not isinstance(channels, list) or not channels
                or any(not isinstance(c, str) or c not in CHANNELS for c in channels)
                or len(set(channels)) != len(channels)):
            problems.append("channels: 要写 campus、intern、social 里的一个或几个，不重复")
            channels = []
        cities = entry.get("cities")
        if (not isinstance(cities, list) or not cities or any(not isinstance(c, str) for c in cities)
                or len(set(cities)) != len(cities)):
            problems.append("cities: 要写城市名的列表，例如 [\"广州\"]，不重复")
            cities = []
        unknown = [city for city in cities if city not in known]
        if unknown:
            problems.append(f"cities: 不认识 {'、'.join(unknown)}；在 city_codes 里给出它们的四位代码")
        terms_url = entry.get("terms_url")
        if not isinstance(terms_url, str) or not terms_url.startswith(("https://", "http://")) \
                or schema._url_problem(terms_url) or not urlsplit(terms_url).hostname:
            problems.append("terms_url: 要写这个门户条款（隐私政策、用户协议）的链接")
        checked = entry.get("terms_checked")
        try:
            checked_day = date.fromisoformat(checked) if isinstance(checked, str) and _DATE.fullmatch(checked) else None
        except ValueError:
            checked_day = None
        if checked_day is None or checked_day > today:
            problems.append("terms_checked: 要写读条款的日期 YYYY-MM-DD，不能晚于今天")
        if problems:
            errors += [f"{where}.{problem}" for problem in problems]
            continue
        tenants[subdomain] = Tenant(subdomain=subdomain, portal=entry["portal"], company=company.strip(),
                                    channels=tuple(channels),
                                    cities=tuple((city, *known[city]) for city in cities),
                                    terms_url=terms_url, terms_checked=checked)
    return tenants, errors


def tenant_rules(tenant: Tenant, channel: str):
    """The site rules for one channel of one tenant's portal."""
    return (NewPortal if tenant.portal == "new" else LegacyPortal)(tenant, channel)


def searches(tenant: Tenant, keywords=(), channel=None) -> list:
    """One Search per channel, city and keyword ("" for the whole list), in the whitelist's order."""
    found = []
    for name in ([channel] if channel else tenant.channels):
        rules = tenant_rules(tenant, name)
        for city, code, _ in tenant.cities:
            for keyword in list(keywords) or [""]:
                label = "·".join([CHANNELS[name], city] + ([keyword] if keyword else []))
                found.append(Search(query=keyword, city=city, city_code=code, site=rules, label=label))
    return found


def profile_keywords(data_root) -> tuple:
    """(keywords, warning): target.search_keywords of the local profile, in order, without repeats."""
    path = Path(data_root) / "profile" / "profile.json"
    if not path.is_file():
        return [], "没有本地档案，按频道和城市读全部岗位"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CollectError(f"档案 {path} 读不了：{exc}；修好档案或用 --query、--all") from None
    target = data.get("target") if isinstance(data, dict) else None
    words = target.get("search_keywords", []) if isinstance(target, dict) else []
    if not isinstance(words, list) or any(not isinstance(word, str) for word in words):
        raise CollectError("档案的 target.search_keywords 要是字符串列表；先运行 profile validate")
    keywords, folded = [], set()
    for word in (word.strip() for word in words):
        key = unicodedata.normalize("NFKC", word).casefold().replace(" ", "")
        if word and key not in folded:
            folded.add(key)
            keywords.append(word)
    return keywords, None if keywords else "档案里没有搜索关键词，按频道和城市读全部岗位"


# -- helpers -----------------------------------------------------------------------------------

def split_job_code(title: str) -> tuple:
    """(the title without a trailing (J12345), that code or None)."""
    match = _JOB_CODE.search(title or "")
    if not match:
        return (title or "").strip(), None
    return title[:match.start()].strip(), match.group(1)


def _visible(node, *, include_nontext=False) -> bool:
    while node is not None:
        if not htmltext.visible(node, include_nontext=include_nontext):
            return False
        node = node.parent
    return True


def _nodes(root, selectors, *, include_nontext=False) -> list:
    # A hidden match of the first selector must not mask a visible match of a later one.
    for selector in selectors:
        found = [node for node in htmltext.select(root, selector) if _visible(node, include_nontext=include_nontext)]
        if found:
            return found
    return []


def _text(root, selectors, **options) -> str:
    return next((htmltext.text(node, **options) for node in _nodes(root, selectors)), "")


def _own_text(node) -> str:
    return "".join(child for child in node.children if isinstance(child, str)).strip()


def _day(text: str):
    match = _DAY.search(text or "")
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return None


def _get(mapping, *names):
    """mapping's value under the first of names present, the key's case ignored; None when absent."""
    if not isinstance(mapping, dict):
        return None
    lowered = {key.lower(): value for key, value in mapping.items() if isinstance(key, str)}
    return next((lowered[name.lower()] for name in names if name.lower() in lowered), None)


def _json(text):
    try:
        return json.loads(text) if isinstance(text, str) else None
    except ValueError:
        return None


def _api_error(payload):
    """Why a data response says it failed - a success flag or a code other than 0/200 - or None."""
    if not isinstance(payload, dict):
        return None
    message = _get(payload, "Message", "Msg", "ErrorMessage")
    message = f"：{message[:80]}" if isinstance(message, str) and message.strip() else ""
    if _get(payload, "Success", "IsSuccess") is False:
        return f"接口报错{message}"
    code = _get(payload, "Code", "StatusCode", "ErrorCode")
    if code is not None and str(code) not in ("0", "200"):
        return f"接口报错（code {str(code)[:20]}）{message}"
    return None


def _flat(value) -> str:
    """A list response's text field as one string: a list of names is joined with /."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "/".join(part.strip() for part in value if isinstance(part, str) and part.strip())
    return ""


# -- the rules shared by both generations ----------------------------------------------------

class _Portal:
    SITE = "ats"
    COLLECTOR = "jobsearch_cn.collect.beisen/1"
    CITY_CODES = None  # cities come from the whitelist; a run has no --city
    MAX_JOBS_CAP = DEFAULT_MAX_JOBS = MAX_JOBS
    MAX_PAGES_CAP = DEFAULT_MAX_PAGES = MAX_PAGES
    WHOLE_LIST = True  # without keywords a search reads the channel's whole list in that city

    def __init__(self, tenant: Tenant, channel: str):
        if channel not in tenant.channels:
            raise CollectError(f"{tenant.subdomain} 的白名单里没有频道 {channel}")
        self.tenant, self.channel = tenant, channel
        self.host = f"{tenant.subdomain}.{DOMAIN}"
        self.origin = f"https://{self.host}"
        self.prefix = f"{PLATFORM}.{tenant.subdomain}."
        self.NAME = f"{tenant.company}（北森门户 {self.host}）"
        self.SOURCE_NAME = f"beisen-{tenant.subdomain}"
        self.labels = {code: label for _, code, label in tenant.cities}

    def _parts(self, url, *, allow_http=False):
        if not isinstance(url, str):
            return None
        try:
            parts = urlsplit(url)
            schemes = ("https", "http") if allow_http else ("https",)
            default_port = 80 if parts.scheme == "http" else 443
            if (parts.scheme not in schemes or parts.hostname != self.host or parts.port not in (None, default_port)
                    or parts.username is not None or parts.password is not None):
                return None
            return parts
        except ValueError:
            return None

    def _scoped(self, native: str) -> str:
        return self.prefix + native

    def _native(self, job_id: str) -> str:
        if not job_id.startswith(self.prefix):
            raise ValueError(f"not a job of {self.host}: {job_id!r}")
        return job_id[len(self.prefix):]

    def job_id_from_url(self, url):
        return self._id_from(self._parts(url))

    def known_job_id_from_url(self, url):
        """A stored http:// address names the same job; it is never a navigation target."""
        return self._id_from(self._parts(url, allow_http=True))

    def _common_problem(self, url, title, root, status):
        if status is not None and not 200 <= status < 300:
            return "blocked", f"网站返回 HTTP {status}"
        parts = self._parts(url)
        if parts is None:
            return "blocked", f"页面离开了 {self.host} 的 HTTPS 地址"
        if any(word in (title or "") for word in _TITLE_WORDS):
            return "blocked", "页面标题显示安全检查"
        path = parts.path.lower()
        if any(word in path for word in ("/verify", "/captcha", "/security")) \
                or _nodes(root, _BLOCKED, include_nontext=True):
            return "blocked", "页面上有验证码或安全验证"
        if "/login" in path or "/account/" in path or _nodes(root, _LOGIN, include_nontext=True):
            return "login", "页面要求登录"
        return None

    def same_job(self, card_title: str, detail_title: str) -> bool:
        def norm(title):
            return re.sub(r"\s+", "", unicodedata.normalize("NFKC", split_job_code(title)[0]))
        return norm(card_title) == norm(detail_title)

    def location_matches(self, location: str, city: str) -> bool:
        return not location or not city or city in location

    def is_closed(self, root, **_) -> bool:
        # Only a notice standing on its own, never the words inside a job's text.
        for node in root.iter():
            own = _own_text(node).strip("。！!~～ ")
            if own in _CLOSED and _visible(node):
                return True
        return False

    def detail_text(self, fields: dict) -> str:
        """The job's text for the inbox: its title, its labelled facts, then its sections.

        The labels are the ones jd parse reads (工作地点, 薪资, 发布时间, 公司名称); a fact the
        page does not show is left out, so it stays unknown (null). 面议 is written as the page
        shows it. The channel names the kind of hiring (校园招聘, 实习生招聘, 社会招聘).
        """
        lines = [fields["title"], f"招聘频道：{CHANNELS[self.channel]}"]
        if fields.get("places"):
            lines.append("工作地点：" + "、".join(fields["places"]))
        if fields.get("kinds"):
            lines.append("工作性质：" + "、".join(fields["kinds"]))
        if fields.get("salary"):
            lines.append("薪资：" + fields["salary"])
        if fields.get("published"):
            lines.append("发布时间：" + fields["published"])
        lines.append("公司名称：" + self.tenant.company)
        if fields.get("job_code"):
            lines.append("职位编号：" + fields["job_code"])
        lines.append(fields["description"])
        return "\n".join(lines)

    @staticmethod
    def _sort_tags(tags) -> tuple:
        """(places, kinds) from a job's tags, the channel's own name left out."""
        places, kinds = [], []
        for tag in tags:
            if tag in CHANNELS.values() or tag == "实习招聘":
                continue
            is_place = _PLACE.search(tag) or any(city in tag for city in CITY_TABLE)
            (places if is_place else kinds).append(tag)
        return places, kinds


# -- the new portal ---------------------------------------------------------------------------

class NewPortal(_Portal):
    PORTAL = "new"
    PAGINATION = "scroll"
    LIST_REQUEST = re.compile(r"^/api/jobad/getjobadpagelist/?$", re.I)
    DETAIL_REQUEST = re.compile(r"^/api/jobad/getjobadinfo/?$", re.I)
    CAPTURE = (LIST_REQUEST, DETAIL_REQUEST)
    SELECTORS = {
        # styled-components keep their display names (STListItem) across builds; the hashes change.
        "card": ["[class*=STListItem-editor]"],
        "list_empty": ["[class*=STEmpty-editor]"],  # "暂时没有符合条件的职位~" in place of the cards
        "detail_title": ["[class*=STJobNameLeft-editor]"],
        "detail_salary": ["[class*=STJobNameRight-editor]"],
        "detail_tags": ["[class*=STJobTabInner-editor]"],
        "detail_date": ["[class*=STJobInfoRight-editor]"],
        "detail_sections": ["[class*=STDutyContainer-editor]"],
        "section_title": ["[class*=STDutyTitle-editor]"],
        "section_content": ["[class*=STDutyContent-editor]"],
    }
    # Not the empty box, nor "共 0 个": both can show before the list response has arrived, so an
    # empty result is read only after the ready wait runs out, from the response and the page.
    LIST_READY = SELECTORS["card"] + _BLOCKED + _LOGIN
    DETAIL_READY = SELECTORS["detail_sections"] + _BLOCKED + _LOGIN
    _PATH = re.compile(r"/(campus|intern|social)/(jobs|detail)/?")

    def search_url(self, query: str, city_code: str, page: int = 1) -> str:
        label = self.labels.get(city_code, city_code)
        params = [("LocId", json.dumps([{"id": city_code, "label": label}], ensure_ascii=False, separators=(",", ":")))]
        if query:
            params.append(("KeyWords", query))
        return f"{self.origin}/{self.channel}/jobs?{urlencode(params)}"

    def _id_from(self, parts):
        match = re.fullmatch(r"/(campus|intern|social)/detail/?", parts.path) if parts else None
        ids = parse_qs(parts.query).get("jobAdId", []) if match else []
        if len(ids) != 1 or not _UUID.fullmatch(ids[0]):
            return None
        return self._scoped(ids[0].lower())

    def canonical_url(self, job_id: str) -> str:
        return f"{self.origin}/{self.channel}/detail?{urlencode({'jobAdId': self._native(job_id)})}"

    # The list response, as recorded: {"Code": 200, "Message": ..., "Count": <jobs in the whole
    # result>, "Data": [<job ad>, ...], "Total": 0, ...}, 20 job ads a page (PageIndex from 0).
    # A job ad's Id is the UUID its detail page takes (jobAdId=); its JobAdId is an internal
    # number, not that id. JobAdName is the name with its job code, Salary null or text such as
    # 面议, LocNames a list of "省·市". Total stays 0: the total is Count. Any other shape is refused.
    def _list_responses(self, responses):
        return [response for response in responses if self.LIST_REQUEST.search(urlsplit(response.url).path)]

    @staticmethod
    def _payload_items(payload):
        """(job ads, total) of one list response, or None when it is not shaped as recorded."""
        data, total = _get(payload, "Data"), _get(payload, "Count")
        if not isinstance(data, list) or not isinstance(total, int) or isinstance(total, bool) or total < 0:
            return None
        return data, total

    def _list(self, responses):
        """(items, unreadable, total, recognised): the job ads of every list response so far, once each."""
        items, unreadable, total, recognised, seen = [], 0, None, False, set()
        for response in self._list_responses(responses):
            found = self._payload_items(_json(response.body))
            if found is None:
                continue
            recognised = True
            entries, total = found
            for entry in entries:
                native = _get(entry, "Id")
                name = _get(entry, "JobAdName")
                if not isinstance(native, str) or not _UUID.fullmatch(native) or not isinstance(name, str) \
                        or not name.strip():
                    unreadable += 1
                    continue
                if native.lower() in seen:
                    continue
                seen.add(native.lower())
                items.append({"id": native.lower(), "name": name.strip(), "salary": _flat(_get(entry, "Salary")),
                              "location": _flat(_get(entry, "LocNames"))})
        return items, unreadable, total, recognised

    def page_problem(self, url, title, root, status=None, responses=()):
        problem = self._common_problem(url, title, root, status)
        if problem:
            return problem
        parts = self._parts(url)
        if not self._PATH.fullmatch(parts.path):
            return "changed", "页面离开了门户公开的职位列表和详情路径"
        for response in responses:
            path = urlsplit(response.url).path
            if response.status >= 400:
                return "blocked", f"接口报错：{path} 返回 HTTP {response.status}"
            payload = _json(response.body)
            if not isinstance(payload, dict):
                return "changed", f"接口响应不是可识别的 JSON 对象（{path}）"
            failure = _api_error(payload)
            if failure:
                return "blocked", f"{failure}（{path}）"
            if self.LIST_REQUEST.search(path) and self._payload_items(payload) is None:
                return "changed", "列表接口响应里没有岗位列表（Data）和总数（Count），页面结构可能变了"
        keyword = parse_qs(parts.query).get("KeyWords", [""])[0]
        for response in self._list_responses(responses) if keyword else ():
            sent = _get(_json(response.request), "KeyWords")
            if sent != keyword:
                return "changed", ("门户没有按地址里的关键词搜索（页面发出的列表请求里不是这个关键词）；"
                                   "这个门户上用 --all 读全部岗位")
        return None

    def parse_cards(self, root, page_url: str, responses=()):
        items, unreadable, _, _ = self._list(responses)
        cards = []
        for item in items:
            title, code = split_job_code(item["name"])
            job_id = self._scoped(item["id"])
            extra = {"tenant": self.tenant.subdomain, "channel": self.channel}
            if code:
                extra["job_code"] = code
            cards.append({"id": job_id, "href": self.canonical_url(job_id), "title": title,
                          "salary": item["salary"], "location": item["location"], "extra": extra})
        return cards, unreadable

    def list_is_empty(self, root, responses=()) -> bool:
        """Only the portal's own "no results": a list response with no job ads and a Count of 0, and
        the page's empty box with no card. Job ads not recognised, or a page that disagrees, are not."""
        items, unreadable, total, recognised = self._list(responses)
        return (recognised and not items and not unreadable and total == 0
                and not _nodes(root, self.SELECTORS["card"]) and bool(_nodes(root, self.SELECTORS["list_empty"])))

    def has_more(self, root, responses=()):
        """Whether the list response's total (Count) is above the jobs read so far.

        The page's "没有更多了~" is not read: it shows under the first 20 jobs of a longer list.
        """
        items, _, total, recognised = self._list(responses)
        return len(items) < total if recognised else None

    def parse_detail(self, root, responses=()) -> dict:
        title, code = split_job_code(_text(root, self.SELECTORS["detail_title"]))
        tags = [htmltext.text(node) for node in _nodes(root, self.SELECTORS["detail_tags"]) if htmltext.text(node)]
        places, kinds = self._sort_tags(tags)
        sections, complete = [], True
        for block in _nodes(root, self.SELECTORS["detail_sections"]):
            heading = _text(block, self.SELECTORS["section_title"])
            content = _text(block, self.SELECTORS["section_content"], keep_newlines=True)
            if not heading:
                continue
            if not content or placeholder_description(content):
                complete = False  # a section still loading: not a complete JD
                continue
            sections.append(f"{heading}\n{content}")
        return {"title": title, "job_code": code, "salary": _text(root, self.SELECTORS["detail_salary"]),
                "places": places, "kinds": kinds, "published": _day(_text(root, self.SELECTORS["detail_date"])),
                "description": "\n".join(sections) if sections and complete else ""}


# -- the legacy portal ------------------------------------------------------------------------

class LegacyPortal(_Portal):
    PORTAL = "legacy"
    PAGINATION = "url"
    SELECTORS = {
        "card": ["table.listtable a[href*=zpdetail]"],
        "rows": ["table.listtable tr"],
        "count": [".tablenote"],  # 共N条记录
        "no_results": [".zx_nojob", ".txtNoResut"],  # 没有搜索到相关应聘职位。 in the table
        "pager": [".tablefooter"],
        # A job's page: its own block (the page also has a search form with 工作地点：), the title
        # followed by an apply status such as (未申请), "label：" / value pairs (li.ntitle and
        # li.nvalue, then pairs of p), and the sections as a heading p followed by a content p.
        "detail_block": [".positiondetail-simple", "[class*=positiondetail]"],
        "detail_title": [".xiangqingtitle"],
        "apply_status": ["[class*=applyStatus]"],
    }
    LIST_READY = ["table.listtable", ".tablenote"] + _BLOCKED + _LOGIN
    DETAIL_READY = [".xiangqingtitle", ".xiangqingtext"] + _BLOCKED + _LOGIN
    _DETAIL_PATH = re.compile(r"/zpdetail/([0-9]{1,20})/?")
    _LABELS = {"places": ("工作地点", "工作城市", "工作地址"), "salary": ("薪资范围", "薪资", "薪酬", "月薪"),
               "published": ("发布时间", "发布日期", "更新时间"), "kinds": ("工作性质", "职位性质", "工作类型")}
    _FACT = re.compile(r"^(?P<label>[一-鿿]{2,6})\s*[:：]\s*(?P<value>.*)$", re.S)

    def search_url(self, query: str, city_code: str, page: int = 1) -> str:
        params = [("r", LEGACY_CHANNEL[self.channel]), ("c", city_code)]
        if query:
            params.append(("k", query))
        if page > 1:
            params.append(("PageIndex", str(page)))
        return f"{self.origin}/search?{urlencode(params)}"

    def _id_from(self, parts):
        match = self._DETAIL_PATH.fullmatch(parts.path) if parts else None
        return self._scoped(match.group(1)) if match else None

    def canonical_url(self, job_id: str) -> str:
        native = self._native(job_id)
        if not _LEGACY_ID.fullmatch(native):
            raise ValueError(f"not a legacy job id: {job_id!r}")
        return f"{self.origin}/zpdetail/{native}"

    def page_problem(self, url, title, root, status=None):
        problem = self._common_problem(url, title, root, status)
        if problem:
            return problem
        path = self._parts(url).path
        if path.rstrip("/") != "/search" and not self._DETAIL_PATH.fullmatch(path):
            return "changed", "页面离开了门户公开的职位搜索和详情路径"
        return None

    def parse_cards(self, root, page_url: str):
        cards, unreadable = [], 0
        for row in _nodes(root, self.SELECTORS["rows"]):
            links = [node for node in htmltext.select(row, "a[href*=zpdetail]") if _visible(node)]
            if not links:
                continue
            cells = [node for node in row.children if isinstance(node, htmltext.Node) and node.tag == "td"]
            job_id = self.job_id_from_url(urljoin(page_url, links[0].get("href", "")))
            name = (links[0].get("title") or htmltext.text(links[0])).strip()
            if job_id is None or not name:
                unreadable += 1
                continue
            title, code = split_job_code(name)
            texts = [htmltext.text(cell) for cell in cells]
            extra = {"tenant": self.tenant.subdomain, "channel": self.channel}
            if code:
                extra["job_code"] = code
            if len(texts) >= 4 and _day(texts[3]):
                extra["list_published"] = _day(texts[3])
            cards.append({"id": job_id, "href": self.canonical_url(job_id), "title": title, "salary": "",
                          "location": texts[2] if len(texts) >= 3 else "", "extra": extra})
        return cards, unreadable

    def list_is_empty(self, root) -> bool:
        """Only the portal's own "no results": no job link, and 共0条 or its no-results box; never a
        page whose count says it has jobs (rows not recognised are not an empty result)."""
        if _nodes(root, self.SELECTORS["card"]):
            return False
        counts = [int(match.group(1)) for node in _nodes(root, self.SELECTORS["count"])
                  for match in [re.search(r"共\s*([0-9]+)\s*条", htmltext.text(node))] if match]
        if any(counts):
            return False
        return 0 in counts or bool(_nodes(root, self.SELECTORS["no_results"]))

    def has_more(self, root):
        pager = _text(root, self.SELECTORS["pager"])
        match = re.search(r"第\s*([0-9]+)\s*/\s*([0-9]+)\s*页", pager)
        if match:
            return int(match.group(1)) < int(match.group(2))
        return any(htmltext.text(node) == "下一页" and node.get("href") for node in htmltext.select(root, "a"))

    def parse_detail(self, root) -> dict:
        found = _nodes(root, self.SELECTORS["detail_block"])
        if not found:
            return {"title": "", "job_code": None, "salary": "", "places": [], "kinds": [], "published": None,
                    "description": ""}
        block = found[0]
        title, code = split_job_code(self._title(block))
        sections, complete = [], True
        for node in block.iter():
            heading = _own_text(node).strip(_HEADING_TRIM)
            if heading not in _SECTION_HEADINGS or not _visible(node) or len(htmltext.text(node)) > len(heading) + 4:
                continue
            content = self._section_content(node, block)
            if not content or placeholder_description(content):
                complete = False
                continue
            sections.append(f"{heading}\n{content}")
        facts = self._facts(block)
        return {"title": title, "job_code": code, "salary": facts["salary"], "places": facts["places"],
                "kinds": facts["kinds"], "published": _day(facts["published"]),
                "description": "\n".join(sections) if sections and complete else ""}

    def _title(self, block) -> str:
        """The job's name, without the apply status (未申请) that follows it."""
        node = next(iter(_nodes(block, self.SELECTORS["detail_title"])), None)
        if node is None:
            return ""
        title = htmltext.text(node)
        for status in _nodes(node, self.SELECTORS["apply_status"]):
            status_text = htmltext.text(status)
            if status_text and title.endswith(status_text):
                title = title[:-len(status_text)]
        return _APPLY_STATUS.sub("", title).strip()

    @classmethod
    def _label(cls, node):
        """The text of node when it is a label on its own (a heading or a "label："), else None."""
        own = _own_text(node)
        heading = own.strip(_HEADING_TRIM)
        if heading in _SECTION_HEADINGS:
            return heading
        match = cls._FACT.match(own)
        return match.group("label") if match and not match.group("value").strip() else None

    @classmethod
    def _section_content(cls, heading, block) -> str:
        """The text after a heading, up to the next heading or label: its later siblings, else its
        parent's, never beyond the job's block."""
        node = heading
        while node is not block and node.parent is not None:
            siblings = node.parent.children
            after = siblings[siblings.index(node) + 1:]
            pieces = []
            for sibling in after:
                if isinstance(sibling, str):
                    pieces.append(sibling.strip())
                    continue
                if cls._label(sibling):
                    break
                if _visible(sibling):
                    pieces.append(htmltext.text(sibling, keep_newlines=True))
            text = "\n".join(piece for piece in pieces if piece)
            if text:
                return text
            node = node.parent
        return ""

    def _facts(self, block) -> dict:
        """The first value of each fact in the job's block: a "label：" element followed by its
        value's element (li.ntitle / li.nvalue, or two p), or "label：value" in one element."""
        facts = {"places": [], "salary": "", "published": "", "kinds": []}
        wanted = {label: key for key, labels in self._LABELS.items() for label in labels}
        for node in block.iter():
            if not isinstance(node, htmltext.Node) or not _visible(node):
                continue
            match = self._FACT.match(_own_text(node))
            if not match or match.group("label") not in wanted:
                continue
            key, value = wanted[match.group("label")], match.group("value").strip()
            if not value:
                siblings = node.parent.children if node.parent is not None else []
                following = [child for child in siblings[siblings.index(node) + 1:]
                             if not isinstance(child, str) or child.strip()]
                nxt = following[0] if following else None
                if isinstance(nxt, str):
                    value = nxt.strip()
                elif nxt is not None and _visible(nxt) and not self._label(nxt):
                    value = htmltext.text(nxt)
            value = value[:60]
            if not value or facts[key]:
                continue
            facts[key] = [value] if key in ("places", "kinds") else value
        return facts
