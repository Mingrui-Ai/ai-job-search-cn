"""Command line interface: python -m jobsearch_cn <command> ...

Every command prints JSON on stdout, so Codex, Claude Code and scripts read the
same output. Exit codes: 0 success; 1 the input was read but is invalid, held
no JD, or names no stored job; 2 the input could not be read, reported as
{"error": ...} on stderr (argparse also exits 2 on a malformed command line).
`collect` adds 3 (stopped at a security check or sign-in page: the user deals
with it in the browser and reruns) and 4 (a page it could not recognise).
"""

import argparse
import codecs
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from jobsearch_cn import (__version__, boss, browser, collect, jd_parser, match, material, messages, profile, report,
                          resume_docx, resume_extract, resume_pdf, review, schema, score, store, vocab)
from jobsearch_cn import applications as applications_mod

_HAN_FIRST, _HAN_LAST = chr(0x4E00), chr(0x9FFF)


class InputError(Exception):
    """The input could not be read or decoded."""


def _force_utf8_output() -> None:
    """Write UTF-8 whatever the host's default encoding is.

    A piped stdout on Windows defaults to the ANSI code page: cp936 (GBK) on a
    Chinese install, cp1252 on most Western ones. GBK output reaches the agent
    as mojibake; cp1252 cannot encode Chinese at all and raises
    UnicodeEncodeError before any output is written.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)  # absent on a StringIO under test
        if reconfigure:
            reconfigure(encoding="utf-8")


def _emit(payload, stream=None) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=stream or sys.stdout)


def _read_bytes(source: str):
    """(bytes, display name) from a file, or from stdin when source is "-"."""
    if source == "-":
        return sys.stdin.buffer.read(), "stdin"
    try:
        return Path(source).read_bytes(), source
    except OSError as exc:
        raise InputError(f"cannot read {source}: {exc.strerror or exc}") from None


def _read_json_text(source: str) -> str:
    """JSON input: UTF-8 only (RFC 8259), with or without the BOM Windows Notepad writes."""
    data, name = _read_bytes(source)
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InputError(f"{name} is not UTF-8 text; save it as UTF-8 and retry") from None


def _read_jd_text(source: str):
    """JD text as Windows users actually save it. Returns (text, warnings).

    UTF-8 with or without a BOM; UTF-16 with a BOM, which is what Windows
    PowerShell 5.1's `>` and Out-File write; otherwise GB18030 (a superset of
    GBK, the Chinese ANSI code page) with a warning. Text with no Chinese but
    runs of "?" is refused: that is what Windows PowerShell 5.1 delivers when it
    pipes Chinese to a program as ASCII, and parsing it would store garbage.
    """
    data, name = _read_bytes(source)
    warnings = []
    try:
        if data.startswith(codecs.BOM_UTF8):
            text = data[len(codecs.BOM_UTF8):].decode("utf-8")
        elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            text = data.decode("utf-16")
        else:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("gb18030")
                warnings.append({"segment": None, "kind": "encoding",
                                 "message": f"{name} is not UTF-8; decoded as GB18030 (GBK)"})
    except UnicodeDecodeError:
        raise InputError(f"{name} is neither UTF-8, UTF-16 nor GBK text") from None
    has_han = any(_HAN_FIRST <= char <= _HAN_LAST for char in text)
    if not has_han and "??" in text and text.count("?") >= 4:
        raise InputError(
            f"{name} has no Chinese characters but many '?': Windows PowerShell 5.1 pipes text "
            "to programs as ASCII. Pass the file path instead, or run "
            "$OutputEncoding = [System.Text.UTF8Encoding]::new() first."
        )
    return text, warnings


def cmd_jd_validate(args) -> int:
    text = _read_json_text(args.file)
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        name = "stdin" if args.file == "-" else args.file
        raise InputError(f"{name} is not valid JSON: {exc}") from None
    errors = schema.validate(record)
    _emit({"valid": not errors, "errors": errors})
    return 1 if errors else 0


def cmd_jd_parse(args) -> int:
    if args.url is not None and not args.url.startswith(("https://", "http://")):
        raise InputError("--url must be an http(s) URL")
    text, warnings = _read_jd_text(args.file)
    try:
        vocabulary = vocab.load(store.data_dir(args.data_dir))
    except vocab.VocabularyError as exc:
        raise InputError(str(exc)) from None
    try:
        jobs, parse_warnings = jd_parser.parse_text(
            text, source_type="paste" if args.file == "-" else "file", site=args.site, url=args.url,
            vocabulary=vocabulary,
        )
    except ValueError as exc:
        raise InputError(str(exc)) from None
    payload = {"jobs": jobs, "warnings": warnings + parse_warnings}
    if args.save and jobs:
        payload["saved"] = _save_all(_store(args), jobs)
    _emit(payload)
    return 0 if jobs else 1


def _store(args) -> store.Store:
    return store.Store(store.data_dir(args.data_dir))


def _summary(record: dict) -> dict:
    return {key: record.get(key) for key in ("id", "title", "company", "cities", "status")}


def _save_all(job_store: store.Store, records: list) -> list:
    saved = []
    for record in records:
        try:
            action, stored = job_store.save(record)
        except store.StoreError as exc:
            raise InputError(str(exc)) from None
        saved.append({"action": action, **_summary(stored)})
    return saved


def cmd_jd_save(args) -> int:
    try:
        payload = json.loads(_read_json_text(args.file))
    except json.JSONDecodeError as exc:
        raise InputError(f"input is not valid JSON: {exc}") from None
    # A single record, or the {"jobs": [...]} that jd parse prints.
    records = payload.get("jobs") if isinstance(payload, dict) and "jobs" in payload else [payload]
    if not isinstance(records, list) or not records:
        raise InputError('expected a job record or {"jobs": [...]}')
    # All or nothing: report every invalid record and store none of them.
    invalid = [{"index": index, "errors": errors} for index, record in enumerate(records)
               if (errors := schema.validate(record))]
    if invalid:
        _emit({"saved": [], "invalid": invalid})
        return 1
    _emit({"saved": _save_all(_store(args), records), "invalid": []})
    return 0


def cmd_jd_list(args) -> int:
    records, warnings = _store(args).all()
    if args.status:
        records = [r for r in records if r.get("status") == args.status]
    _emit({"jobs": [_summary(r) for r in records], "warnings": warnings})
    return 0


def cmd_jd_show(args) -> int:
    try:
        record = _store(args).get(args.id)
    except store.StoreError as exc:
        raise InputError(str(exc)) from None
    if record is None:
        _emit({"error": f"no stored job {args.id}"}, sys.stderr)
        return 1
    _emit(record)
    return 0


def cmd_jd_status(args) -> int:
    job_store = _store(args)
    try:
        if job_store.get(args.id) is None:
            _emit({"error": f"no stored job {args.id}"}, sys.stderr)
            return 1
        record = job_store.set_status(args.id, args.status)
    except store.StoreError as exc:
        raise InputError(str(exc)) from None
    _emit(_summary(record))
    return 0


def _profile_paths(args):
    root = store.data_dir(args.data_dir) / "profile"
    return (Path(args.file) if args.file else root / "profile.json"), root


def _load_profile(path: Path) -> dict:
    if not path.is_file():
        raise InputError(f"no profile at {path}; build one with the cn-setup workflow (docs/cn/profile-setup.md)")
    try:
        return json.loads(_read_json_text(str(path)))
    except json.JSONDecodeError as exc:
        raise InputError(f"{path} is not valid JSON: {exc}") from None


def cmd_profile_validate(args) -> int:
    path, root = _profile_paths(args)
    data = _load_profile(path)
    try:
        groups = set(vocab.load(store.data_dir(args.data_dir)).groups)
    except vocab.VocabularyError as exc:
        raise InputError(str(exc)) from None
    sources_dir = root / "sources"
    sources = {p.name for p in sources_dir.iterdir() if p.is_file()} if sources_dir.is_dir() else set()
    errors = profile.validate(data, sources=sources, groups=groups)
    warnings = profile.warnings(data)
    notes = root / "notes.md"
    if not notes.is_file():
        warnings.append("notes.md is missing; CVs and greetings will have no free-text material")
    else:
        try:
            notes.read_bytes().decode("utf-8-sig")
        except UnicodeDecodeError:
            errors.append("notes.md: not UTF-8 text; save it as UTF-8")
    _emit({"valid": not errors, "errors": errors, "warnings": warnings})
    return 1 if errors else 0


def cmd_profile_show(args) -> int:
    path, _ = _profile_paths(args)
    data = _load_profile(path)
    if not args.contact and not isinstance(data, dict):
        # Nothing to mask the contact details in: say what is wrong without echoing the file.
        raise InputError(f"{path}: must be a JSON object; run profile validate")
    _emit(data if args.contact else profile.redacted(data))
    return 0


def cmd_profile_extract(args) -> int:
    try:
        text = resume_extract.extract_text(args.file)
    except resume_extract.ExtractionError as exc:
        raise InputError(str(exc)) from None
    _emit({"source": Path(args.file).name, "text": text})
    return 0


def _stored_job(job_store: store.Store, job_id):
    try:
        return job_store.get(job_id)
    except store.StoreError as exc:
        raise InputError(str(exc)) from None


def _match_profile(args):
    """The profile a match compares against, or None after reporting why it is unusable."""
    path = Path(args.profile) if args.profile else store.data_dir(args.data_dir) / "profile" / "profile.json"
    data = _load_profile(path)
    # Structure only: whether the source files are still there does not change a match.
    errors = profile.validate(data)
    if errors:
        _emit({"error": "the profile is invalid; run profile validate", "errors": errors}, sys.stderr)
        return None
    return data


def _vocabulary(args) -> vocab.Vocabulary:
    try:
        return vocab.load(store.data_dir(args.data_dir))
    except vocab.VocabularyError as exc:
        raise InputError(str(exc)) from None


def _matches(args) -> store.MatchStore:
    return store.MatchStore(store.data_dir(args.data_dir))


def cmd_match_filter(args) -> int:
    job = _stored_job(_store(args), args.id)
    if job is None:
        _emit({"error": f"no stored job {args.id}"}, sys.stderr)
        return 1
    data = _match_profile(args)
    if data is None:
        return 1
    _emit(match.filter_job(job, data))
    return 0


def cmd_match_score(args) -> int:
    job = _stored_job(_store(args), args.id)
    if job is None:
        _emit({"error": f"no stored job {args.id}"}, sys.stderr)
        return 1
    data = _match_profile(args)
    if data is None:
        return 1
    matches = _matches(args)
    record = score.score_job(job, data, _vocabulary(args), previous=_saved_match(matches, args.id))
    try:
        if args.save:
            matches.save(record)
        if args.draft:
            matches.write_draft(record)
    except store.StoreError as exc:
        raise InputError(str(exc)) from None
    _emit(record)
    return 0


def _saved_match(matches: store.MatchStore, job_id):
    try:
        return matches.get(job_id)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None  # an unreadable record is scored afresh, as if there were none


def _checked_match(args):
    """(record, errors) for a match file against the stored job and the profile; errors None if unusable."""
    text = _read_json_text(args.file)
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        name = "stdin" if args.file == "-" else args.file
        raise InputError(f"{name} is not valid JSON: {exc}") from None
    job_id = record.get("job_id") if isinstance(record, dict) else None
    job = _stored_job(_store(args), job_id) if isinstance(job_id, str) and job_id else None
    if job is None:
        return record, [f"job_id: no stored job {job_id!r}"]
    data = _match_profile(args)
    if data is None:
        return record, None
    return record, score.validate(record, job, data, _vocabulary(args))


def cmd_match_validate(args) -> int:
    _, errors = _checked_match(args)
    if errors is None:
        return 1
    _emit({"valid": not errors, "errors": errors})
    return 1 if errors else 0


def _read_material(source: str):
    text = _read_json_text(source)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        name = "stdin" if source == "-" else source
        raise InputError(f"{name} is not valid JSON: {exc}") from None


def _material_job(args, record):
    """The stored JD a material is for, or None. It only adds warnings and coverage rows, so a job not stored is no error."""
    job_id = record.get("job_id") if isinstance(record, dict) else None
    if isinstance(job_id, str) and job_id:
        try:
            return _store(args).get(job_id)
        except store.StoreError:
            pass  # not a job id the store can look up: the warnings skip the JD
    return None


def _material_notes(args, record):
    """The notes.md beside the profile a material is checked against, read only when its summary cites it."""
    summary = record.get("summary") if isinstance(record, dict) else None
    if not (isinstance(summary, dict) and isinstance(summary.get("refs"), list)
            and material.NOTES_REF in summary["refs"]):
        return None
    path = Path(args.profile) if args.profile else store.data_dir(args.data_dir) / "profile" / "profile.json"
    return material.read_notes(path.parent / "notes.md")


def _message_files(args):
    try:
        root = store.data_dir(args.data_dir)
        return messages.load_templates(root), messages.load_banned(root)
    except messages.TemplateError as exc:
        raise InputError(str(exc)) from None


def _is_message(record) -> bool:
    """A greeting, email or referral (messages.py), not a CV (material.py)."""
    return isinstance(record, dict) and record.get("kind") in messages.KINDS


def _check_material(args, record, data, job, vocabulary=None):
    """(errors, warnings) for a CV, with the notes.md beside the profile that its summary may cite, or for a
    greeting, email or referral against its template (messages.py, which cites no notes.md). material validate,
    material render, resume build and review draft all check through here, so they come to one verdict."""
    vocabulary = _vocabulary(args) if vocabulary is None else vocabulary
    if _is_message(record):
        # Unlike a CV, a message that cites the job or fills {job.title} needs it stored: messages.validate says so.
        templates, banned = _message_files(args)
        return messages.validate(record, data, vocabulary, job, templates, banned)
    if isinstance(record, dict) and isinstance(record.get("kind"), str) and record["kind"] not in material.KINDS:
        # A misspelled kind (greet) is neither a CV nor a message: name the kinds, not the CV fields it lacks.
        return [f"kind: must be one of {', '.join(material.KINDS + messages.KINDS)}"], []
    return material.validate(record, data, vocabulary, job, _material_notes(args, record))


def cmd_material_validate(args) -> int:
    record = _read_material(args.file)
    data = _match_profile(args)
    if data is None:
        return 1
    errors, warnings = _check_material(args, record, data, _material_job(args, record))
    _emit({"valid": not errors, "errors": errors, "warnings": warnings})
    return 1 if errors else 0


def cmd_material_template(args) -> int:
    job = _stored_job(_store(args), args.job_id)
    if job is None:
        _emit({"error": f"no stored job {args.job_id}"}, sys.stderr)
        return 1
    data = _match_profile(args)
    if data is None:
        return 1
    templates, _ = _message_files(args)
    try:
        result = messages.template_for(job, data, _vocabulary(args), templates, args.kind, args.direction)
    except messages.TemplateError as exc:
        raise InputError(str(exc)) from None
    _emit({"job_id": args.job_id, **result})
    return 0


def cmd_material_render(args) -> int:
    record = _read_material(args.file)
    data = _match_profile(args)
    if data is None:
        return 1
    kind = record.get("kind") if isinstance(record, dict) else None
    if not _is_message(record) and (kind in material.KINDS or not isinstance(kind, str)):
        raise InputError(f"material render renders {', '.join(messages.KINDS)}; a CV is built with resume build")
    # A misspelled kind is checked as material validate checks it, so the two say the same.
    job = _material_job(args, record)
    errors, warnings = _check_material(args, record, data, job)
    if errors:
        _emit({"valid": False, "errors": errors, "warnings": warnings})
        return 1
    text = messages.render(record, data, job)
    if not args.output:
        print(text)
        for warning in warnings:
            print(f"警告：{warning}", file=sys.stderr)
        return 0
    # --output (M3-6): the text goes to a file, never to stdout, since an email's signature carries the
    # phone and the email address that the agent's replies must not show.
    named = _MESSAGE_NAME.fullmatch(Path(args.file).name)
    if not named or named.group(1).split("-")[0] != kind:
        raise InputError(f"{args.file}: material render --output takes a material file named {kind}-<n>.json "
                         "and names the text file after it")
    if not schema.is_job_id(record["job_id"]):
        raise InputError(f"job_id: {record['job_id']!r} is not a job id; the text goes in a folder named after it")
    try:
        directory = store.safe_dir(store.data_dir(args.data_dir), "messages", record["job_id"])
    except store.StoreError as exc:
        raise InputError(str(exc)) from None
    output = directory / f"{named.group(1)}.txt"
    if output.is_symlink():
        raise InputError(f"{output} is a link; nothing is written through it")
    resume_pdf._replace(output, f"{text}\n".encode("utf-8"))
    note = _write_build_note(directory, named.group(1), record, data, (output,), "message-build")
    # chars is counted as the length limit counts it (material.md 7.3), and max_chars is that limit, so the
    # two can be shown side by side: not the .txt, whose 标题： line and line breaks the limit leaves out (#133).
    templates, _ = _message_files(args)
    _emit({"text": str(output), "chars": messages.body_chars(record, data, job),
           "max_chars": templates[record["direction"]][kind]["max_chars"], "warnings": warnings,
           "build_note": str(note)})
    return 0


def cmd_review_draft(args) -> int:
    record = _read_material(args.file)
    data = _match_profile(args)
    if data is None:
        return 1
    vocabulary = _vocabulary(args)
    job = _material_job(args, record)
    errors, _ = _check_material(args, record, data, job, vocabulary)
    if errors:
        _emit({"error": "the material is invalid; run material validate first", "errors": errors}, sys.stderr)
        return 1
    result = review.draft(record, data, job, vocabulary)
    result = {"material_hash": review.material_hash(record), "job_found": job is not None, **result}
    _emit(result)
    return 0


def _checked_review(args):
    """(review, errors, warnings) for a review file, checked against the material it names."""
    record = _read_material(args.file)  # a review is JSON read the same way as a material
    if args.material:
        material_path = Path(args.material)
    elif isinstance(record, dict) and isinstance(record.get("material"), str) and args.file != "-":
        # Only a bare file name next to the review: a review never points elsewhere.
        material_path = Path(args.file).parent / Path(record["material"]).name
    else:
        raise InputError("cannot tell which material this review is of; pass --material")
    target = _read_material(str(material_path))
    errors, warnings = review.validate(record, target)
    return record, errors, warnings


def cmd_review_validate(args) -> int:
    _, errors, warnings = _checked_review(args)
    _emit({"valid": not errors, "errors": errors, "warnings": warnings})
    return 1 if errors else 0


def cmd_review_show(args) -> int:
    record, errors, warnings = _checked_review(args)
    if errors:
        _emit({"valid": False, "errors": errors, "warnings": warnings})
        return 1
    print(review.markdown(record), end="")
    return 0


def cmd_match_save(args) -> int:
    record, errors = _checked_match(args)
    if errors is None:
        return 1
    if errors:
        _emit({"valid": False, "errors": errors})
        return 1
    try:
        saved = _matches(args).save(record)
    except store.StoreError as exc:
        raise InputError(str(exc)) from None
    _emit({"saved": saved, "job_id": record["job_id"]})
    return 0


def cmd_match_show(args) -> int:
    try:
        record = _matches(args).get(args.id)
    except store.StoreError as exc:
        raise InputError(str(exc)) from None
    if record is None:
        _emit({"error": f"no match record for {args.id}; run match score {args.id} --save"}, sys.stderr)
        return 1
    _emit(record)
    return 0


def cmd_match_list(args) -> int:
    data = _match_profile(args)
    if data is None:
        return 1
    trial = None if args.weights is None else _trial_weights(args.weights)
    digest, weights, job_store = score.profile_hash(data), score.weights_of(data), _store(args)
    records, warnings = _matches(args).all()
    rows = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("job_id"), str):
            warnings.append("a match record without a job_id, skipped")
            continue
        try:
            job = job_store.get(record["job_id"])
        except store.StoreError:
            job = None
        saved = record.get("total") if isinstance(record.get("total"), dict) else {}
        total = saved if trial is None else score.trial_total(record, trial)
        # Stale: the job, the profile or its weights changed since scoring (or the job is gone); score it again.
        reasons = score.stale_reasons(record, job, digest, weights)
        row = {
            "job_id": record["job_id"],
            "title": job.get("title") if job else None,
            "company": job.get("company") if job else None,
            "grade": total.get("grade"),
            "score": total.get("score"),
            "complete": total.get("complete"),
            "verdict": (record.get("filter") or {}).get("verdict"),
            "stale": bool(reasons),
            "stale_reasons": reasons,
        }
        if trial is not None:
            row["saved"] = {"grade": saved.get("grade"), "score": saved.get("score")}
        rows.append(row)
    rows.sort(key=lambda row: score.list_key(row["grade"], row["score"], row["job_id"]))
    payload = {"matches": rows, "warnings": warnings}
    if trial is not None:
        payload = {"trial": {"note": TRIAL_NOTE, "weights": trial, "shares": score.shares(trial),
                             "profile": {"weights": weights, "shares": score.shares(weights)}}, **payload}
    _emit(payload)
    return 0


TRIAL_NOTE = ("试算：按这组权重和已保存的各维度分数重新算总分、等级和排序，只输出，不改档案和匹配记录。"
              "要换成这组权重，改档案的 target.weights，再重新评分。")
_TRIAL_EXAMPLE = "skills=30,direction=25,experience=25,salary=10,location=10"
_NAMED_NUMBER = re.compile(r"([a-z]+)=(\d+(?:\.\d+)?)")


def _trial_weights(text: str) -> dict:
    """match list --weights "skills=30,direction=25,..." as the weights it names, checked as the profile's are.

    Not JSON: Windows PowerShell 5.1 drops the double quotes inside an argument it passes to a program.
    """
    weights = {}
    for part in text.split(","):
        found = _NAMED_NUMBER.fullmatch(part.strip())
        if not found or found.group(1) in weights:
            raise InputError(f"--weights: {part.strip()!r} is not one dimension=number; "
                             f"name each dimension once, like {_TRIAL_EXAMPLE}")
        name, number = found.groups()
        weights[name] = float(number) if "." in number else int(number)
    errors = profile.weight_errors(weights, "--weights")
    if errors:
        raise InputError("; ".join(errors))
    return {key: weights[key] for key in score.DIMENSIONS}


def _report_records(args, matches: store.MatchStore):
    """(records, warnings) for match report: the named jobs' records, or every saved one; None if one is missing."""
    if not args.ids:
        records, warnings = matches.all()
        kept = [r for r in records if isinstance(r, dict) and isinstance(r.get("job_id"), str)]
        warnings += ["a match record without a job_id, skipped"] * (len(records) - len(kept))
        return kept, warnings
    records = []
    for job_id in dict.fromkeys(args.ids):
        try:
            record = matches.get(job_id)
        except store.StoreError as exc:
            raise InputError(str(exc)) from None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InputError(f"the match record for {job_id} is unreadable: {exc}") from None
        if record is None:
            _emit({"error": f"no match record for {job_id}; run match score {job_id} --save"}, sys.stderr)
            return None, None
        records.append(record)
    return records, []


