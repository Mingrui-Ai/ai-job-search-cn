"""Batch screening (M6-4, docs/cn/screen.md): one inbox batch in, a shortlist out.

An inbox batch is a folder <data dir>/inbox/<site>/<batch>/ that a collector fills with one
JSON file per posting, or a user with .txt files of pasted JDs. check() reads and parses the
files without touching the store, so a collector can test its output. run() saves each
posting through the job store (dedup by the job board's own id, the fingerprint, the URL),
scores with the rules every job of the batch whose match record is missing or stale - what
match score --save does - and lays the batch out as a shortlist: ranked as match list ranks,
one line per job with what to confirm, and the jobs the hard conditions rule out, counted by
condition. No parsing or scoring rule lives here, and nothing reads the network.
"""

import json
from collections import Counter
from datetime import date
from pathlib import Path

from jobsearch_cn import jd_parser, match, report, schema, score, store

FORMAT = "jobsearch_cn.inbox/1"
ITEM_KEYS = ("format", "text", "fetched_at", "url", "site_job_id", "site", "extra")
REQUIRED = ("format", "text", "fetched_at")
MAX_FILE_BYTES = 1_000_000
DEFAULT_TOP = 10
# Statuses the user set to say "not this one": counted, never listed again.
NOT_LISTED = ("skipped", "expired", "unreachable")
_READ = (".json", ".txt")
_ACTION_RANK = {"unchanged": 0, "updated": 1, "created": 2}
LIST_PAGE = "list"
SUMMARY_KEPT = ("a list summary does not replace the text saved for this job, so it did not change; "
                "clip the job's detail page to refresh it")
_UNREAD = (("title", "职位名"), ("company", "公司"), ("cities", "城市"), ("salary", "薪资"))


class BatchError(Exception):
    """The batch cannot be screened: its folder is unreadable or its site unknown."""


class ItemError(Exception):
    """One inbox file is not in the inbox format; the message says why."""


def batch_site(path, site=None) -> str:
    """The batch's site: --site, else the name of the folder holding the batch (inbox/<site>/<batch>/)."""
    if site is not None:
        return site
    name = Path(path).resolve().parent.name
    if name in schema.SITES:
        return name
    raise BatchError(f"cannot tell the batch's site: the folder holding it, {name!r}, is none of "
                     f"{', '.join(schema.SITES)}; put the batch in inbox/<site>/ or pass --site")


def list_files(path):
    """(the .json and .txt files to read, in name order; the entries left alone, with the reason)."""
    try:
        entries = sorted(Path(path).iterdir(), key=lambda entry: entry.name)
    except OSError as exc:
        raise BatchError(f"cannot read the batch folder {path}: {exc.strerror or exc}") from None
    files, ignored = [], []
    for entry in entries:
        name = entry.name
        if name.startswith((".", "~")):
            continue  # still being written (.<name>.tmp, renamed when done), or an editor's lock file
        try:
            if store._is_link(entry):
                ignored.append({"file": name, "reason": "a link or junction; not followed"})
            elif entry.is_dir():
                ignored.append({"file": name + "/", "reason": "a subfolder; only the batch folder itself is read"})
            elif entry.suffix.lower() not in _READ:
                ignored.append({"file": name, "reason": "only .json and .txt files are read"})
            elif entry.stat().st_size > MAX_FILE_BYTES:
                ignored.append({"file": name, "reason": f"larger than {MAX_FILE_BYTES} bytes"})
            else:
                files.append(entry)
        except OSError as exc:
            ignored.append({"file": name, "reason": f"cannot read: {exc.strerror or exc}"})
    return files, ignored


