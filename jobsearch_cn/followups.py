"""Read-only source binding for followup materials. No sends, reminders or database writes."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from jobsearch_cn import applications, build_notes, messages, profile as profile_mod, schema, score, store, vocab

KEYS = ("application_id", "application_revision", "application_hash", "job_hash", "profile_input_hash", "template_hash")
EVENT_TYPES = ("submitted", "reply_received", "status_changed", "note_added")
HASH = re.compile(r"[0-9a-f]{64}")


class ContextError(Exception):
    """A safe field/reason, never a source value or event body."""


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def shape(context):
    if not isinstance(context, dict) or set(context) != set(KEYS):
        raise ContextError("context: must contain exactly the six source-binding fields")
    if not applications.is_id(context["application_id"], "app"):
        raise ContextError("context.application_id: invalid application id")
    if not messages._positive(context["application_revision"]):
        raise ContextError("context.application_revision: must be a positive integer")
    for key in KEYS[2:]:
        if not isinstance(context[key], str) or not HASH.fullmatch(context[key]):
            raise ContextError(f"context.{key}: must be a lowercase SHA-256 digest")


def occurred_date(event):
    # Recording timestamps are deliberately not a fallback for unknown occurrence dates.
    if event["occurred_at"] is not None:
        return applications._parse_utc(event["occurred_at"]).astimezone(applications.LOCAL_TZ).date().isoformat()
    return event["occurred_on"]


def _plain(value):
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items() if key != "compiled"}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _object(path, field):
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError()
        digest(value)  # reject non-finite JSON values too
        return value, raw
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise ContextError(f"context.{field}: current source is missing, unreadable or invalid JSON") from None


def _safe_file(root, parts, field):
    errors = []
    path = build_notes._safe_file(root, parts, field, errors)
    if errors:
        raise ContextError(f"context.{field}: current source path is missing or unsafe")
    return path


def _safe_templates(root):
    current = root
    for part in messages.USER_DIR.parts:
        current = current / part
        if store._is_link(current) or not store._inside(current, root.resolve()):
            raise ContextError("context.template_hash: template path is unsafe")
        if not current.exists():
            return
        if not current.is_dir():
            raise ContextError("context.template_hash: template path is not a directory")
    if any(store._is_link(path) or not path.is_file() for path in current.glob("*.json")):
        raise ContextError("context.template_hash: template file is unsafe")


def _withheld(text, banned):
    return bool(text and (applications.contact_warnings(text, "text")
                         or any(pattern.search(text) for pattern in banned["contact_errors"]["compiled"])))


@dataclass
class Inputs:
    context: dict
    facts: dict
    events: dict
    submitted_id: str
    job: dict
    profile: dict
    templates: dict
    banned: dict
    template: dict
    vocabulary: object


def load(root, application_id, job_id, expected_revision, *, profile_path=None, direction=None):
    """Read and validate all current inputs. Return in-memory inputs used by validation/rendering."""
    root = Path(root)
    if not applications.is_id(application_id, "app"):
        raise ContextError("context.application_id: invalid application id")
    if not messages._positive(expected_revision):
        raise ContextError("context.application_revision: --expected-revision must be a positive integer")
    if not schema.is_job_id(job_id):
        raise ContextError("context.job_hash: invalid job id")
    try:
        app = applications.read_context(root, application_id)
    except applications.ApplicationError as exc:
        raise ContextError(f"context.application: {exc.code}; no usable saved application") from None
    except (applications.StorageError, OSError, sqlite3.Error, RuntimeError, ValueError):
        raise ContextError("context.application: current database is missing, unreadable or unsafe") from None
    submitted = [e for e in app["events"] if e["type"] == "submitted" and not e["voided_by"]]
    if not app["submitted"] or len(submitted) != 1:
        raise ContextError("context.application: no effective confirmed submitted event")
    if app["status"] not in applications.FOLLOWUP_STATUSES:
        raise ContextError(f"context.application: status {app['status']} is not open for followup")
    if app["job_id"] != job_id:
        raise ContextError("context.application: job_id does not match this application")
    if app["revision"] != expected_revision:
        raise ContextError(f"context.application_revision: stale_revision; expected {expected_revision}, current {app['revision']}")

    job_file = _safe_file(root, ("jobs", f"{job_id}.json"), "job_hash")
    job_raw, job_bytes = _object(job_file, "job_hash")
    job_hash = digest(job_raw)  # upgrade fills legacy defaults in place; bind the actual complete input
    try:
        job = schema.upgrade(job_raw)
        if schema.validate(job) or job.get("id") != job_id:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ContextError("context.job_hash: current job is invalid") from None
    profile_file = (_safe_file(root, ("profile", "profile.json"), "profile_input_hash") if profile_path is None
                    else _safe_file(Path(profile_path).parent, (Path(profile_path).name,), "profile_input_hash"))
    data, _ = _object(profile_file, "profile_input_hash")
    if profile_mod.validate(data):
        raise ContextError("context.profile_input_hash: current profile is invalid; run profile validate")
    try:
        _safe_templates(root)
        templates, banned = messages.load_templates(root), messages.load_banned(root)
        vocabulary = vocab.load(root)
        template = messages.template_for(job, data, vocabulary, templates, "followup", direction)
    except (messages.TemplateError, vocab.VocabularyError, OSError, RuntimeError, ValueError):
        raise ContextError("context.template_hash: invalid template/configuration; followup requires default direction") from None
    facts, events = [], {}
    try:
        for event in app["events"]:
            if event["voided_by"] or event["type"] not in EVENT_TYPES:
                continue
            field = {"reply_received": "summary", "status_changed": "reason", "note_added": "text"}.get(event["type"])
            text = event["payload"].get(field) if field else None
            withheld = _withheld(text, banned)
            fact = {"event_id": event["event_id"], "type": event["type"], "seq": event["seq"],
                    "occurred_date": occurred_date(event), "source": event["source"]["kind"],
                    "text": None if withheld else text, "withheld": withheld, "referenceable": not withheld}
            facts.append(fact)
            if not withheld:
                events[event["event_id"]] = fact
    except (TypeError, ValueError):
        raise ContextError("context.application: invalid event occurrence date or text") from None
    app_input = {key: value for key, value in app.items() if key not in ("archived_job_sha256", "events")}
    app_input["events"] = [{key: event[key] for key in
                            ("event_id", "seq", "type", "occurred_at", "occurred_on", "source", "payload", "voided_by")}
                           for event in app["events"]]
    context = {"application_id": application_id, "application_revision": app["revision"],
               "application_hash": digest(app_input), "job_hash": job_hash, "profile_input_hash": digest(data),
               "template_hash": digest({key: template[key] for key in ("template", "template_source", "spec")} |
                                       {"banned": _plain(banned)})}
    channel = dict(app["channel"])
    if _withheld(channel["platform"], banned):
        channel["platform"] = None
    archive_hash = app["archived_job_sha256"]
    return Inputs(context, {"application_id": application_id, "job_id": job_id, "status": app["status"],
                            "channel": channel, "submitted_date": occurred_date(submitted[0]),
                            "next_followup_on": app["next_followup_on"], "events": facts,
                            "job_source": "current_saved_job_not_submission_snapshot",
                            "archived_job_comparison": "unavailable" if archive_hash is None else
                            ("same_bytes" if hashlib.sha256(job_bytes).hexdigest() == archive_hash else "different_bytes"),
                            "note": "本地记录不代表招聘方完整回复情况；事件顺序是记录顺序，未知发生日期不补写。"},
                  events, submitted[0]["event_id"], job, data, templates, banned, template, vocabulary)


def check(root, record, *, profile_path=None):
    context = record.get("context")
    shape(context)
    current = load(root, context["application_id"], record.get("job_id"), context["application_revision"],
                   profile_path=profile_path, direction=record.get("direction"))
    changed = [key for key in KEYS if context[key] != current.context[key]]
    if changed:
        raise ContextError("context: stale source fields: " + ", ".join(changed) + "; reread sources and draft again")
    return current


def recheck(root, record, inputs, *, profile_path=None):
    """Final token check, after rendering or inspecting outputs; no cross-file locking promise."""
    latest = check(root, record, profile_path=profile_path)
    if latest.context != inputs.context:
        raise ContextError("context: sources changed during this check; no current result was published")


def template_result(inputs):
    return {"job_id": inputs.job["id"], **inputs.template, "profile_hash": score.profile_hash(inputs.profile),
            "context": inputs.context, "facts": inputs.facts, "context_status": "current_at_check"}
