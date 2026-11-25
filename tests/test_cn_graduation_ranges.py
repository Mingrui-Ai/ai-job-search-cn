"""Cohort ranges must admit the years between their stated endpoints."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.test_cn_jd_parser import parse_one
from tests.test_cn_match import PROFILES, run_cli


class GraduationRanges(unittest.TestCase):
    def test_both_endpoints_can_name_their_cohort(self):
        for first, last in (("2026", "2028"), ("26", "28")):
            for separator in ("-", "~", "～", "至", "到"):
                text = f"任职要求：面向{first}届{separator}{last}届毕业生"
                with self.subTest(text=text):
                    self.assertEqual(parse_one(text)["requirements"]["graduation"],
                                     {"years": [2026, 2027, 2028], "strict": True})

    def test_existing_ranges_single_years_and_spacing(self):
        for text, years in (
            ("面向2026至2028届毕业生", [2026, 2027, 2028]),
            ("面向26-28届毕业生", [2026, 2027, 2028]),
            ("面向2026 届 至 2028 届毕业生", [2026, 2027, 2028]),
            ("面向2027届毕业生", [2027]),
            ("面向2027届至2027届毕业生", [2027]),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_one(text)["requirements"]["graduation"],
                                 {"years": years, "strict": True})

    def test_discrete_cohorts_do_not_fill_the_gaps(self):
        for separator in ("、", "/", ",", "，", "和", "与", "及", "或"):
            text = f"面向2026届{separator}2028届毕业生"
            with self.subTest(text=text):
                self.assertEqual(parse_one(text)["requirements"]["graduation"],
                                 {"years": [2026, 2028], "strict": True})

    def test_a_preferred_range_keeps_its_preference_and_source(self):
        text = "任职要求：2026届至2028届毕业生优先"
        record = parse_one(text)
        self.assertEqual(record["requirements"]["graduation"],
                         {"years": [2026, 2027, 2028], "strict": False})
        self.assertEqual(record["evidence"]["requirements.graduation"],
                         {"text": text, "method": "rule"})

    def test_years_outside_the_schema_remain_unknown(self):
        for text in ("面向2014届至2017届毕业生", "面向2039届至2041届毕业生"):
            with self.subTest(text=text):
                record = parse_one(text)
                self.assertIsNone(record["requirements"]["graduation"])
                self.assertNotIn("requirements.graduation", record["evidence"])

    def test_cli_saved_range_accepts_an_intermediate_cohort(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            shutil.copytree(PROFILES / "tech", data / "profile")  # synthetic 2027 graduate
            source = data / "jd.txt"
            for separator, expected in (("至", "match"), ("、", "conflict")):
                with self.subTest(separator=separator):
                    source.write_text(
                        "职位名称：后端开发实习生\n公司名称：示例科技有限公司\n工作地点：深圳\n"
                        f"任职要求：面向2026届{separator}2028届毕业生，本科及以上，"
                        "每周至少4天，实习至少6个月，熟悉Python。\n", encoding="utf-8")
                    parsed = run_cli("jd", "parse", str(source), "--save", data_dir=data)
                    self.assertEqual(parsed.returncode, 0, parsed.stderr.decode("utf-8"))
                    job_id = json.loads(parsed.stdout)["saved"][0]["id"]
                    filtered = run_cli("match", "filter", job_id, data_dir=data)
                    self.assertEqual(filtered.returncode, 0, filtered.stderr.decode("utf-8"))
                    result = json.loads(filtered.stdout)
                    graduation = next(c for c in result["checks"] if c["check"] == "graduation")
                    self.assertEqual(graduation["result"], expected, graduation["reason"])
                    self.assertEqual(result["verdict"], "eligible" if expected == "match" else "ineligible")


if __name__ == "__main__":
    unittest.main()
