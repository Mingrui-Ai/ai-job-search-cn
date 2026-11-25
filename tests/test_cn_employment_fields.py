"""Explicit recruitment metadata must survive incidental body mentions."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from jobsearch_cn import jd_parser, schema

REPO = Path(__file__).resolve().parent.parent


def parse(text):
    [record], _ = jd_parser.parse_text(text)
    return record


class EmploymentFields(unittest.TestCase):
    def test_work_nature_precedes_incidental_body_mentions(self):
        for nature, duties, expected in (
                ("社会招聘", "负责2027校园招聘活动的组织与执行。", "experienced"),
                ("社招", "协助整理实习生资料。", "experienced"),
                ("校园招聘", "协助整理实习生资料。", "campus"),
                ("校招", "负责日常实习岗位的招聘流程。", "campus"),
                ("实习", "协助社会招聘活动。", "internship")):
            with self.subTest(nature=nature):
                field = "工作性质：" + nature
                record = parse("职位名称：招聘流程专员\n" + field + "\n工作职责\n" + duties)
                self.assertEqual(record["employment_type"], expected)
                self.assertEqual(record["evidence"]["employment_type"], {"text": field, "method": "rule"})
                self.assertEqual(schema.validate(record), [])

    def test_field_layouts_and_parenthesized_details(self):
        for newline in ("\n", "\r\n"):
            for field in ("工作性质: 社会招聘", "  工作性质 ：\t社会招聘  ", "工作性质：社会招聘（全职）",
                          "工作性质：社会招聘。"):
                with self.subTest(newline=newline, field=field):
                    text = newline.join(("职位名称：招聘流程专员", field, "工作职责", "负责校园招聘活动。"))
                    record = parse(text)
                    self.assertEqual(record["employment_type"], "experienced")
                    self.assertIn(record["evidence"]["employment_type"]["text"], record["raw_text"])

    def test_explicit_title_keeps_its_existing_priority(self):
        record = parse("职位名称：人力资源实习生\n工作性质：社会招聘\n负责校园招聘活动。")
        self.assertEqual(record["employment_type"], "internship")
        self.assertIn("人力资源实习生", record["evidence"]["employment_type"]["text"])

    def test_full_time_and_unknown_values_do_not_infer_a_recruitment_type(self):
        for nature in ("全职", "兼职", "未说明"):
            with self.subTest(nature=nature):
                record = parse("职位名称：资料核验员\n工作性质：" + nature + "\n负责资料归档。")
                self.assertIsNone(record["employment_type"])
                self.assertNotIn("employment_type", record["evidence"])

    def test_without_an_explicit_field_the_existing_body_rules_remain(self):
        for text, expected in (("招聘流程专员\n参加校园招聘。", "campus"),
                               ("招聘流程专员\n社会招聘。", "experienced"),
                               ("招聘流程专员\n日常实习岗位。", "internship")):
            with self.subTest(text=text):
                self.assertEqual(parse(text)["employment_type"], expected)

    def test_multiple_types_do_not_gain_single_field_priority(self):
        for separator in ("，", ",", "、"):
            for other, expected in (("校园招聘", "campus"), ("实习生", "internship")):
                with self.subTest(separator=separator, other=other):
                    record = parse("职位名称：招聘流程专员\n工作性质：社会招聘" + separator + other
                                   + "\n工作职责\n负责资料整理。")
                    self.assertEqual(record["employment_type"], expected)
                    # An ambiguous list still uses the existing body rule;
                    # it must not cite its first part as a complete field.
                    self.assertEqual(record["evidence"]["employment_type"]["text"], other)

    def test_non_enum_values_keep_the_existing_body_fallback(self):
        for value in ("社会招聘负责人", "全职"):
            with self.subTest(value=value):
                record = parse("职位名称：招聘流程专员\n工作性质：" + value + "\n负责校园招聘活动。")
                self.assertEqual(record["employment_type"], "campus")
                self.assertEqual(record["evidence"]["employment_type"]["text"], "校园招聘")

    def test_file_import_and_filter_use_the_explicit_recruitment_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            shutil.copytree(REPO / "tests/fixtures/cn/profile/tech", data / "profile")
            profile_file = data / "profile/profile.json"
            profile = json.loads(profile_file.read_text(encoding="utf-8"))
            profile["target"]["employment_types"] = ["experienced"]
            profile_file.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            source = root / "job.txt"
            source.write_text("职位名称：招聘流程专员\n工作性质：社会招聘\n工作地点：深圳\n工作职责\n"
                              "负责2027校园招聘活动的组织与执行。\n任职资格\n本科及以上学历。\n", encoding="utf-8")

            def cli(*args):
                result = subprocess.run([sys.executable, "-m", "jobsearch_cn", *map(str, args),
                                         "--data-dir", str(data)], cwd=REPO,
                                        capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)

            parsed = cli("jd", "parse", source, "--save")
            job_id = parsed["jobs"][0]["id"]
            filtered = cli("match", "filter", job_id)
            employment = next(item for item in filtered["checks"] if item["check"] == "employment_type")
            self.assertEqual(employment["result"], "match")
            stored = cli("jd", "show", job_id)
            self.assertEqual(stored["employment_type"], "experienced")
            self.assertEqual(stored["evidence"]["employment_type"]["text"], "工作性质：社会招聘")


if __name__ == "__main__":
    unittest.main()
