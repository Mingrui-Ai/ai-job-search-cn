"""H25b (Codex B's V18 audit, P2-1): writes stay inside the chosen data directory.

A folder below the data root that is a symlink or a Windows junction would carry
the job store, match drafts or reports somewhere else without a word. Every
write refuses one. The data root itself is the user's choice and may be a link.
All links and their targets live in a temporary directory.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "cn" / "jd"

sys.path.insert(0, str(REPO))
from jobsearch_cn import cli, jd_parser, store  # noqa: E402

NOW = datetime(2026, 10, 27, 10, 0, tzinfo=timezone(timedelta(hours=8)))


def link(path: Path, target: Path) -> None:
    """A directory symlink, or a junction where Windows refuses symlinks without privileges."""
    target.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, path, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            raise unittest.SkipTest("cannot create a directory link here")
        import _winapi
        _winapi.CreateJunction(str(target), str(path))


def run_cli(*args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop(store.DATA_DIR_ENV, None)
    return subprocess.run([sys.executable, "-m", "jobsearch_cn", *args], cwd=REPO, env=env, capture_output=True)


class LinkCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.root, self.outside = self.base / "data", self.base / "outside"
        self.root.mkdir()
        text = (FIXTURES / "boss_intern.txt").read_text(encoding="utf-8")
        [self.job], _ = jd_parser.parse_text(text, now=NOW)
        self.match = {"job_id": self.job["id"], "note": "synthetic"}

    def assert_nothing_outside(self):
        self.assertEqual([p.name for p in self.outside.rglob("*")], [])


class Refused(LinkCase):
    def test_a_linked_jobs_folder(self):
        link(self.root / "jobs", self.outside)
        with self.assertRaisesRegex(store.StoreError, "link or junction"):
            store.Store(self.root).save(self.job)
        self.assert_nothing_outside()

    def test_a_linked_matches_folder(self):
        link(self.root / "matches", self.outside)
        with self.assertRaisesRegex(store.StoreError, "link or junction"):
            store.MatchStore(self.root).save(self.match)
        with self.assertRaisesRegex(store.StoreError, "link or junction"):
            store.MatchStore(self.root).write_draft(self.match)
        self.assert_nothing_outside()

    def test_a_linked_drafts_folder(self):
        link(self.root / "matches" / "drafts", self.outside)
        with self.assertRaisesRegex(store.StoreError, "link or junction"):
            store.MatchStore(self.root).write_draft(self.match)
        self.assert_nothing_outside()
        # The saved records beside it are a real folder, and still written.
        self.assertEqual(store.MatchStore(self.root).save(self.match), "created")

    def test_a_linked_reports_folder(self):
        link(self.root / "reports", self.outside)
        with self.assertRaisesRegex(store.StoreError, "link or junction"):
            cli._report_dir(self.root, NOW)
        self.assert_nothing_outside()

    def test_jd_save_reports_a_structured_error(self):
        link(self.root / "jobs", self.outside)
        proc = run_cli("jd", "parse", str(FIXTURES / "boss_intern.txt"), "--save", "--data-dir", str(self.root))
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("link or junction", json.loads(proc.stderr.decode("utf-8"))["error"])
        self.assert_nothing_outside()


class OlderPython(LinkCase):
    """#85 review (P3-1): Path.is_junction is new in 3.12, and README promises 3.10+. Without it a
    junction must still be refused, and before anything is created behind it."""

    def junction(self, path: Path, target: Path) -> None:
        if sys.platform != "win32":
            raise unittest.SkipTest("junctions are Windows only")
        import _winapi
        target.mkdir(parents=True, exist_ok=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        _winapi.CreateJunction(str(target), str(path))

    def without_is_junction(self):
        import pathlib
        owner = next((cls for cls in pathlib.Path.__mro__ if "is_junction" in vars(cls)), None)
        if owner is None:
            return
        saved = vars(owner)["is_junction"]
        delattr(owner, "is_junction")
        self.addCleanup(setattr, owner, "is_junction", saved)

    def test_the_reparse_attribute_finds_a_junction(self):
        self.junction(self.root / "matches", self.outside)
        self.without_is_junction()
        self.assertFalse(hasattr(Path, "is_junction"))
        with self.assertRaisesRegex(store.StoreError, "link or junction"):
            store.MatchStore(self.root).write_draft(self.match)
        self.assert_nothing_outside()

    def test_the_resolved_path_is_checked_before_the_next_level_is_made(self):
        # Even with no link detection at all, matches/ resolves outside before drafts/ is made in it.
        self.junction(self.root / "matches", self.outside)
        from unittest.mock import patch
        with patch.object(store, "_is_link", return_value=False):
            with self.assertRaisesRegex(store.StoreError, "resolves outside the data directory"):
                store.MatchStore(self.root).write_draft(self.match)
        self.assert_nothing_outside()


class Allowed(LinkCase):
    def test_real_folders(self):
        self.assertEqual(store.Store(self.root).save(self.job)[0], "created")
        self.assertEqual(store.MatchStore(self.root).save(self.match), "created")
        draft = store.MatchStore(self.root).write_draft(self.match)
        report = cli._report_dir(self.root, NOW)
        for path in (self.root / "jobs" / f"{self.job['id']}.json", draft, report):
            with self.subTest(path=path):
                self.assertTrue(path.exists())
                self.assertIn(self.root.resolve(), path.resolve().parents)

    def test_a_linked_data_root_is_the_users_choice(self):
        chosen = self.base / "chosen"
        link(chosen, self.base / "elsewhere")
        self.assertEqual(store.Store(chosen).save(self.job)[0], "created")
        self.assertTrue((self.base / "elsewhere" / "jobs" / f"{self.job['id']}.json").is_file())

    def test_a_missing_data_root_is_created(self):
        root = self.base / "new" / "data"
        self.assertEqual(store.Store(root).save(self.job)[0], "created")
        self.assertTrue((root / "jobs").is_dir())


if __name__ == "__main__":
    unittest.main()
