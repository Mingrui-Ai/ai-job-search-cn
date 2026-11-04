"""collect: read job postings from the user's signed-in browser into the inbox (docs/cn/collect.md).

One run: open the search results in a tab of its own, read the job cards (scrolling for more
up to the page limit), open each new job's detail page by the link its card carries, and write
one JSON file per job into <data>/inbox/boss/<batch>/ in the inbox format that the batch
screening reads (jobsearch_cn.inbox/1, M6-4 design §3). Then report what was saved, what was
skipped and where the run stopped.

The ground rules are enforced here, not left to the caller:

* Read only. The tab is only navigated and scrolled. Nothing is clicked or typed, so no
  message, application, follow or favourite is ever sent.
* Slow. A random 4-9 s pause before every navigation and every scroll after the first; at most
  MAX_JOBS_CAP detail pages and MAX_PAGES_CAP list loads per run.
* Stop, don't fight. A security check, captcha, sign-in page, browser error, or a page whose
  structure is not recognised ends the run at once. What was saved stays saved; the user deals
  with the page in the browser and runs the command again. Nothing is retried.
* Resume without reopening. A job id already in any batch of the inbox, or in the job store, is
  skipped without opening its page.

Standard library only. The browser is behind a small interface - open(url, ready) and
load_more(item_selectors, ready), each returning a Snapshot, and close() - implemented with
Playwright in browser.py and faked in the tests.
"""

import json
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jobsearch_cn import boss, htmltext, schema, store

INBOX_FORMAT = "jobsearch_cn.inbox/1"
COLLECTOR = "jobsearch_cn.collect.boss/1"
DELAY_RANGE = (4.0, 9.0)
DEFAULT_MAX_JOBS = 30
MAX_JOBS_CAP = 50
DEFAULT_MAX_PAGES = 3
MAX_PAGES_CAP = 10
MAX_QUERY = 50
MAX_INBOX_FILE = 1_000_000
SITE_JOB_ID = re.compile(r"[A-Za-z0-9._~-]{1,128}")
BATCH_NAME = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,63}")
CITY_CODE = re.compile(r"\d{9}")

EXIT_DONE, EXIT_NEEDS_USER, EXIT_PAGE_CHANGED = 0, 3, 4
NEEDS_USER = "请在浏览器里处理后重跑"
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


def make_options(query, city=None, city_code=None, max_jobs=DEFAULT_MAX_JOBS, max_pages=DEFAULT_MAX_PAGES,
                 batch=None) -> Options:
    """Options checked against the limits; CollectError names the first problem."""
    query = (query or "").strip()
    if not query or len(query) > MAX_QUERY:
        raise CollectError(f"--query 要写搜索词，最多 {MAX_QUERY} 个字")
    city = (city or "").strip()
    if city_code:
        if not CITY_CODE.fullmatch(city_code):
            raise CollectError("--city-code 是 9 位数字（在网站上选好城市后，地址栏里 city= 后面那一串）")
    elif city in boss.CITY_CODES:
        city_code = boss.CITY_CODES[city]
    else:
        known = "、".join(boss.CITY_CODES)
        raise CollectError(f"不认识城市\"{city}\"。认识的城市：{known}；别的城市用 --city-code 给出城市代码")
    if not 1 <= max_jobs <= MAX_JOBS_CAP:
        raise CollectError(f"--max 要在 1 到 {MAX_JOBS_CAP} 之间：一次只读少量详情页，降低账号被限制的风险")
    if not 1 <= max_pages <= MAX_PAGES_CAP:
        raise CollectError(f"--max-pages 要在 1 到 {MAX_PAGES_CAP} 之间")
    if batch is not None and not BATCH_NAME.fullmatch(batch):
        raise CollectError("--batch 只能用字母、数字和 . _ -，不能以 . 开头，最多 64 个字符")
    return Options(query=query, city=city, city_code=city_code, max_jobs=max_jobs, max_pages=max_pages, batch=batch)


def _job_ids_in(record) -> set:
    found = set()
    if isinstance(record, dict):
        source = record.get("source") if isinstance(record.get("source"), dict) else record
        if source.get("site", boss.SITE) == boss.SITE and isinstance(source.get("site_job_id"), str):
            found.add(source["site_job_id"])
        job_id = boss.job_id_from_url(source.get("url"))
        if job_id:
            found.add(job_id)
    return found


