"""Application materials (M3-1): a CV as choices and rewrites that cite profile entries by id.

A material holds no name, school, company or date of its own; rendering takes those from the cited entries.
What it does write - the rewritten bullets and the summary - is checked against what it cites: every number
must already be in the cited entries (written in figures or in Chinese), and every vocabulary skill must be
the candidate's. The summary may also cite notes.md, what the user said while building the profile (M3-2c).
See docs/cn/material.md.
"""
from __future__ import annotations

import re
import unicodedata
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
# The summary may cite the profile's free text. An entry id is lowercase letters, digits and hyphens, so a
# name with a dot cannot be one.
NOTES_REF = "notes.md"
# Two lines at the resume's loosest spacing, in the widths of a Chinese character (M3-2c ruling 1): 11pt on
# a 17.4 cm measure is 44 a line. Word's 10.5pt on 18 cm holds about 48.
SUMMARY_WIDTH = 88
SUMMARY_TITLE = "个人简介"
# A section of notes.md with this title is the log of preference changes (profile.md §4): weights and
# cities, not evidence for a summary.
_PREFERENCE_LOG = "偏好记录"
# What counts as a heading in notes.md (M3-2c, planner's ruling on the #115 review): an ATX heading only - at
# most three spaces, one to six #, then a space or the end of the line, and an optional closing run of #.
# Four spaces make an indented code block, and #标签 is no heading. Lines in a fenced code block or an HTML
# comment are no headings either. Setext headings and other HTML blocks are not read (material.md §6).
_HEADING = re.compile(r" {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*")
_COMMENT_START = re.compile(r" {0,3}<!--")
_COMMENT_END = "-->"
# A fenced code block (CommonMark): three or more backticks or tildes, indented at most three spaces. It
# closes at a fence of the same character, at least as long, with nothing after it; a backtick fence's
# info string has no backtick.
_FENCE = re.compile(r" {0,3}(`{3,}(?=[^`]*$)|~{3,})(.*)")
_HIGH_LEVELS = ("proficient", "expert")

# Numbers in figures, with a magnitude (2万) or a percent sign; 1,200 is one number.
_FIGURE = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(万|千|亿)?\s*[%％]?")
_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN_BIG = {"万": 10_000, "亿": 100_000_000}
_CN_RUN = "[零〇一二两三四五六七八九十百千万亿]+"
# Numbers in Chinese only where they are plainly numbers: 百分之三十, 六成, 三倍, 两万, 三十 / 一百二十. A lone
# 一 or 三 is left alone, since 统一, 一线 and 三方 are words, not counts.
_CN_NUMBER = re.compile(rf"(?P<percent>百分之)(?P<pct>{_CN_RUN})|(?P<run>{_CN_RUN})(?P<suffix>成|倍)?")
_MAGNITUDE = {"万": 10_000, "千": 1000, "亿": 100_000_000}
_ZEROS = "零〇"
# 千万 before an imperative is "by all means" (千万不要, 千万别), not ten million.
_NOT_A_COUNT_AFTER = {"千万": ("不", "别", "要", "莫", "勿", "记得", "记住", "务必", "注意", "小心", "当心")}


