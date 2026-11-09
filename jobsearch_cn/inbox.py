"""Move validated local inbox JSON files into a fresh batch for jd screen."""

import os
import shlex
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from jobsearch_cn import schema, screen, store

CLIP_FOLDER = "jobsearch-inbox"


def default_folder() -> Path:
    return Path.home() / "Downloads" / CLIP_FOLDER


def _batch_dir(root: Path, site: str, now: datetime) -> Path:
    parent = store.safe_dir(root, "inbox", site)
    name = now.strftime("%Y%m%d-%H%M%S")
    for number in range(1, 1000):
        candidate = parent / (name if number == 1 else f"{name}-{number}")
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise screen.BatchError(f"cannot make a new batch folder in {parent}")


def _shell_arg(value) -> str:
    """PowerShell literal argument on Windows; POSIX shell argument elsewhere."""
    text = str(value)
    if os.name == "nt":
        return "'" + text.replace("'", "''") + "'"
    return shlex.quote(text)


def _next_argv(batch: Path, root) -> list:
    return ["python", "-m", "jobsearch_cn", "jd", "screen", os.path.abspath(batch),
            "--data-dir", os.path.abspath(root)]


def _next_command(batch: Path, root) -> str:
    argv = _next_argv(batch, root)
    return "python -m jobsearch_cn jd screen " + _shell_arg(argv[5]) + " --data-dir " + _shell_arg(argv[7])


def _move_complete(source: Path, destination: Path) -> None:
    """Copy across volumes, publish without replacement, then remove the source.

    A failed copy leaves the source and no partial destination. An unlink failure
    keeps both complete copies for manual recovery.
    """
    fd, name = tempfile.mkstemp(dir=destination.parent, prefix=".tmp-", suffix=".json")
    os.close(fd)
    temporary = Path(name)
    try:
        shutil.copyfile(source, temporary)
        os.link(temporary, destination)
        source.unlink()
    finally:
        temporary.unlink(missing_ok=True)


def import_folder(folder, root, site: str = "official", now=None) -> dict:
    folder = Path(folder)
    if site not in schema.SITES:
        raise screen.BatchError("unknown inbox site")
    if store._is_link(folder) or not folder.is_dir():
        raise screen.BatchError(f"{folder} is not a folder (or is a link); name the local inbox folder")
    files, ignored = screen.list_files(folder)
    ready, left = [], [dict(entry) for entry in ignored]
    for path in files:
        if path.suffix.lower() != ".json":
            left.append({"file": path.name, "reason": "only .json files are moved; put .txt files in a batch yourself"})
            continue
        try:
            screen.read_item(path.read_bytes(), site)
        except (screen.ItemError, OSError) as exc:
            left.append({"file": path.name, "reason": str(exc)})
            continue
        ready.append(path)
    batch, moved = None, []
    if ready:
        try:
            batch = _batch_dir(Path(root), site, now or datetime.now())
        except OSError as exc:
            raise screen.BatchError(f"cannot create inbox batch: {exc.strerror or exc}") from None
        for path in ready:
            try:
                _move_complete(path, batch / path.name)
                moved.append(path.name)
            except OSError as exc:
                left.append({"file": path.name, "reason": f"cannot move: {exc.strerror or exc}"})
        if not moved:
            try:
                batch.rmdir()
                batch = None
            except OSError:
                pass  # A complete published copy may remain if source removal failed.
    return {
        "folder": str(folder), "batch": str(batch) if batch else None,
        "moved": len(moved), "files": moved, "left": left,
        "next": _next_command(batch, root) if moved else None,
        "next_shell": ("powershell" if os.name == "nt" else "posix") if moved else None,
        "next_argv": _next_argv(batch, root) if moved else None,
    }
