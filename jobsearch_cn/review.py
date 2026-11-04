"""Reviews of application materials (M3-3 part 2): the reviewer's findings, checked and rendered.

A review is the reviewer agent's verdict on one version of one material, written as JSON next to the
material (data/materials/<job id>/review-<n>-r<round>.json). Every finding names a checklist item and,
when it is about one place, the path of that place in the material. The machine draft gives the reviewer
a starting point: which of the JD's skills the material covers in the JD's own wording, in another
spelling, or not at all, and the style rules that are only warnings. See docs/cn/review-format.md and the
checklist in docs/cn/review-checklist.md.
"""
from __future__ import annotations

import hashlib
import json
import re

from jobsearch_cn import jd_parser, material as material_mod, profile as profile_mod, schema, score

REVIEW_VERSION = 1
KINDS = ("resume-review",)
TOP_LEVEL_KEYS = ("schema_version", "kind", "job_id", "material", "material_hash", "round", "mode",
                  "created", "verdict", "findings", "coverage")
FINDING_KEYS = ("item", "path", "severity", "reason", "suggestion")
COVERAGE_KEYS = ("requirement", "status", "where", "note")
MODES = ("independent", "self")  # self: the drafter's own session reviewed it, which the user must be told
VERDICTS = ("pass", "revise")
SEVERITIES = ("must", "suggest")
STATUSES = ("covered", "synonym", "gap")
MAX_ROUNDS = 2
# The notes `review draft` gives a gap. The machine only reads the skills list and the source text of
# the entries the material cites, so a skill in neither is left for the reviewer, never called missing.
GAP_UNUSED = "档案里有，材料没写"
GAP_IN_CITED_TEXT = "技能列表未列，所引条目原文里有，材料没写"
GAP_UNCHECKED = "技能列表未列，需核对经历原文"
MAX_TEXT = profile_mod.MAX_BULLET
# The items of docs/cn/review-checklist.md §2, by section.
CHECKLIST = {"A": 5, "B": 6, "C": 6, "D": 6, "E": 6, "F": 4}
ITEMS = tuple(f"{section}{n}" for section, count in CHECKLIST.items() for n in range(1, count + 1))

_PATH = re.compile(r"(?P<name>[a-z_]+)|\[(?P<index>\d+)\]")
_CJK = r"㐀-䶿一-鿿"
_SPACE_BETWEEN = re.compile(rf"[{_CJK}] +[A-Za-z0-9]|[A-Za-z0-9] +[{_CJK}]")
_HALF_WIDTH_PUNCT = re.compile(rf"[{_CJK}][,;:]|[,;:][{_CJK}]")
_FULL_STOP_END = re.compile(r"[。.．]\s*$")


def material_hash(material) -> str:
    """The digest a review records, so a review of an earlier version of the material is caught."""
    text = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve(material, path: str) -> bool:
    """Whether a path such as experience[0].bullets[1].text names something in the material."""
    node = material
    for part in path.split("."):
        tokens = list(_PATH.finditer(part))
        if not tokens or "".join(t.group(0) for t in tokens) != part or tokens[0].group("name") is None \
                or any(t.group("name") is not None for t in tokens[1:]):
            return False
        for token in tokens:
            if token.group("name") is not None:
                if not isinstance(node, dict) or token.group("name") not in node:
                    return False
                node = node[token.group("name")]
            else:
                # Compare lengths before int(): Python refuses to convert very long digit strings.
                digits = token.group("index").lstrip("0") or "0"
                if not isinstance(node, list) or len(digits) > len(str(len(node))) or int(digits) >= len(node):
                    return False
                node = node[int(digits)]
    return True


