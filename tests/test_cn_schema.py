"""Tests for jobsearch_cn/schema.py and `python -m jobsearch_cn jd validate`.

The schema is the contract between the rule parser, the agents that complete a
record and the local store, so these pin both halves of it: the shape (every
key present, null and [] for "not stated", enums, ranges) and the evidence
rule that keeps a model from inventing a field - every value must cite text
that really occurs in the JD.
"""
import codecs
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "cn" / "job-schema.md"

sys.path.insert(0, str(REPO))
from jobsearch_cn import schema  # noqa: E402

ZERO_WIDTH_SPACE = chr(0x200B)


def doc_example() -> dict:
    """The example record in docs/cn/job-schema.md (its first json block)."""
    match = re.search(r"```json\n(.*?)\n```", DOC.read_text(encoding="utf-8"), re.S)
    return json.loads(match.group(1))


def minimal_record() -> dict:
    """A valid record that states almost nothing: a title, cited by rule."""
    return {
        "schema_version": 1,
        "id": "job_0123456789ab",
        "source": {"type": "paste", "site": None, "url": None, "imported_at": "2026-10-27T10:00:00+08:00"},
        "title": "后端开发实习生",
        "company": None,
        "cities": [],
        "remote": None,
        "employment_type": None,
        "salary": None,
        "requirements": {
            "graduation": None, "days_per_week": None, "min_months": None, "education": None, "skills": [],
            "skill_alternatives": [], "start": None,
        },
        "interview": None,
        "return_offer": None,
        "published_at": None,
        "deadline": None,
        "status": "new",
        "evidence": {"title": {"text": "后端开发实习生", "method": "rule"}},
        "guard": None,
        "raw_text": "后端开发实习生\n负责服务端接口开发。",
    }


def with_value(record: dict, path: str, value) -> dict:
    """Set a dotted field path on a record and return the record."""
    *parents, last = path.split(".")
    target = record
    for part in parents:
        target = target[part]
    target[last] = value
    return record


def fullwidth(text: str) -> str:
    """ASCII as its fullwidth forms, the way some JDs are typed."""
    return "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in text)


def salary(low=None, high=None, unit=None, months=None, negotiable=False) -> dict:
    return {"min": low, "max": high, "unit": unit, "months": months, "negotiable": negotiable}


class SchemaCase(unittest.TestCase):
    def assert_valid(self, record):
        self.assertEqual(schema.validate(record), [])

    def assert_error(self, record, prefix):
        errors = schema.validate(record)
        self.assertTrue(
            any(error.startswith(prefix) for error in errors),
            f"no error starting with {prefix!r} in {errors}",
        )
        return errors

    def cited(self, path: str, value, text: str, method: str = "rule") -> dict:
        """A minimal record holding one more value, cited by text appended to the JD."""
        record = with_value(minimal_record(), path, value)
        record["raw_text"] += "\n" + text
        record["evidence"][path] = {"text": text, "method": method}
        return record


class DocumentedSchema(SchemaCase):
    def test_doc_example_is_valid(self):
        self.assert_valid(doc_example())

    def test_doc_names_every_field_and_value(self):
        text = DOC.read_text(encoding="utf-8")
        names = list(schema.TOP_LEVEL_KEYS)
        for prefix, keys in (
            ("source", schema.SOURCE_KEYS),
            ("salary", schema.SALARY_KEYS),
            ("requirements", schema.REQUIREMENT_KEYS),
            ("requirements.graduation", schema.GRADUATION_KEYS),
            ("requirements.education", schema.EDUCATION_KEYS),
            ("requirements.start", schema.START_KEYS),
            ("interview", schema.INTERVIEW_KEYS),
            ("guard", schema.GUARD_KEYS),
        ):
            names += [f"{prefix}.{key}" for key in keys]
        names += [
            *schema.SOURCE_TYPES, *schema.SITES, *schema.EMPLOYMENT_TYPES, *schema.SALARY_UNITS,
            *schema.EDUCATION_LEVELS, *schema.STATUSES, *schema.EVIDENCE_METHODS,
            *schema.GUARD_VERDICTS, *schema.EVIDENCE_FIELDS, *schema.INTERVIEW_MODES,
        ]
        missing = [name for name in names if f"`{name}`" not in text]
        self.assertEqual(missing, [], "docs/cn/job-schema.md is out of step with jobsearch_cn/schema.py")


