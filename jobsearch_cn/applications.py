"""Application records (M4-1a): one SQLite database of the applications the user made, as events.

An application is one attempt at one stored job through one channel. Everything that happens to it is an
event (created, submitted, status_changed); the status and the submission date in the applications table
are a projection of those events, recomputed by replay() whenever an event is written and checked again
by validate(). What the user actually sent is copied into artifacts/ when it is recorded, with the SHA-256
of its bytes, so a material edited or a PDF rebuilt afterwards does not change what the record says was
sent. Every write is previewed first and then committed with the request id the preview gave, so a retry
never writes twice. The format, commands and exit codes are in docs/cn/applications.md.

This module does not depend on cli.py: the command line, the tests and later skills call it in-process.
Paths live under <data dir>/applications/; nothing here reads or writes anywhere else except the job and
match files it snapshots and the material and sent files the caller names.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from jobsearch_cn import build_notes, review, schema, store

DB_VERSION = 1  # PRAGMA user_version
EXPORT_VERSION = 1  # the schema_version of an export
DB_NAME = "applications.sqlite3"
CHANNELS = ("portal", "company_site", "email", "referral", "campus", "offline", "other", "unknown")
STATUSES = ("drafted", "applied", "interview", "offer", "no_response",
            "hired", "rejected", "withdrawn", "offer_declined")
TERMINAL = ("hired", "rejected", "withdrawn", "offer_declined")
# docs/cn/applications.md §4. drafted -> applied is only ever a submitted event (submit), never status.
TRANSITIONS = {
    "drafted": ("applied", "withdrawn"),
    "applied": ("interview", "offer", "rejected", "withdrawn", "no_response"),
    "interview": ("offer", "rejected", "withdrawn", "no_response"),
    "offer": ("hired", "offer_declined", "rejected", "withdrawn"),
    "no_response": ("interview", "offer", "rejected"),
    **{status: () for status in TERMINAL},
}
REASON_REQUIRED_FROM = ("no_response",)  # a late reply: say what came
EVENT_TYPES = ("created", "submitted", "status_changed", "reply_received", "note_added", "followup_scheduled",
               "followup_cancelled", "event_voided")
UNTIMED_EVENTS = ("note_added", "followup_scheduled", "followup_cancelled", "event_voided")  # no --on / --at
# A follow-up is for an application that was sent and is still open. no_response is the user saying they stopped
# waiting: entering it clears the follow-up date like an ending does (docs/cn/applications.md §4).
FOLLOWUP_STATUSES = ("applied", "interview", "offer")
ORIGINS = ("current", "historical")
ACTORS = ("user", "claude_code", "codex", "dsh")
SOURCE_KINDS = ("user", "authorized_api")
LOCK_TIMEOUT = 5.0  # seconds a write or a backup waits for another writer before it reports busy
BACKUP_POLL = 0.05  # seconds a backup sleeps between tries while another program holds the lock
_SQLITE_BUSY, _SQLITE_LOCKED = 5, 6  # the result codes Connection.backup's progress callback gets for a locked step
MAX_TEXT = 300
MAX_PLATFORM = 40
LOCAL_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")  # no daylight saving, so a fixed offset is exact

_ID = re.compile(r"(app|evt|req|mv|ctx)_[0-9a-f]{32}")
_ON = re.compile(r"\d{4}-\d{2}-\d{2}")
_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:[+-]\d{2}:\d{2}|Z)")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_EXTENSION = re.compile(r"\.[a-z0-9]{1,10}")
MATERIALS_CHECKS = (None, "match", "mismatch", "unchecked")
# resume build writes resume-<n>.* into resumes/<job>/; material render --output writes greeting-<n>, email-<n>
# and referral-<n> .txt into messages/<job>/ (M3-6); each beside a <name>.build.json note (section 12).
_SENT_NAME = re.compile(r"((?:resume|greeting|email|referral)-[1-9][0-9]{0,5})\.[A-Za-z0-9]+")
_MATERIAL_NAME = re.compile(r"((?:resume|greeting|email|referral)-[1-9][0-9]{0,5})\.json")
# review-<n>-r<round>.json for resume-<n>.json, review-<kind>-<n>-r<round>.json for a greeting, email or referral.
_REVIEW_NAME = re.compile(r"review-((?:(?:greeting|email|referral)-)?[1-9][0-9]{0,5})-r([0-9]+)\.json")
_BACKUP_NAME = re.compile(r"[0-9]{8}T[0-9]{6}Z(?:-[1-9][0-9]{0,2})?")
_ARCHIVE_PART = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*")  # one part of a recorded archive path
_EXPORT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.json")
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}
_CONTACT_LIKE = (
    ("a phone number", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("an email address", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("a link", re.compile(r"https?://|www\.", re.IGNORECASE)),
)

SCHEMA = (
    """CREATE TABLE applications (
      application_id   TEXT PRIMARY KEY,
      job_id           TEXT NOT NULL,
      record_origin    TEXT NOT NULL CHECK (record_origin IN ('current','historical')),
      channel_kind     TEXT NOT NULL,
      channel_platform TEXT,
      status           TEXT NOT NULL,
      submitted        INTEGER NOT NULL CHECK (submitted IN (0,1)),
      submitted_at     TEXT,
      submitted_on     TEXT,
      next_followup_on TEXT,
      revision         INTEGER NOT NULL,
      created_at       TEXT NOT NULL,
      updated_at       TEXT NOT NULL
    )""",
    "CREATE INDEX applications_job ON applications(job_id)",
    "CREATE INDEX applications_status ON applications(status)",
    "CREATE INDEX applications_followup ON applications(next_followup_on)",
    """CREATE TABLE events (
      application_id TEXT NOT NULL REFERENCES applications(application_id),
      seq            INTEGER NOT NULL,
      event_id       TEXT NOT NULL UNIQUE,
      request_id     TEXT NOT NULL,
      type           TEXT NOT NULL,
      occurred_at    TEXT,
      occurred_on    TEXT,
      recorded_at    TEXT NOT NULL,
      actor          TEXT NOT NULL CHECK (actor IN ('user','claude_code','codex','dsh')),
      source_kind    TEXT NOT NULL CHECK (source_kind IN ('user','authorized_api')),
      payload        TEXT NOT NULL,
      voided_by      TEXT,
      PRIMARY KEY (application_id, seq)
    )""",
    """CREATE TABLE requests (
      request_id     TEXT PRIMARY KEY,
      request_hash   TEXT NOT NULL,
      application_id TEXT NOT NULL REFERENCES applications(application_id),
      first_seq      INTEGER NOT NULL,
      last_seq       INTEGER NOT NULL
    )""",
    """CREATE TABLE material_versions (
      version_id      TEXT PRIMARY KEY,
      application_id  TEXT NOT NULL REFERENCES applications(application_id),
      kind            TEXT NOT NULL CHECK (kind IN ('resume')),
      material_path   TEXT,
      material_hash   TEXT,
      profile_hash    TEXT,
      review_path     TEXT,
      created_at      TEXT NOT NULL
    )""",
    """CREATE TABLE material_files (
      version_id TEXT NOT NULL REFERENCES material_versions(version_id),
      file_id    TEXT NOT NULL,
      role       TEXT NOT NULL CHECK (role IN ('source','sent')),
      path       TEXT NOT NULL,
      sha256     TEXT NOT NULL,
      size_bytes INTEGER NOT NULL,
      PRIMARY KEY (version_id, file_id)
    )""",
    """CREATE TABLE snapshots (
      application_id TEXT NOT NULL REFERENCES applications(application_id),
      kind           TEXT NOT NULL CHECK (kind IN ('job','match')),
      path           TEXT,
      sha256         TEXT,
      PRIMARY KEY (application_id, kind)
    )""",
)
TABLES = ("applications", "events", "requests", "material_versions", "material_files", "snapshots")


class ApplicationError(Exception):
    """A write or lookup the records refuse; exit code 1. code is one of invalid, transition,
    stale_revision, request_conflict, busy, not_found."""

    def __init__(self, code: str, message: str, **extra):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra

    def payload(self) -> dict:
        return {"error": self.code, "message": self.message, **self.extra}


class StorageError(Exception):
    """A file or the database could not be read or written, or the database is newer than this program; exit 2."""


def _invalid(message: str, **extra) -> ApplicationError:
    return ApplicationError("invalid", message, **extra)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(16)}"


def is_id(value, prefix: str) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None and value.startswith(prefix + "_")


# ---------------------------------------------------------------- time

def now_utc() -> str:
    """The time a record is written; tests patch it."""
    return _utc(datetime.now(timezone.utc))


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def parse_at(text: str) -> str:
    """--at: a moment with its time zone, stored as UTC. A moment without one is refused, not guessed."""
    if not isinstance(text, str) or not _AT.fullmatch(text.strip()):
        raise _invalid(f"--at {text!r}: write a moment with its time zone, like 2026-11-02T14:30+08:00; "
                       "use --on 2026-11-02 when only the date is known")
    text = text.strip()
    try:
        # Python 3.10's fromisoformat does not accept a trailing "Z", nor fractions of other lengths than 3 or 6.
        moment = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        raise _invalid(f"--at {text!r} is not a real moment") from None
    return _utc(moment)


def parse_on(text: str, where: str = "--on") -> str:
    if not isinstance(text, str) or not _ON.fullmatch(text.strip()):
        raise _invalid(f"{where} {text!r}: write the date as YYYY-MM-DD")
    try:
        return date.fromisoformat(text.strip()).isoformat()
    except ValueError:
        raise _invalid(f"{where} {text!r} is not a real date") from None


def _today() -> date:
    """Today in Asia/Shanghai: the day --on may not pass, a follow-up may not precede, list --due defaults to."""
    return datetime.now(timezone.utc).astimezone(LOCAL_TZ).date()


def occurred(on=None, at=None) -> tuple:
    """(occurred_at, occurred_on): a moment, a date or neither, never both and never in the future."""
    if on is not None and at is not None:
        raise _invalid("give --on or --at, not both")
    now = datetime.now(timezone.utc)
    if at is not None:
        value = parse_at(at)
        if _parse_utc(value) > now + timedelta(minutes=5):
            raise _invalid(f"--at {at}: that moment has not happened yet")
        return value, None
    if on is not None:
        value = parse_on(on)
        if date.fromisoformat(value) > _today():
            raise _invalid(f"--on {on}: that day has not come yet (Asia/Shanghai)")
        return None, value
    return None, None


# ---------------------------------------------------------------- small checks

def _text(value, where: str, limit: int, required: bool = False):
    """A short text the user said, stripped; None when empty unless required."""
    if value is not None:
        if not isinstance(value, str):
            raise _invalid(f"{where}: must be text")
        value = value.strip()
        if any(unicodedata.category(char) == "Cc" for char in value):
            raise _invalid(f"{where}: line breaks and control characters are not allowed; keep it to one line")
        if len(value) > limit:
            raise _invalid(f"{where}: at most {limit} characters ({len(value)} given)")
    if not value:
        if required:
            raise _invalid(f"{where}: required")
        return None
    return value


def contact_warnings(value, where: str) -> list:
    """Event texts hold only what the user said, never contact details or links (docs/cn/applications.md §9)."""
    if not isinstance(value, str):
        return []
    return [f"{where}: looks like it holds {label}; keep contact details and links out of application records"
            for label, pattern in _CONTACT_LIKE if pattern.search(value)]


def _channel(kind, platform) -> dict:
    if kind not in CHANNELS:
        raise _invalid(f"--channel {kind!r}: must be one of {', '.join(CHANNELS)}")
    return {"kind": kind, "platform": _text(platform, "--platform", MAX_PLATFORM)}


def _actor(actor) -> str:
    if actor not in ACTORS:
        raise _invalid(f"--actor {actor!r}: must be one of {', '.join(ACTORS)}")
    return actor


def _request_id(preview: bool, request_id) -> None:
    if preview == (request_id is not None):
        raise _invalid("give --preview to see what would be written, or --request-id with the id the preview gave")
    if request_id is not None and not is_id(request_id, "req"):
        raise _invalid(f"--request-id {request_id!r}: use the request_id a --preview printed (req_ and 32 hex digits)")


def _hash_request(body: dict) -> str:
    text = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- the database

class Paths:
    def __init__(self, data_root):
        self.root = Path(data_root)
        self.dir = self.root / "applications"
        self.db = self.dir / DB_NAME
        self.artifacts = self.dir / "artifacts"
        self.backups = self.dir / "backups"

    @classmethod
    def folder(cls, directory) -> "Paths":
        """A backup folder, laid out like applications/: read only, so it has no data root."""
        paths = cls.__new__(cls)
        paths.root, paths.dir = None, Path(directory)
        paths.db, paths.artifacts, paths.backups = paths.dir / DB_NAME, paths.dir / "artifacts", paths.dir / "backups"
        return paths


def _busy(exc: sqlite3.OperationalError):
    text = str(exc).lower()
    if "locked" in text or "busy" in text:
        return ApplicationError("busy", f"another program is writing the application records; nothing written. "
                                        f"Try again in a moment ({exc})")
    return StorageError(f"the application database could not be written: {exc}")


def _connect(paths: Paths, write: bool):
    """(connection, user_version), or None for a reader when there is no database yet.

    A reader never creates the file: sqlite3.connect would leave an empty database behind, so a missing file
    means "no applications yet", and the file that is there is opened read-only.
    """
    if write:
        try:
            store.safe_dir(paths.root, "applications")
        except store.StoreError as exc:
            raise StorageError(str(exc)) from None
    else:
        if store._is_link(paths.dir):
            raise StorageError(f"{paths.dir} is a link or junction; application records are only read from a real folder")
        if not paths.db.exists() and not store._is_link(paths.db):
            return None
    if store._is_link(paths.db):
        raise StorageError(f"{paths.db} is a link; application records are only kept in a real file")
    if paths.db.exists() and not paths.db.is_file():
        raise StorageError(f"{paths.db} is not a file")
    try:
        if write:
            connection = sqlite3.connect(str(paths.db), timeout=LOCK_TIMEOUT, isolation_level=None)
        else:
            connection = sqlite3.connect(paths.db.resolve().as_uri() + "?mode=ro", uri=True,
                                         timeout=LOCK_TIMEOUT, isolation_level=None)
    except sqlite3.Error as exc:
        raise StorageError(f"cannot open {paths.db}: {exc}") from None
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise StorageError("this SQLite build does not enforce foreign keys; application records need it")
        if write:
            connection.execute("PRAGMA journal_mode=DELETE")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.OperationalError as exc:
        connection.close()
        error = _busy(exc)
        if isinstance(error, ApplicationError):
            raise error from None
        raise StorageError(f"{paths.db} is not a readable application database: {exc}") from None
    except sqlite3.DatabaseError as exc:
        connection.close()
        raise StorageError(f"{paths.db} is not an application database: {exc}") from None
    except StorageError:
        connection.close()
        raise
    if version > DB_VERSION:
        connection.close()
        raise StorageError(f"{paths.db} was written by a newer jobsearch_cn (database version {version}, this "
                           f"program knows {DB_VERSION}); update the program, nothing was read or written")
    if version == 0 and tables:
        connection.close()
        raise StorageError(f"{paths.db} holds tables but no application database version; it is not one")
    if version == DB_VERSION and not set(TABLES) <= tables:
        connection.close()
        raise StorageError(f"{paths.db} is missing tables: {', '.join(sorted(set(TABLES) - tables))}")
    return connection, version


def _reader(paths: Paths):
    """A read-only connection, or None when there are no applications yet (no file, or an empty one)."""
    opened = _connect(paths, write=False)
    if opened is None:
        return None
    connection, version = opened
    if version == 0:
        connection.close()
        return None
    return connection


def _ensure_schema(connection) -> None:
    """Create the tables in the open write transaction, the first time anything is written."""
    if connection.execute("PRAGMA user_version").fetchone()[0] == 0:
        for statement in SCHEMA:
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version = {DB_VERSION}")


# ---------------------------------------------------------------- replay

def replay(events: list) -> dict | None:
    """The projection of an application's events: status, submission, channel and revision.

    Voided events are skipped. Raises ApplicationError (transition or invalid) on an event the state before
    it does not allow; writing and validate use this one function, so the two can never disagree.
    """
    state = None
    for event in events:
        if event.get("voided_by"):
            continue
        state = _apply(state, event)
    return state


def _as_of(events: list, revision: int) -> list:
    """The events as they stood at revision: later ones dropped, and a voided_by that a later void set cleared."""
    seqs = {event["event_id"]: event["seq"] for event in events}
    return [dict(event, voided_by=event["voided_by"] if seqs.get(event["voided_by"], revision + 1) <= revision
                 else None) for event in events if event["seq"] <= revision]


def void_target(events: list):
    """The event void would void: the latest one neither voided nor itself a void (None when there is none).
    Voiding again steps back one event at a time; a void is never voided, the event is recorded again instead."""
    for event in reversed(events):
        if not event["voided_by"] and event["type"] != "event_voided":
            return event
    return None


def _apply(state, event: dict) -> dict:
    kind, payload = event["type"], event["payload"]
    if state is None:
        if kind != "created":
            raise _invalid(f"event {event['seq']}: the first event must be created, not {kind}")
        return {"status": "drafted", "submitted": 0, "submitted_at": None, "submitted_on": None,
                "next_followup_on": None, "revision": event["seq"], "channel": payload["channel"]}
    state = dict(state, revision=event["seq"])
    if kind == "created":
        raise _invalid(f"event {event['seq']}: an application is created once")
    if kind == "submitted":
        if state["status"] != "drafted":
            raise ApplicationError("transition", f"only a drafted application can be submitted; this one is "
                                                 f"{state['status']}", status=state["status"])
        state.update(status="applied", submitted=1, submitted_at=event["occurred_at"],
                     submitted_on=event["occurred_on"], channel=payload["channel"])
    elif kind == "status_changed":
        before, after = payload["from"], payload["to"]
        if before != state["status"]:
            raise _invalid(f"event {event['seq']}: changes the status from {before}, but it was {state['status']}")
        allowed = TRANSITIONS.get(before, ())
        if after == "applied" or after not in allowed:
            hint = "; a drafted application becomes applied through submit" if after == "applied" else ""
            raise ApplicationError("transition", f"{before} cannot become {after}{hint}",
                                   status=before, allowed=[item for item in allowed if item != "applied"])
        if before in REASON_REQUIRED_FROM and not payload.get("reason"):
            raise _invalid(f"{before} -> {after}: say what came in --reason (a late reply)")
        state["status"] = after
        if after in TERMINAL or after == "no_response":
            state["next_followup_on"] = None
    elif kind == "reply_received":
        # Sent means a submitted event still stands, not "any status but drafted": drafted -> withdrawn is allowed,
        # and so is withdrawing once a submission was voided, and neither application was ever sent.
        if not state["submitted"]:
            hint = "; record the submission first (submit)" if state["status"] == "drafted" else ""
            raise ApplicationError("transition", f"a reply comes to an application that was sent, and this one never "
                                                 f"was{hint}", status=state["status"])
    elif kind in ("note_added", "event_voided"):
        pass  # a note changes nothing; the event a void names is skipped by replay
    elif kind in ("followup_scheduled", "followup_cancelled"):
        if state["status"] not in FOLLOWUP_STATUSES:
            raise ApplicationError("transition", f"a follow-up is for a sent application still open "
                                                 f"({', '.join(FOLLOWUP_STATUSES)}); this one is {state['status']}",
                                   status=state["status"])
        if kind == "followup_cancelled" and state["next_followup_on"] is None:
            raise _invalid("there is no follow-up date to cancel")
        state["next_followup_on"] = payload["due_on"] if kind == "followup_scheduled" else None
    else:
        raise _invalid(f"event {event['seq']}: unknown event type {kind!r}")
    return state


# ---------------------------------------------------------------- reading records

def _event(row, payload_loader=json.loads) -> dict:
    return {
        "event_id": row["event_id"],
        "seq": row["seq"],
        "request_id": row["request_id"],
        "type": row["type"],
        "occurred_at": row["occurred_at"],
        "occurred_on": row["occurred_on"],
        "recorded_at": row["recorded_at"],
        "actor": row["actor"],
        "source": {"kind": row["source_kind"], "reference": None},
        "payload": payload_loader(row["payload"]),
        "voided_by": row["voided_by"],
    }


def _events(connection, application_id: str) -> list:
    rows = connection.execute("SELECT * FROM events WHERE application_id = ? ORDER BY seq", (application_id,))
    return [_event(row) for row in rows]


def _material_versions(connection, application_id: str) -> list:
    versions = []
    for row in connection.execute("SELECT * FROM material_versions WHERE application_id = ? "
                                  "ORDER BY created_at, version_id", (application_id,)):
        files = [{"file_id": item["file_id"], "role": item["role"], "path": item["path"], "sha256": item["sha256"],
                  "size_bytes": item["size_bytes"]}
                 for item in connection.execute("SELECT * FROM material_files WHERE version_id = ? ORDER BY "
                                                "role DESC, file_id", (row["version_id"],))]
        versions.append({"version_id": row["version_id"], "kind": row["kind"], "material_path": row["material_path"],
                         "material_hash": row["material_hash"], "profile_hash": row["profile_hash"],
                         "review_path": row["review_path"], "created_at": row["created_at"], "files": files})
    return versions


def _application(connection, row) -> dict:
    """One application in the export format (docs/cn/applications.md §7), keys in a fixed order."""
    application_id = row["application_id"]
    events = _events(connection, application_id)
    snapshots = {"job": None, "match": None}
    for item in connection.execute("SELECT * FROM snapshots WHERE application_id = ?", (application_id,)):
        snapshots[item["kind"]] = None if item["path"] is None else {"path": item["path"], "sha256": item["sha256"]}
    submitted = next((event for event in events if event["type"] == "submitted" and not event["voided_by"]), None)
    return {
        "application_id": application_id,
        "job_id": row["job_id"],
        "record_origin": row["record_origin"],
        "channel": {"kind": row["channel_kind"], "platform": row["channel_platform"]},
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "revision": row["revision"],
        "status": row["status"],
        "submission": {
            "confirmed": bool(row["submitted"]),
            "occurred_at": row["submitted_at"],
            "occurred_on": row["submitted_on"],
            # 材料未记录: a submission with no material is recorded as it was (an online profile, a form), and
            # counted apart; null until the application is submitted.
            "materials_recorded": None if submitted is None else bool(submitted["payload"]["material_version_ids"]),
            # the sent files against their resume build note: match, mismatch (only warned), unchecked, or null
            "materials_check": None if submitted is None else submitted["payload"]["materials_check"],
        },
        "next_followup_on": row["next_followup_on"],
        "context_snapshot": {"job": snapshots["job"], "match": snapshots["match"]},
        "material_versions": _material_versions(connection, application_id),
        "events": events,
    }


def _row(connection, application_id: str):
    if not is_id(application_id, "app"):
        raise _invalid(f"{application_id!r} is not an application id (app_ and 32 hex digits)")
    row = connection.execute("SELECT * FROM applications WHERE application_id = ?", (application_id,)).fetchone()
    if row is None:
        raise ApplicationError("not_found", f"no application {application_id}")
    return row


def show(data_root, application_id: str) -> dict:
    connection = _reader(Paths(data_root))
    if connection is None:
        if not is_id(application_id, "app"):
            raise _invalid(f"{application_id!r} is not an application id (app_ and 32 hex digits)")
        raise ApplicationError("not_found", f"no application {application_id}: there are no application records yet")
    with _closing(connection):
        return {"application": _application(connection, _row(connection, application_id))}


def read_context(data_root, application_id: str) -> dict:
    """A checked, read-only event snapshot for followup materials, without archived file reads.

    Keep the projection and its events in one SQLite read transaction. Errors deliberately
    omit stored values: legacy event text may contain private information.
    """
    if not is_id(application_id, "app"):
        raise _invalid("application_id: expected app_ and 32 lowercase hex digits")
    connection = _reader(Paths(data_root))
    if connection is None:
        raise ApplicationError("not_found", "application: no saved record")
    with _closing(connection):
        connection.execute("BEGIN")
        row = _row(connection, application_id)
        try:
            events = _events(connection, application_id)
            errors = []
            ids = {event["event_id"] for event in events}
            if [event["seq"] for event in events] != list(range(1, len(events) + 1)) or len(ids) != len(events):
                raise ValueError("event sequence")
            for event in events:
                _check_event(event, "event", ids, errors)
            if not errors:
                _check_voids(events, "events", errors)
            if errors or not events:
                raise ValueError("events")
            state = replay(events)
            stored = {"status": row["status"], "submitted": row["submitted"], "submitted_at": row["submitted_at"],
                      "submitted_on": row["submitted_on"], "next_followup_on": row["next_followup_on"],
                      "revision": row["revision"],
                      "channel": {"kind": row["channel_kind"], "platform": row["channel_platform"]}}
            created = events[0]["payload"]
            if (state != stored or created.get("job_id") != row["job_id"]
                    or created.get("record_origin") != row["record_origin"]
                    or row["record_origin"] not in ORIGINS or not schema.is_job_id(row["job_id"])):
                raise ValueError("projection")
        except (ApplicationError, KeyError, TypeError, ValueError):
            raise ApplicationError("invalid_context", "application: events or their projection are inconsistent") from None
        snapshot = connection.execute("SELECT sha256 FROM snapshots WHERE application_id = ? AND kind = 'job'",
                                      (application_id,)).fetchone()
        return {"application_id": application_id, "job_id": row["job_id"], "record_origin": row["record_origin"],
                **state, "events": events, "archived_job_sha256": snapshot[0] if snapshot else None}


def _submission_key(item: dict):
    """Newest submission first; a moment sorts within its day after a bare date; never submitted or unknown last."""
    submission = item["submission"]
    if submission["occurred_at"]:
        return (2, _parse_utc(submission["occurred_at"]).astimezone(LOCAL_TZ).strftime("%Y-%m-%dT%H:%M:%S"))
    if submission["occurred_on"]:
        return (2, submission["occurred_on"])
    return (1, "") if submission["confirmed"] else (0, "")


def list_applications(data_root, statuses=None, job_id=None) -> dict:
    for status in statuses or ():
        if status not in STATUSES:
            raise _invalid(f"--status {status!r}: must be one of {', '.join(STATUSES)}")
    if job_id is not None and not schema.is_job_id(job_id):
        raise _invalid(f"--job {job_id!r} is not a job id like job_000000000001")
    connection = _reader(Paths(data_root))
    if connection is None:
        return {"applications": [], "note": "no application records yet"}
    jobs = store.Store(data_root)
    with _closing(connection):
        rows = connection.execute("SELECT * FROM applications ORDER BY created_at DESC, application_id").fetchall()
        items = [_application(connection, row) for row in rows
                 if (not statuses or row["status"] in statuses) and (job_id is None or row["job_id"] == job_id)]
    items.sort(key=lambda item: (_submission_key(item), item["created_at"]), reverse=True)
    summaries = []
    for item in items:
        try:
            job = jobs.get(item["job_id"]) or {}
        except (store.StoreError, OSError, ValueError):
            job = {}
        summaries.append({
            "application_id": item["application_id"], "job_id": item["job_id"],
            "title": job.get("title"), "company": job.get("company"),
            "status": item["status"], "channel": item["channel"], "record_origin": item["record_origin"],
            "submission": item["submission"], "next_followup_on": item["next_followup_on"],
            "revision": item["revision"], "updated_at": item["updated_at"],
        })
    return {"applications": summaries}


def due(data_root, as_of=None, statuses=None, job_id=None) -> dict:
    """list --due: sent, still open applications whose follow-up day has come ("due", the longest overdue first),
    and those with no follow-up day ("unset", the longest waiting first; not overdue). as_of defaults to today in
    Asia/Shanghai."""
    as_of = _today().isoformat() if as_of is None else parse_on(as_of, "--as-of")
    listed = list_applications(data_root, statuses, job_id)
    result = {"as_of": as_of, "due": [], "unset": []}
    if "note" in listed:
        return dict(result, note=listed["note"])
    for item in listed["applications"]:
        if not item["submission"]["confirmed"] or item["status"] not in FOLLOWUP_STATUSES:
            continue
        if item["next_followup_on"] is None:
            result["unset"].append(item)
        elif item["next_followup_on"] <= as_of:
            overdue = (date.fromisoformat(as_of) - date.fromisoformat(item["next_followup_on"])).days
            result["due"].append(dict(item, days_overdue=overdue))
    result["due"].sort(key=lambda item: (item["next_followup_on"], item["application_id"]))

    def waiting(item):
        key = _submission_key(item)
        return ((0, key[1]) if key[0] == 2 else (1, ""), item["application_id"])
    result["unset"].sort(key=waiting)
    return result


def export(data_root, application_ids=None) -> dict:
    """{"schema_version", "exported_at", "applications"}: sorted by application id, events by seq, the same
    bytes for the same records but for exported_at."""
    for application_id in application_ids or ():
        if not is_id(application_id, "app"):
            raise _invalid(f"{application_id!r} is not an application id (app_ and 32 hex digits)")
    document = {"schema_version": EXPORT_VERSION, "exported_at": now_utc(), "applications": []}
    connection = _reader(Paths(data_root))
    if connection is None:
        if application_ids:
            raise ApplicationError("not_found", f"no application {application_ids[0]}: there are no application "
                                                "records yet")
        return document
    with _closing(connection):
        if application_ids:
            rows = [_row(connection, application_id) for application_id in sorted(set(application_ids))]
        else:
            rows = connection.execute("SELECT * FROM applications ORDER BY application_id").fetchall()
        document["applications"] = [_application(connection, row) for row in rows]
    return document


def write_export(data_root, name: str, document: dict) -> Path:
    """Write an export into <data dir>/applications/exports/; name is a bare file name, never a path."""
    if not isinstance(name, str) or not _EXPORT_NAME.fullmatch(name) or ".." in name \
            or name.split(".")[0].upper() in _WINDOWS_RESERVED:
        raise _invalid(f"--out {name!r}: give a file name ending in .json (letters, digits, . _ -), not a path; "
                       "exports are written to <data dir>/applications/exports/")
    try:
        directory = store.safe_dir(Path(data_root), "applications", "exports")
    except store.StoreError as exc:
        raise StorageError(str(exc)) from None
    path = directory / name
    if store._is_link(path):
        raise StorageError(f"{path} is a link; nothing is written through it")
    try:
        store._write_json(directory, path, document)
    except OSError as exc:
        raise StorageError(f"cannot write {path}: {exc.strerror or exc}") from None
    return path


class _closing:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *exc):
        self.connection.close()


# ---------------------------------------------------------------- materials and archives

def _read_file(path) -> bytes:
    path = Path(path)
    if not path.is_file():
        raise StorageError(f"cannot read {path}: not a file")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise StorageError(f"cannot read {path}: {exc.strerror or exc}") from None


def _relative(path: Path, root: Path):
    """path relative to the data directory, with / separators, or None when it is outside."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return None