def validate(review, material) -> tuple[list, list]:
    """(errors, warnings) for a review of the given material; no errors means valid."""
    if not isinstance(review, dict):
        return ["review: must be a JSON object"], []
    errors, warnings = [], []
    profile_mod._keys(review, TOP_LEVEL_KEYS, "", errors)
    if review.get("schema_version") != REVIEW_VERSION or isinstance(review.get("schema_version"), bool):
        errors.append(f"schema_version: must be {REVIEW_VERSION}")
    if review.get("kind") not in KINDS:
        errors.append(f"kind: must be one of {', '.join(KINDS)}")
    for key in ("job_id", "material", "material_hash"):
        _text(review.get(key), key, errors)
    if isinstance(material, dict) and isinstance(review.get("job_id"), str) \
            and review["job_id"] != material.get("job_id"):
        errors.append(f"job_id: {review['job_id']!r} is not the material's job ({material.get('job_id')!r})")
    if isinstance(review.get("material_hash"), str) and review["material_hash"] != material_hash(material):
        errors.append("material_hash: the material has changed since this review; review the current version")
    rnd = review.get("round")
    if not isinstance(rnd, int) or isinstance(rnd, bool) or not 1 <= rnd <= MAX_ROUNDS:
        errors.append(f"round: must be 1 or {MAX_ROUNDS} (at most {MAX_ROUNDS} rounds)")
    schema._check_enum(review.get("mode"), MODES, "mode", errors, nullable=False)
    schema._check_timestamp(review.get("created"), "created", errors)
    schema._check_enum(review.get("verdict"), VERDICTS, "verdict", errors, nullable=False)

    must = _findings(review.get("findings"), material, errors) if "findings" in review else 0
    if "coverage" in review:
        _coverage(review["coverage"], material, errors)
    if review.get("verdict") == "pass" and must:
        errors.append(f"verdict: 'pass' with {must} 'must' finding(s); a pass has none")
    if not errors:
        if review.get("verdict") == "revise" and not must:
            warnings.append("verdict: 'revise' without a 'must' finding; is it a pass with suggestions?")
        if review.get("mode") == "self":
            warnings.append("mode: a self-review (the drafter's own session); tell the user it is not independent")
    return errors, warnings


def _text(value, where: str, errors: list, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{where}: must be a non-empty string" + (" or null" if nullable else ""))
    elif len(value) > MAX_TEXT:
        errors.append(f"{where}: longer than {MAX_TEXT} characters")


def _path(value, where: str, material, errors: list) -> None:
    if not isinstance(value, str) or not resolve(material, value):
        shown = repr(value) if not isinstance(value, str) or len(value) <= 80 else repr(value[:80] + "…")
        errors.append(f"{where}: {shown} is not a place in the material")


def _findings(value, material, errors: list) -> int:
    if not isinstance(value, list):
        errors.append("findings: must be a list ([] when there is nothing)")
        return 0
    must = 0
    for index, finding in enumerate(value):
        where = f"findings[{index}]"
        if not isinstance(finding, dict):
            errors.append(f"{where}: must be an object")
            continue
        profile_mod._keys(finding, FINDING_KEYS, where, errors)
        if finding.get("item") not in ITEMS:
            errors.append(f"{where}.item: {finding.get('item')!r} is not a checklist item (A1-F4)")
        if finding.get("path") is not None:
            _path(finding.get("path"), f"{where}.path", material, errors)
        schema._check_enum(finding.get("severity"), SEVERITIES, f"{where}.severity", errors, nullable=False)
        _text(finding.get("reason"), f"{where}.reason", errors)
        _text(finding.get("suggestion"), f"{where}.suggestion", errors, nullable=True)
        must += finding.get("severity") == "must"
    return must


def _coverage(value, material, errors: list) -> None:
    if not isinstance(value, list):
        errors.append("coverage: must be a list ([] when the JD lists nothing)")
        return
    for index, row in enumerate(value):
        where = f"coverage[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{where}: must be an object")
            continue
        profile_mod._keys(row, COVERAGE_KEYS, where, errors)
        _text(row.get("requirement"), f"{where}.requirement", errors)
        schema._check_enum(row.get("status"), STATUSES, f"{where}.status", errors, nullable=False)
        _text(row.get("note"), f"{where}.note", errors, nullable=True)
        places = row.get("where")
        if not isinstance(places, list):
            errors.append(f"{where}.where: must be a list")
            continue
        for number, place in enumerate(places):
            _path(place, f"{where}.where[{number}]", material, errors)
        if row.get("status") == "gap" and places:
            errors.append(f"{where}.where: a gap has no place in the material")
        if row.get("status") in ("covered", "synonym") and not places:
            errors.append(f"{where}.where: say where the material covers it")


