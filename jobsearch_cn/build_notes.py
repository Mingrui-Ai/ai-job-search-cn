"""Build-note reading shared by reviews and the deliberately permissive submission archive."""
import hashlib
import json
from pathlib import Path
import re

from jobsearch_cn import review, schema, store

MATERIAL_NAME = re.compile(r"((resume|greeting|email|referral|followup)-[1-9][0-9]{0,5})\.json")
_HASH = re.compile(r"[0-9a-f]{64}")
_KEYS = ("schema_version", "kind", "material", "material_hash", "profile_hash", "built_at", "files")


def material_note_path(folder: Path, material_file: Path) -> Path:
    """The existing producer's note name, including the archive's legacy arbitrary-name lookup."""
    name = material_file.name
    return folder / ((name[:-len(".json")] if name.endswith(".json") else name) + ".build.json")


def read_note(path: Path):
    """Decode the existing UTF-8 v1 note; callers choose strict errors or archive warnings."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _safe_file(root: Path, parts: tuple, where: str, errors: list):
    """Read-only counterpart to safe_dir: chosen root may be a link, descendants may not."""
    current = root
    try:
        real_root = root.resolve()
        for index, part in enumerate(parts):
            current = current / part
            if store._is_link(current):
                errors.append(f"{where}: {part} is a link or junction; use real files inside the data directory")
                return None
            if not store._inside(current, real_root):
                errors.append(f"{where}: {part} resolves outside the data directory")
                return None
            if index < len(parts) - 1 and not current.is_dir():
                errors.append(f"{where}: output folder {part} is missing or not a directory")
                return None
        if not current.is_file():
            errors.append(f"{where}: {parts[-1]} is missing or not a file")
            return None
    except (OSError, RuntimeError, ValueError):
        errors.append(f"{where}: cannot safely locate {parts[-1]} inside the data directory")
        return None
    return current


def _note_errors(note, material, filename: str, expected: tuple, maker: str) -> list:
    errors = []
    if not isinstance(note, dict):
        return ["build_note: must be a JSON object"]
    schema._check_keys(note, _KEYS, "build_note", errors)
    if type(note.get("schema_version")) is not int or note["schema_version"] != 1:
        errors.append("build_note.schema_version: must be 1")
    wanted_kind = "resume-build" if maker == "resume build" else "message-build"
    if note.get("kind") != wanted_kind:
        errors.append(f"build_note.kind: must be {wanted_kind}")
    if note.get("material") != filename:
        errors.append("build_note.material: does not name the reviewed material file")
    for field in ("material_hash", "profile_hash"):
        value = note.get(field)
        if not isinstance(value, str) or not _HASH.fullmatch(value):
            errors.append(f"build_note.{field}: must be a lowercase SHA-256 digest")
    if note.get("material_hash") != review.material_hash(material):
        errors.append(f"build_note.material_hash: built from another version of the material; rerun {maker}")
    # The producer records the actual profile used for this build. A material may legitimately
    # carry an older profile_hash (material validate warns); do not require equality or read a profile.
    schema._check_timestamp(note.get("built_at"), "build_note.built_at", errors)
    files = note.get("files")
    if not isinstance(files, list):
        errors.append("build_note.files: must list the expected generated files")
        return errors
    names = []
    for index, item in enumerate(files):
        where = f"build_note.files[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{where}: must be an object with name and sha256")
            continue
        schema._check_keys(item, ("name", "sha256"), where, errors)
        name = item.get("name")
        # Only names derived from the validated material are accepted. Never open a declared path.
        if not isinstance(name, str) or name not in expected:
            errors.append(f"{where}.name: must be one of {', '.join(expected)} (bare file names only)")
        else:
            names.append(name)
        value = item.get("sha256")
        if not isinstance(value, str) or not _HASH.fullmatch(value):
            errors.append(f"{where}.sha256: must be a lowercase SHA-256 digest")
    if sorted(names) != sorted(expected):
        errors.append(f"build_note.files: must list each of {', '.join(expected)} exactly once")
    return errors


def check_outputs(root, material_file: Path, material, declared_name: str) -> list:
    """Strict review check of the current material and its complete generated outputs; no writes.

    This proves identity and byte consistency with the note, not rendering quality or current profile
    facts. Submission archives intentionally retain their separate warning-only policy.
    """
    errors = []
    named = MATERIAL_NAME.fullmatch(material_file.name)
    kind = material.get("kind") if isinstance(material, dict) else None
    job_id = material.get("job_id") if isinstance(material, dict) else None
    if not named or named.group(2) != kind:
        errors.append("build_note.material: the material file must be named <kind>-<n>.json for its kind")
    if declared_name != material_file.name:
        errors.append("build_note.material: review.material must be the actual material's bare file name")
    if not schema.is_job_id(job_id):
        errors.append("build_note.job_id: the material must name a valid job id")
    if errors:
        return errors
    stem = named.group(1)
    folder = "resumes" if kind == "resume" else "messages"
    maker = "resume build" if kind == "resume" else "material render --output"
    expected = tuple(f"{stem}.{extension}" for extension in (("pdf", "docx") if kind == "resume" else ("txt",)))
    root = Path(root)
    note_name = material_note_path(Path(), material_file).name
    note_path = _safe_file(root, (folder, job_id, note_name), "build_note", errors)
    if note_path is None:
        return errors + [f"build_note: rerun {maker} using the same data directory before reviewing"]
    try:
        note = read_note(note_path)
    except (OSError, ValueError):
        return [f"build_note: {note_name} is unreadable or invalid JSON; rerun {maker}"]
    errors = _note_errors(note, material, material_file.name, expected, maker)
    if errors:
        return errors
    hashes = {item["name"]: item["sha256"] for item in note["files"]}
    for name in expected:
        path = _safe_file(root, (folder, job_id, name), "outputs", errors)
        if path is None:
            continue
        try:
            content = path.read_bytes()
        except OSError:
            errors.append(f"outputs: cannot read {name}; rerun {maker}")
            continue
        if not content:
            errors.append(f"outputs: {name} is empty; rerun {maker}")
        elif hashlib.sha256(content).hexdigest() != hashes[name]:
            errors.append(f"outputs: {name} differs from its build note; rerun {maker}")
    return errors
