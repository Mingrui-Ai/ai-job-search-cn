"""Do not turn a waived degree into a minimum on the pasted-JD path."""
import json
import unittest

from tests.test_cn_jd_parser import run_cli


class EducationNegation(unittest.TestCase):
    def education(self, wording):
        result = run_cli("jd", "parse", input_bytes=("数据分析实习生\n" + wording).encode("utf-8"))
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return json.loads(result.stdout)["jobs"][0]["requirements"]["education"]

    def test_waived_minimum_and_preference_stay_unknown(self):
        for wording in ("不要求本科及以上学历，熟悉Excel。", "无需硕士学历。",
                        "不要求本科或硕士及以上学历。", "不要求硕士优先。",
                        "学历要求：不要求本科或硕士学历。", "任职要求\n不要求在读硕士或博士。"):
            with self.subTest(wording=wording):
                self.assertIsNone(self.education(wording))

    def test_waived_degree_does_not_override_explicit_no_minimum(self):
        self.assertEqual(self.education("学历不限，不要求本科在读。"),
                         {"min": "none", "preferred": None})

    def test_independent_affirmative_requirements_remain(self):
        for wording in ("不要求硕士学历，本科及以上学历。", "无需工作经验，但要求本科及以上学历。",
                        "无需工作经验但要求本科及以上学历。", "A岗：本科及以上学历；B岗：学历不限"):
            with self.subTest(wording=wording):
                self.assertEqual(self.education(wording), {"min": "bachelor", "preferred": None})
        self.assertEqual(self.education("不要求博士学历，硕士优先。"),
                         {"min": None, "preferred": "master"})