def _passing_review(material_file: Path, material_hash: str, root: Path):
    """The last-round review beside the material that passed this very version of it, or None."""
    named = _MATERIAL_NAME.fullmatch(material_file.name)
    if not named:
        return None
    kind, number = named.group(1).split("-")
    reviewed = number if kind == "resume" else named.group(1)
    found = []
    for candidate in material_file.parent.glob(f"review-{reviewed}-r*.json"):
        match = _REVIEW_NAME.fullmatch(candidate.name)
        if not match or match.group(1) != reviewed or not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_bytes().decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("material") == material_file.name \
                and data.get("material_hash") == material_hash and data.get("verdict") == "pass":
            found.append((int(match.group(2)), candidate))
    return _relative(max(found)[1], root) if found else None


def prepare_materials(data_root, job_id: str, material_path=None, sent_paths=(), check_material=None) -> dict:
    """Read what the user says they sent; nothing is written. check_material(record) -> (errors, warnings) is
    material.validate against the profile, supplied by the caller.

    Returns {"version": {...} | None, "files": [(file_id, role, data, name)], "digest": {...}, "warnings": [...]}.
    """
    root = Path(data_root)
    sent_paths = list(sent_paths or ())
    warnings, files = [], []
    if material_path is None and not sent_paths:
        return {"version": None, "files": [], "digest": None, "warnings": [], "check": None}
    # The table allows only 'resume' (DB_VERSION 1), so a greeting, email or referral is recorded under it too.
    version = {"kind": "resume", "material_path": None, "material_hash": None, "profile_hash": None,
               "review_path": None}
    digest = {"material": None, "sent": []}
    number = None
    outputs = None  # where the given material's files are made: messages/<job>/ for a message, else resumes/<job>/
    if material_path is not None:
        material_file = Path(material_path)
        data = _read_file(material_file)
        try:
            record = json.loads(data.decode("utf-8-sig"))
        except UnicodeDecodeError:
            raise StorageError(f"{material_file} is not UTF-8 text") from None
        except json.JSONDecodeError as exc:
            raise StorageError(f"{material_file} is not valid JSON: {exc}") from None
        if not isinstance(record, dict):
            raise _invalid(f"{material_file}: a material is a JSON object (docs/cn/material.md)")
        if record.get("job_id") != job_id:
            raise _invalid(f"{material_file} is a material for {record.get('job_id')!r}, not for {job_id}")
        # Followups are local drafts for an existing submission, not first-submission materials.
        # Check the content here: filenames and the caller's optional validator cannot enforce this boundary.
        if record.get("kind") == "followup":
            raise _invalid("followup materials cannot be archived as first-submission materials by record or submit")
        if record.get("kind") == "interview-prep":
            raise _invalid("interview preparation cannot be archived as submission materials by record or submit")
        if check_material is not None:
            errors, material_warnings = check_material(record)
            if errors:
                raise _invalid(f"{material_file} is not a valid material; run material validate", errors=errors)
            warnings.extend(f"material: {item}" for item in material_warnings)
        version["material_hash"] = review.material_hash(record)
        version["profile_hash"] = record.get("profile_hash") if isinstance(record.get("profile_hash"), str) else None
        version["material_path"] = _relative(material_file, root)
        if version["material_path"] is None:
            warnings.append(f"{material_file.name}: the material is outside the data directory; only its copy is kept")
        version["review_path"] = _passing_review(material_file, version["material_hash"], root)
        if version["review_path"] is None:
            warnings.append(f"{material_file.name}: no review beside it passed this version of the material")
        named = _MATERIAL_NAME.fullmatch(material_file.name)
        number = named.group(1) if named else None
        outputs = root / ("messages" if review.is_message(record) else "resumes") / job_id
        files.append(("material", "source", data, "material.json"))
        digest["material"] = _sha256(data)
    else:
        warnings.append("no material file recorded with the sent files; the version has no material_hash")
    if not sent_paths:
        warnings.append("no sent file recorded (--sent); only the material is kept")
    resumes = root / "resumes" / job_id
    sent_hashes = []
    for index, sent in enumerate(sent_paths, start=1):
        sent_file = Path(sent)
        data = _read_file(sent_file)
        extension = sent_file.suffix.lower() if _EXTENSION.fullmatch(sent_file.suffix.lower() or "-") else ""
        file_id = f"sent-{index}"
        files.append((file_id, "sent", data, file_id + extension))
        digest["sent"].append({"sha256": _sha256(data), "extension": extension})
        named = _SENT_NAME.fullmatch(sent_file.name)
        folder = outputs if outputs is not None else _outputs(root, job_id, named.group(1) if named else "")
        if _relative(sent_file.parent, folder) != "." or not named:
            where = (f"a text material render --output wrote under messages/{job_id}/"
                     if folder.parent.name == "messages" else f"a resume-<n> file built under resumes/{job_id}/")
            warnings.append(f"{sent_file.name}: not {where}; recorded as the file you say was sent")
        elif number is not None and named.group(1) != number:
            warnings.append(f"{sent_file.name}: built from {named.group(1)}.json, but the material given is "
                            f"{number}.json")
        if not data:
            warnings.append(f"{sent_file.name}: the file is empty")
        sent_hashes.append((sent_file, _sha256(data)))
    material_file = None if material_path is None else Path(material_path)
    check = _check_builds(outputs or resumes, material_file, version["material_hash"], sent_hashes, warnings)
    digest["check"] = check
    return {"version": version, "files": files, "digest": digest, "warnings": warnings, "check": check}