def _chinese_value(run: str):
    """The value of a run of Chinese numerals, or None if it is not one number.

    一百零二 is 102 and 一千零二十 1020 (零 holds an empty place); 一亿二千万 is 120000000 (万 groups what
    comes after 亿); 一万二 is 12000 and 三百五 350 (a last digit right after 百 or more counts one place
    down); 二〇二六, digits alone with a zero among them, reads digit by digit as 2026.
    """
    if run[0] in _CN_BIG:
        return None  # 万一 is a word, not a count of ten thousand
    if not any(char in _CN_UNITS or char in _CN_BIG for char in run):
        return int("".join(str(_CN_DIGITS[char]) for char in run))
    total, myriads, section, digit, zero, unit = 0, 0, 0, None, False, None
    for char in run:
        if char in _ZEROS:
            if digit is not None:
                return None  # 二零 in a number with units is two numbers
            zero = True
        elif char in _CN_DIGITS:
            if digit is not None:
                return None  # 一二 reads as two numbers
            digit = _CN_DIGITS[char]
        elif char in _CN_UNITS:
            section += (1 if digit is None else digit) * _CN_UNITS[char]
            digit, zero, unit = None, False, _CN_UNITS[char]
        else:
            part = section + (digit or 0)
            if char == "万":
                if not part:
                    return None  # 亿万 is a figure of speech
                myriads = part * _CN_BIG[char]
            else:
                total = (total + myriads + part) * _CN_BIG[char]
                myriads = 0
            section, digit, zero, unit = 0, None, False, _CN_BIG[char]
    tail = digit or 0
    if digit is not None and not zero and unit and unit >= 100:
        tail = digit * unit // 10
    return total + myriads + section + tail


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
        # A bare run counts only when it has a unit in it (三十, 两万) or is digits with a zero among them
        # (二〇二六); 一 or 三 alone is part of a word, and so is 零 in 零基础.
        if plain and not any(char in _CN_UNITS or char in _CN_BIG for char in run) \
                and not (len(run) > 1 and any(char in _ZEROS for char in run)):
            continue
        if plain and run in ("万", "千", "百", "十", "亿"):
            continue
        # Whole words: 千万记得 is "be sure to remember", 千万记录 ten million records.
        if plain and text.startswith(_NOT_A_COUNT_AFTER.get(run, ()), match.end()):
            continue
        value = _chinese_value(run)
        if value is None:
            continue
        if match.group("suffix") == "成":
            value *= 10
        found.append((match.group(0), Fraction(value)))
    return found


