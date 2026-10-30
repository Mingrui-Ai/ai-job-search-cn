"""Hard-condition filter: does a stored job rule the candidate out?

Each check compares one job field with one profile field (docs/cn/profile.md
section 6) and returns match, conflict or unknown, quoting the job's evidence
and naming the profile field it used; a campus or experienced hire that states
no weekly days or internship length gets not_applicable for those, which counts
like a match. The rule that matters most: a value either side leaves unstated
is unknown, never a conflict - the parser leaves fields empty when it is
unsure, and an empty field must not cost the user a job. The reason for an
unknown names the side that is silent and says what the other side states, so
the user knows whether to ask about the job or fill in the profile. The
interview and the start date (M2-6c) are things to confirm more than
conditions: most JDs state neither, so an unknown there leaves the verdict
alone, and only a start date the user cannot make rules a job out. Scoring and
salary comparison are not here (M2-4); nothing is stored.
"""

import re

from jobsearch_cn import schema

MATCH, CONFLICT, UNKNOWN, NOT_APPLICABLE = "match", "conflict", "unknown", "not_applicable"
ELIGIBLE, NEEDS_CHECK, INELIGIBLE = "eligible", "needs_check", "ineligible"

CHECKS = ("graduation", "education", "days_per_week", "min_months", "location", "employment_type", "exclusions",
          "interview", "start_date")
# Checks whose unknown is only something to confirm: it leaves the verdict alone.
TO_CONFIRM = ("interview", "start_date")


def filter_job(job: dict, profile: dict) -> dict:
    """The filter result for one job record against one (valid) profile."""
    results = [
        _graduation(job, profile),
        _education(job, profile),
        _at_most(job, profile, "requirements.days_per_week", "availability.days_per_week", "days_per_week",
                 "每周到岗", "天", "每周能到岗"),
        _at_most(job, profile, "requirements.min_months", "availability.months", "min_months",
                 "实习时长", "个月", "能实习"),
        _location(job, profile),
        _employment_type(job, profile),
        _exclusions(job, profile),
        _interview(job, profile),
        _start_date(job, profile),
    ]
    outcomes = {r["result"] for r in results if not (r["check"] in TO_CONFIRM and r["result"] == UNKNOWN)}
    verdict = INELIGIBLE if CONFLICT in outcomes else NEEDS_CHECK if UNKNOWN in outcomes else ELIGIBLE
    return {"job_id": job["id"], "title": job["title"], "company": job["company"],
            "verdict": verdict, "checks": results}


def _item(check, result, reason, job, job_fields, profile_fields, profile, note=None):
    item = {
        "check": check,
        "result": result,
        "reason": reason,
        "jd": {path: {"value": schema._field(job, path), "evidence": _evidence(job, path)} for path in job_fields},
        "profile": {path: _profile_field(profile, path) for path in profile_fields},
    }
    if note:
        item["note"] = note
    return item


def _evidence(job: dict, path: str):
    entry = job["evidence"].get(path)
    return entry["text"] if entry else None


def _profile_field(profile: dict, path: str):
    value = profile
    for part in path.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _known(value) -> bool:
    return value is not None and value != []


def _graduation(job, profile):
    fields = ("requirements.graduation",), ("graduation.year",)
    wanted = job["requirements"]["graduation"]
    year = _profile_field(profile, "graduation.year")
    if not _known(wanted) or not _known(year):
        asked = (f"JD {'要求' if wanted['strict'] else '优先'} {_years(wanted['years'])} 届" if _known(wanted)
                 else "JD 没写届别")
        have = f"你是 {year} 届" if _known(year) else "档案没写毕业时间"
        return _item("graduation", UNKNOWN, f"{asked}；{have}", job, *fields, profile)
    years = wanted["years"]
    if year in years:
        return _item("graduation", MATCH, f"{year} 届在要求范围内", job, *fields, profile)
    if wanted["strict"]:
        return _item("graduation", CONFLICT, f"JD 限 {_years(years)} 届，你是 {year} 届", job, *fields, profile)
    return _item("graduation", MATCH, f"JD 优先 {_years(years)} 届，不是硬性要求", job, *fields, profile,
                 note=f"你是 {year} 届，不在优先届别内")


