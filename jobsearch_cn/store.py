"""Local job store: one JSON file per record under <data dir>/jobs/.

Match records sit beside it, one file per job under <data dir>/matches/
(MatchStore, D4).

Plain files first, so a user can open, diff and back up their jobs with any
tool; SQLite can sit behind the same functions later (ADR-6: everything stays
in the gitignored data/ directory).

Deduplication (G2), strongest key first:

1. The record id. It is a fingerprint of the JD text, so importing the same JD
   again finds the stored record.
2. The normalised source URL. The same posting re-imported after the company
   edited it has a new fingerprint but the same URL; it updates the stored
   record and keeps its id and status.

A trusted portal job id would rank above both, but Job Schema v1 has no field
for one yet; it arrives with the portal sources (v0.3).
"""

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from jobsearch_cn import schema

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR_ENV = "JOBSEARCH_CN_DATA_DIR"
_EVIDENCE_PRIORITY = {"rule": 0, "agent": 1, "user": 2}

# Query parameters that track the click, not the posting. Dropped before URLs
# are compared, so a link shared twice still matches itself.
TRACKING_PARAMS = {"spm", "from", "ka", "ref", "source", "share_source", "share_from", "sessionid", "lid", "securityid"}


class StoreError(Exception):
    """A record could not be stored or found."""


def data_dir(override=None) -> Path:
    if override:
        return Path(override)
    return Path(os.environ.get(DATA_DIR_ENV) or DEFAULT_DATA_DIR)


def normalize_url(url):
    """A comparable form of a posting URL, or None."""
    if not url:
        return None
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.port and not ((parts.scheme == "http" and parts.port == 80) or (parts.scheme == "https" and parts.port == 443)):
        host = f"{host}:{parts.port}"
    query = sorted(
        (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS and not key.lower().startswith("utm_")
    )
    # http and https name the same posting.
    return urlunsplit(("https", host, parts.path.rstrip("/"), urlencode(query), ""))


class Store:
    def __init__(self, root):
        self.jobs = Path(root) / "jobs"

    def _path(self, job_id: str) -> Path:
        if not schema._ID.match(job_id or ""):
            raise StoreError(f"not a job id: {job_id!r}")
        return self.jobs / f"{job_id}.json"

    def get(self, job_id: str):
        path = self._path(job_id)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def all(self):
        """(records sorted by import time, warnings for files that could not be read)."""
        records, warnings = [], []
        for path in sorted(self.jobs.glob("job_*.json")) if self.jobs.is_dir() else []:
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                warnings.append(f"{path.name}: unreadable, skipped ({exc})")
        records.sort(key=lambda r: ((r.get("source") or {}).get("imported_at") or "", r.get("id") or ""))
        return records, warnings

    def find_by_url(self, url):
        wanted = normalize_url(url)
        if wanted is None:
            return None
        records, _ = self.all()
        return next((r for r in records if normalize_url((r.get("source") or {}).get("url")) == wanted), None)

    def save(self, record: dict):
        """Store a record. Returns (action, stored record); action is created, updated or unchanged.

        Raises StoreError if the record, or the merge with what is stored, is invalid.
        """
        errors = schema.validate(record)
        if errors:
            raise StoreError("invalid record: " + "; ".join(errors))
        existing = self.get(record["id"])
        if existing is not None:
            merged = merge_same_text(existing, record)
        else:
            existing = self.find_by_url(record["source"]["url"])
            if existing is None:
                merged = record
            elif existing["raw_text"] == record["raw_text"]:
                # An earlier URL update kept the original id. The next import
                # of that edited text must still protect completed fields.
                merged = merge_same_text(existing, record)
            else:
                merged = replace_edited(existing, record)
        if existing is not None and merged == existing:
            return "unchanged", existing
        errors = schema.validate(merged)
        if errors:
            raise StoreError("merged record is invalid: " + "; ".join(errors))
        self._write(merged)
        return ("updated" if existing is not None else "created"), merged

    def set_status(self, job_id: str, status: str) -> dict:
        if status not in schema.STATUSES:
            raise StoreError(f"status must be one of {', '.join(schema.STATUSES)}")
        record = self.get(job_id)
        if record is None:
            raise StoreError(f"no stored job {job_id}")
        record["status"] = status
        self._write(record)
        return record

    def _write(self, record: dict) -> None:
        _write_json(self.jobs, self._path(record["id"]), record)


class MatchStore:
    """Match records (docs/cn/match.md), one JSON file per job under <data dir>/matches/ (D4)."""

    def __init__(self, root):
        self.matches = Path(root) / "matches"

    def _path(self, job_id: str) -> Path:
        if not schema._ID.match(job_id or ""):
            raise StoreError(f"not a job id: {job_id!r}")
        return self.matches / f"{job_id}.json"

    def get(self, job_id: str):
        path = self._path(job_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def all(self):
        """(records, warnings for files that could not be read)."""
        records, warnings = [], []
        for path in sorted(self.matches.glob("job_*.json")) if self.matches.is_dir() else []:
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                warnings.append(f"{path.name}: unreadable, skipped ({exc})")
        return records, warnings

    def save(self, record: dict) -> str:
        """Store a checked record (score.validate); created, updated or unchanged."""
        existing = self.get(record["job_id"])
        if existing == record:
            return "unchanged"
        _write_json(self.matches, self._path(record["job_id"]), record)
        return "created" if existing is None else "updated"

    def write_draft(self, record: dict) -> Path:
        """Write a record for an agent to complete to <data dir>/matches/drafts/<job id>.json; not a saved match."""
        path = self.matches / "drafts" / self._path(record["job_id"]).name
        _write_json(path.parent, path, record)
        return path


def _write_json(directory: Path, path: Path, record: dict) -> None:
    """Write atomically, so an interrupted save never leaves half a file."""
    directory.mkdir(parents=True, exist_ok=True)
    text = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _set_field(record: dict, path: str, value) -> None:
    *parents, leaf = path.split(".")
    target = record
    for part in parents:
        target = target[part]
    target[leaf] = value


def merge_same_text(old: dict, new: dict) -> dict:
    """Merge a re-import of the same JD text into the stored record.

    Fill empty fields, but never erase a value with an empty import. When both
    values exist, only equal or higher evidence priority can replace the old
    value: user > agent > rule. Evidence follows the winning value, even when
    the two values are equal. Status and first import time stay unchanged.
    """
    merged = json.loads(json.dumps(old))
    for path in schema.EVIDENCE_FIELDS:
        value = schema._field(new, path)
        if not schema._has_value(value):
            continue
        new_evidence = new["evidence"].get(path)
        old_evidence = old["evidence"].get(path)
        if schema._has_value(schema._field(old, path)):
            old_priority = _EVIDENCE_PRIORITY.get((old_evidence or {}).get("method"), 0)
            new_priority = _EVIDENCE_PRIORITY.get((new_evidence or {}).get("method"), 0)
            if new_priority < old_priority:
                continue
        _set_field(merged, path, value)
        merged["evidence"][path] = new_evidence
    source = merged["source"]
    for key in ("site", "url"):
        if source[key] is None:
            source[key] = new["source"][key]
    merged["guard"] = new["guard"]
    return merged


def replace_edited(old: dict, new: dict) -> dict:
    """The same posting (by URL) with edited text: take the new content, keep identity and status."""
    merged = json.loads(json.dumps(new))
    merged["id"] = old["id"]
    merged["status"] = old["status"]
    merged["source"]["imported_at"] = old["source"]["imported_at"]
    return merged