def _outputs(root: Path, job_id: str, stem: str) -> Path:
    """The folder files named <stem>.* are made in: messages/<job>/ for greeting-<n>, email-<n> and referral-<n>
    (material render --output, M3-6), resumes/<job>/ for anything else (resume build)."""
    return root / ("messages" if stem.split("-")[0] in review.MESSAGE_KINDS else "resumes") / job_id


def build_note_path(file: Path) -> Path:
    """The build note looked for beside a sent file when no material is given: resume-<n>.build.json for
    resume-<n>.<ext> (greeting-<n>.build.json for greeting-<n>.txt and so on), otherwise the name without its
    extension plus .build.json (applications.md section 12)."""
    named = _SENT_NAME.fullmatch(file.name)
    return file.parent / f"{named.group(1)}.build.json" if named else file.parent / (file.stem + ".build.json")


def material_note_path(folder: Path, material_file: Path) -> Path:
    """The note made for a material: <folder>/<material name without .json>.build.json, where folder is
    resumes/<job>/ (resume build) or, for a greeting, email or referral, messages/<job>/ (material render --output)."""
    return build_notes.material_note_path(folder, material_file)


def _check_builds(folder: Path, material_file, material_hash, sent: list, warnings: list):
    """materials_check, the sent files [(path, sha256)] against build notes (applications.md section 12).
    With a material, its note in folder checks every sent file, renamed or not; without one, each sent file is
    looked up by its own name. Returns 'match', 'mismatch' or 'unchecked' (both only warned about), or None with
    no sent file."""
    if not sent:
        return None
    if material_file is not None:
        groups = {material_note_path(folder, material_file): sent}
    else:
        groups = {}
        for item in sent:
            groups.setdefault(build_note_path(item[0]), []).append(item)
    results = [_check_note(note_file, items, material_hash, warnings) for note_file, items in groups.items()]
    return "mismatch" if "mismatch" in results else "unchecked" if "unchecked" in results else "match"


