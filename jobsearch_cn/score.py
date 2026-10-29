"""Explainable scoring: the match record for one stored job and the profile.

score_job() works out the rule part of a match (docs/cn/match.md, "可解释评分"):
the hard-condition filter, and the skills, direction and salary dimensions,
each 0-100, or null when a side does not say enough. An agent adds the
experience dimension - and the direction, where the rules leave it null -
with a reason and evidence; validate() checks such a record before it is
saved: the rule part must be what the rules give, agent evidence must quote
the JD and name experience the profile holds, and the total must follow from
the dimensions. job_hash and profile_hash tell when a record has gone stale.
Integer arithmetic throughout (Fraction), so the same input always gives the
same record, scored_at aside.
"""

import hashlib
import json
from datetime import datetime
from fractions import Fraction

from jobsearch_cn import match, schema, vocab
from jobsearch_cn.profile import WEIGHT_KEYS

SCHEMA_VERSION = 1
# Bump when a rule's result changes - a check result or verdict, a dimension score, which
# gaps are listed - or the default weights do. Rewording a reason does not: a saved record
# keeps the old wording until it is scored again (docs/cn/match.md, 匹配记录).
RULES_VERSION = 1
DIMENSIONS = WEIGHT_KEYS  # skills, direction, experience, salary
DEFAULT_WEIGHTS = {"skills": 35, "direction": 30, "experience": 25, "salary": 10}
# The upstream 04-job-evaluation.md bands; a job the filter rules out is graded ineligible.
GRADES = (("strong", 75), ("good", 60), ("moderate", 45), ("weak", 30), ("poor", 0))
INELIGIBLE = "ineligible"
RECORD_KEYS = ("schema_version", "job_id", "rules_version", "scored_at", "job_hash", "profile_hash",
               "filter", "dimensions", "weights", "total", "gaps")
AGENT_KEYS = ("jd", "profile")

# 精通、熟练 1, 熟悉 0.8, 了解 0.5; no level: 0.8 if some experience used the skill, else 0.5.
_CREDIT = {"expert": Fraction(1), "proficient": Fraction(1), "working": Fraction(4, 5), "familiar": Fraction(1, 2)}
_USED, _UNUSED = Fraction(4, 5), Fraction(1, 2)
_UNIT = {"CNY/hour": "元/小时", "CNY/day": "元/天", "CNY/month": "元/月", "CNY/year": "元/年"}


def job_hash(job: dict) -> str:
    """A digest of the job record; its status is the user's bookkeeping, not the job."""
    return _digest({key: value for key, value in job.items() if key != "status"})


def profile_hash(profile: dict) -> str:
    """A digest of the profile without its contact details, which no match record holds."""
    return _digest({key: value for key, value in profile.items() if key != "contact"})


def _digest(data) -> str:
    text = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stale(record: dict, job, digest: str) -> bool:
    """The job or the profile (its profile_hash is `digest`) changed since scoring, the job is gone,
    or other rules scored it: score it again."""
    return (job is None or record.get("job_hash") != job_hash(job)
            or record.get("profile_hash") != digest or record.get("rules_version") != RULES_VERSION)


def score_job(job: dict, profile: dict, vocabulary, previous=None, now=None) -> dict:
    """The match record for a job: the rule part, and the agent part of `previous` if neither side changed."""
    rules = rule_part(job, profile, vocabulary)
    record = {
        "schema_version": SCHEMA_VERSION,
        "job_id": job["id"],
        "rules_version": RULES_VERSION,
        "scored_at": (now or datetime.now().astimezone()).isoformat(timespec="seconds"),
        "job_hash": job_hash(job),
        "profile_hash": profile_hash(profile),
        "filter": rules["filter"],
        "dimensions": rules["dimensions"],
        "weights": rules["weights"],
        "total": None,
        "gaps": rules["gaps"],
    }
    if (isinstance(previous, dict) and previous.get("job_hash") == record["job_hash"]
            and previous.get("profile_hash") == record["profile_hash"]
            and previous.get("rules_version") == RULES_VERSION):
        dimensions = previous.get("dimensions") or {}
        if (dimensions.get("experience") or {}).get("score") is not None:
            record["dimensions"]["experience"] = dimensions["experience"]
        if record["dimensions"]["direction"]["score"] is None and (dimensions.get("direction") or {}).get("score") is not None:
            record["dimensions"]["direction"] = dimensions["direction"]
    record["total"] = total(record["dimensions"], record["weights"], record["filter"]["verdict"])
    return record


