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
TARGET_KEYS = ("employment_types", "roles", "industries", "salary_min", "salary_ideal", "salary_step", "meal_value",
               "salary_days_per_week", "one_meal_points", "directions", "weights")
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
_EXPERIENCE_ID = re.compile(r"^[a-z][a-z0-9-]{0,39}$")


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
    if _obj(profile, "contact", CONTACT_KEYS, errors):
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
        _check_salary_tiers(target, errors)
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
        if not (isinstance(item_id, str) and _EXPERIENCE_ID.match(item_id)):
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


def _check_salary_tiers(target: dict, errors: list) -> None:
    """The salary tiers (M2-6e): an ideal and a step score pay around 50; the meal value, the days a week a
    day rate counts and the points for one meal are optional. All null scores pay as before."""
    minimum, ideal, step = target.get("salary_min"), target.get("salary_ideal"), target.get("salary_step")
    for key, units in (("salary_ideal", schema.SALARY_UNITS), ("meal_value", schema.MEAL_ALLOWANCE_UNITS)):
        value = target.get(key)
        if value is not None and _obj(target, key, SALARY_MIN_KEYS, errors, path=f"target.{key}"):
            if not (schema._is_number(value.get("amount")) and value["amount"] > 0):
                errors.append(f"target.{key}.amount: must be a positive number")
            _check_enum(value.get("unit"), units, f"target.{key}.unit", errors, nullable=False)
    if isinstance(ideal, dict):
        if not isinstance(minimum, dict):
            errors.append("target.salary_ideal: set target.salary_min too; the tiers run from the minimum up")
        elif ideal.get("unit") != minimum.get("unit"):
            errors.append(f"target.salary_ideal.unit: must be target.salary_min's unit ({minimum.get('unit')})")
        elif (schema._is_number(ideal.get("amount")) and schema._is_number(minimum.get("amount"))
              and ideal["amount"] < minimum["amount"]):
            errors.append("target.salary_ideal.amount: below target.salary_min.amount")
    if step is not None and not (schema._is_number(step) and step > 0):
        errors.append("target.salary_step: must be null or a positive number, in the unit of target.salary_ideal")
    if "salary_ideal" in target and "salary_step" in target and (ideal is None) != (step is None):
        errors.append("target.salary_ideal, target.salary_step: give both or neither; without them salary scores "
                      "0 or 100 on target.salary_min alone")
    days = target.get("salary_days_per_week")
    if days is not None and not (schema._is_number(days) and 0 < days <= 7):
        errors.append("target.salary_days_per_week: must be null or the days worked a week, above 0 and up to 7")
    points = target.get("one_meal_points")
    if points is not None and not (schema._is_number(points) and 0 <= points <= 100):
        errors.append("target.one_meal_points: must be null or a number from 0 to 100")


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


def warnings(profile) -> list[str]:
    """What a valid profile leaves open that will cost answers later, as "<field path>: <message>"."""
    availability = profile.get("availability") if isinstance(profile, dict) else None
    if not isinstance(availability, dict) or not (availability.get("cities") or availability.get("acceptable_cities")):
        return []
    # With cities named but no word on remote work or moving, every job elsewhere is
    # location unknown: the filter cannot rule it in or out.
    return [f"availability.{key}: null while availability.cities is set; jobs in other cities will all be "
            "location unknown" for key in ("remote_ok", "relocate") if availability.get(key) is None]


def redacted(profile: dict) -> dict:
    """The profile with contact details masked, for output that is not a CV."""
    copy = dict(profile)
    if isinstance(profile.get("contact"), dict):
        copy["contact"] = {key: (None if value is None else "***") for key, value in profile["contact"].items()}
    return copy


def _keys(obj: dict, expected, path: str, errors: list) -> None:
    prefix = f"{path}." if path else ""
    for key in expected:
        if key not in obj:
            errors.append(f"{prefix}{key}: missing (use null, or [] for a list, when unknown)")
    for key in obj:
        if key not in expected:
            errors.append(f"{prefix}{key}: unknown field")


def _obj(parent: dict, key: str, expected, errors: list, nullable: bool = False, path: str = None) -> bool:
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
    _keys(value, expected, path, errors)
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
