"""Tests for jobsearch_cn/material.py, the optional profile ids and `material validate` (M3-1).

A material may only choose, order and reword what the profile holds, so these pin: the sample material
passes; each way of citing what is not there fails with the path and the reason (a missing or id-less entry,
the wrong section, a bullet that does not cite its own entry, a course or skill the profile lacks); a rewrite
cannot add a number, written in figures or in Chinese (三倍, 六成, 两万, 百分之三十), nor a skill; the
warnings; the exit codes; and that the ids are optional, so the M2 sample profiles stay valid unchanged.
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SAMPLE = REPO / "tests" / "fixtures" / "cn" / "material" / "tech-m3"
PROFILES = REPO / "tests" / "fixtures" / "cn" / "profile"

sys.path.insert(0, str(REPO))
from jobsearch_cn import material, profile, score, store, vocab  # noqa: E402

VOCABULARY = vocab.load()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


PROFILE = load(SAMPLE / "profile" / "profile.json")
MATERIAL = load(SAMPLE / "resume-1.json")


def bullet(text: str, refs=("exp-1",)) -> dict:
    """The sample material with its first bullet replaced."""
    data = copy.deepcopy(MATERIAL)
    data["experience"][0]["bullets"][0] = {"text": text, "refs": list(refs)}
    return data


def errors_of(data, profile_data=PROFILE) -> list:
    return material.validate(data, profile_data, VOCABULARY)[0]


class Sample(unittest.TestCase):
    def test_the_sample_profile_and_material_are_valid(self):
        self.assertEqual(profile.validate(PROFILE), [])
        self.assertEqual(material.validate(MATERIAL, PROFILE, VOCABULARY), ([], []))

    def test_the_sample_profile_is_the_tech_profile_with_ids(self):
        tech = load(PROFILES / "tech" / "profile.json")
        stripped = copy.deepcopy(PROFILE)
        for section in profile.OPTIONAL_ID_SECTIONS:
            for entry in stripped[section]:
                del entry["id"]
        self.assertEqual(stripped, tech)

    def test_the_sample_material_records_the_sample_profile(self):
        self.assertEqual(MATERIAL["profile_hash"], score.profile_hash(PROFILE))


class OptionalIds(unittest.TestCase):
    def test_the_m2_sample_profiles_stay_valid_without_ids(self):
        for name in ("tech", "ops"):
            with self.subTest(profile=name):
                self.assertEqual(profile.validate(load(PROFILES / name / "profile.json")), [])

    def test_an_id_follows_the_experience_rule(self):
        data = copy.deepcopy(PROFILE)
        data["awards"][0]["id"] = "Award 1"
        self.assertIn("awards[0].id: must be lowercase letters, digits and hyphens, like exp-1",
                      profile.validate(data))

    def test_ids_are_unique_across_sections(self):
        data = copy.deepcopy(PROFILE)
        data["certificates"][0]["id"] = "exp-1"
        self.assertIn("certificates[0].id: duplicate id 'exp-1'", profile.validate(data))

    def test_used_in_still_points_at_experience_only(self):
        data = copy.deepcopy(PROFILE)
        data["skills"][0]["used_in"] = ["edu-1"]
        self.assertTrue(any(error.startswith("skills[0].used_in") for error in profile.validate(data)))

    def test_citing_a_profile_without_ids_says_to_run_cn_setup(self):
        errors = errors_of(MATERIAL, load(PROFILES / "tech" / "profile.json"))
        self.assertTrue(any(error.startswith("education[0].ref: no profile entry with id 'edu-1'")
                            and "cn-setup" in error for error in errors), errors)


class Citations(unittest.TestCase):
    def assertError(self, data, expected: str):
        errors = errors_of(data)
        self.assertTrue(any(expected in error for error in errors), errors)

    def test_an_unknown_ref(self):
        data = copy.deepcopy(MATERIAL)
        data["awards"][0]["ref"] = "award-9"
        self.assertError(data, "awards[0].ref: no profile entry with id 'award-9'")

    def test_a_ref_into_another_section(self):
        data = copy.deepcopy(MATERIAL)
        data["awards"][0]["ref"] = "cert-1"
        self.assertError(data, "awards[0].ref: 'cert-1' is a certificates entry, not awards")

    def test_an_entry_listed_twice(self):
        data = copy.deepcopy(MATERIAL)
        data["awards"].append({"ref": "award-1"})
        self.assertError(data, "awards[1].ref: 'award-1' is listed twice")

    def test_a_bullet_must_cite_its_own_entry(self):
        self.assertError(bullet("基于 LangChain 和 MySQL 搭建课程资料问答", refs=["proj-1"]),
                         "experience[0].bullets[0].refs: must include 'exp-1'")

    def test_a_bullet_and_the_summary_must_cite_something(self):
        self.assertError(bullet("重构订单查询接口", refs=[]), "experience[0].bullets[0].refs: must cite at least one")
        data = copy.deepcopy(MATERIAL)
        data["summary"]["refs"] = []
        self.assertError(data, "summary.refs: must cite at least one")

    def test_a_course_the_entry_does_not_have(self):
        data = copy.deepcopy(MATERIAL)
        data["education"][1]["courses"] = ["机器学习"]
        self.assertError(data, "education[1].courses[0]: '机器学习' is not among this education entry's courses")

    def test_a_listed_skill_the_profile_does_not_have(self):
        data = copy.deepcopy(MATERIAL)
        data["skills"].append("Java")
        self.assertError(data, "skills[5]: 'Java' is not in the profile's skills")

    def test_a_listed_skill_twice(self):
        data = copy.deepcopy(MATERIAL)
        data["skills"].append("golang")  # same_as Go
        self.assertError(data, "skills[5]: duplicate of an earlier skill")

    def test_the_format(self):
        cases = {
            "schema_version": (2, "schema_version: must be 1"),
            "kind": ("greeting", "kind: must be one of resume"),
            "created": ("", "created: must be a non-empty string"),
            "extra": (1, "extra: unknown field"),
        }
        for key, (value, expected) in cases.items():
            with self.subTest(key=key):
                data = copy.deepcopy(MATERIAL)
                data[key] = value
                self.assertError(data, expected)
        data = copy.deepcopy(MATERIAL)
        del data["skills"]
        self.assertEqual(errors_of(data), ["skills: missing (use null, or [] for a list, when unknown)"])
        self.assertEqual(errors_of([]), ["material: must be a JSON object"])

    def test_a_text_too_long(self):
        self.assertError(bullet("重构订单查询接口" * 50), "experience[0].bullets[0].text: longer than")


class RewrittenText(unittest.TestCase):
    def test_numbers_from_the_cited_entries_pass_in_any_writing(self):
        # The source has 120ms, 45ms, 300 and (proj-1) 20.
        for text in ("P99 延迟从一百二十毫秒降到四十五毫秒", "覆盖 300 条测试问题", "覆盖三百条测试问题"):
            with self.subTest(text=text):
                self.assertEqual(errors_of(bullet(text)), [])

    def test_a_number_not_in_the_cited_entries_fails(self):
        for text, quote in (("P99 延迟降低 62%", "62%"), ("延迟降低六成", "六成"), ("查询快了三倍", "三倍"),
                            ("日均处理两万次查询", "两万"), ("延迟降低百分之三十", "百分之三十"),
                            ("覆盖 1,200 条测试问题", "1,200"), ("覆盖 2万 条测试问题", "2万")):
            with self.subTest(text=text):
                self.assertTrue(any(f"the number {quote!r} is not in the cited entries (exp-1)" in error
                                    for error in errors_of(bullet(text))), errors_of(bullet(text)))

    def test_a_number_from_an_entry_not_cited_fails(self):
        # 20 is in proj-1, which this bullet does not cite; citing it too makes it pass.
        self.assertTrue(errors_of(bullet("支持 20 门课程的资料检索")))
        self.assertEqual(errors_of(bullet("支持 20 门课程的资料检索", refs=["exp-1", "proj-1"])), [])

    def test_a_skill_beyond_the_profile_fails(self):
        self.assertTrue(any("the skill 'Kubernetes' is neither in the profile's skills nor in the cited entries"
                            in error for error in errors_of(bullet("用 Go 重构订单查询接口并部署到 Kubernetes"))))
        data = copy.deepcopy(MATERIAL)
        data["summary"]["text"] = "熟悉 Java 后端开发"
        self.assertTrue(any(error.startswith("summary.text: the skill 'Java'") for error in errors_of(data)))

    def test_a_skill_from_the_profile_passes(self):
        self.assertEqual(errors_of(bullet("用 Go 重构订单查询接口，镜像用 Docker 打包")), [])


class Numbers(unittest.TestCase):
    def values(self, text: str) -> list:
        return [value for _, value in material.numbers(text)]

    def test_figures(self):
        self.assertEqual(self.values("P99 从 120ms 降到 45.5ms，提升 62%，覆盖 1,200 条、2万 次"),
                         [99, 120, Fraction("45.5"), 62, 1200, 20000])

    def test_chinese(self):
        self.assertEqual(self.values("一百二十、三十、两万、百分之六十二、六成、三倍、两千万"),
                         [120, 30, 20000, 62, 60, 3, 20_000_000])

    def test_figures_and_chinese_compare_as_values(self):
        self.assertEqual(self.values("62%"), self.values("百分之六十二"))
        self.assertEqual(self.values("2万"), self.values("两万"))
        self.assertEqual(self.values("60%"), self.values("六成"))

    def test_words_with_numerals_are_not_numbers(self):
        for text in ("统一接口", "一线城市", "三方支付", "百度", "十分熟悉", "千兆网络", "万一失败"):
            with self.subTest(text=text):
                self.assertEqual(material.numbers(text), [])


class Warnings(unittest.TestCase):
    def test_a_changed_profile(self):
        data = copy.deepcopy(PROFILE)
        data["experience"][0]["end"] = "2026-09"
        errors, warnings = material.validate(MATERIAL, data, VOCABULARY)
        self.assertEqual(errors, [])
        self.assertIn("profile_hash: the profile has changed since this material was written; check it still holds",
                      warnings)

    def test_a_proficient_skill_left_out(self):
        data = copy.deepcopy(MATERIAL)
        data["skills"].remove("Go")
        self.assertEqual(material.validate(data, PROFILE, VOCABULARY)[1],
                         ["skills: 'Go' is proficient in the profile but not listed"])

    def test_a_jd_skill_the_profile_has_but_the_material_leaves_out(self):
        job = {"requirements": {"skills": ["Docker", "Java"]}}
        self.assertEqual(material.validate(MATERIAL, PROFILE, VOCABULARY, job)[1],
                         ["skills: the JD asks for 'Docker', which the profile has, but it is not listed"])

    def test_no_warnings_while_there_are_errors(self):
        data = copy.deepcopy(MATERIAL)
        data["skills"] = ["Java"]
        self.assertEqual(material.validate(data, PROFILE, VOCABULARY)[1], [])


def run_cli(*args, data_dir):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", **{store.DATA_DIR_ENV: str(data_dir)})
    return subprocess.run([sys.executable, "-m", "jobsearch_cn", *args], cwd=REPO, env=env, capture_output=True)


class Command(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name)
        shutil.copytree(SAMPLE / "profile", self.data / "profile")
        self.file = self.data / "resume-1.json"

    def validate(self, data) -> subprocess.CompletedProcess:
        self.file.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False),
                             encoding="utf-8")
        return run_cli("material", "validate", str(self.file), data_dir=self.data)

    def test_a_valid_material(self):
        proc = self.validate(MATERIAL)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8"))
        self.assertEqual(json.loads(proc.stdout), {"valid": True, "errors": [], "warnings": []})

    def test_an_invalid_material_lists_the_errors(self):
        proc = self.validate(bullet("延迟降低六成"))
        self.assertEqual(proc.returncode, 1)
        result = json.loads(proc.stdout)
        self.assertFalse(result["valid"])
        self.assertIn("experience[0].bullets[0].text: the number '六成'", result["errors"][0])

    def test_unreadable_input_exits_2(self):
        self.assertEqual(self.validate("{not json").returncode, 2)
        self.assertEqual(run_cli("material", "validate", str(self.data / "absent.json"),
                                 data_dir=self.data).returncode, 2)
        shutil.rmtree(self.data / "profile")
        self.assertEqual(self.validate(MATERIAL).returncode, 2)

    def test_a_stored_job_adds_its_warnings_and_a_malformed_job_id_is_skipped(self):
        job = {"requirements": {"skills": ["Docker"]}}
        jobs = self.data / "jobs"
        jobs.mkdir()
        # Stored by hand: the warnings read only requirements.skills.
        (jobs / f"{MATERIAL['job_id']}.json").write_text(json.dumps(job), encoding="utf-8")
        result = json.loads(self.validate(MATERIAL).stdout)
        self.assertEqual(result["warnings"],
                         ["skills: the JD asks for 'Docker', which the profile has, but it is not listed"])
        data = copy.deepcopy(MATERIAL)
        data["job_id"] = "../not-an-id"
        self.assertEqual(self.validate(data).returncode, 0)


if __name__ == "__main__":
    unittest.main()
