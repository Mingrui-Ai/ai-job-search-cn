"""PR 151 round-three review matrix and conservative allowlist boundaries.

All 105 synthetic cases from Codex B's review are retained, with their original
expectations. The first two rounds and seven initial issues live in
test_cn_parse_fix_1110.py. No real job/profile data is used here.
"""
import unittest

from jobsearch_cn import match, score
from tests.test_cn_parse_fix_1110 import parse, reviewer_candidate
from tests.test_cn_score import NOW, VOCABULARY


def review_cases():
    cases = []

    def add(group, body, field, expected):
        cases.append((group, "职位名称：样品登记专员\n工作地点：深圳\n" + body, field, expected))

    for section in ("工作职责", "团队介绍", "任职资格"):
        for tag in ("【 27校招 】", "[2027校园招聘]", "《27校招》"):
            for event in ("活动", "大赛", "宣讲会", "开放日"):
                add("cohort_tag_context", section + "\n协助" + tag + event + "的执行。",
                    "graduation", {"years": [2027], "strict": True})
        for field in ("届别：", "毕业年份:", "招聘类型：", "毕业时间："):
            for gap in ("", "\n"):
                add("cohort_field_context", section + "\n团队负责，" + field + gap + "2027校园招聘活动执行。",
                    "graduation", {"years": [2027], "strict": True})
        for value in ("在读硕士或博士", "硕士/博士在读", "在读硕士", "硕士在读"):
            add("education_label_context", section + "\n团队负责协助 学历要求：\n" + value,
                "education", {"min": "master", "preferred": None})
        add("education_preference", section + "\n团队负责，学历：硕士/博士在读优先",
            "education", {"min": None, "preferred": "master"})
        add("explicit_window_priority", "【27校招】\n" + section + "\n毕业时间：2026年8月-2027年7月毕业，参与活动。",
            "graduation", {"years": [2026, 2027], "strict": True})
    for section in ("工作职责", "团队介绍"):
        add("untagged_people_control", section + "\n协助在读硕士/博士整理资料。\n任职资格\n本科及以上学历。",
            "education", {"min": "bachelor", "preferred": None})
    for event in ("活动", "大赛", "宣讲会", "开放日"):
        add("untagged_event_control", "任职资格\n有参与2027校园招聘" + event + "的经验。", "graduation", None)
    for value in ("全日制硕士/博士在读", "目前在读硕士或博士", "全日制硕士在读"):
        for section in ("工作职责", "团队介绍", "任职资格"):
            add("modified_education_field", section + "\n学历要求：" + value,
                "education", {"min": "master", "preferred": None})
        for prefix in ("团队介绍\n团队负责协助 ", "工作职责\n协助整理样品 "):
            add("modified_field_other_people", prefix + "学历要求：" + value,
                "education", {"min": "master", "preferred": None})
    for tag in ("【27校招-技术类】", "《27校招（技术类）》"):
        for section in ("工作职责", "团队介绍", "任职资格"):
            add("qualified_cohort_tag", section + "\n协助" + tag + "活动执行。",
                "graduation", {"years": [2027], "strict": True})
    return cases


class ThirdReviewMatrix(unittest.TestCase):
    def test_all_105_combinations_and_controls(self):
        cases = review_cases()
        self.assertEqual(len(cases), 105)
        for number, (group, text, field, expected) in enumerate(cases, 1):
            with self.subTest(number=number, group=group, text=text):
                job = parse(text)
                self.assertEqual(job["requirements"][field], expected)
                evidence = job["evidence"].get("requirements." + field)
                if expected is None:
                    self.assertIsNone(evidence)
                else:
                    self.assertIn(evidence["text"], text)
                conflict = expected == {"min": "master", "preferred": None} or expected == {"years": [2027], "strict": True}
                verdict = match.filter_job(job, reviewer_candidate())["verdict"]
                if conflict:
                    self.assertEqual(verdict, "ineligible")
                else:
                    self.assertNotEqual(verdict, "ineligible")


class AllowlistBoundaries(unittest.TestCase):
    def test_modified_explicit_master_fields_exclude_bachelors(self):
        for prefix in ("团队介绍\n团队负责协助 ", "工作职责\n协助整理样品 ", "公司介绍\n"):
            for value in ("全日制 硕士", "目前硕士在读", "目前已经硕士毕业", "目前在读硕士或博士"):
                with self.subTest(prefix=prefix, value=value):
                    text = prefix + "学历：" + value
                    job = parse(text)
                    self.assertEqual(job["requirements"]["education"], {"min": "master", "preferred": None})
                    self.assertIn(job["evidence"]["requirements.education"]["text"], text)
                    rec = score.score_job(job, reviewer_candidate(), VOCABULARY, now=NOW)
                    self.assertEqual(rec["total"]["grade"], "ineligible")

    def test_new_patterns_outside_allowlist_stay_unknown(self):
        for text in (
                "团队介绍\n团队里有硕士，2026年成立。",
                "公司简介\n2026年成立，设有在读硕士交流室。",
                "工作职责\n协助在读硕士整理2026年报告。",
                "活动名称：2027校园招聘宣讲会与在读硕士交流日",
                "职位名称：2027校园招聘活动策划专员",
                "2027校园招聘", "在读硕士", "目前在读硕士或博士",
                "学历：未说明。协助在读硕士整理资料。",
                "学历：未说明\n协助在读硕士整理资料。",
                "届别：未说明。协助2027校园招聘。",
                "届别：未说明\n协助2027校园招聘。",
                "任职资格\n熟悉Python。\n团队介绍\n在读硕士十余人，2027校园招聘。",
                "任职要求\n熟悉Python。\n公司概况\n在读硕士十余人，2027校园招聘。"):
            with self.subTest(text=text):
                job = parse(text)
                for field in ("education", "graduation"):
                    self.assertIsNone(job["requirements"][field])
                    self.assertNotIn("requirements." + field, job["evidence"])
                self.assertEqual(match.filter_job(job, reviewer_candidate())["verdict"], "needs_check")

    def test_candidate_sentences_in_requirements_and_tag_annotations(self):
        for heading in ("任职要求", "岗位要求", "任职资格"):
            for body in ("面向2027校园招聘应届毕业生。", "2027校园招聘毕业生。", "1. 2027校招学生。"):
                with self.subTest(heading=heading, body=body):
                    self.assertEqual(parse(heading + "\n" + body)["requirements"]["graduation"],
                                     {"years": [2027], "strict": True})
        for tag in ("【27校招-技术类】", "[2027校招，技术/运营方向]", "《2027届（技术类）》"):
            self.assertEqual(parse("公司简介\n协助" + tag + "活动执行。")["requirements"]["graduation"],
                             {"years": [2027], "strict": True})

    def test_pre_pr_patterns_keep_their_original_scope(self):
        # Legacy rules are deliberately not tightened by the new allowlist.
        for text, field, expected in (
                ("2027届", "graduation", {"years": [2027], "strict": True}),
                ("硕士在读", "education", {"min": "master", "preferred": None}),
                ("硕士毕业", "education", {"min": "master", "preferred": None}),
                ("在读硕士或博士优先", "education", {"min": None, "preferred": "master"}),
                ("团队介绍\n在读硕士或博士优先担任组长。", "education", {"min": None, "preferred": "master"})):
            with self.subTest(text=text):
                self.assertEqual(parse(text)["requirements"][field], expected)


if __name__ == "__main__":
    unittest.main()
