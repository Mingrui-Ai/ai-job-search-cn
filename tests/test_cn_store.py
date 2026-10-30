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


class InterviewMerge(StoreCase):
    """M2-6c: interview and requirements.start merge as whole objects, by evidence priority."""

    TEXT = "职位名称：资料整理实习生\n面试地点：北京\n线上/线下面试\n能尽快到岗"

    def test_an_agent_correction_survives_a_rule_reimport(self):
        [rule], _ = jd_parser.parse_text(self.TEXT, now=NOW)
        self.assertEqual(rule["interview"], {"mode": "mixed", "cities": ["北京"]})
        corrected = json.loads(json.dumps(rule))
        corrected["interview"] = {"mode": "either", "cities": ["北京"]}
        corrected["evidence"]["interview"] = {"text": ["面试地点：北京", "线上/线下面试"], "method": "agent"}
        self.assertEqual(schema.validate(corrected), [])
        self.store.save(rule)
        self.store.save(corrected)
        _, stored = self.store.save(rule)
        self.assertEqual(stored["interview"], {"mode": "either", "cities": ["北京"]})
        self.assertEqual(stored["evidence"]["interview"]["method"], "agent")
        self.assertEqual(stored["requirements"]["start"], {"by": None, "asap": True})

    def test_a_record_saved_before_m2_6c_gains_them_on_reimport(self):
        [record], _ = jd_parser.parse_text(self.TEXT, now=NOW)
        self.store.save(record)
        path = self.root / "jobs" / f"{record['id']}.json"
        old = json.loads(path.read_text(encoding="utf-8"))
        del old["interview"], old["requirements"]["start"]
        for key in ("interview", "requirements.start"):
            old["evidence"].pop(key)
        path.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        self.assertIsNone(self.store.get(record["id"])["interview"])
        _, stored = self.store.save(record)
        self.assertEqual(stored["interview"], record["interview"])
        self.assertEqual(stored["requirements"]["start"], record["requirements"]["start"])


