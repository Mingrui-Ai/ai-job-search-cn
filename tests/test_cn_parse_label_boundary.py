"""PR 151: a valued education field cannot also open a requirements section.

Fictional inputs only. Negative cases reproduce on 9b98301; controls keep
multiline field values, standalone section headings and explicit requirements.
"""

import unittest

from jobsearch_cn import match
from tests.test_cn_parse_fix_1110 import parse, reviewer_candidate


class EducationFieldBoundary(unittest.TestCase):
    def test_finished_field_does_not_read_later_degree(self):
        for colon in ("：", ":", "\n："):
            for gap in ("", "\n"):
                for value, expected in (("未说明", None), ("不限", {"min": "none", "preferred": None})):
                    for boundary in ("。", "；", ";", "！", "!", "？", "?", "\n"):
                        with self.subTest(colon=colon, gap=gap, value=value, boundary=boundary):
                            text = "学历要求" + colon + gap + value + boundary + "协助在读硕士整理资料。"
                            job = parse(text)
                            self.assertEqual(job["requirements"]["education"], expected)
                            evidence = job["evidence"].get("requirements.education")
                            if expected is None:
                                self.assertIsNone(evidence)
                            else:
                                self.assertIn(evidence["text"], text)
                                self.assertNotIn("在读硕士", evidence["text"])
                            self.assertNotEqual(match.filter_job(job, reviewer_candidate())["verdict"], "ineligible")

    def test_finished_field_does_not_read_later_cohort(self):
        for colon in ("：", ":", "\n："):
            for gap in ("", "\n"):
                for boundary in ("。", "；", "\n"):
                    with self.subTest(colon=colon, gap=gap, boundary=boundary):
                        text = "学历要求" + colon + gap + "未说明" + boundary + "2027校园招聘。"
                        job = parse(text)
                        self.assertIsNone(job["requirements"]["graduation"])
                        self.assertNotIn("requirements.graduation", job["evidence"])
                        self.assertNotEqual(match.filter_job(job, reviewer_candidate())["verdict"], "ineligible")

    def test_inline_and_multiline_field_values_still_apply(self):
        for colon in ("：", ":"):
            for gap in ("", "\n", "\n  "):
                for value, expected in (
                        ("全日制在读硕士或博士", {"min": "master", "preferred": None}),
                        ("全日制在读硕士或博士优先", {"min": None, "preferred": "master"})):
                    with self.subTest(colon=colon, gap=gap, value=value):
                        text = "学历要求" + colon + gap + value + "。\n协助整理资料。"
                        job = parse(text)
                        self.assertEqual(job["requirements"]["education"], expected)
                        self.assertIn(job["evidence"]["requirements.education"]["text"], text)
                        verdict = match.filter_job(job, reviewer_candidate())["verdict"]
                        if expected["min"]:
                            self.assertEqual(verdict, "ineligible")
                        else:
                            self.assertNotEqual(verdict, "ineligible")

    def test_standalone_and_general_requirements_sections_still_apply(self):
        for heading in ("学历要求", "【学历要求】", "[学历要求]", "  学历要求  ",
                        "【学历要求】：", "[学历要求]:", "任职要求", "任职要求：", "岗位要求:"):
            with self.subTest(heading=heading):
                text = heading + "\n相关领域的在读硕士或博士。\n候选人：2027校招应届毕业生。"
                job = parse(text)
                self.assertEqual(job["requirements"]["education"], {"min": "master", "preferred": None})
                self.assertEqual(job["requirements"]["graduation"], {"years": [2027], "strict": True})
                self.assertEqual(match.filter_job(job, reviewer_candidate())["verdict"], "ineligible")

    def test_field_also_ends_a_preceding_requirements_section(self):
        text = "任职要求：熟悉Python。\n学历要求：不限。协助在读硕士整理资料。\n2027校园招聘。"
        job = parse(text)
        self.assertEqual(job["requirements"]["education"], {"min": "none", "preferred": None})
        self.assertIsNone(job["requirements"]["graduation"])
        self.assertNotEqual(match.filter_job(job, reviewer_candidate())["verdict"], "ineligible")


class FieldTerminators(unittest.TestCase):
    """Recognized fields close an earlier section using their own syntax."""

    education_labels = ("学历", "学历要求", "学历 要求", "学历\n要求")
    cohort_labels = ("招聘频道", "招聘类型", "招聘类别", "工作性质", "届别", "毕业时间", "毕业年份")

    def assert_unknown(self, text):
        job = parse(text)
        for field in ("education", "graduation"):
            self.assertIsNone(job["requirements"][field])
            self.assertNotIn("requirements." + field, job["evidence"])
        self.assertNotEqual(match.filter_job(job, reviewer_candidate())["verdict"], "ineligible")

    def test_review_six_cases(self):
        for label in ("学历 要求", "学历要求", "学历"):
            for suffix in ("协助在读硕士整理资料。", "2027校园招聘。"):
                with self.subTest(label=label, suffix=suffix):
                    self.assert_unknown("职位名称：样品记录实习生\n工作地点：深圳\n"
                                        "任职要求：熟悉Python。\n" + label + "：未说明。" + suffix)

    def test_field_matrix_ends_previous_section(self):
        for label in self.education_labels + self.cohort_labels:
            for prefix in ("", "\n", "\n1. ", "\n2、"):
                for value in ("：未说明", ":\n未说明", "\n：\n未说明"):
                    for end in ("。", "；", "\n"):
                        with self.subTest(label=label, prefix=prefix, value=value, end=end):
                            text = ("任职要求：熟悉Python。" + prefix + label + value + end
                                    + "协助在读硕士整理资料。\n2027校园招聘。")
                            self.assert_unknown(text)

    def test_real_requirements_before_and_after_fields_still_apply(self):
        for label in self.education_labels + self.cohort_labels:
            for heading in ("任职要求：", "【学历要求】：", "岗位要求\n"):
                for placement in ("before", "after"):
                    with self.subTest(label=label, heading=heading, placement=placement):
                        field = label + "：未说明。\n协助整理资料。\n"
                        requirements = heading + "在读硕士或博士。\n候选人：2027校招应届毕业生。\n"
                        text = requirements + field if placement == "before" else field + requirements
                        job = parse(text)
                        self.assertEqual(job["requirements"]["education"], {"min": "master", "preferred": None})
                        self.assertEqual(job["requirements"]["graduation"], {"years": [2027], "strict": True})
                        for name in ("education", "graduation"):
                            self.assertIn(job["evidence"]["requirements." + name]["text"], requirements)
                        self.assertEqual(match.filter_job(job, reviewer_candidate())["verdict"], "ineligible")

    def test_fields_keep_their_explicit_values(self):
        groups = ((self.education_labels, "education", "在读硕士或博士", {"min": "master", "preferred": None}),
                  (self.cohort_labels, "graduation", "2027校园招聘", {"years": [2027], "strict": True}))
        for labels, name, value, expected in groups:
            for label in labels:
                for prefix in ("任职要求：熟悉Python。\n1. ", "工作职责\n"):
                    for colon in ("：", ":\n", "\n：\n"):
                        with self.subTest(label=label, prefix=prefix, colon=colon):
                            text = prefix + label + colon + value + "。\n协助整理资料。"
                            job = parse(text)
                            self.assertEqual(job["requirements"][name], expected)
                            self.assertIn(job["evidence"]["requirements." + name]["text"], text)
                            self.assertEqual(match.filter_job(job, reviewer_candidate())["verdict"], "ineligible")


if __name__ == "__main__":
    unittest.main()
