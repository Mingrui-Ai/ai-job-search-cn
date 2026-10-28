"""Command line interface: python -m jobsearch_cn <command> ...

Every command prints JSON on stdout, so Codex, Claude Code and scripts read the
same output. Exit codes: 0 success; 1 the input was read but is invalid, held
no JD, or names no stored job; 2 the input could not be read, reported as
{"error": ...} on stderr (argparse also exits 2 on a malformed command line).
"""

import argparse
import codecs
import json
import sys
from pathlib import Path

from jobsearch_cn import __version__, jd_parser, match, profile, resume_extract, schema, store, vocab

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
    sources_dir = root / "sources"
    sources = {p.name for p in sources_dir.iterdir() if p.is_file()} if sources_dir.is_dir() else set()
    errors = profile.validate(data, sources=sources)
    warnings = []
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
    _emit(data if args.contact else profile.redacted(data))
    return 0


def cmd_profile_extract(args) -> int:
    try:
        text = resume_extract.extract_text(args.file)
    except resume_extract.ExtractionError as exc:
        raise InputError(str(exc)) from None
    _emit({"source": Path(args.file).name, "text": text})
    return 0


def cmd_match_filter(args) -> int:
    job_store = _store(args)
    try:
        job = job_store.get(args.id)
    except store.StoreError as exc:
        raise InputError(str(exc)) from None
    if job is None:
        _emit({"error": f"no stored job {args.id}"}, sys.stderr)
        return 1
    path = Path(args.profile) if args.profile else store.data_dir(args.data_dir) / "profile" / "profile.json"
    data = _load_profile(path)
    # Structure only: whether the source files are still there does not change a filter result.
    errors = profile.validate(data)
    if errors:
        _emit({"error": "the profile is invalid; run profile validate", "errors": errors}, sys.stderr)
        return 1
    _emit(match.filter_job(job, data))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m jobsearch_cn",
        description="AI Job Search CN 本地工具（离线处理用户提供的岗位数据）",
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