def _report_dir(root: Path, now) -> Path:
    """<data dir>/reports/<date-time>/, a fresh directory even when two reports land in the same second.
    reports/ must be a real folder inside the data directory (store.safe_dir)."""
    base = store.safe_dir(root, "reports") / now.strftime("%Y%m%d-%H%M%S")
    path, suffix = base, 1
    while path.exists() or path.is_symlink():
        suffix += 1
        path = base.with_name(f"{base.name}-{suffix}")
    path.mkdir()
    return path


def cmd_match_report(args) -> int:
    data = _match_profile(args)
    if data is None:
        return 1
    matches, job_store = _matches(args), _store(args)
    records, warnings = _report_records(args, matches)
    if records is None:
        return 1
    if not records:
        _emit({"error": "no saved match records; run match score <id> --save first"}, sys.stderr)
        return 1
    digest, weights, entries = score.profile_hash(data), score.weights_of(data), []
    for record in records:
        try:
            job = job_store.get(record["job_id"])
        except store.StoreError:
            job = None
        reasons = score.stale_reasons(record, job, digest, weights)
        entries.append(report.entry(record, job, bool(reasons), reasons))
    entries, vocabulary = report.order(entries), _vocabulary(args)
    now = datetime.now().astimezone()
    try:
        directory = _report_dir(store.data_dir(args.data_dir), now)
    except store.StoreError as exc:
        raise InputError(str(exc)) from None
    page, form = directory / "report.html", directory / "feedback.csv"
    page.write_text(report.build(entries, data, now.isoformat(timespec="seconds"), vocabulary),
                    encoding="utf-8", newline="\n")
    # newline="": the form already ends its rows in CRLF, as Excel expects.
    with open(form, "w", encoding="utf-8", newline="") as handle:
        handle.write(report.feedback_csv(entries))
    _emit({"report": str(page), "feedback": str(form), "jobs": len(entries),
           "stale": [item["record"]["job_id"] for item in entries if item["stale"]], "warnings": warnings})
    return 0


