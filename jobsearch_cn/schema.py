"""Job record schema (version 1) and its validator.

A job record is plain JSON, so every consumer reads and writes the same thing:
the CLI, Codex, Claude Code and the local store. docs/cn/job-schema.md is the
field reference; this module enforces it, and tests/test_cn_schema.py keeps
the two in step.

Conventions:

* Every key is always present. A scalar or object the JD does not state is
  null; a list it does not state is []. An agent completing a record therefore
  writes an explicit "not stated" instead of silently dropping a key.
* Unknown keys are errors, so a misspelt field fails loudly.
* Every value read from the JD cites it. evidence["<field path>"] holds the
  snippet(s) the value came from and how it was obtained: "rule" (this
  package's parser), "agent" (a model) or "user" (typed in by the user).
  For rule and agent evidence each snippet must occur in raw_text, and every
  item of a list field must occur in its evidence. A model cannot cite text
  the JD does not contain, so an invented value cannot pass validation.
  Whether a value was *derived* correctly from real text is the parser's
  tests' job, not this module's.
"""

import math
import re
import unicodedata
from datetime import date, datetime

SCHEMA_VERSION = 1

SOURCE_TYPES = ("paste", "file", "url", "portal")
SITES = (
    "boss", "shixiseng", "nowcoder", "liepin", "zhaopin", "51job", "lagou",
    "official", "ats", "referral", "other",
)
EMPLOYMENT_TYPES = ("internship", "campus", "experienced")
SALARY_UNITS = ("CNY/hour", "CNY/day", "CNY/month", "CNY/year")
# Lowest to highest, so a preferred level can be checked against the minimum.
EDUCATION_LEVELS = ("associate", "bachelor", "master", "phd")
# The vocabulary /scrape writes to seen_jobs.json, so a CN record can join the
# upstream job pool without translation.
STATUSES = ("new", "skipped", "ranked", "expired", "unreachable")
EVIDENCE_METHODS = ("rule", "agent", "user")
GUARD_VERDICTS = ("clean", "warn")

TOP_LEVEL_KEYS = (
    "schema_version", "id", "source", "title", "company", "cities", "remote",
    "employment_type", "salary", "requirements", "return_offer", "published_at",
    "deadline", "status", "evidence", "guard", "raw_text",
)
SOURCE_KEYS = ("type", "site", "url", "imported_at")
SALARY_KEYS = ("min", "max", "unit", "months", "negotiable")
REQUIREMENT_KEYS = ("graduation", "days_per_week", "min_months", "education", "skills")
GRADUATION_KEYS = ("years", "strict")
EDUCATION_KEYS = ("min", "preferred")
EVIDENCE_KEYS = ("text", "method")
GUARD_KEYS = ("verdict", "counts")

# Fields read from the JD text. Each one that holds a value needs evidence.
EVIDENCE_FIELDS = (
    "title", "company", "cities", "remote", "employment_type", "salary",
    "requirements.graduation", "requirements.days_per_week",
    "requirements.min_months", "requirements.education", "requirements.skills",
    "return_offer", "published_at", "deadline",
)
# List fields whose every item must appear in the field's own evidence.
ITEMIZED_FIELDS = ("cities", "requirements.skills")

MAX_RAW_TEXT = 50_000
MAX_NAME = 200