class MergePriority(StoreCase):
    def setUp(self):
        super().setUp()
        # Fictional text and controlled extracted values: these tests exercise
        # storage, independently of how the parser resolves ambiguous months.
        self.text = (
            "职位名称：资料整理实习生\n"
            "平台介绍：实习3个月及以上\n"
            "岗位要求：连续实习4个月以上\n"
            "技能：Python、Go\n"
            "办公候选安排：支持远程；不支持远程\n"
        )
        self.url = "https://jobs.example.invalid/job/merge-priority"

    def record(self, method, months, *, text=None, now=NOW, url=None):
        [record], _ = jd_parser.parse_text(
            self.text if text is None else text, now=now,
            url=self.url if url is None else url,
        )
        record["requirements"]["min_months"] = months
        record["evidence"]["requirements.min_months"] = {
            "text": None if method == "user" else
                    "连续实习4个月以上" if months == 4 else "实习3个月及以上",
            "method": method,
        }
        self.assertEqual(schema.validate(record), [])
        return record

    def test_all_method_pairs_keep_winning_value_and_evidence(self):
        cases = [
            ("rule", "rule", True), ("rule", "agent", True), ("rule", "user", True),
            ("agent", "rule", False), ("agent", "agent", True), ("agent", "user", True),
            ("user", "rule", False), ("user", "agent", False), ("user", "user", True),
        ]
        for old_method, new_method, new_wins in cases:
            # Equal values must not allow lower-priority evidence to take over.
            for new_months in (3, 4):
                with self.subTest(old=old_method, new=new_method, months=new_months):
                    case_store = store.Store(self.root / f"{old_method}-{new_method}-{new_months}")
                    old = self.record(old_method, 4)
                    new = self.record(new_method, new_months)
                    case_store.save(old)
                    action, stored = case_store.save(new)
                    winner = new if new_wins else old
                    self.assertEqual(stored["requirements"]["min_months"],
                                     winner["requirements"]["min_months"])
                    self.assertEqual(stored["evidence"]["requirements.min_months"],
                                     winner["evidence"]["requirements.min_months"])
                    changed = (winner["requirements"]["min_months"] != 4 or
                               winner["evidence"]["requirements.min_months"] !=
                               old["evidence"]["requirements.min_months"])
                    self.assertEqual(action, "updated" if changed else "unchanged")
                    self.assertEqual(case_store.get(old["id"]), stored)

    def test_rule_reimport_does_not_replace_agent_four_months_with_three(self):
        first = self.record("rule", 3)
        self.store.save(first)
        self.store.set_status(first["id"], "ranked")
        correction = self.record("agent", 4)
        self.assertEqual(self.store.save(correction)[0], "updated")
        action, stored = self.store.save(self.record("rule", 3, now=LATER))
        self.assertEqual(action, "unchanged")
        self.assertEqual(stored["requirements"]["min_months"], 4)
        self.assertEqual(stored["evidence"]["requirements.min_months"],
                         correction["evidence"]["requirements.min_months"])
        self.assertEqual(stored["status"], "ranked")
        self.assertEqual(stored["source"]["imported_at"], first["source"]["imported_at"])
        self.assertEqual(len(self.store.all()[0]), 1)

    def test_empty_old_values_accept_rules_despite_stale_user_evidence(self):
        old = self.record("user", None)
        old["requirements"]["skills"] = []
        old["remote"] = None
        for path in ("requirements.skills", "remote"):
            old["evidence"][path] = {"text": None, "method": "user"}
        self.store.save(old)
        new = json.loads(json.dumps(old))
        new["requirements"]["min_months"] = 3
        new["requirements"]["skills"] = ["Python"]
        new["remote"] = False
        for path, text in (("requirements.min_months", "实习3个月及以上"),
                           ("requirements.skills", "Python"), ("remote", "不支持远程")):
            new["evidence"][path] = {"text": text, "method": "rule"}
        action, stored = self.store.save(new)
        self.assertEqual(action, "updated")
        self.assertEqual(stored, new)

    def test_empty_new_user_values_do_not_erase_agent_values_or_evidence(self):
        old = self.record("agent", 4)
        old["requirements"]["skills"] = ["Python"]
        old["evidence"]["requirements.skills"] = {"text": "Python", "method": "agent"}
        old["remote"] = False
        old["evidence"]["remote"] = {"text": "不支持远程", "method": "agent"}
        self.store.save(old)
        new = json.loads(json.dumps(old))
        new["requirements"]["min_months"] = None
        new["requirements"]["skills"] = []
        new["remote"] = None
        for path in ("requirements.min_months", "requirements.skills", "remote"):
            new["evidence"][path] = {"text": None, "method": "user"}
        action, stored = self.store.save(new)
        self.assertEqual(action, "unchanged")
        self.assertEqual(stored, old)

    def test_priorities_are_per_field_and_false_is_a_value(self):
        old = self.record("agent", 4)
        old["requirements"]["skills"] = ["Python"]
        old["evidence"]["requirements.skills"] = {"text": "Python", "method": "rule"}
        old["remote"] = False
        old["evidence"]["remote"] = {"text": None, "method": "user"}
        self.store.save(old)
        new = self.record("rule", 3)
        new["requirements"]["skills"] = ["Go"]
        new["evidence"]["requirements.skills"] = {"text": "Go", "method": "agent"}
        new["remote"] = True
        new["evidence"]["remote"] = {"text": "支持远程", "method": "agent"}
        action, stored = self.store.save(new)
        self.assertEqual(action, "updated")
        self.assertEqual(stored["requirements"]["min_months"], 4)
        self.assertEqual(stored["requirements"]["skills"], ["Go"])
        self.assertIs(stored["remote"], False)
        for path, winner in (("requirements.min_months", old),
                             ("requirements.skills", new), ("remote", old)):
            self.assertEqual(stored["evidence"][path], winner["evidence"][path])

    def test_changed_text_at_same_url_replaces_even_agent_and_user_values(self):
        for method in ("agent", "user"):
            with self.subTest(method=method):
                case_store = store.Store(self.root / method)
                old = self.record(method, 4)
                old["company"] = "示例用户补充公司"
                old["evidence"]["company"] = {"text": None, "method": "user"}
                case_store.save(old)
                case_store.set_status(old["id"], "ranked")
                edited = self.record("rule", 3, text=self.text + "\n岗位说明：已更新安排",
                                     now=LATER, url=self.url + "?utm_source=test")
                edited["company"] = None
                edited["evidence"].pop("company", None)
                self.assertNotEqual(edited["id"], old["id"])
                action, stored = case_store.save(edited)
                self.assertEqual(action, "updated")
                self.assertEqual(stored["requirements"]["min_months"], 3)
                self.assertEqual(stored["evidence"], edited["evidence"])
                self.assertIsNone(stored["company"])
                self.assertEqual(stored["raw_text"], edited["raw_text"])
                self.assertEqual((stored["id"], stored["status"]), (old["id"], "ranked"))
                self.assertEqual(stored["source"]["imported_at"], old["source"]["imported_at"])
                self.assertEqual(len(case_store.all()[0]), 1)

    def test_same_edited_text_found_by_url_still_protects_agent_values(self):
        original = self.record("rule", 3)
        self.store.save(original)
        edited = self.record("rule", 3, text=self.text + "\n岗位说明：新增材料核对",
                             now=LATER)
        _, stored = self.store.save(edited)
        self.assertNotEqual(stored["id"], edited["id"])
        corrected = json.loads(json.dumps(stored))
        corrected["requirements"]["min_months"] = 4
        corrected["evidence"]["requirements.min_months"] = {
            "text": "连续实习4个月以上", "method": "agent",
        }
        self.store.save(corrected)
        action, reimported = self.store.save(edited)
        self.assertEqual(action, "unchanged")
        self.assertEqual(reimported, corrected)
        self.assertEqual(len(self.store.all()[0]), 1)