def _check_note(note_file: Path, sent: list, material_hash, warnings: list) -> str:
    """One build note against the sent files it should list; material_hash is None when no material is given."""
    names = ", ".join(path.name for path, _ in sent)
    maker = "material render --output" if note_file.name.split("-")[0] in review.MESSAGE_KINDS else "resume build"
    if not note_file.is_file():
        warnings.append(f"{names}: no {maker} note {note_file.name} to check against; recorded unchecked, "
                        "as the file(s) you say were sent")
        return "unchecked"
    try:
        note = build_notes.read_note(note_file)
        hashes = {item["sha256"] for item in note["files"]}
        note_hash = note["material_hash"]
    except (OSError, ValueError, KeyError, TypeError):
        warnings.append(f"{note_file.name}: the build note is unreadable; {names} recorded unchecked")
        return "unchecked"
    result = "match"
    for path, sha256 in sent:
        if sha256 not in hashes:
            warnings.append(f"{path.name}: not a file {note_file.name} records (edited after {maker}?); "
                            "recorded as the file you say was sent")
            result = "mismatch"
    if material_hash is not None and note_hash != material_hash:
        warnings.append(f"{note_file.name}: built from another version of the material than the one given; "
                        "recorded as given")
        result = "mismatch"
    return result


def _write_verified(path: Path, data: bytes) -> None:
    with open(path, "xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    if _sha256(path.read_bytes()) != _sha256(data):
        raise StorageError(f"{path}: the copy read back differs from what was written")


def _archive_dir(paths: Paths, application_id: str, prefix: str, files: list) -> tuple:
    """Write files into artifacts/<application>/<new id>/ through a .tmp folder renamed once every copy reads back
    right. Returns (folder id, folder path, [(file_id, role, relative path, sha256, size)])."""
    try:
        base = store.safe_dir(paths.root, "applications", "artifacts", application_id)
    except store.StoreError as exc:
        raise StorageError(str(exc)) from None
    folder_id = new_id(prefix)
    temporary, final = base / f"{folder_id}.tmp", base / folder_id
    try:
        temporary.mkdir()
        recorded = []
        for file_id, role, data, name in files:
            _write_verified(temporary / name, data)
            relative = f"artifacts/{application_id}/{folder_id}/{name}"
            recorded.append((file_id, role, relative, _sha256(data), len(data)))
        os.rename(temporary, final)
    except OSError as exc:
        shutil.rmtree(temporary, ignore_errors=True)
        raise StorageError(f"cannot archive into {base}: {exc.strerror or exc}") from None
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return folder_id, final, recorded


def _snapshot_files(data_root, job_id: str) -> tuple:
    """(files, warnings): the stored job and its match as they are now, to freeze at the first submission."""
    root, files, warnings = Path(data_root), [], []
    for kind, folder in (("job", "jobs"), ("match", "matches")):
        path = root / folder / f"{job_id}.json"
        if path.is_file() and not store._is_link(path):
            files.append((kind, "snapshot", _read_file(path), f"{kind}.json"))
        elif kind == "job":
            warnings.append(f"{job_id}: the job is no longer stored; no job snapshot is kept")
    return files, warnings


# ---------------------------------------------------------------- writing

def _unfinished_for_job(connection, job_id: str, exclude=None) -> list:
    if connection is None:
        return []
    marks = ",".join("?" * len(TERMINAL))
    rows = connection.execute(f"SELECT application_id FROM applications WHERE job_id = ? AND status NOT IN ({marks})",
                              (job_id, *TERMINAL))
    return [row[0] for row in rows if row[0] != exclude]


def _repeat(connection, request_id: str, request_hash: str):
    """The result a request already written gave, or None; a different request under the same id is refused."""
    row = connection.execute("SELECT * FROM requests WHERE request_id = ?", (request_id,)).fetchone()
    if row is None:
        return None
    if row["request_hash"] != request_hash:
        raise ApplicationError("request_conflict", f"{request_id} was already used for a different request; "
                                                    "preview again for a new request id",
                               application_id=row["application_id"])
    application = _application(connection, _row(connection, row["application_id"]))
    events = [event for event in application["events"] if row["first_seq"] <= event["seq"] <= row["last_seq"]]
    return {"application": application, "events": events, "request_id": request_id, "preview": False,
            "repeated": True, "warnings": []}


def _stale(connection, row, expected_revision: int):
    if row["revision"] != expected_revision:
        later = [event for event in _events(connection, row["application_id"]) if event["seq"] > expected_revision]
        return ApplicationError("stale_revision", f"the application changed since revision {expected_revision}; "
                                                  "read it again and tell the user what changed",
                                revision=row["revision"], events=later)
    return None


def _planned(events: list, actor: str) -> list:
    """Events as a preview shows them: no event id, seq or recorded_at yet."""
    return [{"event_id": None, "seq": None, "request_id": None, "type": event["type"],
             "occurred_at": event["occurred_at"], "occurred_on": event["occurred_on"], "recorded_at": None,
             "actor": actor, "source": {"kind": "user", "reference": None}, "payload": event["payload"],
             "voided_by": None} for event in events]


def _commit(paths: Paths, connection, *, request_id, request_hash, actor, application_id, new_row, expected_revision,
            events, version, version_files, snapshot) -> dict:
    """Write one request in one transaction. version_files and snapshot are already archived."""
    try:
        connection.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        raise _busy(exc) from None
    try:
        _ensure_schema(connection)
        repeated = _repeat(connection, request_id, request_hash)
        if repeated is not None:
            connection.execute("ROLLBACK")
            return repeated
        if new_row is None:
            row = _row(connection, application_id)
            stale = _stale(connection, row, expected_revision)
            if stale:
                raise stale
            existing = _events(connection, application_id)
        else:
            existing = []
        now = now_utc()
        first = (existing[-1]["seq"] if existing else 0) + 1
        written = []
        for offset, event in enumerate(events):
            payload = dict(event["payload"])
            if event["type"] == "submitted":
                payload["material_version_ids"] = [version["version_id"]] if version else []
                payload["sent_file_refs"] = [{"version_id": version["version_id"], "file_id": item[0]}
                                             for item in version_files if item[1] == "sent"] if version else []
            written.append({"event_id": new_id("evt"), "seq": first + offset, "request_id": request_id,
                            "type": event["type"], "occurred_at": event["occurred_at"],
                            "occurred_on": event["occurred_on"], "recorded_at": now, "actor": actor,
                            "source": {"kind": "user", "reference": None}, "payload": payload, "voided_by": None})
        voids = {event["payload"]["target_event_id"]: event["event_id"] for event in written
                 if event["type"] == "event_voided"}
        if voids:  # the revision check above makes the target still the latest event that can be voided
            existing = [dict(event, voided_by=voids.get(event["event_id"], event["voided_by"])) for event in existing]
        state = replay(existing + written)
        projection = (state["status"], state["submitted"], state["submitted_at"], state["submitted_on"],
                      state["next_followup_on"], state["revision"], state["channel"]["kind"],
                      state["channel"]["platform"])
        if new_row is not None:
            connection.execute(
                "INSERT INTO applications (application_id, job_id, record_origin, status, submitted, submitted_at, "
                "submitted_on, next_followup_on, revision, channel_kind, channel_platform, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (application_id, new_row["job_id"], new_row["record_origin"], *projection, now, now))
        else:
            connection.execute(
                "UPDATE applications SET status = ?, submitted = ?, submitted_at = ?, submitted_on = ?, "
                "next_followup_on = ?, revision = ?, channel_kind = ?, channel_platform = ?, updated_at = ? "
                "WHERE application_id = ?", (*projection, now, application_id))
        if version is not None:
            connection.execute(
                "INSERT INTO material_versions (version_id, application_id, kind, material_path, material_hash, "
                "profile_hash, review_path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (version["version_id"], application_id, version["kind"], version["material_path"],
                 version["material_hash"], version["profile_hash"], version["review_path"], now))
            connection.executemany(
                "INSERT INTO material_files (version_id, file_id, role, path, sha256, size_bytes) "
                "VALUES (?, ?, ?, ?, ?, ?)", [(version["version_id"], *item) for item in version_files])
        if snapshot is not None:
            recorded = {item[0]: item for item in snapshot}
            for kind in ("job", "match"):
                item = recorded.get(kind)
                connection.execute("INSERT INTO snapshots (application_id, kind, path, sha256) VALUES (?, ?, ?, ?)",
                                   (application_id, kind, item[2] if item else None, item[3] if item else None))
        connection.executemany(
            "INSERT INTO events (application_id, seq, event_id, request_id, type, occurred_at, occurred_on, "
            "recorded_at, actor, source_kind, payload, voided_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(application_id, event["seq"], event["event_id"], request_id, event["type"], event["occurred_at"],
              event["occurred_on"], event["recorded_at"], actor, "user", _dump(event["payload"]), None)
             for event in written])
        for target, void_id in voids.items():
            changed = connection.execute("UPDATE events SET voided_by = ? WHERE application_id = ? AND event_id = ? "
                                         "AND voided_by IS NULL", (void_id, application_id, target)).rowcount
            if changed != 1:
                raise _invalid(f"event {target} is not an event of this application that can be voided")
        connection.execute("INSERT INTO requests (request_id, request_hash, application_id, first_seq, last_seq) "
                           "VALUES (?, ?, ?, ?, ?)", (request_id, request_hash, application_id, written[0]["seq"],
                                                      written[-1]["seq"]))
        connection.execute("COMMIT")
    except sqlite3.OperationalError as exc:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise _busy(exc) from None
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    application = _application(connection, _row(connection, application_id))
    return {"application": application, "events": [e for e in application["events"] if e["seq"] >= first],
            "request_id": request_id, "preview": False, "repeated": False}