_ID = re.compile(r"^job_[0-9a-f]{12}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FOLDED_AWAY = re.compile(r"[\s\u200b-\u200d\u2060\ufeff]+")


def normalize_for_match(text: str) -> str:
    """Fold what copying a JD changes: width (NFKC), case, whitespace, zero-width characters."""
    return _FOLDED_AWAY.sub("", unicodedata.normalize("NFKC", text).casefold())


def validate(record) -> list[str]:
    """Return every problem with a job record as "<field path>: <message>"; [] means valid."""
    if not isinstance(record, dict):
        return ["record: must be a JSON object"]
    errors: list[str] = []
    _check_keys(record, TOP_LEVEL_KEYS, "", errors)

    if "schema_version" in record:
        version = record["schema_version"]
        if not _is_int(version) or version != SCHEMA_VERSION:
            errors.append(f"schema_version: must be {SCHEMA_VERSION}")
    if "id" in record and not (isinstance(record["id"], str) and _ID.match(record["id"])):
        errors.append("id: must be job_ followed by 12 lowercase hex digits")
    if "source" in record:
        _check_source(record["source"], errors)
    for key in ("title", "company"):
        if key in record:
            _check_text(record[key], key, errors)
    if "cities" in record:
        _check_text_list(record["cities"], "cities", errors)
    for key in ("remote", "return_offer"):
        if key in record:
            _check_bool(record[key], key, errors)
    if "employment_type" in record:
        _check_enum(record["employment_type"], EMPLOYMENT_TYPES, "employment_type", errors)
    if "salary" in record:
        _check_salary(record["salary"], errors)
    if "requirements" in record:
        _check_requirements(record["requirements"], errors)
    for key in ("published_at", "deadline"):
        if key in record:
            _check_date(record[key], key, errors)
    if "status" in record:
        _check_enum(record["status"], STATUSES, "status", errors, nullable=False)
    if "guard" in record:
        _check_guard(record["guard"], errors)
    if "raw_text" in record:
        _check_raw_text(record["raw_text"], errors)
    if "evidence" in record:
        _check_evidence(record, errors)
    return errors


def _check_keys(obj: dict, expected, path: str, errors: list) -> None:
    prefix = f"{path}." if path else ""
    for key in expected:
        if key not in obj:
            errors.append(f"{prefix}{key}: missing (use null, or [] for a list, when the JD does not say)")
    for key in obj:
        if key not in expected:
            errors.append(f"{prefix}{key}: unknown field")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return (_is_int(value) or isinstance(value, float)) and math.isfinite(value)


def _check_text(value, path: str, errors: list) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}: must be null or a non-empty string")
    elif len(value) > MAX_NAME:
        errors.append(f"{path}: longer than {MAX_NAME} characters")


def _check_text_list(value, path: str, errors: list) -> None:
    if not isinstance(value, list):
        errors.append(f"{path}: must be a list ([] when the JD does not say)")
        return
    seen = set()
    for index, item in enumerate(value):
        where = f"{path}[{index}]"
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{where}: must be a non-empty string")
            continue
        if len(item) > MAX_NAME:
            errors.append(f"{where}: longer than {MAX_NAME} characters")
        folded = normalize_for_match(item)
        if folded in seen:
            errors.append(f"{where}: duplicate of an earlier item")
        seen.add(folded)


def _check_bool(value, path: str, errors: list, nullable: bool = True) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, bool):
        errors.append(f"{path}: must be true, false or null" if nullable else f"{path}: must be true or false")


def _check_enum(value, choices, path: str, errors: list, nullable: bool = True) -> None:
    if value is None and nullable:
        return
    if value not in choices:
        errors.append(f"{path}: must be one of {', '.join(choices)}" + (" or null" if nullable else ""))


def _check_int_range(value, low: int, high: int, path: str, errors: list) -> None:
    if value is None:
        return
    if not _is_int(value) or not low <= value <= high:
        errors.append(f"{path}: must be null or a whole number from {low} to {high}")


def _check_date(value, path: str, errors: list) -> None:
    if value is None:
        return
    valid = isinstance(value, str) and bool(_DATE.match(value))
    if valid:
        try:
            date.fromisoformat(value)
        except ValueError:
            valid = False
    if not valid:
        errors.append(f"{path}: must be null or a date like 2026-10-27")