def rule_part(job: dict, profile: dict, vocabulary) -> dict:
    """What the rules give: the filter, the dimensions before any agent adds to them, weights and gaps."""
    filtered = match.filter_job(job, profile)
    skills = _skills(job, profile, vocabulary)
    salary = _salary(job, profile)
    weights = (profile.get("target") or {}).get("weights") or DEFAULT_WEIGHTS
    return {
        "filter": {"verdict": filtered["verdict"], "checks": filtered["checks"]},
        "dimensions": {
            "skills": skills,
            "direction": _direction(job, profile, vocabulary),
            "experience": _experience(job, profile, vocabulary),
            "salary": salary,
        },
        "weights": {key: weights[key] for key in DIMENSIONS},
        "gaps": _gaps(job, skills, salary, filtered["checks"]),
    }


def _asked(job: dict, vocabulary) -> list:
    """The JD's skills, a same_as synonym counted once (the first spelling)."""
    seen, asked = set(), []
    for name in job["requirements"]["skills"]:
        key = vocabulary.key(name)
        if key not in seen:
            seen.add(key)
            asked.append(name)
    return asked


def _credit(skill: dict) -> Fraction:
    level = skill.get("level")
    if level in _CREDIT:
        return _CREDIT[level]
    return _USED if skill.get("used_in") else _UNUSED


def _skills(job, profile, vocabulary) -> dict:
    asked = _asked(job, vocabulary)
    if not asked:
        return {"score": None, "method": "rule", "reason": "JD 没写技能", "matched": [], "missing": []}
    held = {}
    for skill in profile.get("skills") or []:
        key, credit = vocabulary.key(skill["name"]), _credit(skill)
        if key not in held or credit > held[key][1]:
            held[key] = (skill["name"], credit)
    matched, missing, earned = [], [], Fraction(0)
    for name in asked:
        hit = held.get(vocabulary.key(name))
        if hit:
            matched.append({"jd": name, "profile": hit[0], "credit": _plain(hit[1])})
            earned += hit[1]
        else:
            missing.append(name)
    return {"score": _round(earned / len(asked) * 100), "method": "rule",
            "reason": f"JD 要求 {len(asked)} 项技能，你有 {len(matched)} 项", "matched": matched, "missing": missing}


def _direction(job, profile, vocabulary) -> dict:
    groups = {}
    for name in _asked(job, vocabulary):
        group = vocabulary.group_of(name)
        if group and group != vocab.GENERAL:
            groups[group] = groups.get(group, 0) + 1
    wanted = (profile.get("target") or {}).get("directions") or []

    def result(score, reason):
        return {"score": score, "method": "rule", "reason": reason, "jd_groups": groups, "evidence": None}

    if not wanted:
        return result(None, "档案没写求职方向（target.directions）")
    if not groups:
        return result(None, "JD 的技能都不在方向分组里（或没写技能），由 Agent 按标题和职责判断")
    top = max(groups.values())
    leading = [group for group, count in groups.items() if count == top]
    named = "、".join(vocabulary.groups[group]["label"] for group in leading)
    if set(leading) & set(wanted):
        return result(100, f"JD 技能以{named}方向为主，在你的求职方向中")
    if set(groups) & set(wanted):
        return result(50, f"JD 技能以{named}方向为主，也有属于你求职方向的技能")
    return result(0, f"JD 技能以{named}方向为主，不在你的求职方向中")


def _experience(job, profile, vocabulary) -> dict:
    """Left to an agent; the rules only point at the experience the JD's skills were used in."""
    used = {}
    for skill in profile.get("skills") or []:
        for ref in skill.get("used_in") or []:
            refs = used.setdefault(vocabulary.key(skill["name"]), [])
            if ref not in refs:
                refs.append(ref)
    hints = [{"jd": name, "profile": used[vocabulary.key(name)]}
             for name in _asked(job, vocabulary) if vocabulary.key(name) in used]
    return {"score": None, "method": "agent", "reason": "等 Agent 对照经历补充", "hints": hints, "evidence": None}