def _write(paths: Paths, *, request_id, request_body, actor, application_id, new_row, expected_revision, events,
           prepared, snapshot_files, warnings, connection) -> dict:
    """Archive the files, then commit; the archives are removed again when the commit does not happen."""
    request_hash = _hash_request(request_body)
    repeated = _repeat(connection, request_id, request_hash) if _has_tables(connection) else None
    if repeated is not None:
        return repeated
    created = []
    version, version_files, snapshot = None, [], None
    try:
        if prepared and prepared["files"]:
            version_id, folder, version_files = _archive_dir(paths, application_id, "mv", prepared["files"])
            created.append(folder)
            version = dict(prepared["version"], version_id=version_id)
        if snapshot_files is not None:
            snapshot = []
            if snapshot_files:
                _, folder, snapshot = _archive_dir(paths, application_id, "ctx", snapshot_files)
                created.append(folder)
        result = _commit(paths, connection, request_id=request_id, request_hash=request_hash, actor=actor,
                         application_id=application_id, new_row=new_row, expected_revision=expected_revision,
                         events=events, version=version, version_files=version_files, snapshot=snapshot)
    except BaseException:
        _remove(created, paths, application_id)
        raise
    if result["repeated"]:
        _remove(created, paths, application_id)  # another process wrote this very request meanwhile
        return result
    result["warnings"] = warnings
    return result


def _remove(folders: list, paths: Paths, application_id: str) -> None:
    for folder in folders:
        shutil.rmtree(folder, ignore_errors=True)
    base = paths.artifacts / application_id
    try:
        base.rmdir()  # only when empty: an application's earlier archives stay
    except OSError:
        pass


def _has_tables(connection) -> bool:
    return connection.execute("PRAGMA user_version").fetchone()[0] >= 1


def record(data_root, job_id: str, *, channel: str, platform=None, submitted: bool = False, on=None, at=None,
           historical: bool = False, material=None, sent=(), actor: str = "user", preview: bool = False,
           request_id=None, check_material=None) -> dict:
    """application record: a new application, drafted, or applied when submitted is given."""
    paths, root = Paths(data_root), Path(data_root)
    _request_id(preview, request_id)
    actor = _actor(actor)
    channel_value = _channel(channel, platform)
    if not schema.is_job_id(job_id):
        raise _invalid(f"{job_id!r} is not a job id like job_000000000001")
    if historical and not submitted:
        raise _invalid("--historical records an application already sent; add --submitted")
    if not submitted and (on is not None or at is not None or material is not None or sent):
        raise _invalid("--on, --at, --material and --sent describe the submission; add --submitted, or record "
                       "them later with submit")
    occurred_at, occurred_on = occurred(on, at) if submitted else (None, None)
    origin = "historical" if historical else "current"
    warnings = []
    try:
        job = store.Store(root).get(job_id)
    except (store.StoreError, ValueError, OSError) as exc:
        raise StorageError(f"cannot read the stored job {job_id}: {exc}") from None
    if job is None:
        if not historical:
            raise ApplicationError("not_found", f"{job_id} is not in the job store; import the JD first (jd parse "
                                                "--save), then record the application")
        warnings.append(f"{job_id} is not in the job store; the historical record keeps only its id")
    prepared = prepare_materials(root, job_id, material, sent, check_material) if submitted else None
    if prepared:
        warnings.extend(prepared["warnings"])
    if submitted and not historical and not (prepared and prepared["files"]):
        warnings.append("材料未记录 (no material recorded): the submission is recorded without the files sent; "
                        "say so to the user")
    warnings.extend(contact_warnings(channel_value["platform"], "--platform"))
    events = [{"type": "created", "occurred_at": None, "occurred_on": None,
               "payload": {"job_id": job_id, "record_origin": origin, "channel": channel_value}}]
    if submitted:
        events.append({"type": "submitted", "occurred_at": occurred_at, "occurred_on": occurred_on,
                       "payload": {"channel": channel_value, "material_version_ids": [], "sent_file_refs": [],
                                   "materials_check": prepared["check"] if prepared else None}})
    replay([dict(event, seq=index + 1) for index, event in enumerate(events)])
    reader = _reader(paths) if preview else None
    if preview:
        with _closing(reader) if reader else _nullcontext():
            others = _unfinished_for_job(reader, job_id)
        if others:
            warnings.append(f"{job_id} already has an unfinished application ({', '.join(others)}); a second one is "
                            "right only for another channel or a new attempt")
        return {"application": None, "events": _planned(events, actor), "request_id": new_id("req"), "preview": True,
                "status": {"from": None, "to": "applied" if submitted else "drafted"},
                "materials": _material_preview(prepared), "warnings": warnings}
    request_body = {"command": "record", "job_id": job_id, "channel": channel_value, "submitted": submitted,
                    "occurred_at": occurred_at, "occurred_on": occurred_on, "record_origin": origin, "actor": actor,
                    "materials": prepared["digest"] if prepared else None}
    connection, _ = _connect(paths, write=True)
    with _closing(connection):
        if _has_tables(connection):
            others = _unfinished_for_job(connection, job_id)
            if others:
                warnings.append(f"{job_id} already has an unfinished application ({', '.join(others)}); a second one "
                                "is right only for another channel or a new attempt")
        snapshot_files = None
        if submitted and not historical:
            snapshot_files, snapshot_warnings = _snapshot_files(root, job_id)
            warnings.extend(snapshot_warnings)
        return _write(paths, request_id=request_id, request_body=request_body, actor=actor,
                      application_id=new_id("app"), new_row={"job_id": job_id, "record_origin": origin},
                      expected_revision=None, events=events, prepared=prepared, snapshot_files=snapshot_files,
                      warnings=warnings, connection=connection)


def _material_preview(prepared):
    if not prepared or not prepared["files"]:
        return []
    return [{"file_id": file_id, "role": role, "name": name, "sha256": _sha256(data), "size_bytes": len(data)}
            for file_id, role, data, name in prepared["files"]]


class _nullcontext:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


def _existing(paths: Paths, application_id: str, expected_revision, preview: bool):
    """(connection, row) for a write on an application that must exist. The revision is checked by _current,
    after a retry of a request already written has had the chance to return its first result."""
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 1:
        raise _invalid("--expected-revision: the revision show or list printed, a whole number from 1")
    if not is_id(application_id, "app"):
        raise _invalid(f"{application_id!r} is not an application id (app_ and 32 hex digits)")
    if preview:
        connection = _reader(paths)
        if connection is None:
            raise ApplicationError("not_found", f"no application {application_id}: there are no application "
                                                "records yet")
    else:
        if not paths.db.exists():
            raise ApplicationError("not_found", f"no application {application_id}: there are no application "
                                                "records yet")
        connection, version = _connect(paths, write=True)
        if version == 0:
            connection.close()
            raise ApplicationError("not_found", f"no application {application_id}: there are no application "
                                                "records yet")
    try:
        row = _row(connection, application_id)
    except BaseException:
        connection.close()
        raise
    return connection, row


