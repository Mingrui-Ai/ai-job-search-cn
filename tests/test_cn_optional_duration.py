"""A preferred or waived internship length is not a mandatory minimum."""
import json
import unittest

from tests.test_cn_jd_parser import run_cli


class OptionalInternshipDuration(unittest.TestCase):
    def duration(self, wording):
        result = run_cli("jd", "parse", input_bytes=("数据分析实习生\n" + wording).encode("utf-8"))
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return json.loads(result.stdout)["jobs"][0]["requirements"]["min_months"]

    def test_waived_or_preferred_durations_are_not_required(self):
        for wording in ("不要求实习满6个月。", "无需实习至少6个月。", "能实习6个月者优先。",
                        "保证实习6个月为佳。", "优先考虑实习6个月的同学。"):
            with self.subTest(wording=wording):
                self.assertIsNone(self.duration(wording))

    def test_optional_duration_does_not_hide_an_actual_minimum(self):
        for wording in ("实习至少3个月，能实习6个月者优先。", "不要求实习满6个月，至少3个月。",
                        "至少3个月，但可实习6个月者优先。", "熟悉Excel者优先但须实习至少3个月。",
                        "不要求掌握Excel但须实习至少3个月。"):
            with self.subTest(wording=wording):
                self.assertEqual(3, self.duration(wording))

    def test_required_and_conflicting_durations_keep_existing_behavior(self):
        self.assertEqual(6, self.duration("实习至少6个月。"))
        self.assertIsNone(self.duration("实习至少3个月，实习至少6个月。"))
        self.assertIsNone(self.duration("具有6个月以上工作经验。"))