class Shape(SchemaCase):
    def test_minimal_record_is_valid(self):
        self.assert_valid(minimal_record())

    def test_record_must_be_an_object(self):
        self.assertEqual(schema.validate([minimal_record()]), ["record: must be a JSON object"])

    def test_missing_key_names_its_path(self):
        record = minimal_record()
        del record["requirements"]["skills"]
        self.assert_error(record, "requirements.skills: missing")

    def test_unknown_key_is_rejected(self):
        record = minimal_record()
        record["compnay"] = "示例科技"
        self.assert_error(record, "compnay: unknown field")

    def test_schema_version_and_id(self):
        for path, value in (("schema_version", 2), ("schema_version", True), ("id", "job_XYZ"), ("id", 42)):
            with self.subTest(path=path, value=value):
                self.assert_error(with_value(minimal_record(), path, value), f"{path}: must be")

    def test_an_id_with_anything_around_it_is_invalid(self):
        # V18 P3-1: "$" with re.match let a trailing newline through; the store uses the same check.
        for value in ("job_123456789abc\n", "job_123456789abc\r", "job_123456789abc\r\n", " job_123456789abc",
                      "job_123456789abc ", "job_123456789abc/x", "../job_123456789abc", "job_12345678\\abc"):
            with self.subTest(value=value):
                self.assertFalse(schema.is_job_id(value))
                self.assert_error(with_value(minimal_record(), "id", value), "id: must be")
        self.assertTrue(schema.is_job_id("job_123456789abc"))

    def test_enum_fields(self):
        for path, value in (
            ("employment_type", "intern"), ("status", None), ("source.site", "weibo"), ("source.type", None),
        ):
            with self.subTest(path=path):
                self.assert_error(with_value(minimal_record(), path, value), f"{path}: must be one of")

    def test_whole_numbers_reject_booleans_and_out_of_range_values(self):
        for path, value in (
            ("requirements.days_per_week", True), ("requirements.days_per_week", 8), ("requirements.min_months", 0),
        ):
            with self.subTest(path=path, value=value):
                self.assert_error(with_value(minimal_record(), path, value), f"{path}: must be null or a whole number")

    def test_dates_are_real_calendar_dates(self):
        for value in ("2026/10/27", "2026-02-30", "27.10.2026", 20261027):
            with self.subTest(value=value):
                self.assert_error(
                    with_value(minimal_record(), "published_at", value), "published_at: must be null or a date"
                )

    def test_imported_at_needs_a_utc_offset(self):
        self.assert_error(
            with_value(minimal_record(), "source.imported_at", "2026-10-27T10:00:00"), "source.imported_at: must be"
        )
        self.assert_valid(with_value(minimal_record(), "source.imported_at", "2026-10-27T02:00:00Z"))

    def test_url_sources_need_an_http_url(self):
        record = with_value(minimal_record(), "source.type", "url")
        self.assert_error(record, "source.url: required")
        self.assert_error(with_value(record, "source.url", "ftp://example.com/job"), "source.url: must be null or an http")
        self.assert_valid(with_value(record, "source.url", "https://jobs.example.com/123"))

    def test_lists_are_never_null(self):
        self.assert_error(with_value(minimal_record(), "cities", None), "cities: must be a list")

    def test_list_items_are_unique_ignoring_case_and_width(self):
        record = self.cited("requirements.skills", ["Python", fullwidth("python")], "熟悉Python")
        self.assert_error(record, "requirements.skills[1]: duplicate")

    def test_raw_text_is_required_and_bounded(self):
        self.assert_error(with_value(minimal_record(), "raw_text", " \n "), "raw_text: must be the non-empty")
        too_long = "后端开发实习生" + "x" * schema.MAX_RAW_TEXT
        self.assert_error(with_value(minimal_record(), "raw_text", too_long), "raw_text: longer than")


