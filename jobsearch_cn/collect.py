"""collect: read job postings from a job site into the inbox (docs/cn/collect.md).

One run: open the search results in a tab of its own (in a headless Chrome started for the run,
or with --cdp in a dedicated Chrome), read the job cards (scrolling or paging for
more up to the page limit), open each new job's detail page by the link its card carries, and
write one JSON file per job into <data>/inbox/<site>/<batch>/ in the inbox format that the batch
screening reads (jobsearch_cn.inbox/1, docs/cn/screen.md §2). Then report what was saved, what was
skipped and where the run stopped.

The ground rules are enforced here, not left to the caller:

* Read only. The tab is only navigated and scrolled. Nothing is clicked or typed, so no
  message, application, follow or favourite is ever sent.
* Slow. A random 4-9 s pause before every navigation and every scroll after the first; at most
  MAX_JOBS_CAP detail pages and MAX_PAGES_CAP list loads per run.
* Stop, don't fight. A security check, captcha, sign-in page, HTTP 403/429 (on the page or on a
  list or data request of its own tab), browser error, or a page whose structure is not
  recognised (a blank later result page included) ends the run at once. What was saved stays
  saved; the user deals with it and runs the command again. Nothing is retried.
* Resume without reopening. A job id already in any batch of the inbox, or in the job store, is
  skipped without opening its page.

Everything that depends on one site's pages is in that site's rules module , passed in
as Options.site. A site module has these names:

* SITE (the inbox folder and the record's site, one of schema.SITES), NAME (for messages),
  optional SOURCE_NAME (default batch prefix) and COLLECTOR (extra.collector override).
* CITY_CODES: city name -> the code its search takes, with CITY_CODE (the pattern a --city-code
  must match) and CITY_CODE_HELP (the message when it does not); or None when the search takes
  the city's name itself.
* PAGINATION ("scroll": the list grows as it is scrolled; "url": search_url takes a page
  number), SELECTORS["card"], LIST_READY and DETAIL_READY (the selectors a page is ready on).
* search_url(query, city_code, page), job_id_from_url(url), canonical_url(job_id),
  parse_cards(root, page_url) -> (cards, unreadable), list_is_empty(root),
  page_problem(url, title, root, status) -> None or ("blocked" | "login" | "changed", reason),
  is_closed(root), parse_detail(root) -> fields with title and description,
  detail_text(fields), same_job(card_title, detail_title), location_matches(location, city).
  Optional known_job_id_from_url(url) recognises legacy stored URLs for deduplication
  without relaxing the URLs accepted for navigation.
* Optional, for a site that needs them:
  - CAPTURE: compiled patterns for the paths of the page's own data requests (xhr/fetch to the
    same origin) whose responses the site reads, for pages whose cards carry no link of their own.
    The tab keeps those responses as they arrive (browser.Tab.capture; it never sends a request
    itself), and page_problem, parse_cards, list_is_empty, has_more, is_closed and parse_detail
    then also get responses=(Response, ...) as a keyword.
  - has_more(root) -> True, False or None: whether the list goes on after this load. False ends
    that search without another load. True makes a load that brings no new card an empty one,
    and EMPTY_LOADS of those in a row stop the run (page changed).
  - MAX_JOBS_CAP / MAX_PAGES_CAP (lower limits than the framework's) and DEFAULT_MAX_JOBS /
    DEFAULT_MAX_PAGES; WHOLE_LIST = True when a search may be "" and read the whole list.
  - a card's "extra": facts from the list the record keeps in its extra.

A run reads one list (make_options) or several (make_search_options): each Search is a search
term, a city and its code, and the rules that read it, so one run can cover a site's channels,
cities and keywords with one pacer, one page and detail budget, one dedup and one batch.

Standard library only. The browser is behind a small interface - open(url, ready) and
load_more(item_selectors, ready), each returning a Snapshot, close(), and headless (True when
the user cannot see the browser) - implemented with Playwright in browser.py and faked in the
tests. The live tab also implements check_before_action(callback): after a page passes its
check, the callback rechecks it just before navigating or scrolling, including responses
delivered during the pacing pause. A problem raises _Stop before that action can happen.
"""