def _current(connection, row, expected_revision: int, request_id, request_body):
    """A retry's first result, or None once the row is checked to be at expected_revision."""
    if request_id is not None:
        repeated = _repeat(connection, request_id, _hash_request(request_body))
        if repeated is not None:
            return repeated
    stale = _stale(connection, row, expected_revision)
    if stale:
        raise stale
    return None


def submit(data_root, application_id: str, *, expected_revision, on=None, at=None, channel=None, platform=None,
           material=None, sent=(), actor: str = "user", preview: bool = False, request_id=None,
           check_material=None) -> dict:
    """application submit: a drafted application was sent."""
    paths, root = Paths(data_root), Path(data_root)
    _request_id(preview, request_id)
    actor = _actor(actor)
    occurred_at, occurred_on = occurred(on, at)
    connection, row = _existing(paths, application_id, expected_revision, preview)
    with _closing(connection):
        if channel is None and platform is not None:
            channel = row["channel_kind"]
        channel_value = _channel(channel, platform) if channel is not None else \
            {"kind": row["channel_kind"], "platform": row["channel_platform"]}
        prepared = prepare_materials(root, row["job_id"], material, sent, check_material)
        request_body = {"command": "submit", "application_id": application_id, "expected_revision": expected_revision,
                        "channel": channel_value, "occurred_at": occurred_at, "occurred_on": occurred_on,
                        "actor": actor, "materials": prepared["digest"]}
        repeated = _current(connection, row, expected_revision, request_id, request_body)
        if repeated is not None:
            return repeated
        if row["status"] != "drafted":
            raise ApplicationError("transition", f"only a drafted application can be submitted; this one is "
                                                 f"{row['status']}", status=row["status"])
        origin = row["record_origin"]
        warnings = contact_warnings(channel_value["platform"], "--platform") + prepared["warnings"]
        if origin == "current" and not prepared["files"]:
            warnings.append("材料未记录 (no material recorded): the submission is recorded without the files sent; "
                            "say so to the user")
        events = [{"type": "submitted", "occurred_at": occurred_at, "occurred_on": occurred_on,
                   "payload": {"channel": channel_value, "material_version_ids": [], "sent_file_refs": [],
                                   "materials_check": prepared["check"] if prepared else None}}]
        if preview:
            return {"application": _application(connection, row), "events": _planned(events, actor),
                    "request_id": new_id("req"), "preview": True,
                    "status": {"from": row["status"], "to": "applied"},
                    "materials": _material_preview(prepared), "warnings": warnings}
        snapshot_files = None
        # A submission voided and made again keeps the job and match kept the first time (docs/cn/applications.md).
        kept = connection.execute("SELECT 1 FROM snapshots WHERE application_id = ?", (application_id,)).fetchone()
        if origin == "current" and kept is None:
            snapshot_files, snapshot_warnings = _snapshot_files(root, row["job_id"])
            warnings.extend(snapshot_warnings)
        return _write(paths, request_id=request_id, request_body=request_body, actor=actor,
                      application_id=application_id, new_row=None, expected_revision=expected_revision,
                      events=events, prepared=prepared, snapshot_files=snapshot_files, warnings=warnings,
                      connection=connection)


def change_status(data_root, application_id: str, new_status: str, *, expected_revision, reason=None, on=None,
                  at=None, actor: str = "user", preview: bool = False, request_id=None) -> dict:
    """application status: the application moved on (docs/cn/applications.md §4)."""
    paths = Paths(data_root)
    _request_id(preview, request_id)
    actor = _actor(actor)
    if new_status not in STATUSES:
        raise _invalid(f"{new_status!r}: the status must be one of {', '.join(STATUSES)}")
    reason = _text(reason, "--reason", MAX_TEXT)
    occurred_at, occurred_on = occurred(on, at)
    connection, row = _existing(paths, application_id, expected_revision, preview)
    with _closing(connection):
        request_body = {"command": "status", "application_id": application_id, "expected_revision": expected_revision,
                        "to": new_status, "reason": reason, "occurred_at": occurred_at, "occurred_on": occurred_on,
                        "actor": actor}
        repeated = _current(connection, row, expected_revision, request_id, request_body)
        if repeated is not None:
            return repeated
        events = [{"type": "status_changed", "occurred_at": occurred_at, "occurred_on": occurred_on,
                   "payload": {"from": row["status"], "to": new_status, "reason": reason}}]
        # Only the events the row was read at: another process may have written more since, which the write
        # transaction reports as stale_revision, not as a status this request never saw.
        existing = [event for event in _events(connection, application_id) if event["seq"] <= row["revision"]]
        replay(existing + [dict(events[0], seq=existing[-1]["seq"] + 1, voided_by=None)])
        warnings = contact_warnings(reason, "--reason")
        if preview:
            return {"application": _application(connection, row), "events": _planned(events, actor),
                    "request_id": new_id("req"), "preview": True,
                    "status": {"from": row["status"], "to": new_status}, "materials": [], "warnings": warnings}
        return _write(paths, request_id=request_id, request_body=request_body, actor=actor,
                      application_id=application_id, new_row=None, expected_revision=expected_revision,
                      events=events, prepared=None, snapshot_files=None, warnings=warnings, connection=connection)


def _append(data_root, application_id: str, command: str, *, expected_revision, actor, preview, request_id,
            body: dict, plan) -> dict:
    """reply, note, followup and void: one event added to an existing application.

    plan(events) gets the events as they stood at expected_revision and returns {"event", "warnings"} and, for a
    void, "body" (what joins the request digest) and "show" (what the output adds). The events as of the revision
    make a retry plan exactly what it planned the first time. What plan refuses is raised only after _current, so
    a retry of a request already written gets its first result even when a check that depends on today
    (followup's date) would refuse it now.
    """
    paths = Paths(data_root)
    _request_id(preview, request_id)
    actor = _actor(actor)
    connection, row = _existing(paths, application_id, expected_revision, preview)
    with _closing(connection):
        existing = _as_of(_events(connection, application_id), expected_revision)
        try:
            planned, refused = plan(existing), None
        except ApplicationError as exc:
            planned, refused = {}, exc
        request_body = {"command": command, "application_id": application_id, "expected_revision": expected_revision,
                        "actor": actor, **body, **planned.get("body", {})}
        repeated = _current(connection, row, expected_revision, request_id, request_body)
        if repeated is not None:
            return repeated
        if refused is not None:
            raise refused
        event = planned["event"]
        trial = existing
        if event["type"] == "event_voided":
            target = event["payload"]["target_event_id"]
            trial = [dict(item, voided_by="pending" if item["event_id"] == target else item["voided_by"])
                     for item in existing]
        state = replay(trial + [dict(event, seq=existing[-1]["seq"] + 1, voided_by=None)])
        warnings = planned["warnings"]
        if preview:
            return {"application": _application(connection, row), "events": _planned([event], actor),
                    "request_id": new_id("req"), "preview": True,
                    "status": {"from": row["status"], "to": state["status"]}, "materials": [], "warnings": warnings,
                    **planned.get("show", {})}
        result = _write(paths, request_id=request_id, request_body=request_body, actor=actor,
                        application_id=application_id, new_row=None, expected_revision=expected_revision,
                        events=[event], prepared=None, snapshot_files=None, warnings=warnings, connection=connection)
        return dict(result, **planned.get("show", {}))


def reply(data_root, application_id: str, *, expected_revision, summary, on=None, at=None, actor: str = "user",
          preview: bool = False, request_id=None) -> dict:
    """application reply: a reply came in that does not change the status (one that does is a status --reason)."""
    summary = _text(summary, "--summary", MAX_TEXT, required=True)
    occurred_at, occurred_on = occurred(on, at)

    def plan(events):
        return {"event": {"type": "reply_received", "occurred_at": occurred_at, "occurred_on": occurred_on,
                          "payload": {"summary": summary}},
                "warnings": contact_warnings(summary, "--summary")}
    return _append(data_root, application_id, "reply", expected_revision=expected_revision, actor=actor,
                   preview=preview, request_id=request_id, plan=plan,
                   body={"summary": summary, "occurred_at": occurred_at, "occurred_on": occurred_on})


def note(data_root, application_id: str, *, expected_revision, text, actor: str = "user", preview: bool = False,
         request_id=None) -> dict:
    """application note: the user's own words on an application, in any status."""
    text = _text(text, "--text", MAX_TEXT, required=True)

    def plan(events):
        return {"event": {"type": "note_added", "occurred_at": None, "occurred_on": None, "payload": {"text": text}},
                "warnings": contact_warnings(text, "--text")}
    return _append(data_root, application_id, "note", expected_revision=expected_revision, actor=actor,
                   preview=preview, request_id=request_id, plan=plan, body={"text": text})


def followup(data_root, application_id: str, *, expected_revision, due=None, cancel: bool = False,
             actor: str = "user", preview: bool = False, request_id=None) -> dict:
    """application followup: set the day to follow up (today or later, Asia/Shanghai), or cancel it."""
    if (due is None) == (not cancel):
        raise _invalid("give --due YYYY-MM-DD or --cancel")
    due_on = None
    if due is not None:
        due_on = parse_on(due, "--due")

    def plan(events):
        if due_on is None:
            return {"event": {"type": "followup_cancelled", "occurred_at": None, "occurred_on": None, "payload": {}},
                    "warnings": []}
        # "Not before today" is checked here, not with the format above: _append raises what plan refuses only
        # after a retry of a request already written has had its first result back, and today moves. The same
        # request retried the next day returns what it wrote; only a new request is held to the new day.
        if date.fromisoformat(due_on) < _today():
            raise _invalid(f"--due {due}: that day has passed (Asia/Shanghai); to follow up now, give today's date")
        return {"event": {"type": "followup_scheduled", "occurred_at": None, "occurred_on": None,
                          "payload": {"due_on": due_on}}, "warnings": []}
    return _append(data_root, application_id, "followup", expected_revision=expected_revision, actor=actor,
                   preview=preview, request_id=request_id, plan=plan, body={"due_on": due_on, "cancel": bool(cancel)})


def void(data_root, application_id: str, *, expected_revision, reason, actor: str = "user", preview: bool = False,
         request_id=None) -> dict:
    """application void: void the latest event that can be voided (a mistake). Nothing is deleted."""
    reason = _text(reason, "--reason", MAX_TEXT, required=True)

    def plan(events):
        target = void_target(events)
        if target is None or target["type"] == "created":
            raise _invalid("nothing is left to void but the created event, and an application is not deleted; one "
                           "recorded by mistake is marked withdrawn with --reason (docs/cn/applications.md)")
        if target["type"] == "submitted" and events[0]["payload"].get("record_origin") == "historical":
            raise _invalid("a historical record is a submission by definition, so its submitted event is not voided "
                           "alone; one recorded by mistake is marked withdrawn with --reason (docs/cn/applications.md)")
        return {"event": {"type": "event_voided", "occurred_at": None, "occurred_on": None,
                          "payload": {"target_event_id": target["event_id"], "reason": reason}},
                "warnings": contact_warnings(reason, "--reason"), "body": {"target_event_id": target["event_id"]},
                "show": {"voids": target}}
    return _append(data_root, application_id, "void", expected_revision=expected_revision, actor=actor,
                   preview=preview, request_id=request_id, plan=plan, body={"reason": reason})


