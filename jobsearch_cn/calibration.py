"""Read-only application retrospective: recorded facts and archived score context.

No current profile/job/match reads, no scoring, writes, or outcome prediction.
See docs/cn/calibration.md for the interpretation and confirmation boundary.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import sqlite3

from jobsearch_cn import applications as app, score, store

CONTRACT_VERSION = 1
DIMENSIONS = ("skills", "direction", "experience", "salary", "location")
_HASH = re.compile(r"[0-9a-f]{64}")
_GRADES = ("strong", "good", "moderate", "weak", "poor", "ineligible", "needs_check")


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonstandard JSON constant")


def _json(data):
    value = json.loads(data, object_pairs_hook=_object, parse_constant=_constant)
    # Also rejects overflow such as 1e999 in otherwise standard JSON.
    json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
    return value


def _domain(code, application_id=None):
    return app.ApplicationError(code, "application retrospective cannot use inconsistent or changed evidence",
                                **({"application_id": application_id} if app.is_id(application_id, "app") else {}))


def _read_records(paths, ids):
    """One consistent read transaction, including the raw event tokens used by the digest."""
    connection = app._reader(paths)
    if connection is None:
        if ids:
            raise app.ApplicationError("not_found", "a selected application does not exist")
        return []
    with app._closing(connection):
        connection.execute("BEGIN")
        rows = [app._row(connection, item) for item in ids] if ids else connection.execute(
            "SELECT * FROM applications ORDER BY application_id").fetchall()
        result = []
        for row in rows:
            application_id = row["application_id"]
            errors = []
            try:
                checked = app._check_record_events(connection, row, errors, _json)
                if errors or checked is None:
                    raise _domain("inconsistent_events", application_id)
                events, _ = checked
                # Legacy validation checks timestamp syntax; also reject impossible calendar values here.
                for event in events:
                    for key in ("occurred_at", "recorded_at"):
                        if event[key] is not None:
                            app._parse_utc(event[key])
                for key in ("created_at", "updated_at"):
                    app._parse_utc(row[key])
                if type(row["revision"]) is not int or row["revision"] < 1:
                    raise ValueError("invalid revision")
                snapshots = [dict(item) for item in connection.execute(
                    "SELECT * FROM snapshots WHERE application_id = ? ORDER BY kind", (application_id,))]
                first = next((e for e in events if e["type"] == "submitted"), None)
                kinds = [item["kind"] for item in snapshots]
                if row["record_origin"] == "current" and first:
                    if kinds != ["job", "match"]:
                        raise ValueError("missing snapshot registration")
                elif snapshots:
                    raise ValueError("snapshot has no current first submission")
                for item in snapshots:
                    if (item["path"] is None) != (item["sha256"] is None):
                        raise ValueError("inconsistent snapshot registration")
                    if item["sha256"] is not None and not _hash(item["sha256"]):
                        raise ValueError("invalid archive digest")
            except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
                raise _domain("inconsistent_events", application_id) from None
            raw_events = [dict(item) for item in connection.execute(
                "SELECT * FROM events WHERE application_id = ? ORDER BY seq", (application_id,))]
            result.append({"application": dict(row), "events": events, "raw_events": raw_events,
                           "snapshots": snapshots})
        connection.execute("ROLLBACK")
        return result


def _archive_path(paths, application_id, item):
    relative = item["path"]
    parts = app._archive_parts(relative)
    if (parts is None or len(parts) != 4 or parts[1] != application_id
            or not app.is_id(parts[2], "ctx") or parts[3] != item["kind"] + ".json"):
        raise _domain("archive_integrity", application_id)
    path, refused = app._archived(paths.dir, relative)
    if refused:
        raise _domain("archive_integrity", application_id)
    # An internal junction could otherwise borrow another application's bytes.
    current = paths.dir
    for part in parts:
        current = current / part
        if store._is_link(current):
            raise _domain("archive_integrity", application_id)
    return path


def _archive_bytes(paths, application_id, item):
    path = _archive_path(paths, application_id, item)
    try:
        before = path.stat()
        if not path.is_file():
            raise _domain("archive_integrity", application_id)
        data = path.read_bytes()
        after = path.stat()
    except (FileNotFoundError, NotADirectoryError):
        raise _domain("archive_integrity", application_id) from None
    _archive_path(paths, application_id, item)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise _domain("stale_context", application_id)
    if hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise _domain("archive_integrity", application_id)
    return data


def _archives(paths, records):
    found = {}
    for record in records:
        identity = record["application"]["application_id"]
        found[identity] = {item["kind"]: _archive_bytes(paths, identity, item)
                           for item in record["snapshots"] if item["path"] is not None}
    return found


def _hash(value):
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


def _number(value, minimum=0, maximum=None):
    return (type(value) in (int, float) and math.isfinite(value) and value >= minimum
            and (maximum is None or value <= maximum))


def _time(value):
    if not isinstance(value, str) or not app._AT.fullmatch(value):
        raise ValueError("unsupported timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("timestamp has no timezone")
    # Both comparison bases must be representable before exposing a historical score.
    # An ISO year at either endpoint can overflow after applying its timezone offset.
    parsed.astimezone(timezone.utc)
    parsed.astimezone(app.LOCAL_TZ)
    return parsed


def _historical_score(value):
    """Interpret only the exposed v1 fields, retaining their original values; never rescore."""
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("unsupported match schema")
    if type(value.get("rules_version")) is not int or value["rules_version"] < 1:
        raise ValueError("invalid rules version")
    _time(value.get("scored_at"))
    if not _hash(value.get("profile_hash")) or not _hash(value.get("job_hash")):
        raise ValueError("invalid digest")
    dimensions, weights, total = value.get("dimensions"), value.get("weights"), value.get("total")
    if not isinstance(dimensions, dict) or not dimensions or not set(dimensions) <= set(DIMENSIONS):
        raise ValueError("unsupported dimensions")
    if not isinstance(weights, dict) or set(weights) != set(dimensions):
        raise ValueError("unsupported weights")
    if not all(_number(weight) for weight in weights.values()) or not any(weights.values()):
        raise ValueError("invalid weights")
    if not math.isfinite(sum(weights.values())):
        raise ValueError("overflowing weights")
    scores = {}
    for key in DIMENSIONS:
        if key not in dimensions:
            scores[key] = None  # A missing old dimension is not a zero or an unscored present dimension.
            continue
        item = dimensions[key]
        if (not isinstance(item, dict) or "score" not in item or item.get("method") not in ("rule", "agent")
                or (item["score"] is not None and not _number(item["score"], maximum=100))):
            raise ValueError("invalid dimension")
        scores[key] = {"score": item["score"], "method": item["method"]}
    if (not isinstance(total, dict) or set(total) != {"score", "grade", "complete", "missing"}
            or (total["score"] is not None and not _number(total["score"], maximum=100))
            or total["grade"] not in _GRADES or type(total["complete"]) is not bool
            or not isinstance(total["missing"], list)
            or any(not isinstance(key, str) or key not in DIMENSIONS for key in total["missing"])
            or len(total["missing"]) != len(set(total["missing"]))):
        raise ValueError("invalid total")
    return {"schema_version": 1, "rules_version": value["rules_version"], "scored_at": value["scored_at"],
            "profile_hash": value["profile_hash"], "job_hash": value["job_hash"], "weights": weights,
            "dimensions": scores, "absent_dimensions": [key for key in DIMENSIONS if key not in dimensions],
            "total": total}


def _safe_label(value):
    if value is None:
        return None
    if (not isinstance(value, str) or not value.strip() or len(value) > 200
            or not value.isprintable()
            or any(pattern.search(value) for _, pattern in app._CONTACT_LIKE)):
        raise ValueError("unsafe label")
    return value


def _warning(warnings, application_id, code, kind):
    warnings.append({"application_id": application_id, "code": code, "kind": kind})


def _timing(historical, submitted):
    if historical is None or submitted is None:
        return "unknown"
    moment = _time(historical["scored_at"])
    if submitted["occurred_at"]:
        other = app._parse_utc(submitted["occurred_at"])
        return "before" if moment < other else "after" if moment > other else "at_submission"
    if submitted["occurred_on"]:
        day = moment.astimezone(app.LOCAL_TZ).date().isoformat()
        return ("before" if day < submitted["occurred_on"] else "after" if day > submitted["occurred_on"]
                else "same_day_order_unknown")
    return "unknown"


def _event_summary(event):
    result = {key: event[key] for key in ("event_id", "seq", "type", "occurred_at", "occurred_on",
                                         "recorded_at", "voided_by")}
    result["source_kind"] = event["source"]["kind"]
    if event["type"] == "status_changed":
        result.update(from_status=event["payload"]["from"], to_status=event["payload"]["to"])
    elif event["type"] == "event_voided":
        result["target_event_id"] = event["payload"]["target_event_id"]
    return result


def _row(record, raw, warnings):
    application, events = record["application"], record["events"]
    identity, job_id = application["application_id"], application["job_id"]
    first = next((event for event in events if event["type"] == "submitted"), None)
    submitted = next((event for event in events if event["type"] == "submitted" and not event["voided_by"]), None)
    snapshots = {kind: None for kind in ("job", "match")}
    for item in record["snapshots"]:
        if item["path"] is not None:
            snapshots[item["kind"]] = {"context_id": item["path"].split("/")[2], "sha256": item["sha256"]}
    context_ids = {item["context_id"] for item in snapshots.values() if item is not None}
    if len(context_ids) > 1:
        raise _domain("archive_integrity", identity)
    loaded, readability = {}, {}
    for kind in ("job", "match"):
        readability[kind] = "missing" if kind not in raw else "supported"
        if kind not in raw:
            continue
        try:
            value = _json(raw[kind])
            if not isinstance(value, dict):
                raise ValueError("unsupported object")
            key = "id" if kind == "job" else "job_id"
            if value.get(key) is not None and value[key] != job_id:
                raise _domain("job_binding", identity)
            if value.get(key) != job_id:
                raise ValueError("missing identity")
            if kind == "job" and (type(value.get("schema_version")) is not int or value["schema_version"] != 1):
                raise ValueError("unsupported job schema")
            loaded[kind] = value
        except (ValueError, TypeError, RecursionError):
            readability[kind] = "unsupported"
            _warning(warnings, identity, "archive_content_unsupported", kind)
    historical = None
    if "match" in loaded:
        try:
            historical = _historical_score(loaded["match"])
        except (ValueError, KeyError, TypeError, OverflowError):
            readability["match"] = "unsupported"
            _warning(warnings, identity, "archive_content_unsupported", "match")
    labels = {"title": None, "company": None}
    if "job" in loaded:
        for key in labels:
            try:
                labels[key] = _safe_label(loaded["job"].get(key))
            except ValueError:
                _warning(warnings, identity, "label_omitted", key)
    binding = "unavailable"
    if historical is not None and "job" in loaded:
        binding = "verified_current_digest" if score.job_hash(loaded["job"]) == historical["job_hash"] else "not_verified"
    submission_binding = ("not_submitted" if first is None else "no_effective_submission" if submitted is None
                          else "first_submission" if first["event_id"] == submitted["event_id"]
                          else "first_submission_reused")
    timing = _timing(historical, submitted)
    exclusions = []
    if not submitted:
        exclusions.append("no_effective_submission")
    if historical is None:
        exclusions.append("historical_score_unavailable")
    elif historical["total"]["score"] is None:
        exclusions.append("historical_total_unavailable")
    if binding != "verified_current_digest":
        exclusions.append("job_binding_" + binding)
    if submission_binding != "first_submission":
        exclusions.append("submission_" + submission_binding)
    if timing not in ("before", "at_submission"):
        exclusions.append("score_timing_" + timing)
    quality = {"archive_integrity": "verified" if raw else "no_archived_files",
               "snapshot_origin": ("historical_without_snapshot" if application["record_origin"] == "historical"
                                   else "first_registered_submission" if first else "not_submitted"),
               "readability": readability, "submission_binding": submission_binding, "score_timing": timing,
               "job_binding": binding, "historical_profile_check": "unavailable"}
    milestones = {}
    for name in ("interview", "offer", "hired"):
        ids = [e["event_id"] for e in events if not e["voided_by"] and e["type"] == "status_changed"
               and e["payload"]["to"] == name]
        milestones[name + "_recorded"] = {"recorded": bool(ids), "event_ids": ids}
    replies = [e["event_id"] for e in events if not e["voided_by"] and e["type"] == "reply_received"]
    return {"application_id": identity, "job_id": job_id, "revision": application["revision"], **labels,
            "record_origin": application["record_origin"], "status": application["status"],
            "channel_kind": application["channel_kind"], "events": [_event_summary(e) for e in events],
            "submission": {"confirmed": submitted is not None,
                           "event_id": submitted["event_id"] if submitted else None,
                           "occurred_at": submitted["occurred_at"] if submitted else None,
                           "occurred_on": submitted["occurred_on"] if submitted else None,
                           "recorded_at": submitted["recorded_at"] if submitted else None,
                           "first_registered_event_id": first["event_id"] if first else None,
                           "first_registered_at": first["recorded_at"] if first else None},
            "milestones": milestones, "reply_recorded": {"recorded": bool(replies), "event_ids": replies},
            "snapshots": snapshots, "quality": quality, "historical_score": historical,
            "descriptive_comparison": {"eligible": not exclusions, "excluded_reasons": exclusions}}


def _summary(rows):
    jobs, groups = defaultdict(list), {}
    for row in rows:
        jobs[row["job_id"]].append(row["application_id"])
        historical = row["historical_score"]
        row["basis_group_id"] = None
        if historical is None:
            continue
        basis = {key: historical[key] for key in ("rules_version", "profile_hash", "weights")}
        basis["scored_dimensions"] = [key for key in DIMENSIONS if historical["dimensions"][key] is not None
                                      and historical["dimensions"][key]["score"] is not None]
        group_id = _digest(basis)
        row["basis_group_id"] = group_id
        group = groups.setdefault(group_id, {"basis_group_id": group_id, "basis": basis,
                                             "application_ids": [], "comparison_application_ids": []})
        group["application_ids"].append(row["application_id"])
        if row["descriptive_comparison"]["eligible"]:
            group["comparison_application_ids"].append(row["application_id"])
    return {"application_count": len(rows), "submitted_application_count": sum(r["submission"]["confirmed"] for r in rows),
            "distinct_job_count": len(jobs),
            "duplicate_jobs": [{"job_id": job, "application_ids": ids, "application_count": len(ids)}
                               for job, ids in sorted(jobs.items()) if len(ids) > 1],
            "current_status_counts": {status: sum(r["status"] == status for r in rows) for status in app.STATUSES},
            "milestone_counts": {name: sum(r["milestones"][name]["recorded"] for r in rows)
                                 for name in ("interview_recorded", "offer_recorded", "hired_recorded")},
            "reply_recorded_count": sum(r["reply_recorded"]["recorded"] for r in rows),
            "historical_score_count": sum(r["historical_score"] is not None for r in rows),
            "comparison_count": sum(r["descriptive_comparison"]["eligible"] for r in rows),
            "quality_counts": {key: dict(sorted(Counter(r["quality"][key] for r in rows).items())) for key in
                               ("archive_integrity", "snapshot_origin", "submission_binding", "score_timing", "job_binding")},
            "basis_groups": [groups[key] for key in sorted(groups)]}


def retrospective(data_root, application_ids=None):
    """Return a deterministic derived view, refusing changed inputs instead of retrying."""
    if any(not app.is_id(value, "app") for value in application_ids or ()):
        raise app.ApplicationError("invalid", "application ids must have app_ and 32 hex digits")
    ids = sorted(set(application_ids or ()))
    paths = app.Paths(data_root)
    try:
        records = _read_records(paths, ids)
        archives = _archives(paths, records)
        warnings = []
        rows = [_row(record, archives[record["application"]["application_id"]], warnings) for record in records]
        summary = _summary(rows)
        # A second transaction sees updates committed after the first read; archives are reread as bytes too.
        current = _read_records(paths, ids)
        if current != records:
            raise _domain("stale_context")
        if _archives(paths, current) != archives:
            raise _domain("stale_context")
        tokens = {"contract_version": CONTRACT_VERSION, "requested_ids": ids,
                  "scope_mode": "selected" if ids else "all", "records": records,
                  "archive_bytes": {identity: {kind: hashlib.sha256(body).hexdigest() for kind, body in blobs.items()}
                                    for identity, blobs in archives.items()}}
        return {"schema_version": 1, "generated_at": app.now_utc(), "evidence_hash": _digest(tokens),
                "scope": {"mode": "selected" if ids else "all", "application_ids": [r["application_id"] for r in rows],
                          "time_basis": "current_recorded_observation", "unit": "application_attempt"},
                "rows": rows, "summary": summary, "warnings": warnings}
    except app.StorageError:
        raise app.StorageError("application retrospective could not read the database or archive files") from None
    except (sqlite3.Error, OSError):
        raise app.StorageError("application retrospective could not read the database or archive files") from None
