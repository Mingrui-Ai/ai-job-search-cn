"""Greetings, application emails and referral requests (M3-4): Material v1 kinds written to a template.

A template (jobsearch_cn/message_templates/<direction>.json, overridable under
<data dir>/templates/messages/) fixes, for one job direction, the slots a message is made of, their order,
which kinds of experience each prefers and the length limit. The Agent drafts the text; this module checks
it. Names, schools, job titles and contact details are written as placeholders ({edu-1.school}, {job.title})
filled from the profile and the stored job when the message is rendered. The check refuses a phone, email,
WeChat or QQ id typed by hand and a brace left once the placeholders are filled; a school, company or name
typed by hand it cannot tell from any other words, so that is for the review (M3-6). Numbers and skills in
the text are checked against what each segment cites, as for a CV (material.py); days a week, months and the
start date against the profile's own availability field for each. See docs/cn/material.md.
"""
from __future__ import annotations

import json
import re
from fractions import Fraction
from pathlib import Path

from jobsearch_cn import material, profile as profile_mod, schema, score

LEGACY_KINDS = ("greeting", "email", "referral")
KINDS = (*LEGACY_KINDS, "followup")
TOP_LEVEL_KEYS = ("schema_version", "kind", "job_id", "profile_hash", "created", "direction", "template",
                  "subject", "segments")
SEGMENT_KEYS = ("slot", "text", "refs")
SUBJECT_KEYS = ("text", "refs")
# The longest a message may be, in characters after its placeholders are filled. A template may set less,
# never more.
HARD_LIMITS = {"greeting": 150, "email": 600, "referral": 300, "followup": 300}
HARD_SUBJECT_LIMIT = 40
DEFAULT = "default"
BUILTIN = Path(__file__).resolve().parent / "message_templates"
USER_DIR = Path("templates") / "messages"
TEMPLATE_VERSION = 1
JOB, AVAILABILITY = "job", "availability"
SIGNATURE = "signature"  # the email slot where the candidate's phone and email belong

# Placeholder -> (what it reads, the ref a segment must cite to use it).
_PLACEHOLDER = re.compile(r"\{([^{}\s]*)\}")
_ENTRY_FIELDS = {"education": ("school", "major", "level"), "experience": ("name", "org", "role")}
_AVAILABILITY_FIELDS = ("start_date", "days_per_week", "months")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_CONTACT_ANYWHERE = ("name", "github", "website")
_CONTACT_SIGNATURE = ("phone", "email")
_LINK_PLACEHOLDER = re.compile(r"\{contact\.(?:github|website)\}")  # filled with a link
# Contact details typed by hand rather than through a placeholder.
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# What a message promises about the availability, read clause by clause (_Checker._availability): a count of
# days a week or of months is compared with availability.days_per_week or availability.months alone, never
# with the digits of another field (2026-12-07 is no 12 months); a start is written {availability.start_date}.
_CLAUSE = re.compile(r"[^，,。；;！!？?\n]+")
_COUNT = (r"(?P<count>\{availability\.[a-z_]+\}"
          r"|\d+(?:\.\d+)?(?:\s*(?:-|~|～|－|—|到|至)\s*\d+(?:\.\d+)?)?"
          r"|[零〇一二两三四五六七八九十百几数半]+)")
# 三天内, 两个月后: when something happens, not how long; 后端 and 后台 are words.
_RELATIVE = r"(?:之?内|以内|之?后(?![端台])|以后)"
# Days a week: a count of days a few characters after 每周 or 一周 (每周可以到岗 4 天), or 4 天/周. 每周 alone is
# how often, not how many days, and 每周更新 3 篇推文持续 30 天 is no promise.
_DAYS = (re.compile(rf"[每一]\s*(?:个\s*)?(?:周|星期|礼拜)[^，,。；;！!？?\n\d{{}}]{{0,8}}?(?<![第今明后昨前当])"
                    rf"{_COUNT}\s*(?:个\s*)?(?:工作日|天)(?!\s*{_RELATIVE})"),
         re.compile(rf"(?<![第今明后昨前当\d]){_COUNT}\s*(?:个\s*)?(?:工作日|天)\s*[/／每]\s*(?:周|星期|礼拜)"))
# Months: a count in a clause about the stay (可以连续实习 6 个月); 实习了, 实习期间 and 实习生 tell of the past
# or of someone, not of how long the candidate can stay.
_STAY = re.compile(r"实习(?!了|过|生|经历|期间|中|的|时(?!长|间))|在岗|到岗|上岗|入职")
_MONTHS = re.compile(rf"(?<![上下第\d]){_COUNT}\s*(?P<unit>个半月|个多?月)(?!\s*{_RELATIVE})")
_YEARS = re.compile(r"(?<![上下前去今明后第\d])(?P<count>\{availability\.[a-z_]+\}|\d{1,2}(?:\.\d+)?|[一二两三半])"
                    rf"\s*年(?![级底初中末内前后度份制龄纪代轻])(?!\s*{_RELATIVE})")
