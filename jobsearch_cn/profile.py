"""Candidate profile (version 1) and its validator.

The profile lives in data/profile/ (gitignored, ADR-6): profile.json holds the
structured facts that filtering and scoring compare against job records;
notes.md holds free text for writing CVs and greetings; sources/ holds the
material the facts came from. docs/cn/profile.md is the field reference.

Conventions match the job schema: every key is present (null, or [] for a
list, when unknown), unknown keys are errors, and enums shared with job records
(education level, employment type, salary unit) use the same values so they
compare directly. Every fact names its source: a file under sources/, or
"user" for something the user said. A CV may only state what the profile holds.
"""

import re
from datetime import date

from jobsearch_cn import match, schema, vocab
from jobsearch_cn.schema import _check_bool, _check_enum, _check_int_range, _check_text, _is_int

PROFILE_VERSION = 1

SKILL_LEVELS = ("familiar", "working", "proficient", "expert")  # 了解 / 熟悉 / 熟练 / 精通
EXPERIENCE_TYPES = ("internship", "project", "research", "competition", "campus", "work")
USER_SOURCE = "user"

TOP_LEVEL_KEYS = (
    "schema_version", "contact", "graduation", "education", "availability", "target",
    "skills", "experience", "awards", "certificates", "languages", "exclusions",
)
CONTACT_KEYS = ("name", "phone", "email", "github", "website")
GRADUATION_KEYS = ("year", "month")
EDUCATION_KEYS = ("level", "school", "major", "start", "end", "gpa", "rank", "courses", "source")
AVAILABILITY_KEYS = ("start_date", "days_per_week", "months", "cities", "acceptable_cities", "remote_ok", "relocate")
TARGET_KEYS = ("employment_types", "roles", "industries", "salary_min", "directions", "weights")
SALARY_MIN_KEYS = ("amount", "unit")
# The scoring dimensions (M2-4; location since M2-6b).
WEIGHT_KEYS = ("skills", "direction", "experience", "salary", "location")
SKILL_KEYS = ("name", "level", "used_in", "source")
EXPERIENCE_KEYS = ("id", "type", "name", "org", "role", "start", "end", "bullets", "source")
AWARD_KEYS = ("name", "date", "source")
CERTIFICATE_KEYS = ("name", "detail", "date", "source")
LANGUAGE_KEYS = ("name", "level", "source")
EXCLUSION_KEYS = ("cities", "companies", "keywords")

MAX_BULLET = 300

