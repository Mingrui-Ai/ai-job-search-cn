"""Command line entry point: python -m jobsearch_cn <command> ...

Commands are registered here as the week-1 modules land (JD import, parse,
validate, store). Run from the repository root.
"""

import argparse
import sys

from jobsearch_cn import __version__


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m jobsearch_cn",
        description="AI Job Search CN 本地工具（离线处理用户提供的岗位数据）",
    )
    parser.add_argument("--version", action="version", version=f"jobsearch_cn {__version__}")
    parser.add_subparsers(dest="command", metavar="<command>")
    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