_START = re.compile(r"到岗|入职|上岗|报到|到职|开始实习")
_START_PLACEHOLDER = "{availability.start_date}"
# A start verb commits to a date only with a time next to it: 随时可以入职 does, 期待入职贵司 does not. Every time
# but the placeholder is written by hand, and fails even beside it ({availability.start_date}或明天到岗).
_WHEN = re.compile(r"\{availability\.start_date\}|随时|马上|立即|立刻|即刻|即日|当[天日]|今天|明天|后天|现在|目前"
                   r"|下{1,2}个?(?:周|星期|礼拜|月)|[本这]个?(?:周|星期|礼拜|月)|月[初中底末]|年[初中底后]|尽[快早]"
                   r"|更早|提前|早[些点]|早一[点些]"
                   r"|第一时间|[上下]半年|暑假|寒假|暑期|(?:周|星期|礼拜)[一二三四五六日天]"
                   r"|\d{4}\s*年|\d{1,2}\s*月|\d{1,2}\s*[日号]|\d{1,2}\s*[-/]\s*\d{1,2}"
                   r"|[一二三四五六七八九十]+\s*[月号]")
# 两周后可以入职 promises a start; in 入职 2 周后独立负责 the time comes after the verb and tells something else.
_WITHIN = re.compile(rf"(?:\d+|[一二两三四五六七八九十几半]+)\s*个?\s*(?:天|周|星期|礼拜|月)\s*{_RELATIVE}")
# 周一至周五都可以到岗 promises days a week with no number in it.
_WEEKDAYS = re.compile(r"(?:周|星期|礼拜)[一二三四五六日天]\s*(?:到|至|-|~|～|—)\s*(?:周|星期|礼拜)?[一二三四五六日天]")
# Words that make a count a bound or a guess, not the profile's value (planner, 2026-11-04: equal, exactly):
# 至少 or 最多 anywhere before the count in its clause, 约 right before it, 以上, 起 or 左右 right after its unit.
_BOUND_BEFORE = re.compile(r"至少|最少|起码|最低|最短|最长|最多|至多|不少于|不低于|不短于|不小于|不多于|不超过|不大于"
                           r"|多于|少于|超过|大于|小于|高于|低于|不到|不足|大约|大概|大致|差不多|将近|接近")
_BOUND_RIGHT_BEFORE = re.compile(r"(?:约|近|超|逾)\s*$")
_BOUND_AFTER = re.compile(rf"\s*(?:以上|以下|起|左右|上下|前后|出头|有余|开外|多(?!数)|及以上|或以上|或以下"
                          rf"|或更[多长久少短]|甚至更[多长久]|更[多长久少短]|往上|打底|保底|不等|{_RELATIVE})")
# A days or months placeholder is followed by its unit and nothing that changes it: {availability.months}个半月
# would render as 6个半月 while the profile says 6.
_COUNT_PLACEHOLDER = re.compile(r"\{availability\.(?P<field>days_per_week|months)\}")
_UNIT_AFTER = {"days_per_week": re.compile(r"\s*(?:个\s*)?(?:工作日|天)"), "months": re.compile(r"\s*个\s*月")}
# {availability.start_date} is the earliest day the candidate can start: from it on (起, 以后) is that promise;
# by it (最晚, 之前), around it (左右) or earlier (或更早) is not. 不早于 (and 不会早于, 不先于) is not earlier than it,
# so that promise too: 早于 and 先于 count only when no 不 negates them (#123 P3).
_DATE_BOUND_BEFORE = re.compile(r"最晚|最迟|不晚于|不迟于|(?<!不)(?<!不会)(?<!不能)(?<!不得)(?:早于|先于)")
_DATE_BOUND_AFTER = re.compile(r"\s*(?:之前|以前|前后|前(?![往来去])|左右|上下|或更早|或之前|或提前)")
_UNITS = {"days_per_week": "天", "months": "个月"}
_FIELD_WORDS = {"days_per_week": "days a week", "months": "months"}
_NOT_GIVEN = "which the profile does not give; leave it out, or ask the user to add it to the profile"


class TemplateError(Exception):
    """A template file that cannot be read or does not have the template shape."""


# ---------------------------------------------------------------- templates

def load_templates(data_dir=None) -> dict:
    """direction -> template: the built-in ones, then the user's (a same-named file replaces a built-in one).

    A user template's limits are capped at HARD_LIMITS, so a user file can lower them, never raise them.
    """
    found = {}
    for path in sorted(BUILTIN.glob("*.json")):
        if path.name != "banned.json":
            found[path.stem] = _template(path)
    builtin_default = found.get(DEFAULT)
    followup_source = "builtin/default"
    if data_dir is not None:
        user = Path(data_dir) / USER_DIR
        if user.is_dir():
            for path in sorted(user.glob("*.json")):
                if path.name != "banned.json":
                    found[path.stem] = _template(path)
                    if path.stem == DEFAULT and "followup" in found[DEFAULT]:
                        followup_source = "user/default"
    if DEFAULT not in found:
        raise TemplateError(f"no {DEFAULT} template")
    provider = found[DEFAULT] if "followup" in found[DEFAULT] else builtin_default
    if provider is None or "followup" not in provider:
        raise TemplateError("no built-in default followup template")
    # Only this optional spec falls back; legacy overrides retain their own revision.
    found[DEFAULT]["followup"] = provider["followup"]
    found[DEFAULT]["_followup_identity"] = {"revision": provider["revision"], "source": followup_source}
    return found


