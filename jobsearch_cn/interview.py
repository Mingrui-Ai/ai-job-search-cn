"""Offline interview practice packs, current sources and exact factual references."""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

from jobsearch_cn import guard, profile, schema
from jobsearch_cn import interview_files as files

CONTEXT = "binding_version job_input_hash profile_input_hash bank_hash policy_version"
PACK_KEYS = "schema_version kind job_id created context direction requirements questions coverage"
QUESTION_KEYS = "id category origin question requirement_refs project_ref bank_ref facts unknowns"
_SLUG = re.compile(r"[a-z][a-z0-9-]{0,39}")
_BANK_ID = re.compile(r"[a-z][a-z0-9-]{0,39}\.[a-z][a-z0-9-]{0,59}")
_RESERVED = {"con", "prn", "aux", "nul", *("com" + str(i) for i in range(10)), *("lpt" + str(i) for i in range(10))}
_PRIVATE = re.compile(r"(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:https?|mailto|data|file|ftp):|www\.|\\\\|"
                      r"(?:\+?86[ -]?)?1[3-9](?:[ -]?\d){9}|"
                      r"(?:微信|微\s*信|wechat|weixin|QQ|扣扣|手机号|电话号码)\s*[:：号IDid\s]|"
                      r"[A-Za-z]:[\\/])", re.IGNORECASE)
_LONG_NUMBER = re.compile(r"(?:\d[ -]?){7,}")


def _text(value, limit=300):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _list(value, maximum):
    if not isinstance(value, list) or len(value) > maximum:
        files.fail("invalid", "interview list is invalid or exceeds its limit")
    return value


def _id(value, prefix):
    return isinstance(value, str) and re.fullmatch(prefix + r"-[1-9][0-9]{0,5}", value) is not None


def _unique(values):
    if any(not isinstance(value, str) for value in values) or len(set(values)) != len(values):
        files.fail("invalid", "interview identifiers or references must be unique strings")


def _version(value):
    return type(value) is int and value == 1


def _sensitive(value, contacts, *, long_numbers):
    if not isinstance(value, str):
        return True
    folded = unicodedata.normalize("NFKC", value)
    if any(unicodedata.category(char).startswith("C") and char not in "\n\t" for char in value):
        return True
    compact = re.sub(r"\s+", "", folded).casefold()
    return bool(_PRIVATE.search(folded) or _PRIVATE.search(compact) or
                (long_numbers and (_LONG_NUMBER.search(folded) or _LONG_NUMBER.search(compact))) or
                any(re.sub(r"\s+", "", unicodedata.normalize("NFKC", item)).casefold() in compact
                    for item in contacts if isinstance(item, str) and item.strip()))


def sensitive(value, contacts=()):
    return _sensitive(value, contacts, long_numbers=True)


def job_identifier(value, contacts):
    # Only the existing fixed opaque schema id bypasses the generic long-number heuristic.
    # Explicit phone patterns and known contact values remain prohibited.
    if not schema.is_job_id(value) or _sensitive(value, contacts, long_numbers=False):
        files.fail("unsafe_text", "interview job identifier is invalid or private")


def artifact_identifier(job_id, name, contacts):
    """Check both fixed path components and their outward relative representation."""
    job_identifier(job_id, contacts)
    text(name, contacts)
    # Components were checked individually; retain the narrow opaque-job-id treatment.
    if _sensitive("interviews/" + job_id + "/" + name, contacts, long_numbers=False):
        files.fail("unsafe_text", "interview artifact identifier is private")


def text(value, contacts=(), limit=300):
    if not _text(value, limit) or sensitive(value, contacts):
        files.fail("unsafe_text", "interview text is empty, too long, private or contains control characters")


def literal(value):
    """All external Markdown strings are literal CommonMark/GFM fenced text."""
    longest = max((len(match.group()) for match in re.finditer(r"`+", value)), default=0)
    fence = "`" * max(3, longest + 1)
    return fence + "\n" + value + ("" if value.endswith("\n") else "\n") + fence


