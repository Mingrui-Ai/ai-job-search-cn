"""Opt-in local evidence for a collector's structure stop, from its existing Snapshot only.

No browser access, response bodies or other browser state. metadata.json is published last:
without it a directory is incomplete, even when page.html was successfully written.
"""

import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path

from jobsearch_cn import store

FORMAT = "jobsearch_cn.collect-diagnostics/1"
MAX_HTML_BYTES = 1_000_000
MAX_METADATA_BYTES = 64_000
_BATCH = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,63}")


def _write_bytes(directory: Path, path: Path, body: bytes) -> None:
    """Atomically publish a complete new file; never replace an existing path."""
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".html")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save(data_root, batch, snapshot, *, phase, reason, at) -> dict:
    """Save one stop's HTML and metadata, or describe why it could not be saved.

    All failures stay diagnostic results: they must not replace the collector's stop or
    cause it to continue. A partial directory is retained and explicitly marked incomplete.
    """
    if snapshot is None:
        return {"status": "unavailable", "complete": False, "reason": "结构停止没有可用的当次快照"}
    result = {"status": "failed", "complete": False, "directory": None, "html": None, "metadata": None}
    try:
        if not isinstance(batch, str) or not _BATCH.fullmatch(batch):
            raise ValueError("诊断批次名不安全")
        if phase not in ("list", "detail"):
            raise ValueError("诊断快照没有有效的 list/detail 阶段")
        original = snapshot.html.encode("utf-8")
        # Removing an incomplete final character preserves valid UTF-8 and the exact prefix.
        body = original[:MAX_HTML_BYTES].decode("utf-8", errors="ignore").encode("utf-8")
        truncated = len(body) != len(original)
        metadata = {
            "format": FORMAT, "batch": batch, "recorded_at": at.isoformat(timespec="microseconds"),
            "phase": phase, "stop_status": "page_changed", "stop_reason": reason,
            "url": snapshot.url, "title": snapshot.title, "http_status": snapshot.status,
            "encoding": "utf-8", "html_file": "page.html", "truncated": truncated,
            "original_bytes": len(original), "saved_bytes": len(body),
            "original_sha256": hashlib.sha256(original).hexdigest(),
            "saved_sha256": hashlib.sha256(body).hexdigest(),
        }
        if len((json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")) > MAX_METADATA_BYTES:
            raise ValueError(f"诊断元数据超过 {MAX_METADATA_BYTES} 字节，未保存")
        root = Path(data_root)
        parent = store.safe_dir(root, "collect", "diagnostics", batch)
        name = at.strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid.uuid4().hex
        directory = parent / name
        directory.mkdir()  # create-only: even a collision or a pre-existing link is refused
        result["directory"] = str(directory)
        directory = store.safe_dir(root, "collect", "diagnostics", batch, name)
        _write_bytes(directory, directory / "page.html", body)
        result["html"] = str(directory / "page.html")
        directory = store.safe_dir(root, "collect", "diagnostics", batch, name)
        store._write_json(directory, directory / "metadata.json", metadata, overwrite=False)
        result.update(status="truncated" if truncated else "saved", complete=True,
                      metadata=str(directory / "metadata.json"), truncated=truncated)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[:500]
        if result["directory"]:
            try:
                checked = store.safe_dir(root, "collect", "diagnostics", batch, name)
                result["partial_files"] = [name for name in ("page.html", "metadata.json")
                                           if os.path.lexists(checked / name)]
            except Exception:
                result["partial_files"] = None  # the directory can no longer be safely inspected
    return result
