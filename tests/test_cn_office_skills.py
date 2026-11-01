"""H29: office applications are skills; ordinary nouns and employers are not."""
import unittest

from jobsearch_cn import jd_parser, schema


class OfficeSkills(unittest.TestCase):
    def assert_skills(self, text, expected):
        [job], _ = jd_parser.parse_text(text)
        self.assertEqual(job["requirements"]["skills"], expected)
        self.assertEqual(schema.validate(job), [])
        if not expected:
            self.assertNotIn("requirements.skills", job["evidence"])
        return job

    def test_application_names_and_software_context(self):
        for text, expected in (
                ("行政助理\n技能要求：熟练使用 Word、Excel、PPT 等办公软件。", ["Word", "Excel", "PPT"]),
                ("人事专员\n需掌握word文档排版，能使用powerpoint制作演示文稿。", ["Word", "PowerPoint"]),
                ("市场助理\n熟悉 Office 办公套件和 WPS。", ["Office", "WPS"]),
                ("运营助理\n办公软件：Microsoft Word、Microsoft Excel、Microsoft PowerPoint。",
                 ["Microsoft Word", "Microsoft Excel", "Microsoft PowerPoint"]),
                ("工具要求：Microsoft Office / MS Office / WPS Office / Microsoft Visio。",
                 ["Microsoft Office", "MS Office", "WPS Office", "Microsoft Visio"]),
                ("岗位要求：掌握 Visio 绘制流程图。", ["Visio"]),
                ("技能：Word", ["Word"]),
                ("熟练使用office。", ["Office"]),
                ("Word、Excel、PPT", ["Word", "Excel", "PPT"]),
                ("Word, Excel, PowerPoint", ["Word", "Excel", "PowerPoint"]),
                ("熟悉Word / Office", ["Word", "Office"]),
                ("Proficient in Word and Excel.", ["Word", "Excel"]),
                ("Experience with Office software is required.", ["Office"]),
                ("Prepare Word documents for the team.", ["Word"]),
                ("熟练用Word为公司编写报告", ["Word"]),
                ("使用 Word 制作公司报告", ["Word"])):
            with self.subTest(text=text):
                self.assert_skills(text, expected)

    def test_ordinary_english_and_identifier_boundaries(self):
        for text in ("Every word matters.", "Please use the word clearly.", "Communication skills: choose each word carefully.",
                     "Knowledge of every word is helpful.", "Experience with word of mouth marketing.",
                     "Word choice is important.", "Word processing skills are useful.", "Please check the word count.",
                     "Office hours are flexible.", "Skills: familiar with office hours.", "We work from the office.",
                     "Familiar with office administration.", "Experience with office operations is required.",
                     "Familiar with word embeddings.", "Experience with word puzzles.",
                     "We excel at customer support.", "Candidates should excel in teamwork.",
                     "Our Office is downtown.", "Head office is in Shanghai.", "Office supplies are provided.",
                     "password keyword WordPress Office365 MyOffice WPSX VisioPro PowerPointer PPTX Excellent",
                     "普通正文只有 word 和 office，没有软件要求。", "word / office"):
            with self.subTest(text=text):
                self.assert_skills(text, [])

    def test_review_english_verbs_do_not_establish_software_meaning(self):
        for text in ("Experience in word tokenization is required.",
                     "Use word distributions to cluster text.",
                     "Knowledge of word matching helps.",
                     "Familiar with office routines.",
                     "Experience with office moving projects.",
                     "Use office facilities efficiently.",
                     "Prepare office documents for filing.",
                     "Rent an office suite downtown.",
                     "熟悉 word tokenization。", "掌握 office procedures。"):
            with self.subTest(text=text):
                self.assert_skills(text, [])
        for text, expected in (("Proficient in Word and Excel.", ["Word", "Excel"]),
                               ("Prepare Word documents.", ["Word"]),
                               ("Use Microsoft Word.", ["Microsoft Word"]),
                               ("办公软件：Word、Office", ["Word", "Office"])):
            with self.subTest(text=text):
                self.assert_skills(text, expected)

    def test_review_software_use_for_company_business_is_not_a_company_name(self):
        for text, expected in (("熟练使用Excel统计公司回款数据。", ["Excel"]),
                               ("使用Excel维护公司台账。", ["Excel"]),
                               ("使用PPT演示公司方案。", ["PPT"]),
                               ("使用PowerPoint呈现公司业务。", ["PowerPoint"]),
                               ("熟练使用Excel分析公司的销售数据。", ["Excel"]),
                               ("使用Word汇总公司纪要。", ["Word"]),
                               ("了解如何用Excel分析集团经营数据。", ["Excel"]),
                               ("了解使用PPT介绍集团业务的方法。", ["PPT"])):
            with self.subTest(text=text):
                job = self.assert_skills(text, expected)
                self.assertEqual(job["evidence"]["requirements.skills"]["text"], text.rstrip("。"))
        self.assert_skills("公司：Excel信息有限公司\n熟练使用Excel。", ["Excel"])
        self.assert_skills("了解Excel信息有限公司的业务。", [])

    def test_company_names_do_not_supply_skills(self):
        for name in ("Word空间有限公司", "Office咨询有限公司", "Excel信息有限公司", "PPT文化有限公司",
                     "PowerPoint软件有限公司", "WPS服务有限公司", "Visio教育有限公司", "Microsoft Office科技有限公司"):
            for text in (f"公司：{name}\n岗位要求：负责客户接待。", f"欢迎加入{name}。", f"需要了解{name}的业务。"):
                with self.subTest(text=text):
                    self.assert_skills(text, [])
        for text in ("公司：Word\n岗位要求：负责接待。", "Company: Office Works\nReception duties.",
                     "Employer: Excel Works\nReception duties.", "Join WPS Labs Ltd.", "Office Solutions Inc.",
                     "欢迎加入 Excel 信息有限公司。"):
            with self.subTest(text=text):
                self.assert_skills(text, [])

    def test_real_requirement_after_company_or_office_hours_keeps_its_evidence(self):
        text = "公司：Word空间有限公司\nOffice hours are flexible.\n技能要求：熟悉 Word、Excel、WPS Office。"
        job = self.assert_skills(text, ["Word", "Excel", "WPS Office"])
        self.assertEqual(job["company"], "Word空间有限公司")
        self.assertEqual(job["evidence"]["requirements.skills"],
                         {"text": "技能要求：熟悉 Word、Excel、WPS Office", "method": "rule"})
        self.assert_skills("公司：Word\n技能要求：熟悉Word。", ["Word"])
        job = self.assert_skills("招聘助理实习生\nExcel人才｜上海｜180元/天｜3天/周｜4个月｜本科\n任职要求：熟悉Word。", ["Word"])
        self.assertEqual(job["company"], "Excel人才")

    def test_negation_and_alternatives_still_apply(self):
        self.assert_skills("无需Word排版经验；不要求Office或WPS；不必掌握Visio。", [])
        job = self.assert_skills("熟悉 Word 或 WPS Office。", ["Word", "WPS Office"])
        self.assertEqual(job["requirements"]["skill_alternatives"], [["Word", "WPS Office"]])
        job = self.assert_skills("熟悉 WPS 或 Word。", ["WPS", "Word"])
        self.assertEqual(job["requirements"]["skill_alternatives"], [["WPS", "Word"]])
        job = self.assert_skills("熟悉 PPT 或 PowerPoint。", ["PPT", "PowerPoint"])
        self.assertEqual(job["requirements"]["skill_alternatives"], [])
        job = self.assert_skills("熟悉 Microsoft Office 或 MS Office。", ["Microsoft Office", "MS Office"])
        self.assertEqual(job["requirements"]["skill_alternatives"], [])


if __name__ == "__main__":
    unittest.main()