def read_item(data: bytes, site: str) -> dict:
    """An inbox JSON item, checked against the inbox format; raises ItemError naming every problem."""
    try:
        item = json.loads(data.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise ItemError("not UTF-8 text; save it as UTF-8") from None
    except json.JSONDecodeError as exc:
        raise ItemError(f"not valid JSON: {exc}") from None
    if not isinstance(item, dict):
        raise ItemError("must be one JSON object, one posting per file")
    problems = [f"{key}: unknown field (put anything else in extra)" for key in item if key not in ITEM_KEYS]
    problems += [f"{key}: missing" for key in REQUIRED if item.get(key) is None]
    if item.get("format") is not None and item["format"] != FORMAT:
        problems.append(f"format: must be {FORMAT!r}")
    if item.get("text") is not None and not (isinstance(item["text"], str) and item["text"].strip()):
        problems.append("text: must be a non-empty string")
    if item.get("site") is not None and item["site"] != site:
        problems.append(f"site: {item['site']!r} is not the batch's site {site!r}")
    if "extra" in item and not isinstance(item["extra"], dict):
        problems.append("extra: must be a JSON object")
    # The source the job record will hold, checked by the schema's own rules.
    source = {"type": "portal", "site": site, "url": item.get("url"), "imported_at": "2000-01-01T00:00:00+00:00",
              "site_job_id": item.get("site_job_id"), "fetched_at": item.get("fetched_at")}
    errors = []
    schema._check_source(source, errors)
    problems += [error.removeprefix("source.") for error in errors]
    if problems:
        raise ItemError("; ".join(problems))
    return item


def read_file(path: Path, site: str, vocabulary, now=None):
    """(job records, warnings) from one inbox file; raises ItemError."""
    return _read_file(path, site, vocabulary, now)[:2]


def _read_file(path: Path, site: str, vocabulary, now=None):
    """read_file, plus whether the file says it holds only a list page's summary (extra.page, set by a local collector)."""
    summary = False
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ItemError(f"cannot read: {exc.strerror or exc}") from None
    if path.suffix.lower() == ".json":
        item = read_item(data, site)
        summary = item.get("extra", {}).get("page") == LIST_PAGE
        records, warnings = jd_parser.parse_text(
            item["text"], source_type="portal", site=site, url=item.get("url"), now=now, vocabulary=vocabulary,
            single=True, site_job_id=item.get("site_job_id"), fetched_at=item["fetched_at"])
        if records and not item.get("url") and not item.get("site_job_id"):
            warnings.append({"segment": None, "kind": "no_key",
                             "message": "no url and no site_job_id: only the same JD text finds this job again"})
    else:
        try:
            text, warnings = jd_parser.decode(data, path.name)
        except ValueError as exc:
            raise ItemError(str(exc)) from None
        records, more = jd_parser.parse_text(text, source_type="file", site=site, now=now, vocabulary=vocabulary)
        warnings += more
    if not records:
        raise ItemError("; ".join(w["message"] for w in warnings if w["kind"] in ("empty", "too_long"))
                        or "no JD text found")
    return records, [w for w in warnings if w["kind"] != "empty"], summary


def _label(path: Path, number: int, count: int) -> str:
    """The file a job came from; file.txt#2 for the second JD of a .txt holding several."""
    return f"{path.name}#{number}" if count > 1 else path.name


def _keys(record: dict) -> list:
    """What makes two records the same posting, strongest first (store.Store.find_existing)."""
    url = store.normalize_url(record["source"]["url"])
    return [key for key in (("portal", store.portal_key(record["source"])), ("url", url), ("id", record["id"]))
            if key[1] is not None]


def salary_text(salary):
    """The pay as the rules read it, e.g. "150–200 元/天" or "15000–25000 元/月 · 13 薪"; None if not read."""
    if not isinstance(salary, dict):
        return None
    low, high = salary.get("min"), salary.get("max")
    if low is None and high is None:
        return "面议" if salary.get("negotiable") else None
    if low is not None and high is not None and low != high:
        amount = f"{score._plain(low)}–{score._plain(high)}"
    else:
        amount = str(score._plain(low if low is not None else high))
    text = f"{amount} {score._UNIT.get(salary.get('unit'), '')}".strip()
    if salary.get("months"):
        text += f" · {score._plain(salary['months'])} 薪"
    return text


def unread(record: dict) -> list:
    """The fields a shortlist line shows that the rules did not read."""
    return [label for key, label in _UNREAD if not record.get(key)]


def check(path, site: str, vocabulary, now=None) -> dict:
    """jd screen --check: every file read and parsed, nothing stored; duplicates within the batch."""
    files, ignored = list_files(path)
    entries, seen, duplicates, jobs = [], {}, [], 0
    for file in files:
        try:
            records, warnings = read_file(file, site, vocabulary, now)
        except ItemError as exc:
            entries.append({"file": file.name, "ok": False, "reason": str(exc)})
            continue
        found = []
        for number, record in enumerate(records, 1):
            label = _label(file, number, len(records))
            first = next((seen[key] for key in _keys(record) if key in seen), None)
            if first is not None:
                duplicates.append([first, label])
            for key in _keys(record):
                seen.setdefault(key, label)
            found.append({"id": record["id"], "title": record["title"], "company": record["company"],
                          "cities": record["cities"], "salary": salary_text(record["salary"]),
                          "unread": unread(record), "guard": record["guard"]["verdict"]})
        jobs += len(found)
        entries.append({"file": file.name, "ok": True, "type": records[0]["source"]["type"], "jobs": found,
                        "warnings": warnings})
    failed = sum(1 for entry in entries if not entry["ok"])
    return {"batch": {"path": str(path), "site": site, "files": len(files)}, "files": entries,
            "duplicates": duplicates, "ignored": ignored, "ok": len(entries) - failed, "failed": failed, "jobs": jobs}


def reference_date(value=None) -> date:
    """Resolve the local calendar day once per run, rejecting invalid dates before any write."""
    if value is None:
        return date.today()
    errors = []
    schema._check_date(value, "as_of", errors)
    if errors:
        raise BatchError("--as-of: must be a calendar date in YYYY-MM-DD format")
    return date.fromisoformat(value)


def _freshness(job: dict, as_of: date, maximum: int) -> dict:
    """Use only the validated job's publication date, never fetch/import timestamps."""
    published = job.get("published_at")
    age = (as_of - date.fromisoformat(published)).days if published is not None else None
    status = "unknown" if age is None else "future" if age < 0 else "too_old" if age > maximum else "recent"
    return {"published_at": published, "age_days": age, "status": status}


def run(path, site: str, profile: dict, vocabulary, job_store: store.Store, matches: store.MatchStore,
        top: int = DEFAULT_TOP, now=None, as_of=None) -> dict:
    """jd screen: import the batch, score what needs it, and the shortlist (docs/cn/screen.md)."""
    day = reference_date(as_of)
    maximum = profile["target"].get("max_job_age_days")
    if maximum is not None and not (schema._is_int(maximum) and maximum > 0):
        raise BatchError("target.max_job_age_days: must be null or a positive integer")
    files, ignored = list_files(path)
    skipped, warnings, jobs = [], [], {}
    index = job_store.index()
    for file in files:
        try:
            records, file_warnings, summary = _read_file(file, site, vocabulary, now)
        except ItemError as exc:
            skipped.append({"file": file.name, "reason": str(exc)})
            continue
        warnings += [{"file": file.name, **warning} for warning in file_warnings]
        for number, record in enumerate(records, 1):
            label = _label(file, number, len(records))
            existing, same_text = job_store.find_existing(record, index)
            changed = existing is not None and not same_text
            if summary and changed:
                # A list card must not replace the full text of the job it links to (screen.md 3).
                action, stored, changed = "unchanged", existing, False
                warnings.append({"file": label, "kind": "summary_kept", "message": SUMMARY_KEPT})
            else:
                try:
                    action, stored = job_store.save(record, index)
                except store.StoreError as exc:
                    skipped.append({"file": label, "reason": str(exc)})
                    continue
            entry = jobs.get(stored["id"])
            if entry is None:
                jobs[stored["id"]] = {"action": action, "jd_changed": changed, "files": [label]}
                continue
            warnings.append({"file": label, "kind": "duplicate",
                             "message": f"the same posting as {entry['files'][0]}, earlier in this batch"})
            entry["files"].append(label)
            entry["jd_changed"] = entry["jd_changed"] or changed
            if _ACTION_RANK[action] > _ACTION_RANK[entry["action"]]:
                entry["action"] = action

    digest, weights = score.profile_hash(profile), score.weights_of(profile)
    listed, scored, not_listed = [], 0, dict.fromkeys(NOT_LISTED, 0)
    for job_id, entry in jobs.items():
        job = job_store.get(job_id)
        if job.get("status") in NOT_LISTED:
            not_listed[job["status"]] += 1
            continue
        saved = _saved(matches, job_id)
        if saved is None or score.stale_reasons(saved, job, digest, weights):
            saved = score.score_job(job, profile, vocabulary, previous=saved, now=now)
            matches.save(saved)
            scored += 1
        listed.append((job, saved, entry))

    listed.sort(key=lambda item: score.list_key((item[1].get("total") or {}).get("grade"),
                                                 (item[1].get("total") or {}).get("score"), item[0]["id"]))
    short, out, old, gaps = [], [], [], Counter()
    for job, record, entry in listed:
        points, profile_side = confirm_points(job, record, profile)
        gaps.update(profile_side)
        freshness = _freshness(job, day, maximum) if maximum is not None else None
        if (record.get("filter") or {}).get("verdict") == match.INELIGIBLE:
            row = _ruled_out_row(job, record, entry)
            out.append(row)
        elif freshness is not None and freshness["status"] == "too_old":
            reason = f"发布已 {freshness['age_days']} 天，超过你设置的 {maximum} 天"
            row = _row(0, job, record, entry, points)
            del row["rank"]
            row.update(reason=reason, line="- " + "｜".join(_cells(job) + [f"发布时间筛选：{reason}"]))
            old.append(row)
        else:
            if freshness is not None:
                if freshness["status"] == "unknown":
                    points.append("发布时间（JD 没写，需确认是否仍在招）")
                elif freshness["status"] == "future":
                    points.append(f"发布时间（{freshness['published_at']} 晚于参考日期 {day.isoformat()}，需核实）")
            row = _row(len(short) + 1, job, record, entry, points)
            short.append(row)
        if freshness is not None:
            row["freshness"] = freshness
    shown = short if not top else short[:top]
    by_check = Counter(conflict["check"] for row in out for conflict in row["conflicts"])
    order = list(report.CHECKS)
    payload = {
        "batch": {"path": str(path), "site": site, "files": len(files)},
        "summary": [],
        "imported": {action: sum(1 for entry in jobs.values() if entry["action"] == action)
                     for action in ("created", "updated", "unchanged")} | {"skipped": len(skipped)},
        "scored": scored,
        "weights": weights,
        "freshness": {"as_of": day.isoformat(), "max_job_age_days": maximum,
                      "excluded": {"jobs": len(old), "rows": old}},
        "shortlist": {"total": len(short), "shown": len(shown), "rows": shown},
        "ruled_out": {"jobs": len(out),
                      "by_check": [{"check": check, "label": report.CHECKS.get(check, check), "jobs": count}
                                   for check, count in sorted(by_check.items(), key=lambda item: (
                                       -item[1], order.index(item[0]) if item[0] in order else len(order)))],
                      "rows": out},
        "not_listed": not_listed,
        "profile_gaps": [{"check": check, "label": label, "reason": reason, "jobs": count}
                         for (check, label, reason), count in sorted(gaps.items(), key=lambda item: -item[1])],
        "skipped": skipped,
        "ignored": ignored,
        "warnings": warnings,
    }
    payload["summary"] = _summary(payload, len(jobs))
    return payload


def _saved(matches: store.MatchStore, job_id: str):
    try:
        return matches.get(job_id)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None  # an unreadable record is scored afresh, as match score does


def confirm_points(job: dict, record: dict, profile: dict):
    """(what to confirm about this job, short labels; what the profile does not say, as (check, label, reason)).

    The report's 待确认 reading (report.pending): an unknown whose reason says "JD 没写" is checked in the
    JD or asked of HR, one saying "档案没写" is the profile's to fill. The profile's side is the same for
    every job of the batch, so it is returned apart and summed up once. An unknown interview or start date
    is only listed when the interview is in person elsewhere and the profile does not travel (M2-6f): most
    JDs state neither, and the report lists them anyway.
    """
    points, gaps = [], []
    for check in (record.get("filter") or {}).get("checks") or []:
        if check.get("result") != match.UNKNOWN:
            continue
        name, reason = check.get("check"), check.get("reason") or ""
        label = report.CHECKS.get(name, name)
        if name in match.TO_CONFIRM:
            if name == "interview" and "不去外地面试" in reason:
                points.append(f"{label}（只在外地现场面，先问能不能线上）")
            continue
        parts = [part for part in reason.split("；") if part]
        from_jd = [part for part in parts if "JD 没写" in part]
        from_profile = [part for part in parts if "档案没写" in part]
        if from_jd or not from_profile:
            points.append(f"{label}（{'，'.join(from_jd) or reason}）")
        gaps += [(name, label, part) for part in from_profile]
    dimensions, target = record.get("dimensions") or {}, profile.get("target") or {}
    if (dimensions.get("skills") or {}).get("score") is None:
        points.append("技能（JD 没列技能，看原文）")
    if (dimensions.get("direction") or {}).get("score") is None:
        if target.get("directions"):
            points.append("方向（规则判断不了，挑中后让 Agent 补）")
        else:
            gaps.append(("direction", "方向", "档案没写求职方向"))
    salary = dimensions.get("salary") or {}
    if salary.get("score") is None:
        offered = job.get("salary") or {}
        if offered.get("min") is None and offered.get("max") is None:
            points.append("薪资（面议）" if offered.get("negotiable") else "薪资（JD 没写）")
        elif not target.get("salary_min"):
            gaps.append(("salary", "薪资", "档案没写最低期望薪资"))
        else:
            points.append(f"薪资（{salary.get('reason') or '没算分'}）")
    located = any(p.startswith("地点（") for p in points) or any(gap[0] == "location" for gap in gaps)
    if (dimensions.get("location") or {}).get("score") is None and not located:
        if not job.get("cities"):
            points.append("地点（JD 没写城市）")
        else:
            gaps.append(("location", "地点", "档案没写首选和可以接受的城市"))
    for key, label in (("title", "职位名"), ("company", "公司")):
        if not job.get(key):
            points.append(f"{label}（没读出，看原文）")
    if (job.get("guard") or {}).get("verdict") == "warn":
        points.append("JD 里有像是写给 AI 的句子（摘录见 warnings）")
    return points, gaps


def _cells(job: dict) -> list:
    return [job.get("title") or "（职位名没读出）", job.get("company") or "（公司没读出）",
            "、".join(job.get("cities") or []) or "（城市没读出）", salary_text(job.get("salary")) or "（薪资没读出）"]


def _row(rank: int, job: dict, record: dict, entry: dict, points: list) -> dict:
    total = record.get("total") or {}
    grade = "没有总分" if total.get("score") is None else (
        f"{total['score']} 分，{report.GRADES.get(total.get('grade'), total.get('grade'))}")
    cells = _cells(job) + [grade]
    if points:
        cells.append("待确认：" + "、".join(points))
    if entry["action"] == "unchanged":
        cells.append("以前导入过")
    elif entry["jd_changed"]:
        cells.append("JD 改过")
    return {
        "rank": rank,
        "job_id": job["id"],
        "action": entry["action"],
        "jd_changed": entry["jd_changed"],
        "title": job.get("title"),
        "company": job.get("company"),
        "cities": job.get("cities") or [],
        "salary": salary_text(job.get("salary")),
        "score": total.get("score"),
        "grade": total.get("grade"),
        "verdict": (record.get("filter") or {}).get("verdict"),
        "to_confirm": points,
        "url": (job.get("source") or {}).get("url"),
        "files": entry["files"],
        "line": f"{rank}. " + "｜".join(cells),
    }


def _ruled_out_row(job: dict, record: dict, entry: dict) -> dict:
    conflicts = [{"check": check.get("check"), "label": report.CHECKS.get(check.get("check"), check.get("check")),
                  "reason": check.get("reason")}
                 for check in (record.get("filter") or {}).get("checks") or [] if check.get("result") == match.CONFLICT]
    why = "、".join(f"{c['label']}（{c['reason']}）" for c in conflicts)
    return {
        "job_id": job["id"],
        "action": entry["action"],
        "title": job.get("title"),
        "company": job.get("company"),
        "cities": job.get("cities") or [],
        "salary": salary_text(job.get("salary")),
        "score": (record.get("total") or {}).get("score"),
        "conflicts": conflicts,
        "url": (job.get("source") or {}).get("url"),
        "files": entry["files"],
        "line": "- " + "｜".join(_cells(job) + [f"不符合：{why}"]),
    }


def _summary(payload: dict, jobs: int) -> list:
    imported, out = payload["imported"], payload["ruled_out"]
    head = (f"这批 {payload['batch']['files']} 个文件，读出 {jobs} 个岗位：新的 {imported['created']} 个，"
            f"更新 {imported['updated']} 个，以前导入过 {imported['unchanged']} 个")
    if imported["skipped"]:
        head += f"；{imported['skipped']} 个文件或 JD 没导入，原因见 skipped"
    shares = score.shares(payload["weights"])
    lines = [head + "。",
             f"按规则评了 {payload['scored']} 个，其余的评分没过期、照用；总分不含经历维度，挑中的岗位再按评分工作流补。"
             "权重：" + "、".join(f"{report.DIMENSIONS[key]} {shares[key]}%" for key in score.DIMENSIONS) + "。"]
    if out["jobs"]:
        lines.append(f"硬性条件过滤掉 {out['jobs']} 个：" + "、".join(
            f"{item['label']} {item['jobs']}" for item in out["by_check"]) + "（一个岗位可能有几项冲突）。")
    else:
        lines.append("没有岗位被硬性条件过滤掉。")
    freshness = payload["freshness"]
    if freshness["max_job_age_days"] is None:
        lines.append(f"发布时间筛选未启用（参考日期 {freshness['as_of']}，未设置天数）。")
    else:
        lines.append(f"发布时间筛选：参考日期 {freshness['as_of']}，保留发布不超过 "
                     f"{freshness['max_job_age_days']} 天的岗位（含当天）；另排除 "
                     f"{freshness['excluded']['jobs']} 个过旧岗位（不重复计算硬条件冲突）。"
                     "发布时间未知或晚于参考日期的不据此排除，保留待确认，不代表已确认是新岗位；旧岗位和评分仍保留。")
    hidden = sum(payload["not_listed"].values())
    if hidden:
        lines.append(f"你标过不看、过期或打不开的 {hidden} 个没有列出。")
    short = payload["shortlist"]
    if short["total"]:
        lines.append(f"短名单 {short['total']} 个，按等级和总分排序，列出前 {short['shown']} 个。")
    else:
        lines.append("短名单是空的：这批没有符合或待确认的岗位。")
    if payload["profile_gaps"]:
        lines.append("档案没写的几项让不少岗位只能判待确认：" + "；".join(
            f"{gap['reason']}（{gap['jobs']} 个岗位）" for gap in payload["profile_gaps"]) + "。补上档案再筛一遍，待确认会少。")
    return lines