def _salary(job, profile) -> dict:
    offered = job.get("salary") or {}
    wanted = (profile.get("target") or {}).get("salary_min")
    upper = offered.get("max") if offered.get("max") is not None else offered.get("min")

    def result(score, reason):
        return {"score": score, "method": "rule", "reason": reason}

    if upper is None:
        return result(None, "JD 薪资面议" if offered.get("negotiable") else "JD 没写薪资")
    if not wanted:
        return result(None, "档案没写最低期望薪资")
    if offered.get("unit") != wanted.get("unit"):
        return result(None, f"JD 按{_UNIT[offered['unit']]}、你按{_UNIT[wanted['unit']]}计，单位不同，不换算")
    unit, amount = _UNIT[offered["unit"]], wanted["amount"]
    if upper >= amount:
        return result(100, f"JD 上限 {_plain(upper)} {unit}，达到你的最低期望 {_plain(amount)} {unit}")
    return result(0, f"JD 上限 {_plain(upper)} {unit}，低于你的最低期望 {_plain(amount)} {unit}")


def _gaps(job, skills, salary, checks) -> list:
    """What stands between you and the job, each with the JD text it rests on (null when the JD is silent)."""
    gaps = [{"kind": "skill", "item": name, "jd": _quote(job, "requirements.skills", name)} for name in skills["missing"]]
    if salary["score"] == 0:
        gaps.append({"kind": "salary", "item": salary["reason"], "jd": _quote(job, "salary")})
    for check in checks:
        if check["result"] in (match.CONFLICT, match.UNKNOWN):
            quote = next((_first(field["evidence"]) for field in check["jd"].values() if field["evidence"]), None)
            gaps.append({"kind": "filter", "item": check["check"], "result": check["result"],
                         "reason": check["reason"], "jd": quote})
    return gaps


def _quote(job: dict, path: str, term: str = None):
    entry = job["evidence"].get(path)
    if not entry or not entry.get("text"):
        return None
    snippets = [entry["text"]] if isinstance(entry["text"], str) else entry["text"]
    if term is not None:
        folded = schema.normalize_for_match(term)
        return next((s for s in snippets if folded in schema.normalize_for_match(s)), None)
    return snippets[0]


def _first(evidence):
    return evidence if isinstance(evidence, str) else evidence[0]


def total(dimensions: dict, weights: dict, verdict: str) -> dict:
    """The weighted mean of the scored dimensions, rounded half up; a job the filter rules out is ineligible."""
    scored = [key for key in DIMENSIONS if dimensions[key]["score"] is not None]
    weight = sum((_fraction(weights[key]) for key in scored), Fraction(0))
    score = None
    if weight > 0:
        score = _round(sum((_fraction(weights[key]) * dimensions[key]["score"] for key in scored), Fraction(0)) / weight)
    if verdict == match.INELIGIBLE:
        grade = INELIGIBLE
    else:
        grade = None if score is None else next(name for name, floor in GRADES if score >= floor)
    return {"score": score, "grade": grade, "complete": len(scored) == len(DIMENSIONS),
            "missing": [key for key in DIMENSIONS if key not in scored]}


_GRADE_ORDER = [name for name, _ in GRADES] + [INELIGIBLE]


def list_key(grade, total_score, job_id) -> tuple:
    """How match list orders records: by grade, strong first and ineligible last, then by score, high first."""
    rank = _GRADE_ORDER.index(grade) if grade in _GRADE_ORDER else len(_GRADE_ORDER)
    return rank, -total_score if isinstance(total_score, int) else 1, job_id


def _fraction(number) -> Fraction:
    return Fraction(str(number))