import json
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jobsearch_cn import collect_diagnostics, htmltext, schema, store
from jobsearch_cn.content import placeholder_description

INBOX_FORMAT = "jobsearch_cn.inbox/1"
DELAY_RANGE = (4.0, 9.0)
DEFAULT_MAX_JOBS = 30
MAX_JOBS_CAP = 50
DEFAULT_MAX_PAGES = 3
MAX_PAGES_CAP = 10
EMPTY_LOADS = 2  # loads in a row that bring no new card while the site says there is more
MAX_QUERY = 50
MAX_INBOX_FILE = 1_000_000
BATCH_NAME = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,63}")
CITY_NAME = re.compile(r"[\u4e00-\u9fff]{2,10}")

EXIT_DONE, EXIT_NEEDS_USER, EXIT_PAGE_CHANGED = 0, 3, 4
DENIED_STATUSES = (403, 429)  # the site refuses or rate-limits: stop, whatever the site's rules say
NEEDS_USER = "请在浏览器里处理后重跑"
NEEDS_USER_HEADLESS = "过一段时间（至少几个小时）再重跑，不要马上重试"
SIGN_IN_HEADLESS = "只读取免登录的公开页面；需要登录时停止，不尝试登录"
FINISHED = {"max_jobs": "到了 --max 上限", "max_pages": "到了 --max-pages 上限", "end_of_list": "搜索结果没有更多了",
            "no_results": "这个搜索没有结果"}


class CollectError(Exception):
    """The command line asked for something the collector will not do; nothing was opened."""


class BrowserError(Exception):
    """The browser failed while the run was going: the tab was closed, a page timed out, ..."""


@dataclass(frozen=True)
class Response:
    """A data response the page itself received, kept for a site that reads it (CAPTURE)."""

    url: str
    status: int
    request: str | None = None  # the body the page sent with the request, as text
    body: str | None = None  # the response body as text; None when it could not be read


@dataclass
class Snapshot:
    """A rendered page as the browser shows it: final address, title, serialised DOM, HTTP status,
    and the page's own data responses for a site that reads them (CAPTURE)."""

    url: str
    title: str
    html: str
    status: int | None = None
    responses: tuple = ()


@dataclass
class Search:
    """One list a run reads: a search term ("" for the whole list) in one city, read by site's rules."""

    query: str
    city: str
    city_code: str
    site: object = None
    label: str = ""


@dataclass
class Options:
    query: str
    city: str
    city_code: str
    max_jobs: int = DEFAULT_MAX_JOBS
    max_pages: int = DEFAULT_MAX_PAGES
    batch: str | None = None
    site: object = None
    searches: tuple = ()  # several lists (make_search_options); empty: the one search above
    diagnostics: bool = False  # save an existing structure-stop snapshot locally, only when requested


def make_options(query, city=None, city_code=None, max_jobs=DEFAULT_MAX_JOBS, max_pages=DEFAULT_MAX_PAGES,
                 batch=None, site=None, diagnostics=False) -> Options:
    """Options checked against the limits; CollectError names the first problem.

    site is the site's rules module . Where its search takes the city's name
    (CITY_CODES is None), the name is the city code and there is no --city-code.
    """
    if site is None:
        raise CollectError("没有启用采集适配器；请配置本地个人模块（docs/cn/collect.md）")
    if getattr(site, "OFFLINE_ONLY", False):
        raise CollectError(getattr(site, "DISABLED_REASON", "这个适配器只支持离线解析"))
    query = (query or "").strip()
    if not query or len(query) > MAX_QUERY:
        raise CollectError(f"--query 要写搜索词，最多 {MAX_QUERY} 个字")
    city = (city or "").strip()
    if site.CITY_CODES is None:
        if city_code:
            raise CollectError("这个网站按城市名搜索，不用 --city-code")
        if not CITY_NAME.fullmatch(city):
            raise CollectError("--city 要写城市名，例如 广州（2 到 10 个汉字）")
        city_code = city
    elif city_code:
        if not site.CITY_CODE.fullmatch(city_code):
            raise CollectError(site.CITY_CODE_HELP)
    elif city in site.CITY_CODES:
        city_code = site.CITY_CODES[city]
    else:
        known = "、".join(site.CITY_CODES)
        raise CollectError(f"不认识城市\"{city}\"。认识的城市：{known}；别的城市用 --city-code 给出城市代码")
    _check_limits(site, max_jobs, max_pages, batch)
    return Options(query=query, city=city, city_code=city_code, max_jobs=max_jobs, max_pages=max_pages, batch=batch,
                   site=site, diagnostics=diagnostics)


