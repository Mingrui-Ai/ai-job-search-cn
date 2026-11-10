"""Synthetic regressions for the seven issues found during the first ATS collection."""
import unittest

from jobsearch_cn import jd_parser, match, report, score, screen
from tests.test_cn_score import NOW, VOCABULARY, profile_from


def parse(text):
    return jd_parser.parse_text(text, now=NOW, single=True)[0][0]


def reviewer_candidate():
    profile = profile_from("tech")
    profile["graduation"]["year"] = 2026
    profile["education"] = [e for e in profile["education"] if e["level"] == "bachelor"]
    profile["target"]["employment_types"] = ["internship", "campus", "experienced"]
    return profile


class ReviewRegressions(unittest.TestCase):
    """Codex B's five synthetic counterexamples, including both explicit cohort forms."""

    def test_p2_salary_suffixes_preserve_explicit_rates(self):
        for text, expected in (("180/天起", (180, "CNY/day")),
                               ("180/天包午餐", (180, "CNY/day")),
                               ("35/小时可协商", (35, "CNY/hour"))):
            with self.subTest(text=text):
                job = parse("职位名称：样品记录实习生\n工作地点：深圳\n薪资：" + text)
                self.assertIsNotNone(job["salary"])
                self.assertEqual((job["salary"]["min"], job["salary"]["unit"]), expected)
                if expected[1] == "CNY/day":
                    self.assertIsNotNone(score.score_job(job, reviewer_candidate(), VOCABULARY, now=NOW)["total"]["score"])

    def test_p2_campus_heading_must_not_override_explicit_cohorts(self):
        for requirement in ("面向2026/2027届毕业生", "2026年8月-2027年7月毕业"):
            with self.subTest(requirement=requirement):
                job = parse("【27校招】样本研究员\n任职资格\n" + requirement + "，本科及以上学历。")
                self.assertEqual(job["requirements"]["graduation"], {"years": [2026, 2027], "strict": True})
                self.assertEqual(job["evidence"]["requirements.graduation"]["text"], requirement)
                self.assertNotEqual(match.filter_job(job, reviewer_candidate())["verdict"], "ineligible")

    def test_p2_recruitment_activity_is_not_candidate_cohort(self):
        job = parse("职位名称：招聘流程专员\n工作性质：社会招聘\n工作地点：深圳\n工作职责\n"
                    "负责2027校园招聘活动的组织与执行。\n任职资格\n本科及以上学历。")
        self.assertIsNone(job["requirements"]["graduation"])
        self.assertNotIn("requirements.graduation", job["evidence"])
        self.assertNotEqual(match.filter_job(job, reviewer_candidate())["verdict"], "ineligible")

    def test_p2_education_describing_other_people_is_not_requirement(self):
        for context in ("工作职责\n协助在读硕士/博士整理实验数据。", "团队介绍\n团队现有在读硕士/博士十余人。"):
            with self.subTest(context=context):
                job = parse("职位名称：课程助教\n" + context + "\n任职资格\n本科及以上学历。")
                self.assertEqual(job["requirements"]["education"]["min"], "bachelor")
                self.assertEqual(job["evidence"]["requirements.education"]["text"], "本科及以上")
                self.assertNotEqual(match.filter_job(job, reviewer_candidate())["verdict"], "ineligible")

    def test_p3_collected_headers_do_not_turn_navigation_into_titles(self):
        for first in ("招聘首页", "欢迎加入我们"):
            with self.subTest(first=first):
                job = parse(first + "\n招聘频道：校园招聘\n工作地点：苏州\n工作职责\n协助登记样品。")
                self.assertIsNone(job["title"])
                self.assertNotIn("title", job["evidence"])


class ReviewBoundaries(unittest.TestCase):
    def test_salary_modifiers_without_labels_and_nonunit_words(self):
        for text, expected in (("3-4K", (3000, "CNY/month")), ("200/天", (200, "CNY/day")),
                               ("180/天起", (180, "CNY/day")), ("180/天包午餐", (180, "CNY/day")),
                               ("35/小时可协商", (35, "CNY/hour")), ("180/日税前", (180, "CNY/day")),
                               ("180/天提供住宿", (180, "CNY/day")), ("35/小时根据经验调整", (35, "CNY/hour"))):
            with self.subTest(text=text):
                salary = parse(text)["salary"]
                self.assertIsNotNone(salary)
                self.assertEqual((salary["min"], salary["unit"]), expected)
        for text in ("薪资面议，CET-6/日语N2", "薪资面议，版本6/时间管理"):
            with self.subTest(text=text):
                self.assertTrue(parse(text)["salary"]["negotiable"])

    def test_campus_year_needs_candidate_or_header_context(self):
        for text in ("招聘频道：2027校园招聘", "工作性质：27校招", "2027校园招聘",
                     "任职资格\n面向2027校园招聘应届毕业生。"):
            with self.subTest(text=text):
                self.assertEqual(parse(text)["requirements"]["graduation"], {"years": [2027], "strict": True})
        for text in ("工作职责\n2027校园招聘活动执行。", "团队介绍\n2027校园招聘",
                     "任职资格\n有参与2027校园招聘活动的经验。", "负责组织2027校园招聘。"):
            with self.subTest(text=text):
                self.assertIsNone(parse(text)["requirements"]["graduation"])
        job = parse("【27校招】样本研究员\n任职资格\n2026/2027届毕业生优先。")
        self.assertEqual(job["requirements"]["graduation"], {"years": [2026, 2027], "strict": False})

    def test_student_education_needs_requirements_or_explicit_degree_statement(self):
        for text in ("工作职责\n协助在读硕士/博士整理实验数据。", "团队介绍\n团队现有在读硕士/博士十余人。",
                     "工作职责\n在读硕士/博士是服务对象。", "团队介绍\n在读硕士或博士优先担任组长。",
                     "团队现有在读硕士十余人。"):
            with self.subTest(text=text):
                self.assertIsNone(parse(text)["requirements"]["education"])
        for text in ("学历要求：在读硕士/博士", "要求在读硕士或博士", "候选人须在读硕士/博士",
                     "团队介绍\n有多名资深同事。\n任职资格\n在读硕士/博士。",
                     "任职资格\n在读硕士/博士。\n团队介绍\n团队现有在读博士十余人。"):
            with self.subTest(text=text):
                self.assertEqual(parse(text)["requirements"]["education"], {"min": "master", "preferred": None})

    def test_navigation_with_metadata_still_allows_later_priced_role(self):
        for first in ("招聘首页", "欢迎加入我们", "职位列表", "联系我们"):
            with self.subTest(first=first):
                job = parse(first + "\n招聘频道：校园招聘\n工作地点：苏州\n样本研究员 3-4K\n工作职责\n整理样品。")
                self.assertEqual(job["title"], "样本研究员")
        for title in ("首页运营实习生", "职位搜索算法工程师"):
            with self.subTest(title=title):
                self.assertEqual(parse(title + "\n招聘频道：校园招聘\n工作地点：苏州")["title"], title)


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
