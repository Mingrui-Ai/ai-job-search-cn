"""Generic inbox import and command regressions from #145."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from jobsearch_cn import inbox, screen, store, vocab
REPO = Path(__file__).resolve().parent.parent

def inbox_json(job_id: str, **fields) -> str:
    item = {"format": screen.FORMAT, "site": "official",
            "url": f"https://jobs.example.invalid/openings/{job_id}.html",
            "fetched_at": "2026-11-05T10:31:20+08:00", "text": "数据分析实习生 150-200元/天\n广州"}
    item.update(fields)
    return json.dumps(item, ensure_ascii=False)


class InboxImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.clips = self.tmp / "Downloads" / inbox.CLIP_FOLDER
        self.clips.mkdir(parents=True)
        self.data = self.tmp / "data"

    def write(self, name: str, text: str) -> None:
        (self.clips / name).write_text(text, encoding="utf-8")

    def test_moves_good_files_into_a_new_batch_and_leaves_the_rest(self):
        self.write("20261105-103120-007-a1.json", inbox_json("a1"))
        self.write("20261105-103121-000-a2.json", inbox_json("a2"))
        self.write("bad.json", inbox_json("a3", fetchedAt="x"))
        self.write("wrong-site.json", inbox_json("a4", site="liepin"))
        self.write("notes.txt", "x")
        self.write("half.json.crdownload", "{")
        now = datetime(2026, 11, 5, 11, 0, 0)
        payload = inbox.import_folder(self.clips, self.data, now=now)
        batch = self.data / "inbox" / "official" / "20261105-110000"
        self.assertEqual(payload["batch"], str(batch))
        self.assertEqual(payload["files"], ["20261105-103120-007-a1.json", "20261105-103121-000-a2.json"])
        self.assertEqual(sorted(p.name for p in batch.iterdir()), payload["files"])
        self.assertEqual(sorted(e["file"] for e in payload["left"]),
                         ["bad.json", "half.json.crdownload", "notes.txt", "wrong-site.json"])
        self.assertTrue((self.clips / "bad.json").exists())
        self.assertIn("unknown field", next(e for e in payload["left"] if e["file"] == "bad.json")["reason"])
        check = screen.check(batch, screen.batch_site(batch), vocab.load())
        self.assertEqual((check["jobs"], check["failed"]), (2, 0))
        again = inbox.import_folder(self.clips, self.data, now=now)  # nothing good left: no batch made
        self.assertEqual((again["moved"], again["batch"]), (0, None))
        self.assertEqual([p.name for p in (self.data / "inbox" / "official").iterdir()], ["20261105-110000"])

    def test_same_second_gets_a_second_batch(self):
        now = datetime(2026, 11, 5, 11, 0, 0)
        self.write("a1.json", inbox_json("a1"))
        inbox.import_folder(self.clips, self.data, now=now)
        self.write("a2.json", inbox_json("a2"))
        payload = inbox.import_folder(self.clips, self.data, now=now)
        self.assertTrue(payload["batch"].endswith("20261105-110000-2"))

    def test_command(self):
        self.write("a1.json", inbox_json("a1"))
        out = subprocess.run([sys.executable, "-X", "utf8", "-m", "jobsearch_cn", "jd",
                              "inbox-import", str(self.clips), "--data-dir", str(self.data)],
                             capture_output=True, cwd=REPO)
        self.assertEqual(out.returncode, 0, out.stderr.decode("utf-8", "replace"))
        payload = json.loads(out.stdout.decode("utf-8"))
        self.assertEqual(payload["moved"], 1)
        self.assertTrue(payload["next"].startswith("python -m jobsearch_cn jd screen "))
        self.assertIn("--data-dir", payload["next"])
        missing = subprocess.run([sys.executable, "-X", "utf8", "-m", "jobsearch_cn", "jd",
                                  "inbox-import", str(self.tmp / "nope"), "--data-dir", str(self.data)],
                                 capture_output=True, cwd=REPO)
        self.assertEqual(missing.returncode, 2)

    def test_default_folder(self):
        self.assertEqual(inbox.default_folder(), Path.home() / "Downloads" / "jobsearch-inbox")

    def test_data_root_file_is_json_error_and_source_unchanged(self):
        self.write("a1.json", inbox_json("a1"))
        self.data.write_bytes(b"original")
        out = subprocess.run([sys.executable, "-m", "jobsearch_cn", "jd", "inbox-import", str(self.clips),
                              "--data-dir", str(self.data)], cwd=REPO, capture_output=True)
        self.assertEqual(out.returncode, 2)
        self.assertIn("error", json.loads(out.stderr))
        self.assertNotIn(b"Traceback", out.stderr)
        self.assertEqual(self.data.read_bytes(), b"original")
        self.assertTrue((self.clips / "a1.json").exists())

    def test_partial_copy_failure_preserves_source_and_removes_empty_batch(self):
        import errno
        self.write("a1.json", inbox_json("a1"))
        original = (self.clips / "a1.json").read_bytes()

        def disk_full(source, destination):
            Path(destination).write_bytes(b"partial")
            raise OSError(errno.ENOSPC, "disk full")

        with mock.patch.object(inbox.shutil, "copyfile", side_effect=disk_full):
            payload = inbox.import_folder(self.clips, self.data)
        self.assertEqual((payload["moved"], payload["batch"], payload["next"]), (0, None, None))
        self.assertEqual([entry["file"] for entry in payload["left"]], ["a1.json"])
        self.assertEqual((self.clips / "a1.json").read_bytes(), original)
        self.assertFalse(list(self.data.rglob("*.json")))
        self.assertFalse(list(self.data.rglob(".tmp-*")))

    def test_destination_created_concurrently_is_not_replaced(self):
        self.write("a1.json", inbox_json("a1"))
        real_link = os.link

        def race(source, destination):
            Path(destination).write_bytes(b"existing complete original")
            real_link(source, destination)

        with mock.patch.object(inbox.os, "link", side_effect=race):
            payload = inbox.import_folder(self.clips, self.data)
        self.assertEqual(payload["moved"], 0)
        self.assertTrue((self.clips / "a1.json").exists())
        self.assertEqual((Path(payload["batch"]) / "a1.json").read_bytes(), b"existing complete original")
        self.assertFalse(list(self.data.rglob(".tmp-*")))


class NextCommandTest(unittest.TestCase):
    """The next command is run as printed, by a shell, the way an agent or the user would run it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.clips = self.tmp / "clips"
        self.clips.mkdir()
        self.other = self.data_folder("other data")

    def data_folder(self, name: str) -> Path:
        folder = self.tmp / name
        shutil.copytree(REPO / "tests" / "fixtures" / "cn" / "profile" / "tech", folder / "profile")
        return folder

    def env(self, data_dir=None) -> dict:
        env = dict(os.environ, PYTHONUTF8="1", PYTHONPATH=str(REPO))
        env.pop(store.DATA_DIR_ENV, None)
        if data_dir is not None:
            env[store.DATA_DIR_ENV] = str(data_dir)
        return env

    def import_clips(self, *options, cwd=REPO, env=None) -> dict:
        (self.clips / "a1.json").write_text(inbox_json("a1"), encoding="utf-8")
        out = subprocess.run([sys.executable, "-m", "jobsearch_cn", "jd", "inbox-import", str(self.clips), *options],
                             capture_output=True, cwd=cwd, env=env or self.env(self.other))
        self.assertEqual(out.returncode, 0, out.stderr.decode("utf-8", "replace"))
        return json.loads(out.stdout.decode("utf-8"))

    def run_next(self, command: str, env: dict, powershell: bool = False) -> dict:
        self.assertTrue(command.startswith("python "), command)
        rest = command[len("python"):]
        if os.name == "nt" or powershell:
            argv = [shutil.which("powershell"), "-NoProfile", "-Command", f"& '{sys.executable}'{rest}"]
            out = subprocess.run(argv, capture_output=True, cwd=REPO, env=env)
        else:
            out = subprocess.run(inbox._shell_arg(sys.executable) + rest, shell=True, capture_output=True,
                                 cwd=REPO, env=env)
        self.assertEqual(out.returncode, 0, out.stderr.decode("utf-8", "replace"))
        return json.loads(out.stdout.decode("utf-8"))

    def assert_stored_only_in(self, data: Path) -> None:
        self.assertEqual(len(list((data / "jobs").glob("job_*.json"))), 1)
        self.assertEqual(len(list((data / "matches").glob("*.json"))), 1)
        self.assertFalse((self.other / "jobs").exists())
        self.assertFalse((self.other / "matches").exists())

    def test_named_data_folder_with_spaces_is_kept(self):
        data = self.data_folder("指定 的 数据")
        payload = self.import_clips("--data-dir", str(data))
        screened = self.run_next(payload["next"], self.env(self.other))
        self.assertEqual(screened["imported"]["created"], 1)
        self.assert_stored_only_in(data)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell only")
    def test_literal_dollar_backtick_apostrophe_are_preserved(self):
        data = self.data_folder("$reviewSuffix `tick O'Brien")
        payload = self.import_clips("--data-dir", str(data))
        self.assertEqual(payload["next_shell"], "powershell")
        self.assertEqual(payload["next_argv"][-1], str(data))
        self.run_next(payload["next"], self.env(self.other), powershell=True)
        self.assert_stored_only_in(data)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell only")
    def test_named_data_folder_with_spaces_in_powershell(self):
        data = self.data_folder("指定 的 数据")
        payload = self.import_clips("--data-dir", str(data))
        self.run_next(payload["next"], self.env(self.other), powershell=True)
        self.assert_stored_only_in(data)

    def test_folder_from_the_environment_does_not_rest_on_the_next_environment(self):
        data = self.data_folder("from env")
        payload = self.import_clips(env=self.env(data))
        self.run_next(payload["next"], self.env(self.other))
        self.assert_stored_only_in(data)

    def test_relative_data_folder_is_made_absolute(self):
        data = self.data_folder("relative data")
        payload = self.import_clips("--data-dir", "relative data", cwd=self.tmp)
        self.run_next(payload["next"], self.env(self.other))  # run from another folder
        self.assert_stored_only_in(data)

    def test_arguments_survive_the_shell(self):
        show = [sys.executable, "-c", "import json, sys; print(json.dumps(sys.argv[1:]))"]
        for text in (os.path.abspath(os.sep), str(self.tmp / "a b")):  # a drive root ends in a backslash
            command = " ".join(inbox._shell_arg(part) for part in [*show, text]) + " after"
            out = subprocess.run(["powershell", "-NoProfile", "-Command", "& " + command] if os.name == "nt" else command,
                                 shell=os.name != "nt", capture_output=True, check=True)
            self.assertEqual(json.loads(out.stdout), [text, "after"])