def _texts(material: dict):
    """(path, text) for every text the drafter wrote."""
    summary = material.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("text"), str):
        yield "summary.text", summary["text"]
    for index, item in enumerate(material.get("experience") or []):
        for number, bullet in enumerate((item or {}).get("bullets") or []):
            if isinstance(bullet, dict) and isinstance(bullet.get("text"), str):
                yield f"experience[{index}].bullets[{number}].text", bullet["text"]


def draft(material: dict, profile: dict, job, vocabulary) -> dict:
    """The machine's starting point for a review: JD skill coverage and style warnings."""
    return {"coverage": coverage(material, profile, job, vocabulary), "style": style(material)}


def coverage(material: dict, profile: dict, job, vocabulary) -> list:
    """One row per skill the JD asks for: covered in its wording, covered by a synonym, or a gap.

    A gap's note says only what the machine can tell: the skill is in the profile's skills list; or the
    list lacks it but the source text of an entry the material cites names it; or neither, which is not
    proof the candidate lacks it (an entry the material leaves out may name it), so the reviewer checks.
    """
    if not isinstance(job, dict):
        return []
    held = {vocabulary.key(skill["name"]) for skill in profile.get("skills") or []
            if isinstance(skill, dict) and isinstance(skill.get("name"), str)}
    patterns = jd_parser._skill_patterns(vocabulary)
    cited = _cited_skills(material, profile, patterns)
    places = {}  # key -> [(path, surface)]
    for index, name in enumerate(material.get("skills") or []):
        if isinstance(name, str):
            places.setdefault(vocabulary.key(name), []).append((f"skills[{index}]", name))
    for path, text in _texts(material):
        claimed = []
        for _, pattern, key in patterns:
            for match in pattern.finditer(text):
                if any(match.start() < end and start < match.end() for start, end in claimed):
                    continue
                claimed.append((match.start(), match.end()))
                places.setdefault(key, []).append((path, match.group(0)))
    requirements = job.get("requirements") if isinstance(job.get("requirements"), dict) else {}
    names = [name for name in requirements.get("skills") or [] if isinstance(name, str)]
    groups = [[name for name in group if isinstance(name, str)]
              for group in requirements.get("skill_alternatives") or [] if isinstance(group, list)]
    spellings = {}  # key -> every spelling the JD uses for that skill, casefolded
    for name in names + [name for group in groups for name in group]:
        spellings.setdefault(vocabulary.key(name), set()).add(name.casefold())
    # The JD's skills as match scoring counts them: a skill_alternatives group is one item, at its first skill.
    items = score._requirements({"requirements": {"skills": names, "skill_alternatives": groups}}, vocabulary)
    found_in = {"places": places, "spellings": spellings, "held": held, "cited": cited}
    return [_coverage_row(item, found_in, vocabulary) for item in items]


def _coverage_row(item: list, found_in: dict, vocabulary) -> dict:
    """One coverage row for a skill, or for a group the JD lets the candidate choose from.

    A group is covered when any of its skills is, a synonym when none is covered but one is written
    another way, and otherwise a gap whose note names the skills the machine found something about.
    """
    members = []  # (name, status, where, note)
    for name in item:
        key = vocabulary.key(name)
        found = found_in["places"].get(key, [])
        where = list(dict.fromkeys(path for path, _ in found))
        if not found:
            note = (GAP_UNUSED if key in found_in["held"] else
                    GAP_IN_CITED_TEXT if key in found_in["cited"] else GAP_UNCHECKED)
            members.append((name, "gap", [], note))
        elif any(surface.casefold() in found_in["spellings"][key] for _, surface in found):
            members.append((name, "covered", where, None))
        else:
            spelled = "、".join(dict.fromkeys(surface for _, surface in found))
            members.append((name, "synonym", where, f"材料写作 {spelled}，JD 写作 {name}；档案支持的话改用 JD 的写法"))
    label = score._label(item)
    for status in ("covered", "synonym"):
        chosen = [member for member in members if member[1] == status]
        if chosen:
            where = list(dict.fromkeys(path for member in chosen for path in member[2]))
            note = None if status == "covered" else "；".join(member[3] for member in chosen)
            return {"requirement": label, "status": status, "where": where, "note": note}
    for note in (GAP_UNUSED, GAP_IN_CITED_TEXT, GAP_UNCHECKED):
        named = [member[0] for member in members if member[3] == note]
        if named:
            if len(item) > 1 and note != GAP_UNCHECKED:
                note = f"{'、'.join(named)}：{note}"
            return {"requirement": label, "status": "gap", "where": [], "note": note}
    raise AssertionError("an item has at least one skill")


