"""The local entry is opt-in, collect-only, and never discovers remote packages."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

from jobsearch_cn import browser, cli, personal

PACKAGE = Path(__file__).parent / "fixtures" / "collect_personal"


class PersonalModules(unittest.TestCase):
    def test_unconfigured_does_not_inspect_or_import_any_package(self):
        with mock.patch.dict(os.environ, {personal.MODULE_ENV: ""}), mock.patch.object(personal, "_local_path") as path:
            self.assertEqual(personal.load_adapters(), {})
            path.assert_not_called()

    def test_explicit_local_package_and_relative_import(self):
        for path in (PACKAGE, PACKAGE / "__init__.py"):
            with self.subTest(path=path), mock.patch.dict(os.environ, {personal.MODULE_ENV: str(path.resolve())}):
                adapters = personal.load_adapters()
                self.assertEqual(set(adapters), {"example"})
                self.assertEqual(adapters["example"].HOST, "jobs.example.invalid")

    def test_other_commands_never_import_even_configured_broken_code(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            (package / "__init__.py").write_text("raise RuntimeError('must not execute')", encoding="utf-8")
            with mock.patch.dict(os.environ, {personal.MODULE_ENV: str(package)}), redirect_stdout(io.StringIO()), \
                    mock.patch.object(personal, "load_adapters") as load:
                with self.assertRaises(SystemExit) as exit:
                    cli.main(["jd", "--help"])
                self.assertEqual(exit.exception.code, 0)
                load.assert_not_called()

    def test_urls_relative_paths_network_paths_missing_packages_fail_before_browser(self):
        for value in ("https://example.invalid/module", "./module", "//server/share/module", "\\\\server\\share\\module"):
            with self.subTest(value=value), mock.patch.dict(os.environ, {personal.MODULE_ENV: value}), \
                    mock.patch.object(browser, "open_tab") as opened, redirect_stderr(io.StringIO()) as err:
                self.assertEqual(cli.main(["collect", "--help"]), 2)
                self.assertIn("error", json.loads(err.getvalue()))
                opened.assert_not_called()

    def test_invalid_contract_and_import_error_are_json_errors(self):
        for code in ("ADAPTERS = []", "ADAPTERS = {'bad': object()}", "raise ValueError('invalid module')"):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                (Path(directory) / "__init__.py").write_text(code, encoding="utf-8")
                with mock.patch.dict(os.environ, {personal.MODULE_ENV: directory}), redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(cli.main(["collect"]), 2)
                    self.assertIn("error", json.loads(err.getvalue()))

    def test_reconfigure_does_not_reuse_previous_submodule(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("one", "two"):
                package = root / name
                package.mkdir()
                (package / "__init__.py").write_text("from .value import ADAPTERS", encoding="utf-8")
                (package / "value.py").write_text("ADAPTERS = {}", encoding="utf-8")
                with mock.patch.dict(os.environ, {personal.MODULE_ENV: str(package)}):
                    self.assertEqual(personal.load_adapters(), {})
            (root / "two" / "value.py").write_text("raise ValueError('fresh package')", encoding="utf-8")
            with mock.patch.dict(os.environ, {personal.MODULE_ENV: str(root / "two")}), self.assertRaises(personal.ModuleError):
                personal.load_adapters()