# ---------------------------------------------------------------- validate

def validate(data_root, backup=None) -> dict:
    """{"valid", "errors", "warnings", "orphans"}: the whole database against its own rules and its archive; with
    backup, a folder application backup wrote, checked by the same rules and against its manifest."""
    if backup is not None:
        return _validate_backup(Paths(data_root), backup)
    return _validate_paths(Paths(data_root))


def _validate_paths(paths: Paths) -> dict:
    connection = _reader(paths)
    if connection is None:
        return {"valid": True, "errors": [], "warnings": ["no application records yet"], "orphans": []}
    errors, warnings = [], []
    with _closing(connection):
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        if integrity != ["ok"]:
            errors.extend(f"database: {item}" for item in integrity)
        for row in connection.execute("PRAGMA foreign_key_check"):
            errors.append(f"{row[0]}: row {row[1]} refers to a missing {row[2]}")
        registered = set()
        for row in connection.execute("SELECT * FROM applications ORDER BY application_id").fetchall():
            _check_application(connection, row, errors, warnings, paths, registered)
        for row in connection.execute("SELECT request_id, application_id, first_seq, last_seq FROM requests"):
            seqs = {event[0]: event[1] for event in connection.execute(
                "SELECT seq, request_id FROM events WHERE application_id = ?", (row["application_id"],))}
            if not is_id(row["request_id"], "req"):
                errors.append(f"request {row['request_id']!r}: not a request id")
            if any(seqs.get(seq) != row["request_id"] for seq in range(row["first_seq"], row["last_seq"] + 1)):
                errors.append(f"request {row['request_id']}: events {row['first_seq']}-{row['last_seq']} of "
                              f"{row['application_id']} are not the ones it wrote")
    orphans = _orphans(paths, registered)
    if orphans:
        warnings.append(f"{len(orphans)} file(s) or folder(s) under applications/artifacts or backups are in no "
                        "record (a write or backup that did not finish); nothing refers to them, remove them once "
                        "the user agrees")
    return {"valid": not errors, "errors": errors, "warnings": warnings, "orphans": orphans}


def _archive_parts(relative):
    """The parts of a recorded archive path (artifacts/...), or None when it is no such path.

    Only / separates, and every part is a plain name: letters, digits, _ and -, with dots only between them, and
    no Windows device name. So nothing Windows would read as a separator, a drive, a parent or a stream (\\, C:,
    .., a trailing dot, a colon) gets through, on any system: one database gets the same verdict everywhere.
    """
    parts = relative.split("/") if isinstance(relative, str) else []
    if len(parts) < 2 or parts[0] != "artifacts" or not all(
            _ARCHIVE_PART.fullmatch(part) and part.split(".")[0].upper() not in _WINDOWS_RESERVED for part in parts):
        return None
    return parts


def _archived(folder: Path, relative) -> tuple:
    """(folder/relative, None) for a recorded archive path, or (None, why it is refused).

    folder is applications/ or a backup laid out like it. The path must be plain (_archive_parts), and the file
    it names must still lie inside folder/artifacts once every link or junction on the way is followed. Checking
    the records, copying them into a backup and checking a backup all go through here, so a recorded path never
    reads or writes outside its own folder.
    """
    parts = _archive_parts(relative)
    if parts is None:
        return None, f"archive path {relative!r} is not a plain path under artifacts/"
    path = folder.joinpath(*parts)
    try:
        inside = store._inside(path, folder.resolve() / "artifacts")
    except (OSError, RuntimeError):  # a link loop
        inside = False
    if not inside:
        return None, f"archive path {relative} leads out of artifacts/ through a link or junction"
    return path, None


def _validate_backup(paths: Paths, name) -> dict:
    if not isinstance(name, str) or not _BACKUP_NAME.fullmatch(name):
        raise _invalid(f"--backup {name!r}: the name of a folder under applications/backups/, like 20261104T083000Z")
    folder = paths.backups / name
    if store._is_link(paths.backups) or store._is_link(folder) or not folder.is_dir():
        raise ApplicationError("not_found", f"no backup {name} under applications/backups/")
    copy = Paths.folder(folder)
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        database = manifest["database"]
        listed = {item["path"]: item for item in manifest["artifacts"]}
        if manifest["kind"] != "applications-backup" or not isinstance(database, dict) \
                or not all(isinstance(relative, str) for relative in listed):
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        return {"valid": False, "errors": [f"backup {name}: manifest.json is missing or unreadable"], "warnings": [],
                "orphans": [], "backup": name}
    errors = []
    data = copy.db.read_bytes() if copy.db.is_file() and not store._is_link(copy.db) else None
    if data is None:
        errors.append(f"backup {name}: {DB_NAME} is missing")
    elif _sha256(data) != database.get("sha256") or len(data) != database.get("size_bytes"):
        errors.append(f"backup {name}: {DB_NAME} is not the database the manifest records")
    result = _validate_paths(copy) if data is not None else {"errors": [], "warnings": [], "orphans": []}
    for relative, item in sorted(listed.items()):
        path, refused = _archived(folder, relative)
        if refused:
            errors.append(f"backup {name}: manifest: {refused}")
            continue
        copied = path.read_bytes() if path.is_file() and not store._is_link(path) else None
        if copied is None or _sha256(copied) != item.get("sha256") or len(copied) != item.get("size_bytes"):
            errors.append(f"backup {name}: {relative} is missing or not the file the manifest records")
    errors += result["errors"]
    return {"valid": not errors, "errors": errors, "warnings": result["warnings"], "orphans": result["orphans"],
            "backup": name}


def backup(data_root) -> dict:
    """application backup: a consistent copy of the database (Connection.backup) and of the archived files it
    records, with manifest.json, in applications/backups/<UTC time>/. It records nothing, so it has no preview."""
    paths = Paths(data_root)
    deadline = time.monotonic() + LOCK_TIMEOUT  # the whole wait for another program's lock, opening included
    source = _reader(paths)
    if source is None:
        raise ApplicationError("not_found", "there are no application records yet; nothing to back up")
    with _closing(source):
        try:
            backups = store.safe_dir(paths.root, "applications", "backups")
        except store.StoreError as exc:
            raise StorageError(str(exc)) from None
        name = backup_name(backups, datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        temp = backups / f"{name}.tmp"
        temp.mkdir()
        try:
            target = sqlite3.connect(temp / DB_NAME)
            try:
                _copy_database(source, target, deadline)
            finally:
                target.close()
            return _finish_backup(paths, backups, name, temp)
        except BaseException:
            shutil.rmtree(temp, ignore_errors=True)
            raise


def _copy_database(source, target, deadline: float) -> None:
    """source.backup(target), refused as busy rather than waiting past deadline for another program's lock.

    Connection.backup retries a locked step by itself and never gives up, and each step would first sit out the
    connection's busy timeout, so a lock taken after the source was opened could hold a backup indefinitely.
    Here a step does not wait (busy_timeout 0), the copy sleeps BACKUP_POLL between tries, and the progress
    callback, which runs after every step, ends the copy before another try would pass the deadline.
    """
    source.execute("PRAGMA busy_timeout = 0")

    def progress(status, remaining, total):
        if status in (_SQLITE_BUSY, _SQLITE_LOCKED) and time.monotonic() + BACKUP_POLL > deadline:
            raise ApplicationError("busy", f"another program kept the application records locked for "
                                           f"{LOCK_TIMEOUT:g} seconds; no backup made. Try again in a moment")
    try:
        source.backup(target, progress=progress, sleep=BACKUP_POLL)
    except sqlite3.OperationalError as exc:
        raise _busy(exc) from None


def backup_name(backups: Path, stamp: str) -> str:
    """The UTC time, with -2, -3 ... when a backup (or one under way) already took it in the same second."""
    name = stamp
    for number in range(2, 1000):
        if not (backups / name).exists() and not (backups / f"{name}.tmp").exists():
            return name
        name = f"{stamp}-{number}"
    raise ApplicationError("busy", "too many backups in one second; try again")


def _finish_backup(paths: Paths, backups: Path, name: str, temp: Path) -> dict:
    """Copy the archived files the database copy records, check the copy, write the manifest, then rename."""
    copy, warnings, artifacts = Paths.folder(temp), [], []
    connection = _reader(copy)
    with _closing(connection):
        recorded = [row[0] for row in connection.execute(
            "SELECT path FROM material_files UNION SELECT path FROM snapshots WHERE path IS NOT NULL ORDER BY 1")]
        counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("applications", "events")}
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    for relative in recorded:
        source_file, refused = _archived(paths.dir, relative)
        target = _archived(temp, relative)[0]
        if refused is None and target is None:
            refused = f"archive path {relative} leads out of the backup"
        if refused:
            warnings.append(f"{refused}; not copied")
            continue
        if store._is_link(source_file) or not source_file.is_file():
            warnings.append(f"{relative} is missing; not copied")
            continue
        data = source_file.read_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_verified(target, data)
        artifacts.append({"path": relative, "sha256": _sha256(data), "size_bytes": len(data)})
    checked = _validate_paths(copy)
    data = copy.db.read_bytes()
    manifest = {"schema_version": 1, "kind": "applications-backup", "created_at": now_utc(),
                "database": {"name": DB_NAME, "sha256": _sha256(data), "size_bytes": len(data),
                             "user_version": user_version},
                "counts": counts, "artifacts": artifacts, "source_valid": checked["valid"]}
    store._write_json(temp, temp / "manifest.json", manifest)
    if not checked["valid"]:
        warnings.append("the records do not pass validate; the backup keeps them as they are (application validate)")
    final = backups / name
    temp.rename(final)
    return {"backup": name, "path": str(final), "manifest": manifest, "warnings": warnings}


