"""Application materials (M3-1): a CV as choices and rewrites that cite profile entries by id.

A material holds no name, school, company or date of its own; rendering takes those from the cited entries.
What it does write - the rewritten bullets and the summary - is checked against what it cites: every number
must already be in the cited entries (written in figures or in Chinese), and every vocabulary skill must be
the candidate's. See docs/cn/material.md.
"""
from __future__ import annotations

import re
from fractions import Fraction

from jobsearch_cn import jd_parser, profile as profile_mod, schema, score

MATERIAL_VERSION = 1
KINDS = ("resume",)  # greetings and emails (M3-4) will be further kinds of the same format

TOP_LEVEL_KEYS = ("schema_version", "kind", "job_id", "profile_hash", "created", "summary",
                  "education", "experience", "skills", "awards", "certificates", "languages")
SUMMARY_KEYS = ("text", "refs")
EDUCATION_KEYS = ("ref", "courses")
EXPERIENCE_KEYS = ("ref", "bullets")
BULLET_KEYS = ("text", "refs")
ENTRY_KEYS = ("ref",)
# The material section, the profile section its refs point into, and the profile fields a citation quotes.
SECTIONS = {
    "education": ("school", "major", "gpa", "rank", "courses"),
    "experience": ("name", "org", "role", "bullets"),
    "awards": ("name",),
    "certificates": ("name", "detail"),
    "languages": ("name", "level"),
}
MAX_TEXT = profile_mod.MAX_BULLET
_HIGH_LEVELS = ("proficient", "expert")

# Numbers in figures, with a magnitude (2万) or a percent sign; 1,200 is one number.
_FIGURE = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(万|千|亿)?")
_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN_BIG = {"万": 10_000, "亿": 100_000_000}
_CN_RUN = "[零〇一二两三四五六七八九十百千万亿]+"
# Numbers in Chinese only where they are plainly numbers: 百分之三十, 六成, 三倍, 两万, 三十 / 一百二十. A lone
# 一 or 三 is left alone, since 统一, 一线 and 三方 are words, not counts.
_CN_NUMBER = re.compile(rf"(?P<percent>百分之)(?P<pct>{_CN_RUN})|(?P<run>{_CN_RUN})(?P<suffix>成|倍)?")
_MAGNITUDE = {"万": 10_000, "千": 1000, "亿": 100_000_000}


def _chinese_value(run: str):
    """The value of a run of Chinese numerals such as 一百二十 or 两万, or None if it is not one number."""
    total, section, digit = 0, 0, None
    for char in run:
        if char in _CN_DIGITS:
            if digit is not None:
                return None  # 一二 reads as two numbers
            digit = _CN_DIGITS[char]
        elif char in _CN_UNITS:
            section += (1 if digit is None else digit) * _CN_UNITS[char]
            digit = None
        else:
            total = (total + section + (digit or 0)) * _CN_BIG[char]
            section, digit = 0, None
    return total + section + (digit or 0)


def numbers(text: str) -> list:
    """(quote, value) for every number in text; 62% and 百分之六十二 both give 62, 六成 gives 60."""
    found, taken = [], []
    for match in _FIGURE.finditer(text):
        value = Fraction(match.group(1).replace(",", ""))
        if match.group(2):
            value *= _MAGNITUDE[match.group(2)]
        found.append((match.group(0).strip(), value))
        taken.append((match.start(), match.end()))
    for match in _CN_NUMBER.finditer(text):
        if any(match.start() < end and start < match.end() for start, end in taken):
            continue
        run = match.group("pct") or match.group("run")
        plain = not (match.group("percent") or match.group("suffix"))
        # A bare run counts only when it has a unit in it (三十, 两万); 一 or 三 alone is part of a word.
        if plain and not any(char in _CN_UNITS or char in _CN_BIG for char in run):
            continue
        if plain and run in ("万", "千", "百", "十", "亿"):
            continue
        value = _chinese_value(run)
        if value is None:
            continue
        if match.group("suffix") == "成":
            value *= 10
        found.append((match.group(0), Fraction(value)))
    return found