def _cited_skills(material: dict, profile: dict, patterns) -> set:
    """Vocabulary keys of the skills named in the source text of the profile entries the material cites."""
    refs = set()
    summary = material.get("summary")
    if isinstance(summary, dict):
        refs.update(summary.get("refs") or [])
    for section in ("education", "experience", "awards", "certificates", "languages"):
        for item in material.get(section) or []:
            if not isinstance(item, dict):
                continue
            refs.add(item.get("ref"))
            for bullet in item.get("bullets") or []:
                if isinstance(bullet, dict):
                    refs.update(bullet.get("refs") or [])
    entries, keys = material_mod._entries(profile), set()
    for ref in refs:
        if isinstance(ref, str) and ref in entries:
            text = material_mod._source_text(*entries[ref])
            keys.update(key for _, pattern, key in patterns if pattern.search(text))
    return keys


def style(material: dict) -> list:
    """Warnings for checklist E1 and E3; they never fail a material."""
    warnings = []
    for path, text in _texts(material):
        if path != "summary.text" and _FULL_STOP_END.search(text):
            warnings.append(f"{path}: E1 ends with a full stop; bullets end without one")
        if _HALF_WIDTH_PUNCT.search(text):
            warnings.append(f"{path}: E1 use full-width punctuation (，；：) in Chinese text")
        if _SPACE_BETWEEN.search(text):
            warnings.append(f"{path}: E3 no space between Chinese and English or numbers")
    return warnings


_LABELS = {"must": "必改", "suggest": "建议", "covered": "已覆盖", "synonym": "同义可改", "gap": "缺口",
           "pass": "通过", "revise": "需修改", "independent": "独立审核", "self": "自审"}


def markdown(review: dict) -> str:
    """A valid review as Markdown for the user; nothing is saved.

    Free text never breaks the structure it sits in: line breaks in it become <br> (_line), and in a
    table cell pipes are escaped too (_cell). Paths, enums and the timestamp are validated, so need neither.
    """
    lines = [f"# 审核结果：{_line(review['material'])}（第 {review['round']} 轮）", "",
             f"- 岗位：{_line(review['job_id'])}",
             f"- 结论：{_LABELS[review['verdict']]}",
             f"- 方式：{_LABELS[review['mode']]}" + ("（起草者自己的会话审核，不是独立审核）"
                                                   if review["mode"] == "self" else ""),
             f"- 时间：{review['created']}", "", "## 问题", ""]
    if not review["findings"]:
        lines.append("没有。")
    order = sorted(review["findings"], key=lambda f: (f["severity"] != "must", ITEMS.index(f["item"])))
    for finding in order:
        place = f" `{finding['path']}`" if finding["path"] else ""
        lines.append(f"- **{_LABELS[finding['severity']]}** {finding['item']}{place}：{_line(finding['reason'])}")
        if finding["suggestion"]:
            lines.append(f"  - 建议改成：{_line(finding['suggestion'])}")
    lines += ["", "## 岗位要求覆盖", ""]
    if not review["coverage"]:
        lines.append("没有列出。")
    else:
        lines += ["| 要求 | 情况 | 位置 | 说明 |", "| --- | --- | --- | --- |"]
        for row in review["coverage"]:
            where = "、".join(f"`{p}`" for p in row["where"]) or "-"
            cells = (_cell(row["requirement"]), _LABELS[row["status"]], where, _cell(row["note"] or "-"))
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _line(text: str) -> str:
    """Free text on one Markdown line: its line breaks become <br>, so it cannot end a list item or a heading."""
    return "<br>".join(text.splitlines())


def _cell(text: str) -> str:
    """Text for one Markdown table cell: a pipe or a line break in it must not split the row."""
    return _line(text.replace("\\", "\\\\").replace("|", "\\|"))
