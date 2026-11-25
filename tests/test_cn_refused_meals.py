"""Explicitly unavailable meal benefits must not become positive benefits."""
import json
import unittest

from tests.test_cn_jd_parser import run_cli


class RefusedMealBenefits(unittest.TestCase):
    def meals(self, wording):
        result = run_cli("jd", "parse", input_bytes=("数据分析实习生\n" + wording).encode("utf-8"))
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return json.loads(result.stdout)["jobs"][0]["benefits"]["meals"]

    def test_refused_allowances_and_withdrawn_meals_are_unknown(self):
        for wording in ("不提供餐补30元/天。", "不发放餐补500元/月。", "未提供餐补30元/天。",
                        "不再提供午餐。", "不再包午餐。", "不再免费提供午餐。",
                        "不提供午餐。", "无餐补30元/天。"):
            with self.subTest(wording=wording):
                self.assertIsNone(self.meals(wording))

    def test_independent_positive_benefits_are_retained(self):
        self.assertEqual({"per_day": 1, "allowance": None},
                         self.meals("不提供餐补30元/天，但提供工作餐。"))
        self.assertEqual({"per_day": 0, "allowance": {"amount": 30, "unit": "CNY/day"}},
                         self.meals("不再提供午餐，餐补30元/天。"))
        self.assertEqual({"per_day": 1, "allowance": None},
                         self.meals("不提供早餐，提供午餐。"))

    def test_positive_meal_and_allowance_wording_is_unchanged(self):
        self.assertEqual({"per_day": 1, "allowance": {"amount": 30, "unit": "CNY/day"}},
                         self.meals("免费提供午餐，提供餐补30元/天。"))
