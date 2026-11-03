"""Greetings, application emails and referral requests (M3-4): Material v1 kinds written to a template.

A template (jobsearch_cn/message_templates/<direction>.json, overridable under
<data dir>/templates/messages/) fixes, for one job direction, the slots a message is made of, their order,
which kinds of experience each prefers and the length limit. The Agent drafts the text; this module checks
it. Names, schools, job titles and contact details are not typed into a message: they are placeholders
({edu-1.school}, {job.title}) filled from the profile and the stored job when the message is rendered, so
a message has nowhere to invent them. Numbers and skills in the text are checked against what each segment
cites, as for a CV (material.py). See docs/cn/material.md.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from jobsearch_cn import material, profile as profile_mod, schema, score

KINDS = ("greeting", "email", "referral")
TOP_LEVEL_KEYS = ("schema_version", "kind", "job_id", "profile_hash", "created", "direction", "template",
                  "subject", "segments")
SEGMENT_KEYS = ("slot", "text", "refs")
SUBJECT_KEYS = ("text", "refs")
# The longest a message may be, in characters after its placeholders are filled. A template may set less,
# never more.
HARD_LIMITS = {"greeting": 150, "email": 600, "referral": 300}
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
_CONTACT_ANYWHERE = ("name",)
_CONTACT_SIGNATURE = ("phone", "email")
# Contact details typed by hand rather than through a placeholder.
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Wording that commits to a start date, days a week or a length of stay: it must cite the availability.
_COMMITMENT = re.compile(r"到岗|每周\s*\S{0,3}\s*天|实习\s*\S{0,4}\s*个月|一周\s*\S{0,3}\s*天")


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
    if data_dir is not None:
        user = Path(data_dir) / USER_DIR
        if user.is_dir():
            for path in sorted(user.glob("*.json")):
                if path.name != "banned.json":
                    found[path.stem] = _template(path)
    if DEFAULT not in found:
        raise TemplateError(f"no {DEFAULT} template")
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
                    banned[level].append({"reason": str(group.get("reason") or "用户自己加的禁用说法"),
                                          "words": [w for w in group.get("words") or [] if isinstance(w, str)],
                                          "patterns": [p for p in group.get("patterns") or []
                                                       if isinstance(p, str)]})
    for group in [*banned["errors"], *banned["warnings"], banned["referral_warnings"], banned["greeting_warnings"]]:
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
    for kind in KINDS:
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
    return f"{direction}/{kind}@{templates[direction]['revision']}"


def choose(job, profile: dict, vocabulary, templates: dict, direction: str = None) -> tuple[str, str]:
    """(direction, why) for a message to this job: the one asked for, else the JD's leading direction that
    the candidate also wants, else the candidate's first direction, else the default template."""
    if direction:
        if direction not in templates:
            raise TemplateError(f"no template for direction {direction!r} "
                                f"(there are: {', '.join(sorted(templates))})")
        return direction, "按 --direction 指定"
    wanted = [d for d in ((profile.get("target") or {}).get("directions") or []) if isinstance(d, str)]
    if isinstance(job, dict):
        groups = {group: len(items) for group, items in score.direction_skills(job, vocabulary).items()}
        shared = [d for d in wanted if d in groups]
        if shared:
            top = max(groups[d] for d in shared)
            pick = next(d for d in shared if groups[d] == top)
            if pick in templates:
                return pick, f"JD 的技能有 {groups[pick]} 项属于这个方向，也在你的求职方向里"
            return DEFAULT, f"JD 和你的求职方向都是 {pick}，但这个方向还没有模板，用通用模板"
    if wanted:
        if wanted[0] in templates:
            return wanted[0], "JD 的技能和你的求职方向没有交集（或没有岗位记录），用你的第一个求职方向"
        return DEFAULT, f"你的第一个求职方向 {wanted[0]} 还没有模板，用通用模板"
    return DEFAULT, "档案没写求职方向，用通用模板"


def template_for(job, profile: dict, vocabulary, templates: dict, kind: str, direction: str = None) -> dict:
    """What `material template` prints: the chosen template for one kind, and why it was chosen."""
    if kind not in KINDS:
        raise TemplateError(f"kind must be one of {', '.join(KINDS)}")
    picked, why = choose(job, profile, vocabulary, templates, direction)
    spec = templates[picked][kind]
    return {"direction": picked, "label": templates[picked].get("label"), "reason": why, "kind": kind,
            "template": template_id(picked, kind, templates), "spec": spec}


# ---------------------------------------------------------------- placeholders

def _resolve(name: str, profile: dict, job, entries: dict, slot: str, kind: str):
    """(value, the ref it needs, error) for one placeholder; value is None when it cannot be filled."""
    head, _, field = name.partition(".")
    if not field:
        return None, None, f"{{{name}}} is not a placeholder (write {{entry.field}}, e.g. {{edu-1.school}})"
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
            return None, None, f"{{{name}}}: contact placeholders are name, and phone and email in a signature"
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


