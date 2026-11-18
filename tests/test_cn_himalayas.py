"""Import and replay synthetic Himalayas details through the public screening CLI."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from jobsearch_cn import jd_parser, screen, store, vocab

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "tests/fixtures/cn/profile/tech/profile.json"
URL = "https://himalayas.app/companies/example/jobs/"
TITLE = "Software Engineer, C# Platform"
COMPANY = "Example, Inc."


def item(slug="alpha", *, title=TITLE, body="Build tools.", legacy=False):
    guid = "example/" + slug
    date_line = "发布日期：2026-11-16" if legacy else "来源最后更新（UTC）：2026-11-16"
    text = "\n".join((title, "公司名称：" + COMPANY, "工作性质：实习（Intern）", date_line,
                      "来源：Himalayas", "来源列出的可申请地区：China", "", body))
    row = {"format": screen.FORMAT, "site": "other" if legacy else "himalayas",
           "text": text, "fetched_at": "2026-11-16T10:00:00Z", "url": URL + slug + "?utm_source=api",
           "extra": {"source": "Himalayas", "guid": guid, "expires_at": "2026-11-17T18:00:00Z"}}
    if not legacy:
        row["site_job_id"] = hashlib.sha256(guid.encode()).hexdigest()
    return row


class HimalayasScreen(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data = Path(temp.name)
        self.jobs = store.Store(self.data)
        self.profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        self.profile["target"]["max_job_age_days"] = 60
        self.profile_path = self.data / "profile.json"
        self.profile_path.write_text(json.dumps(self.profile), encoding="utf-8")

    def batch(self, rows, name):
        where = self.data / "inbox" / rows[0]["site"] / name
        where.mkdir(parents=True)
        for index, row in enumerate(rows):
            (where / f"{index}.json").write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        return where

    def cli(self, path, *options, expected_code=0):
        command = [sys.executable, "-m", "jobsearch_cn", "jd", "screen", str(path), "--data-dir",
                   str(self.data), "--profile", str(self.profile_path), "--as-of", "2026-11-16", *options]
        run = subprocess.run(command, cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                             text=True, encoding="utf-8", capture_output=True)
        self.assertEqual(run.returncode, expected_code, run.stderr + run.stdout)
        return json.loads(run.stdout)

    def test_two_distinct_guids_and_updated_link(self):
        path = self.batch([item("alpha"), item("beta")], "initial")
        self.assertEqual(self.cli(path, "--check")["duplicates"], [])
        payload = self.cli(path)
        self.assertEqual(payload["imported"]["created"], 2)
        saved, _ = self.jobs.all()
        self.assertEqual({job["title"] for job in saved}, {TITLE})
        self.assertEqual({job["company"] for job in saved}, {COMPANY})
        self.assertTrue(all(job["evidence"]["title"]["text"] == TITLE for job in saved))
        self.assertTrue(all(job["evidence"]["company"]["text"] == COMPANY for job in saved))
        self.assertTrue(all(job["published_at"] is None for job in saved))
        self.assertTrue(all(r["freshness"]["status"] == "unknown" for r in payload["shortlist"]["rows"]))
        first = next(job for job in saved if job["source"]["url"].startswith(URL + "alpha"))
        newer = item(title="Director of Customer Success, Americas", body="发布日期：2026-08-10\nBuild tools.")
        newer.update(fetched_at="2026-11-16T11:00:00Z", url=URL + "alpha?campaign=b")
        newer["extra"]["expires_at"] = "2026-12-01T18:00:00Z"
        again = self.cli(self.batch([newer], "edited"))
        self.assertEqual(again["imported"]["updated"], 1)
        updated = self.jobs.get(first["id"])
        self.assertEqual(updated["title"], "Director of Customer Success, Americas")
        self.assertEqual(updated["published_at"], "2026-08-10")
        self.assertEqual(again["freshness"]["excluded"]["jobs"], 1)
        self.assertEqual(self.cli(path)["imported"]["unchanged"], 2)
        self.assertEqual(self.jobs.get(first["id"]), updated)

    def test_legacy_batch_preserves_id_and_corrects_header(self):
        old = item(title="Director of Customer Success, Americas", legacy=True)
        parsed, _ = jd_parser.parse_text(old["text"], single=True, site="other", url=old["url"], source_type="portal",
                                         fetched_at=old["fetched_at"])
        previous = parsed[0]
        previous["status"] = "ranked"
        self.assertEqual(previous["published_at"], "2026-11-16")
        self.assertEqual(previous["company"], "Example")
        self.jobs.save(previous)
        current = self.cli(self.batch([old], "legacy"))
        self.assertEqual(current["imported"]["updated"], 1)
        stored = self.jobs.get(previous["id"])
        self.assertEqual((stored["source"]["site"], stored["status"]), ("himalayas", "ranked"))
        self.assertEqual((stored["title"], stored["company"]), ("Director of Customer Success, Americas", COMPANY))
        self.assertIsNone(stored["published_at"])
        self.assertNotIn("published_at", stored["evidence"])
        self.assertEqual(stored["source"]["imported_at"], previous["source"]["imported_at"])

    def test_older_observation_cannot_list_an_uncorrected_legacy_record(self):
        old = item(legacy=True)
        latest = {**old, "fetched_at": "2026-11-17T10:00:00Z"}
        records, _ = jd_parser.parse_text(latest["text"], single=True, site="other", url=latest["url"],
                                          source_type="portal", fetched_at=latest["fetched_at"])
        _, original = self.jobs.save(records[0])
        result = self.cli(self.batch([old], "older"), expected_code=1)
        self.assertEqual(result["imported"]["skipped"], 1)
        self.assertEqual(result["shortlist"]["total"], 0)
        self.assertIn("最新详情收件", result["skipped"][0]["reason"])
        self.assertEqual(self.jobs.get(original["id"]), original)
        upgraded = self.cli(self.batch([latest], "latest"))
        self.assertEqual(upgraded["imported"]["updated"], 1)
        corrected = self.jobs.get(original["id"])
        self.assertIsNone(corrected["published_at"])
        self.assertEqual(corrected["company"], COMPANY)

    def test_source_expiry_to_the_second_keeps_history(self):
        row = item()
        path = self.batch([row], "expiry")
        def run(at):
            return screen.run(path, "himalayas", self.profile, vocab.load(), self.jobs,
                              store.MatchStore(self.data), now=at, as_of=at.date().isoformat())
        before = run(datetime(2026, 11, 17, 17, 59, 59, tzinfo=timezone.utc))
        self.assertEqual(before["shortlist"]["total"], 1)
        for day in (17, 18):
            after = run(datetime(2026, 11, day, 18, tzinfo=timezone.utc))
            self.assertEqual(after["not_listed"]["expired"], 1)
            self.assertEqual(after["shortlist"]["total"], 0)
        self.assertEqual(len(self.jobs.all()[0]), 1)
        self.assertEqual(self.jobs.all()[0][0]["status"], "new")