def known_job_ids(data_root: Path) -> tuple:
    """(ids, warnings): the BOSS job ids already collected into any inbox batch or stored as jobs."""
    ids, warnings = set(), []
    inbox = Path(data_root) / "inbox" / boss.SITE
    for path in sorted(inbox.glob("*/*.json")) if inbox.is_dir() else []:
        if path.name.startswith((".", "~")) or path.is_symlink():
            continue
        try:
            if path.stat().st_size > MAX_INBOX_FILE:
                continue
            ids |= _job_ids_in(json.loads(path.read_text(encoding="utf-8-sig")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            warnings.append(f"{path.relative_to(inbox).as_posix()}: unreadable, its job is not counted as collected")
    records, store_warnings = store.Store(data_root).all()
    for record in records:
        ids |= _job_ids_in(record)
    return ids, warnings + store_warnings


def inbox_record(*, text: str, fetched_at: str, job_id: str, extra: dict) -> dict:
    """One inbox file's content (M6-4 design §3.2): the job's text plus where and when it was read."""
    record = {"format": INBOX_FORMAT, "site": boss.SITE, "fetched_at": fetched_at, "text": text,
              "url": boss.canonical_url(job_id), "extra": extra}
    if SITE_JOB_ID.fullmatch(job_id):
        record["site_job_id"] = job_id
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
    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status, self.reason = status, reason


def _now() -> datetime:
    return datetime.now().astimezone()


class _Run:
    def __init__(self, tab, options: Options, data_root: Path, *, sleep, uniform, clock):
        self.tab, self.options, self.data_root, self.clock = tab, options, Path(data_root), clock
        self.pacer = _Pacer(sleep, uniform)
        started = clock()
        self.batch = options.batch or started.strftime("%Y%m%d-%H%M%S")
        self.batch_dir = None
        self.unreadable = 0
        self.known, self.warnings = known_job_ids(self.data_root)
        self.summary = {
            "site": boss.SITE, "query": options.query, "city": options.city, "city_code": options.city_code,
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
        problem = boss.page_problem(snapshot.url, snapshot.title, root, snapshot.status)
        if problem:
            kind, reason = problem
            raise _Stop("needs_user", reason if kind == "blocked" else f"{reason}：请先在这个浏览器里登录 BOSS 直聘")

    # -- list phase --------------------------------------------------------------------------
    def _read_list(self, snapshot: Snapshot, first: bool):
        root = htmltext.parse(snapshot.html)
        self._check(snapshot, root)
        cards, unreadable = boss.parse_cards(root, snapshot.url)
        if not cards:
            if first and boss.list_is_empty(root):
                return None
            if first or unreadable:
                raise _Stop("page_changed", "搜索结果页上找不到岗位卡片或卡片里的详情链接，页面结构可能变了")
        # A list that grows by scrolling shows the same odd cards (ads, say) again on every load.
        self.unreadable = max(self.unreadable, unreadable)
        return cards

    def _load_list(self, number: int) -> Snapshot:
        self.summary["stopped_at"] = f"搜索结果第 {number} 次加载"
        self.summary["list_loads"] = number
        options = self.options
        if number == 1 or boss.PAGINATION == "url":
            return self._act(self.tab.open, boss.search_url(options.query, options.city_code, number), boss.LIST_READY)
        return self._act(self.tab.load_more, boss.SELECTORS["card"], boss.LIST_READY)

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
        mismatched = [card for card in candidates if not boss.location_matches(card["location"], options.city)]
        if candidates and len(mismatched) * 2 > len(candidates):
            self.warnings.append(f"一半以上的岗位不在{options.city}：城市代码 {options.city_code} 可能不对")
        if self.unreadable:
            self.warnings.append(f"{self.unreadable} 张卡片里没有认得的岗位详情链接（可能是广告），跳过了")
        return candidates[:options.max_jobs]

    # -- detail phase ------------------------------------------------------------------------
    def _save(self, record: dict, job_id: str) -> None:
        if self.batch_dir is None:
            self.batch_dir = store.safe_dir(self.data_root, "inbox", boss.SITE, self.batch)
            self.summary["batch_dir"] = str(self.batch_dir)
        name = f"{job_id}.json"
        store._write_json(self.batch_dir, self.batch_dir / name, record)
        self.summary["files"].append(name)
        self.summary["saved"] += 1
        self.known.add(job_id)

    def read_detail(self, card: dict, position: int) -> None:
        snapshot = self._act(self.tab.open, card["href"], boss.DETAIL_READY)
        fetched_at = self.clock().isoformat(timespec="seconds")
        root = htmltext.parse(snapshot.html)
        self._check(snapshot, root)
        if boss.is_closed(root):
            self.summary["closed"] += 1
            return
        landed = boss.job_id_from_url(snapshot.url)
        if landed != card["id"]:
            raise _Stop("page_changed", "打开岗位链接后没有停在这个岗位的详情页上")
        fields = boss.parse_detail(root)
        if not fields["title"] or not fields["description"]:
            raise _Stop("page_changed", "详情页上找不到岗位名称或职位描述，页面结构可能变了")
        if not boss.same_job(card["title"], fields["title"]):
            raise _Stop("page_changed", f"详情页的岗位名\"{fields['title']}\"和列表里的\"{card['title']}\"对不上")
        text = boss.detail_text(fields)
        if len(text) > schema.MAX_RAW_TEXT:
            self.summary["failed"].append({"job": card["id"], "reason": f"岗位文字超过 {schema.MAX_RAW_TEXT} 字，没有保存"})
            return
        extra = {"collector": COLLECTOR, "query": self.options.query, "city": self.options.city,
                 "list_title": card["title"], "list_salary": card["salary"], "list_location": card["location"],
                 "position": position}
        self._save(inbox_record(text=text, fetched_at=fetched_at, job_id=card["id"], extra=extra), card["id"])

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
            tail = NEEDS_USER if stop.status == "needs_user" else "已存的岗位不受影响；页面结构的规则要更新（docs/cn/collect.md）"
            summary["message"] = f"{stop.reason}。停在{summary['stopped_at']}，已新存 {summary['saved']} 个岗位。{tail}"
        return summary


def run(tab, options: Options, data_root, *, sleep=time.sleep, uniform=random.uniform, clock=_now) -> dict:
    """Collect one batch through tab. Returns the summary; status is done, needs_user or page_changed."""
    return _Run(tab, options, data_root, sleep=sleep, uniform=uniform, clock=clock).run()


def exit_code(summary: dict) -> int:
    return {"done": EXIT_DONE, "needs_user": EXIT_NEEDS_USER}.get(summary["status"], EXIT_PAGE_CHANGED)
