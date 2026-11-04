"""Tests for jobsearch_cn/material.py, the optional profile ids and `material validate` (M3-1).

A material may only choose, order and reword what the profile holds, so these pin: the sample material
passes; each way of citing what is not there fails with the path and the reason (a missing or id-less entry,
the wrong section, a bullet that does not cite its own entry, a course or skill the profile lacks); a rewrite
cannot add a number, written in figures or in Chinese (三倍, 六成, 两万, 百分之三十), nor a skill; the
warnings; the exit codes; and that the ids are optional, so the M2 sample profiles stay valid unchanged.
The summary may also cite notes.md (M3-2c): checked against its text but for the 偏好记录 section, refused
when there is no notes.md or a bullet cites it, and warned about past two lines.
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
from jobsearch_cn import material, messages, profile, score, store, vocab  # noqa: E402

VOCABULARY = vocab.load()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


PROFILE = load(SAMPLE / "profile" / "profile.json")
MATERIAL = load(SAMPLE / "resume-1.json")
NOTES = (SAMPLE / "profile" / "notes.md").read_text(encoding="utf-8")
# Appended to the sample notes: a preference log, as profile.md §4 shows it, and a section after it.
PREFERENCES = """
## 偏好记录

- 2026-10-30 · `target.weights` → {"skills": 25, "direction": 25, "experience": 20, "salary": 10, "location": 20} · 来源：user（用户确认）

### 补记