def load_banned(data_dir=None) -> dict:
    """The banned wording: the built-in list, plus words and patterns a user file adds (it cannot remove any)."""
    banned = _read(BUILTIN / "banned.json")
    if data_dir is not None:
        user = Path(data_dir) / USER_DIR / "banned.json"
        if user.is_file():
            extra = _read(user)
            if not isinstance(extra, dict):
                raise TemplateError(f'{user}: expected {{"errors": [...], "warnings": [...]}}')
            for level in ("errors", "warnings"):
                groups = extra.get(level) or []
                if not isinstance(groups, list) or not all(isinstance(group, dict) for group in groups):
                    raise TemplateError(f"{user}: {level} must be a list of {{reason, words, patterns}}")
                for group in groups:
                    lists = {}
                    for key in ("words", "patterns"):
                        items = group.get(key)
                        items = [] if items is None else items
                        # "words": "简历" would ban 简 and 历 one by one, not the whole word.
                        if not isinstance(items, list) or not all(isinstance(item, str) and item for item in items):
                            raise TemplateError(f"{user}: {level}: {key} must be a list of non-empty strings")
                        lists[key] = items
                    banned[level].append({"reason": str(group.get("reason") or "用户自己加的禁用说法"), **lists})
    for group in [*banned["errors"], *banned["warnings"], banned["referral_warnings"], banned["greeting_warnings"],
                  banned["contact_errors"]]:
        try:
            group["compiled"] = [re.compile(re.escape(word)) for word in group.get("words") or []] + \
                                [re.compile(pattern) for pattern in group.get("patterns") or []]
        except re.error as exc:
            raise TemplateError(f"banned wording {group.get('reason')!r}: a pattern is not a regular expression "
                                f"({exc})") from None
    return banned


def _read(path: Path):
    try:
        return json.loads(path.read_bytes().decode("utf-8-sig"))
    except OSError as exc:
        raise TemplateError(f"cannot read {path}: {exc.strerror or exc}") from None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TemplateError(f"{path} is not UTF-8 JSON: {exc}") from None


def _template(path: Path) -> dict:
    doc = _read(path)
    where = str(path)
    if not isinstance(doc, dict) or doc.get("version") != TEMPLATE_VERSION or doc.get("direction") != path.stem:
        raise TemplateError(f'{where}: expected {{"version": {TEMPLATE_VERSION}, "direction": "{path.stem}", ...}}')
    # version is the file's format; revision counts changes to this template, so a message written to an
    # older revision gets a warning (validate).
    revision = doc.setdefault("revision", 1)
    if not _positive(revision):
        raise TemplateError(f"{where}: revision must be a positive integer")
    for kind in (*LEGACY_KINDS, *(("followup",) if "followup" in doc else ())):
        spec = doc.get(kind)
        if not isinstance(spec, dict) or not isinstance(spec.get("slots"), list) or not spec["slots"]:
            raise TemplateError(f"{where}: {kind}.slots must be a non-empty list")
        names = []
        for slot in spec["slots"]:
            if not isinstance(slot, dict) or not isinstance(slot.get("slot"), str):
                raise TemplateError(f"{where}: every slot in {kind}.slots needs a name")
            if not _positive(slot.get("max", 1)):
                raise TemplateError(f"{where}: {kind}.slots {slot['slot']!r}: max must be a positive integer")
            names.append(slot["slot"])
        if len(set(names)) != len(names):
            raise TemplateError(f"{where}: {kind}.slots names a slot twice")
        if kind == "followup" and (not {"context", "request"} <= set(names)
                                   or names != [name for name in ("context", "progress", "request") if name in names]
                                   or any(slot.get("required") is not True for slot in spec["slots"]
                                          if slot["slot"] in ("context", "request"))):
            raise TemplateError("followup: ordered context, optional progress, request slots; context/request required")
        limit = spec.get("max_chars", HARD_LIMITS[kind])
        if not _positive(limit):
            raise TemplateError(f"{where}: {kind}.max_chars must be a positive integer")
        spec["max_chars"] = min(limit, HARD_LIMITS[kind])
        if kind == "email":
            subject = spec.get("subject_max_chars", HARD_SUBJECT_LIMIT)
            if not _positive(subject):
                raise TemplateError(f"{where}: email.subject_max_chars must be a positive integer")
            spec["subject_max_chars"] = min(subject, HARD_SUBJECT_LIMIT)
    return doc