def cmd_resume_sample(args) -> int:
    try:
        directory = store.safe_dir(store.data_dir(args.data_dir), "resumes")
    except store.StoreError as exc:
        raise InputError(str(exc)) from None
    output, content = directory / "sample.pdf", resume_pdf.sample()
    if output.is_symlink():
        raise InputError(f"{output} is a link; nothing is written through it")
    try:
        result = resume_pdf.render(content, output, args.typst)
    except resume_pdf.ResumeError as exc:
        _emit({"error": str(exc)}, sys.stderr)
        return 1
    problems = resume_pdf.check(output, resume_pdf.fields_of(content))
    _emit({**result, "problems": problems})
    return 1 if problems else 0


# resume-<n>.json (docs/cn/material.md §1); the PDF and the Word version take its name.
_MATERIAL_NAME = re.compile(r"(resume-[1-9][0-9]{0,5})\.json")
# greeting-<n>.json, email-<n>.json, referral-<n>.json: material render --output names the text after it.
_MESSAGE_NAME = re.compile(r"((?:greeting|email|referral)-[1-9][0-9]{0,5})\.json")


def _write_build_note(directory, stem: str, record: dict, data: dict, outputs, kind="resume-build"):
    """<stem>.build.json beside the outputs: which material and files this build made (applications.md §12).
    resume build writes kind resume-build, material render --output kind message-build.
    With no file written it writes nothing and returns None, so an earlier note still matches its files."""
    outputs = [output for output in outputs if output.is_file()]
    if not outputs:
        return None
    import hashlib
    from datetime import datetime
    note = {"schema_version": 1, "kind": kind, "material": f"{stem}.json",
            "material_hash": review.material_hash(record), "profile_hash": score.profile_hash(data),
            "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "files": [{"name": output.name, "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
                      for output in outputs]}
    path = directory / f"{stem}.build.json"
    if path.is_symlink():
        raise InputError(f"{path} is a link; nothing is written through it")
    path.write_text(json.dumps(note, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def cmd_resume_build(args) -> int:
    named = _MATERIAL_NAME.fullmatch(Path(args.file).name)
    if not named:
        raise InputError(f"{args.file}: resume build takes a material file named resume-<n>.json "
                         "(docs/cn/material.md), and names the PDF and Word files after it")
    record = _read_material(args.file)
    data = _match_profile(args)
    if data is None:
        return 1
    if _is_message(record):
        raise InputError("resume build builds a CV; a greeting, email or referral is rendered with material render")
    vocabulary = _vocabulary(args)
    errors, warnings = _check_material(args, record, data, _material_job(args, record), vocabulary)
    if errors:
        _emit({"error": "the material is invalid; run material validate", "errors": errors}, sys.stderr)
        return 1
    if not schema.is_job_id(record["job_id"]):
        raise InputError(f"job_id: {record['job_id']!r} is not a job id like job_000000000001; "
                         "the resume goes in a folder named after it")
    try:
        directory = store.safe_dir(store.data_dir(args.data_dir), "resumes", record["job_id"])
    except store.StoreError as exc:
        raise InputError(str(exc)) from None
    except OSError as exc:
        _emit({"error": f"cannot make the folder resumes/{record['job_id']} in the data directory: "
                        f"{resume_pdf.os_reason(exc)}"}, sys.stderr)
        return 1
    pdf, docx = directory / f"{named.group(1)}.pdf", directory / f"{named.group(1)}.docx"
    for output in (pdf, docx):
        if output.is_symlink():
            raise InputError(f"{output} is a link; nothing is written through it")
    content = material.render(record, data, vocabulary)
    try:
        result = resume_pdf.render(content, pdf, args.typst)
    except resume_pdf.ResumeError as exc:
        _emit({"error": str(exc)}, sys.stderr)
        return 1
    try:
        result.update(resume_docx.write(content, docx))
    except OSError as exc:  # V24 P3-1: JSON, not a traceback, and the reason without the path
        _emit({"error": f"cannot write {docx.name}: {resume_pdf.os_reason(exc)}"}, sys.stderr)
        return 1
    fields = resume_pdf.fields_of(content)
    problems = resume_pdf.check(pdf, fields) + resume_docx.check(docx, fields)
    problems += resume_docx.same_text(pdf, docx, content)
    if not content["name"]:
        warnings.append("contact.name: the profile has no name, so the resume has none")
    try:
        note = _write_build_note(directory, named.group(1), record, data, (pdf, docx))
    except OSError as exc:
        _emit({"error": f"cannot write {named.group(1)}.build.json: {resume_pdf.os_reason(exc)}"}, sys.stderr)
        return 1
    result["build_note"] = None if note is None else str(note)
    _emit({**result, "problems": problems, "warnings": warnings})
    return 1 if problems else 0


# ---------------------------------------------------------------- application (M4-1a, docs/cn/applications.md)

def _application_run(function, *args, **kwargs) -> int:
    """Run one applications call: its result on stdout (0), a refusal on stderr (1), unreadable input as exit 2."""
    try:
        result = function(*args, **kwargs)
    except applications_mod.ApplicationError as exc:
        _emit(exc.payload(), sys.stderr)
        return 1
    except applications_mod.StorageError as exc:
        raise InputError(str(exc)) from None
    _emit(result)
    return 0


def _application_material_check(args):
    """(check, ok): material validate against the profile, needed only when --material is given."""
    if not getattr(args, "material", None):
        return None, True
    data = _match_profile(args)  # reports an invalid profile itself
    if data is None:
        return None, False
    vocabulary = _vocabulary(args)

    def check(record):
        # The one check material validate runs, so a greeting, email or referral is checked as one (M3-6).
        return _check_material(args, record, data, _material_job(args, record), vocabulary)
    return check, True


def cmd_application_record(args) -> int:
    check, ok = _application_material_check(args)
    if not ok:
        return 1
    return _application_run(
        applications_mod.record, store.data_dir(args.data_dir), args.job_id, channel=args.channel,
        platform=args.platform, submitted=args.submitted, on=args.on, at=args.at, historical=args.historical,
        material=args.material, sent=args.sent or (), actor=args.actor, preview=args.preview,
        request_id=args.request_id, check_material=check)


def cmd_application_submit(args) -> int:
    check, ok = _application_material_check(args)
    if not ok:
        return 1
    return _application_run(
        applications_mod.submit, store.data_dir(args.data_dir), args.application_id,
        expected_revision=args.expected_revision, on=args.on, at=args.at, channel=args.channel,
        platform=args.platform, material=args.material, sent=args.sent or (), actor=args.actor,
        preview=args.preview, request_id=args.request_id, check_material=check)


def cmd_application_status(args) -> int:
    return _application_run(
        applications_mod.change_status, store.data_dir(args.data_dir), args.application_id, args.status,
        expected_revision=args.expected_revision, reason=args.reason, on=args.on, at=args.at, actor=args.actor,
        preview=args.preview, request_id=args.request_id)


def cmd_application_show(args) -> int:
    return _application_run(applications_mod.show, store.data_dir(args.data_dir), args.application_id)


def cmd_application_list(args) -> int:
    if args.as_of is not None and not args.due:
        _emit({"error": "invalid", "message": "--as-of goes with --due"}, sys.stderr)
        return 1
    if args.due:
        return _application_run(applications_mod.due, store.data_dir(args.data_dir), as_of=args.as_of,
                                statuses=args.status, job_id=args.job)
    return _application_run(applications_mod.list_applications, store.data_dir(args.data_dir),
                            statuses=args.status, job_id=args.job)


def _application_write(function, args, **kwargs) -> int:
    """reply, note, followup and void: the arguments every write on an existing application shares."""
    return _application_run(function, store.data_dir(args.data_dir), args.application_id,
                            expected_revision=args.expected_revision, actor=args.actor, preview=args.preview,
                            request_id=args.request_id, **kwargs)


def cmd_application_reply(args) -> int:
    return _application_write(applications_mod.reply, args, summary=args.summary, on=args.on, at=args.at)


def cmd_application_note(args) -> int:
    return _application_write(applications_mod.note, args, text=args.text)


def cmd_application_followup(args) -> int:
    return _application_write(applications_mod.followup, args, due=args.due, cancel=args.cancel)


def cmd_application_void(args) -> int:
    return _application_write(applications_mod.void, args, reason=args.reason)


def cmd_application_backup(args) -> int:
    return _application_run(applications_mod.backup, store.data_dir(args.data_dir))


def cmd_application_validate(args) -> int:
    try:
        result = applications_mod.validate(store.data_dir(args.data_dir), backup=args.backup)
    except applications_mod.ApplicationError as exc:
        _emit(exc.payload(), sys.stderr)
        return 1
    except applications_mod.StorageError as exc:
        raise InputError(str(exc)) from None
    _emit(result)
    return 0 if result["valid"] else 1


def cmd_application_export(args) -> int:
    root = store.data_dir(args.data_dir)
    if not args.out:
        return _application_run(applications_mod.export, root, args.application_ids)

    def write():
        document = applications_mod.export(root, args.application_ids)
        path = applications_mod.write_export(root, args.out, document)
        return {"out": str(path), "applications": len(document["applications"])}
    return _application_run(write)


def _add_application_parser(commands, stored) -> None:
    group = commands.add_parser("application", help="投递记录：记投递、投出、改状态、回复、备注、跟进、作废、查看、导出和备份",
                                description="投递记录（docs/cn/applications.md）。写操作先 --preview 看要写什么，"
                                            "用户确认后带预览给的 --request-id 再运行一次才写入。")
    group.set_defaults(help_parser=group)
    sub = group.add_subparsers(dest="application_command", metavar="<application-command>")

    def writer(name, summary, description):
        parser = sub.add_parser(name, parents=[stored], help=summary, description=description)
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--preview", action="store_true", help="只输出要写的事件和一个 request_id，不写任何东西")
        mode.add_argument("--request-id", help="预览给的 request_id：写入；同一个 id 重试不会重复写")
        parser.add_argument("--actor", default="user", choices=applications_mod.ACTORS,
                            help="谁在记录（默认 user；Agent 写自己的名字）")
        return parser

    def when(parser):
        moment = parser.add_mutually_exclusive_group()
        moment.add_argument("--on", help="只知道日期：YYYY-MM-DD")
        moment.add_argument("--at", help="知道时刻：必须带时区，如 2026-11-02T14:30+08:00")

    def materials(parser):
        parser.add_argument("--material", help="投出的材料文件：简历 data/materials/<岗位id>/resume-<n>.json，"
                                               "或沟通草稿 greeting-<n>.json、email-<n>.json、referral-<n>.json")
        parser.add_argument("--sent", nargs="+", action="extend", metavar="FILE",
                            help="实际发出的文件（PDF、Word，或沟通草稿的 .txt），会复制归档")
        parser.add_argument("--profile", help="检查材料用的档案；默认为 <数据目录>/profile/profile.json")

    record_parser = writer("record", "新建一次投递（只起草，或带 --submitted 记为已投出）",
                           "新建一次投递。不带 --submitted 是 drafted；带了是 applied。")
    record_parser.add_argument("job_id", help="岗位 id（岗位库里的）")
    record_parser.add_argument("--channel", required=True, choices=applications_mod.CHANNELS, help="投递渠道")
    record_parser.add_argument("--platform", help=f"平台名，如 BOSS直聘（≤{applications_mod.MAX_PLATFORM} 字）")
    record_parser.add_argument("--submitted", action="store_true", help="已经投出")
    record_parser.add_argument("--historical", action="store_true",
                               help="补录以前的投递（要带 --submitted；可以没有材料、日期未知）")
    when(record_parser)
    materials(record_parser)
    record_parser.set_defaults(handler=cmd_application_record)

    submit_parser = writer("submit", "把一条 drafted 的投递记为已投出", "把一条 drafted 的投递记为已投出（applied）。")
    submit_parser.add_argument("application_id", help="投递 id")
    submit_parser.add_argument("--expected-revision", type=int, required=True, help="show 或 list 给的 revision")
    submit_parser.add_argument("--channel", choices=applications_mod.CHANNELS, help="实际渠道和起草时不同时写")
    submit_parser.add_argument("--platform", help="实际平台名")
    when(submit_parser)
    materials(submit_parser)
    submit_parser.set_defaults(handler=cmd_application_submit)

    status_parser = writer("status", "改一条投递的状态", "按 docs/cn/applications.md §4 的状态表改状态。")
    status_parser.add_argument("application_id", help="投递 id")
    status_parser.add_argument("status", choices=[item for item in applications_mod.STATUSES if item != "drafted"],
                               help="新状态")
    status_parser.add_argument("--expected-revision", type=int, required=True, help="show 或 list 给的 revision")
    status_parser.add_argument("--reason", help=f"原因或对方说了什么（≤{applications_mod.MAX_TEXT} 字）")
    when(status_parser)
    status_parser.set_defaults(handler=cmd_application_status)

    def existing(name, summary, description, handler):
        parser = writer(name, summary, description)
        parser.add_argument("application_id", help="投递 id")
        parser.add_argument("--expected-revision", type=int, required=True, help="show 或 list 给的 revision")
        parser.set_defaults(handler=handler)
        return parser

    reply_parser = existing("reply", "记一次不改状态的回复", "记收到的回复（不改状态）。改了状态的回复用 status --reason 记。",
                            cmd_application_reply)
    reply_parser.add_argument("--summary", required=True, help=f"回复说了什么（≤{applications_mod.MAX_TEXT} 字）")
    when(reply_parser)
    note_parser = existing("note", "给一条投递加备注", "加一条备注，任何状态都可以。", cmd_application_note)
    note_parser.add_argument("--text", required=True, help=f"备注（≤{applications_mod.MAX_TEXT} 字）")
    followup_parser = existing("followup", "设置或取消跟进日期",
                               "设置跟进日期（今天或以后，Asia/Shanghai），或取消。只用于已投出、没结束的投递。",
                               cmd_application_followup)
    due_or_cancel = followup_parser.add_mutually_exclusive_group(required=True)
    due_or_cancel.add_argument("--due", help="跟进日期：YYYY-MM-DD")
    due_or_cancel.add_argument("--cancel", action="store_true", help="取消跟进日期")
    void_parser = existing("void", "作废最近一条事件（输错时用）",
                           "作废最近一条还能作废的事件：不删除，只标记；created 和作废事件本身不能作废。",
                           cmd_application_void)
    void_parser.add_argument("--reason", required=True, help=f"为什么作废（≤{applications_mod.MAX_TEXT} 字）")

    backup_parser = sub.add_parser(
        "backup", parents=[stored], help="备份投递记录库和归档文件",
        description="把数据库的一致快照和它登记的归档文件复制到 <数据目录>/applications/backups/<UTC 时间>/，"
                    "旁边写 manifest.json。不改任何记录。")
    backup_parser.set_defaults(handler=cmd_application_backup)

    show_parser = sub.add_parser("show", parents=[stored], help="一条投递的完整内容（格式同导出）",
                                 description="一条投递的完整内容，格式同导出。只读。")
    show_parser.add_argument("application_id", help="投递 id")
    show_parser.set_defaults(handler=cmd_application_show)

    list_parser = sub.add_parser("list", parents=[stored], help="投递列表，最近投出的在前",
                                 description="投递列表，最近投出的在前。只读。")
    list_parser.add_argument("--status", nargs="+", action="extend", choices=applications_mod.STATUSES,
                             help="只列这些状态")
    list_parser.add_argument("--job", help="只列这个岗位的投递")
    list_parser.add_argument("--due", action="store_true",
                             help="待跟进：已投出、没结束、跟进日期已到的（due）和没设跟进日期的（unset）")
    list_parser.add_argument("--as-of", help="和 --due 一起用：按这一天算（YYYY-MM-DD；默认 Asia/Shanghai 的今天）")
    list_parser.set_defaults(handler=cmd_application_list)

    validate_parser = sub.add_parser(
        "validate", parents=[stored], help="检查整个投递记录库和归档文件",
        description="检查整库：事件连续、状态重放一致、归档文件在且摘要对、有没有没登记的孤立文件。"
                    "通过时退出码 0，不通过时退出码 1。只读。")
    validate_parser.add_argument("--backup", metavar="NAME", help="改为检查 applications/backups/ 下的这份备份")
    validate_parser.set_defaults(handler=cmd_application_validate)

    export_parser = sub.add_parser(
        "export", parents=[stored], help="导出投递记录 JSON",
        description="导出投递记录 JSON；不写 --out 时打印。--out 只收文件名，写到 <数据目录>/applications/exports/。")
    export_parser.add_argument("application_ids", nargs="*", help="只导出这些投递；省略时导出全部")
    export_parser.add_argument("--out", help="文件名（不是路径），以 .json 结尾")
    export_parser.set_defaults(handler=cmd_application_export)


def cmd_collect_boss(args) -> int:
    try:
        options = collect.make_options(args.query, city=args.city, city_code=args.city_code, max_jobs=args.max,
                                       max_pages=args.max_pages, batch=args.batch)
        browser.check_cdp_url(args.cdp)
    except (collect.CollectError, browser.BrowserUnavailable) as exc:
        raise InputError(str(exc)) from None
    root = store.data_dir(args.data_dir)
    try:
        tab = browser.open_tab(args.cdp)
    except browser.BrowserUnavailable as exc:
        raise InputError(str(exc)) from None
    try:
        summary = collect.run(tab, options, root)
    except store.StoreError as exc:
        raise InputError(f"收件夹写不进去：{exc}") from None
    finally:
        tab.close()
    _emit(summary)
    return collect.exit_code(summary)


def _add_collect_parser(commands, stored) -> None:
    group = commands.add_parser(
        "collect", help="从你自己已登录的浏览器读取招聘网站上的岗位，存进收件夹（要装 Playwright）",
        description="接管你用调试端口启动的 Chrome，在一个新标签里按搜索词和城市慢速读列表和详情页，"
                    "每个岗位存一个文件到 <数据目录>/inbox/<网站>/<批次>/。只读、不点任何按钮；"
                    "遇到安全检查或登录页就停下。说明见 docs/cn/collect.md。",
    )
    group.set_defaults(help_parser=group)
    sites = group.add_subparsers(dest="collect_site", metavar="<site>")
    parser = sites.add_parser(
        "boss", parents=[stored], help="BOSS 直聘：按搜索词和城市读取岗位",
        description="退出码：0 读完（到了上限或没有更多结果）；2 没能开始（参数不对、没装 Playwright、连不上浏览器）；"
                    "3 遇到安全检查、验证码或没登录，已抓的已保存，请在浏览器里处理后重跑；"
                    "4 页面结构认不出，已抓的已保存。",
    )
    parser.add_argument("--query", required=True, help="搜索词，例如 \"Java 实习\"")
    parser.add_argument("--city", help=f"城市，认得的有：{'、'.join(boss.CITY_CODES)}")
    parser.add_argument("--city-code", help="别的城市：网站的 9 位城市代码（在网站上选好城市后，地址栏里 city= 后面那一串）")
    parser.add_argument("--max", type=int, default=collect.DEFAULT_MAX_JOBS,
                        help=f"这次最多打开几个新岗位的详情页（默认 {collect.DEFAULT_MAX_JOBS}，最多 {collect.MAX_JOBS_CAP}）")
    parser.add_argument("--max-pages", type=int, default=collect.DEFAULT_MAX_PAGES,
                        help=f"搜索结果最多加载几屏（默认 {collect.DEFAULT_MAX_PAGES}，最多 {collect.MAX_PAGES_CAP}）")
    parser.add_argument("--batch", help="批次名，默认用开始的时间 YYYYMMDD-HHMMSS；写已有的批次名就接着往里存")
    parser.add_argument("--cdp", default=browser.DEFAULT_CDP, help=f"浏览器的调试地址，只能是本机（默认 {browser.DEFAULT_CDP}）")
    parser.set_defaults(handler=cmd_collect_boss)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m jobsearch_cn",
        description="AI Job Search CN 本地工具（离线处理用户提供的岗位数据；只有 collect 会读取你自己已登录的浏览器）",
    )
    parser.add_argument("--version", action="version", version=f"jobsearch_cn {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="<command>")

    stored = argparse.ArgumentParser(add_help=False)
    stored.add_argument("--data-dir", help=f"数据目录（默认为仓库下的 data/，或环境变量 {store.DATA_DIR_ENV}）")

    jd = commands.add_parser("jd", help="岗位 JD 相关命令", description="岗位 JD 相关命令")
    jd.set_defaults(help_parser=jd)
    jd_commands = jd.add_subparsers(dest="jd_command", metavar="<jd-command>")

    parse = jd_commands.add_parser(
        "parse", parents=[stored],
        help="按规则从 JD 文本抽取岗位记录（多份 JD 用一行 === 分隔）",
        description="按规则从 JD 文本抽取岗位记录，输出 {\"jobs\": [...], \"warnings\": [...]}。"
                    "规则读不准的字段留空，由 Agent 或用户补全后再用 jd validate 校验。",
    )
    parse.add_argument("file", nargs="?", default="-", help="JD 文本文件；省略或为 - 时读取标准输入")
    parse.add_argument("--site", choices=schema.SITES, help="JD 的原发布平台")
    parse.add_argument("--url", help="JD 的原链接（只能用于单份 JD）")
    parse.add_argument("--save", action="store_true", help="解析后直接保存到本地岗位库（重复的 JD 会合并）")
    parse.set_defaults(handler=cmd_jd_parse)

    save = jd_commands.add_parser(
        "save", parents=[stored],
        help="校验并保存岗位记录到本地岗位库（重复的 JD 会合并）",
        description="保存一条岗位记录，或 jd parse 输出的 {\"jobs\": [...]}。任何一条无效则一条都不保存。",
    )
    save.add_argument("file", nargs="?", default="-", help="JSON 文件路径；省略或为 - 时读取标准输入")
    save.set_defaults(handler=cmd_jd_save)

    listing = jd_commands.add_parser("list", parents=[stored], help="列出本地岗位库中的岗位",
                                     description="列出本地岗位库中的岗位（按导入时间排序）。")
    listing.add_argument("--status", choices=schema.STATUSES, help="只列出该状态的岗位")
    listing.set_defaults(handler=cmd_jd_list)

    show = jd_commands.add_parser("show", parents=[stored], help="输出一条岗位记录的全部内容",
                                  description="输出一条岗位记录的全部内容。")
    show.add_argument("id", help="岗位 id，例如 job_9f4694691d57")
    show.set_defaults(handler=cmd_jd_show)

    status = jd_commands.add_parser("status", parents=[stored], help="修改岗位状态",
                                    description="修改岗位状态。")
    status.add_argument("id", help="岗位 id")
    status.add_argument("status", choices=schema.STATUSES, help="新状态")
    status.set_defaults(handler=cmd_jd_status)

    validate = jd_commands.add_parser(
        "validate",
        help="按 docs/cn/job-schema.md 校验一条岗位记录（JSON）",
        description="按 docs/cn/job-schema.md 校验一条岗位记录，输出 {\"valid\": ..., \"errors\": [...]}。",
    )
    validate.add_argument("file", nargs="?", default="-", help="JSON 文件路径；省略或为 - 时读取标准输入")
    validate.set_defaults(handler=cmd_jd_validate)

    prof = commands.add_parser("profile", help="个人档案相关命令", description="个人档案相关命令（data/profile/）")
    prof.set_defaults(help_parser=prof)
    prof_commands = prof.add_subparsers(dest="profile_command", metavar="<profile-command>")

    prof_extract = prof_commands.add_parser(
        "extract", help="只读提取 DOCX/PDF 简历的纯文本，不保存文件",
        description='读取简历，输出 UTF-8 JSON {"source": 文件名, "text": 纯文本}；不写文件或日志。',
    )
    prof_extract.add_argument("file", help="简历路径，通常在 data/profile/sources/ 下；支持 .docx、.pdf")
    prof_extract.set_defaults(handler=cmd_profile_extract)

    prof_validate = prof_commands.add_parser(
        "validate", parents=[stored], help="按 docs/cn/profile.md 校验个人档案",
        description="校验 data/profile/profile.json，并检查来源文件和 notes.md，"
                    "输出 {\"valid\": ..., \"errors\": [...], \"warnings\": [...]}。",
    )
    prof_validate.add_argument("file", nargs="?", help="档案文件；默认为 <数据目录>/profile/profile.json")
    prof_validate.set_defaults(handler=cmd_profile_validate)

    prof_show = prof_commands.add_parser("show", parents=[stored], help="输出个人档案（默认隐去联系方式）",
                                         description="输出个人档案。联系方式默认隐去，加 --contact 才显示。")
    prof_show.add_argument("file", nargs="?", help="档案文件；默认为 <数据目录>/profile/profile.json")
    prof_show.add_argument("--contact", action="store_true", help="显示联系方式（只在写简历时需要）")
    prof_show.set_defaults(handler=cmd_profile_show)

    match_parser = commands.add_parser("match", help="岗位与个人档案的匹配", description="岗位与个人档案的匹配")
    match_parser.set_defaults(help_parser=match_parser)
    match_commands = match_parser.add_subparsers(dest="match_command", metavar="<match-command>")
    match_filter = match_commands.add_parser(
        "filter", parents=[stored], help="硬性条件过滤：逐项给出符合 / 冲突 / 未知",
        description="按 docs/cn/match.md 用个人档案过滤一个已保存的岗位，输出每项条件的结论和依据。结果不保存。",
    )
    match_filter.add_argument("id", help="岗位 id，例如 job_9f4694691d57")
    match_filter.add_argument("--profile", help="档案文件；默认为 <数据目录>/profile/profile.json")
    match_filter.set_defaults(handler=cmd_match_filter)

    match_score = match_commands.add_parser(
        "score", parents=[stored], help="可解释评分：计算规则部分，输出匹配记录",
        description="按 docs/cn/match.md 给一个已保存的岗位评分：技能、方向、薪资、地点由规则计算，带上硬性过滤的结论，"
                    "给出加权总分、等级和缺口；经历由 Agent 补充。输出匹配记录，加 --save 同时保存。",
    )
    match_score.add_argument("id", help="岗位 id，例如 job_9f4694691d57")
    match_score.add_argument("--profile", help="档案文件；默认为 <数据目录>/profile/profile.json")
    match_score.add_argument("--save", action="store_true", help="同时保存到 <数据目录>/matches/<岗位id>.json")
    match_score.add_argument("--draft", action="store_true",
                             help="同时写出草稿 <数据目录>/matches/drafts/<岗位id>.json，供 Agent 补充经历后校验、保存")
    match_score.set_defaults(handler=cmd_match_score)

    match_validate = match_commands.add_parser(
        "validate", parents=[stored], help="校验 Agent 补充后的匹配记录",
        description="对照岗位库里的岗位和个人档案校验匹配记录：规则部分不能改，Agent 的依据要引用 JD 原文和档案里的经历，"
                    "总分要由各维度算得出。输出 {\"valid\": ..., \"errors\": [...]}。",
    )
    match_validate.add_argument("file", help="匹配记录文件；- 表示标准输入")
    match_validate.add_argument("--profile", help="档案文件；默认为 <数据目录>/profile/profile.json")
    match_validate.set_defaults(handler=cmd_match_validate)

    match_save = match_commands.add_parser(
        "save", parents=[stored], help="校验通过后保存匹配记录",
        description="同 match validate，通过后保存到 <数据目录>/matches/<岗位id>.json。",
    )
    match_save.add_argument("file", help="匹配记录文件；- 表示标准输入")
    match_save.add_argument("--profile", help="档案文件；默认为 <数据目录>/profile/profile.json")
    match_save.set_defaults(handler=cmd_match_save)

    match_show = match_commands.add_parser("show", parents=[stored], help="显示已保存的匹配记录",
                                           description="输出 <数据目录>/matches/<岗位id>.json。")
    match_show.add_argument("id", help="岗位 id，例如 job_9f4694691d57")
    match_show.set_defaults(handler=cmd_match_show)

    match_list = match_commands.add_parser(
        "list", parents=[stored], help="按等级、总分列出已评分的岗位，标出过期的记录；--weights 换一组权重试算",
        description="列出已保存的匹配记录，按等级、总分排序。岗位、档案或权重在评分后改过的记录标为 stale，"
                    "stale_reasons 写明原因，需要重新评分。加 --weights 时用这组权重和已保存的各维度分数试算，"
                    "只输出，不改档案和记录。",
    )
    match_list.add_argument("--profile", help="档案文件；默认为 <数据目录>/profile/profile.json")
    match_list.add_argument("--weights", metavar="WEIGHTS",
                            help=f"试算用的权重，五项都写，例如 {_TRIAL_EXAMPLE}")
    match_list.set_defaults(handler=cmd_match_list)

    match_report = match_commands.add_parser(
        "report", parents=[stored], help="把已保存的匹配记录生成可读的报告（HTML）和反馈表（CSV）",
        description="读取已保存的匹配记录，写出 <数据目录>/reports/<日期时间>/report.html 和 feedback.csv，"
                    "输出两个文件的路径。过期的记录会标出来。报告和反馈表都不含联系方式。",
    )
    match_report.add_argument("ids", nargs="*", metavar="id", help="岗位 id；省略时包括所有已保存的记录")
    match_report.add_argument("--profile", help="档案文件；默认为 <数据目录>/profile/profile.json")
    match_report.set_defaults(handler=cmd_match_report)

    resume = commands.add_parser("resume", help="简历生成相关命令", description="简历生成相关命令")
    resume.set_defaults(help_parser=resume)
    resume_commands = resume.add_subparsers(dest="resume_command", metavar="<resume-command>")
    resume_sample = resume_commands.add_parser(
        "sample", parents=[stored], help="用固定的虚构内容生成一页 PDF，验证 Typst 和字体装好了",
        description="用固定的虚构内容生成 <数据目录>/resumes/sample.pdf 并检查，输出间距、字体和发现的问题。"
                    "Typst 的安装方法见 docs/cn/resume-pdf.md。",
    )
    resume_sample.add_argument("--typst", help=f"Typst 程序的路径；默认为环境变量 {resume_pdf.TYPST_ENV}，再找 PATH 里的 typst")
    resume_sample.set_defaults(handler=cmd_resume_sample)
    resume_build = resume_commands.add_parser(
        "build", parents=[stored], help="把一份材料生成一页 PDF 和 Word 版简历，并检查两份的文字",
        description="先像 material validate 一样检查材料，再从档案取出姓名、学校、日期等，生成 "
                    "<数据目录>/resumes/<岗位id>/resume-<n>.pdf 和 .docx（n 同材料文件名），检查两份的文字都和内容一致。"
                    "材料不通过时退出码 1，什么也不写；检查发现问题时退出码 1。"
                    "材料格式见 docs/cn/material.md，PDF 和 Word 版见 docs/cn/resume-pdf.md。",
    )
    resume_build.add_argument("file", help="材料文件，名为 resume-<n>.json")
    resume_build.add_argument("--profile", help="档案文件；默认为 <数据目录>/profile/profile.json")
    resume_build.add_argument("--typst", help=f"Typst 程序的路径；默认为环境变量 {resume_pdf.TYPST_ENV}，再找 PATH 里的 typst")
    resume_build.set_defaults(handler=cmd_resume_build)

    material_parser = commands.add_parser("material", help="求职材料（简历等）相关命令",
                                          description="求职材料（简历等）相关命令，格式见 docs/cn/material.md")
    material_parser.set_defaults(help_parser=material_parser)
    material_commands = material_parser.add_subparsers(dest="material_command", metavar="<material-command>")
    material_validate = material_commands.add_parser(
        "validate", parents=[stored], help="检查一份材料：引用的档案条目都在，改写没有编出数字和技能",
        description="对照个人档案检查一份材料（data/materials/<岗位id>/resume-<n>.json）。通过时退出码 0，"
                    "不通过时退出码 1 并列出哪一条、为什么；警告不影响退出码。",
    )
    material_validate.add_argument("file", help="材料文件；- 表示标准输入")
    material_validate.add_argument("--profile", help="档案文件；默认为 <数据目录>/profile/profile.json")
    material_validate.set_defaults(handler=cmd_material_validate)
    material_template = material_commands.add_parser(
        "template", parents=[stored], help="打招呼语、投递邮件、内推请求：按方向选模板",
        description="按岗位的技能和档案的求职方向选模板（见 docs/cn/material.md），"
                    "输出槽位、字数限制、写法提示和选它的理由。",
    )
    material_template.add_argument("job_id", help="岗位 id（本地岗位库里要有）")
    material_template.add_argument("--kind", required=True, choices=messages.KINDS, help="材料种类")
    material_template.add_argument("--direction", help="指定方向：模板名（例如 tech、ops、default），或者技能词表里"
                                                       "还没有模板的方向（例如 design、hr），这时用 default 模板")
    material_template.add_argument("--profile", help="档案文件；默认为 <数据目录>/profile/profile.json")
    material_template.set_defaults(handler=cmd_material_template)
    material_render = material_commands.add_parser(
        "render", parents=[stored], help="检查打招呼语、邮件或内推请求，通过后输出可以直接复制的文字",
        description="先做和 material validate 相同的检查，有错误时输出错误，退出码 1；"
                    "通过时把占位符换成档案和岗位里的值，输出纯文本，警告写到 stderr。",
    )
    material_render.add_argument("file", help="材料文件；- 表示标准输入")
    material_render.add_argument("--profile", help="档案文件；默认为 <数据目录>/profile/profile.json")
    material_render.add_argument("--output", action="store_true",
                                 help="写到 <数据目录>/messages/<岗位id>/<kind>-<n>.txt，旁边写说明文件 "
                                      "<kind>-<n>.build.json；标准输出只给路径、字数和警告，不含正文")
    material_render.set_defaults(handler=cmd_material_render)

    review_parser = commands.add_parser("review", help="材料审核相关命令（起草 + 审核工作流）",
                                        description="材料审核相关命令，格式见 docs/cn/review-format.md，"
                                                    "清单见 docs/cn/review-checklist.md")
    review_parser.set_defaults(help_parser=review_parser)
    review_commands = review_parser.add_subparsers(dest="review_command", metavar="<review-command>")
    review_draft = review_commands.add_parser(
        "draft", parents=[stored], help="给审核者的机器初稿：岗位技能的覆盖情况和标点、空格的警告",
        description="对一份通过检查的材料，列出 JD 要求的每项技能是用 JD 的写法覆盖了、用别的写法覆盖了，"
                    "还是缺口，以及清单 E1、E3 的警告。只输出，不写文件。",
    )
    review_draft.add_argument("file", help="材料文件；- 表示标准输入")
    review_draft.add_argument("--profile", help="档案文件；默认为 <数据目录>/profile/profile.json")
    review_draft.set_defaults(handler=cmd_review_draft)
    for name, handler, summary in (
            ("validate", cmd_review_validate, "检查一份审核结果的格式，以及它审的是不是材料的当前版本"),
            ("show", cmd_review_show, "把一份审核结果显示成 Markdown（先检查，不通过就列出错误）")):
        sub = review_commands.add_parser(name, help=summary, description=summary + "。通过时退出码 0，不通过时退出码 1。")
        sub.add_argument("file", help="审核结果文件（data/materials/<岗位id>/review-<n>-r<轮次>.json）")
        sub.add_argument("--material", help="审核的材料文件；默认为审核结果同目录下 material 字段写的文件")
        sub.set_defaults(handler=handler)
    _add_application_parser(commands, stored)
    _add_collect_parser(commands, stored)
    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        getattr(args, "help_parser", parser).print_help()
        return 0
    try:
        return handler(args)
    except InputError as exc:
        _emit({"error": str(exc)}, sys.stderr)
        return 2
