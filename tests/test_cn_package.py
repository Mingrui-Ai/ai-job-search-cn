"""Boundary guards for the jobsearch_cn package (docs/cn/cn-migration-plan.md).

* Standard library only. The upstream tools/ scripts are stdlib-only so that
  installing the project runs no third-party code; the CN package keeps that.
* Offline. Parsing, validation and storage must be reproducible from local
  input alone. Network access belongs to portal adapters under .agents/skills/,
  which carry the /add-portal robots/ToS checks. Like the settings.json deny
  list, this is a tripwire rather than a wall: it makes adding a network path
  a visible, reviewed change instead of an incidental import.
* UTF-8 output whatever the console code page. A Chinese Windows console
  defaults to cp936 (GBK), a Western one to cp1252; the CLI must emit UTF-8
  under both, the same contract tests/test_tools_utf8_output.py pins for
  tools/.
"""
import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "jobsearch_cn"

sys.path.insert(0, str(REPO))
from jobsearch_cn import __version__  # noqa: E402

# Modules that open connections or hand a URL to something that will. Matched
# as a prefix, so `http.client` covers `http.client.HTTPSConnection`.
# `urllib.parse` and `http.HTTPStatus` stay usable: parsing a source URL to
# extract a job id is offline work.
NETWORK_MODULES = (
    "socket",
    "ssl",
    "http.client",
    "http.server",
    "urllib.request",
    "ftplib",
    "smtplib",
    "poplib",
    "imaplib",
    "xmlrpc",
    "webbrowser",
)

# Upstream tools/ scripts the package may import. They are stdlib-only by the
# upstream convention, so reusing one adds code, not a dependency. Name each
# one: a new entry is a reviewed decision, like everything else in this file.
UPSTREAM_TOOLS = {"posting_guard"}


def package_imports():
    """Yield (relative path, line, dotted module) for every import in the package."""
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield rel, node.lineno, alias.name
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                yield rel, node.lineno, node.module
                # `from urllib import request` names the submodule in the alias.
                for alias in node.names:
                    yield rel, node.lineno, f"{node.module}.{alias.name}"


def is_network_module(name: str) -> bool:
    return any(name == banned or name.startswith(banned + ".") for banned in NETWORK_MODULES)


class PackageImports(unittest.TestCase):
    def test_package_has_modules_to_check(self):
        self.assertTrue((PACKAGE / "__init__.py").is_file(), "sanity: the package moved")

    def test_standard_library_only(self):
        allowed = set(sys.stdlib_module_names) | {"jobsearch_cn"} | UPSTREAM_TOOLS
        offenders = [
            f"{rel}:{line} imports {name}"
            for rel, line, name in package_imports()
            if name.split(".")[0] not in allowed
        ]
        self.assertEqual(offenders, [], "jobsearch_cn must stay standard-library only")

    def test_allowed_upstream_tools_exist_and_stay_offline(self):
        # Follow imports between tools/ scripts (posting_guard imports page_decode),
        # so the whole chain the package pulls in is held to the same rule.
        pending, checked = sorted(UPSTREAM_TOOLS), set()
        while pending:
            name = pending.pop()
            if name in checked:
                continue
            checked.add(name)
            path = REPO / "tools" / f"{name}.py"
            self.assertTrue(path.is_file(), f"tools/{name}.py moved or was removed upstream")
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            imported += [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module]
            self.assertEqual([m for m in imported if is_network_module(m)], [], f"tools/{name}.py went online")
            pending += [m for m in imported if (REPO / "tools" / f"{m}.py").is_file()]
        self.assertIn("page_decode", checked, "sanity: the walk follows imports between tools/ scripts")

    def test_no_network_modules(self):
        offenders = [
            f"{rel}:{line} imports {name}"
            for rel, line, name in package_imports()
            if is_network_module(name)
        ]
        self.assertEqual(offenders, [], "jobsearch_cn must stay offline; network access belongs to portal adapters")

    def test_network_matcher_keeps_offline_url_parsing(self):
        self.assertTrue(is_network_module("urllib.request"))
        self.assertTrue(is_network_module("http.client"))
        self.assertFalse(is_network_module("urllib.parse"))
        self.assertFalse(is_network_module("http"))
        self.assertFalse(is_network_module("sslib"))


def run_cli(*args, encoding):
    """Run the CLI the way a legacy-code-page Windows console pipes it."""
    env = dict(os.environ, PYTHONIOENCODING=encoding, PYTHONUTF8="0")
    return subprocess.run(
        [sys.executable, "-m", "jobsearch_cn", *args], cwd=REPO, env=env, capture_output=True
    )


class CliEntryPoint(unittest.TestCase):
    def test_version(self):
        proc = run_cli("--version", encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        self.assertIn(__version__, proc.stdout.decode("utf-8"))

    def test_help_is_utf8_under_legacy_code_pages(self):
        for encoding in ("cp1252", "gbk"):
            with self.subTest(encoding=encoding):
                proc = run_cli("--help", encoding=encoding)
                err = proc.stderr.decode("utf-8", "replace")
                self.assertNotIn("UnicodeEncodeError", err)
                self.assertEqual(proc.returncode, 0, err)
                self.assertIn("离线", proc.stdout.decode("utf-8"))



class NoControlCharacters(unittest.TestCase):
    """No C0 control characters in CN text files.

    They are invisible in an editor and on GitHub, so they slip through
    review. The usual source is a backslash eaten by a string escape while a
    file is generated: "D:\06_Projects" written through a non-raw Python
    string becomes "D:" + chr(6) + "_Projects". Tab, newline and carriage
    return are fine.
    """

    ALLOWED = {chr(9), chr(10), chr(13)}  # tab, newline, carriage return

    def files(self):
        yield REPO / "AGENTS.md"
        yield from sorted((REPO / "docs" / "cn").rglob("*.md"))
        yield from sorted(PACKAGE.rglob("*.py"))

    def test_none_in_docs_agents_or_package(self):
        found = []
        for path in self.files():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                bad = sorted({f"0x{ord(c):02x}" for c in line if (ord(c) < 0x20 or ord(c) == 0x7F)
                              and c not in self.ALLOWED})
                if bad:
                    found.append(f"{path.relative_to(REPO)}:{number}: {', '.join(bad)}")
        self.assertEqual(found, [], "control characters, probably a backslash lost to a string escape")

    def test_the_check_sees_them(self):
        line = "D:" + chr(6) + "_Projects" + chr(7) + "i-job-search-cn"
        self.assertTrue(any(ord(c) < 0x20 and c not in self.ALLOWED for c in line))
        self.assertTrue(list(self.files()), "sanity: no files to check")

if __name__ == "__main__":
    unittest.main()
