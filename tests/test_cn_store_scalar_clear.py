"""H22b: deliberate scalar/object corrections, using synthetic records only."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from jobsearch_cn import jd_parser, schema, score, store
from tests.test_cn_schema import minimal_record
from tests.test_cn_store import NOW, LATER, run_cli
from tests.test_cn_store_clear import set_field


FIELDS = {
    "title": ("样品员", "样品员只是培训案例，不是此岗位名称。"),
    "company": ("示例资料公司", "示例资料公司只是案例，不是招聘公司。"),
    "remote": (False, "不支持远程只是旧项目说明，不是此岗位的办公要求。"),
    "employment_type": ("internship", "实习只是案例类型，不是本岗位类型。"),
    "salary": ({"min": 100, "max": 100, "unit": "CNY/day", "months": None, "negotiable": False},
               "CFA一级证书编号不是薪资。"),
    "requirements.graduation": ({"years": [2027], "strict": True}, "2027届是活动名称，不是招聘限制。"),
    "requirements.days_per_week": (5, "5天是培训时长，不是每周到岗要求。"),
    "requirements.min_months": (3, "3个月是项目历史，不是实习时长要求。"),
    "requirements.education": ({"min": "master", "preferred": None}, "硕士是讲师学历，不是候选人要求。"),
    "requirements.start": ({"by": "2026-12-01", "asap": False}, "2026-12-01是活动日期，不是到岗截止。"),
    "interview": ({"mode": "onsite", "cities": ["深圳"]}, "深圳现场面试只是材料举例，不是本次面试安排。"),
    "benefits.meals": ({"per_day": 2, "allowance": None}, "包两餐是旧方案，不是本岗位福利。"),
    "return_offer": (False, "不转正是旧方案，不是本次约定。"),
    "published_at": ("2026-10-01", "2026-10-01是项目创建日期，不是岗位发布时间。"),
    "deadline": ("2026-12-31", "2026-12-31是培训结束日，不是投递截止。"),
}
TEXT = "\n".join(quote for _, quote in FIELDS.values()) + "\nPython 或 Java 只是课程举例，不是技能要求。"


def record():
    job = minimal_record()
    job["raw_text"] = TEXT
    job["id"] = jd_parser.parse_text(TEXT, now=NOW, single=True)[0][0]["id"]
    for path, (value, quote) in FIELDS.items():
        set_field(job, path, value)
        job["evidence"][path] = {"method": "rule", "text": quote}
    return job


def clear(job, path="salary", method="agent", text=None):
    new = copy.deepcopy(job)
    set_field(new, path, None)
    new["evidence"][path] = {"method": method, "text": FIELDS[path][1] if text is None else text, "clear": True}
    return new


class ScalarClear(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_all_fields_and_sources_with_string_or_list_reasons(self):
        self.assertEqual(schema.validate(record()), [])
        for path in FIELDS:
            for old_method in ("rule", "agent", "user"):
                for method in ("agent", "user"):
                    for as_list in (False, True):
                        with self.subTest(path=path, old=old_method, method=method, as_list=as_list):
                            jobs = store.Store(self.root / f"{path}-{old_method}-{method}-{as_list}")
                            old = record()
                            old["evidence"][path]["method"] = old_method
                            jobs.save(old)
                            new = clear(old, path, method)
                            if as_list:
                                new["evidence"][path]["text"] = [FIELDS[path][1]]
                            self.assertEqual(schema.validate(new), [])
                            if old_method == "user" and method == "agent":
                                with self.assertRaisesRegex(store.StoreError, "lower priority"):
                                    jobs.save(new)
                                self.assertEqual(jobs.get(old["id"]), old)
                            else:
                                self.assertEqual(jobs.save(new), ("updated", new))
                                self.assertEqual(jobs.get(old["id"]), new)

    def test_ordinary_null_keeps_values_even_with_nonempty_evidence(self):
        for path in FIELDS:
            for method in (None, "rule", "agent", "user"):
                with self.subTest(path=path, method=method):
                    jobs = store.Store(self.root / f"{path}-{method}")
                    old = record()
                    jobs.save(old)
                    new = clear(old, path)
                    new["evidence"][path].pop("clear")
                    if method is None:
                        new["evidence"].pop(path)
                    else:
                        new["evidence"][path]["method"] = method
                    self.assertEqual(jobs.save(new), ("unchanged", old))

    def test_clear_is_persistent_and_can_be_replaced_by_equal_or_higher_sources(self):
        for path in FIELDS:
            for old_method in ("agent", "user"):
                for method in ("rule", "agent", "user"):
                    with self.subTest(path=path, old=old_method, new=method):
                        jobs = store.Store(self.root / f"{path}-{old_method}-{method}")
                        old = clear(record(), path, old_method)
                        self.assertEqual(jobs.save(old), ("created", old))
                        self.assertEqual(jobs.save(old), ("unchanged", old))
                        ordinary_null = copy.deepcopy(old)
                        ordinary_null["evidence"][path] = {"method": "user", "text": None}
                        self.assertEqual(jobs.save(ordinary_null), ("unchanged", old))
                        new = record()
                        new["evidence"][path]["method"] = method
                        allowed = method == "user" or method == old_method == "agent"
                        self.assertEqual(jobs.save(new), ("updated", new) if allowed else ("unchanged", old))
                        if allowed:
                            self.assertNotIn("clear", jobs.get(old["id"])["evidence"][path])

    def test_invalid_clear_intents_and_evidence_never_write(self):
        cases = []
        for value in (False, None, 0, 1, "true", [], {}):
            new = clear(record())
            new["evidence"]["salary"]["clear"] = value
            cases.append(new)
        for method in ("rule", "unknown"):
            cases.append(clear(record(), method=method))
        for method in ("agent", "user"):
            for value in (None, "", " \n", [], [""], [FIELDS["salary"][1], " "], 1):
                new = clear(record(), method=method)
                new["evidence"]["salary"]["text"] = value
                cases.append(new)
        for quote in ("没有这段文字", FIELDS["salary"][1].replace("CFA", "cfa"), "CFA 一级证书编号不是薪资。"):
            cases.append(clear(record(), text=quote))
        new = record()
        new["evidence"]["salary"]["clear"] = True
        cases.append(new)
        for path in ("cities", "requirements.skills", "requirements.skill_alternatives", "salary.min", "id",
                     "source", "status", "raw_text", "guard", "requirements", "benefits"):
            new = record()
            new["evidence"][path] = {"method": "user", "text": "本人明确纠正", "clear": True}
            cases.append(new)
        jobs = store.Store(self.root)
        old = record()
        jobs.save(old)
        path = jobs.jobs / (old["id"] + ".json")
        before = path.read_bytes()
        for number, new in enumerate(cases):
            with self.subTest(number=number):
                self.assertTrue(schema.validate(new))
                with self.assertRaises(store.StoreError):
                    jobs.save(new)
                self.assertEqual(path.read_bytes(), before)

    def test_user_reason_need_not_be_jd_text(self):
        new = clear(record(), method="user", text="本人确认这是误录，当前薪资尚未提供。")
        self.assertEqual(schema.validate(new), [])
        jobs = store.Store(self.root)
        jobs.save(record())
        self.assertEqual(jobs.save(new), ("updated", new))

    def test_priority_error_preserves_entire_file_and_index(self):
        jobs = store.Store(self.root)
        old = clear(record(), method="user")
        old["source"].update(site="boss", site_job_id="scalar-old")
        jobs.save(old)
        index = jobs.index()
        index_before = copy.deepcopy(index.__dict__)
        path = jobs.jobs / (old["id"] + ".json")
        before = path.read_bytes()
        new = clear(old)
        new["company"] = "新公司"
        new["evidence"]["company"] = {"method": "user", "text": "用户纠正公司"}
        with self.assertRaisesRegex(store.StoreError, "salary.*lower priority"):
            jobs.save(new, index)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(index.__dict__, index_before)

    def test_skill_group_protection_still_blocks_whole_scalar_correction(self):
        jobs = store.Store(self.root)
        old = record()
        old["requirements"].update(skills=["Python", "Java"], skill_alternatives=[["Python", "Java"]])
        for field, method in (("skills", "rule"), ("skill_alternatives", "user")):
            old["evidence"]["requirements." + field] = {"method": method, "text": "Python 或 Java"}
        jobs.save(old)
        new = clear(old)
        for field in ("skills", "skill_alternatives"):
            new["requirements"][field] = []
            new["evidence"]["requirements." + field] = {"method": "agent", "text": "Python 或 Java 只是课程举例，不是技能要求。"}
        self.assertEqual(schema.validate(new), [])
        with self.assertRaisesRegex(store.StoreError, "cannot clear requirements.skills"):
            jobs.save(new)
        self.assertEqual(jobs.get(old["id"]), old)

    def test_same_text_keys_protect_clear_but_different_text_replaces(self):
        for key in ("url", "portal"):
            with self.subTest(key=key):
                jobs = store.Store(self.root / key)
                old = record()
                old["source"]["url"] = "https://jobs.example.invalid/scalar"
                if key == "portal":
                    old["source"].update(site="boss", site_job_id="scalar")
                jobs.save(old)
                jobs.set_status(old["id"], "ranked")
                edited = copy.deepcopy(old)
                edited["raw_text"] += "\n新的原文版本。"
                edited["id"] = jd_parser.parse_text(edited["raw_text"], now=NOW, single=True)[0][0]["id"]
                edited["source"]["imported_at"] = LATER.isoformat()
                _, saved = jobs.save(edited)
                correction = clear(saved, method="user")
                jobs.save(correction)
                self.assertEqual(jobs.save(edited), ("unchanged", correction))
                later = copy.deepcopy(edited)
                later["raw_text"] += "\n又一版本。"
                action, replaced = jobs.save(later)
                self.assertEqual(action, "updated")
                self.assertEqual(replaced["salary"], FIELDS["salary"][0])
                self.assertNotIn("clear", replaced["evidence"]["salary"])
                self.assertEqual((replaced["id"], replaced["status"]), (old["id"], "ranked"))
                self.assertEqual(replaced["source"]["imported_at"], old["source"]["imported_at"])

    def test_match_hash_becomes_stale_and_rule_reimport_keeps_correction(self):
        jobs = store.Store(self.root)
        old = record()
        jobs.save(old)
        match_record = {"job_hash": score.job_hash(old), "profile_hash": "profile", "weights": {}, "rules_version": 13}
        _, corrected = jobs.save(clear(old))
        self.assertNotEqual(score.job_hash(old), score.job_hash(corrected))
        self.assertEqual(score.stale_reasons(match_record, corrected, "profile", {}), ["job"])
        self.assertEqual(jobs.save(old), ("unchanged", corrected))
        self.assertEqual(score.RULES_VERSION, 13)

    def test_merged_record_rechecks_exact_evidence_against_retained_raw_text(self):
        jobs = store.Store(self.root)
        old = record()
        jobs.save(old)
        new = clear(old)
        new["raw_text"] = new["raw_text"].replace("CFA", "cfa")
        new["evidence"]["salary"]["text"] = FIELDS["salary"][1].replace("CFA", "cfa")
        self.assertEqual(schema.validate(new), [])
        with self.assertRaisesRegex(store.StoreError, "merged record is invalid"):
            jobs.save(new)
        self.assertEqual(jobs.get(old["id"]), old)

    def test_cli_single_record_and_envelope_roundtrip(self):
        jobs = store.Store(self.root / "data")
        old = record()
        jobs.save(old)
        path = self.root / "correction.json"
        data_args = ["--data-dir", str(jobs.root)]
        new = clear(old)
        path.write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")
        validated = run_cli("jd", "validate", str(path))
        self.assertEqual(validated.returncode, 0, validated.stdout)
        self.assertTrue(json.loads(validated.stdout)["valid"])
        for payload in (new, {"jobs": [new]}):
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            saved = run_cli("jd", "save", str(path), *data_args)
            self.assertEqual(saved.returncode, 0, saved.stderr)
            self.assertIn(json.loads(saved.stdout)["saved"][0]["action"], ("updated", "unchanged"))
        shown = run_cli("jd", "show", old["id"], *data_args)
        self.assertEqual(shown.returncode, 0)
        self.assertEqual(json.loads(shown.stdout), new)

    def test_cli_multi_record_clear_rejected_before_any_write(self):
        path = self.root / "batch.json"
        for position in (0, 1):
            with self.subTest(position=position):
                jobs = store.Store(self.root / str(position))
                old = record()
                jobs.save(old)
                other = record()
                other["id"] = "job_abcdef012345"
                other["raw_text"] += "\n其他岗位。"
                records = [other]
                records.insert(position, clear(old))
                path.write_text(json.dumps({"jobs": records}, ensure_ascii=False), encoding="utf-8")
                before = {p.name: p.read_bytes() for p in jobs.jobs.iterdir()}
                result = run_cli("jd", "save", str(path), "--data-dir", str(jobs.root))
                self.assertNotEqual(result.returncode, 0)
                error = json.loads(result.stderr or result.stdout)
                self.assertIn("single", json.dumps(error))
                self.assertEqual({p.name: p.read_bytes() for p in jobs.jobs.iterdir()}, before)


if __name__ == "__main__":
    unittest.main()