@dataclass
class Inputs:
    context: dict
    job: dict
    profile: dict
    bank: dict
    selection: dict
    contacts: tuple
    entries: dict


def _source(root, parts, *, bound):
    try:
        return files.read(root, parts)
    except files.Error as exc:
        if exc.code == "missing_input":
            files.fail("stale_context" if bound else "not_found", "required interview source is missing")
        raise


def _bank(root, direction, contacts):
    if (not isinstance(direction, str) or not _SLUG.fullmatch(direction) or direction in _RESERVED
            or sensitive(direction, contacts)):
        files.fail("configuration", "interview direction must name a supported local configuration", 2)
    name = direction + ".json"
    parts = ("templates", "interviews", name)
    local = files.safe(root, parts, required=False)
    if local.exists():
        bank, origin = files.read(root, parts), "local"
    else:
        try:
            bank = files.read(Path(__file__).parent, ("interview_questions", name))
        except files.Error as exc:
            if exc.code == "missing_input":
                files.fail("configuration", "interview direction has no question configuration", 2)
            raise
        origin = "builtin"
    try:
        files.keys(bank, "schema_version direction revision provenance questions", "bank")
        if not _version(bank["schema_version"]) or bank["direction"] != direction or not files.positive(bank["revision"]):
            files.fail()
        provenance = bank["provenance"]
        files.keys(provenance, "kind source_ref license notice", "bank.provenance")
        if provenance["kind"] not in ("project_original", "user_provided_unverified"):
            files.fail()
        if not _text(provenance["source_ref"], 1000):
            files.fail()
        text(provenance["license"], contacts, 100)
        text(provenance["notice"], contacts, 300)
        items = _list(bank["questions"], 100)
        if not items:
            files.fail()
        identities = []
        for item in items:
            files.keys(item, "id prompt practice_kind tags prep_prompts", "bank.question")
            if not isinstance(item["id"], str) or not _BANK_ID.fullmatch(item["id"]):
                files.fail()
            if not item["id"].startswith(direction + ".") or item["practice_kind"] != "general":
                files.fail()
            text(item["id"], contacts)
            identities.append(item["id"])
            text(item["prompt"], contacts)
            for key in ("tags", "prep_prompts"):
                for value in _list(item[key], 8):
                    text(value, contacts)
        _unique(identities)
    except files.Error:
        files.fail("configuration", "selected interview question configuration is invalid or private", 2)
    return bank, {"direction": direction, "origin": origin, "name": name}


def load(root, job_id, direction="default", *, bound=False):
    if not schema.is_job_id(job_id):
        files.fail("invalid", "interview job id is invalid")
    raw_job = _source(root, ("jobs", job_id + ".json"), bound=bound)
    raw_profile = _source(root, ("profile", "profile.json"), bound=bound)
    try:
        job = schema.upgrade(deepcopy(raw_job))
        if schema.validate(job) or job.get("id") != job_id or profile.validate(raw_profile):
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        files.fail("invalid_source", "interview requires a valid saved job and profile")
    contacts = tuple(value for value in (raw_profile.get("contact") or {}).values() if isinstance(value, str) and value.strip())
    job_identifier(job_id, contacts)
    bank, selection = _bank(root, direction, contacts)
    context = {"binding_version": 1, "job_input_hash": files.digest(raw_job),
               "profile_input_hash": files.digest(raw_profile),
               "bank_hash": files.digest({"selection": selection, "bank": bank}), "policy_version": 1}
    return Inputs(context, job, raw_profile, bank, selection, contacts,
                  {item["id"]: item for item in raw_profile["experience"]})


def recheck(root, inputs):
    latest = load(root, inputs.job["id"], inputs.selection["direction"], bound=True)
    if latest.context != inputs.context:
        files.fail("stale_context", "interview sources or selected question configuration changed")


