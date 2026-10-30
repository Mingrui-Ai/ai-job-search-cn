"""H22: explicit, evidenced list corrections survive same-text re-imports."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from jobsearch_cn import jd_parser, schema, store
from tests.test_cn_store import NOW, LATER, run_cli


TEXT = (
    "职位名称：资料整理实习生\n"
    "工作说明：上海是培训地点，不是工作城市。\n"
    "材料说明：Python、Java 是示例名称，不是技能要求。\n"
    "办公方式：不支持远程办公\n"
)
FIELDS = {
    "cities": (["上海"], "上海是培训地点，不是工作城市。"),
    "requirements.skills": (["Python", "Java"], "Python、Java 是示例名称，不是技能要求。"),
}


def set_field(record, path, value):
    target = record
    *parents, leaf = path.split(".")
    for part in parents:
        target = target[part]
    target[leaf] = copy.deepcopy(value)


def record(*, method="rule", text=TEXT, now=NOW, url=None):
    [job], _ = jd_parser.parse_text(text, now=now, url=url)
    # Deliberate false positives, independent of parser changes: storage must
    # let a later evidenced correction remove them without changing the JD.
    for path, (value, quote) in FIELDS.items():
        set_field(job, path, value)
        job["evidence"][path] = {"method": method, "text": quote}
    return job


def cleared(job, path, method):
    correction = copy.deepcopy(job)
    set_field(correction, path, [])
    correction["evidence"][path] = {"method": method, "text": FIELDS[path][1]}
    return correction


class ExplicitListClear(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_user_and_agent_clears_follow_all_source_priorities(self):
        for path in FIELDS:
            for old_method in ("rule", "agent", "user"):
                for method in ("agent", "user"):
                    for text_list in (False, True):
                        with self.subTest(path=path, old=old_method, new=method, text_list=text_list):
                            jobs = store.Store(self.root / f"{path}-{old_method}-{method}-{text_list}")
                            old = record(method=old_method)
                            jobs.save(old)
                            correction = cleared(old, path, method)
                            if text_list:
                                correction["evidence"][path]["text"] = [FIELDS[path][1]]
                            self.assertEqual(schema.validate(correction), [])
                            action, saved = jobs.save(correction)
                            allowed = not (old_method == "user" and method == "agent")
                            self.assertEqual(action, "updated" if allowed else "unchanged")
                            self.assertEqual(saved, correction if allowed else old)
                            self.assertEqual(jobs.get(old["id"]), saved)

    def test_rule_empty_lists_never_clear_even_rule_values(self):
        for path in FIELDS:
            for old_method in ("rule", "agent", "user"):
                with self.subTest(path=path, old=old_method):
                    jobs = store.Store(self.root / f"{path}-{old_method}")
                    old = record(method=old_method)
                    jobs.save(old)
                    self.assertEqual(jobs.save(cleared(old, path, "rule")), ("unchanged", old))

    def test_no_evidence_or_user_null_reason_does_not_clear(self):
        for path in FIELDS:
            for absent in (True, False):
                with self.subTest(path=path, absent=absent):
                    jobs = store.Store(self.root / f"{path}-{absent}")
                    old = record()
                    jobs.save(old)
                    correction = cleared(old, path, "user")
                    if absent:
                        correction["evidence"].pop(path)
                    else:
                        correction["evidence"][path]["text"] = None
                    self.assertEqual(schema.validate(correction), [])
                    self.assertEqual(jobs.save(correction), ("unchanged", old))

    def test_invalid_empty_reasons_are_rejected_without_writing(self):
        jobs = store.Store(self.root)
        old = record()
        jobs.save(old)
        for method in ("agent", "user"):
            for text in ("", " \t\n", [], [" "], 1):
                with self.subTest(method=method, text=text):
                    correction = cleared(old, "requirements.skills", method)
                    correction["evidence"]["requirements.skills"]["text"] = text
                    with self.assertRaises(store.StoreError):
                        jobs.save(correction)
                    self.assertEqual(jobs.get(old["id"]), old)

    def test_rule_reimport_preserves_clear_evidence_status_and_first_import_time(self):
        for method in ("agent", "user"):
            with self.subTest(method=method):
                jobs = store.Store(self.root / method)
                original = record()
                jobs.save(original)
                old = jobs.set_status(original["id"], "ranked")
                for path in FIELDS:
                    old = cleared(old, path, method)
                self.assertEqual(jobs.save(old), ("updated", old))
                self.assertEqual(jobs.save(record(now=LATER)), ("unchanged", old))
                self.assertEqual(jobs.get(old["id"]), old)
                self.assertEqual(len(jobs.all()[0]), 1)

    def test_confirming_an_already_empty_list_protects_it_from_rules(self):
        jobs = store.Store(self.root)
        old = record()
        path = "requirements.skills"
        set_field(old, path, [])
        old["evidence"].pop(path)
        jobs.save(old)
        correction = cleared(old, path, "agent")
        self.assertEqual(jobs.save(correction), ("updated", correction))
        self.assertEqual(jobs.save(record()), ("unchanged", correction))

    def test_cleared_list_retains_priority_but_can_be_corrected_again(self):
        for old_method in ("agent", "user"):
            for method in ("rule", "agent", "user"):
                for new_is_empty in (False, True):
                    with self.subTest(old=old_method, new=method, empty=new_is_empty):
                        jobs = store.Store(self.root / f"{old_method}-{method}-{new_is_empty}")
                        path = "requirements.skills"
                        old = cleared(record(), path, old_method)
                        jobs.save(old)
                        new = copy.deepcopy(old)
                        set_field(new, path, [] if new_is_empty else FIELDS[path][0])
                        new["evidence"][path] = {"method": method, "text": TEXT}
                        allowed = method == "user" or (method == "agent" and old_method == "agent")
                        self.assertEqual(jobs.save(new),
                                         ("updated", new) if allowed else ("unchanged", old))

    def test_scalar_null_with_reason_still_does_not_erase_value(self):
        jobs = store.Store(self.root)
        old = record()
        self.assertIs(old["remote"], False)
        jobs.save(old)
        for method in ("agent", "user"):
            new = copy.deepcopy(old)
            new["remote"] = None
            new["evidence"]["remote"] = {"method": method, "text": "不支持远程办公"}
            self.assertEqual(jobs.save(new), ("unchanged", old))

    def test_clear_survives_same_edited_text_found_by_url_but_not_new_text(self):
        jobs = store.Store(self.root)
        url = "https://jobs.example.invalid/h22"
        first = record(url=url)
        jobs.save(first)
        jobs.set_status(first["id"], "ranked")
        edited = record(text=TEXT + "\n材料说明：第二版", url=url, now=LATER)
        _, saved = jobs.save(edited)
        self.assertNotEqual(saved["id"], edited["id"])
        correction = cleared(saved, "cities", "user")
        self.assertEqual(jobs.save(correction), ("updated", correction))
        self.assertEqual(jobs.save(edited), ("unchanged", correction))
        latest = record(text=TEXT + "\n材料说明：第三版", url=url, now=LATER)
        action, saved = jobs.save(latest)
        self.assertEqual(action, "updated")
        self.assertEqual(saved["cities"], ["上海"])
        self.assertEqual(saved["evidence"]["cities"], latest["evidence"]["cities"])
        self.assertEqual((saved["id"], saved["status"]), (first["id"], "ranked"))
        self.assertEqual(saved["source"]["imported_at"], first["source"]["imported_at"])

    def test_cli_validate_save_show_and_reimport(self):
        def ok(*args):
            result = run_cli(*args)
            self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8", "replace"))
            return json.loads(result.stdout)

        data_args = ["--data-dir", str(self.root / "data")]
        jobs = store.Store(self.root / "data")
        original = record()
        jobs.save(original)
        correction = cleared(original, "cities", "agent")
        path = self.root / "correction.json"
        path.write_text(json.dumps(correction, ensure_ascii=False), encoding="utf-8")
        self.assertTrue(ok("jd", "validate", str(path))["valid"])
        self.assertEqual(ok("jd", "save", str(path), *data_args)["saved"][0]["action"], "updated")
        self.assertEqual(ok("jd", "show", original["id"], *data_args), correction)
        path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(ok("jd", "save", str(path), *data_args)["saved"][0]["action"], "unchanged")
        self.assertEqual(ok("jd", "show", original["id"], *data_args), correction)


class SkillAlternativeClear(unittest.TestCase):
    """H16 integration: groups can be corrected without deleting the job."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.text = "资料整理实习生\n熟悉 Python 或 Java\n以上为课程举例，岗位不设任选技能要求。"
        [self.original], _ = jd_parser.parse_text(self.text, now=NOW)
        self.path = "requirements.skill_alternatives"
        self.assertEqual(self.original["requirements"]["skill_alternatives"], [["Python", "Java"]])

    def correction(self, original, method):
        corrected = copy.deepcopy(original)
        corrected["requirements"]["skill_alternatives"] = []
        corrected["evidence"][self.path] = {
            "method": method, "text": "以上为课程举例，岗位不设任选技能要求。",
        }
        return corrected

    def test_all_priorities_and_same_text_rule_reimport(self):
        for old_method in ("rule", "agent", "user"):
            for new_method in ("rule", "agent", "user"):
                with self.subTest(old=old_method, new=new_method):
                    jobs = store.Store(self.root / f"{old_method}-{new_method}")
                    old = copy.deepcopy(self.original)
                    old["evidence"][self.path]["method"] = old_method
                    jobs.save(old)
                    corrected = self.correction(old, new_method)
                    self.assertEqual(schema.validate(corrected), [])
                    allowed = new_method == "user" or (new_method == "agent" and old_method != "user")
                    expected = corrected if allowed else old
                    self.assertEqual(jobs.save(corrected),
                                     ("updated" if allowed else "unchanged", expected))
                    self.assertEqual(jobs.save(self.original), ("unchanged", expected))
                    self.assertEqual(jobs.get(old["id"]), expected)
                    self.assertEqual(expected["requirements"]["skills"], old["requirements"]["skills"])

    def test_group_clear_requires_reason_and_related_skills_must_stay_valid(self):
        jobs = store.Store(self.root)
        jobs.save(self.original)
        for missing_evidence in (True, False):
            corrected = self.correction(self.original, "user")
            if missing_evidence:
                corrected["evidence"].pop(self.path)
            else:
                corrected["evidence"][self.path]["text"] = None
            self.assertEqual(jobs.save(corrected), ("unchanged", self.original))
        invalid = copy.deepcopy(self.original)
        invalid["requirements"]["skills"] = []
        invalid["evidence"]["requirements.skills"] = {
            "method": "agent", "text": "以上为课程举例，岗位不设任选技能要求。",
        }
        with self.assertRaises(store.StoreError):
            jobs.save(invalid)
        self.assertEqual(jobs.get(self.original["id"]), self.original)
        for method in ("agent", "user"):
            with self.subTest(method=method):
                paired = store.Store(self.root / method)
                paired.save(self.original)
                corrected = self.correction(invalid, method)
                corrected["evidence"]["requirements.skills"]["method"] = method
                self.assertEqual(paired.save(corrected), ("updated", corrected))
                self.assertEqual(paired.save(self.original), ("unchanged", corrected))

    def test_cli_group_clear_and_reparse_keep_correction(self):
        def ok(*args):
            result = run_cli(*args)
            self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8", "replace"))
            return json.loads(result.stdout)

        for method in ("agent", "user"):
            with self.subTest(method=method):
                data_args = ["--data-dir", str(self.root / method)]
                source = self.root / "sample.txt"
                source.write_text(self.text, encoding="utf-8")
                parsed = ok("jd", "parse", str(source), "--save", *data_args)["jobs"][0]
                corrected = self.correction(parsed, method)
                path = self.root / "corrected.json"
                path.write_text(json.dumps(corrected, ensure_ascii=False), encoding="utf-8")
                self.assertTrue(ok("jd", "validate", str(path))["valid"])
                self.assertEqual(ok("jd", "save", str(path), *data_args)["saved"][0]["action"], "updated")
                self.assertEqual(ok("jd", "parse", str(source), "--save", *data_args)["saved"][0]["action"], "unchanged")
                self.assertEqual(ok("jd", "show", parsed["id"], *data_args), corrected)

    def paired_correction(self, old, group_method="agent"):
        corrected = self.correction(old, group_method)
        corrected["requirements"]["skills"] = []
        corrected["evidence"]["requirements.skills"] = {
            "method": "agent", "text": "以上为课程举例，岗位不设任选技能要求。",
        }
        # A rejected merge must not leave this unrelated, valid change behind.
        corrected["company"] = "示例修正公司"
        corrected["evidence"]["company"] = {"method": "user", "text": "合成用户纠正"}
        return corrected

    def assert_rejected_without_writing(self, jobs, old, corrected, reason):
        self.assertEqual(schema.validate(corrected), [])
        before = {p.name: p.read_bytes() for p in jobs.jobs.iterdir()}
        input_before = copy.deepcopy(corrected)
        with self.assertRaises(store.StoreError) as raised:
            jobs.save(corrected)
        error = str(raised.exception)
        self.assertIn("requirements.skill_alternatives[0]", error)
        self.assertIn("Python", error)
        self.assertIn("Java", error)
        self.assertIn(reason, error)
        self.assertIn("clear both fields", error)
        self.assertEqual({p.name: p.read_bytes() for p in jobs.jobs.iterdir()}, before)
        self.assertEqual(jobs.get(old["id"]), old)
        self.assertEqual(corrected, input_before)

    def test_paired_clear_checks_group_priority_independently(self):
        for old_method in ("rule", "agent", "user"):
            for new_method in ("agent", "user"):
                with self.subTest(old_group=old_method, new_group=new_method):
                    jobs = store.Store(self.root / f"paired-{old_method}-{new_method}")
                    old = copy.deepcopy(self.original)
                    old["evidence"][self.path]["method"] = old_method
                    jobs.save(old)
                    corrected = self.paired_correction(old, new_method)
                    if old_method == "user" and new_method == "agent":
                        self.assert_rejected_without_writing(jobs, old, corrected, "lower priority")
                    else:
                        self.assertEqual(jobs.save(corrected), ("updated", corrected))
                        self.assertEqual(jobs.save(self.original), ("unchanged", corrected))
                        self.assertEqual(jobs.get(old["id"]), corrected)

    def test_paired_clear_needs_a_separate_group_reason(self):
        for old_method in ("rule", "agent", "user"):
            for missing in ("absent", "user_null", "rule"):
                with self.subTest(old_group=old_method, missing=missing):
                    jobs = store.Store(self.root / f"reason-{old_method}-{missing}")
                    old = copy.deepcopy(self.original)
                    old["evidence"][self.path]["method"] = old_method
                    jobs.save(old)
                    corrected = self.paired_correction(old, "user")
                    if missing == "absent":
                        corrected["evidence"].pop(self.path)
                    elif missing == "user_null":
                        corrected["evidence"][self.path]["text"] = None
                    else:
                        corrected["evidence"][self.path]["method"] = "rule"
                    self.assert_rejected_without_writing(jobs, old, corrected, "clearing reason")

    def test_rejected_clear_also_protects_same_text_found_by_url(self):
        jobs = store.Store(self.root)
        url = "https://jobs.example.invalid/h22-groups"
        first = copy.deepcopy(self.original)
        first["source"]["url"] = url
        jobs.save(first)
        jobs.set_status(first["id"], "ranked")
        [edited], _ = jd_parser.parse_text(self.text + "\n第二版材料", now=LATER, url=url)
        edited["evidence"][self.path]["method"] = "user"
        _, old = jobs.save(edited)
        self.assertNotEqual(old["id"], edited["id"])
        corrected = self.paired_correction(edited)
        self.assert_rejected_without_writing(jobs, old, corrected, "lower priority")

    def test_h16_reimports_and_new_text_replacement_still_work(self):
        # Previously empty skills must still discard a re-parse's incompatible
        # groups through H16's normal fit; the new import isn't a clear.
        jobs = store.Store(self.root / "reimport")
        empty = self.paired_correction(self.original)
        empty["evidence"].pop(self.path)
        jobs.save(empty)
        self.assertEqual(jobs.save(self.original), ("unchanged", empty))

        # If the attempted skills clear loses its own priority comparison, no
        # skill was removed; there is no new cross-field conflict to reject.
        jobs = store.Store(self.root / "blocked-skills")
        old = copy.deepcopy(self.original)
        for path in ("requirements.skills", self.path):
            old["evidence"][path]["method"] = "user"
        jobs.save(old)
        corrected = self.correction(old, "agent")
        corrected["requirements"]["skills"] = []
        corrected["evidence"]["requirements.skills"] = corrected["evidence"][self.path].copy()
        self.assertEqual(jobs.save(corrected), ("unchanged", old))

        # A genuinely edited JD still replaces the whole record, regardless of
        # the old group's source, while preserving identity/status/import time.
        jobs = store.Store(self.root / "edited")
        old["source"]["url"] = "https://jobs.example.invalid/h22-edited"
        jobs.save(old)
        jobs.set_status(old["id"], "ranked")
        [edited], _ = jd_parser.parse_text(self.text + "\n新版本", now=LATER, url=old["source"]["url"])
        corrected = self.paired_correction(edited)
        action, saved = jobs.save(corrected)
        self.assertEqual(action, "updated")
        self.assertEqual(saved["requirements"]["skills"], [])
        self.assertEqual(saved["requirements"]["skill_alternatives"], [])
        self.assertEqual(saved["evidence"][self.path], corrected["evidence"][self.path])
        self.assertEqual((saved["id"], saved["status"], saved["source"]["imported_at"]),
                         (old["id"], "ranked", old["source"]["imported_at"]))

    def test_cli_rejects_paired_clear_with_structured_error_and_no_write(self):
        for missing_reason in (False, True):
            with self.subTest(missing_reason=missing_reason):
                jobs = store.Store(self.root / str(missing_reason))
                old = copy.deepcopy(self.original)
                old["evidence"][self.path]["method"] = "user"
                jobs.save(old)
                corrected = self.paired_correction(old)
                if missing_reason:
                    corrected["evidence"].pop(self.path)
                path = self.root / "paired.json"
                path.write_text(json.dumps(corrected, ensure_ascii=False), encoding="utf-8")
                valid = run_cli("jd", "validate", str(path))
                self.assertEqual(valid.returncode, 0)
                self.assertTrue(json.loads(valid.stdout)["valid"])
                before = {p.name: p.read_bytes() for p in jobs.jobs.iterdir()}
                result = run_cli("jd", "save", str(path), "--data-dir", str(jobs.jobs.parent))
                self.assertEqual(result.returncode, 2, result.stdout.decode("utf-8"))
                self.assertEqual(result.stdout, b"")
                payload = json.loads(result.stderr)
                self.assertEqual(set(payload), {"error"})
                self.assertIn("requirements.skill_alternatives[0]", payload["error"])
                self.assertIn("clearing reason" if missing_reason else "lower priority", payload["error"])
                self.assertIn("clear both fields", payload["error"])
                self.assertEqual({p.name: p.read_bytes() for p in jobs.jobs.iterdir()}, before)
                # Follow the error's remedy with a synthetic user confirmation.
                corrected["evidence"][self.path] = self.correction(old, "user")["evidence"][self.path]
                path.write_text(json.dumps(corrected, ensure_ascii=False), encoding="utf-8")
                result = run_cli("jd", "save", str(path), "--data-dir", str(jobs.jobs.parent))
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
                self.assertEqual(json.loads(result.stdout)["saved"][0]["action"], "updated")
                self.assertEqual(jobs.get(old["id"]), corrected)


if __name__ == "__main__":
    unittest.main()