def _years(years) -> str:
    return "/".join(str(y) for y in years)


_LEVEL_NAMES = {"associate": "大专", "bachelor": "本科", "master": "硕士", "phd": "博士"}


def _education(job, profile):
    fields = ("requirements.education",), ("education",)
    required = (job["requirements"]["education"] or {}).get("min")
    levels = [e.get("level") for e in profile.get("education") or [] if e.get("level") in schema.EDUCATION_LEVELS]
    if required == schema.NO_MINIMUM:
        return _item("education", MATCH, "JD 写明学历不限", job, *fields, profile)
    if required is None:
        return _item("education", UNKNOWN, "JD 没写最低学历（优先学历不作要求）", job, *fields, profile)
    if not levels:
        return _item("education", UNKNOWN, "档案没写学历", job, *fields, profile)
    highest = max(levels, key=schema.EDUCATION_LEVELS.index)
    if schema.EDUCATION_LEVELS.index(highest) >= schema.EDUCATION_LEVELS.index(required):
        return _item("education", MATCH, f"最高学历{_LEVEL_NAMES[highest]}，满足{_LEVEL_NAMES[required]}及以上",
                     job, *fields, profile)
    return _item("education", CONFLICT, f"JD 要求{_LEVEL_NAMES[required]}及以上，你的最高学历是{_LEVEL_NAMES[highest]}",
                 job, *fields, profile)


_NOT_INTERNSHIP = {"campus": "校招", "experienced": "社招"}


def _at_most(job, profile, job_path, profile_path, check, label, unit, can):
    """The job asks for N; the candidate can give M. Conflict when N > M."""
    fields = (job_path,), (profile_path,)
    needed, available = schema._field(job, job_path), _profile_field(profile, profile_path)
    if needed is None and job["employment_type"] in _NOT_INTERNSHIP:
        # Weekly days and an internship length belong to internships; a full-time hire that states none asks none.
        return _item(check, NOT_APPLICABLE, f"{_NOT_INTERNSHIP[job['employment_type']]}岗位，JD 没写{label}，不适用",
                     job, (job_path, "employment_type"), (profile_path,), profile)
    if needed is None or available is None:
        asked = f"JD 没写{label}要求" if needed is None else f"JD 要求{label} {needed} {unit}"
        have = f"档案没写{can}几{unit}" if available is None else f"你{can} {available} {unit}"
        return _item(check, UNKNOWN, f"{asked}；{have}", job, *fields, profile)
    if needed <= available:
        return _item(check, MATCH, f"JD 要求{label} {needed} {unit}，你可以 {available} {unit}", job, *fields, profile)
    return _item(check, CONFLICT, f"JD 要求{label} {needed} {unit}，你只能 {available} {unit}", job, *fields, profile)


def _city(name: str) -> str:
    folded = schema.normalize_for_match(name)
    return folded[:-1] if folded.endswith("市") and len(folded) > 2 else folded


def _location(job, profile):
    fields = ("cities", "remote"), ("availability.cities", "availability.acceptable_cities", "availability.remote_ok",
                                    "availability.relocate")
    availability = profile.get("availability") or {}
    wanted = {_city(c) for c in availability.get("cities") or []}
    acceptable = {_city(c) for c in availability.get("acceptable_cities") or []}
    offered = job["cities"]
    remote, remote_ok, relocate = job["remote"], availability.get("remote_ok"), availability.get("relocate")

    if offered and wanted & {_city(c) for c in offered}:
        shared = [c for c in offered if _city(c) in wanted]
        return _item("location", MATCH, f"工作城市{'、'.join(shared)}在你的意向内", job, *fields, profile)
    if remote is True and remote_ok is True:
        return _item("location", MATCH, "JD 可远程，你接受远程", job, *fields, profile)
    if offered and acceptable & {_city(c) for c in offered}:
        # A city the user accepts is one they can work in; how much less they like it is the score's (M2-6b).
        shared = "、".join(c for c in offered if _city(c) in acceptable)
        return _item("location", MATCH, f"工作城市{shared}在你可以接受的城市内", job, *fields, profile,
                     note=f"{shared}是你可以接受的城市，不是首选")
    if not offered:
        return _item("location", UNKNOWN, "JD 没写工作城市", job, *fields, profile)
    if not wanted and not acceptable:
        return _item("location", UNKNOWN, "档案没写意向城市", job, *fields, profile)
    where = "、".join(offered)
    if relocate is True:
        return _item("location", MATCH, f"{where}不在意向城市内，但你愿意去其他城市", job, *fields, profile,
                     note="需要搬到其他城市")
    # A conflict needs both ways out closed on the record: no move, and remote
    # ruled out by one side. Remote unstated on both sides is still a way out.
    if relocate is False and (remote is False or remote_ok is False):
        return _item("location", CONFLICT, f"{where}不在意向城市内，且不能远程、不搬家", job, *fields, profile)
    return _item("location", UNKNOWN, f"{where}不在意向城市内；{_ways_out(remote, remote_ok, relocate)}",
                 job, *fields, profile)


