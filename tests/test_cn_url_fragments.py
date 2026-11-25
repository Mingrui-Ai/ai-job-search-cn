"""Synthetic pasted JDs exercise URL deduplication through the documented CLI."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jobsearch_cn import store


REPO = Path(__file__).resolve().parent.parent


class RouteFragmentCommands(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.data = ["--data-dir", str(self.root / "data")]

    def cli(self, *args):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        env.pop("JOBSEARCH_CN_DATA_DIR", None)
        result = subprocess.run([sys.executable, "-m", "jobsearch_cn", *args, *self.data],
                                cwd=REPO, env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return json.loads(result.stdout)

    def save(self, title, url):
        path = self.root / "jd.txt"
        path.write_text(f"职位名称：{title}\n公司名称：示例科技有限公司\n"
                        "工作地点：深圳\n任职要求：熟悉Python。\n", encoding="utf-8")
        return self.cli("jd", "parse", str(path), "--url", url, "--save")

    def assert_distinct_jobs(self, first_url, second_url):
        first = self.save("后端开发工程师", first_url)
        second = self.save("前端开发工程师", second_url)
        self.assertEqual(second["saved"][0]["action"], "created")
        first_id, second_id = first["saved"][0]["id"], second["saved"][0]["id"]
        self.assertNotEqual(first_id, second_id)
        self.assertEqual({item["id"] for item in self.cli("jd", "list")["jobs"]}, {first_id, second_id})
        self.assertEqual(self.cli("jd", "show", first_id)["raw_text"], first["jobs"][0]["raw_text"])
        self.assertEqual(self.cli("jd", "show", second_id)["raw_text"], second["jobs"][0]["raw_text"])
        index = store.Store(self.root / "data").index()
        self.assertEqual(index.url(store.normalize_url(first_url)), first_id)
        self.assertEqual(index.url(store.normalize_url(second_url)), second_id)

    def test_distinct_fragment_paths_keep_both_jobs(self):
        self.assert_distinct_jobs("https://careers.example.test/#/jobs/1",
                                  "https://careers.example.test/#/jobs/2")

    def test_distinct_fragment_queries_keep_both_jobs(self):
        self.assert_distinct_jobs("https://careers.example.test/#/jobDetail?id=1",
                                  "https://careers.example.test/#/jobDetail?id=2")

    def test_distinct_hashbang_routes_keep_both_jobs(self):
        self.assert_distinct_jobs("https://careers.example.test/#!/jobs/1",
                                  "https://careers.example.test/#!/jobs/2")

    def test_same_route_updates_existing_job_and_preserves_status(self):
        first = self.save("后端开发工程师", "http://CAREERS.example.test/?utm_source=share#/jobs/1")
        job_id = first["saved"][0]["id"]
        self.cli("jd", "status", job_id, "ranked")
        second = self.save("高级后端开发工程师", "https://careers.example.test/#/jobs/1")
        self.assertEqual(second["saved"][0]["action"], "updated")
        self.assertEqual(second["saved"][0]["id"], job_id)
        self.assertEqual(second["saved"][0]["status"], "ranked")
        self.assertEqual(len(self.cli("jd", "list")["jobs"]), 1)
        self.assertEqual(self.cli("jd", "show", job_id)["raw_text"], second["jobs"][0]["raw_text"])

    def test_plain_page_anchors_still_match_the_same_job(self):
        first = self.save("后端开发工程师", "https://careers.example.test/jobs/1#top")
        second = self.save("高级后端开发工程师", "https://careers.example.test/jobs/1#requirements")
        self.assertEqual(second["saved"][0]["action"], "updated")
        self.assertEqual(second["saved"][0]["id"], first["saved"][0]["id"])
        self.assertEqual(len(self.cli("jd", "list")["jobs"]), 1)