def catalog(inputs):
    withheld = 0
    def project(value):
        nonlocal withheld
        if value is None:
            return None
        if not _text(value, 1000) or sensitive(value, inputs.contacts):
            withheld += 1
            return None
        return value
    lines = []
    for index, value in enumerate(inputs.job["raw_text"].splitlines()):
        if value.strip():
            safe = project(value)
            lines.append({"line": index + 1, "text": safe, "withheld": safe is None})
    entries = []
    for entry in inputs.entries.values():
        if sensitive(entry["id"], inputs.contacts):
            withheld += 1
            continue  # An unusable locator withholds the entire entry; never invent a replacement id.
        fields = {key: project(entry[key]) for key in ("name", "org", "role")}
        fields["bullets"] = [{"index": i, "text": project(value)} for i, value in enumerate(entry["bullets"])]
        entries.append({"ref": entry["id"], "type": entry["type"],
                        "source_type": "user" if entry["source"] == profile.USER_SOURCE else "source_file", **fields})
    return {"job": {"id": inputs.job["id"], "title": project(inputs.job["title"]),
                    "company": project(inputs.job["company"]), "lines": lines},
            "experience": entries, "withheld_count": withheld,
            "bank": {"direction": inputs.bank["direction"], "revision": inputs.bank["revision"],
                     "origin": inputs.selection["origin"], "provenance": {key: inputs.bank["provenance"][key]
                      for key in ("kind", "license", "notice")}, "questions": deepcopy(inputs.bank["questions"])}}


def template(root, job_id, direction=None):
    inputs = load(root, job_id, direction or "default")
    result = {"draft_ready": False, "context": inputs.context, "catalog": catalog(inputs),
              "warnings": ["direction_unspecified"] if direction is None else [],
              "guard": guard.summary(guard.check(inputs.job["raw_text"])[1]),
              "draft": {"schema_version": 1, "kind": "interview-prep", "job_id": job_id, "created": files.now(),
                        "context": inputs.context, "direction": inputs.selection["direction"],
                        "requirements": [], "questions": [], "coverage": []}}
    recheck(root, inputs)
    return result


def shape(pack):
    files.keys(pack, PACK_KEYS, "pack")
    if not _version(pack["schema_version"]) or pack["kind"] != "interview-prep" or not schema.is_job_id(pack["job_id"]):
        files.fail("invalid", "interview pack version, kind or job id is invalid")
    files.timestamp(pack["created"])
    files.keys(pack["context"], CONTEXT, "context")
    context = pack["context"]
    if not _version(context["binding_version"]) or not _version(context["policy_version"]):
        files.fail("invalid", "interview context version is unsupported")
    if not all(files.hash_value(context[key]) for key in ("job_input_hash", "profile_input_hash", "bank_hash")):
        files.fail("invalid", "interview context hashes must be lowercase SHA-256")
    if not isinstance(pack["direction"], str) or not _SLUG.fullmatch(pack["direction"]):
        files.fail("invalid", "interview direction is invalid")
    _list(pack["requirements"], 20)
    if not 1 <= len(_list(pack["questions"], 20)) <= 20:
        files.fail("invalid", "a deliverable interview pack requires one to twenty questions")
    _list(pack["coverage"], 20)