def _caps(site) -> tuple:
    """(detail cap, list-load cap): the framework's, or a site's own lower ones."""
    return (min(MAX_JOBS_CAP, getattr(site, "MAX_JOBS_CAP", MAX_JOBS_CAP)),
            min(MAX_PAGES_CAP, getattr(site, "MAX_PAGES_CAP", MAX_PAGES_CAP)))


def _check_limits(site, max_jobs, max_pages, batch) -> None:
    jobs_cap, pages_cap = _caps(site)
    if not 1 <= max_jobs <= jobs_cap:
        raise CollectError(f"--max 要在 1 到 {jobs_cap} 之间：一次只读少量详情页，降低账号被限制的风险")
    if not 1 <= max_pages <= pages_cap:
        raise CollectError(f"--max-pages 要在 1 到 {pages_cap} 之间")
    if batch is not None and not BATCH_NAME.fullmatch(batch):
        raise CollectError("--batch 只能用字母、数字和 . _ -，不能以 . 开头，最多 64 个字符")


def make_search_options(searches, max_jobs=None, max_pages=None, batch=None, diagnostics=False) -> Options:
    """Options for a run over several lists with one page and detail budget; CollectError names the first problem.

    Every Search names its own rules (search.site), all for the same inbox site; the first one's
    caps, defaults, batch prefix and dedup rules hold for the run. max_jobs and max_pages default
    to the site's DEFAULT_MAX_JOBS and DEFAULT_MAX_PAGES (else the framework's).
    """
    searches = tuple(searches)
    site = searches[0].site if searches else None
    if site is None:
        raise CollectError("没有启用采集适配器；请配置本地个人模块（docs/cn/collect.md）")
    if getattr(site, "OFFLINE_ONLY", False):
        raise CollectError(getattr(site, "DISABLED_REASON", "这个适配器只支持离线解析"))
    for search in searches:
        if getattr(search.site, "SITE", None) != site.SITE:
            raise CollectError("一次采集只能写进同一个来源的收件夹")
        if not isinstance(search.query, str) or len(search.query) > MAX_QUERY or search.query != search.query.strip():
            raise CollectError(f"搜索词最多 {MAX_QUERY} 个字，前后不能有空格")
        if not search.query and not getattr(search.site, "WHOLE_LIST", False):
            raise CollectError(f"--query 要写搜索词，最多 {MAX_QUERY} 个字")
        if not search.city_code:
            raise CollectError(f"不知道城市“{search.city}”的代码")
    max_jobs = getattr(site, "DEFAULT_MAX_JOBS", DEFAULT_MAX_JOBS) if max_jobs is None else max_jobs
    max_pages = getattr(site, "DEFAULT_MAX_PAGES", DEFAULT_MAX_PAGES) if max_pages is None else max_pages
    _check_limits(site, max_jobs, max_pages, batch)
    return Options(query="", city="", city_code="", max_jobs=max_jobs, max_pages=max_pages, batch=batch, site=site,
                   searches=searches, diagnostics=diagnostics)


