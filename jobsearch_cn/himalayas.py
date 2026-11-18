"""Offline interpretation of the public Himalayas API and its original inbox export."""

from copy import deepcopy
from datetime import datetime
import hashlib
import re
from urllib.parse import urlsplit


_PATH = re.compile(r"/companies/([a-z0-9-]+)/jobs/([a-z0-9-]+)")
_LEGACY_DATE = re.compile(r"(?m)^发布日期：(\d{4}-\d{2}-\d{2})$")


def guid(url):
    """Official GUID components, including for the old application URL with attribution."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    match = _PATH.fullmatch(parts.path)
    if parts.scheme != "https" or parts.netloc.lower() != "himalayas.app" or not match:
        return None
    return "/".join(match.groups())


def site_id(identifier):
    return hashlib.sha256(identifier.encode("ascii")).hexdigest()


def corrected_text(text):
    """Correct only the generated date in a legacy header. Preserve every line of the JD body."""
    header, sep, body = text.partition("\n\n")
    if "来源：Himalayas" in header.splitlines():
        header = _LEGACY_DATE.sub(r"来源最后更新（UTC）：\1", header, count=1)
    return header + sep + body


def older_snapshot(incoming, saved):
    """A historical inbox replay must not undo a later observation of this posting."""
    latest = saved.get("fetched_at")
    seen = incoming.get("fetched_at")
    if not seen or not latest:
        return False
    return datetime.fromisoformat(seen.replace("Z", "+00:00")) < datetime.fromisoformat(latest.replace("Z", "+00:00"))


def upgrade_legacy(record, source):
    """Retain the original job ID, status and any user/agent evidence on ordinary reimport."""
    old = deepcopy(record)
    header, _, _ = old["raw_text"].partition("\n\n")
    legacy_date = _LEGACY_DATE.search(header)
    old["raw_text"] = corrected_text(old["raw_text"])
    old["source"].update(site="himalayas", site_job_id=source["site_job_id"])
    citation = old["evidence"].get("published_at", {})
    if legacy_date and citation.get("method") == "rule" and citation.get("text") == legacy_date.group():
        old["published_at"] = None
        old["evidence"].pop("published_at")
    return old