- 2026-10-31 · `availability.days_per_week` → 5 · 来源：user（"可以每周 5 天"）
"""


def summary(text: str, refs=("notes.md",)) -> dict:
    """The sample material with its summary replaced."""
    data = copy.deepcopy(MATERIAL)
    data["summary"] = {"text": text, "refs": list(refs)}
    return data


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
            "created": ("", "created: must be an ISO 8601 time with a UTC offset"),
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

    def test_created_must_be_a_real_time_with_an_offset(self):
        for value in ("not-a-time", "2026-13-99", "2026-11-01T25:00:00+08:00", "2026-11-01T10:00:00", None, 20261101):
            with self.subTest(created=value):
                data = copy.deepcopy(MATERIAL)
                data["created"] = value
                self.assertError(data, "created: must be an ISO 8601 time with a UTC offset")
        for value in ("2026-11-01T10:00:00+08:00", "2026-11-01T02:00:00Z"):
            with self.subTest(created=value):
                data = copy.deepcopy(MATERIAL)
                data["created"] = value
                self.assertEqual(errors_of(data), [])


class RewrittenText(unittest.TestCase):
    def test_numbers_from_the_cited_entries_pass_in_any_writing(self):
        # The source has 120ms, 45ms, 300 and (proj-1) 20.
        for text in ("P99 延迟从一百二十毫秒降到四十五毫秒", "覆盖 300 条测试问题", "覆盖三百条测试问题"):
            with self.subTest(text=text):
                self.assertEqual(errors_of(bullet(text)), [])

    def test_a_number_not_in_the_cited_entries_fails(self):
        for text, quote in (("P99 延迟降低 62%", "62%"), ("延迟降低六成", "六成"), ("查询快了三倍", "三倍"),
                            ("日均处理两万次查询", "两万"), ("延迟降低百分之三十", "百分之三十"),
                            ("覆盖 1,200 条测试问题", "1,200"), ("覆盖 2万 条测试问题", "2万"),
                            ("处理一百零二个请求", "一百零二"), ("处理一千零二十个请求", "一千零二十"),
                            ("日均一亿二千万次查询", "一亿二千万"), ("于二〇二六年上线", "二〇二六")):
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


class SummaryFromNotes(unittest.TestCase):
    """A summary may rest on what the user said while building the profile, kept in notes.md."""

    def errors(self, data, notes=NOTES) -> list:
        return material.validate(data, PROFILE, VOCABULARY, notes=notes)[0]

    def test_notes_alone_is_enough(self):
        self.assertEqual(self.errors(summary("计算机硕士在读，有后端和大模型应用的实习与项目经验")), [])

    def test_notes_with_entries(self):
        self.assertEqual(self.errors(summary("计算机硕士在读，做过 RAG 问答服务的检索评测", ["notes.md", "exp-1"])), [])

    def test_citing_notes_without_a_notes_file_fails(self):
        self.assertEqual(self.errors(summary("计算机硕士在读"), notes=None),
                         ["summary.refs[0]: cites notes.md, but there is no notes.md beside the profile that reads "
                          "as UTF-8 text"])

    def test_a_bullet_may_not_cite_notes(self):
        data = bullet("用 Go 重构订单查询接口", refs=["exp-1", "notes.md"])
        self.assertEqual(self.errors(data), ["experience[0].bullets[0].refs[1]: only the summary may cite notes.md"])

    def test_notes_cited_twice(self):
        self.assertEqual(self.errors(summary("计算机硕士在读", ["notes.md", "notes.md"])),
                         ["summary.refs[1]: notes.md is cited twice"])

    def test_numbers_must_be_in_the_notes(self):
        self.assertEqual(self.errors(summary("把接口的 P99 延迟从一百二十毫秒降到 45ms")), [])
        self.assertTrue(any("the number '30' is not in the cited entries (notes.md)" in error
                            for error in self.errors(summary("把接口的 P99 延迟降到 30ms"))))

    def test_skills_must_be_in_the_notes_or_the_profile(self):
        self.assertTrue(any(error.startswith("summary.text: the skill 'Kubernetes'")
                            for error in self.errors(summary("会用 Kubernetes 部署服务"))))
        notes = NOTES + "\n实习时学会了用 Kubernetes 部署服务。\n"
        self.assertEqual(self.errors(summary("会用 Kubernetes 部署服务"), notes=notes), [])
        # Said in the notes, but the summary cites only an entry.
        self.assertTrue(self.errors(summary("会用 Kubernetes 部署服务", ["exp-1"]), notes=notes))

    def test_the_preference_log_is_no_evidence(self):
        notes = NOTES + PREFERENCES
        for text in ("带过 25 人的团队", "每周可以到岗 5 天"):  # 25 in the log, 5 in a subsection of it
            with self.subTest(text=text):
                self.assertTrue(any("is not in the cited entries (notes.md)" in error
                                    for error in self.errors(summary(text), notes=notes)))
        # A heading of the log's level or above ends it.
        notes += "\n## 社团\n\n带过 25 人的社团。\n"
        self.assertEqual(self.errors(summary("带过 25 人的社团"), notes=notes), [])

    def test_evidence_keeps_everything_but_the_log(self):
        kept = material.evidence(NOTES + PREFERENCES + "\n# 其他\n\n正文")
        self.assertIn("P99 延迟从 120ms 降到 45ms", kept)
        self.assertIn("# 其他\n\n正文", kept)
        for gone in ("偏好记录", "target.weights", "补记", "days_per_week"):
            self.assertNotIn(gone, kept)

    def test_a_heading_in_a_code_block_does_not_end_the_log(self):
        # Codex B's #115 review, P2: a "## 示例" inside a fence was read as a heading of the log's level.
        log = "\n- 2026-11-02 · `target.weights` → {\"skills\": 73} · 来源：user（用户确认）\n"
        for fenced in ("```text\n## 示例\n```", "~~~\n# 示例\n~~~", "````\n## 示例\n```\n## 示例\n````",
                       "  ```\n## 示例\n  ```"):
            notes = NOTES + "\n## 偏好记录\n" + fenced + log
            with self.subTest(fenced=fenced):
                self.assertTrue(any("the number '73' is not in the cited entries (notes.md)" in error
                                    for error in self.errors(summary("做过73次评测"), notes=notes)))
                self.assertNotIn("73", material.evidence(notes))
                # A real heading of the log's level right after the block still ends it.
                after = notes + "## 评测\n\n做过73次评测。\n"
                self.assertEqual(self.errors(summary("做过73次评测"), notes=after), [])

    def test_a_code_block_outside_the_log_is_evidence(self):
        notes = NOTES + "\n```text\n## 偏好记录\n做过73次评测\n```\n"
        self.assertEqual(self.errors(summary("做过73次评测"), notes=notes), [])

    def test_only_an_atx_heading_ends_the_log(self):
        # The planner's boundary after the #115 review: at most three spaces, 1-6 #, then a space or the end.
        log = "\n- 2026-11-02 · `target.weights` → {\"skills\": 73} · 来源：user（用户确认）\n"
        for line in ("    ## 示例", "#示例", "##示例", "<!--\n## 示例\n-->", "<!-- 注释\n# 示例 -->",
                     "\t## 示例"):
            notes = NOTES + "\n## 偏好记录\n" + line + log
            with self.subTest(line=line):
                self.assertNotIn("73", material.evidence(notes))
                self.assertTrue(any("the number '73' is not in the cited entries (notes.md)" in error
                                    for error in self.errors(summary("做过73次评测"), notes=notes)))
        for heading in ("## 评测", " ## 评测", "  ## 评测", "   ## 评测", "## 评测 ##", "#", "##"):
            notes = NOTES + "\n## 偏好记录\n- `target.weights` → {\"skills\": 25}\n" + heading + "\n做过73次评测。\n"
            with self.subTest(heading=heading):
                self.assertEqual(self.errors(summary("做过73次评测"), notes=notes), [])
                self.assertNotIn("25", material.evidence(notes))

    def test_the_log_heading_itself_follows_the_same_rule(self):
        for heading, is_log in (("   ## 偏好记录", True), ("## 偏好记录 ##", True), ("    ## 偏好记录", False),
                                ("#偏好记录", False), ("<!--\n## 偏好记录\n-->", False)):
            with self.subTest(heading=heading):
                kept = material.evidence(heading + "\n- `target.weights` → {\"skills\": 25}\n")
                self.assertEqual("25" not in kept, is_log)

    def test_a_comment_on_one_line_ends_where_it_starts(self):
        notes = NOTES + "\n## 偏好记录\n<!-- 只追加 -->\n- {\"skills\": 25}\n## 评测\n做过73次评测\n"
        kept = material.evidence(notes)
        self.assertNotIn("25", kept)
        self.assertIn("做过73次评测", kept)

    def test_the_hash_leaves_the_notes_out(self):
        # Ruling 4: notes.md is not in profile_hash, so changing it alone warns of nothing; the checks above
        # run again on every build instead.
        errors, warnings = material.validate(summary("计算机硕士在读"), PROFILE, VOCABULARY,
                                             notes=NOTES + "\n补一句。\n")
        self.assertEqual((errors, warnings), ([], []))


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

    def test_chinese_with_zeros_and_two_magnitudes(self):
        cases = {"一百零二": 102, "一千零二十": 1020, "一亿二千万": 120_000_000, "三十万零五": 300_005,
                 "一万二": 12000, "三百五": 350, "一万零二": 10002, "二〇二六": 2026, "两千万": 20_000_000}
        for text, value in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.values(text), [value])

    def test_qianwan_before_an_imperative_is_no_number(self):
        for text in ("千万不要改数字", "千万别漏写", "千万要核对", "千万记得核对", "千万记住", "千万务必核对",
                     "千万莫改", "千万勿改", "千万注意", "千万小心", "千万当心"):
            with self.subTest(text=text):
                self.assertEqual(material.numbers(text), [])
        # The words, not their first character: 记录 and 务工 do not make 千万 an imperative.
        for text in ("处理千万记录", "服务千万务工人员", "千万级用户", "日活过千万", "千万得到"):
            with self.subTest(text=text):
                self.assertEqual(self.values(text), [10_000_000])

    def test_words_with_numerals_are_not_numbers(self):
        for text in ("统一接口", "一线城市", "三方支付", "百度", "十分熟悉", "千兆网络", "万一失败", "零基础",
                     "亿万网民"):
            with self.subTest(text=text):
                self.assertEqual(material.numbers(text), [])


class Warnings(unittest.TestCase):
    def test_a_changed_profile(self):
        data = copy.deepcopy(PROFILE)
        data["experience"][0]["end"] = "2026-09"
        errors, warnings = material.validate(MATERIAL, data, VOCABULARY)
        self.assertEqual(errors, [])
        # With the current value, which no command prints on its own (P3 after #115).
        current = score.profile_hash(data)
        self.assertNotEqual(current, MATERIAL["profile_hash"])
        self.assertIn("profile_hash: the profile has changed since this material was written; check it still holds "
                      f"(the current value is {current})", warnings)

    def test_a_message_gets_the_same_warning(self):
        # material validate checks greetings, emails and referrals too (messages.py); they warn alike.
        greeting = load(SAMPLE / "greeting-1.json")
        data = copy.deepcopy(PROFILE)
        data["skills"][0]["level"] = "expert"
        errors, warnings = messages.validate(greeting, data, VOCABULARY, load(SAMPLE / "job.json"),
                                             messages.load_templates(), messages.load_banned())
        self.assertEqual(errors, [])
        self.assertEqual(warnings[0], "profile_hash: the profile has changed since this material was written; "
                                      f"check it still holds (the current value is {score.profile_hash(data)})")

    def test_no_warning_while_the_profile_is_unchanged(self):
        self.assertEqual(material._profile_changed(MATERIAL, PROFILE), None)
        self.assertEqual(material._profile_changed({**MATERIAL, "profile_hash": None}, PROFILE), None)

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

    def test_width_counts_half_width_characters_as_half(self):
        self.assertEqual(material.width("Go 和 Python"), 6)
        self.assertEqual(material.width("熟悉（RAG），P99"), 8)

    def test_a_summary_past_two_lines(self):
        self.assertEqual(material.validate(summary("简" * 88, ["exp-1"]), PROFILE, VOCABULARY), ([], []))
        self.assertEqual(material.validate(summary("简" * 88 + "a", ["exp-1"]), PROFILE, VOCABULARY),
                         ([], ["summary.text: about 88.5 characters wide, more than the two lines (88) a summary "
                               "should take; shorten it"]))
        # Past the 300-character limit it is an error, not a warning.
        self.assertIn("summary.text: longer than 300 characters", errors_of(summary("简" * 301, ["exp-1"])))


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

    def test_the_profile_hash_warning_gives_the_value_to_copy(self):
        # A draft whose profile_hash is not the current one: the warning says what to write, and once written
        # it goes away. Still a warning, so the exit code stays 0.
        data = copy.deepcopy(MATERIAL)
        data["profile_hash"] = "0" * 64
        proc = self.validate(data)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8"))
        [warning] = json.loads(proc.stdout)["warnings"]
        head, _, current = warning.partition(" (the current value is ")
        self.assertEqual(head, "profile_hash: the profile has changed since this material was written; "
                               "check it still holds")
        self.assertEqual(current, score.profile_hash(PROFILE) + ")")
        data["profile_hash"] = current[:-1]
        self.assertEqual(json.loads(self.validate(data).stdout), {"valid": True, "errors": [], "warnings": []})

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

    def test_the_notes_beside_the_profile_are_read(self):
        data = summary("计算机硕士在读，有后端和大模型应用的实习与项目经验")
        self.assertEqual(json.loads(self.validate(data).stdout)["errors"], [])
        (self.data / "profile" / "notes.md").write_bytes("计算机硕士在读".encode("gbk"))
        self.assertIn("summary.refs[0]: cites notes.md", json.loads(self.validate(data).stdout)["errors"][0])
        (self.data / "profile" / "notes.md").unlink()
        self.assertIn("summary.refs[0]: cites notes.md", json.loads(self.validate(data).stdout)["errors"][0])
        # A summary that does not cite notes.md does not need it.
        self.assertEqual(self.validate(MATERIAL).returncode, 0)

    def test_a_fenced_heading_in_the_log_lets_no_number_through(self):
        # The #115 review's reproduction, end to end.
        (self.data / "profile" / "notes.md").write_text(
            "## 偏好记录\n```text\n## 示例\n```\n"
            "- 2026-11-02 · `target.weights` → {\"skills\": 73} · 来源：user（用户确认）\n", encoding="utf-8")
        proc = self.validate(summary("做过73次评测"))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("the number '73'", json.loads(proc.stdout)["errors"][0])


if __name__ == "__main__":
    unittest.main()