def _job_ids_in(record, site=None) -> set:
    found = set()
    if isinstance(record, dict):
        source = record.get("source") if isinstance(record.get("source"), dict) else record
        if source.get("site", site.SITE) == site.SITE and schema.site_job_id_allowed(site.SITE, source.get("site_job_id")):
            found.add(source["site_job_id"])
        known_id = getattr(site, "known_job_id_from_url", site.job_id_from_url)
        job_id = known_id(source.get("url"))
        if job_id:
            found.add(job_id)
    return found


def known_job_ids(data_root: Path, site=None) -> tuple:
    """(ids, warnings): the site's job ids already collected into any inbox batch or stored as jobs."""
    ids, warnings = set(), []
    inbox = Path(data_root) / "inbox" / site.SITE
    for path in sorted(inbox.glob("*/*.json")) if inbox.is_dir() else []:
        if path.name.startswith((".", "~")) or path.is_symlink():
            continue
        try:
            if path.stat().st_size > MAX_INBOX_FILE:
                continue
            ids |= _job_ids_in(json.loads(path.read_text(encoding="utf-8-sig")), site)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            warnings.append(f"{path.relative_to(inbox).as_posix()}: unreadable, its job is not counted as collected")
    records, store_warnings = store.Store(data_root).all()
    for record in records:
        ids |= _job_ids_in(record, site)
    return ids, warnings + store_warnings


def inbox_record(*, text: str, fetched_at: str, job_id: str, extra: dict, site=None) -> dict:
    """One inbox file's content (docs/cn/screen.md §2.2): the job's text plus where and when it was read."""
    record = {"format": INBOX_FORMAT, "site": site.SITE, "fetched_at": fetched_at, "text": text,
              "url": site.canonical_url(job_id), "extra": extra}
    if schema.site_job_id_allowed(site.SITE, job_id):
        record["site_job_id"] = job_id  # a job board's id, or an ats id scoped by platform and tenant
    elif schema.is_site_job_id(job_id):
        # "official" covers many companies: only the full recognised URL scopes its id.
        record["extra"] = dict(extra, site_job_id=job_id)
    return record


class _Pacer:
    """The pause before every browser action except the first."""

    def __init__(self, sleep, uniform):
        self._sleep, self._uniform, self._started = sleep, uniform, False

    def before_action(self) -> None:
        if self._started:
            self._sleep(self._uniform(*DELAY_RANGE))
        self._started = True


class _Stop(Exception):
    def __init__(self, status: str, reason: str, advice: str | None = None, *, snapshot=None, phase=None):
        super().__init__(reason)
        self.status, self.reason, self.advice = status, reason, advice
        self.snapshot, self.phase = snapshot, phase


def _now() -> datetime:
    return datetime.now().astimezone()


