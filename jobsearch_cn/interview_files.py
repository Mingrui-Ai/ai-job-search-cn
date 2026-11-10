"""Bounded local inputs and commit-marker publication for interview preparation only."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from jobsearch_cn import schema, store

LIMIT = 2 * 1024 * 1024
PACK = re.compile(r"prep-([1-9][0-9]{0,5})\.json")
REVIEW = re.compile(r"review-prep-([1-9][0-9]{0,5})-r([12])\.json")
HASH = re.compile(r"[0-9a-f]{64}")
STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})")


class Error(Exception):
    def __init__(self, code, message, exit_code=1):
        self.code, self.message, self.exit_code = code, message, exit_code
        super().__init__(message)


def fail(code="invalid", message="interview input does not satisfy its contract", exit_code=1):
    raise Error(code, message, exit_code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonstandard number")


def decode(raw):
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs, parse_constant=_constant)
        canonical(value)  # finite numbers and valid Unicode, including in unused fields
        return value
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        fail("invalid_json", "interview input must be finite, unambiguous UTF-8 JSON", 2)


def keys(value, expected, field):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        fail("invalid", field + ": unexpected object fields")


def positive(value, maximum=999999):
    return type(value) is int and 1 <= value <= maximum


def hash_value(value):
    return isinstance(value, str) and HASH.fullmatch(value) is not None


def timestamp(value):
    try:
        if not isinstance(value, str) or not STAMP.fullmatch(value):
            raise ValueError()
        if value[-1] != "Z" and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
            raise ValueError()
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        parsed.astimezone(timezone.utc)
        parsed.astimezone(timezone(timedelta(hours=8)))
    except (ValueError, OverflowError):
        fail("invalid", "timestamp must be a representable ISO time with timezone")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def safe(root, parts, *, required=True):
    root = Path(root).absolute()
    current = root
    try:
        real_root = root.resolve()
        for part in parts:
            if not isinstance(part, str) or part in ("", ".", "..") or any(c in part for c in "\\/:"):
                fail("unsafe_path", "interview path is not a fixed local path")
            current = current / part
            if store._is_link(current) or not store._inside(current, real_root):
                fail("unsafe_path", "interview descendants must be real files within the selected root")
        if current.exists() and not current.is_file():
            fail("unsafe_path", "interview input or output is not a regular file")
        if required and not current.is_file():
            fail("missing_input", "interview input is missing", 2)
        return current
    except (OSError, RuntimeError, ValueError):
        fail("io_error", "interview path cannot be inspected", 2)


def locate(root, filename, *, review=False):
    path = Path(filename)
    if ".." in path.parts:
        fail("unsafe_path", "interview file must use its fixed location")
    try:
        parts = path.absolute().relative_to(Path(root).absolute()).parts
    except ValueError:
        fail("unsafe_path", "interview file is outside the selected root")
    pattern = REVIEW if review else PACK
    if len(parts) != 3 or parts[0] != "interviews" or not schema.is_job_id(parts[1]) or not pattern.fullmatch(parts[2]):
        fail("unsafe_path", "interview file must use its fixed job directory and numbered name")
    return parts, safe(root, parts)


def identity(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def read_bytes(root, parts):
    path = safe(root, parts)
    try:
        before = identity(path)
        if before[2] > LIMIT:
            fail("too_large", "interview input exceeds the size limit", 2)
        with path.open("rb") as source:
            raw = source.read(LIMIT + 1)
        if len(raw) > LIMIT:
            fail("too_large", "interview input exceeds the size limit", 2)
        safe(root, parts)
        if identity(path) != before:
            fail("stale_context", "interview input changed during reading")
        return raw
    except OSError:
        fail("io_error", "interview input could not be read", 2)


def read(root, parts):
    return decode(read_bytes(root, parts))


def _remove_owned(root, parts, token):
    """Never clean an object that replaced this invocation's temporary file."""
    try:
        path = safe(root, parts)
        if identity(path) == token:
            path.unlink()
    except (Error, OSError):
        pass


def _stage(root, parts, payload, owned):
    path = safe(root, parts, required=False)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as target:
        try:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        finally:
            stat = os.fstat(target.fileno())
            token = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
            owned.append((parts, token))
    return path, token


def publish(root, parts, pack, body, recheck, verify):
    """Exclusive writer, invalidate old build, replace md, commit build last; not a two-file transaction."""
    folder_parts, stem = parts[:-1], Path(parts[-1]).stem
    writer_parts = (*folder_parts, stem + ".writer")
    writer = safe(root, writer_parts, required=False)
    owned = []
    publication_started = False
    note_parts = (*folder_parts, stem + ".build.json")
    output_parts = (*folder_parts, stem + ".md")
    try:
        try:
            writer, writer_token = _stage(root, writer_parts, uuid.uuid4().hex.encode("ascii"), owned)
        except FileExistsError:
            fail("busy", "an interview writer marker exists; inspect it before manual recovery")
        note = {"schema_version": 1, "kind": "interview-build", "pack": parts[-1],
                "pack_hash": digest(pack), "context_hash": digest(pack["context"]), "built_at": now(),
                "files": [{"name": stem + ".md", "sha256": hashlib.sha256(body).hexdigest()}]}
        staged = []
        for payload in (body, canonical(note) + b"\n"):
            temp_parts = (*folder_parts, ".interview-" + uuid.uuid4().hex + ".tmp")
            temp, token = _stage(root, temp_parts, payload, owned)
            staged.append((temp, token, temp_parts))
        recheck()
        safe(root, writer_parts)
        if identity(writer) != writer_token:
            fail("stale_context", "interview writer marker changed")
        note_path = safe(root, note_parts, required=False)
        output_path = safe(root, output_parts, required=False)
        for temp, token, temp_parts in staged:
            safe(root, temp_parts)
            if identity(temp) != token:
                fail("stale_context", "interview temporary output changed")
        # The old completion marker must be gone before changing the formal output.
        publication_started = True
        if note_path.exists():
            note_path.unlink()
        os.replace(staged[0][0], output_path)
        recheck()
        safe(root, note_parts, required=False)
        safe(root, output_parts)
        safe(root, writer_parts)
        safe(root, staged[1][2])
        if identity(writer) != writer_token or identity(staged[1][0]) != staged[1][1]:
            fail("stale_context", "interview publication objects changed")
        os.replace(staged[1][0], note_path)
        if verify(allow_writer=True) != note["files"][0]["sha256"]:
            fail("invalid_output", "interview published bytes differ from the prepared output")
        recheck()
        safe(root, writer_parts)
        if identity(writer) != writer_token:
            fail("stale_context", "interview writer marker changed")
        if verify(allow_writer=True) != note["files"][0]["sha256"]:
            fail("invalid_output", "interview published bytes changed before completion")
        return {"output": "/".join(output_parts), "build_note": "/".join(note_parts),
                "output_sha256": note["files"][0]["sha256"]}
    except BaseException:
        if publication_started:
            try:
                note_path = safe(root, note_parts)
                # Invalidate only this writer's own committed marker.
                if identity(note_path) == staged[1][1] and read(root, note_parts) == note:
                    note_path.unlink()
            except (Error, OSError):
                pass
        raise
    finally:
        for owned_parts, token in reversed(owned):
            _remove_owned(root, owned_parts, token)