def fill(text: str, profile: dict, job, entries: dict, slot: str, kind: str) -> tuple[str, list, list]:
    """(text with its placeholders filled, the refs they need, errors)."""
    needed, errors = [], []

    def one(match):
        value, ref, error = _resolve(match.group(1), profile, job, entries, slot, kind)
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
        availability = profile.get("availability") or {}
        return "\n".join(str(availability[key]) for key in _AVAILABILITY_FIELDS
                         if availability.get(key) is not None and not isinstance(availability.get(key), bool))
    return material._source_text(*entries[ref])


class _Checker:
    def __init__(self, record: dict, profile: dict, vocabulary, job, banned: dict, errors: list, warnings: list):
        self.kind = record.get("kind")
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
        text = value.get("text")
        if not isinstance(text, str) or not text.strip():
            self.errors.append(f"{where}.text: must be a non-empty string")
            return ""
        filled, needed, problems = fill(text, self.profile, self.job, self.entries, slot, self.kind)
        self.errors.extend(f"{where}.text: {problem}" for problem in problems)
        for ref in needed:
            if ref not in refs:
                self.errors.append(f"{where}.refs: must include {ref!r}, whose placeholder the text uses")
        written = _PLACEHOLDER.sub(" ", text)  # what the Agent wrote itself; placeholders are data
        # A hand-typed phone or email is reported as that (_wording), not as an invented number besides.
        self._invented(_EMAIL.sub(" ", _PHONE.sub(" ", written)), refs, f"{where}.text")
        self._wording(written, refs, f"{where}.text", slot)
        return filled

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
        if _COMMITMENT.search(text) and AVAILABILITY not in refs:
            self.errors.append(f"{where}: commits to a start date, days a week or a length of stay without "
                               f"citing {AVAILABILITY!r}; write what the profile's availability says, and cite it")
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


def _hits(group: dict, text: str, source: str) -> list:
    """The banned words a text uses, in order, once each; a word the cited entries themselves use passes
    (an award called 第一名, a course called 健康管理)."""
    found = []
    for pattern in group["compiled"]:
        for match in pattern.finditer(text):
            quote = match.group(0).strip(" ，,。！!")
            if quote and quote not in found and not (source and pattern.search(source)):
                found.append(quote)
    return found


def validate(record, profile: dict, vocabulary, job=None, templates: dict = None, banned: dict = None) \
        -> tuple[list, list]:
    """(errors, warnings) for a greeting, email or referral against the profile, the job and its template."""
    if not isinstance(record, dict):
        return ["material: must be a JSON object"], []
    templates = templates if templates is not None else load_templates()
    banned = banned if banned is not None else load_banned()
    errors, warnings = [], []
    profile_mod._keys(record, TOP_LEVEL_KEYS, "", errors)
    if record.get("schema_version") != material.MATERIAL_VERSION or isinstance(record.get("schema_version"), bool):
        errors.append(f"schema_version: must be {material.MATERIAL_VERSION}")
    kind = record.get("kind")
    if kind not in KINDS:
        return errors + [f"kind: must be one of {', '.join(KINDS)}"], []
    for key in ("job_id", "profile_hash"):
        schema._check_text(record.get(key), key, errors)
    schema._check_timestamp(record.get("created"), "created", errors)

    direction = record.get("direction")
    if not isinstance(direction, str) or direction not in templates:
        errors.append(f"direction: must be one of {', '.join(sorted(templates))}")
        return errors, []
    spec = templates[direction][kind]
    current = template_id(direction, kind, templates)
    named = record.get("template")
    if not isinstance(named, str) or named.rpartition("@")[0] != current.rpartition("@")[0]:
        errors.append(f"template: must be {current!r} (the direction and kind of this material)")

    checker = _Checker(record, profile, vocabulary, job, banned, errors, warnings)
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
    digest = record.get("profile_hash")
    if digest and digest != score.profile_hash(profile):
        warnings.insert(0, "profile_hash: the profile has changed since this material was written; "
                           "check it still holds")
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

def render(record: dict, profile: dict, job) -> str:
    """The message as plain text to copy, its placeholders filled. Validate it first."""
    entries = material._entries(profile)
    kind = record["kind"]
    parts = [fill(segment["text"], profile, job, entries, segment["slot"], kind)[0]
             for segment in record["segments"]]
    if kind == "greeting":
        return "".join(parts)
    if kind == "referral":
        return "\n".join(parts)
    subject = fill(record["subject"]["text"], profile, job, entries, None, kind)[0]
    return f"标题：{subject}\n\n" + "\n\n".join(parts)