class _Run:
    def __init__(self, tab, options: Options, data_root: Path, *, sleep, uniform, clock):
        self.tab, self.options, self.data_root, self.clock = tab, options, Path(data_root), clock
        self.site = site = options.site
        self.searches = options.searches or (Search(options.query, options.city, options.city_code, site),)
        self.capture = bool(getattr(site, "CAPTURE", None))
        if self.capture:
            tab.capture(site.CAPTURE)  # keep the page's own data responses this site reads
        self.headless = getattr(tab, "headless", False)  # a browser the user cannot see or act in
        self.pacer = _Pacer(sleep, uniform)
        started = clock()
        prefix = f"{site.SOURCE_NAME}-" if hasattr(site, "SOURCE_NAME") else ""
        self.batch = options.batch or prefix + started.strftime("%Y%m%d-%H%M%S")
        self.batch_dir = None
        self.unreadable = 0
        self.loads = 0
        self.known, self.warnings = known_job_ids(self.data_root, site)
        several = bool(options.searches)
        self.summary = {
            "site": site.SITE, "query": None if several else options.query, "city": None if several else options.city,
            "city_code": None if several else options.city_code,
            "batch": self.batch, "batch_dir": None, "status": "done", "finished": None, "message": None,
            "stopped_at": None, "saved": 0, "skipped_known": 0, "closed": 0, "failed": [], "list_loads": 0,
            "cards_seen": 0, "files": [], "warnings": self.warnings,
        }
        if options.diagnostics:
            self.summary["diagnostics"] = {"status": "not_applicable"}
        if several:
            self.summary["searches"] = [
                {"label": search.label, "query": search.query, "city": search.city, "city_code": search.city_code,
                 "list_loads": 0, "cards_seen": 0, "finished": "not_run"} for search in self.searches]

    # -- browser actions -------------------------------------------------------------------
    def _act(self, action, *args) -> Snapshot:
        self.pacer.before_action()
        try:
            return action(*args)
        except BrowserError as exc:
            raise _Stop("needs_user", f"浏览器出错：{exc}") from None

    def _kw(self, snapshot: Snapshot) -> dict:
        """What a site that reads the page's own data responses gets besides the DOM."""
        return {"responses": tuple(snapshot.responses)} if self.capture else {}

    def _check(self, snapshot: Snapshot, root, site, phase) -> None:
        if snapshot.status in DENIED_STATUSES:
            raise _Stop("needs_user", f"网站返回 HTTP {snapshot.status}")
        problem = site.page_problem(snapshot.url, snapshot.title, root, snapshot.status, **self._kw(snapshot))
        if problem:
            kind, reason = problem
            if kind == "blocked":
                raise _Stop("needs_user", reason)
            if kind == "changed":  # the page is not what the rules expect: not a block, not a sign-in
                raise _Stop("page_changed", reason, snapshot=snapshot, phase=phase)
            if self.headless:
                raise _Stop("needs_user", f"{reason}：{site.NAME}要登录才能看", SIGN_IN_HEADLESS)
            raise _Stop("needs_user", reason, SIGN_IN_HEADLESS)
        if hasattr(self.tab, "check_before_action"):
            self.tab.check_before_action(
                lambda current: self._check(current, htmltext.parse(current.html), site, phase))

    # -- list phase --------------------------------------------------------------------------
    def _read_list(self, snapshot: Snapshot, first: bool, search: Search):
        """(cards, more): None for an explicitly empty first page; more is the site's has_more, if it has one."""
        site, kw = search.site, self._kw(snapshot)
        root = htmltext.parse(snapshot.html)
        self._check(snapshot, root, site, "list")
        cards, unreadable = site.parse_cards(root, snapshot.url, **kw)
        more = site.has_more(root, **kw) if hasattr(site, "has_more") else None
        if not cards:
            # No cards at all is the end only where the site says so (its "no results" box). A
            # blank or unknown later page is not the end of the list: the page has changed, or
            # the site stopped serving it.
            if site.list_is_empty(root, **kw):
                if more is True:
                    return [], True  # a recognised empty load while the site's total says more
                return (None if first else []), False
            raise _Stop("page_changed", "搜索结果页上找不到岗位卡片或卡片里的详情链接，页面结构可能变了",
                        snapshot=snapshot, phase="list")
        # A list that grows by scrolling shows the same odd cards (ads, say) again on every load.
        self.unreadable = max(self.unreadable, unreadable)
        return cards, more

    def _load_list(self, search: Search, number: int, entry) -> Snapshot:
        self.loads += 1
        where = f"{search.label}的" if search.label else ""
        self.summary["stopped_at"] = f"{where}搜索结果第 {number} 次加载"
        self.summary["list_loads"] = self.loads
        if entry is not None:
            entry["list_loads"] += 1
        site = search.site
        if number == 1 or site.PAGINATION == "url":
            return self._act(self.tab.open, site.search_url(search.query, search.city_code, number), site.LIST_READY)
        return self._act(self.tab.load_more, site.SELECTORS["card"], site.LIST_READY)

    def _search(self, search: Search, seen: set, candidates: list, entry) -> str:
        """Read one search's list into candidates; returns how it ended (a FINISHED key)."""
        options, number, empty = self.options, 1, 0
        search_seen = set()  # another search's duplicates still count as progress through this list
        snapshot = self._load_list(search, 1, entry)
        cards, more = self._read_list(snapshot, True, search)
        if cards is None:
            return "no_results"
        while True:
            new = 0
            page_new = {card["id"] for card in cards} - search_seen
            search_seen.update(page_new)
            for card in cards:
                if card["id"] in seen:
                    continue
                seen.add(card["id"])
                new += 1
                self.summary["cards_seen"] += 1
                if card["id"] in self.known:
                    self.summary["skipped_known"] += 1
                else:
                    candidates.append((card, search))
            if entry is not None:
                entry["cards_seen"] += new
            if (number > 1 or not cards) and not page_new:
                if more is not True:
                    return "end_of_list"
                empty += 1  # the site says there is more, yet this load brought nothing new
                if empty >= EMPTY_LOADS:
                    raise _Stop("page_changed", f"连续 {EMPTY_LOADS} 次加载都没有新岗位，页面却显示还有更多："
                                                "翻页方式可能变了，或网站不再给出后面的结果",
                                snapshot=snapshot, phase="list")
            else:
                empty = 0
            if len(candidates) >= options.max_jobs:
                return "max_jobs"
            if more is False:
                return "end_of_list"
            if self.loads >= options.max_pages:
                return "max_pages"
            number += 1
            snapshot = self._load_list(search, number, entry)
            cards, more = self._read_list(snapshot, False, search)

    def collect_cards(self) -> list:
        """The new jobs to open, in list order, at most max_jobs of them, each with the search that found it."""
        options, seen, candidates, outcomes = self.options, set(), [], []
        entries = self.summary.get("searches") or [None] * len(self.searches)
        for search, entry in zip(self.searches, entries):
            if len(candidates) >= options.max_jobs or self.loads >= options.max_pages:
                outcomes.append("not_run")
                continue
            if entry is not None:
                entry["finished"] = "stopped"
            outcome = self._search(search, seen, candidates, entry)
            outcomes.append(outcome)
            if entry is not None:
                entry["finished"] = outcome
        if len(candidates) >= options.max_jobs:
            pass  # run() reports max_jobs
        elif "max_pages" in outcomes or "not_run" in outcomes:
            self.summary["finished"] = "max_pages"
        elif all(outcome == "no_results" for outcome in outcomes):
            self.summary["finished"] = "no_results"
        else:
            self.summary["finished"] = "end_of_list"
        by_city = {}
        for card, search in candidates:
            by_city.setdefault((search.city, search.city_code), []).append((card, search))
        for (city, city_code), found in by_city.items():
            mismatched = [card for card, search in found if not search.site.location_matches(card["location"], city)]
            if len(mismatched) * 2 > len(found):
                self.warnings.append(f"一半以上的岗位不在{city}：城市代码 {city_code} 可能不对")
        if self.unreadable:
            self.warnings.append(f"{self.unreadable} 张卡片里没有认得的岗位详情链接（可能是广告），跳过了")
        return candidates[:options.max_jobs]

    # -- detail phase ------------------------------------------------------------------------
    def _save(self, record: dict, job_id: str) -> None:
        if self.batch_dir is None:
            self.batch_dir = store.safe_dir(self.data_root, "inbox", self.site.SITE, self.batch)
            self.summary["batch_dir"] = str(self.batch_dir)
        name = f"{job_id}.json"
        try:
            store._write_json(self.batch_dir, self.batch_dir / name, record, overwrite=False)
        except FileExistsError:
            raise _Stop("needs_user", f"收件夹已有同名文件 {name}，为保留原件没有写入",
                        "请核对原件或换一个 --batch，不要删除原件后直接重跑") from None
        except OSError as exc:
            raise _Stop("needs_user", f"无法安全写入收件文件 {name}：{exc.strerror or type(exc).__name__}",
                        "请检查收件目录的权限和文件系统是否支持原子创建，已有原件不会被覆盖") from None
        self.summary["files"].append(name)
        self.summary["saved"] += 1
        self.known.add(job_id)

    def read_detail(self, card: dict, search: Search, position: int) -> None:
        site = search.site
        snapshot = self._act(self.tab.open, card["href"], site.DETAIL_READY)
        fetched_at = self.clock().isoformat(timespec="seconds")
        root, kw = htmltext.parse(snapshot.html), self._kw(snapshot)
        self._check(snapshot, root, site, "detail")
        if site.is_closed(root, **kw):
            self.summary["closed"] += 1
            return
        landed = site.job_id_from_url(snapshot.url)
        if landed != card["id"]:
            raise _Stop("page_changed", "打开岗位链接后没有停在这个岗位的详情页上", snapshot=snapshot, phase="detail")
        fields = site.parse_detail(root, **kw)
        if not fields["title"] or not fields["description"] or placeholder_description(fields["description"]):
            raise _Stop("page_changed", "详情页上找不到岗位名称或职位描述，页面结构可能变了",
                        snapshot=snapshot, phase="detail")
        if not site.same_job(card["title"], fields["title"]):
            raise _Stop("page_changed", f"详情页的岗位名\"{fields['title']}\"和列表里的\"{card['title']}\"对不上",
                        snapshot=snapshot, phase="detail")
        text = site.detail_text(fields)
        if len(text) > schema.MAX_RAW_TEXT:
            self.summary["failed"].append({"job": card["id"], "reason": f"岗位文字超过 {schema.MAX_RAW_TEXT} 字，没有保存"})
            return
        extra = {**(card.get("extra") or {}),
                 "collector": getattr(site, "COLLECTOR", f"jobsearch_cn.collect.{site.SITE}/1"),
                 "query": search.query, "city": search.city,
                 "list_title": card["title"], "list_salary": card["salary"], "list_location": card["location"],
                 "position": position}
        self._save(inbox_record(text=text, fetched_at=fetched_at, job_id=card["id"], extra=extra, site=site),
                   card["id"])

    def run(self) -> dict:
        summary = self.summary
        try:
            candidates = self.collect_cards()
            for number, (card, search) in enumerate(candidates, 1):
                summary["stopped_at"] = f"第 {number} 个新岗位（共 {len(candidates)} 个）"
                self.read_detail(card, search, number)
            summary["stopped_at"] = None
            if candidates and len(candidates) >= self.options.max_jobs:
                summary["finished"] = "max_jobs"
            summary["finished"] = summary["finished"] or "end_of_list"
            summary["message"] = (f"{FINISHED[summary['finished']]}：新存 {summary['saved']} 个岗位，"
                                  f"跳过 {summary['skipped_known']} 个以前抓过的")
        except _Stop as stop:
            summary["status"] = stop.status
            if self.options.diagnostics and stop.status == "page_changed":
                summary["diagnostics"] = collect_diagnostics.save(
                    self.data_root, self.batch, stop.snapshot, phase=stop.phase, reason=stop.reason, at=self.clock())
            if stop.advice:
                tail = stop.advice
            elif stop.status != "needs_user":
                tail = "已存的岗位不受影响；页面结构的规则要更新（docs/cn/collect.md）"
            else:
                tail = NEEDS_USER_HEADLESS if self.headless else NEEDS_USER
            summary["message"] = f"{stop.reason}。停在{summary['stopped_at']}，已新存 {summary['saved']} 个岗位。{tail}"
        return summary


def run(tab, options: Options, data_root, *, sleep=time.sleep, uniform=random.uniform, clock=_now) -> dict:
    """Collect one batch through tab. Returns the summary; status is done, needs_user or page_changed."""
    return _Run(tab, options, data_root, sleep=sleep, uniform=uniform, clock=clock).run()


def exit_code(summary: dict) -> int:
    return {"done": EXIT_DONE, "needs_user": EXIT_NEEDS_USER}.get(summary["status"], EXIT_PAGE_CHANGED)