def check(pack, inputs):
    """Exact references prove source presence; independent review still checks meaning and assumptions."""
    shape(pack)
    if pack["context"] != inputs.context:
        files.fail("stale_context", "interview source context is stale; take a new template and review again")
    requirements = {}
    for item in pack["requirements"]:
        files.keys(item, "id quote", "requirement")
        if not _id(item["id"], "req") or item["id"] in requirements:
            files.fail("invalid", "requirement ids must be unique")
        text(item["id"], inputs.contacts)
        text(item["quote"], inputs.contacts, 500)
        if item["quote"] not in inputs.job["raw_text"]:
            files.fail("invalid_reference", "requirement quote is not an exact job excerpt")
        # A substring of a withheld source line must not escape the withholding boundary.
        if not any(item["quote"] in line and not sensitive(line, inputs.contacts)
                   and _text(line, 1000) for line in inputs.job["raw_text"].splitlines()):
            files.fail("unsafe_text", "requirement refers to a withheld job excerpt")
        if item["quote"] in requirements.values():
            files.fail("invalid", "requirement quotes must not be duplicated")
        requirements[item["id"]] = item["quote"]
    question_ids, unknown_ids = [], []
    actual = {key: [] for key in requirements}
    bank_questions = {item["id"]: item for item in inputs.bank["questions"]}
    project_count = 0
    for question in pack["questions"]:
        files.keys(question, QUESTION_KEYS, "question")
        if not _id(question["id"], "q"):
            files.fail("invalid", "question id is invalid")
        text(question["id"], inputs.contacts)
        question_ids.append(question["id"])
        text(question["question"], inputs.contacts)
        category = question["category"]
        if category not in ("jd", "project", "general") or question["origin"] != (
                "bank_practice" if category == "general" else "agent_practice"):
            files.fail("invalid", "question category and practice origin do not agree")
        refs = _list(question["requirement_refs"], 20); _unique(refs)
        if any(ref not in requirements for ref in refs) or (category == "jd" and not refs):
            files.fail("invalid_reference", "question requirement references are invalid")
        for ref in refs:
            actual[ref].append(question["id"])
        facts = _list(question["facts"], 8)
        if category == "project":
            project_count += 1
            reference = question["project_ref"]
            if not isinstance(reference, str) or reference not in inputs.entries or not facts:
                files.fail("invalid_reference", "project question needs an existing experience and facts")
            text(reference, inputs.contacts)
            entry = inputs.entries[reference]
            locators = []
            for fact in facts:
                if not isinstance(fact, dict):
                    files.fail()
                field = fact.get("field")
                files.keys(fact, "ref field quote index" if field == "bullets" else "ref field quote", "fact")
                if fact["ref"] != reference or field not in ("name", "org", "role", "bullets"):
                    files.fail("invalid_reference", "project fact must cite the same experience and an allowed field")
                if field == "bullets":
                    index = fact["index"]
                    if type(index) is not int or not 0 <= index < len(entry["bullets"]):
                        files.fail("invalid_reference", "project bullet index is invalid")
                    expected = entry["bullets"][index]
                else:
                    expected = entry[field]
                text(fact["quote"], inputs.contacts, 500)
                if fact["quote"] != expected:
                    files.fail("invalid_reference", "project fact must equal its complete source field")
                locators.append(field + ":" + str(fact.get("index", "")))
            _unique(locators)
        elif facts or question["project_ref"] is not None:
            files.fail("invalid", "only a project question carries personal facts")
        if category == "general":
            ref = question["bank_ref"]
            files.keys(ref, "direction revision id", "bank_ref")
            if (ref["direction"] != pack["direction"] or type(ref["revision"]) is not int or
                    ref["revision"] != inputs.bank["revision"] or not isinstance(ref["id"], str) or
                    ref["id"] not in bank_questions or question["question"] != bank_questions[ref["id"]]["prompt"]):
                files.fail("invalid_reference", "general question must equal its selected bank prompt")
        elif question["bank_ref"] is not None:
            files.fail("invalid", "only a general question cites a bank prompt")
        for item in _list(question["unknowns"], 8):
            files.keys(item, "id prompt answer", "unknown")
            if not _id(item["id"], "u") or item["answer"] is not None:
                files.fail("invalid", "unknown information must have a unique id and a null answer")
            text(item["id"], inputs.contacts)
            unknown_ids.append(item["id"]); text(item["prompt"], inputs.contacts)
    _unique(question_ids); _unique(unknown_ids)
    covered = {}
    for row in pack["coverage"]:
        files.keys(row, "requirement_ref question_refs", "coverage")
        ref = row["requirement_ref"]
        if not isinstance(ref, str) or ref not in actual or ref in covered:
            files.fail("invalid_reference", "coverage must name every requirement once")
        cited = _list(row["question_refs"], 20); _unique(cited)
        if set(cited) != set(actual[ref]):
            files.fail("invalid_reference", "coverage must agree with question references in both directions")
        covered[ref] = cited
    if set(covered) != set(requirements):
        files.fail("invalid_reference", "coverage must name every requirement once")
    warnings = []
    if not requirements: warnings.append("no_jd_requirements")
    if not project_count: warnings.append("no_project_questions")
    if any(not refs for refs in actual.values()): warnings.append("uncovered_requirements")
    return {"valid": True, "warnings": warnings, "question_count": len(question_ids),
            "coverage_complete": bool(requirements) and all(actual.values()),
            "pack_hash": files.digest(pack), "context_hash": files.digest(inputs.context)}