def _check_record_events(connection, row, errors: list, payload_loader=json.loads):
    """Shared application/event validation; no material or archive file reads."""
    application_id = row["application_id"]
    where = application_id
    if not is_id(application_id, "app"):
        errors.append(f"{where!r}: not an application id")
    if not schema.is_job_id(row["job_id"]):
        errors.append(f"{where}: job_id {row['job_id']!r} is not a job id")
    if row["record_origin"] not in ORIGINS:
        errors.append(f"{where}: record_origin {row['record_origin']!r}")
    if row["channel_kind"] not in CHANNELS:
        errors.append(f"{where}: channel {row['channel_kind']!r} is not one of {', '.join(CHANNELS)}")
    for column in ("created_at", "updated_at"):
        if not isinstance(row[column], str) or not _UTC.fullmatch(row[column]):
            errors.append(f"{where}: {column} {row[column]!r} is not a UTC time like 2026-11-03T08:00:00Z")
    events = []
    for event_row in connection.execute("SELECT * FROM events WHERE application_id = ? ORDER BY seq",
                                        (application_id,)):
        try:
            event = _event(event_row, payload_loader)
        except (TypeError, ValueError):
            errors.append(f"{where} event {event_row['seq']}: the payload is not JSON")
            return
        events.append(event)
    if [event["seq"] for event in events] != list(range(1, len(events) + 1)):
        errors.append(f"{where}: events are not numbered 1, 2, 3 ... without gaps")
        return
    event_ids = {event["event_id"] for event in events}
    payload_errors = []
    for event in events:
        _check_event(event, f"{where} event {event['seq']}", event_ids, payload_errors)
    if not payload_errors:
        _check_voids(events, where, payload_errors)
    errors.extend(payload_errors)
    if payload_errors:
        return
    try:
        state = replay(events)
    except ApplicationError as exc:
        errors.append(f"{where}: the events do not replay: {exc.message}")
        return
    if state is None:
        errors.append(f"{where}: has no events")
        return
    stored = {"status": row["status"], "submitted": row["submitted"], "submitted_at": row["submitted_at"],
              "submitted_on": row["submitted_on"], "next_followup_on": row["next_followup_on"],
              "revision": row["revision"], "channel": {"kind": row["channel_kind"], "platform": row["channel_platform"]}}
    for key, value in state.items():
        if stored[key] != value:
            errors.append(f"{where}: {key} is {stored[key]!r} but the events give {value!r}")
    created = events[0]["payload"]
    if created.get("job_id") != row["job_id"] or created.get("record_origin") != row["record_origin"]:
        errors.append(f"{where}: the created event names another job or origin than the record")
    if row["record_origin"] == "historical" and not state["submitted"]:
        errors.append(f"{where}: a historical record must be submitted")
    return events, state


def _check_application(connection, row, errors: list, warnings: list, paths: Paths, registered: set) -> None:
    checked = _check_record_events(connection, row, errors)
    if checked is None:
        return
    events, state = checked
    application_id = where = row["application_id"]
    versions = {item["version_id"]: item for item in _material_versions(connection, application_id)}
    submitted = next((event for event in events if event["type"] == "submitted" and not event["voided_by"]), None)
    for event in events:
        if event["type"] != "submitted":
            continue
        for version_id in event["payload"]["material_version_ids"]:
            if version_id not in versions:
                errors.append(f"{where} event {event['seq']}: material version {version_id} is not in the record")
        for ref in event["payload"]["sent_file_refs"]:
            files = versions.get(ref.get("version_id"), {}).get("files", [])
            if not any(item["file_id"] == ref.get("file_id") and item["role"] == "sent" for item in files):
                errors.append(f"{where} event {event['seq']}: sent file {ref} is not in the record")
    if submitted and row["record_origin"] == "current" and not submitted["payload"]["material_version_ids"]:
        warnings.append(f"{where}: 材料未记录 (no material recorded with the submission)")
    check = submitted["payload"]["materials_check"] if submitted else None
    if check == "mismatch":
        warnings.append(f"{where}: materials_check mismatch (a sent file or the material differs from its resume "
                        "build note)")
    elif check == "unchecked":
        warnings.append(f"{where}: materials_check unchecked (no resume build note the sent files were checked "
                        "against)")
    for version in versions.values():
        for item in version["files"]:
            _check_archived(paths, item["path"], item["sha256"], item["size_bytes"], f"{where} {version['version_id']}"
                            f" {item['file_id']}", errors, registered)
    snapshots = connection.execute("SELECT * FROM snapshots WHERE application_id = ?", (application_id,)).fetchall()
    for item in snapshots:
        if item["path"] is not None:
            _check_archived(paths, item["path"], item["sha256"], None, f"{where} snapshot {item['kind']}", errors,
                            registered)
    if submitted and row["record_origin"] == "current" and not snapshots:
        errors.append(f"{where}: submitted, but the job and match at that time were not kept")
    for event in events:
        payload = event["payload"]
        for key in ("reason", "summary", "text"):
            warnings.extend(contact_warnings(payload.get(key), f"{where} event {event['seq']} {key}"))
        channel = payload.get("channel")
        if isinstance(channel, dict):
            warnings.extend(contact_warnings(channel.get("platform"), f"{where} event {event['seq']} platform"))


def _check_voids(events: list, where: str, errors: list) -> None:
    """Each void names an earlier event of this application that was then the latest one a void could take (never
    created, never a void), each event is voided at most once, and voided_by is the void that names it."""
    by_id = {event["event_id"]: event for event in events}
    voided = {}
    for event in events:
        if event["type"] != "event_voided":
            continue
        target_id = event["payload"]["target_event_id"]
        target = by_id.get(target_id)
        if target is None or target["seq"] >= event["seq"]:
            errors.append(f"{where} event {event['seq']}: voids {target_id}, no earlier event of this application")
            continue
        if target_id in voided:
            errors.append(f"{where} event {event['seq']}: voids event {target['seq']}, which was voided already")
        if target["voided_by"] != event["event_id"]:
            errors.append(f"{where} event {event['seq']}: voids event {target['seq']}, whose voided_by does not "
                          "name it")
        voided[target_id] = event["event_id"]
        latest = void_target(_as_of(events, event["seq"] - 1))
        if target["type"] in ("created", "event_voided") or latest is None or latest["event_id"] != target_id:
            errors.append(f"{where} event {event['seq']}: voids event {target['seq']}, which was not the latest "
                          "event that could be voided")
    for event in events:
        if event["voided_by"] is not None and voided.get(event["event_id"]) != event["voided_by"]:
            errors.append(f"{where} event {event['seq']}: voided_by names no void of this event")


def _check_event(event: dict, where: str, event_ids: set, errors: list) -> None:
    if not is_id(event["event_id"], "evt"):
        errors.append(f"{where}: event_id {event['event_id']!r}")
    if not is_id(event["request_id"], "req"):
        errors.append(f"{where}: request_id {event['request_id']!r}")
    if event["type"] not in EVENT_TYPES:
        errors.append(f"{where}: unknown type {event['type']!r}")
        return
    if event["actor"] not in ACTORS or event["source"]["kind"] not in SOURCE_KINDS:
        errors.append(f"{where}: actor or source")
    if event["occurred_at"] is not None and event["occurred_on"] is not None:
        errors.append(f"{where}: occurred_at and occurred_on are both set")
    if event["occurred_at"] is not None and not _UTC.fullmatch(str(event["occurred_at"])):
        errors.append(f"{where}: occurred_at {event['occurred_at']!r} is not a UTC time")
    if event["occurred_on"] is not None and not _valid_date(event["occurred_on"]):
        errors.append(f"{where}: occurred_on {event['occurred_on']!r} is not a date")
    if not isinstance(event["recorded_at"], str) or not _UTC.fullmatch(event["recorded_at"]):
        errors.append(f"{where}: recorded_at {event['recorded_at']!r} is not a UTC time")
    if event["voided_by"] is not None and event["voided_by"] not in event_ids:
        errors.append(f"{where}: voided by an event that is not there")
    payload = event["payload"]
    expected = {"created": {"job_id", "record_origin", "channel"},
                "submitted": {"channel", "material_version_ids", "sent_file_refs", "materials_check"},
                "status_changed": {"from", "to", "reason"},
                "reply_received": {"summary"}, "note_added": {"text"}, "followup_scheduled": {"due_on"},
                "followup_cancelled": set(), "event_voided": {"target_event_id", "reason"}}[event["type"]]
    if not isinstance(payload, dict) or set(payload) != expected:
        errors.append(f"{where}: the payload must have exactly {', '.join(sorted(expected)) or 'nothing'}")
        return
    if event["type"] in UNTIMED_EVENTS and (event["occurred_at"] is not None or event["occurred_on"] is not None):
        errors.append(f"{where}: a {event['type']} event has no occurred_at or occurred_on")
    for key in ("summary", "text"):
        if key in payload and (not isinstance(payload[key], str) or not payload[key].strip()
                               or len(payload[key]) > MAX_TEXT):
            errors.append(f"{where}: {key} must be text of 1 to {MAX_TEXT} characters")
    if event["type"] == "followup_scheduled" and not _valid_date(payload["due_on"]):
        errors.append(f"{where}: due_on {payload['due_on']!r} is not a date")
    if event["type"] == "event_voided":
        if not is_id(payload["target_event_id"], "evt"):
            errors.append(f"{where}: target_event_id {payload['target_event_id']!r}")
        if not isinstance(payload["reason"], str) or not payload["reason"].strip() or len(payload["reason"]) > MAX_TEXT:
            errors.append(f"{where}: a void needs a reason of 1 to {MAX_TEXT} characters")
    if "channel" in payload:
        channel = payload["channel"]
        if not isinstance(channel, dict) or set(channel) != {"kind", "platform"} or channel["kind"] not in CHANNELS:
            errors.append(f"{where}: channel must be {{kind, platform}} with a known kind")
    if event["type"] == "submitted":
        if not isinstance(payload["material_version_ids"], list) or not isinstance(payload["sent_file_refs"], list):
            errors.append(f"{where}: material_version_ids and sent_file_refs must be lists")
        if payload["materials_check"] not in MATERIALS_CHECKS:
            errors.append(f"{where}: materials_check {payload['materials_check']!r}")
    if event["type"] == "status_changed":
        if payload["from"] not in STATUSES or payload["to"] not in STATUSES:
            errors.append(f"{where}: unknown status")
        reason = payload["reason"]
        if reason is not None and (not isinstance(reason, str) or len(reason) > MAX_TEXT):
            errors.append(f"{where}: reason must be text of at most {MAX_TEXT} characters")


def _valid_date(value) -> bool:
    if not isinstance(value, str) or not _ON.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _check_archived(paths: Paths, relative, sha256, size, where: str, errors: list, registered: set) -> None:
    path, refused = _archived(paths.dir, relative)
    if refused:
        errors.append(f"{where}: {refused}")
        return
    registered.add(path.relative_to(paths.dir).as_posix())
    if store._is_link(path) or not path.is_file():
        errors.append(f"{where}: the archived file {relative} is missing")
        return
    data = path.read_bytes()
    if _sha256(data) != sha256 or (size is not None and len(data) != size):
        errors.append(f"{where}: the archived file {relative} changed since it was recorded")


def _orphans(paths: Paths, registered: set) -> list:
    """Files and folders under artifacts/ that no record names, as paths relative to applications/."""
    found = []
    walked = paths.artifacts.is_dir() and not store._is_link(paths.artifacts)
    for current, folders, files in os.walk(paths.artifacts) if walked else ():
        here = Path(current)
        for name in sorted(folders):
            relative = (here / name).relative_to(paths.dir).as_posix()
            if not any(item.startswith(relative + "/") for item in registered):
                found.append(relative + "/")
        folders[:] = [name for name in sorted(folders)
                      if any(item.startswith((here / name).relative_to(paths.dir).as_posix() + "/")
                             for item in registered)]
        for name in sorted(files):
            relative = (here / name).relative_to(paths.dir).as_posix()
            if relative not in registered:
                found.append(relative)
    if paths.backups.is_dir() and not store._is_link(paths.backups):  # a backup that did not finish
        found.extend(f"backups/{item.name}/" for item in paths.backups.iterdir()
                     if item.name.endswith(".tmp") and item.is_dir())
    return sorted(found)