_JD_REMOTE = {None: "JD 没写能否远程", True: "JD 可远程", False: "JD 不支持远程"}


def _ways_out(remote, remote_ok, relocate) -> str:
    """What each side says about remote work and moving: "JD 没写能否远程；你接受远程、不考虑异地"."""
    said, unsaid = [], []
    if remote_ok is None:
        unsaid.append("是否接受远程")
    else:
        said.append("接受远程" if remote_ok else "不接受远程")
    if relocate is None:
        unsaid.append("是否愿意去其他城市")
    else:
        said.append("愿意去其他城市" if relocate else "不考虑异地")
    profile_side = [part for part in ("你" + "、".join(said) if said else "",
                                      "档案没写" + "和".join(unsaid) if unsaid else "") if part]
    return "；".join([_JD_REMOTE[remote]] + profile_side)


_TYPE_NAMES = {"internship": "实习", "campus": "校招", "experienced": "社招"}


def _employment_type(job, profile):
    fields = ("employment_type",), ("target.employment_types",)
    kind = job["employment_type"]
    wanted = _profile_field(profile, "target.employment_types") or []
    if kind is None or not wanted:
        offered = f"这是{_TYPE_NAMES[kind]}岗位" if kind else "JD 没写岗位类型"
        sought = f"你找的是{'、'.join(_TYPE_NAMES[k] for k in wanted)}" if wanted else "档案没写想找的岗位类型"
        return _item("employment_type", UNKNOWN, f"{offered}；{sought}", job, *fields, profile)
    if kind in wanted:
        return _item("employment_type", MATCH, f"{_TYPE_NAMES[kind]}岗位在你的求职方向内", job, *fields, profile)
    return _item("employment_type", CONFLICT,
                 f"这是{_TYPE_NAMES[kind]}岗位，你找的是{'、'.join(_TYPE_NAMES[k] for k in wanted)}",
                 job, *fields, profile)


def _exclusions(job, profile):
    """Keywords match the title only; body text would exclude a JD that says "不是外包"."""
    fields = ("title", "company", "cities"), ("exclusions",)
    exclusions = profile.get("exclusions") or {}
    title, company = job["title"], job["company"]
    hits = []
    for keyword in exclusions.get("keywords") or []:
        if title and schema.normalize_for_match(keyword) in schema.normalize_for_match(title):
            hits.append(f"标题含排除词“{keyword}”")
    for name in exclusions.get("companies") or []:
        if company and schema.normalize_for_match(name) in schema.normalize_for_match(company):
            hits.append(f"公司在排除名单中（{name}）")
    excluded = {_city(c) for c in exclusions.get("cities") or []}
    if job["cities"] and all(_city(c) in excluded for c in job["cities"]):
        hits.append(f"工作城市{'、'.join(job['cities'])}都在排除名单中")
    if hits:
        return _item("exclusions", CONFLICT, "；".join(hits), job, *fields, profile)
    unchecked = [label for label, needed, have in (
        ("标题", exclusions.get("keywords"), title), ("公司", exclusions.get("companies"), company)) if needed and not have]
    if unchecked:
        return _item("exclusions", UNKNOWN, f"JD 没写{'和'.join(unchecked)}，无法核对排除项", job, *fields, profile)
    return _item("exclusions", MATCH, "没有命中排除项", job, *fields, profile)


