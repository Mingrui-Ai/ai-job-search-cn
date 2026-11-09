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
  page_problem(url, title, root, status) -> None or ("blocked" | "login", reason),
  is_closed(root), parse_detail(root) -> fields with title and description,
  detail_text(fields), same_job(card_title, detail_title), location_matches(location, city).
  Optional known_job_id_from_url(url) recognises legacy stored URLs for deduplication
  without relaxing the URLs accepted for navigation.

Standard library only. The browser is behind a small interface - open(url, ready) and
load_more(item_selectors, ready), each returning a Snapshot, close(), and headless (True when
the user cannot see the browser) - implemented with Playwright in browser.py and faked in the
tests.
"""

import json
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jobsearch_cn import htmltext, schema, store
from jobsearch_cn.content import placeholder_description

INBOX_FORMAT = "jobsearch_cn.inbox/1"
DELAY_RANGE = (4.0, 9.0)
DEFAULT_MAX_JOBS = 30
MAX_JOBS_CAP = 50
DEFAULT_MAX_PAGES = 3
MAX_PAGES_CAP = 10
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


@dataclass
class Snapshot:
    """A rendered page as the browser shows it: final address, title, serialised DOM, HTTP status."""

    url: str
    title: str
    html: str
    status: int | None = None


@dataclass
class Options:
    query: str
    city: str
    city_code: str
    max_jobs: int = DEFAULT_MAX_JOBS
    max_pages: int = DEFAULT_MAX_PAGES
    batch: str | None = None
    site: object = None


def make_options(query, city=None, city_code=None, max_jobs=DEFAULT_MAX_JOBS, max_pages=DEFAULT_MAX_PAGES,
                 batch=None, site=None) -> Options:
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
    if not 1 <= max_jobs <= MAX_JOBS_CAP:
        raise CollectError(f"--max 要在 1 到 {MAX_JOBS_CAP} 之间：一次只读少量详情页，降低账号被限制的风险")
    if not 1 <= max_pages <= MAX_PAGES_CAP:
        raise CollectError(f"--max-pages 要在 1 到 {MAX_PAGES_CAP} 之间")
    if batch is not None and not BATCH_NAME.fullmatch(batch):
        raise CollectError("--batch 只能用字母、数字和 . _ -，不能以 . 开头，最多 64 个字符")
    return Options(query=query, city=city, city_code=city_code, max_jobs=max_jobs, max_pages=max_pages, batch=batch,
                   site=site)


def _job_ids_in(record, site=None) -> set:
    found = set()
    if isinstance(record, dict):
        source = record.get("source") if isinstance(record.get("source"), dict) else record
        if (site.SITE in schema.PORTAL_SITES and source.get("site", site.SITE) == site.SITE
                and isinstance(source.get("site_job_id"), str)):
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
    if schema.is_site_job_id(job_id):
        if site.SITE in schema.PORTAL_SITES:
            record["site_job_id"] = job_id
        else:
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
    def __init__(self, status: str, reason: str, advice: str | None = None):
        super().__init__(reason)
        self.status, self.reason, self.advice = status, reason, advice


def _now() -> datetime:
    return datetime.now().astimezone()


class _Run:
    def __init__(self, tab, options: Options, data_root: Path, *, sleep, uniform, clock):
        self.tab, self.options, self.data_root, self.clock = tab, options, Path(data_root), clock
        self.site = site = options.site
        self.headless = getattr(tab, "headless", False)  # a browser the user cannot see or act in
        self.pacer = _Pacer(sleep, uniform)
        started = clock()
        prefix = f"{site.SOURCE_NAME}-" if hasattr(site, "SOURCE_NAME") else ""
        self.batch = options.batch or prefix + started.strftime("%Y%m%d-%H%M%S")
        self.batch_dir = None
        self.unreadable = 0
        self.known, self.warnings = known_job_ids(self.data_root, site)
        self.summary = {
            "site": site.SITE, "query": options.query, "city": options.city, "city_code": options.city_code,
            "batch": self.batch, "batch_dir": None, "status": "done", "finished": None, "message": None,
            "stopped_at": None, "saved": 0, "skipped_known": 0, "closed": 0, "failed": [], "list_loads": 0,
            "cards_seen": 0, "files": [], "warnings": self.warnings,
        }

    # -- browser actions -------------------------------------------------------------------
    def _act(self, action, *args) -> Snapshot:
        self.pacer.before_action()
        try:
            return action(*args)
        except BrowserError as exc:
            raise _Stop("needs_user", f"浏览器出错：{exc}") from None

    def _check(self, snapshot: Snapshot, root) -> None:
        if snapshot.status in DENIED_STATUSES:
            raise _Stop("needs_user", f"网站返回 HTTP {snapshot.status}")
        problem = self.site.page_problem(snapshot.url, snapshot.title, root, snapshot.status)
        if problem:
            kind, reason = problem
            if kind == "blocked":
                raise _Stop("needs_user", reason)
            if self.headless:
                raise _Stop("needs_user", f"{reason}：{self.site.NAME}要登录才能看", SIGN_IN_HEADLESS)
            raise _Stop("needs_user", reason, SIGN_IN_HEADLESS)

    # -- list phase --------------------------------------------------------------------------
    def _read_list(self, snapshot: Snapshot, first: bool):
        root = htmltext.parse(snapshot.html)
        self._check(snapshot, root)
        cards, unreadable = self.site.parse_cards(root, snapshot.url)
        if not cards:
            # No cards at all is the end only where the site says so (its "no results" box). A
            # blank or unknown later page is not the end of the list: the page has changed, or
            # the site stopped serving it.
            if self.site.list_is_empty(root):
                return None if first else []
            raise _Stop("page_changed", "搜索结果页上找不到岗位卡片或卡片里的详情链接，页面结构可能变了")
        # A list that grows by scrolling shows the same odd cards (ads, say) again on every load.
        self.unreadable = max(self.unreadable, unreadable)
        return cards

    def _load_list(self, number: int) -> Snapshot:
        self.summary["stopped_at"] = f"搜索结果第 {number} 次加载"
        self.summary["list_loads"] = number
        options = self.options
        if number == 1 or self.site.PAGINATION == "url":
            return self._act(self.tab.open, self.site.search_url(options.query, options.city_code, number), self.site.LIST_READY)
        return self._act(self.tab.load_more, self.site.SELECTORS["card"], self.site.LIST_READY)

    def collect_cards(self) -> list:
        """The new jobs to open, in list order, at most max_jobs of them."""
        options, seen, candidates = self.options, set(), []
        cards = self._read_list(self._load_list(1), first=True)
        if cards is None:
            self.summary["finished"] = "no_results"
            return []
        loads = 1
        while True:
            for card in cards:
                if card["id"] in seen:
                    continue
                seen.add(card["id"])
                self.summary["cards_seen"] += 1
                if card["id"] in self.known:
                    self.summary["skipped_known"] += 1
                else:
                    candidates.append(card)
            if len(candidates) >= options.max_jobs:
                break
            if loads >= options.max_pages:
                self.summary["finished"] = "max_pages"
                break
            loads += 1
            cards = self._read_list(self._load_list(loads), first=False)
            if not any(card["id"] not in seen for card in cards):
                self.summary["finished"] = "end_of_list"
                break
        mismatched = [card for card in candidates if not self.site.location_matches(card["location"], options.city)]
        if candidates and len(mismatched) * 2 > len(candidates):
            self.warnings.append(f"一半以上的岗位不在{options.city}：城市代码 {options.city_code} 可能不对")
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

    def read_detail(self, card: dict, position: int) -> None:
        snapshot = self._act(self.tab.open, card["href"], self.site.DETAIL_READY)
        fetched_at = self.clock().isoformat(timespec="seconds")
        root = htmltext.parse(snapshot.html)
        self._check(snapshot, root)
        if self.site.is_closed(root):
            self.summary["closed"] += 1
            return
        landed = self.site.job_id_from_url(snapshot.url)
        if landed != card["id"]:
            raise _Stop("page_changed", "打开岗位链接后没有停在这个岗位的详情页上")
        fields = self.site.parse_detail(root)
        if not fields["title"] or not fields["description"] or placeholder_description(fields["description"]):
            raise _Stop("page_changed", "详情页上找不到岗位名称或职位描述，页面结构可能变了")
        if not self.site.same_job(card["title"], fields["title"]):
            raise _Stop("page_changed", f"详情页的岗位名\"{fields['title']}\"和列表里的\"{card['title']}\"对不上")
        text = self.site.detail_text(fields)
        if len(text) > schema.MAX_RAW_TEXT:
            self.summary["failed"].append({"job": card["id"], "reason": f"岗位文字超过 {schema.MAX_RAW_TEXT} 字，没有保存"})
            return
        extra = {"collector": getattr(self.site, "COLLECTOR", f"jobsearch_cn.collect.{self.site.SITE}/1"),
                 "query": self.options.query, "city": self.options.city,
                 "list_title": card["title"], "list_salary": card["salary"], "list_location": card["location"],
                 "position": position}
        self._save(inbox_record(text=text, fetched_at=fetched_at, job_id=card["id"], extra=extra, site=self.site),
                   card["id"])

    def run(self) -> dict:
        summary = self.summary
        try:
            candidates = self.collect_cards()
            for number, card in enumerate(candidates, 1):
                summary["stopped_at"] = f"第 {number} 个新岗位（共 {len(candidates)} 个）"
                self.read_detail(card, number)
            summary["stopped_at"] = None
            if candidates and len(candidates) >= self.options.max_jobs:
                summary["finished"] = "max_jobs"
            summary["finished"] = summary["finished"] or "end_of_list"
            summary["message"] = (f"{FINISHED[summary['finished']]}：新存 {summary['saved']} 个岗位，"
                                  f"跳过 {summary['skipped_known']} 个以前抓过的")
        except _Stop as stop:
            summary["status"] = stop.status
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