def validate(material, profile: dict, vocabulary, job: dict = None) -> tuple[list, list]:
    """(errors, warnings) for a material against the profile it cites; no errors means valid.

    profile must already pass profile.validate. job is the stored JD the material is for, when there is one;
    it only adds warnings.
    """
    if not isinstance(material, dict):
        return ["material: must be a JSON object"], []
    errors, warnings = [], []
    profile_mod._keys(material, TOP_LEVEL_KEYS, "", errors)
    if material.get("schema_version") != MATERIAL_VERSION or isinstance(material.get("schema_version"), bool):
        errors.append(f"schema_version: must be {MATERIAL_VERSION}")
    if material.get("kind") not in KINDS:
        errors.append(f"kind: must be one of {', '.join(KINDS)}")
    for key in ("job_id", "profile_hash"):
        schema._check_text(material.get(key), key, errors)
    if not isinstance(material.get("created"), str) or not material.get("created", "").strip():
        errors.append("created: must be a non-empty string (an ISO 8601 time)")

    entries = _entries(profile)
    checker = _Citations(errors, entries, profile, vocabulary)

    summary = material.get("summary")
    if summary is not None:
        if not isinstance(summary, dict):
            errors.append("summary: must be an object or null")
        else:
            profile_mod._keys(summary, SUMMARY_KEYS, "summary", errors)
            refs = checker.refs(summary.get("refs"), "summary.refs", section=None)
            checker.text(summary.get("text"), "summary.text", refs)

    for section in SECTIONS:
        keys = {"education": EDUCATION_KEYS, "experience": EXPERIENCE_KEYS}.get(section, ENTRY_KEYS)
        items = material.get(section)
        if section not in material:
            continue
        if not isinstance(items, list):
            errors.append(f"{section}: must be a list ([] when there is nothing)")
            continue
        seen = set()
        for index, item in enumerate(items):
            where = f"{section}[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{where}: must be an object")
                continue
            profile_mod._keys(item, keys, where, errors)
            entry = checker.ref(item.get("ref"), f"{where}.ref", section)
            if entry is None:
                continue
            if item["ref"] in seen:
                errors.append(f"{where}.ref: {item['ref']!r} is listed twice")
            seen.add(item["ref"])
            if section == "education":
                _courses(item.get("courses"), entry, where, errors)
            if section == "experience":
                checker.bullets(item.get("bullets"), item["ref"], where)

    _skills(material.get("skills"), profile, vocabulary, errors)
    if not errors:
        warnings = _warnings(material, profile, vocabulary, job)
    return errors, warnings


def _entries(profile: dict) -> dict:
    """id -> (section, entry) for every profile entry that has an id."""
    found = {}
    for section in SECTIONS:
        for entry in profile.get(section) or []:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                found[entry["id"]] = (section, entry)
    return found


def _source_text(section: str, entry: dict) -> str:
    parts = []
    for field in SECTIONS[section]:
        value = entry.get(field)
        parts += value if isinstance(value, list) else [value] if isinstance(value, str) else []
    return "\n".join(parts)


