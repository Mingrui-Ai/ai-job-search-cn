"""H12 header boundaries, using new synthetic text (not the V6 holdout).

The planner runs V6 and the user's real JDs independently. These cases test
tag-cell meaning, evidence, and exclusion of body prose and unrelated rows.
"""
import unittest

from jobsearch_cn import jd_parser, schema


def parse(text):
    [record], _ = jd_parser.parse_text(text)
    return record


class HeaderLabels(unittest.TestCase):
    def test_pipe_styles_and_city_cells_do_not_read_company_or_district_names(self):
        for separator in ("｜", " | "):
            with self.subTest(separator=separator):
                row = separator.join(("南京示例花栈文化", "广州·南京路/深圳/广州", "180-220元/天",
                                      "4天/周", "5个月", "本科"))
                record = parse("品牌策划实习生\n" + row)
                self.assertEqual(record["company"], "南京示例花栈文化")
                self.assertEqual(record["cities"], ["广州", "深圳"])
                self.assertEqual(record["requirements"]["education"], {"min": "bachelor", "preferred": None})
                self.assertEqual(record["evidence"]["cities"]["text"], "广州·南京路/深圳/广州")
                self.assertEqual(record["evidence"]["requirements.education"], {"text": "本科", "method": "rule"})
                self.assertEqual(schema.validate(record), [])

    def test_each_supported_bare_education_word_is_a_tag_only(self):
        for word, level in (("大专", "associate"), ("专科", "associate"), ("本科", "bachelor"),
                            ("学士", "bachelor"), ("硕士", "master"), ("研究生", "master"), ("博士", "phd")):
            for separator in (" ", "｜"):
                with self.subTest(word=word, separator=separator):
                    record = parse("人力资源实习生\n" + separator.join(("成都", "4天/周", "5个月", word)))
                    self.assertEqual(record["requirements"]["education"], {"min": level, "preferred": None})
                    self.assertEqual(record["cities"], ["成都"])
            with self.subTest(body_word=word):
                record = parse("人力资源实习生\n岗位职责\n" + word)
                self.assertIsNone(record["requirements"]["education"])

    def test_tag_search_follows_the_title_beyond_page_line_30(self):
        for navigation in (0, 24):
            with self.subTest(navigation=navigation):
                # With navigation the row is line 41; its distance from the
                # selected title is unchanged. None of this text comes from V6.
                text = "\n".join(["首页"] * navigation + ["采购助理实习生 180-220元/天"]
                                 + ["收藏职位"] * 15
                                 + ["示例叶舟商贸｜苏州｜180-220元/天｜4天/周｜5个月｜大专",
                                    "岗位职责", "协助维护供应商资料。"])
                record = parse(text)
                self.assertEqual(record["company"], "示例叶舟商贸")
                self.assertEqual(record["cities"], ["苏州"])
                self.assertEqual(record["requirements"]["min_months"], 5)
                self.assertEqual(record["requirements"]["education"], {"min": "associate", "preferred": None})
                self.assertEqual(schema.validate(record), [])

    def test_late_explicit_title_with_whitespace_tags(self):
        text = "\n".join(["首页"] * 45 + ["职位名称：采购助理实习生", "苏州 工业园区 4天/周 5个月 硕士"])
        record = parse(text)
        self.assertEqual(record["cities"], ["苏州"])
        self.assertEqual(record["requirements"]["min_months"], 5)
        self.assertEqual(record["requirements"]["education"], {"min": "master", "preferred": None})
        self.assertIsNone(record["company"])

    def test_body_labels_keep_priority_and_preferences_keep_their_meaning(self):
        header = "采购助理实习生\n示例叶舟商贸｜苏州｜4天/周｜5个月｜本科\n"
        record = parse(header + "工作地点：南京\n任职要求：硕士学历，博士优先")
        self.assertEqual(record["cities"], ["南京"])
        self.assertEqual(record["requirements"]["education"], {"min": "master", "preferred": "phd"})
        self.assertEqual(record["evidence"]["cities"]["text"], "工作地点：南京")
        record = parse(header + "任职要求：硕士优先")
        self.assertEqual(record["requirements"]["education"], {"min": "bachelor", "preferred": "master"})
        self.assertEqual(record["evidence"]["requirements.education"]["text"], ["本科", "硕士优先"])

    def test_header_scope_rejects_body_intro_and_sentences_with_pipes(self):
        row = "示例叶舟商贸｜苏州｜4天/周｜5个月｜本科"
        for prefix in ("岗位职责", "任职要求：", "公司介绍", "负责整理文档。", "无需相关经验",
                       "看过该职位的人还看了", "推荐职位", "公司基本信息"):
            with self.subTest(prefix=prefix):
                record = parse("采购助理实习生\n" + prefix + "\n" + row)
                self.assertIsNone(record["company"])
                self.assertEqual(record["cities"], [])
                self.assertIsNone(record["requirements"]["education"])
                self.assertIsNone(record["requirements"]["min_months"])
        for sentence in ("负责采购跟单｜苏州｜4天/周｜5个月｜本科",
                         "请保证到岗｜苏州｜4天/周｜5个月｜本科",
                         "示例叶舟商贸｜可以在苏州到岗｜4天/周｜5个月｜本科",
                         "示例叶舟商贸｜苏州｜4天/周｜5个月内入职｜本科",
                         "可以 4天/周 到岗 5个月 内入职"):
            with self.subTest(sentence=sentence):
                record = parse("采购助理实习生\n" + sentence)
                self.assertIsNone(record["company"])
                self.assertEqual(record["cities"], [])
                self.assertIsNone(record["requirements"]["education"])
                self.assertIsNone(record["requirements"]["min_months"])

    def test_unlimited_education_and_unknown_city_are_not_invented(self):
        record = parse("采购助理实习生\n苏州｜4天/周｜5个月｜学历不限")
        self.assertEqual(record["requirements"]["education"], {"min": "none", "preferred": None})
        # M2-4a's explicit no-minimum statement also outranks a bare tag.
        record = parse("采购助理实习生\n苏州｜4天/周｜5个月｜本科\n任职要求：学历不限，硕士优先")
        self.assertEqual(record["requirements"]["education"], {"min": "none", "preferred": "master"})
        self.assertEqual(record["evidence"]["requirements.education"]["text"], ["学历不限", "硕士优先"])
        record = parse("采购助理实习生\n示例叶舟商贸｜虚构城｜4天/周｜5个月｜本科")
        self.assertEqual(record["cities"], [])

    def test_education_or_district_first_is_not_a_company(self):
        for first in ("学士", "西湖区"):
            with self.subTest(first=first):
                record = parse(f"采购助理实习生\n{first}｜杭州｜4天/周｜5个月")
                self.assertIsNone(record["company"])
                self.assertEqual(record["cities"], ["杭州"])

    def test_conflicting_months_still_remain_empty(self):
        record = parse("采购助理实习生\n示例叶舟商贸｜苏州｜4天/周｜5个月｜本科\n"
                       "岗位要求：连续实习6个月以上")
        self.assertIsNone(record["requirements"]["min_months"])
        self.assertNotIn("requirements.min_months", record["evidence"])


if __name__ == "__main__":
    unittest.main()