def _check_timestamp(value, path: str, errors: list) -> None:
    parsed = None
    if isinstance(value, str):
        # Python 3.10's fromisoformat does not accept a trailing "Z".
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            parsed = None
    if parsed is None or parsed.tzinfo is None:
        errors.append(f"{path}: must be an ISO 8601 time with a UTC offset, like 2026-10-27T10:00:00+08:00")


def _check_source(source, errors: list) -> None:
    if not isinstance(source, dict):
        errors.append("source: must be an object")
        return
    _check_keys(source, SOURCE_KEYS, "source", errors)
    if "type" in source:
        _check_enum(source["type"], SOURCE_TYPES, "source.type", errors, nullable=False)
    if "site" in source:
        _check_enum(source["site"], SITES, "source.site", errors)
    if "url" in source:
        url = source["url"]
        if url is not None and not (isinstance(url, str) and url.startswith(("https://", "http://"))):
            errors.append("source.url: must be null or an http(s) URL")
        if url is None and source.get("type") == "url":
            errors.append("source.url: required when source.type is url")
    if "imported_at" in source:
        _check_timestamp(source["imported_at"], "source.imported_at", errors)


def _check_salary(salary, errors: list) -> None:
    if salary is None:
        return
    if not isinstance(salary, dict):
        errors.append("salary: must be null or an object")
        return
    _check_keys(salary, SALARY_KEYS, "salary", errors)
    amounts = {}
    for key in ("min", "max"):
        value = salary.get(key)
        if value is None:
            continue
        if _is_number(value) and value > 0:
            amounts[key] = value
        else:
            errors.append(f"salary.{key}: must be null or a positive number")
    if len(amounts) == 2 and amounts["min"] > amounts["max"]:
        errors.append("salary.min: greater than salary.max")
    if "unit" in salary:
        _check_enum(salary["unit"], SALARY_UNITS, "salary.unit", errors)
    if "months" in salary:
        _check_int_range(salary["months"], 12, 24, "salary.months", errors)
        if salary["months"] is not None and salary.get("unit") != "CNY/month":
            errors.append("salary.months: only used with unit CNY/month")
    if "negotiable" in salary:
        _check_bool(salary["negotiable"], "salary.negotiable", errors, nullable=False)
        if salary["negotiable"] is False:
            if salary.get("min") is None and salary.get("max") is None:
                errors.append("salary: give min or max, set negotiable to true, or use null when the JD names no salary")
            if salary.get("unit") is None:
                errors.append("salary.unit: required unless negotiable is true")


def _check_requirements(requirements, errors: list) -> None:
    if not isinstance(requirements, dict):
        errors.append("requirements: must be an object")
        return
    _check_keys(requirements, REQUIREMENT_KEYS, "requirements", errors)
    if "graduation" in requirements:
        _check_graduation(requirements["graduation"], errors)
    if "days_per_week" in requirements:
        _check_int_range(requirements["days_per_week"], 1, 7, "requirements.days_per_week", errors)
    if "min_months" in requirements:
        _check_int_range(requirements["min_months"], 1, 36, "requirements.min_months", errors)
    if "education" in requirements:
        _check_education(requirements["education"], errors)
    if "skills" in requirements:
        _check_text_list(requirements["skills"], "requirements.skills", errors)


def _check_graduation(graduation, errors: list) -> None:
    path = "requirements.graduation"
    if graduation is None:
        return
    if not isinstance(graduation, dict):
        errors.append(f"{path}: must be null or an object")
        return
    _check_keys(graduation, GRADUATION_KEYS, path, errors)
    if "years" in graduation:
        years = graduation["years"]
        if not (isinstance(years, list) and years and all(_is_int(y) and 2000 <= y <= 2100 for y in years)):
            errors.append(f"{path}.years: must be a non-empty list of graduation years such as 2027")
        elif len(set(years)) != len(years):
            errors.append(f"{path}.years: lists a year twice")
    if "strict" in graduation:
        _check_bool(graduation["strict"], f"{path}.strict", errors, nullable=False)