def prepared(root, filename):
    parts, _ = files.locate(root, filename)
    pack = files.read(root, parts); shape(pack)
    if pack["job_id"] != parts[1]:
        files.fail("invalid_reference", "interview pack belongs to another job directory")
    inputs = load(root, pack["job_id"], pack["direction"], bound=True)
    for name in (parts[-1], Path(parts[-1]).stem + ".md", Path(parts[-1]).stem + ".build.json"):
        artifact_identifier(pack["job_id"], name, inputs.contacts)
    result = check(pack, inputs)
    return parts, pack, inputs, result


def recheck_pack(root, parts, pack, inputs):
    if files.read(root, parts) != pack:
        files.fail("stale_context", "interview pack changed during this operation")
    recheck(root, inputs)


def validate(root, filename):
    parts, pack, inputs, result = prepared(root, filename)
    recheck_pack(root, parts, pack, inputs)
    return result


def markdown(pack, inputs):
    lines = ["# 面试准备包", "", "所有问题均为练习建议，不是公司真题或命中预测。",
             "基于当前岗位和档案；未核验实际投出的材料，也不代表已有面试邀请。", ""]
    for key, label in (("title", "岗位"), ("company", "公司")):
        value = inputs.job.get(key)
        if _text(value, 1000) and not sensitive(value, inputs.contacts):
            lines += [label, literal(value), ""]
    lines += ["## JD考点原句", ""]
    if not pack["requirements"]: lines += ["未列可引用JD考点，不表示完整覆盖JD。", ""]
    for item in pack["requirements"]:
        lines += [item["id"], literal(item["quote"]), ""]
    labels = {"jd": "JD练习建议", "project": "项目深挖练习建议", "general": "通用练习题"}
    for question in pack["questions"]:
        lines += ["## " + question["id"] + " · " + labels[question["category"]], "", literal(question["question"]), ""]
        for fact in question["facts"]:
            lines += ["档案原文（" + fact["ref"] + "）", literal(fact["quote"]), ""]
        for unknown in question["unknowns"]:
            lines += ["待补信息（未知）", literal(unknown["prompt"]), ""]
        if question["requirement_refs"]:
            lines += ["考点依据：" + "、".join(question["requirement_refs"]), ""]
        if question["bank_ref"]:
            lines += ["配置练习依据：" + question["bank_ref"]["id"], ""]
    lines += ["## 题库来源声明", literal(inputs.bank["provenance"]["kind"]),
              literal(inputs.bank["provenance"]["license"]), literal(inputs.bank["provenance"]["notice"]), "",
              "新事实先按建档流程确认；不要把待补信息补成未经确认的个人经历。", ""]
    return "\n".join(lines)


def render(root, filename, output=False):
    from jobsearch_cn import interview_review
    parts, pack, inputs, result = prepared(root, filename)
    body = markdown(pack, inputs)
    recheck_pack(root, parts, pack, inputs)
    if not output:
        return {**result, "markdown": body}
    result.update(files.publish(root, parts, pack, body.encode("utf-8"),
                               lambda: recheck_pack(root, parts, pack, inputs),
                               lambda **kw: interview_review.outputs(root, parts, pack, **kw)))
    return result