class _Citations:
    def __init__(self, errors: list, entries: dict, profile: dict, vocabulary):
        self.errors, self.entries, self.profile, self.vocabulary = errors, entries, profile, vocabulary
        self.patterns = jd_parser._skill_patterns(vocabulary)

    def ref(self, value, where: str, section):
        """The cited entry, or None after reporting why it cannot be cited."""
        if not isinstance(value, str) or not value.strip():
            self.errors.append(f"{where}: must be the id of a profile entry")
            return None
        if value not in self.entries:
            message = f"{where}: no profile entry with id {value!r}"
            missing = [name for name in ([section] if section else SECTIONS)
                       if any(isinstance(entry, dict) and "id" not in entry
                              for entry in self.profile.get(name) or [])]
            if missing:
                message += (f"; {', '.join(missing)} has entries without an id, which cannot be cited - "
                            "run cn-setup to add the ids")
            self.errors.append(message)
            return None
        cited_section, entry = self.entries[value]
        if section and cited_section != section:
            self.errors.append(f"{where}: {value!r} is a {cited_section} entry, not {section}")
            return None
        return entry

    def refs(self, value, where: str, section, required=None) -> list:
        """The ids cited by a refs list that resolve; at least one is needed."""
        if not isinstance(value, list) or not value:
            self.errors.append(f"{where}: must cite at least one profile entry id")
            return []
        good = []
        for index, ref in enumerate(value):
            if self.ref(ref, f"{where}[{index}]", section) is not None:
                good.append(ref)
        if required and required not in value:
            self.errors.append(f"{where}: must include {required!r}, the entry this bullet sits under")
        return good

    def bullets(self, value, parent: str, where: str) -> None:
        if not isinstance(value, list):
            self.errors.append(f"{where}.bullets: must be a list ([] when there is nothing)")
            return
        for index, bullet in enumerate(value):
            path = f"{where}.bullets[{index}]"
            if not isinstance(bullet, dict):
                self.errors.append(f"{path}: must be an object")
                continue
            profile_mod._keys(bullet, BULLET_KEYS, path, self.errors)
            refs = self.refs(bullet.get("refs"), f"{path}.refs", section=None, required=parent)
            self.text(bullet.get("text"), f"{path}.text", refs)

    def text(self, value, where: str, refs: list) -> None:
        """A rewritten text: no number and no skill beyond what it cites."""
        if not isinstance(value, str) or not value.strip():
            self.errors.append(f"{where}: must be a non-empty string")
            return
        if len(value) > MAX_TEXT:
            self.errors.append(f"{where}: longer than {MAX_TEXT} characters")
        if not refs:
            return
        source = "\n".join(_source_text(*self.entries[ref]) for ref in refs)
        known = {value for _, value in numbers(source)}
        for quote, number in numbers(value):
            if number not in known:
                self.errors.append(
                    f"{where}: the number {quote!r} is not in the cited entries ({', '.join(refs)}); "
                    "use the figure the profile gives, or ask the user to add it to the profile")
        held = {self.vocabulary.key(skill["name"]) for skill in self.profile.get("skills") or []
                if isinstance(skill, dict) and isinstance(skill.get("name"), str)}
        held |= {key for _, _, key in self._skills_in(source)}
        for term, key in sorted({(term, key) for _, term, key in self._skills_in(value)}):
            if key not in held:
                self.errors.append(f"{where}: the skill {term!r} is neither in the profile's skills "
                                   "nor in the cited entries")

    def _skills_in(self, text: str) -> list:
        claimed, hits = [], []
        for term, pattern, key in self.patterns:
            for match in pattern.finditer(text):
                if any(match.start() < end and start < match.end() for start, end in claimed):
                    continue
                claimed.append((match.start(), match.end()))
                hits.append((match, term, key))
        return hits


def _courses(value, entry: dict, where: str, errors: list) -> None:
    if not isinstance(value, list):
        errors.append(f"{where}.courses: must be a list ([] when there is nothing)")
        return
    held = {schema.normalize_for_match(course) for course in entry.get("courses") or [] if isinstance(course, str)}
    seen = set()
    for index, course in enumerate(value):
        if not isinstance(course, str) or not course.strip():
            errors.append(f"{where}.courses[{index}]: must be a non-empty string")
            continue
        folded = schema.normalize_for_match(course)
        if folded not in held:
            errors.append(f"{where}.courses[{index}]: {course!r} is not among this education entry's courses")
        elif folded in seen:
            errors.append(f"{where}.courses[{index}]: duplicate of an earlier course")
        seen.add(folded)


def _skills(value, profile: dict, vocabulary, errors: list) -> None:
    if value is None and "skills" not in ():
        pass
    if not isinstance(value, list):
        errors.append("skills: must be a list ([] when there is nothing)")
        return
    held = {vocabulary.key(skill["name"]) for skill in profile.get("skills") or []
            if isinstance(skill, dict) and isinstance(skill.get("name"), str)}
    seen = set()
    for index, name in enumerate(value):
        if not isinstance(name, str) or not name.strip():
            errors.append(f"skills[{index}]: must be a non-empty string")
            continue
        key = vocabulary.key(name)
        if key not in held:
            errors.append(f"skills[{index}]: {name!r} is not in the profile's skills")
        elif key in seen:
            errors.append(f"skills[{index}]: duplicate of an earlier skill")
        seen.add(key)


def _warnings(material: dict, profile: dict, vocabulary, job) -> list:
    warnings = []
    digest = material.get("profile_hash")
    if digest and digest != score.profile_hash(profile):
        warnings.append("profile_hash: the profile has changed since this material was written; check it still holds")
    listed = {vocabulary.key(name) for name in material.get("skills") or []}
    for skill in profile.get("skills") or []:
        if skill.get("level") in _HIGH_LEVELS and vocabulary.key(skill["name"]) not in listed:
            warnings.append(f"skills: {skill['name']!r} is {skill['level']} in the profile but not listed")
    if isinstance(job, dict):
        held = {vocabulary.key(skill["name"]) for skill in profile.get("skills") or []}
        for name in ((job.get("requirements") or {}).get("skills") or []):
            if isinstance(name, str) and vocabulary.key(name) in held and vocabulary.key(name) not in listed:
                warnings.append(f"skills: the JD asks for {name!r}, which the profile has, but it is not listed")
    return warnings