class Salary(SchemaCase):
    def test_monthly_range_with_extra_months(self):
        self.assert_valid(self.cited("salary", salary(10000, 15000, "CNY/month", months=14), "10-15K·14薪"))

    def test_negotiable_needs_no_amount(self):
        self.assert_valid(self.cited("salary", salary(negotiable=True), "薪资面议"))

    def test_fixed_salary_needs_an_amount_and_a_unit(self):
        record = self.cited("salary", salary(), "薪资待遇优厚")
        self.assert_error(record, "salary: give min or max")
        self.assert_error(record, "salary.unit: required unless negotiable")

    def test_min_is_not_above_max(self):
        self.assert_error(
            self.cited("salary", salary(300, 200, "CNY/day"), "200-300元/天"), "salary.min: greater than salary.max"
        )

    def test_months_only_with_monthly_pay(self):
        self.assert_error(
            self.cited("salary", salary(200, 300, "CNY/day", months=13), "200-300元/天"),
            "salary.months: only used with unit CNY/month",
        )

    def test_amounts_are_positive_numbers(self):
        for value in ("200", True, -1, 0, float("nan")):
            with self.subTest(value=value):
                self.assert_error(
                    self.cited("salary", salary(value, 300, "CNY/day"), "200-300元/天"),
                    "salary.min: must be null or a positive number",
                )


class Requirements(SchemaCase):
    def test_graduation_years_must_be_listed(self):
        self.assert_error(
            self.cited("requirements.graduation", {"years": [], "strict": True}, "2027届"),
            "requirements.graduation.years: must be",
        )

    def test_graduation_strictness_is_explicit(self):
        self.assert_error(
            self.cited("requirements.graduation", {"years": [2027]}, "2027届优先"),
            "requirements.graduation.strict: missing",
        )

    def test_preferred_education_is_not_below_the_minimum(self):
        self.assert_error(
            self.cited("requirements.education", {"min": "master", "preferred": "bachelor"}, "硕士及以上"),
            "requirements.education.preferred: lower than",
        )

    def test_education_with_no_level_should_be_null(self):
        self.assert_error(
            self.cited("requirements.education", {"min": None, "preferred": None}, "学历不限"),
            "requirements.education: use null",
        )

    def test_no_minimum_is_a_stated_minimum_only(self):
        # "none" says the JD rules out no one by degree; a preferred degree is still a degree.
        record = self.cited("requirements.education", {"min": "none", "preferred": "master"}, "学历不限，硕士优先")
        self.assertEqual(schema.validate(record), [])
        self.assert_error(
            self.cited("requirements.education", {"min": "bachelor", "preferred": "none"}, "本科及以上"),
            "requirements.education.preferred: must be one of",
        )