def validate(material, profile: dict, vocabulary, job: dict = None, notes: str = None) -> tuple[list, list]:
    """(errors, warnings) for a material against the profile it cites; no errors means valid.

    profile must already pass profile.validate. job is the stored JD the material is for, when there is one;
    it only adds warnings. notes is the text of the notes.md beside the profile (read_notes), None when there
    is none that reads as UTF-8; only a summary that cites notes.md needs it.
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
    schema._check_timestamp(material.get("created"), "created", errors)

    entries = _entries(profile)
    checker = _Citations(errors, entries, profile, vocabulary, notes)

    summary = material.get("summary")
    if summary is not None:
        if not isinstance(summary, dict):
            errors.append("summary: must be an object or null")
        else:
            profile_mod._keys(summary, SUMMARY_KEYS, "summary", errors)
            refs = checker.refs(summary.get("refs"), "summary.refs", section=None, notes=True)
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

    if "skills" in material:  # a missing key is already reported
        _skills(material["skills"], profile, vocabulary, errors)
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


def read_notes(path) -> str | None:
    """The text of a notes.md, or None when there is none or it is not UTF-8 (profile validate reports that)."""
    try:
        return path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def evidence(notes: str) -> str:
    """notes.md as a summary's evidence: all of it but the 偏好记录 section, which runs to the next heading
    of its level or above. Only _HEADING is a heading, and never inside a fenced code block or an HTML
    comment, whatever the line starts with."""
    kept, skipping, fence, comment = [], None, None, False
    for line in notes.splitlines():
        if fence:
            closing = _FENCE.fullmatch(line)
            if closing and closing.group(1)[0] == fence[0] and len(closing.group(1)) >= len(fence) \
                    and not closing.group(2).strip():
                fence = None
        elif comment:
            comment = _COMMENT_END not in line
        elif _FENCE.fullmatch(line):
            fence = _FENCE.fullmatch(line).group(1)
        elif _COMMENT_START.match(line):
            comment = _COMMENT_END not in line  # CommonMark: the block ends on the line holding -->
        else:
            heading = _HEADING.fullmatch(line)
            if heading:
                level = len(heading.group(1))
                if skipping is not None and level <= skipping:
                    skipping = None
                if skipping is None and heading.group(2) == _PREFERENCE_LOG:
                    skipping = level
        if skipping is None:
            kept.append(line)
    return "\n".join(kept)


def width(text: str) -> float:
    """How wide text prints, in Chinese characters: a letter, digit or half-width mark is half of one."""
    return sum(0.5 if unicodedata.east_asian_width(char) in ("Na", "H", "N") else 1 for char in text)


def _source_text(section: str, entry: dict) -> str:
    parts = []
    for field in SECTIONS[section]:
        value = entry.get(field)
        parts += value if isinstance(value, list) else [value] if isinstance(value, str) else []
    return "\n".join(parts)


class _Citations:
    def __init__(self, errors: list, entries: dict, profile: dict, vocabulary, notes=None):
        self.errors, self.entries, self.profile, self.vocabulary = errors, entries, profile, vocabulary
        self.notes = notes
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

    def refs(self, value, where: str, section, required=None, notes=False) -> list:
        """The ids cited by a refs list that resolve, and notes.md where it may be cited; at least one is
        needed."""
        if not isinstance(value, list) or not value:
            self.errors.append(f"{where}: must cite at least one profile entry id")
            return []
        good = []
        for index, ref in enumerate(value):
            if ref == NOTES_REF:
                if not notes:
                    self.errors.append(f"{where}[{index}]: only the summary may cite {NOTES_REF}")
                elif self.notes is None:
                    self.errors.append(f"{where}[{index}]: cites {NOTES_REF}, but there is no {NOTES_REF} beside "
                                       "the profile that reads as UTF-8 text")
                elif ref in good:
                    self.errors.append(f"{where}[{index}]: {NOTES_REF} is cited twice")
                else:
                    good.append(ref)
            elif self.ref(ref, f"{where}[{index}]", section) is not None:
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
        source = "\n".join(evidence(self.notes) if ref == NOTES_REF else _source_text(*self.entries[ref])
                           for ref in refs)
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
    summary = material.get("summary")
    if summary and width(summary["text"]) > SUMMARY_WIDTH:
        warnings.append(f"summary.text: about {width(summary['text']):g} characters wide, more than the two lines "
                        f"({SUMMARY_WIDTH}) a summary should take; shorten it")
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


# Rendering (M3-2): the flat content resume_pdf and resume_docx lay out, shaped as resume_templates/sample.json.
_DEGREES = {"associate": "专科", "bachelor": "本科", "master": "硕士", "phd": "博士"}
_EMPLOYMENT = {"internship": "实习", "campus": "校招", "experienced": "社招"}
_EXPERIENCE_TITLES = {"internship": "实习经历", "work": "工作经历", "project": "项目经历",
                      "research": "科研经历", "competition": "竞赛经历", "campus": "校园经历"}
# Headed by the project, contest or topic itself; the others by the employer or student body (profile.md).
_NAMED_FIRST = ("project", "research", "competition")
# Strongest first. A null level is a skill the profile found only in experience (profile.md, 填写约定).
_SKILL_LINES = (("expert", "精通"), ("proficient", "熟练"), ("working", "熟悉"), (None, "项目中使用"),
                ("familiar", "了解"))
CONTACT_SEPARATOR = " | "
DOT = " · "


def render(material: dict, profile: dict, vocabulary) -> dict:
    """The flat resume content for a material that passes validate(material, profile, vocabulary).

    Names, schools, dates and contact details come from the cited profile entries; the material adds
    which entries, in what order, the rewritten bullets, the courses and the skills. The summary, when the
    material has one, is the first section: a paragraph under the header (M3-2c). With none, the content is
    what it was before the summary was printed. Experience is split into one section per type, in the order
    the material first lists each type.
    """
    entries = _entries(profile)
    cited = lambda item: entries[item["ref"]][1]  # noqa: E731
    sections = []
    if material.get("summary"):
        sections.append({"title": SUMMARY_TITLE, "text": material["summary"]["text"]})
    education = [_education_entry(cited(item), item["courses"]) for item in material["education"]]
    if education:
        sections.append({"title": "教育经历", "entries": education})
    by_type = {}
    for item in material["experience"]:
        entry = cited(item)
        by_type.setdefault(entry["type"], []).append(_experience_entry(entry, item["bullets"]))
    sections += [{"title": _EXPERIENCE_TITLES[kind], "entries": items} for kind, items in by_type.items()]
    skills = _skill_lines(material["skills"], profile, vocabulary)
    if skills:
        sections.append({"title": "专业技能", "lines": skills})
    honours = _honour_lines([cited(item) for item in material["awards"]],
                            [cited(item) for item in material["certificates"]],
                            [cited(item) for item in material["languages"]])
    if honours:
        sections.append({"title": "荣誉与证书", "lines": honours})
    contact = profile["contact"]
    return {"name": contact.get("name") or "", "contact": _contact(contact), "intent": _intent(profile),
            "sections": sections}


def _month(value):
    """2025-09 or 2025-09-01 as 2025.09."""
    return value[:7].replace("-", ".") if value else None


def _dates(start, end) -> str:
    """2025.09 - 2027.06 with an ASCII hyphen; an open end is 至今 (M3-2 ruling d)."""
    start, end = _month(start), _month(end)
    if start:
        return f"{start} - {end or '至今'}"
    return end or ""


def _contact(contact: dict) -> str:
    return CONTACT_SEPARATOR.join(contact[key] for key in ("phone", "email", "github", "website") if contact.get(key))


def _intent(profile: dict) -> str:
    """求职意向 from the profile alone (M3-2 ruling b): roles and kind, cities, days and months, start."""
    target, availability = profile["target"], profile["availability"]
    roles = "、".join(target["roles"])
    kinds = "、".join(_EMPLOYMENT[kind] for kind in target["employment_types"])
    terms = []
    if "internship" in target["employment_types"]:
        if availability.get("days_per_week"):
            terms.append(f"每周 {availability['days_per_week']} 天")
        if availability.get("months"):
            terms.append(f"可实习 {availability['months']} 个月")
    start = availability.get("start_date")
    parts = [f"{roles}（{kinds}）" if roles and kinds else roles or kinds,
             "、".join(availability.get("cities") or []),
             "，".join(terms),
             f"{start.replace('-', '.')} 起可到岗" if start else ""]
    parts = [part for part in parts if part]
    return "求职意向：" + DOT.join(parts) if parts else ""


def _gpa(value):
    if not value:
        return None
    return value if "gpa" in value.casefold() or "绩点" in value else f"GPA {value}"


def _education_entry(entry: dict, courses: list) -> dict:
    bullets = []
    scores = [part for part in (_gpa(entry.get("gpa")), entry.get("rank")) if part]
    if scores:
        bullets.append("，".join(scores))
    if courses:
        bullets.append("主修课程：" + "、".join(courses))
    return {"left": entry.get("school") or "",
            "middle": DOT.join(part for part in (entry.get("major"), _DEGREES.get(entry.get("level"))) if part),
            "right": _dates(entry.get("start"), entry.get("end")), "bullets": bullets}


def _experience_entry(entry: dict, bullets: list) -> dict:
    first, second = ("name", "org") if entry["type"] in _NAMED_FIRST else ("org", "name")
    return {"left": entry.get(first) or entry.get(second) or "", "middle": entry.get("role") or "",
            "right": _dates(entry.get("start"), entry.get("end")), "bullets": [bullet["text"] for bullet in bullets]}


def _skill_lines(names: list, profile: dict, vocabulary) -> list:
    """One line per level, each in the material's order and spelling (a JD's spelling of the same skill)."""
    levels = {vocabulary.key(skill["name"]): skill.get("level") for skill in profile["skills"]}
    lines = []
    for level, label in _SKILL_LINES:
        listed = [name for name in names if levels.get(vocabulary.key(name)) == level]
        if listed:
            lines.append({"label": label, "rest": "、".join(listed)})
    return lines


def _joined(*parts) -> str:
    return " ".join(part for part in parts if part)


def _honour_lines(awards: list, certificates: list, languages: list) -> list:
    """Awards as name（2024.10）, certificates as name and detail, then each language whose level no
    listed certificate already says (M3-2 ruling c: 英语 CET-6 552 is not repeated under CET-6 552)."""
    texts = [f"{entry['name']}（{_month(entry['date'])}）" if entry.get("date") else entry["name"] for entry in awards]
    written = [_joined(entry["name"], entry.get("detail")) for entry in certificates]
    texts += written
    said = ["".join(text.split()).casefold() for text in written]
    for entry in languages:
        level = entry.get("level")
        if level and any("".join(level.split()).casefold() in text for text in said):
            continue
        texts.append(_joined(entry["name"], level))
    return [{"label": "", "rest": text} for text in texts]
