"""Synthetic regressions for the seven issues found during the first ATS collection."""
import unittest

from jobsearch_cn import jd_parser, report, score, screen
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

    def test_titles_keep_role_brackets_and_reject_prose_headers(self):
        for title in ("资料分析工程师（样本方向）", "资料分析工程师（样本方向） 180元/天",
                      "资料分析工程师（样本方向）（12k-18k）"):
            with self.subTest(title=title):
                job = parse(title + "\n工作职责\n协助核验报告。")
                self.assertEqual(job["title"], "资料分析工程师（样本方向）")
        for first in ("欢迎来到样本之家", "负责整理记录，归档资料", "招聘首页"):
            # No collected-header context, or sentence wording, must remain insufficient.
            tail = "\n招聘频道：校园招聘\n工作地点：苏州" if "负责" in first else "\n工作职责\n归档样本。"
            self.assertIsNone(parse(first + tail)["title"])

    def test_day_and_hour_rates_need_complete_period_tokens(self):
        for text in ("CET-6/日语N2", "N2/日语", "版本6/时间管理", "CET-6/日语N2\n每周可在职4天"):
            with self.subTest(text=text):
                self.assertIsNone(parse("任职资格\n" + text)["salary"])
        for text, low, unit in (("180-240/天", 180, "CNY/day"), ("180元/天包午餐", 180, "CNY/day"),
                                ("35/小时", 35, "CNY/hour"), ("35元/小时可协商", 35, "CNY/hour"),
                                ("CET-6/日语N2，薪资180元/天", 180, "CNY/day")):
            with self.subTest(text=text):
                salary = parse(text)["salary"]
                self.assertEqual((salary["min"], salary["unit"]), (low, unit))

    def test_graduation_requires_a_valid_graduation_window(self):
        for text in ("2026年8月-2027年7月实习", "2026年13月-2027年7月毕业", "2027年8月-2026年7月毕业"):
            with self.subTest(text=text):
                self.assertIsNone(parse(text)["requirements"]["graduation"])
        self.assertEqual(parse("2026年8月-2027年7月毕业优先")["requirements"]["graduation"],
                         {"years": [2026, 2027], "strict": False})

    def test_current_graduate_choices_keep_minimum_and_preference_separate(self):
        for text in ("在读博士或硕士", "在读硕士研究生/博士研究生"):
            self.assertEqual(parse(text)["requirements"]["education"], {"min": "master", "preferred": None})
        self.assertEqual(parse("在读硕士或博士优先")["requirements"]["education"],
                         {"min": None, "preferred": "master"})

    def test_coverage_counts_positive_weights_and_preserves_conflicts(self):
        dims = {k: {"score": 100} for k in score.DIMENSIONS}
        weights = dict.fromkeys(score.DIMENSIONS, 0)
        weights['location'] = 10
        for verdict, grade in (("eligible", "needs_check"), ("ineligible", "ineligible")):
            total = score.total(dims, weights, verdict)
            self.assertEqual((total['score'], total['grade'], total['complete']), (None, grade, True))
        weights['skills'] = 10
        dims['skills']['score'] = 0  # a known mismatch still supplies information
        self.assertEqual(score.total(dims, weights, "eligible")['score'], 50)

    def test_sparse_results_are_consistent_in_validation_trial_report_and_screen(self):
        profile = profile_from("tech")
        job = parse("职位名称：样本核验员\n工作地点：深圳")
        record = score.score_job(job, profile, VOCABULARY, now=NOW)
        self.assertEqual(score.validate(record, job, profile, VOCABULARY), [])
        self.assertEqual(score.trial_total(record, record['weights']), record['total'])
        page = report.build([report.entry(record, job, False)], profile, NOW.isoformat(), VOCABULARY)
        self.assertIn("暂不计算总分", page)
        self.assertNotIn("四舍五入为 <strong>None", page)
        row = screen._row(1, job, record, {'action': 'created', 'jd_changed': False, 'files': []}, [])
        self.assertIn("待确认（评分信息不足）", row['line'])


if __name__ == "__main__":
    unittest.main()
