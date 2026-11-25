"""Return-offer wording through the documented pasted-JD CLI."""
import json
import unittest

from tests.test_cn_jd_parser import run_cli


class RetentionNegation(unittest.TestCase):
    def parse(self, wording):
        result = run_cli("jd", "parse", input_bytes=("数据分析实习生\n" + wording).encode("utf-8"))
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return json.loads(result.stdout)["jobs"][0]

    def test_explicitly_unavailable_retention_is_false(self):
        for wording in ("暂无留用机会", "不提供留用机会", "没有留用机会", "不可留用", "不能留用"):
            with self.subTest(wording=wording):
                job = self.parse(wording)
                self.assertIs(job["return_offer"], False)
                self.assertIn("留用", str(job["evidence"]["return_offer"]))

    def test_positive_retention_and_existing_conversion_wording(self):
        for wording, expected in (("提供留用机会", True), ("有转正机会", True),
                                  ("不提供转正", False), ("暂无转正机会", False),
                                  ("每周至少3天", None)):
            with self.subTest(wording=wording):
                self.assertIs(self.parse(wording)["return_offer"], expected)