def _interview(job, profile):
    """Online, or in person in a city you want: a match. In person only elsewhere: a match with a note of the
    cost, or to confirm when you will not travel to interview (M2-6f) - the JD may still allow an online one."""
    fields = ("interview",), ("availability.cities", "availability.acceptable_cities",
                              "availability.interview_travel")
    interview = job["interview"]
    if interview is None:
        return _item("interview", UNKNOWN, "JD 没写面试形式；需要确认是线上还是现场面试、在哪里面试", job, *fields, profile)
    mode, places = interview["mode"], interview["cities"]
    where = "、".join(places)
    if mode == "online":
        return _item("interview", MATCH, "线上面试，不用出行", job, *fields, profile)
    if mode == "either":
        onsite = f"去{where}现场面试" if places else "现场面试"
        return _item("interview", MATCH, f"可以线上面试，不用出行；也可以{onsite}", job, *fields, profile)
    how = "有一轮要现场面试" if mode == "mixed" else "要现场面试"
    if not places:
        return _item("interview", UNKNOWN, f"JD 没写面试地点（{how}）；需要确认在哪里面试", job, *fields, profile)
    # Both tiers are cities you would go to, as in the location check (M2-6b).
    availability = profile.get("availability") or {}
    wanted = {_city(c) for key in ("cities", "acceptable_cities") for c in availability.get(key) or []}
    if not wanted:
        return _item("interview", MATCH, f"{how}，在{where}", job, *fields, profile,
                     note=f"档案没写意向城市，看去{where}面试要不要出行")
    away = [c for c in places if _city(c) not in wanted]
    if not away:
        return _item("interview", MATCH, f"{how}，在{where}，在你的意向城市内", job, *fields, profile)
    if len(away) == len(places) and availability.get("interview_travel") is False:
        return _item("interview", UNKNOWN, f"JD 写{how}，在{where}，不在你的意向城市内；你暂时不去外地面试，"
                     "投之前先问能不能线上面试", job, *fields, profile)
    return _item("interview", MATCH, f"{how}，在{where}", job, *fields, profile,
                 note=f"要去{'、'.join(away)}面试，有路费和时间成本")


def _start_date(job, profile):
    """A start-by date you can only reach later is a conflict; "as soon as possible" names no date to compare."""
    fields = ("requirements.start",), ("availability.start_date",)
    start = job["requirements"]["start"]
    by, can = (start or {}).get("by"), _profile_field(profile, "availability.start_date")
    asked = (_asked_by(job, by) if by else "JD 没写具体到岗日期，只说希望尽快到岗" if start and start["asap"]
             else "JD 没写到岗时间")
    if by and can:
        if can <= by:
            return _item("start_date", MATCH, f"{asked}，你 {can} 就能到岗", job, *fields, profile)
        return _item("start_date", CONFLICT, f"{asked}，你 {can} 才能到岗", job, *fields, profile)
    have = f"你 {can} 可以到岗" if can else "档案没写可到岗日期"
    return _item("start_date", UNKNOWN, f"{asked}；{have}", job, *fields, profile)


def _asked_by(job, by: str) -> str:
    """The start-by date, saying so when the JD gave no year with it and the year was inferred
    (jd_parser._start_by). Only a year written with the date counts: "2026届" elsewhere is no year for it."""
    text = (job["evidence"].get("requirements.start") or {}).get("text")
    snippets = [text] if isinstance(text, str) else [s for s in text or [] if isinstance(s, str)]
    stated = re.compile(rf"{by[:4]}\s*[年\-/.－]\s*0?{int(by[5:7])}(?!\d)")
    if not snippets or any(stated.search(snippet) for snippet in snippets):
        return f"JD 要求 {by} 前到岗"
    month = re.compile(rf"(?<!\d){int(by[5:7])}\s*月")
    quoted = next((snippet for snippet in snippets if month.search(snippet)), snippets[0])
    basis = "发布日期" if job.get("published_at") else "导入日期"
    return f"JD 写“{quoted}”，没写年份，按{basis}推断为 {by} 前到岗"