def _positive(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def template_id(direction: str, kind: str, templates: dict) -> str:
    if kind == "followup":
        return f"default/followup@{templates[DEFAULT]['_followup_identity']['revision']}"
    return f"{direction}/{kind}@{templates[direction]['revision']}"


def choose(job, profile: dict, vocabulary, templates: dict, direction: str = None) -> tuple[str, str]:
    """(direction, why) for a message to this job: the one asked for, else the JD's leading direction that
    the candidate also wants, else the candidate's first direction, else the default template. A direction
    with no template of its own (design, finance; any skill vocabulary group) uses the default one."""
    if direction:
        if direction in templates:
            return direction, "按 --direction 指定"
        groups = sorted(getattr(vocabulary, "groups", None) or {})
        if direction in groups:
            return DEFAULT, f"按 --direction 指定 {direction}，这个方向还没有模板，用通用模板 {DEFAULT}"
        raise TemplateError(f"no direction {direction!r}: a direction is one with a template "
                            f"({', '.join(sorted(templates))}) or a skill vocabulary group ({', '.join(groups)}), "
                            f"which uses the {DEFAULT} template")
    wanted = [d for d in ((profile.get("target") or {}).get("directions") or []) if isinstance(d, str)]
    if isinstance(job, dict):
        groups = {group: len(items) for group, items in score.direction_skills(job, vocabulary).items()}
        shared = [d for d in wanted if d in groups]
        if shared:
            top = max(groups[d] for d in shared)
            pick = next(d for d in shared if groups[d] == top)
            if pick in templates:
                return pick, f"JD 的技能有 {groups[pick]} 项属于这个方向，也在你的求职方向里"
            return DEFAULT, f"JD 和你的求职方向都是 {pick}，但这个方向还没有模板，用通用模板 {DEFAULT}"
    if wanted:
        if wanted[0] in templates:
            return wanted[0], "JD 的技能和你的求职方向没有交集（或没有岗位记录），用你的第一个求职方向"
        return DEFAULT, f"你的第一个求职方向 {wanted[0]} 还没有模板，用通用模板 {DEFAULT}"
    return DEFAULT, f"档案没写求职方向，用通用模板 {DEFAULT}"


def template_for(job, profile: dict, vocabulary, templates: dict, kind: str, direction: str = None) -> dict:
    """What `material template` prints: the chosen template for one kind, and why it was chosen."""
    if kind not in KINDS:
        raise TemplateError(f"kind must be one of {', '.join(KINDS)}")
    if kind == "followup":
        if direction not in (None, DEFAULT):
            raise TemplateError("followup only supports --direction default; no direction was silently changed")
        return {"direction": DEFAULT, "label": "跟进正文", "reason": "通用无标题跟进正文", "kind": kind,
                "template": template_id(DEFAULT, kind, templates), "spec": templates[DEFAULT][kind],
                "template_source": templates[DEFAULT]["_followup_identity"]["source"]}
    picked, why = choose(job, profile, vocabulary, templates, direction)
    spec = templates[picked][kind]
    return {"direction": picked, "label": templates[picked].get("label"), "reason": why, "kind": kind,
            "template": template_id(picked, kind, templates), "spec": spec}


# ---------------------------------------------------------------- placeholders

def _resolve(name: str, profile: dict, job, entries: dict, slot: str, kind: str, followup=None):
    """(value, the ref it needs, error) for one placeholder; value is None when it cannot be filled."""
    head, _, field = name.partition(".")
    if not field:
        return None, None, f"{{{name}}} is not a placeholder (write {{entry.field}}, e.g. {{edu-1.school}})"
    if head.startswith("evt_"):
        if kind != "followup" or followup is None or head not in followup.events:
            return None, None, "event placeholder: no usable effective event in this application's context"
        if field != "occurred_date":
            return None, None, "event placeholder: only occurred_date is supported"
        value = followup.events[head]["occurred_date"]
        if value is None:
            return None, head, "event occurred_date is unknown; omit the date, never use recorded_at"
        year, month, day = map(int, value.split("-"))
        return f"{year}年{month}月{day}日", head, None
    if head == JOB:
        if field not in ("title", "company"):
            return None, None, f"{{{name}}}: a job placeholder is {{job.title}} or {{job.company}}"
        if not isinstance(job, dict):
            return None, JOB, f"{{{name}}}: the job is not in the job store, so there is nothing to fill it with"
        value = job.get(field)
        if not isinstance(value, str) or not value.strip():
            return None, JOB, f"{{{name}}}: the stored job has no {field}"
        return value, JOB, None
    if head == AVAILABILITY:
        if field not in _AVAILABILITY_FIELDS:
            return None, None, f"{{{name}}}: availability placeholders are {', '.join(_AVAILABILITY_FIELDS)}"
        value = (profile.get("availability") or {}).get(field)
        if value is None or isinstance(value, bool):
            return None, AVAILABILITY, f"{{{name}}}: the profile has no availability.{field}"
        if field == "start_date" and isinstance(value, str) and _DATE.fullmatch(value):
            year, month, day = (int(part) for part in value.split("-"))
            return f"{year}年{month}月{day}日", AVAILABILITY, None
        return str(value), AVAILABILITY, None
    if head == "contact":
        if field in _CONTACT_SIGNATURE:
            if kind != "email" or slot != SIGNATURE:
                return None, None, (f"{{{name}}}: the phone and the email belong only in an email's "
                                    f"{SIGNATURE} segment")
        elif field not in _CONTACT_ANYWHERE:
            return None, None, (f"{{{name}}}: contact placeholders are {', '.join(_CONTACT_ANYWHERE)}, and phone "
                                "and email in a signature")
        value = (profile.get("contact") or {}).get(field)
        if not isinstance(value, str) or not value.strip():
            return None, None, f"{{{name}}}: the profile has no contact.{field}"
        return value, None, None
    if head not in entries:
        return None, None, f"{{{name}}}: no profile entry with id {head!r}"
    section, entry = entries[head]
    if field not in _ENTRY_FIELDS.get(section, ()):
        allowed = ", ".join(_ENTRY_FIELDS.get(section, ())) or "none"
        return None, head, f"{{{name}}}: an {section} entry's placeholders are {allowed}"
    value = entry.get(field)
    if field == "level":
        value = material._DEGREES.get(value)  # 专科, 本科, 硕士, 博士: the words the CV prints
    if not isinstance(value, str) or not value.strip():
        return None, head, f"{{{name}}}: {head} has no {field}"
    return value, head, None


def fill(text: str, profile: dict, job, entries: dict, slot: str, kind: str, followup=None) -> tuple[str, list, list]:
    """(text with its placeholders filled, the refs they need, errors)."""
    needed, errors = [], []

    def one(match):
        value, ref, error = _resolve(match.group(1), profile, job, entries, slot, kind, followup)
        if ref and ref not in needed:
            needed.append(ref)
        if error:
            errors.append(error)
            return match.group(0)
        return value

    return _PLACEHOLDER.sub(one, text), needed, errors


# ---------------------------------------------------------------- checking

def _source(ref: str, profile: dict, job, entries: dict) -> str:
    """The text a citation stands for: numbers and skills in a segment must come from these."""
    if ref == JOB:
        return "\n".join(value for value in (job.get("title"), job.get("company")) if isinstance(value, str)) \
            if isinstance(job, dict) else ""
    if ref == AVAILABILITY:
        # Its days and months are checked field by field (_Checker._availability), its start date is written
        # {availability.start_date}; so it vouches for no other number, and a date's 12 is not 12 months.
        return ""
    if ref.startswith("evt_"):
        return ""  # progress/date refs never vouch for candidate numbers, skills or banned wording
    return material._source_text(*entries[ref])


class _Checker:
    def __init__(self, record: dict, profile: dict, vocabulary, job, banned: dict, errors: list, warnings: list,
                 followup=None):
        self.kind = record.get("kind")
        self.followup = followup
        self.profile, self.vocabulary, self.job, self.banned = profile, vocabulary, job, banned
        self.errors, self.warnings = errors, warnings
        self.entries = material._entries(profile)
        self.citations = material._Citations(errors, self.entries, profile, vocabulary)
        self.held = {vocabulary.key(skill["name"]) for skill in profile.get("skills") or []
                     if isinstance(skill, dict) and isinstance(skill.get("name"), str)}

    def refs(self, value, where: str) -> list:
        if not isinstance(value, list):
            self.errors.append(f"{where}: must be a list of profile entry ids ([] when it cites nothing)")
            return []
        good = []
        for index, ref in enumerate(value):
            path = f"{where}[{index}]"
            if ref == JOB:
                if not isinstance(self.job, dict):
                    self.errors.append(f"{path}: cites the job, but job_id is not in the job store")
                    continue
            elif ref == AVAILABILITY:
                if not isinstance(self.profile.get("availability"), dict):
                    self.errors.append(f"{path}: the profile has no availability")
                    continue
            elif self.kind == "followup" and isinstance(ref, str) and ref.startswith("evt_"):
                if self.followup is None or ref not in self.followup.events:
                    self.errors.append(f"{path}: not a usable effective event of the bound application")
                    continue
            elif ref == material.NOTES_REF:
                self.errors.append(f"{path}: a message does not cite {material.NOTES_REF}; only a CV's summary does")
                continue
            elif self.citations.ref(ref, path, None) is None:
                continue
            if ref in good:
                self.errors.append(f"{path}: {ref!r} is cited twice")
                continue
            good.append(ref)
        return good

    def segment(self, value, where: str, slot: str) -> str:
        """Check one piece of text; return it with its placeholders filled ('' when it is unusable)."""
        if not isinstance(value, dict):
            self.errors.append(f"{where}: must be an object")
            return ""
        keys = SUBJECT_KEYS if slot is None else SEGMENT_KEYS
        profile_mod._keys(value, keys, where, self.errors)
        refs = self.refs(value.get("refs"), f"{where}.refs")
        if self.kind == "followup" and self.followup is not None:
            if slot == "context" and self.followup.submitted_id not in refs:
                self.errors.append(f"{where}.refs: context must cite the effective submitted event")
            if slot == "progress" and not any(ref in self.followup.events for ref in refs):
                self.errors.append(f"{where}.refs: progress must cite a usable effective event")
        text = value.get("text")
        if not isinstance(text, str) or not text.strip():
            self.errors.append(f"{where}.text: must be a non-empty string")
            return ""
        filled, needed, problems = fill(text, self.profile, self.job, self.entries, slot, self.kind, self.followup)
        self.errors.extend(f"{where}.text: {problem}" for problem in problems)
        if not problems and ("{" in filled or "}" in filled):
            # { 回复 } or {{edu-1.school}} written by hand, or a profile or job value with braces in it.
            at = min(index for index in (filled.find("{"), filled.find("}")) if index >= 0)
            self.errors.append(f"{where}.text: once filled it still has a brace ({filled[max(0, at - 8):at + 9]!r}); "
                               "write each placeholder exactly as {entry.field} and no other braces, and fix a "
                               "profile or job value that has braces in it")
        for ref in needed:
            if ref not in refs:
                self.errors.append(f"{where}.refs: must include {ref!r}, whose placeholder the text uses")
        written = _PLACEHOLDER.sub(" ", text)  # what the Agent wrote itself; placeholders are data
        # The availability's counts and dates are checked against their own fields, not as numbers besides.
        checked = _blank(text, self._availability(text, refs, f"{where}.text"))
        # A hand-typed phone, email or WeChat id is reported as that (_wording), not as an invented number besides.
        self._invented(self._without_contacts(_PLACEHOLDER.sub(" ", checked)), refs, f"{where}.text")
        self._wording(written, refs, f"{where}.text", slot)
        if self.kind == "greeting":
            for link in _LINK_PLACEHOLDER.findall(text):
                self.warnings.append(f"{where}.text: {link!r} - {self.banned['greeting_warnings']['reason']}")
        return filled

    def _without_contacts(self, text: str) -> str:
        text = _EMAIL.sub(" ", _PHONE.sub(" ", text))
        for pattern in self.banned["contact_errors"]["compiled"]:
            text = pattern.sub(" ", text)
        return text

    def _availability(self, text: str, refs: list, where: str) -> list:
        """Check what the text promises about the availability; return the spans checked here.

        Days a week and months are the profile's availability.days_per_week and availability.months exactly,
        written in Arabic digits or as the placeholder (五天, 半年 cannot be checked, so they are refused), with
        no 至少, 以上, 起 or 左右 and no 个半月; a start is written {availability.start_date}, and no other time
        is written by hand beside it. A promise the profile has no value for fails, and any promise needs the
        segment to cite the availability.
        """
        availability = self.profile.get("availability")
        availability = availability if isinstance(availability, dict) else {}
        # Other placeholders are masked, so {exp-1.name} lends no digit or word; positions stay the same.
        masked = _PLACEHOLDER.sub(lambda m: m.group(0) if m.group(1).startswith(AVAILABILITY + ".")
                                  else "_" * len(m.group(0)), text)
        spans, problems, promised = [], [], False
        for clause in _CLAUSE.finditer(masked):
            body, taken = clause.group(0), []
            found = [(match, "days_per_week", False) for regex in _DAYS for match in regex.finditer(body)]
            if _STAY.search(body):
                found += [(match, "months", regex is _YEARS) for regex in (_MONTHS, _YEARS)
                          for match in regex.finditer(body)]
            # By position; of two reads of one count (每周 4 天, 4 天/周) the longer, so what follows is read after it.
            for match, field, years in sorted(found, key=lambda item: (item[0].start("count"), -item[0].end())):
                span = (match.start("count"), match.end())  # 4 天, not 每周可以到岗: 到岗 may still tell a start
                if any(span[0] < end and start < span[1] for start, end in taken):
                    continue
                promised = True
                # 至少 before an earlier count of the clause is that count's: look back to the count before.
                problem = _count_problem(match, field, years, availability, body[_since(taken, span[0]):span[0]])
                taken.append(span)
                if problem:
                    problems.append(f"{where}: {problem}")
            for match in _COUNT_PLACEHOLDER.finditer(body):
                # A placeholder the rules above did not read as a count still says the profile's value only with
                # its own unit: not {availability.months}月, not {availability.months}个月以内.
                if any(match.start() < end and start < match.end() for start, end in taken):
                    continue
                field = match.group("field")
                unit = _UNIT_AFTER[field].match(body, match.end())
                end = unit.end() if unit else match.end()
                quote = text[clause.start() + match.start():clause.start() + end].strip()
                if unit is None:
                    problems.append(f"{where}: {quote!r}: {_FIELD_WORDS[field]} are written "
                                    f"{match.group(0)}{_UNITS[field]}")
                else:
                    word = _bound(body[_since(taken, match.start()):match.start()], body, end)
                    if word:
                        problems.append(f"{where}: {_bound_problem(quote, word, field, availability)}")
                taken.append((match.start(), end))
            for match in re.finditer(re.escape(_START_PLACEHOLDER), body):
                bound = _DATE_BOUND_BEFORE.search(body, _since(taken, match.start()), match.start()) \
                    or _DATE_BOUND_AFTER.match(body, match.end())
                if bound:
                    problems.append(f"{where}: {bound.group(0).strip()!r} with {_START_PLACEHOLDER}: the profile gives "
                                    "the earliest day you can start, so write that day or from it on "
                                    f"({_START_PLACEHOLDER}起), not by it, before it, around it or earlier")
            if _START.search(body) or _STAY.search(body):
                for match in _WEEKDAYS.finditer(body):
                    taken.append(match.span())
                    promised = True
                    value = availability.get("days_per_week")
                    problems.append(f"{where}: {match.group(0)!r} promises days a week; " + (
                        f"write {value}天 or {{availability.days_per_week}}天" if _positive(value) else
                        f"it is availability.days_per_week, {_NOT_GIVEN}"))
            rest = _blank(body, taken)
            verbs = [match.start() for match in _START.finditer(rest)]
            times = [match.span() for match in _WHEN.finditer(rest)] + \
                    [match.span() for match in _WITHIN.finditer(rest) if verbs and match.end() <= verbs[-1]]
            if verbs and times:
                promised = True
                # The placeholder vouches for itself only: 明天 beside it is still written by hand.
                by_hand = sorted(span for span in times if rest[span[0]:span[1]] != _START_PLACEHOLDER)
                if by_hand:
                    quote = text[clause.start():clause.end()].strip()
                    pieces = ", ".join(dict.fromkeys(repr(rest[start:end].strip()) for start, end in by_hand))
                    start = availability.get("start_date")
                    if not isinstance(start, str) or not start:
                        problems.append(f"{where}: {quote!r} promises when you can start; it is "
                                        f"availability.start_date, {_NOT_GIVEN} (written by hand: {pieces})")
                    else:
                        problems.append(f"{where}: {quote!r} promises when you can start; write the date as "
                                        f"{{availability.start_date}} (the profile gives {start}), not by hand "
                                        f"and not as a word like 随时 or 明天 (written by hand: {pieces})")
                    taken += by_hand
            spans += [(clause.start() + start, clause.start() + end) for start, end in taken]
        if promised and AVAILABILITY not in refs:
            self.errors.append(f"{where}: commits to a start date, days a week or a length of stay without "
                               f"citing {AVAILABILITY!r}; write what the profile's availability says, and cite it")
        self.errors.extend(problems)
        return spans

    def _invented(self, text: str, refs: list, where: str) -> None:
        source = "\n".join(_source(ref, self.profile, self.job, self.entries) for ref in refs)
        known = {value for _, value in material.numbers(source)}
        for quote, number in material.numbers(text):
            if number not in known:
                cited = ", ".join(refs) or "nothing"
                self.errors.append(f"{where}: the number {quote!r} is not in what it cites ({cited}); use the "
                                   "figure the profile gives, or ask the user to add it to the profile")
        # A skill the job asks for, even one in its title, is not one the candidate has: only the profile counts.
        own = "\n".join(_source(ref, self.profile, self.job, self.entries) for ref in refs if ref != JOB)
        held = self.held | {key for _, _, key in self.citations._skills_in(own)}
        for term, key in sorted({(term, key) for _, term, key in self.citations._skills_in(text)}):
            if key not in held:
                self.errors.append(f"{where}: the skill {term!r} is neither in the profile's skills "
                                   "nor in the cited entries")

    def _wording(self, text: str, refs: list, where: str, slot) -> None:
        source = "\n".join(_source(ref, self.profile, self.job, self.entries) for ref in refs)
        if _PHONE.search(text) or _EMAIL.search(text):
            self.errors.append(f"{where}: a phone number or email typed by hand; use {{contact.phone}} or "
                               f"{{contact.email}} in an email's {SIGNATURE} segment")
        contacts = self.banned["contact_errors"]
        for hit in _hits(contacts, _EMAIL.sub(" ", _PHONE.sub(" ", text)), source):
            self.errors.append(f"{where}: {hit!r} - {contacts['reason']}")
        for group in self.banned["errors"]:
            for hit in _hits(group, text, source):
                self.errors.append(f"{where}: {hit!r} - {group['reason']}")
        for group in self.banned["warnings"]:
            for hit in _hits(group, text, source):
                self.warnings.append(f"{where}: {hit!r} - {group['reason']}")
        extra = {"referral": "referral_warnings", "greeting": "greeting_warnings"}.get(self.kind)
        if extra:
            group = self.banned[extra]
            for hit in _hits(group, text, source):
                self.warnings.append(f"{where}: {hit!r} - {group['reason']}")


def _blank(text: str, spans) -> str:
    """text with each span replaced by spaces, so the positions of the rest stay the same."""
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    return "".join(chars)


def _since(taken: list, start: int) -> int:
    """Where the text before start that belongs to it begins: the end of the last span checked before it."""
    return max((end for _, end in taken if end <= start), default=0)


def _bound(before: str, string: str, end: int, unit: str = ""):
    """The word that makes a count a bound or a guess rather than the profile's value, or None: 至少 or 最多 in
    the text before it, 约 right before it, 以上, 起 or 左右 right after its unit, or the unit 个半月 or 个多月."""
    if unit in ("个半月", "个多月"):
        return unit
    for found in (_BOUND_BEFORE.search(before), _BOUND_RIGHT_BEFORE.search(before), _BOUND_AFTER.match(string, end)):
        if found:
            return found.group(0).strip()
    return None


def _bound_problem(quote: str, word: str, field: str, availability: dict) -> str:
    value, unit, placeholder = availability.get(field), _UNITS[field], f"{{{AVAILABILITY}.{field}}}"
    exact = f"{value}{unit} or {placeholder}{unit}" if _positive(value) else f"{placeholder}{unit}"
    return (f"{quote!r}: {word!r} does not promise exactly the profile's availability.{field}; write {exact}, "
            "with nothing like 至少, 以上, 起, 左右 or 半")


def _count_problem(match, field: str, years: bool, availability: dict, before: str):
    """What is wrong with one count of days a week or months a message promises, or None. before is the text
    of its clause before it, back to the count before."""
    count, unit = match.group("count"), _UNITS[field]
    quote = match.string[match.start("count"):match.end()].strip()
    placeholder = f"{{{AVAILABILITY}.{field}}}"
    value = availability.get(field)
    if count.startswith("{"):
        if count != placeholder or years:
            return f"{quote!r}: {_FIELD_WORDS[field]} are written {placeholder}{unit}"
    elif value is None or isinstance(value, bool):
        return f"{quote!r} promises {_FIELD_WORDS[field]}; it is availability.{field}, {_NOT_GIVEN}"
    elif not count[0].isdigit():
        return (f"{quote!r}: write {_FIELD_WORDS[field]} in Arabic digits ({value}{unit}) or as {placeholder}{unit}, "
                "so they can be checked against the profile")
    word = _bound(before, match.string, match.end(), (match.groupdict().get("unit") or "").replace(" ", ""))
    if word:
        return _bound_problem(quote, word, field, availability)
    if count.startswith("{"):
        return None  # filled from the profile, and fill() reports a value the profile does not give
    figures = [Fraction(figure) for figure in re.findall(r"\d+(?:\.\d+)?", count)]
    if years:
        figures = [figure * 12 for figure in figures]
    if any(figure != value for figure in figures):
        return (f"{quote!r} is not the profile's availability.{field} ({value}); write {value}{unit} "
                f"or {placeholder}{unit}")
    return None


def _hits(group: dict, text: str, source: str) -> list:
    """The banned words a text uses, in order, once each; a word the cited entries themselves use passes
    (an internship whose own bullet says 覆盖率 100%)."""
    found = []
    for pattern in group["compiled"]:
        for match in pattern.finditer(text):
            quote = match.group(0).strip(" ，,。！!")
            if quote and quote not in found and not (source and pattern.search(source)):
                found.append(quote)
    return found


def validate(record, profile: dict, vocabulary, job=None, templates: dict = None, banned: dict = None, *, followup=None) \
        -> tuple[list, list]:
    """(errors, warnings) for a greeting, email or referral against the profile, the job and its template."""
    if not isinstance(record, dict):
        return ["material: must be a JSON object"], []
    templates = templates if templates is not None else load_templates()
    banned = banned if banned is not None else load_banned()
    errors, warnings = [], []
    kind = record.get("kind")
    profile_mod._keys(record, TOP_LEVEL_KEYS + (("context",) if kind == "followup" else ()), "", errors)
    if record.get("schema_version") != material.MATERIAL_VERSION or isinstance(record.get("schema_version"), bool):
        errors.append(f"schema_version: must be {material.MATERIAL_VERSION}")
    if kind not in KINDS:
        return errors + [f"kind: must be one of {', '.join(KINDS)}"], []
    if kind == "followup" and (followup is None or followup.context != record.get("context")):
        return errors + ["context: followup requires checked current source inputs"], []
    for key in ("job_id", "profile_hash"):
        schema._check_text(record.get(key), key, errors)
    schema._check_timestamp(record.get("created"), "created", errors)

    direction = record.get("direction")
    if kind == "followup" and direction != DEFAULT:
        return errors + ["direction: followup requires default"], []
    if not isinstance(direction, str) or direction not in templates:
        errors.append(f"direction: must be one of {', '.join(sorted(templates))}")
        return errors, []
    spec = templates[direction][kind]
    current = template_id(direction, kind, templates)
    named = record.get("template")
    head, _, revision = named.rpartition("@") if isinstance(named, str) else ("", "", "")
    if head != current.rpartition("@")[0]:
        errors.append(f"template: must be {current!r} (the direction and kind of this material)")
    elif not re.fullmatch(r"[1-9]\d*", revision):
        errors.append(f"template: the revision after @ must be a positive integer, as in {current!r}")
    if kind == "followup" and named != current:
        errors.append("template: followup must name the current effective template")

    checker = _Checker(record, profile, vocabulary, job, banned, errors, warnings, followup)
    subject = record.get("subject")
    subject_text = ""
    if kind == "email":
        if subject is None:
            errors.append("subject: an email needs a subject {text, refs}")
        else:
            subject_text = checker.segment(subject, "subject", None)
            if len(subject_text) > spec["subject_max_chars"]:
                errors.append(f"subject: {len(subject_text)} characters once filled; "
                              f"the limit is {spec['subject_max_chars']}")
    elif subject is not None:
        errors.append(f"subject: must be null for a {kind}")

    segments = record.get("segments")
    texts = []
    if not isinstance(segments, list) or not segments:
        errors.append("segments: must be a non-empty list")
    else:
        texts = _slots(segments, spec, checker, errors)
    if texts:
        length = sum(len(text) for text in texts)
        if length > spec["max_chars"]:
            errors.append(f"segments: {length} characters once filled; the limit for a {kind} is {spec['max_chars']}")

    if errors:
        return errors, []
    if named != current:
        warnings.insert(0, f"template: written to {named}, the template is now {current}; check the slots still fit")
    changed = material._profile_changed(record, profile)
    if changed:
        warnings.insert(0, changed)
    return errors, warnings


def _slots(segments: list, spec: dict, checker: _Checker, errors: list) -> list:
    order = [slot["slot"] for slot in spec["slots"]]
    limits = {slot["slot"]: slot.get("max", 1) for slot in spec["slots"]}
    counts, last, texts = {}, -1, []
    for index, segment in enumerate(segments):
        where = f"segments[{index}]"
        slot = segment.get("slot") if isinstance(segment, dict) else None
        if slot not in order:
            errors.append(f"{where}.slot: must be one of {', '.join(order)}")
            continue
        position = order.index(slot)
        if position < last:
            errors.append(f"{where}.slot: {slot!r} comes after {order[last]!r}; the order is {', '.join(order)}")
        last = max(last, position)
        counts[slot] = counts.get(slot, 0) + 1
        if counts[slot] > limits[slot]:
            errors.append(f"{where}.slot: at most {limits[slot]} {slot!r} segment(s)")
        texts.append(checker.segment(segment, where, slot))
    for slot in spec["slots"]:
        if slot.get("required") and slot["slot"] not in counts:
            errors.append(f"segments: the required {slot['slot']!r} segment is missing")
    return texts


# ---------------------------------------------------------------- rendering

def _filled(record: dict, profile: dict, job, followup=None) -> tuple:
    """(the subject or None, the segments) with their placeholders filled."""
    entries = material._entries(profile)
    kind = record["kind"]
    parts = [fill(segment["text"], profile, job, entries, segment["slot"], kind, followup)[0]
             for segment in record["segments"]]
    subject = fill(record["subject"]["text"], profile, job, entries, None, kind)[0] if kind == "email" else None
    return subject, parts


def render(record: dict, profile: dict, job, *, followup=None) -> str:
    """The message as plain text to copy, its placeholders filled. Validate it first."""
    subject, parts = _filled(record, profile, job, followup)
    kind = record["kind"]
    if kind == "greeting":
        return "".join(parts)
    if kind in ("referral", "followup"):
        return "\n".join(parts)
    return f"标题：{subject}\n\n" + "\n\n".join(parts)


def body_chars(record: dict, profile: dict, job, *, followup=None) -> int:
    """The characters the length limit counts (material.md 7.3): the filled segments, without an email's
    subject, the 标题： line or the line breaks render puts between segments. Validate it first."""
    return sum(len(part) for part in _filled(record, profile, job, followup)[1])