class SkillAlternatives(StoreCase):
    """H16 added requirements.skill_alternatives to records users had already stored."""

    def stored_before_h16(self) -> dict:
        record = parse("boss_intern.txt")
        self.store.save(record)
        old = json.loads(json.dumps(record))
        del old["requirements"]["skill_alternatives"]
        del old["evidence"]["requirements.skill_alternatives"]
        (self.root / "jobs" / f"{record['id']}.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        return record

    def test_an_older_record_reads_back_with_the_field_and_takes_a_reimport(self):
        record = self.stored_before_h16()
        self.assertEqual(self.store.get(record["id"])["requirements"]["skill_alternatives"], [])
        self.assertEqual(self.store.all()[0][0]["requirements"]["skill_alternatives"], [])
        self.assertEqual(schema.validate(self.store.get(record["id"])), [])
        action, stored = self.store.save(parse("boss_intern.txt", now=LATER))
        self.assertEqual(action, "updated")
        self.assertEqual(stored["requirements"]["skill_alternatives"], [["Golang", "Java"]])

    def test_groups_follow_the_skills_when_the_merge_would_split_them(self):
        # An agent dropped Java from the skills; a re-parse offers "Golang 或 Java" again. The
        # agent's skills win, so the re-parse's group, naming Java, cannot come with them.
        record = self.stored_before_h16()
        agent = self.store.get(record["id"])
        agent["requirements"]["skills"] = ["Go", "MySQL", "Redis", "Golang", "Docker", "Kubernetes"]
        agent["evidence"]["requirements.skills"]["method"] = "agent"
        self.assertEqual(self.store.save(agent)[0], "updated")
        action, stored = self.store.save(parse("boss_intern.txt", now=LATER))
        self.assertEqual(action, "unchanged")
        self.assertEqual(stored["requirements"]["skill_alternatives"], [])
        self.assertNotIn("requirements.skill_alternatives", stored["evidence"])


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
