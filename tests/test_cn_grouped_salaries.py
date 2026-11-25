"""Grouped amounts survive pasted-JD import without losing leading digits."""
import json
import unittest

from tests.test_cn_jd_parser import run_cli


class GroupedSalaryAmounts(unittest.TestCase):
    def parse(self, wording):
        result = run_cli("jd", "parse", input_bytes=("数据分析师\n" + wording).encode("utf-8"))
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return json.loads(result.stdout)["jobs"][0]

    def test_grouped_wages_keep_the_whole_amount(self):
        cases = (
            ("薪资：12,500-18,500元/月", 12500, 18500, "CNY/month"),
            ("月薪15,000元", 15000, 15000, "CNY/month"),
            ("薪资：180,000-240,000元/年", 180000, 240000, "CNY/year"),
            ("薪资：1,200元/天", 1200, 1200, "CNY/day"),
            ("薪资：1,200.50元/小时", 1200.5, 1200.5, "CNY/hour"),
            ("薪资：12,000元-18,000元/月", 12000, 18000, "CNY/month"),
        )
        for wording, low, high, unit in cases:
            with self.subTest(wording=wording):
                job = self.parse(wording)
                salary = job["salary"]
                self.assertIsNotNone(salary)
                self.assertEqual((low, high, unit),
                                 (salary["min"], salary["max"], salary["unit"]))
                self.assertIn(",", str(job["evidence"]["salary"]))

    def test_invalid_grouping_is_not_salvaged_as_a_smaller_salary(self):
        for wording in ("薪资：12,34元/月", "薪资：1,20K/月", "薪资：1,23,456元/年"):
            with self.subTest(wording=wording):
                self.assertIsNone(self.parse(wording)["salary"])

    def test_plain_and_decimal_scaled_wages_are_unchanged(self):
        for wording in ("薪资：15000元/月", "薪资：1.5万元/月", "薪资：15K/月，餐补500元/月",
                        "工作地点北京,15000元/月", "工作地点北京,15K/月"):
            with self.subTest(wording=wording):
                self.assertEqual(15000, self.parse(wording)["salary"]["min"])

    def test_grouped_meal_allowance_stays_separate_from_salary(self):
        job = self.parse("薪资20K/月，餐补1,200元/月")
        self.assertEqual(20000, job["salary"]["min"])
        self.assertEqual({"amount": 1200, "unit": "CNY/month"},
                         job["benefits"]["meals"]["allowance"])
