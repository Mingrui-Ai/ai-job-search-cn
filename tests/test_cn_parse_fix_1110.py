"""Synthetic regressions for the seven issues found during the first ATS collection."""
import unittest

from jobsearch_cn import jd_parser, report, score
from tests.test_cn_score import NOW, VOCABULARY, profile_from


def parse(text):
    return jd_parser.parse_text(text, now=NOW, single=True)[0][0]


class CollectionRegressions(unittest.TestCase):
    def test_01_title_without_a_job_word_in_collected_header(self):
        title = "质量保障（校招，苏州）"
        job = parse(title + "\n招聘频道：校园招聘\n工作地点：苏州\n公司名称：虚构星叶实验室\n"
                    "工作职责\n协助整理样品登记表。\n任职资格\n本科及以上学历。")
        self.assertEqual(job["title"], title)
        self.assertEqual(job["evidence"]["title"]["text"], title)

    def test_02_salary_parentheses_do_not_leave_a_half_bracket(self):
        job = parse("质量分析工程师（12k-18k）\n公司名称：虚构星叶实验室\n工作职责\n整理检测报告。")
        self.assertEqual(job["title"], "质量分析工程师")
        self.assertEqual(job["salary"]["min"], 12000)

    def test_03_certificates_are_not_day_rates(self):
        job = parse("职位名称：资料核验实习生\n公司名称：虚构星叶实验室\n任职资格\n"
                    "通过CET-6/日语N2，能阅读外语设备手册优先。")
        self.assertIsNone(job["salary"])
        self.assertNotIn("salary", job["evidence"])

    def test_04_current_graduate_students_are_education_requirements(self):
        for phrase in ("在读硕士/博士", "相关领域的在读硕士或博士", "硕士及以上在读"):
            with self.subTest(phrase=phrase):
                job = parse("职位名称：样本研究实习生\n任职资格\n" + phrase + "，愿意学习样品归档流程。")
                self.assertEqual(job["requirements"]["education"], {"min": "master", "preferred": None})

    def test_05_weekly_attendance_with_zaizhi(self):
        job = parse("职位名称：资料核验实习生\n任职资格\n每周可在职4天，协助核验收货记录。")
        self.assertEqual(job["requirements"]["days_per_week"], 4)

    def test_06_graduation_windows_and_campus_cohorts(self):
        for text, years in (("2026年8月-2027年7月毕业的学生", [2026, 2027]),
                            ("【27校招】质量分析工程师", [2027])):
            with self.subTest(text=text):
                job = parse(text + "\n公司名称：虚构星叶实验室\n工作地点：苏州")
                self.assertEqual(job["requirements"]["graduation"], {"years": years, "strict": True})

    def test_07_location_alone_cannot_be_a_top_ranked_perfect_match(self):
        profile = profile_from("tech")
        sparse_job = parse("职位名称：资料核验员\n工作地点：深圳\n工作职责\n整理样品登记表。")
        full_job = parse("职位名称：资料核验员\n工作地点：深圳\n任职资格\n熟悉Python。\n薪资：200元/天")
        sparse, full = [score.score_job(j, profile, VOCABULARY, now=NOW) for j in (sparse_job, full_job)]
        self.assertIsNone(sparse["total"]["score"])
        self.assertEqual(sparse["total"]["grade"], "needs_check")
        self.assertIn("待确认", report.conclusion(sparse))
        self.assertNotIn("很匹配", report.conclusion(sparse))
        ordered = report.order([report.entry(sparse, sparse_job, False), report.entry(full, full_job, False)])
        self.assertEqual(ordered[0]["record"]["job_id"], full_job["id"])


if __name__ == "__main__":
    unittest.main()