def _check_education(education, errors: list) -> None:
    path = "requirements.education"
    if education is None:
        return
    if not isinstance(education, dict):
        errors.append(f"{path}: must be null or an object")
        return
    _check_keys(education, EDUCATION_KEYS, path, errors)
    for key in EDUCATION_KEYS:
        if key in education:
            _check_enum(education[key], EDUCATION_LEVELS, f"{path}.{key}", errors)
    lowest, preferred = education.get("min"), education.get("preferred")
    if lowest is None and preferred is None and all(key in education for key in EDUCATION_KEYS):
        errors.append(f"{path}: use null instead of an object with no level")
    if lowest in EDUCATION_LEVELS and preferred in EDUCATION_LEVELS:
        if EDUCATION_LEVELS.index(preferred) < EDUCATION_LEVELS.index(lowest):
            errors.append(f"{path}.preferred: lower than requirements.education.min")


def _check_guard(guard, errors: list) -> None:
    if guard is None:
        return
    if not isinstance(guard, dict):
        errors.append("guard: must be null or an object")
        return
    _check_keys(guard, GUARD_KEYS, "guard", errors)
    if "verdict" in guard:
        _check_enum(guard["verdict"], GUARD_VERDICTS, "guard.verdict", errors, nullable=False)
    if "counts" in guard:
        counts = guard["counts"]
        if not (isinstance(counts, dict) and all(_is_int(n) and n >= 0 for n in counts.values())):
            errors.append("guard.counts: must map finding names to non-negative counts")


def _check_raw_text(raw, errors: list) -> None:
    if not isinstance(raw, str) or not raw.strip():
        errors.append("raw_text: must be the non-empty original JD text")
    elif len(raw) > MAX_RAW_TEXT:
        errors.append(f"raw_text: longer than {MAX_RAW_TEXT} characters; keep one JD per record")


def _field(record: dict, path: str):
    value = record
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _has_value(value) -> bool:
    return value is not None and value != []


def _check_evidence(record: dict, errors: list) -> None:
    evidence = record["evidence"]
    if not isinstance(evidence, dict):
        errors.append("evidence: must be an object keyed by field path")
        return
    raw = record.get("raw_text")
    haystack = normalize_for_match(raw) if isinstance(raw, str) else None
    for path, entry in evidence.items():
        where = f"evidence.{path}"
        if path not in EVIDENCE_FIELDS:
            errors.append(f"{where}: not a field that takes evidence")
            continue
        if not isinstance(entry, dict):
            errors.append(f"{where}: must be an object with text and method")
            continue
        _check_keys(entry, EVIDENCE_KEYS, where, errors)
        method = entry.get("method")
        if "method" in entry:
            _check_enum(method, EVIDENCE_METHODS, f"{where}.method", errors, nullable=False)
        if "text" not in entry or (entry["text"] is None and method == "user"):
            continue
        snippets = [entry["text"]] if isinstance(entry["text"], str) else entry["text"]
        if not (isinstance(snippets, list) and snippets and all(isinstance(s, str) and s.strip() for s in snippets)):
            errors.append(f"{where}.text: must be a non-empty string or list of strings (null only for user)")
            continue
        if method not in ("rule", "agent") or haystack is None:
            continue
        for snippet in snippets:
            if normalize_for_match(snippet) not in haystack:
                errors.append(f"{where}.text: not found in raw_text: {snippet!r}")
        if path in ITEMIZED_FIELDS and isinstance(_field(record, path), list):
            folded = [normalize_for_match(snippet) for snippet in snippets]
            for item in _field(record, path):
                if isinstance(item, str) and not any(normalize_for_match(item) in text for text in folded):
                    errors.append(f"{where}: {item!r} does not appear in its evidence text")
    for path in EVIDENCE_FIELDS:
        if _has_value(_field(record, path)) and path not in evidence:
            errors.append(f"{path}: has a value but no evidence; cite the JD text it came from, or use null")
