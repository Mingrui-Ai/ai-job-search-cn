"""Offline application snapshots: checked facts, a small display model and one safely published HTML file."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import re
import secrets
import tempfile

from jobsearch_cn import applications, schema, store


STATUS_LABELS = {
    "drafted": "尚未投出", "applied": "已投出", "interview": "面试中", "offer": "已获 Offer",
    "no_response": "决定不再等待", "hired": "已入职", "rejected": "招聘方拒绝",
    "withdrawn": "已主动撤回", "offer_declined": "已婉拒 Offer",
}
CHANNEL_LABELS = {
    "portal": "招聘平台", "company_site": "公司官网", "email": "邮件", "referral": "内推",
    "campus": "校园招聘", "offline": "线下", "other": "其他渠道", "unknown": "渠道未记录",
}
JOB_LABELS = {"new": "新入库", "skipped": "已跳过", "ranked": "已有评分记录",
              "expired": "已过期", "unreachable": "暂不可达", None: "当前岗位资料未知"}
GROUP_LABELS = {"due": "提醒已到", "unset": "未设提醒", "future": "未来提醒", "other": "其他记录"}
WITHHELD = "含联系信息，未展示"

# Unicode word boundaries/whitespace, but ASCII-only label folding and account values.
# Keep this display-only extension separate from shared application contact warnings.
_CONTACT_PREFIX = r"(?<!\w)(?:(?:联系|添加|请加|加)\s*)?"
_LABELED_CONTACTS = (
    re.compile(_CONTACT_PREFIX + r"(?:微信号?|(?ai:wechat))\s*[:：=]\s*"
               r"[A-Za-z][A-Za-z0-9_-]{5,19}(?![\w.-])"),
    re.compile(_CONTACT_PREFIX + r"(?ai:qq)号?\s*[:：=]\s*[1-9][0-9]{4,11}(?![\w.-])"),
)


@dataclass(frozen=True)
class Progress:
    label: str
    occurred_on: str | None


@dataclass(frozen=True)
class Record:
    application_id: str
    job_id: str
    title: str
    company: str
    job_status: str | None
    status: str
    channel: str
    submitted: bool
    submitted_on: str | None
    reminder: str | None
    group: str
    progress: tuple[Progress, ...]
    milestones: frozenset[str]
    duplicate: bool
    short_id: str


@dataclass(frozen=True)
class Snapshot:
    started_at: str
    completed_at: str
    followup_as_of: str
    records: tuple[Record, ...]
    counts: dict
    statuses: dict
    milestones: dict
    warnings: tuple[str, ...]


def _now() -> datetime:
    return datetime.now(applications.LOCAL_TZ)


def _path(root: Path, *parts: str) -> Path:
    """Check existing components without creating them; the explicitly chosen data root may be a link."""
    current, real_root = root, root.resolve()
    for index, part in enumerate(parts):
        current /= part
        if store._is_link(current) or not store._inside(current, real_root):
            raise applications.StorageError("application report: a source or output path is a link or escapes the data root")
        if index < len(parts) - 1 and current.exists() and not current.is_dir():
            raise applications.StorageError("application report: a source or output parent is not a directory")
    return current


def _job(root: Path, job_id: str, warnings: list) -> dict:
    path = _path(root, "jobs", f"{job_id}.json")
    try:
        if not path.is_file():
            raise ValueError("missing")
        record = json.loads(path.read_bytes().decode("utf-8-sig"))
        if not isinstance(record, dict):
            raise ValueError("object")
        record = schema.upgrade(record)
        if record.get("id") != job_id or schema.validate(record):
            raise ValueError("schema")
        for field in ("title", "company"):
            if isinstance(record[field], str):
                record[field].encode("utf-8")
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, RecursionError):
        warnings.append(f"{job_id}：当前岗位资料缺失或无效，名称和岗位池状态标为未知。")
        return {"title": "岗位名称未记录", "company": "公司未记录", "status": None}
    shown = {"status": record["status"]}
    for field, missing in (("title", "岗位名称未记录"), ("company", "公司未记录")):
        value = record[field]
        labeled_contact = isinstance(value, str) and any(pattern.search(value) for pattern in _LABELED_CONTACTS)
        if applications.contact_warnings(value, field) or labeled_contact:
            shown[field] = WITHHELD
            warnings.append(f"{job_id} 的{'岗位名称' if field == 'title' else '公司名称'}：含联系信息，整字段未展示。")
        else:
            shown[field] = value if isinstance(value, str) and value.strip() else missing
    return shown


def _occurred(at, on) -> str | None:
    try:
        if at is not None:
            return applications._parse_utc(at).astimezone(applications.LOCAL_TZ).date().isoformat()
        return date.fromisoformat(on).isoformat() if on is not None else None
    except (ValueError, TypeError, OverflowError):
        raise applications.ApplicationError("invalid_context", "application report: an occurrence date is invalid") from None


def _short_ids(ids: list[str]) -> dict:
    size = 6
    while len({identity[-size:] for identity in ids}) != len(ids):
        size += 1
    return {identity: identity[-size:] for identity in ids}


def load(data_root) -> Snapshot:
    """Freeze one comparison day, check the SQL batch, and read each current job once inside the read interval."""
    started = _now()
    root = Path(data_root)
    _path(root, "applications", applications.DB_NAME)
    raw = applications.read_report_records(root)
    warnings = []
    jobs = {job_id: _job(root, job_id, warnings) for job_id in sorted({item["job_id"] for item in raw})}
    duplicates = Counter(item["job_id"] for item in raw)
    short = _short_ids([item["application_id"] for item in raw])
    as_of = started.date().isoformat()
    records = []
    for item in raw:
        progress, milestones = [], set()
        for event in item["progress"]:
            kind = event["type"]
            label = {"submitted": "确认投出", "reply_received": "记录了回复"}.get(kind)
            if kind == "status_changed":
                label = STATUS_LABELS[event["status"]]
                if item["submitted"] and event["status"] in ("interview", "offer", "hired"):
                    milestones.add(event["status"])
            progress.append(Progress(label, _occurred(event["occurred_at"], event["occurred_on"])))
        group, reminder = "other", item["next_followup_on"]
        if item["submitted"] and item["status"] in applications.FOLLOWUP_STATUSES:
            group = "unset" if reminder is None else "due" if reminder <= as_of else "future"
        job = jobs[item["job_id"]]
        records.append(Record(item["application_id"], item["job_id"], job["title"], job["company"], job["status"],
                              item["status"], item["channel"], item["submitted"],
                              _occurred(item["submitted_at"], item["submitted_on"]), reminder, group,
                              tuple(progress), frozenset(milestones), duplicates[item["job_id"]] > 1,
                              short[item["application_id"]]))
    order = {name: index for index, name in enumerate(GROUP_LABELS)}
    records.sort(key=lambda r: (order[r.group], (r.reminder if r.group in ("due", "future") else r.submitted_on)
                               or "9999-99-99", r.application_id))
    groups = Counter(r.group for r in records)
    counts = {"records": len(records), "distinct_jobs": len(jobs),
              "submitted": sum(r.submitted for r in records),
              "submitted_jobs": len({r.job_id for r in records if r.submitted}),
              "open_submitted": sum(groups[key] for key in ("due", "unset", "future")),
              "unsubmitted": sum(not r.submitted for r in records),
              "unsubmitted_drafted": sum(not r.submitted and r.status == "drafted" for r in records),
              "unsubmitted_withdrawn": sum(not r.submitted and r.status == "withdrawn" for r in records),
              **{key: groups[key] for key in ("due", "unset", "future")}}
    return Snapshot(started.isoformat(timespec="seconds"), _now().isoformat(timespec="seconds"), as_of,
                    tuple(records), counts, {key: sum(r.status == key for r in records) for key in STATUS_LABELS},
                    {key: sum(key in r.milestones for r in records) for key in ("interview", "offer", "hired")},
                    tuple(warnings))


CSS = """
:root{color-scheme:light;--ink:#172e36;--muted:#52656c;--line:#d4dfe0;--paper:#fff;
--teal:#116b66;--wash:#eef5f4;--amber:#795217}
*{box-sizing:border-box}html{scroll-behavior:auto}body{margin:0;background:#f4f6f3;color:var(--ink);
font:16px/1.65 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
main{max-width:1200px;margin:auto;padding:40px 32px 64px}h1,h2,h3,p{margin:0}h1{font-size:2.5rem;
letter-spacing:-.05em;line-height:1.2}h2{font-size:1.35rem}h3{font-size:1rem}a{color:var(--teal)}
a:focus-visible,summary:focus-visible,.table-wrap:focus-visible{outline:3px solid #a0640a;outline-offset:4px}
.eyebrow{color:var(--teal);font-size:.75rem;letter-spacing:.15em;font-weight:700;margin-bottom:12px}
.heading{display:flex;justify-content:space-between;align-items:start;gap:24px}.stamp{text-align:right;
font-size:.8rem;color:var(--muted);max-width:32rem}.stamp strong{display:block;color:var(--ink)}
nav{display:flex;flex-wrap:wrap;gap:10px 24px;margin:24px 0}nav a{text-underline-offset:5px}
.overview{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));background:var(--ink);color:white;
border-radius:14px;padding:24px;margin:28px 0 36px;gap:24px}.overview strong{display:block;
font-size:2.25rem;line-height:1.2;font-weight:650}.overview small{display:block;color:#d6e3e5;margin-top:8px}
section{margin-top:30px;scroll-margin-top:16px}.section-head{display:flex;align-items:baseline;gap:16px;
justify-content:space-between;flex-wrap:wrap;margin-bottom:16px}.subtle{color:var(--muted);font-size:.875rem}
.next{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.card,.panel{background:var(--paper);
border:1px solid var(--line);border-radius:12px;padding:22px}.card.due{border-top:4px solid var(--amber)}
.card.unset{border-top:4px solid var(--teal)}.card.future{border-top:4px solid #879694}.count{font-size:1.8rem;
font-weight:650;margin-right:8px}.hint{margin:8px 0 12px;color:var(--muted);font-size:.875rem}
.task-list{list-style:none;padding:0;margin:0}.task-list li{padding:12px 0;border-top:1px solid var(--line);
overflow-wrap:anywhere}.task-list strong{display:block}.task-list small{display:block;color:var(--muted)}
.columns{display:grid;grid-template-columns:1fr 1fr;gap:20px}.stats{display:grid;
grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;margin:18px 0 0}.stats div{border-top:1px solid var(--line);
padding-top:10px}.stats dt{font-size:.8rem;color:var(--muted)}.stats dd{margin:2px 0 0;font-size:1.6rem}
.milestones{grid-template-columns:repeat(4,minmax(0,1fr))}.table-wrap{overflow-x:auto;background:white;
border:1px solid var(--line);border-radius:12px}table{border-collapse:collapse;width:100%;table-layout:fixed;
min-width:640px}caption{text-align:left;padding:16px 20px;color:var(--muted);font-size:.875rem}
th,td{padding:16px 18px;vertical-align:top;text-align:left;border-top:1px solid var(--line);overflow-wrap:anywhere}
th{font-size:.8rem;background:var(--wash);font-weight:600}th:first-child{width:35%}th:nth-child(2){width:16%}
th:nth-child(3){width:17%}th:nth-child(4){width:17%}th:nth-child(5){width:15%}td strong{display:block}
.tag{display:inline-block;border-radius:5px;padding:2px 7px;background:var(--wash);font-size:.75rem;
margin-top:6px}.status{font-weight:600}.date{font-variant-numeric:tabular-nums}.empty{color:var(--muted);
padding:18px 0}.table-empty{text-align:center;padding:36px}.identity{font-size:.8rem;color:var(--muted);margin-top:6px}
details{font-size:.875rem}summary{cursor:pointer;color:var(--teal);text-underline-offset:4px}
details ol{padding-left:1.2em;margin:8px 0}details li{margin-top:6px}.scope{border-top:1px solid var(--line);
padding-top:24px;color:var(--muted);font-size:.85rem}.scope p{margin:8px 0}.scope ul{padding-left:1.2em}
.notice{margin-top:20px;padding:12px 16px;background:#fbf3e3;border:1px solid #dcc48f;border-radius:8px}
@media(max-width:850px){main{padding:28px 20px 40px}.heading{display:block}.stamp{text-align:left;margin-top:16px}
.columns{grid-template-columns:1fr}.overview{grid-template-columns:repeat(2,minmax(0,1fr))}
.next{grid-template-columns:1fr}.card{padding:18px}h1{font-size:2rem}.milestones{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media(max-width:380px){main{padding:24px 14px}.stats{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media print{body{background:white;font-size:10pt}main{max-width:none;padding:0}nav{display:none}
.overview{background:white;color:var(--ink);border:1px solid var(--line);padding:12px;margin:16px 0;
grid-template-columns:repeat(4,minmax(0,1fr))}.overview small{color:var(--muted)}.overview strong{font-size:20pt}
.next{grid-template-columns:repeat(3,minmax(0,1fr))}.card,.panel{padding:12px}.columns{grid-template-columns:1fr 1fr}
.table-wrap{overflow:visible}table{min-width:0;font-size:9pt}th,td{padding:8px}thead{display:table-header-group}
tr,.card,.panel{break-inside:avoid}h2,h3{break-after:avoid}section{margin-top:18px}.heading{display:block}
.stamp{text-align:left;margin-top:10px}a{color:inherit;text-decoration:none}}
"""


def _text(value) -> str:
    return escape(str(value), quote=True)


def _date(value: str | None) -> str:
    return _text(value) if value else "发生日期未记录"


def _reminder(record: Record, as_of: str) -> str:
    if record.group == "due":
        days = (date.fromisoformat(as_of) - date.fromisoformat(record.reminder)).days
        return f"{record.reminder} · {'当天到期' if not days else f'已过 {days} 天'}"
    if record.group == "future":
        return f"{record.reminder} · 尚未到期"
    return "未设置 · 非逾期" if record.group == "unset" else "不在开放提醒范围"


def render(snapshot: Snapshot, generated_at: str) -> str:
    """Render only the reduced display model; never receive raw JD or event payloads."""
    count = snapshot.counts
    out = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
           'style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
           '<title>投递看板 · 本地快照</title><style>', CSS, '</style></head><body><main>',
           '<header class="heading"><div><p class="eyebrow">APPLICATIONS / 本地记录</p>',
           '<h1>投递看板</h1></div><div class="stamp"><strong>本次读取的快照 · 非实时</strong>',
           f'<p>读取区间：{_text(snapshot.started_at)}<br>至 {_text(snapshot.completed_at)}</p>',
           f'<p>生成：{_text(generated_at)}<br>提醒比较日：{_text(snapshot.followup_as_of)}（北京时间）</p>',
           '</div></header><nav aria-label="页面导航"><a href="#next">下一步</a>',
           '<a href="#status">当前状态与里程碑</a><a href="#records">全部投递</a>',
           '<a href="#scope">统计口径</a></nav><div class="overview">',
           f'<div><strong>{count["records"]}</strong>条投递记录<small>涉及 {count["distinct_jobs"]} 个不同岗位</small></div>',
           f'<div><strong>{count["submitted"]}</strong>次确认投出<small>涉及 {count["submitted_jobs"]} 个不同岗位</small></div>',
           f'<div><strong>{count["open_submitted"]}</strong>条仍开放<small>已投出 / 面试中 / 已获 Offer</small></div>',
           f'<div><strong>{count["unsubmitted"]}</strong>条尚未投出<small>{count["unsubmitted_drafted"]} 条草稿 · '
           f'{count["unsubmitted_withdrawn"]} 条投出前撤回</small></div></div>',
           '<section id="next"><div class="section-head"><h2>可考虑的下一步</h2>',
           '<p class="subtle">先核对实际进展，再决定是否起草或设置提醒</p></div><div class="next">']
    hints = {"due": "提醒日期已到，可核对进展并决定是否起草跟进。", "unset": "尚未安排提醒，不代表逾期。",
             "future": "提醒日期尚未到，不作为已到期待办。"}
    for group in ("due", "unset", "future"):
        items = [record for record in snapshot.records if record.group == group]
        out.append(f'<article class="card {group}"><h3><span class="count">{len(items)}</span>'
                   f'{GROUP_LABELS[group]}</h3><p class="hint">{hints[group]}</p><ul class="task-list">')
        for record in items:
            out.append(f'<li><strong>{_text(record.title)}</strong>{_text(record.company)}'
                       f'<small>{_text(_reminder(record, snapshot.followup_as_of))}</small>')
            if record.duplicate:
                out.append(f'<small>{CHANNEL_LABELS[record.channel]} · 投递尾号 {_text(record.short_id)}</small>')
            out.append('</li>')
        out.append('</ul>' + ('' if items else '<p class="empty">当前没有这类记录。</p>') + '</article>')
    out += ['</div></section><section id="status" class="columns"><div class="panel"><h2>当前状态</h2>',
            '<p class="subtle">每条记录只计入一个当前状态</p><dl class="stats">']
    for status, label in STATUS_LABELS.items():
        out.append(f'<div><dt>{label}</dt><dd>{snapshot.statuses[status]}</dd></div>')
    out += ['</dl></div><div class="panel"><h2>已记录的里程碑</h2>',
            '<p class="subtle">仍有效的历史记录可以重叠；不推导缺失阶段</p><dl class="stats milestones">']
    for label, number in (("投出", count["submitted"]), ("面试", snapshot.milestones["interview"]),
                          ("Offer", snapshot.milestones["offer"]), ("入职", snapshot.milestones["hired"])):
        out.append(f'<div><dt>{label}</dt><dd>{number}</dd></div>')
    out += ['</dl><p class="hint">例如直接进入 Offer 的记录，不补计一次面试。后续状态变化不会抹去未作废的历史里程碑。</p>',
            '</div></section><section id="records"><div class="section-head"><h2>全部投递</h2>',
            f'<p class="subtle">{count["records"]} 条 · 按提醒安排分组</p></div>',
            '<div class="table-wrap" role="region" aria-label="全部投递，可横向滚动" tabindex="0"><table>',
            '<caption>名称和岗位池状态为本次读取的当前资料；与投出时可能不同。</caption>',
            '<thead><tr><th scope="col">岗位 / 公司</th><th scope="col">投递状态</th>',
            '<th scope="col">投出日期</th><th scope="col">提醒安排</th><th scope="col">有效进展</th></tr></thead><tbody>']
    for record in snapshot.records:
        out.append(f'<tr><td><strong>{_text(record.title)}</strong>{_text(record.company)}<br>'
                   f'<span class="tag">岗位池：{JOB_LABELS[record.job_status]}</span>')
        if record.duplicate:
            out.append(f'<details class="identity"><summary>区分同岗位投递 · {_text(record.short_id)}</summary>'
                       f'{CHANNEL_LABELS[record.channel]}<br>投递编号：{_text(record.application_id)}</details>')
        out.append(f'</td><td class="status">{STATUS_LABELS[record.status]}</td>'
                   f'<td class="date">{_date(record.submitted_on) if record.submitted else "尚未投出"}</td>'
                   f'<td>{GROUP_LABELS[record.group]}<br><span class="subtle">'
                   f'{_text(_reminder(record, snapshot.followup_as_of))}</span></td><td>')
        if record.progress:
            out.append('<details><summary>查看进展</summary><p class="subtle">按记录顺序排列</p><ol>')
            for progress in record.progress:
                out.append(f'<li>{_text(progress.label)}<br>{_date(progress.occurred_on)}</li>')
            out.append('</ol></details>')
        else:
            out.append('<span class="subtle">暂无有效进展记录</span>')
        out.append('</td></tr>')
    if not snapshot.records:
        out.append('<tr><td colspan="5" class="table-empty">尚无投递记录。记录投递后，可重新生成一份看板。</td></tr>')
    out += ['</tbody></table></div></section><footer id="scope" class="scope"><h2>统计口径与资料范围</h2>',
            '<p>投递记录按投递编号计数，岗位按岗位编号去重。已投出仅计仍有效的投出记录；发生日期未记录也计入。</p>',
            '<p>提醒已到、未设和未来三组只覆盖仍开放且确认投出的记录。决定不再等待、主动撤回、婉拒 Offer '
            '及招聘方拒绝分别记录。没有本地回复记录，不代表招聘方没有回复。</p>',
            '<p>投递与进展来自同一读取快照；岗位资料在上述区间逐一读取，不保证与投递记录处于同一瞬间。'
            '岗位过期或暂不可达不改变投递状态；已有评分记录标签不表示评分仍有效。</p>',
            '<p>进展只展示有效事件类型与真实发生日期，按记录顺序排列。未知日期不使用录入时间补齐。</p>',
            '<p>此文件不读取档案、评分、材料或归档正文，不展示备注、回复正文或自定义渠道文字。'
            '标题和公司中的已识别联系信息整字段扣留；检测不保证发现所有敏感内容。</p>',
            '<p>重新打开本文件仍是原快照。需要更新时，重新请求生成投递看板；提醒和投递变更仍须另行预览、确认。</p>']
    if snapshot.warnings:
        out.append('<div class="notice"><strong>资料提示</strong><ul>')
        unavailable = sum(record.job_status is None for record in snapshot.records)
        withheld = sum(record.title == WITHHELD or record.company == WITHHELD for record in snapshot.records)
        if unavailable:
            out.append(f'<li>{unavailable} 条记录的当前岗位资料不可用，名称和岗位池状态暂未知。</li>')
        if withheld:
            out.append(f'<li>{withheld} 条记录的岗位名称或公司含联系信息，相关字段已整段隐藏。</li>')
        out.append('</ul></div>')
    out.append('</footer></main></body></html>\n')
    return ''.join(out)


def _identity(path: Path) -> tuple:
    stat = path.lstat()
    return stat.st_dev, stat.st_ino


def publish(data_root, data: bytes) -> Path:
    """Publish into an exclusively owned directory; cleanup never follows a replaced path or removes a tree."""
    root, directory, owned, directory_id = Path(data_root), None, {}, None
    try:
        parent = store.safe_dir(root, "reports", "applications")
        stamp = _now().astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for _ in range(8):
            candidate = parent / f"{stamp}-{secrets.token_hex(6)}"
            _path(root, "reports", "applications")
            try:
                candidate.mkdir()
            except FileExistsError:
                continue
            directory, directory_id = candidate, _identity(candidate)
            break
        if directory is None:
            raise applications.StorageError("application report: could not allocate a new report directory")
        _path(root, "reports", "applications", directory.name)
        descriptor, name = tempfile.mkstemp(prefix=".tmp-", suffix=".html", dir=directory)
        temporary = Path(name)
        stat = os.fstat(descriptor)
        owned[temporary] = (stat.st_dev, stat.st_ino)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _path(root, "reports", "applications", directory.name, temporary.name)
        if _identity(directory) != directory_id or _identity(temporary) != owned[temporary]:
            raise applications.StorageError("application report: an output path changed while writing")
        if temporary.read_bytes() != data:
            raise applications.StorageError("application report: the complete output did not verify")
        final = _path(root, "reports", "applications", directory.name, "report.html")
        if final.exists():
            raise applications.StorageError("application report: the new output already exists")
        os.replace(temporary, final)
        owned[final] = owned[temporary]
        _path(root, "reports", "applications", directory.name, final.name)
        if _identity(final) != owned[final] or final.read_bytes() != data:
            raise applications.StorageError("application report: the published output did not verify")
        return final
    except (OSError, ValueError, store.StoreError, applications.StorageError) as exc:
        if directory is not None:
            try:
                _path(root, "reports", "applications", directory.name)
                if _identity(directory) == directory_id:
                    for path, identity in owned.items():
                        _path(root, "reports", "applications", directory.name, path.name)
                        if path.exists() and _identity(path) == identity:
                            path.unlink()
                    directory.rmdir()  # only an empty directory owned by this call
            except (OSError, ValueError, applications.StorageError):
                pass  # unsafe or changed objects are left untouched
        if isinstance(exc, applications.StorageError):
            raise
        raise applications.StorageError("application report: could not safely publish the report; no report returned") from None


def generate(data_root) -> dict:
    try:
        snapshot = load(data_root)
        generated_at = _now().isoformat(timespec="seconds")
        content = render(snapshot, generated_at).encode("utf-8")
        path = publish(data_root, content)
    except OSError:
        raise applications.StorageError("application report: a source or output could not be accessed") from None
    return {"report": str(path), "generated_at": generated_at, "snapshot_started_at": snapshot.started_at,
            "snapshot_completed_at": snapshot.completed_at, "followup_as_of": snapshot.followup_as_of,
            **snapshot.counts, "warnings": list(snapshot.warnings)}
