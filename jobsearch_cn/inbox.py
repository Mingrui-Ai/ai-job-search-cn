"""jd inbox-import: move the files the boss-clip browser extension saved into a new inbox batch.

The extension (extensions/boss-clip/, docs/cn/boss-clip.md) can only write below the browser's
download folder, so it saves one inbox JSON per job in <Downloads>/jobsearch-boss-clip/. This
moves every file there that is in the inbox format (screen.read_item) into a new batch folder
<data dir>/inbox/<site>/<YYYYMMDD-HHMMSS>/, for jd screen. Files that are not in the format stay
where they are and are listed with the reason. Nothing is parsed into the job store here.
"""

import os
import shlex
import shutil
from datetime import datetime
from pathlib import Path

from jobsearch_cn import screen, store

CLIP_FOLDER = "jobsearch-boss-clip"


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


def _shell_arg(path) -> str:
    """One path as a command-line argument for this system's shells, whatever spaces it holds.

    On Windows the double quotes suit cmd, PowerShell and Git Bash alike. A backslash right before
    the closing quote (a drive root as the data folder) would escape it, so it is doubled.
    """
    text = str(path)
    if os.name != "nt":
        return shlex.quote(text)
    return '"' + text + "\\" * (len(text) - len(text.rstrip("\\"))) + '"'


def _next_command(batch: Path, root) -> str:
    """jd screen on the batch, in the data folder this import used, not whichever the next run defaults to."""
    return (f"python -m jobsearch_cn jd screen {_shell_arg(os.path.abspath(batch))} "
            f"--data-dir {_shell_arg(os.path.abspath(root))}")


def import_folder(folder, root, site: str = "boss", now=None) -> dict:
    """Move the inbox files in folder into a new batch; the batch folder is made only if one moves."""
    folder = Path(folder)
    if store._is_link(folder) or not folder.is_dir():
        raise screen.BatchError(f"{folder} is not a folder (or is a link); the extension saves into "
                                f"<下载目录>/{CLIP_FOLDER}, name that folder")
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
        batch = _batch_dir(Path(root), site, now or datetime.now())
        for path in ready:
            try:
                shutil.move(str(path), str(batch / path.name))
                moved.append(path.name)
            except OSError as exc:
                left.append({"file": path.name, "reason": f"cannot move: {exc.strerror or exc}"})
    return {
        "folder": str(folder),
        "batch": str(batch) if batch else None,
        "moved": len(moved),
        "files": moved,
        "left": left,
        "next": _next_command(batch, root) if moved else None,
    }