def _round(value: Fraction) -> int:
    """Half up, as 四舍五入 means: 62.5 is 63."""
    return int((value + Fraction(1, 2)) // 1)


def _plain(number):
    """1 rather than 1.0, 0.8 rather than Fraction(4, 5)."""
    value = number if isinstance(number, Fraction) else Fraction(str(number))
    return int(value) if value.denominator == 1 else float(value)


def validate(record, job: dict, profile: dict, vocabulary) -> list:
    """Every problem with a match record against the stored job and the profile; [] means valid."""
    if not isinstance(record, dict):
        return ["match: must be a JSON object"]
    errors = [f"{key}: missing" for key in RECORD_KEYS if key not in record]
    errors += [f"{key}: unknown field" for key in record if key not in RECORD_KEYS]
    if errors:
        return errors
    if record["schema_version"] != SCHEMA_VERSION:
        errors.append(f"schema_version: must be {SCHEMA_VERSION}")
    if record["rules_version"] != RULES_VERSION:
        errors.append(f"rules_version: scored by other rules; run match score again (now {RULES_VERSION})")
    if record["job_id"] != job["id"]:
        errors.append(f"job_id: {record['job_id']!r} is not the job {job['id']!r}")
    if not _is_time(record["scored_at"]):
        errors.append("scored_at: must be an ISO 8601 time with an offset")
    if record["job_hash"] != job_hash(job) or record["profile_hash"] != profile_hash(profile):
        errors.append("job_hash/profile_hash: the job or the profile changed since scoring; run match score again")
    if errors:
        return errors

    rules = rule_part(job, profile, vocabulary)
    for key in ("filter", "weights", "gaps"):
        if record[key] != rules[key]:
            errors.append(f"{key}: not what the rules give; it comes from match score and is not edited")
    dimensions = record["dimensions"]
    if not isinstance(dimensions, dict) or sorted(dimensions) != sorted(DIMENSIONS):
        return errors + [f"dimensions: must hold exactly {', '.join(DIMENSIONS)}"]
    for key in ("skills", "salary"):
        if dimensions[key] != rules["dimensions"][key]:
            errors.append(f"dimensions.{key}: a rule dimension; an agent does not change it")
    errors += _agent_dimension(dimensions, rules["dimensions"], "direction", "jd_groups", job, profile)
    errors += _agent_dimension(dimensions, rules["dimensions"], "experience", "hints", job, profile)
    if not errors:
        expected = total(dimensions, record["weights"], record["filter"]["verdict"])
        if record["total"] != expected:
            # An agent copies the total from here rather than doing the arithmetic.
            errors.append("total: does not follow from the dimensions and weights; they give "
                          f"{json.dumps(expected, ensure_ascii=False)}")
    return errors


def _agent_dimension(dimensions, rules, key, fixed, job, profile) -> list:
    """An agent may fill experience, and a direction the rules left null; nothing else about them."""
    given, rule, where = dimensions[key], rules[key], f"dimensions.{key}"
    if given == rule:
        return []
    if rule["score"] is not None:
        return [f"{where}: the rules scored it; an agent does not change it"]
    if not isinstance(given, dict) or sorted(given) != sorted(rule):
        return [f"{where}: must keep the fields {', '.join(rule)}"]
    errors = []
    if given[fixed] != rule[fixed]:
        errors.append(f"{where}.{fixed}: comes from the rules; not edited")
    if given["method"] != "agent":
        errors.append(f"{where}.method: an agent's score has method agent")
    score = given["score"]
    if not (schema._is_int(score) and 0 <= score <= 100):
        errors.append(f"{where}.score: must be a whole number from 0 to 100")
    if not (isinstance(given["reason"], str) and given["reason"].strip()):
        errors.append(f"{where}.reason: say why, in a sentence")
    evidence = given["evidence"]
    if not (isinstance(evidence, dict) and sorted(evidence) == sorted(AGENT_KEYS)
            and all(isinstance(evidence[k], list) for k in AGENT_KEYS)):
        return errors + [f"{where}.evidence: must be {{\"jd\": [JD quotes], \"profile\": [experience ids]}}"]
    if not evidence["jd"]:
        errors.append(f"{where}.evidence.jd: quote the JD text the score rests on")
    haystack = schema.normalize_for_match(job["raw_text"])
    for index, quote in enumerate(evidence["jd"]):
        if not (isinstance(quote, str) and quote.strip() and schema.normalize_for_match(quote) in haystack):
            errors.append(f"{where}.evidence.jd[{index}]: not found in the JD text")
    if key == "experience" and not evidence["profile"]:
        errors.append(f"{where}.evidence.profile: name the experience (its id) the score rests on")
    ids = {item.get("id") for item in profile.get("experience") or [] if isinstance(item, dict)}
    for index, ref in enumerate(evidence["profile"]):
        # Check the type first: an object or a list here is an agent's slip, and an error, not a crash.
        if not (isinstance(ref, str) and ref.strip()):
            errors.append(f"{where}.evidence.profile[{index}]: must be an experience id (a string)")
        elif ref not in ids:
            errors.append(f"{where}.evidence.profile[{index}]: no experience with id {ref!r} in the profile")
    return errors


def _is_time(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False
