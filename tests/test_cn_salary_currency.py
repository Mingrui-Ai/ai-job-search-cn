"""Explicit foreign wages must not acquire a CNY label during JD import."""
import json
import unittest

from tests.test_cn_jd_parser import run_cli


class SalaryCurrency(unittest.TestCase):
    def salary(self, wording):
        result = run_cli("jd", "parse", input_bytes=("数据分析师\n" + wording).encode("utf-8"))
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return json.loads(result.stdout)["jobs"][0]["salary"]

    def test_explicit_foreign_currency_is_left_unknown(self):
        for wording in ("薪资：USD 20-30K/月", "薪资：20-30K美元/月", "薪资：HKD 20K",
                        "薪资：EUR 40-50/小时", "薪资：200/天（美元）", "薪资：20K/月（港币）",
                        "薪资：美元税前20K/月", "薪资：20K/月 USD", "薪资：$20K/月"):
            with self.subTest(wording=wording):
                self.assertIsNone(self.salary(wording))

    def test_local_cny_quote_survives_unrelated_currency_mentions(self):
        for wording in ("公司完成100万美元融资。\n薪资：20-30K/月",
                        "负责美元结算业务，月薪20-30K。", "薪资：人民币20-30K/月",
                        "薪资：CNY 20-30K/月", "薪资：USD 5K/月；国内岗位20-30K/月"):
            with self.subTest(wording=wording):
                value = self.salary(wording)
                self.assertEqual((value["min"], value["max"], value["unit"]),
                                 (20000, 30000, "CNY/month"))