class SkillAlternatives(SchemaCase):
    """H16: groups of skills the JD offers a choice between."""

    CLAUSE = "熟悉 Golang 或 Java，了解 Docker"

    def chosen(self, groups, text=None, method="rule") -> dict:
        record = self.cited("requirements.skills", ["Golang", "Java", "Docker"], self.CLAUSE, method=method)
        record["requirements"]["skill_alternatives"] = groups
        record["evidence"]["requirements.skill_alternatives"] = {"text": text or "熟悉 Golang 或 Java", "method": method}
        return record

    def test_a_cited_group_of_listed_skills_is_valid(self):
        self.assert_valid(self.chosen([["Golang", "Java"]]))
        self.assert_valid(self.chosen([["golang", "ＪＡＶＡ"]], method="agent"))  # compared as skills are

    def test_a_list_of_groups_of_two_or_more(self):
        for groups, error in ((None, "must be a list of skill groups"), ([["Golang"]], "at least two skills"),
                              (["Golang"], "at least two skills"), ([["Golang", "golang"]], "duplicate"),
                              ([["Golang", ""]], "non-empty string")):
            with self.subTest(groups=groups):
                self.assert_error(self.chosen(groups), "requirements.skill_alternatives")
                self.assertTrue(any(error in e for e in schema.validate(self.chosen(groups))), error)

    def test_every_grouped_skill_is_listed_and_in_one_group(self):
        self.assert_error(self.chosen([["Golang", "Rust"]], text=self.CLAUSE),
                          "requirements.skill_alternatives[0]: 'Rust' is not in requirements.skills")
        self.assert_error(self.chosen([["Golang", "Java"], ["Java", "Docker"]], text=self.CLAUSE),
                          "requirements.skill_alternatives[1]: 'Java' is already in an earlier group")

    def test_a_group_needs_evidence_offering_it_as_one_choice(self):
        record = self.chosen([["Golang", "Java"]])
        del record["evidence"]["requirements.skill_alternatives"]
        self.assert_error(record, "requirements.skill_alternatives: has a value but no evidence")
        # Each skill is cited, but not as a choice: the choice is not shown to be the JD's.
        self.assert_error(self.chosen([["Golang", "Docker"]], text=["熟悉 Golang", "了解 Docker"]),
                          "evidence.requirements.skill_alternatives: no snippets offer Golang / Docker as one choice")
        self.assert_valid(self.chosen([["Golang", "Docker"]], text=self.CLAUSE))

    def test_snippets_that_overlap_offer_a_merged_choice(self):
        # "熟悉 Python 或 Java；熟悉 Java 或 Go": two snippets, linked by Java (Codex B's P2-2 on #59).
        text = "熟悉 Python 或 Java；熟悉 Java 或 Go；了解 Docker、Kubernetes"
        record = self.cited("requirements.skills", ["Python", "Java", "Go", "Docker", "Kubernetes"], text, "agent")
        record["requirements"]["skill_alternatives"] = [["Python", "Java", "Go"]]
        record["evidence"]["requirements.skill_alternatives"] = {"text": ["熟悉 Python 或 Java", "熟悉 Java 或 Go"],
                                                                 "method": "agent"}
        self.assert_valid(record)
        # Two choices that share no skill are not one: Docker、Kubernetes is no link to Python, Java, Go.
        record["requirements"]["skill_alternatives"] = [["Python", "Java", "Docker", "Kubernetes"]]
        record["evidence"]["requirements.skill_alternatives"]["text"] = ["熟悉 Python 或 Java", "了解 Docker、Kubernetes"]
        self.assert_error(record, "evidence.requirements.skill_alternatives: no snippets offer")

    def test_upgrade_adds_the_field_to_an_older_record(self):
        record = minimal_record()
        del record["requirements"]["skill_alternatives"]
        self.assert_error(record, "requirements.skill_alternatives: missing")
        self.assert_valid(schema.upgrade(record))
        self.assertEqual(schema.upgrade([1]), [1])  # not a record: left for validate to report


