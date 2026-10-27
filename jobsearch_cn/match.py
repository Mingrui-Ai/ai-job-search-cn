"""Hard-condition filter: does a stored job rule the candidate out?

Each check compares one job field with one profile field (docs/cn/profile.md
section 6) and returns match, conflict or unknown, quoting the job's evidence
and naming the profile field it used. The rule that matters most: a value
either side leaves unstated is unknown, never a conflict - the parser leaves
fields empty when it is unsure, and an empty field must not cost the user a
job. Scoring and salary comparison are not here (M2-4); nothing is stored.
"""

from jobsearch_cn import schema

MATCH, CONFLICT, UNKNOWN = "match", "conflict", "unknown"
ELIGIBLE, NEEDS_CHECK, INELIGIBLE = "eligible", "needs_check", "ineligible"

CHECKS = ("graduation", "education", "days_per_week", "min_months", "location", "employment_type", "exclusions")


def filter_job(job: dict, profile: dict) -> dict:
    """The filter result for one job record against one (valid) profile."""
    results = [
        _graduation(job, profile),
        _education(job, profile),
        _at_most(job, profile, "requirements.days_per_week", "availability.days_per_week", "days_per_week",
                 "每周到岗", "天"),
        _at_most(job, profile, "requirements.min_months", "availability.months", "min_months", "实习时长", "个月"),
        _location(job, profile),
        _employment_type(job, profile),
        _exclusions(job, profile),
    ]
    outcomes = {r["result"] for r in results}
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
        return _item("graduation", UNKNOWN, "JD 或档案没写届别", job, *fields, profile)
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


def _at_most(job, profile, job_path, profile_path, check, label, unit):
    """The job asks for N; the candidate can give M. Conflict when N > M."""
    fields = (job_path,), (profile_path,)
    needed, available = schema._field(job, job_path), _profile_field(profile, profile_path)
    if needed is None or available is None:
        return _item(check, UNKNOWN, f"JD 或档案没写{label}", job, *fields, profile)
    if needed <= available:
        return _item(check, MATCH, f"JD 要求{label} {needed} {unit}，你可以 {available} {unit}", job, *fields, profile)
    return _item(check, CONFLICT, f"JD 要求{label} {needed} {unit}，你只能 {available} {unit}", job, *fields, profile)


def _city(name: str) -> str:
    folded = schema.normalize_for_match(name)
    return folded[:-1] if folded.endswith("市") and len(folded) > 2 else folded


def _location(job, profile):
    fields = ("cities", "remote"), ("availability.cities", "availability.remote_ok", "availability.relocate")
    availability = profile.get("availability") or {}
    wanted = {_city(c) for c in availability.get("cities") or []}
    offered = job["cities"]
    remote, remote_ok, relocate = job["remote"], availability.get("remote_ok"), availability.get("relocate")

    if offered and wanted & {_city(c) for c in offered}:
        shared = [c for c in offered if _city(c) in wanted]
        return _item("location", MATCH, f"工作城市{'、'.join(shared)}在你的意向内", job, *fields, profile)
    if remote is True and remote_ok is True:
        return _item("location", MATCH, "JD 可远程，你接受远程", job, *fields, profile)
    if not offered:
        return _item("location", UNKNOWN, "JD 没写工作城市", job, *fields, profile)
    if not wanted:
        return _item("location", UNKNOWN, "档案没写意向城市", job, *fields, profile)
    where = "、".join(offered)
    if relocate is True:
        return _item("location", MATCH, f"{where}不在意向城市内，但你愿意去其他城市", job, *fields, profile,
                     note="需要搬到其他城市")
    # A conflict needs both ways out closed on the record: no move, and remote
    # ruled out by one side. Remote unstated on both sides is still a way out.
    if relocate is False and (remote is False or remote_ok is False):
        return _item("location", CONFLICT, f"{where}不在意向城市内，且不能远程、不搬家", job, *fields, profile)
    return _item("location", UNKNOWN, f"{where}不在意向城市内，是否可远程或愿意搬家未知", job, *fields, profile)


_TYPE_NAMES = {"internship": "实习", "campus": "校招", "experienced": "社招"}


def _employment_type(job, profile):
    fields = ("employment_type",), ("target.employment_types",)
    kind = job["employment_type"]
    wanted = _profile_field(profile, "target.employment_types") or []
    if kind is None or not wanted:
        return _item("employment_type", UNKNOWN, "JD 或档案没写岗位类型", job, *fields, profile)
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
