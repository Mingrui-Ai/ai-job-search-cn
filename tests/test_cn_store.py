"""Tests for jobsearch_cn/store.py and the `jd save / list / show / status` commands.

The store is where duplicates die (gap G2), so these pin the dedup keys - the
content fingerprint, then the normalised URL - and the merge rules that make
re-importing safe: an agent's completion lands, a fresh rule parse never erases
it, a value the user typed in survives both, and status is the store's.
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
from jobsearch_cn import jd_parser, schema, store  # noqa: E402

NOW = datetime(2026, 10, 27, 10, 0, tzinfo=timezone(timedelta(hours=8)))
LATER = NOW + timedelta(days=1)


def parse(name: str, *, now=NOW, **options) -> dict:
    text = (FIXTURES / name).read_text(encoding="utf-8")
    [record] = jd_parser.parse_text(text, now=now, **options)[0]
    return record


class StoreCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.store = store.Store(self.root)


class Dedup(StoreCase):
    def test_first_save_creates_one_file(self):
        record = parse("boss_intern.txt")
        self.assertEqual(self.store.save(record)[0], "created")
        self.assertEqual([p.name for p in (self.root / "jobs").iterdir()], [f"{record['id']}.json"])
        self.assertEqual(self.store.get(record["id"]), record)

    def test_reimporting_the_same_jd_is_unchanged(self):
        self.store.save(parse("boss_intern.txt"))
        action, _ = self.store.save(parse("boss_intern.txt", now=LATER))
        self.assertEqual(action, "unchanged")
        self.assertEqual(len(self.store.all()[0]), 1)

    def test_whitespace_differences_are_the_same_jd(self):
        text = (FIXTURES / "boss_intern.txt").read_text(encoding="utf-8")
        [a], _ = jd_parser.parse_text(text, now=NOW)
        [b], _ = jd_parser.parse_text(text.replace("\n", "\r\n\n"), now=LATER)
        self.store.save(a)
        self.assertEqual(self.store.save(b)[0], "unchanged")

    def test_different_jds_are_kept_apart(self):
        for name in sorted(p.name for p in FIXTURES.glob("*.txt")):
            self.assertEqual(self.store.save(parse(name))[0], "created", name)
        self.assertEqual(len(self.store.all()[0]), len(list(FIXTURES.glob("*.txt"))))

    def test_an_edited_posting_at_the_same_url_updates_in_place(self):
        url = "https://www.zhipin.com/job_detail/abc123.html"
        first = parse("boss_intern.txt", url=url)
        self.store.save(first)
        self.store.set_status(first["id"], "ranked")
        text = (FIXTURES / "boss_intern.txt").read_text(encoding="utf-8") + "\n补充：可提供住宿补贴"
        [edited], _ = jd_parser.parse_text(text, now=LATER, url=url + "?ka=search_list&utm_source=x")
        self.assertNotEqual(edited["id"], first["id"])
        action, stored = self.store.save(edited)
        self.assertEqual(action, "updated")
        self.assertEqual((stored["id"], stored["status"]), (first["id"], "ranked"))
        self.assertEqual(stored["source"]["imported_at"], first["source"]["imported_at"])
        self.assertIn("住宿补贴", stored["raw_text"])
        self.assertEqual(len(self.store.all()[0]), 1)
        self.assertEqual(self.store.save(edited)[0], "unchanged")

    def test_invalid_records_are_refused_and_nothing_is_written(self):
        record = parse("boss_intern.txt")
        record["status"] = "applied?"
        with self.assertRaises(store.StoreError):
            self.store.save(record)
        self.assertFalse((self.root / "jobs").exists())


class NormalizeUrl(unittest.TestCase):
    def test_tracking_and_cosmetic_differences_match(self):
        same = [
            "https://www.zhipin.com/job_detail/abc.html",
            "http://WWW.ZHIPIN.COM/job_detail/abc.html/",
            "https://www.zhipin.com:443/job_detail/abc.html?ka=search&utm_medium=x#top",
            "https://www.zhipin.com/job_detail/abc.html?spm=1.2&from=share",
        ]
        self.assertEqual(len({store.normalize_url(u) for u in same}), 1)

    def test_identifying_parameters_are_kept(self):
        self.assertNotEqual(store.normalize_url("https://a.example/job?id=1"),
                            store.normalize_url("https://a.example/job?id=2"))

    def test_query_order_does_not_matter(self):
        self.assertEqual(store.normalize_url("https://a.example/j?a=1&b=2"),
                         store.normalize_url("https://a.example/j?b=2&a=1"))

    def test_no_url_is_none(self):
        self.assertIsNone(store.normalize_url(None))
        self.assertIsNone(store.normalize_url(""))


class Merge(StoreCase):
    def setUp(self):
        super().setUp()
        self.base = parse("shixiseng_intern.txt")
        self.store.save(self.base)
        # The parser leaves company or education empty on some fixtures; pick
        # a field it left empty so the test exercises a real completion.
        self.empty = next(p for p in ("company", "requirements.education", "title")
                          if not schema._has_value(schema._field(self.base, p)))

    def completed(self, method: str) -> dict:
        record = json.loads(json.dumps(self.base))
        snippet = self.base["raw_text"].splitlines()[0].strip()
        if self.empty == "requirements.education":
            record["requirements"]["education"] = {"min": "bachelor", "preferred": None}
        else:
            record[self.empty] = snippet[:40]
        record["evidence"][self.empty] = {"text": snippet[:40] if method != "user" else None, "method": method}
        self.assertEqual(schema.validate(record), [], "sanity: the completed record is valid")
        return record

    def test_an_agent_completion_lands(self):
        action, stored = self.store.save(self.completed("agent"))
        self.assertEqual(action, "updated")
        self.assertEqual(stored["evidence"][self.empty]["method"], "agent")

    def test_a_fresh_rule_parse_does_not_erase_the_completion(self):
        self.store.save(self.completed("agent"))
        action, stored = self.store.save(parse("shixiseng_intern.txt", now=LATER))
        self.assertEqual(action, "unchanged")
        self.assertIn(self.empty, stored["evidence"])

    def test_a_user_value_survives_an_agent_value(self):
        self.store.save(self.completed("user"))
        self.store.save(self.completed("agent"))
        self.assertEqual(self.store.get(self.base["id"])["evidence"][self.empty]["method"], "user")

    def test_status_is_the_stores_not_the_imports(self):
        self.store.set_status(self.base["id"], "skipped")
        self.store.save(self.completed("agent"))
        self.assertEqual(self.store.get(self.base["id"])["status"], "skipped")


class Files(StoreCase):
    def test_a_corrupt_file_is_reported_not_fatal(self):
        self.store.save(parse("boss_intern.txt"))
        (self.root / "jobs" / "job_000000000000.json").write_text("{not json", encoding="utf-8")
        records, warnings = self.store.all()
        self.assertEqual(len(records), 1)
        self.assertEqual(len(warnings), 1)

    def test_ids_cannot_escape_the_store(self):
        for bad in ("../secret", "job_../../x", "JOB_9F4694691D57"):
            with self.assertRaises(store.StoreError):
                self.store.get(bad)

    def test_no_temp_files_are_left_behind(self):
        self.store.save(parse("boss_intern.txt"))
        self.assertEqual([p.name for p in (self.root / "jobs").glob(".tmp-*")], [])

    def test_the_default_location_is_gitignored_data(self):
        self.assertEqual(store.DEFAULT_DATA_DIR, REPO / "data")
        self.assertIn("/data/", (REPO / ".gitignore").read_text(encoding="utf-8").splitlines())


def run_cli(*args, input_bytes=None):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop(store.DATA_DIR_ENV, None)
    return subprocess.run([sys.executable, "-m", "jobsearch_cn", *args], cwd=REPO, env=env,
                          input=input_bytes, capture_output=True)


class Commands(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)
        self.data = ["--data-dir", str(self.tmp / "data")]

    def ok(self, *args, input_bytes=None) -> dict:
        proc = run_cli(*args, input_bytes=input_bytes)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        return json.loads(proc.stdout)

    def test_parse_save_list_show_status(self):
        out = self.ok("jd", "parse", str(FIXTURES / "boss_intern.txt"), "--save", *self.data)
        [saved] = out["saved"]
        self.assertEqual(saved["action"], "created")
        job_id = saved["id"]
        again = self.ok("jd", "parse", str(FIXTURES / "boss_intern.txt"), "--save", *self.data)
        self.assertEqual(again["saved"][0]["action"], "unchanged")
        listed = self.ok("jd", "list", *self.data)["jobs"]
        self.assertEqual([j["id"] for j in listed], [job_id])
        self.assertEqual(self.ok("jd", "show", job_id, *self.data)["raw_text"], out["jobs"][0]["raw_text"])
        self.assertEqual(self.ok("jd", "status", job_id, "ranked", *self.data)["status"], "ranked")
        self.assertEqual(self.ok("jd", "list", "--status", "new", *self.data)["jobs"], [])

    def test_save_takes_parse_output_or_a_single_record(self):
        parsed = self.ok("jd", "parse", str(FIXTURES / "nowcoder_campus.txt"))
        path = self.tmp / "parsed.json"
        path.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.ok("jd", "save", str(path), *self.data)["saved"][0]["action"], "created")
        single = json.dumps(parsed["jobs"][0], ensure_ascii=False).encode("utf-8")
        self.assertEqual(self.ok("jd", "save", *self.data, input_bytes=single)["saved"][0]["action"], "unchanged")

    def test_one_invalid_record_saves_none(self):
        parsed = self.ok("jd", "parse", str(FIXTURES / "boss_intern.txt"))
        bad = json.loads(json.dumps(parsed["jobs"][0]))
        bad["title"] = "编造的岗位名"
        bad["evidence"]["title"] = {"text": "编造的岗位名", "method": "agent"}
        payload = json.dumps({"jobs": [parsed["jobs"][0], bad]}, ensure_ascii=False).encode("utf-8")
        proc = run_cli("jd", "save", *self.data, input_bytes=payload)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout)["invalid"][0]["index"], 1)
        self.assertEqual(self.ok("jd", "list", *self.data)["jobs"], [])

    def test_unknown_ids(self):
        self.assertEqual(run_cli("jd", "show", "job_000000000000", *self.data).returncode, 1)
        self.assertEqual(run_cli("jd", "status", "job_000000000000", "ranked", *self.data).returncode, 1)
        self.assertEqual(run_cli("jd", "show", "../etc", *self.data).returncode, 2)

    def test_data_dir_from_the_environment(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8", **{store.DATA_DIR_ENV: str(self.tmp / "env")})
        proc = subprocess.run([sys.executable, "-m", "jobsearch_cn", "jd", "parse",
                               str(FIXTURES / "boss_intern.txt"), "--save"],
                              cwd=REPO, env=env, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        self.assertEqual(len(list((self.tmp / "env" / "jobs").glob("job_*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