_MONTH = re.compile(r"^\d{4}-\d{2}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EXPERIENCE_ID = re.compile(r"[a-z][a-z0-9-]{0,39}")  # fullmatch: "$" would let "exp-1\n" through


def validate(profile, sources=None, groups=None) -> list[str]:
    """Every problem with a profile as "<field path>: <message>"; [] means valid.

    sources is the set of file names under data/profile/sources/; when given,
    every non-"user" source must be one of them. groups is the set of skill
    vocabulary group keys (the user's included); when given, every
    target.directions entry must be one of them.
    """
    if not isinstance(profile, dict):
        return ["profile: must be a JSON object"]
    errors: list[str] = []
    _keys(profile, TOP_LEVEL_KEYS, "", errors)
    check = _Checker(errors, sources)

    if "schema_version" in profile and not (_is_int(profile["schema_version"])
                                            and profile["schema_version"] == PROFILE_VERSION):
        errors.append(f"schema_version: must be {PROFILE_VERSION}")
    if _obj(profile, "contact", CONTACT_KEYS, errors, name_unknown=False):
        for key in CONTACT_KEYS:
            _check_text(profile["contact"].get(key), f"contact.{key}", errors)
    if _obj(profile, "graduation", GRADUATION_KEYS, errors, nullable=True):
        graduation = profile["graduation"]
        if graduation.get("year") is None:
            errors.append("graduation.year: required when graduation is given")
        _check_int_range(graduation.get("year"), 2000, 2100, "graduation.year", errors)
        _check_int_range(graduation.get("month"), 1, 12, "graduation.month", errors)

    for index, item in check.items(profile, "education", EDUCATION_KEYS):
        where = f"education[{index}]"
        _check_enum(item.get("level"), schema.EDUCATION_LEVELS, f"{where}.level", errors, nullable=False)
        for key in ("school", "major", "gpa", "rank"):
            _check_text(item.get(key), f"{where}.{key}", errors)
        check.period(item, where)
        check.texts(item.get("courses"), f"{where}.courses")
        check.source(item, where)

    if _obj(profile, "availability", AVAILABILITY_KEYS, errors):
        availability = profile["availability"]
        _check_day(availability.get("start_date"), "availability.start_date", errors)
        _check_int_range(availability.get("days_per_week"), 1, 7, "availability.days_per_week", errors)
        _check_int_range(availability.get("months"), 1, 24, "availability.months", errors)
        # Cities compare as the filter and the score compare them (match._city): 深圳 and 深圳市 are one city,
        # within a tier and across the two. A field that is not a list has its error already; skip it.
        cities, acceptable = availability.get("cities"), availability.get("acceptable_cities")
        check.texts(cities, "availability.cities", fold=match._city)
        check.texts(acceptable, "availability.acceptable_cities", fold=match._city)
        preferred = {match._city(c) for c in cities if isinstance(c, str)} if isinstance(cities, list) else set()
        for index, city in enumerate(acceptable if isinstance(acceptable, list) else []):
            if isinstance(city, str) and match._city(city) in preferred:
                errors.append(f"availability.acceptable_cities[{index}]: {city!r} is already a preferred city "
                              "(availability.cities)")
        for key in ("remote_ok", "relocate"):
            _check_bool(availability.get(key), f"availability.{key}", errors)

    if _obj(profile, "target", TARGET_KEYS, errors):
        target = profile["target"]
        types = target.get("employment_types")
        check.texts(types, "target.employment_types")
        for index, value in enumerate(types if isinstance(types, list) else []):
            _check_enum(value, schema.EMPLOYMENT_TYPES, f"target.employment_types[{index}]", errors, nullable=False)
        check.texts(target.get("roles"), "target.roles")
        check.texts(target.get("industries"), "target.industries")
        salary = target.get("salary_min")
        if salary is not None and _obj(target, "salary_min", SALARY_MIN_KEYS, errors, path="target.salary_min"):
            amount = salary.get("amount")
            if not (schema._is_number(amount) and amount > 0):
                errors.append("target.salary_min.amount: must be a positive number")
            _check_enum(salary.get("unit"), schema.SALARY_UNITS, "target.salary_min.unit", errors, nullable=False)
        directions = target.get("directions")
        check.texts(directions, "target.directions")
        for index, key in enumerate(directions if isinstance(directions, list) else []):
            if key == vocab.GENERAL:
                errors.append(f"target.directions[{index}]: {vocab.GENERAL} holds office software every direction "
                              "uses; it is not a direction")
            elif isinstance(key, str) and groups is not None and key not in groups:
                choices = ", ".join(sorted(set(groups) - {vocab.GENERAL}))
                errors.append(f"target.directions[{index}]: {key!r} is not a skill vocabulary group ({choices})")
        weights = target.get("weights")
        if weights is not None:
            errors += weight_errors(weights)

    experience_ids = set()
    for index, item in check.items(profile, "experience", EXPERIENCE_KEYS):
        where = f"experience[{index}]"
        item_id = item.get("id")
        if not (isinstance(item_id, str) and _EXPERIENCE_ID.fullmatch(item_id)):
            errors.append(f"{where}.id: must be lowercase letters, digits and hyphens, like exp-1")
        elif item_id in experience_ids:
            errors.append(f"{where}.id: duplicate id {item_id!r}")
        else:
            experience_ids.add(item_id)
        _check_enum(item.get("type"), EXPERIENCE_TYPES, f"{where}.type", errors, nullable=False)
        # name: the project, contest or topic; org: where; role: the candidate's position.
        for key in ("name", "org", "role"):
            _check_text(item.get(key), f"{where}.{key}", errors)
        check.period(item, where)
        check.texts(item.get("bullets"), f"{where}.bullets", max_length=MAX_BULLET)
        check.source(item, where)

    for index, item in check.items(profile, "skills", SKILL_KEYS):
        where = f"skills[{index}]"
        _required_text(item.get("name"), f"{where}.name", errors)
        _check_enum(item.get("level"), SKILL_LEVELS, f"{where}.level", errors)
        used_in = item.get("used_in")
        check.texts(used_in, f"{where}.used_in")
        for ref in used_in if isinstance(used_in, list) else []:
            if isinstance(ref, str) and ref not in experience_ids:
                errors.append(f"{where}.used_in: no experience with id {ref!r}")
        check.source(item, where)
    check.unique_names(profile.get("skills"), "skills")

    for index, item in check.items(profile, "awards", AWARD_KEYS):
        _required_text(item.get("name"), f"awards[{index}].name", errors)
        _check_month(item.get("date"), f"awards[{index}].date", errors)
        check.source(item, f"awards[{index}]")
    for index, item in check.items(profile, "certificates", CERTIFICATE_KEYS):
        _required_text(item.get("name"), f"certificates[{index}].name", errors)
        _check_text(item.get("detail"), f"certificates[{index}].detail", errors)
        _check_month(item.get("date"), f"certificates[{index}].date", errors)
        check.source(item, f"certificates[{index}]")
    for index, item in check.items(profile, "languages", LANGUAGE_KEYS):
        _required_text(item.get("name"), f"languages[{index}].name", errors)
        _check_text(item.get("level"), f"languages[{index}].level", errors)
        check.source(item, f"languages[{index}]")

    if _obj(profile, "exclusions", EXCLUSION_KEYS, errors):
        for key in EXCLUSION_KEYS:
            check.texts(profile["exclusions"].get(key), f"exclusions.{key}")
    return errors


def weight_errors(weights, path: str = "target.weights") -> list[str]:
    """Every problem with a set of weights, the profile's or match list --weights': all five dimensions,
    each a number 0 or more, at least one above 0."""
    if not isinstance(weights, dict):
        return [f"{path}: must be an object"]
    errors = [f"{path}.{key}: missing; name all five ({', '.join(WEIGHT_KEYS)})"
              for key in WEIGHT_KEYS if key not in weights]
    errors += [f"{path}.{key}: unknown field" for key in weights if key not in WEIGHT_KEYS]
    errors += [f"{path}.{key}: must be a number, 0 or more" for key in WEIGHT_KEYS
               if key in weights and not (schema._is_number(weights[key]) and weights[key] >= 0)]
    if not errors and not any(weights.values()):
        errors.append(f"{path}: at least one weight must be above 0")
    return errors


# What leaving each open costs a job outside both tiers of cities, as match._location and score._location
# treat it: neither field alone settles every such job, so each message says when it still can.
_OPEN_ENDS = {
    "remote_ok": "a job elsewhere that offers remote work cannot count as remote for you: it scores on its city, "
                 "and unless you will move (relocate true) its location check stays unknown",
    "relocate": "unless a job elsewhere is remote and you accept that (remote_ok true), it scores 0 on location "
                "and its location check stays unknown",
}


def warnings(profile) -> list[str]:
    """What a valid profile leaves open that will cost answers later, as "<field path>: <message>"."""
    availability = profile.get("availability") if isinstance(profile, dict) else None
    if not isinstance(availability, dict) or not (availability.get("cities") or availability.get("acceptable_cities")):
        return []
    return [f"availability.{key}: null while you name cities; {cost}" for key, cost in _OPEN_ENDS.items()
            if availability.get(key) is None]


def redacted(profile: dict) -> dict:
    """The profile with contact details masked, for output that is not a CV.

    Details typed in the wrong shape are masked too. A contact that is not an object is masked whole. A field
    contact does not know is counted, never named: the name may be the detail itself ({"a@example.com": "138…"}).
    A top-level field the format does not know keeps its name, as profile validate reports it, but not its value.
    """
    copy = {key: (value if key in TOP_LEVEL_KEYS or value is None else "***") for key, value in profile.items()}
    contact = profile.get("contact")
    if isinstance(contact, dict):
        masked = {key: (None if contact[key] is None else "***") for key in CONTACT_KEYS if key in contact}
        if len(masked) < len(contact):
            masked["unknown_fields"] = len(contact) - len(masked)
        copy["contact"] = masked
    elif contact is not None:
        copy["contact"] = "***"
    return copy


def _keys(obj: dict, expected, path: str, errors: list, name_unknown: bool = True) -> None:
    prefix = f"{path}." if path else ""
    for key in expected:
        if key not in obj:
            errors.append(f"{prefix}{key}: missing (use null, or [] for a list, when unknown)")
    unknown = [key for key in obj if key not in expected]
    if name_unknown:
        errors.extend(f"{prefix}{key}: unknown field" for key in unknown)
    elif unknown:  # the name may be a contact detail typed as a key, so only the count goes out
        errors.append(f"{path}: {len(unknown)} unknown field(s), not named here; only {', '.join(expected)} belong")


def _obj(parent: dict, key: str, expected, errors: list, nullable: bool = False, path: str = None,
         name_unknown: bool = True) -> bool:
    """Check parent[key] is an object with exactly `expected` keys. True when its fields can be checked."""
    path = path or key
    if key not in parent:
        return False
    value = parent[key]
    if value is None and nullable:
        return False
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object" + (" or null" if nullable else ""))
        return False
    _keys(value, expected, path, errors, name_unknown)
    return True


def _required_text(value, path: str, errors: list) -> None:
    if value is None:
        errors.append(f"{path}: required")
    else:
        _check_text(value, path, errors)


def _check_month(value, path: str, errors: list) -> None:
    """null, YYYY-MM or YYYY-MM-DD."""
    if value is None:
        return
    text = value if isinstance(value, str) else ""
    if _MONTH.match(text):
        text += "-01"
    try:
        valid = bool(_DAY.match(text)) and bool(date.fromisoformat(text))
    except ValueError:
        valid = False
    if not valid:
        errors.append(f"{path}: must be null or a date like 2026-09 or 2026-09-01")


def _check_day(value, path: str, errors: list) -> None:
    if value is not None and not (isinstance(value, str) and _DAY.match(value)):
        errors.append(f"{path}: must be null or a date like 2026-11-15")
        return
    _check_month(value, path, errors)


class _Checker:
    def __init__(self, errors: list, sources):
        self.errors = errors
        self.sources = sources

    def items(self, parent: dict, key: str, expected):
        """(index, item) for each well-formed object in the list parent[key]."""
        value = parent.get(key)
        if key not in parent:
            return
        if not isinstance(value, list):
            self.errors.append(f"{key}: must be a list ([] when there is nothing)")
            return
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                self.errors.append(f"{key}[{index}]: must be an object")
                continue
            _keys(item, expected, f"{key}[{index}]", self.errors)
            yield index, item

    def texts(self, value, path: str, max_length: int = schema.MAX_NAME, fold=schema.normalize_for_match) -> None:
        """A list of distinct non-empty strings; fold says which two count as the same."""
        if not isinstance(value, list):
            self.errors.append(f"{path}: must be a list ([] when there is nothing)")
            return
        seen = set()
        for index, item in enumerate(value):
            where = f"{path}[{index}]"
            if not isinstance(item, str) or not item.strip():
                self.errors.append(f"{where}: must be a non-empty string")
                continue
            if len(item) > max_length:
                self.errors.append(f"{where}: longer than {max_length} characters")
            folded = fold(item)
            if folded in seen:
                self.errors.append(f"{where}: duplicate of an earlier item")
            seen.add(folded)

    def period(self, item: dict, where: str) -> None:
        start, end = item.get("start"), item.get("end")
        _check_month(start, f"{where}.start", self.errors)
        _check_month(end, f"{where}.end", self.errors)
        if isinstance(start, str) and isinstance(end, str) and start[:7] > end[:7]:
            self.errors.append(f"{where}: start is after end")

    def source(self, item: dict, where: str) -> None:
        value = item.get("source")
        if not isinstance(value, str) or not value.strip():
            self.errors.append(f"{where}.source: must be {USER_SOURCE!r} or a file name under sources/")
        elif value != USER_SOURCE and ("/" in value or "\\" in value or value.startswith(".")):
            self.errors.append(f"{where}.source: must be a plain file name under sources/, not a path")
        elif value != USER_SOURCE and self.sources is not None and value not in self.sources:
            self.errors.append(f"{where}.source: no file {value!r} in sources/")

    def unique_names(self, items, path: str) -> None:
        seen = set()
        for index, item in enumerate(items if isinstance(items, list) else []):
            name = item.get("name") if isinstance(item, dict) else None
            if isinstance(name, str):
                folded = schema.normalize_for_match(name)
                if folded in seen:
                    self.errors.append(f"{path}[{index}].name: duplicate of an earlier skill")
                seen.add(folded)
