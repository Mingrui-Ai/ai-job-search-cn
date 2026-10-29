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


if __name__ == "__main__":
    unittest.main()