class InterviewAndStart(SchemaCase):
    """M2-6c: how the JD interviews, and when it wants you to start."""

    def test_an_interview_online_in_person_or_both(self):
        for mode, cities, text in (("online", [], "视频面试"), ("onsite", ["北京"], "面试地点：北京"),
                                   ("either", ["北京"], "面试地点：北京，也可视频面试"), ("mixed", [], "一面视频，二面现场面试")):
            with self.subTest(mode=mode):
                self.assert_valid(self.cited("interview", {"mode": mode, "cities": cities}, text))

    def test_an_interview_needs_a_known_mode_and_no_city_when_online(self):
        for value, error in (({"mode": None, "cities": []}, "interview.mode: must be one of"),
                             ({"mode": "video", "cities": []}, "interview.mode: must be one of"),
                             ({"mode": "online", "cities": ["北京"]}, "interview.cities: an online interview has no city"),
                             ({"mode": "onsite"}, "interview.cities: missing"),
                             ("现场", "interview: must be null or an object")):
            with self.subTest(value=value):
                self.assert_error(self.cited("interview", value, "面试地点：北京"), error)

    def test_each_interview_city_appears_in_the_evidence(self):
        record = self.cited("interview", {"mode": "onsite", "cities": ["北京", "上海"]}, "面试地点：北京")
        self.assert_error(record, "evidence.interview: '上海' does not appear in its evidence text")

    def test_a_start_by_a_date_or_as_soon_as_possible(self):
        for value, text in (({"by": "2026-11-01", "asap": False}, "11月1日前到岗"),
                            ({"by": None, "asap": True}, "能尽快到岗"),
                            ({"by": "2026-11-01", "asap": True}, "尽快到岗，最晚11月1日前到岗")):
            with self.subTest(value=value):
                self.assert_valid(self.cited("requirements.start", value, text))

    def test_a_start_needs_a_date_or_haste(self):
        for value, error in (({"by": None, "asap": False}, "requirements.start: use null"),
                             ({"by": "2026-11-31", "asap": False}, "requirements.start.by: must be null or a date"),
                             ({"by": "2026-11-01", "asap": None}, "requirements.start.asap: must be true or false"),
                             ({"by": "2026-11-01"}, "requirements.start.asap: missing")):
            with self.subTest(value=value):
                self.assert_error(self.cited("requirements.start", value, "11月1日前到岗"), error)

    def test_values_need_evidence(self):
        record = with_value(minimal_record(), "requirements.start", {"by": None, "asap": True})
        self.assert_error(record, "requirements.start: has a value but no evidence")
        record = with_value(minimal_record(), "interview", {"mode": "online", "cities": []})
        self.assert_error(record, "interview: has a value but no evidence")

    def test_upgrade_adds_both_fields_to_an_older_record(self):
        record = minimal_record()
        del record["interview"], record["requirements"]["start"]
        self.assert_error(record, "interview: missing")
        self.assert_error(record, "requirements.start: missing")
        upgraded = schema.upgrade(record)
        self.assert_valid(upgraded)
        self.assertEqual((upgraded["interview"], upgraded["requirements"]["start"]), (None, None))


class Evidence(SchemaCase):
    def test_a_value_without_evidence_is_rejected(self):
        self.assert_error(with_value(minimal_record(), "company", "示例科技"), "company: has a value but no evidence")

    def test_a_citation_must_occur_in_the_jd(self):
        record = minimal_record()
        record["evidence"]["title"]["text"] = "高级算法专家"
        self.assert_error(record, "evidence.title.text: not found in raw_text")

    def test_copying_differences_are_folded(self):
        record = minimal_record()
        record["raw_text"] += "\n熟悉 Python，了解" + ZERO_WIDTH_SPACE + "\n" + fullwidth("LangChain")
        record["requirements"]["skills"] = ["Python", "LangChain"]
        record["evidence"]["requirements.skills"] = {"text": "熟悉python,了解langchain", "method": "agent"}
        self.assert_valid(record)

    def test_each_list_item_must_appear_in_its_evidence(self):
        record = self.cited("requirements.skills", ["Python", "Kubernetes"], "熟悉Python", method="agent")
        errors = self.assert_error(record, "evidence.requirements.skills: 'Kubernetes' does not appear")
        self.assertFalse(any("'Python'" in error for error in errors), errors)

    def test_user_supplied_values_need_no_citation(self):
        record = with_value(minimal_record(), "company", "示例科技")
        record["evidence"]["company"] = {"text": None, "method": "user"}
        self.assert_valid(record)

    def test_only_user_evidence_may_omit_the_text(self):
        record = minimal_record()
        record["evidence"]["title"]["text"] = None
        self.assert_error(record, "evidence.title.text: must be a non-empty string")

    def test_every_snippet_is_checked(self):
        record = self.cited("requirements.education", {"min": "bachelor", "preferred": "phd"}, "本科及以上，硕士优先")
        record["evidence"]["requirements.education"]["text"] = ["本科及以上", "博士优先"]
        self.assert_error(record, "evidence.requirements.education.text: not found in raw_text: '博士优先'")

    def test_evidence_keys_are_field_paths(self):
        record = minimal_record()
        record["evidence"]["requirements.salary"] = {"text": "后端开发实习生", "method": "rule"}
        self.assert_error(record, "evidence.requirements.salary: not a field that takes evidence")

    def test_method_must_be_known(self):
        record = minimal_record()
        record["evidence"]["title"]["method"] = "model"
        self.assert_error(record, "evidence.title.method: must be one of")


