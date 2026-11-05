"""BOSS one-click clip (docs/cn/boss-clip.md): the extension's page reader and jd inbox-import.

All pages and jobs are made up. The page reader (extensions/boss-clip/clip.js) runs under node on a
fake DOM (extensions/boss-clip/test/fixture_pages.js); its items must pass screen.read_item, the same
check jd screen applies. The node part is skipped when node is not installed.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from jobsearch_cn import inbox, jd_parser, screen, store, vocab

REPO = Path(__file__).resolve().parent.parent
EXTENSION = REPO / "extensions" / "boss-clip"
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is not installed")
class ClipPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run([NODE, str(EXTENSION / "test" / "fixture_pages.js")], capture_output=True, check=True)
        cls.results = json.loads(out.stdout.decode("utf-8"))

    def test_detail_page_is_one_inbox_item_without_recruiter_or_recommendations(self):
        result = self.results["detail"]
        self.assertEqual(result["page"], "detail")
        [entry] = result["items"]
        item = screen.read_item(json.dumps(entry["item"]).encode("utf-8"), "boss")
        self.assertEqual(item["site_job_id"], "bx0001")
        self.assertEqual(item["url"], "https://www.zhipin.com/job_detail/bx0001.html")  # query string dropped
        self.assertRegex(entry["name"], r"^\d{8}-\d{6}-\d{3}-bx0001\.json$")
        text = item["text"]
        self.assertEqual(text.splitlines()[:3], ["数据分析实习生 150-200元/天", "广州 4天/周 6个月 本科", "职位描述"])
        self.assertIn("1. 整理业务数据\n2. 写周报\n工作地址", text)
        for gone in ("刚刚活跃", "王女士", "别的岗位", "融资阶段"):
            self.assertNotIn(gone, text)
        records, _ = jd_parser.parse_text(text, source_type="portal", site="boss", url=item["url"],
                                          vocabulary=vocab.load(), single=True, site_job_id="bx0001",
                                          fetched_at=item["fetched_at"])
        self.assertEqual(records[0]["title"], "数据分析实习生")

    def test_list_page_keeps_each_linked_card_once(self):
        result = self.results["list"]
        self.assertEqual(result["page"], "list")
        [entry] = result["items"]  # no link, another site's link and the repeat are left out
        item = screen.read_item(json.dumps(entry["item"]).encode("utf-8"), "boss")
        self.assertEqual(item["site_job_id"], "abc_123~x")
        self.assertEqual(item["text"], "后端开发实习生 200-250元/天\n深圳·南山区 5天/周 本科\n示例软件")
        self.assertEqual(item["extra"]["page"], "list")

    def test_pages_it_refuses(self):
        for name in ("captcha", "closed", "signed_out", "other_site", "empty"):
            self.assertIn("problem", self.results[name], name)
            self.assertNotIn("items", self.results[name], name)

    def test_what_stands_in_the_way_wins_over_old_job_content(self):
        for name in ("dialog_over_title", "form_over_title", "dialog_over_cards", "form_over_cards",
                     "second_dialog_shown"):
            self.assertIn("登录", self.results[name].get("problem", ""), name)
            self.assertNotIn("items", self.results[name], name)
        self.assertIn("验证", self.results["captcha_over_title"]["problem"])
        self.assertIn("关闭", self.results["closed_with_title"]["problem"])
        self.assertNotIn("items", self.results["captcha_over_title"])
        self.assertNotIn("items", self.results["closed_with_title"])

    def test_what_does_not_block_the_page_still_saves(self):
        for name in ("hidden_dialog", "zero_size_dialog", "header_link_detail", "header_link_list", "jd_words"):
            self.assertNotIn("problem", self.results[name], name)
            self.assertEqual(len(self.results[name]["items"]), 1, name)
        self.assertIn("开发登录弹窗和验证码", self.results["jd_words"]["items"][0]["item"]["text"])

    def test_heading_without_a_title_saves_nothing(self):
        # Such an item would pass read_item and replace a saved job's title and text in jd screen.
        for name in ("empty_h1", "empty_h1_with_text", "blank_h1", "zero_width_h1", "punctuation_h1", "removed_h1"):
            self.assertIn("职位名", self.results[name].get("problem", ""), name)
            self.assertNotIn("items", self.results[name], name)

    def test_job_ids_and_time(self):
        self.assertEqual(self.results["ids"], ["A.b_c~d-e", None, None, "rel"])
        self.assertRegex(self.results["fetched_at"], r"^2026-11-05T10:31:20[+-]\d\d:\d\d$")


def inbox_json(job_id: str, **fields) -> str:
    item = {"format": screen.FORMAT, "site": "boss", "site_job_id": job_id,
            "url": f"https://www.zhipin.com/job_detail/{job_id}.html",
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
        batch = self.data / "inbox" / "boss" / "20261105-110000"
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
        self.assertEqual([p.name for p in (self.data / "inbox" / "boss").iterdir()], ["20261105-110000"])

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
        self.assertEqual(inbox.default_folder(), Path.home() / "Downloads" / "jobsearch-boss-clip")


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
        if powershell:
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
            out = subprocess.run(command, shell=True, capture_output=True, check=True)
            self.assertEqual(json.loads(out.stdout), [text, "after"])


class ManifestTest(unittest.TestCase):
    def test_permissions_stay_minimal(self):
        manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], 3)
        self.assertEqual(sorted(manifest["permissions"]), ["activeTab", "downloads", "scripting"])
        for key in ("host_permissions", "content_scripts", "optional_permissions", "externally_connectable"):
            self.assertNotIn(key, manifest)

    def test_scripts_do_not_navigate_or_fetch(self):
        code = "\n".join((EXTENSION / name).read_text(encoding="utf-8") for name in ("background.js", "clip.js"))
        for word in ("fetch(", "XMLHttpRequest", "chrome.debugger", "chrome.tabs.create", "chrome.tabs.update",
                     ".click(", "location.assign", "location.href =", "window.open", "scrollTo", "eval("):
            self.assertNotIn(word, code)
        self.assertIsNone(re.search(r"\.(innerHTML|outerHTML)\s*=", code))


if __name__ == "__main__":
    unittest.main()