def run_cli(*args, input_bytes=None, encoding="utf-8"):
    """Run the real CLI; `encoding` is the console code page it is told it has."""
    env = dict(os.environ, PYTHONIOENCODING=encoding, PYTHONUTF8="0")
    return subprocess.run(
        [sys.executable, "-m", "jobsearch_cn", *args], cwd=REPO, env=env, input=input_bytes, capture_output=True
    )


class ValidateCommand(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)

    def write(self, name: str, data: bytes) -> str:
        path = self.tmp / name
        path.write_bytes(data)
        return str(path)

    @staticmethod
    def example_bytes() -> bytes:
        return json.dumps(doc_example(), ensure_ascii=False).encode("utf-8")

    def test_valid_file_exits_zero(self):
        proc = run_cli("jd", "validate", self.write("job.json", self.example_bytes()))
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        self.assertEqual(json.loads(proc.stdout), {"valid": True, "errors": []})

    def test_invalid_record_exits_one_and_lists_errors(self):
        record = with_value(doc_example(), "status", "applied")
        proc = run_cli("jd", "validate", "-", input_bytes=json.dumps(record).encode("utf-8"))
        self.assertEqual(proc.returncode, 1)
        result = json.loads(proc.stdout)
        self.assertFalse(result["valid"])
        self.assertTrue(any(error.startswith("status: must be one of") for error in result["errors"]), result)

    def test_reads_stdin_when_no_file_is_given(self):
        proc = run_cli("jd", "validate", input_bytes=self.example_bytes())
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))

    def test_utf8_bom_from_windows_notepad_is_accepted(self):
        path = self.write("bom.json", codecs.BOM_UTF8 + self.example_bytes())
        self.assertEqual(run_cli("jd", "validate", path).returncode, 0)

    def test_non_utf8_file_is_an_input_error(self):
        data = '{"title": "后端开发实习生"}'.encode("gbk")
        with self.assertRaises(UnicodeDecodeError):  # sanity: these GBK bytes are not UTF-8
            data.decode("utf-8")
        proc = run_cli("jd", "validate", self.write("gbk.json", data))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not UTF-8", json.loads(proc.stderr)["error"])

    def test_malformed_json_is_an_input_error(self):
        proc = run_cli("jd", "validate", input_bytes=b"{not json")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not valid JSON", json.loads(proc.stderr)["error"])

    def test_missing_file_is_an_input_error(self):
        proc = run_cli("jd", "validate", str(self.tmp / "missing.json"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot read", json.loads(proc.stderr)["error"])

    def test_chinese_errors_reach_a_legacy_console_as_utf8(self):
        record = doc_example()
        record["evidence"]["title"]["text"] = "高级算法专家"
        payload = json.dumps(record, ensure_ascii=False).encode("utf-8")
        for encoding in ("cp1252", "gbk"):
            with self.subTest(encoding=encoding):
                proc = run_cli("jd", "validate", input_bytes=payload, encoding=encoding)
                err = proc.stderr.decode("utf-8", "replace")
                self.assertNotIn("UnicodeEncodeError", err)
                self.assertEqual(proc.returncode, 1, err)
                self.assertIn("高级算法专家", proc.stdout.decode("utf-8"))

    def test_jd_alone_prints_its_help(self):
        proc = run_cli("jd")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("validate", proc.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
