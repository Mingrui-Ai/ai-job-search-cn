"""Tests for jobsearch_cn/messages.py and `material template / validate / render` for greetings, application
emails and referral requests (M3-4).

These pin: the fictional samples pass and render to text ready to copy; the template is chosen by the JD's
and the profile's directions, falling back to the profile's first direction and then the default; each rule
that fails a message does (an invented number or skill, an unfilled or forbidden placeholder, a placeholder
whose entry is not cited, a hand-typed phone, a promise of days, months or a start the profile's availability
does not back, banned wording, a slot missing, repeated or out of order, the length limits); the warnings; a
user template can lower a limit and not raise it, a user can add banned words but not remove them, and a
malformed user file is refused; every material command checks a material the same way, and the CV-only ones
refuse a message; the CLI's exit codes.
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MATERIALS = REPO / "tests" / "fixtures" / "cn" / "material"
TECH = MATERIALS / "tech-m3"
OPS = MATERIALS / "ops-m3"

sys.path.insert(0, str(REPO))
from jobsearch_cn import messages, profile, score, vocab  # noqa: E402

VOCABULARY = vocab.load()
TEMPLATES = messages.load_templates()
BANNED = messages.load_banned()
COMMA = "，"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


TECH_PROFILE = load(TECH / "profile" / "profile.json")
TECH_JOB = load(TECH / "job.json")
OPS_PROFILE = load(OPS / "profile" / "profile.json")
OPS_JOB = load(OPS / "job.json")
GREETING = load(TECH / "greeting-1.json")
EMAIL = load(TECH / "email-1.json")
REFERRAL = load(TECH / "referral-1.json")
OPS_GREETING = load(OPS / "greeting-1.json")


def check(record, profile_data=TECH_PROFILE, job=TECH_JOB, templates=TEMPLATES, banned=BANNED):
    return messages.validate(record, profile_data, VOCABULARY, job, templates, banned)


def errors_of(record, **kwargs) -> list:
    return check(record, **kwargs)[0]


def with_segment(record, index, text, refs=None, slot=None) -> dict:
    data = copy.deepcopy(record)
    data["segments"][index]["text"] = text
    if refs is not None:
        data["segments"][index]["refs"] = list(refs)
    if slot is not None:
        data["segments"][index]["slot"] = slot
    return data


class Samples(unittest.TestCase):
    def test_the_samples_are_valid_with_no_warnings(self):
        self.assertEqual(profile.validate(OPS_PROFILE), [])
        for record in (GREETING, EMAIL, REFERRAL):
            self.assertEqual(check(record), ([], []), record["kind"])
        self.assertEqual(check(OPS_GREETING, profile_data=OPS_PROFILE, job=OPS_JOB), ([], []))

    def test_the_ops_profile_is_the_m2_ops_profile_with_ids(self):
        original = load(REPO / "tests" / "fixtures" / "cn" / "profile" / "ops" / "profile.json")
        stripped = copy.deepcopy(OPS_PROFILE)
        for section in ("education", "certificates"):
            for entry in stripped[section]:
                del entry["id"]
        self.assertEqual(stripped, original)

    def test_render_fills_the_placeholders(self):
        text = messages.render(GREETING, TECH_PROFILE, TECH_JOB)
        self.assertTrue(text.startswith("您好" + COMMA + "我是示例理工大学计算机科学与技术专业的硕士生"), text)
        self.assertIn("后端开发实习生", text)
        self.assertIn("2026年11月15日起到岗", text)
        self.assertNotIn("{", text)
        self.assertNotIn("\n", text)
        email = messages.render(EMAIL, TECH_PROFILE, TECH_JOB)
        self.assertTrue(email.startswith("标题：应聘后端开发实习生-李明-示例理工大学\n\n您好！\n\n"), email)
        self.assertIn("电话：13800000000", email)
        self.assertEqual(len(messages.render(REFERRAL, TECH_PROFILE, TECH_JOB).splitlines()), 4)

    def test_every_built_in_template_covers_the_three_kinds_within_the_hard_limits(self):
        self.assertEqual(set(TEMPLATES), {"tech", "data", "product", "ops", "default"})
        for direction, template in TEMPLATES.items():
            for kind in messages.KINDS:
                self.assertLessEqual(template[kind]["max_chars"], messages.HARD_LIMITS[kind], (direction, kind))
            self.assertIn("signature", [slot["slot"] for slot in template["email"]["slots"]])


class Choose(unittest.TestCase):
    def test_the_jd_direction_the_candidate_wants(self):
        self.assertEqual(messages.choose(TECH_JOB, TECH_PROFILE, VOCABULARY, TEMPLATES)[0], "tech")
        self.assertEqual(messages.choose(OPS_JOB, OPS_PROFILE, VOCABULARY, TEMPLATES)[0], "ops")

    def test_a_direction_given_wins(self):
        self.assertEqual(messages.choose(TECH_JOB, TECH_PROFILE, VOCABULARY, TEMPLATES, "product"),
                         ("product", "按 --direction 指定"))
        with self.assertRaises(messages.TemplateError):
            messages.choose(TECH_JOB, TECH_PROFILE, VOCABULARY, TEMPLATES, "astronaut")

    def test_a_direction_given_without_a_template_uses_the_default(self):
        # Any skill vocabulary group is a direction; general too, though no profile may want it.
        for direction in ("design", "market", "finance", "hr", "general"):
            self.assertEqual(messages.choose(TECH_JOB, TECH_PROFILE, VOCABULARY, TEMPLATES, direction),
                             ("default", f"按 --direction 指定 {direction}，这个方向还没有模板，用通用模板 default"))
        result = messages.template_for(TECH_JOB, TECH_PROFILE, VOCABULARY, TEMPLATES, "email", "design")
        self.assertEqual((result["direction"], result["template"]), ("default", "default/email@1"))

    def test_no_shared_direction_takes_the_profiles_first(self):
        direction, why = messages.choose(OPS_JOB, TECH_PROFILE, VOCABULARY, TEMPLATES)
        self.assertEqual(direction, "tech")
        self.assertIn("第一个求职方向", why)

    def test_a_direction_without_a_template_falls_back_to_default(self):
        data = copy.deepcopy(TECH_PROFILE)
        data["target"]["directions"] = ["finance"]
        self.assertEqual(messages.choose(TECH_JOB, data, VOCABULARY, TEMPLATES)[0], "default")
        data["target"]["directions"] = []
        self.assertEqual(messages.choose(TECH_JOB, data, VOCABULARY, TEMPLATES),
                         ("default", "档案没写求职方向，用通用模板 default"))

    def test_template_for_gives_the_spec_and_its_id(self):
        result = messages.template_for(TECH_JOB, TECH_PROFILE, VOCABULARY, TEMPLATES, "email")
        self.assertEqual(result["template"], "tech/email@1")
        self.assertEqual(result["spec"]["max_chars"], 600)
        self.assertEqual(result["spec"]["subject_max_chars"], 40)


class Invented(unittest.TestCase):
    def test_a_number_not_in_what_the_segment_cites(self):
        errors = errors_of(with_segment(GREETING, 1, "用 Go 重构订单查询接口" + COMMA + "延迟降低 62%。"))
        self.assertEqual(len(errors), 1)
        self.assertIn("segments[1].text: the number '62%'", errors[0])

    def test_a_number_cited_from_another_entry_does_not_count(self):
        errors = errors_of(with_segment(GREETING, 1, "覆盖 20 门课程。", ["exp-1"]))
        self.assertIn("the number '20'", errors[0])
        self.assertEqual(errors_of(with_segment(GREETING, 1, "覆盖 20 门课程。", ["proj-1"])), [])

    def test_a_skill_the_profile_does_not_have(self):
        errors = errors_of(with_segment(GREETING, 1, "熟悉 Kubernetes 的部署。", ["exp-1"]))
        self.assertEqual(errors, ["segments[1].text: the skill 'Kubernetes' is neither in the profile's skills "
                                  "nor in the cited entries"])

    def test_a_skill_the_job_asks_for_is_not_the_candidates(self):
        job = copy.deepcopy(TECH_JOB)
        job["title"] = "Kubernetes 开发实习生"
        errors = errors_of(with_segment(GREETING, 3, "我也熟悉 Kubernetes。"), job=job)
        self.assertTrue(any("'Kubernetes'" in error for error in errors), errors)
        # Citing the job does not make the skill in its title the candidate's.
        errors = errors_of(with_segment(GREETING, 3, "我也熟悉 Kubernetes。", ["job"]), job=job)
        self.assertEqual(errors, ["segments[3].text: the skill 'Kubernetes' is neither in the profile's skills "
                                  "nor in the cited entries"])

    def test_numbers_inside_filled_placeholders_are_data(self):
        data = with_segment(GREETING, 2, "每周{availability.days_per_week}天。", ["availability"])
        self.assertEqual(errors_of(data), [])


class Placeholders(unittest.TestCase):
    def test_an_unknown_entry_or_field(self):
        errors = errors_of(with_segment(GREETING, 0, "您好" + COMMA + "我是{edu-9.school}的学生。", ["edu-1"]))
        self.assertEqual(errors, ["segments[0].text: {edu-9.school}: no profile entry with id 'edu-9'"])
        errors = errors_of(with_segment(GREETING, 0, "您好" + COMMA + "我的绩点是{edu-1.gpa}。", ["edu-1"]))
        self.assertIn("an education entry's placeholders are school, major, level", errors[0])
        errors = errors_of(with_segment(GREETING, 0, "您好" + COMMA + "{name}", []))
        self.assertIn("is not a placeholder", errors[0])

    def test_the_placeholders_entry_must_be_cited(self):
        errors = errors_of(with_segment(GREETING, 0, "您好" + COMMA + "我想应聘{job.title}。", ["edu-1"]))
        self.assertEqual(errors, ["segments[0].refs: must include 'job', whose placeholder the text uses"])

    def test_a_ref_the_profile_does_not_have_or_notes(self):
        errors = errors_of(with_segment(GREETING, 1, "做过订单查询接口。", ["exp-9"]))
        self.assertEqual(errors, ["segments[1].refs[0]: no profile entry with id 'exp-9'"])
        errors = errors_of(with_segment(GREETING, 1, "做过订单查询接口。", ["exp-1", "notes.md"]))
        self.assertEqual(errors, ["segments[1].refs[1]: a message does not cite notes.md; only a CV's summary does"])

    def test_the_phone_and_email_only_in_an_email_signature(self):
        errors = errors_of(with_segment(GREETING, 3, "电话 {contact.phone}"))
        self.assertIn("belong only in an email's signature segment", errors[0])
        errors = errors_of(with_segment(EMAIL, 5, "电话 {contact.phone}"))
        self.assertIn("belong only in an email's signature segment", errors[0])

    def test_a_job_placeholder_needs_the_stored_job(self):
        errors = errors_of(GREETING, job=None)
        self.assertIn("segments[0].refs[1]: cites the job, but job_id is not in the job store", errors)
        self.assertTrue(any("the job is not in the job store" in error for error in errors), errors)

    def test_a_template_marker_left_in(self):
        for text in ("【这里写结尾】", "期待加入XX公司。", "期待加入xxx团队。", "期待加入××公司。"):
            errors = errors_of(with_segment(GREETING, 3, text))
            self.assertTrue(any("模板标记没有替换" in error for error in errors), (text, errors))
        # Two or more X standing alone; 5xx and XXL-JOB are no marker.
        for text in ("把 5xx 错误率降下来了。", "熟悉 XXL-JOB 调度。"):
            self.assertFalse(any("模板标记" in error for error in errors_of(with_segment(GREETING, 3, text))), text)

    def test_a_brace_left_once_filled(self):
        for text, refs in (("期待{ 回复 }", []), ("我是{{edu-1.school}}的学生。", ["edu-1"])):
            errors = errors_of(with_segment(GREETING, 3, text, refs))
            self.assertEqual(len(errors), 1, (text, errors))
            self.assertIn("once filled it still has a brace", errors[0])
        # A stored value with braces in it would go out as they are.
        job = copy.deepcopy(TECH_JOB)
        job["title"] = "后端开发{待定}实习生"
        errors = errors_of(GREETING, job=job)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("segments[0].text: once filled it still has a brace", errors[0])

    def test_the_github_and_website_placeholders(self):
        data = with_segment(EMAIL, 4, "我的代码都在 {contact.github}。", [], slot="fit")  # in place of availability
        self.assertEqual(check(data), ([], []))
        self.assertIn("我的代码都在 github.com/example。", messages.render(data, TECH_PROFILE, TECH_JOB))
        # In a greeting, a link the platform may block warns, as one typed by hand does.
        self.assertEqual(check(with_segment(GREETING, 3, "代码在 {contact.github}。"))[1],
                         ["segments[3].text: '{contact.github}' - 招呼语里放链接，平台常会屏蔽"])
        self.assertEqual(errors_of(with_segment(GREETING, 3, "主页 {contact.website}。")),
                         ["segments[3].text: {contact.website}: the profile has no contact.website"])


class Availability(unittest.TestCase):
    """What a message promises about the availability, against the profile's own field for each promise
    (tech-m3: from 2026-11-15, 4 days a week, 6 months)."""

    @staticmethod
    def promise(text, profile_data=TECH_PROFILE) -> list:
        return errors_of(with_segment(GREETING, 2, text, ["availability"]), profile_data=profile_data)

    @staticmethod
    def changed(**availability) -> dict:
        data = copy.deepcopy(TECH_PROFILE)
        data["availability"].update(availability)
        return data

    def test_days_and_months_match_their_own_field(self):
        self.assertEqual(self.promise("每周可以到岗 4 天，能连续实习 6 个月。"), [])
        self.assertEqual(self.promise("每周可以到岗5天。"),
                         ["segments[2].text: '5天' is not the profile's availability.days_per_week (4); "
                          "write 4天 or {availability.days_per_week}天"])
        self.assertEqual(self.promise("能连续实习3个月。"),
                         ["segments[2].text: '3个月' is not the profile's availability.months (6); "
                          "write 6个月 or {availability.months}个月"])
        self.assertEqual(len(self.promise("每周 3-4 天。")), 1)  # a range promises each of its ends

    def test_days_and_months_in_chinese_numerals_are_refused(self):
        # 五天 and 三个月 slip past the number check (material.numbers leaves a lone 五 alone), so they are refused.
        for text, quote in (("每周可以到岗五天。", "五天"), ("一周能来两天。", "两天"), ("能连续实习三个月。", "三个月"),
                            ("能实习半年。", "半年"), ("可以实习一年。", "一年")):
            errors = self.promise(text)
            self.assertEqual(len(errors), 1, (text, errors))  # 一周 and 每周 say how often, not how many days
            self.assertIn(f"'{quote}': write ", errors[0])
            self.assertIn("in Arabic digits", errors[0])

    def test_the_digits_of_a_date_vouch_for_no_count(self):
        data = self.changed(start_date="2026-12-07", months=3)
        self.assertIn("'12 个月' is not the profile's availability.months (3)", self.promise("我可以连续实习 12 个月。", data)[0])
        self.assertIn("'7 天' is not the profile's availability.days_per_week (4)",
                      self.promise("我每周可以到岗 7 天，烦请告知申请方式。", data)[0])

    def test_a_promise_the_profile_gives_no_value_for_fails(self):
        data = self.changed(start_date=None, days_per_week=None, months=None)
        for text in ("您好，我随时可以到岗。", "每周可以到岗 4 天。", "能连续实习 6 个月。", "周一至周五都可以实习。"):
            errors = self.promise(text, data)
            self.assertEqual(len(errors), 1, (text, errors))
            self.assertIn("which the profile does not give", errors[0])
        self.assertIn("the profile has no availability.start_date", self.promise("可以{availability.start_date}起到岗。", data)[0])

    def test_a_start_is_written_with_its_placeholder(self):
        self.assertEqual(self.promise("可以{availability.start_date}起到岗。"), [])
        data = self.changed(start_date="2026-12-07")
        for text in ("我明天即可到岗。", "随时可以入职。", "12月1日起可以到岗。", "两周后可以上岗。", "下半年可以开始实习。"):
            errors = self.promise(text, data)
            self.assertEqual(len(errors), 1, (text, errors))
            self.assertIn("promises when you can start; write the date as {availability.start_date}", errors[0])

    def test_a_placeholder_for_another_field_fails(self):
        self.assertIn("days a week are written {availability.days_per_week}天", self.promise("每周{availability.months}天。")[0])
        self.assertIn("months are written {availability.months}个月", self.promise("可以实习{availability.months}年。")[0])

    def test_a_bound_fails_even_at_the_profiles_value(self):
        # Planner, 2026-11-04: the profile's value exactly. The review's cases and other bounds (4 days, 6 months),
        # then V23's on a profile of 3 months.
        cases = [(text, TECH_PROFILE) for text in (
            "每周至少到岗4天。", "能连续实习6个月以上。", "每周可以到岗4天以上。", "能连续实习至少6个月。", "每周可以至少到岗4天。",
            "每周 4 天起。", "每周 4 天左右。", "每周约 4 天。", "最多每周 4 天。", "大约实习 6 个月。", "不超过 6 个月的实习都可以。",
            "实习 6 个月及以上。", "实习 6 个月或更长。", "可以实习 6 个月出头。", "可以 4 天/周以上。",
            "每周至少{availability.days_per_week}天。", "实习{availability.months}个月以上。",
            "可以工作{availability.months}个月以内。")]
        cases += [(text, self.changed(months=3)) for text in ("可以至少实习3个月。", "可以连续实习3个月以上。")]
        for text, data in cases:
            errors = self.promise(text, data)
            self.assertEqual(len(errors), 1, (text, errors))
            self.assertIn("does not promise exactly the profile's availability.", errors[0])
        self.assertEqual(self.promise("每周至少到岗4天。"),
                         ["segments[2].text: '4天': '至少' does not promise exactly the profile's "
                          "availability.days_per_week; write 4天 or {availability.days_per_week}天, with nothing like "
                          "至少, 以上, 起, 左右 or 半"])
        # 至少 before the first of two counts in a clause bounds that one, not the next.
        errors = self.promise("每周 4 天并至少实习 6 个月。")
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("'6 个月': '至少'", errors[0])

    def test_a_unit_that_changes_the_months_fails(self):
        # {availability.months}个半月 renders as 6个半月 while the profile says 6.
        for text, quote in (("可以连续实习{availability.months}个半月。", "'{availability.months}个半月': '个半月'"),
                            ("可以连续实习6个半月。", "'6个半月': '个半月'"),
                            ("实习{availability.months}个多月。", "'{availability.months}个多月': '个多月'"),
                            ("可以实习 6 个多月。", "'6 个多月': '个多月'")):
            errors = self.promise(text)
            self.assertEqual(len(errors), 1, (text, errors))
            self.assertIn(quote, errors[0])
        self.assertEqual(self.promise("实习{availability.months}月。"),
                         ["segments[2].text: '{availability.months}': months are written {availability.months}个月"])

    def test_a_time_by_hand_fails_beside_the_placeholder(self):
        # The placeholder vouches for itself only (the review's two cases, then V23's on a later start).
        for text, data in (("可以{availability.start_date}或明天到岗。", TECH_PROFILE),
                           ("可以{availability.start_date}到岗或随时入职。", TECH_PROFILE),
                           ("可于{availability.start_date}或明天到岗。", self.changed(start_date="2026-12-07"))):
            errors = self.promise(text, data)
            self.assertEqual(len(errors), 1, (text, errors))
            self.assertIn("promises when you can start; write the date as {availability.start_date}", errors[0])
            self.assertRegex(errors[0], r"\(written by hand: '(明天|随时)'\)$")
        self.assertIn("written by hand: '提前'", self.promise("可以提前到岗。")[0])

    def test_the_start_date_placeholder_is_the_earliest_day(self):
        for text in ("可以{availability.start_date}起到岗。", "最早{availability.start_date}到岗。",
                     "{availability.start_date}以后都可以到岗。", "可以{availability.start_date}前往贵司报到。",
                     "{availability.start_date}起每周可以到岗 4 天，实习 6 个月。"):
            self.assertEqual(self.promise(text), [], text)
        for text, word in (("最晚{availability.start_date}到岗。", "最晚"), ("{availability.start_date}之前可以到岗。", "之前"),
                           ("{availability.start_date}前到岗。", "前"), ("{availability.start_date}左右到岗。", "左右"),
                           ("可以{availability.start_date}或更早到岗。", "或更早")):
            errors = self.promise(text)
            self.assertTrue(any(f"'{word}' with {{availability.start_date}}: the profile gives the earliest day" in error
                                for error in errors), (text, errors))

    def test_wording_that_promises_nothing_passes(self):
        # No time next to the verb, a frequency with no count, a wish: nothing to hold against the profile.
        for text in ("期待入职贵司。", "到岗安排可以再沟通。", "每周的安排可以再沟通。", "入职后负责的是订单查询接口。",
                     "周一到周五都方便电话沟通。"):
            self.assertEqual(errors_of(with_segment(GREETING, 3, text)), [], text)
        # Counts in an account of past work are numbers for the cited entry to back, not availability.
        for text in ("每周更新 3 篇推文持续 30 天。", "实习的 3 个月里完成了重构。", "实习期间用 2 个月完成重构。",
                     "入职后效率提升 1.5 倍。"):
            errors = errors_of(with_segment(GREETING, 1, text, ["exp-1"]))
            self.assertTrue(errors, text)
            self.assertFalse(any("availability" in error for error in errors), (text, errors))

    def test_days_written_per_week(self):
        self.assertEqual(self.promise("可以 4 天/周到岗。"), [])
        self.assertIn("'5 天/周' is not the profile's availability.days_per_week (4)", self.promise("可以 5 天/周到岗。")[0])


class Wording(unittest.TestCase):
    def test_a_hand_typed_phone_or_email(self):
        for text in ("我的电话是 13912345678", "邮箱 li.ming2024@example.com"):
            errors = errors_of(with_segment(GREETING, 3, text))
            self.assertEqual(len(errors), 1, errors)  # not an invented number besides
            self.assertIn("typed by hand", errors[0], text)

    def test_a_hand_typed_wechat_or_qq(self):
        for text in ("您好，我的微信号：li_ming_2024，方便时加我。", "可以加微信 shili_handle 联系。", "vx: shili-2024",
                     "WeChat：liming2024", "QQ：123456789", "微信号是 13912345678"):
            errors = errors_of(with_segment(GREETING, 3, text))
            self.assertEqual(len(errors), 1, (text, errors))  # the digits in it are no invented number besides
            self.assertTrue("手写了微信号、QQ 号这类联系方式" in errors[0] or "typed by hand" in errors[0], (text, errors))
        for text in ("做过微信小程序的前端。", "熟悉 wxPython。"):
            self.assertEqual(errors_of(with_segment(GREETING, 3, text)), [], text)

    def test_a_commitment_without_the_availability(self):
        for text in ("可以尽快到岗。", "随时可以入职。", "能实习半年。", "每周可以到岗 4 天。", "可以连续实习 6 个月。"):
            errors = errors_of(with_segment(GREETING, 3, text))
            self.assertTrue(errors, text)
            self.assertIn("without citing 'availability'", errors[0], text)
        # A count the profile gives fails only for want of the citation.
        self.assertEqual(len(errors_of(with_segment(GREETING, 3, "每周可以到岗 4 天。"))), 1)

    def test_m34_sensitive_details_and_boasts_fail(self):
        for text, reason in (("我今年 23 岁。", "敏感个人信息"), ("我是党员。", "敏感个人信息"),
                             ("我没有重大病史。", "敏感个人信息"), ("家庭住址在示例市。", "敏感个人信息"),
                             ("我的后端能力是顶尖的。", "绝对化的自夸")):
            errors = errors_of(with_segment(GREETING, 3, text))
            self.assertTrue(any(reason in error for error in errors), (text, errors))
        self.assertEqual(errors_of(with_segment(GREETING, 3, "祝您工作顺利，身体健康！")), [])

    def test_a_banned_word_the_cited_entry_uses_passes(self):
        banned = copy.deepcopy(BANNED)
        banned["errors"].append({"reason": "test", "compiled": [__import__("re").compile("订单")]})
        self.assertEqual(errors_of(GREETING, banned=banned), [])  # exp-1 itself says 订单
        errors = errors_of(with_segment(GREETING, 3, "订单系统很有意思。"), banned=banned)
        self.assertEqual(errors, ["segments[3].text: '订单' - test"])

    def test_cliches_salary_and_links_warn(self):
        self.assertEqual(check(with_segment(GREETING, 3, "在吗？想聊聊。"))[1],
                         ["segments[3].text: '在吗' - 套话或不礼貌的开头"])
        self.assertEqual(check(with_segment(GREETING, 3, "亲" + COMMA + "期待回复。"))[1],
                         ["segments[3].text: '亲' - 套话或不礼貌的开头"])
        self.assertEqual(check(with_segment(GREETING, 3, "我亲自写了简历。"))[1], [])
        self.assertEqual(check(with_segment(REFERRAL, 3, "想问下这个岗位的薪资。"))[1],
                         ["segments[3].text: '薪资' - 内推请求里提薪资"])
        self.assertEqual(check(with_segment(GREETING, 3, "作品见 https://example.com"))[1],
                         ["segments[3].text: 'https://' - 招呼语里放链接，平台常会屏蔽"])
        self.assertEqual(check(with_segment(EMAIL, 5, "作品见 https://example.com"))[1], [])


class Shape(unittest.TestCase):
    def test_slots_missing_repeated_out_of_order_or_unknown(self):
        data = copy.deepcopy(GREETING)
        del data["segments"][3]
        self.assertEqual(errors_of(data), ["segments: the required 'closing' segment is missing"])
        data = copy.deepcopy(GREETING)
        data["segments"][0], data["segments"][1] = data["segments"][1], data["segments"][0]
        self.assertIn("segments[1].slot: 'opening' comes after 'evidence'", errors_of(data)[0])
        data = copy.deepcopy(GREETING)
        data["segments"][1:1] = [copy.deepcopy(GREETING["segments"][1])] * 2
        self.assertEqual(errors_of(data)[0], "segments[3].slot: at most 2 'evidence' segment(s)")
        self.assertIn("must be one of opening", errors_of(with_segment(GREETING, 3, "谢谢", slot="ps"))[0])

    def test_the_greeting_length_limit(self):
        long = with_segment(GREETING, 3, "期待和您进一步沟通" * 5)
        errors = errors_of(long)
        self.assertEqual(len(errors), 1)
        self.assertRegex(errors[0], r"segments: \d+ characters once filled; the limit for a greeting is 150")

    def test_the_email_subject(self):
        data = copy.deepcopy(EMAIL)
        data["subject"] = None
        self.assertIn("subject: an email needs a subject {text, refs}", errors_of(data))
        data["subject"] = {"text": "应聘{job.title}" + "很想加入贵司" * 6, "refs": ["job"]}
        self.assertRegex(errors_of(data)[0], r"subject: \d+ characters once filled; the limit is 40")
        data = copy.deepcopy(GREETING)
        data["subject"] = {"text": "你好", "refs": []}
        self.assertEqual(errors_of(data), ["subject: must be null for a greeting"])

    def test_the_header(self):
        data = copy.deepcopy(GREETING)
        data["template"] = "ops/greeting@1"
        self.assertEqual(errors_of(data), ["template: must be 'tech/greeting@1' (the direction and kind of this material)"])
        data["direction"] = "astronaut"
        self.assertIn("direction: must be one of", errors_of(data)[0])
        data = copy.deepcopy(GREETING)
        data["kind"] = "poster"
        self.assertEqual(errors_of(data)[-1], "kind: must be one of greeting, email, referral")
        data = copy.deepcopy(GREETING)
        data["extra"] = 1
        self.assertIn("extra: unknown field", errors_of(data))
        for named in ("tech/greeting@abc", "tech/greeting@0", "tech/greeting@", "tech/greeting@1.5", "tech/greeting@-1"):
            data = copy.deepcopy(GREETING)
            data["template"] = named
            self.assertEqual(errors_of(data), ["template: the revision after @ must be a positive integer, "
                                               "as in 'tech/greeting@1'"], named)

    def test_a_newer_template_or_a_changed_profile_warns(self):
        data = copy.deepcopy(GREETING)
        data["template"] = "tech/greeting@2"  # written to a user's revision 2, which is gone
        self.assertEqual(check(data)[1], ["template: written to tech/greeting@2, the template is now "
                                          "tech/greeting@1; check the slots still fit"])
        changed = copy.deepcopy(TECH_PROFILE)
        changed["skills"][0]["level"] = "expert"
        self.assertNotEqual(score.profile_hash(changed), GREETING["profile_hash"])
        self.assertIn("profile_hash: the profile has changed", check(GREETING, profile_data=changed)[1][0])


class UserFiles(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.data)
        self.user = self.data / "templates" / "messages"
        self.user.mkdir(parents=True)

    def write(self, name, doc):
        (self.user / name).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def test_a_user_template_can_lower_a_limit_but_not_raise_it(self):
        tech = copy.deepcopy(messages._read(messages.BUILTIN / "tech.json"))
        tech["greeting"]["max_chars"] = 100
        tech["referral"]["max_chars"] = 5000
        tech["email"]["subject_max_chars"] = 999
        self.write("tech.json", tech)
        templates = messages.load_templates(self.data)
        self.assertEqual(templates["tech"]["greeting"]["max_chars"], 100)
        self.assertEqual(templates["tech"]["referral"]["max_chars"], 300)
        self.assertEqual(templates["tech"]["email"]["subject_max_chars"], 40)
        self.assertIn("the limit for a greeting is 100", errors_of(GREETING, templates=templates)[0])

    def test_a_user_can_add_a_direction(self):
        finance = copy.deepcopy(messages._read(messages.BUILTIN / "default.json"))
        finance["direction"] = "finance"
        self.write("finance.json", finance)
        self.assertIn("finance", messages.load_templates(self.data))

    def test_a_malformed_user_template_is_refused(self):
        self.write("tech.json", {"version": 1, "direction": "data"})
        with self.assertRaises(messages.TemplateError):
            messages.load_templates(self.data)
        tech = messages._read(messages.BUILTIN / "tech.json")
        for change in (lambda doc: doc.update(revision=0), lambda doc: doc["greeting"]["slots"][1].update(max="2")):
            broken = copy.deepcopy(tech)
            change(broken)
            self.write("tech.json", broken)
            with self.assertRaises(messages.TemplateError):
                messages.load_templates(self.data)

    def test_a_malformed_user_banned_file_is_refused(self):
        for doc in (["冒昧"], {"errors": "冒昧"}, {"errors": [{"reason": "括号", "patterns": ["("]}]},
                    # A string is no list: "简历" would ban 简 and 历 one by one.
                    {"errors": [{"reason": "整个词", "words": "简历"}]}, {"warnings": [{"patterns": [3]}]},
                    {"errors": [{"words": [""]}]}):
            self.write("banned.json", doc)
            with self.assertRaises(messages.TemplateError, msg=doc):
                messages.load_banned(self.data)

    def test_a_new_revision_warns_a_message_written_to_the_old_one(self):
        tech = copy.deepcopy(messages._read(messages.BUILTIN / "tech.json"))
        tech["revision"] = 2
        self.write("tech.json", tech)
        templates = messages.load_templates(self.data)
        self.assertEqual(check(GREETING, templates=templates),
                         ([], ["template: written to tech/greeting@1, the template is now tech/greeting@2; "
                               "check the slots still fit"]))

    def test_user_banned_words_add_to_the_built_in_ones(self):
        self.write("banned.json", {"errors": [{"reason": "我不想写", "words": ["冒昧"]}], "warnings": []})
        banned = messages.load_banned(self.data)
        self.assertGreater(len(banned["errors"]), len(BANNED["errors"]))
        self.assertIn("segments[0].text: '冒昧' - 我不想写", errors_of(REFERRAL, banned=banned))
        self.assertTrue(any("敏感个人信息" in error
                            for error in errors_of(with_segment(GREETING, 3, "我是党员。"), banned=banned)))


def run_cli(*args, data_dir):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-X", "utf8", "-m", "jobsearch_cn", *args, "--data-dir", str(data_dir)],
                          cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8")


class Cli(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.data)
        (self.data / "profile").mkdir()
        shutil.copy(TECH / "profile" / "profile.json", self.data / "profile" / "profile.json")
        (self.data / "jobs").mkdir()
        # Stored by hand: messages read only the title, the company and the skills.
        shutil.copy(TECH / "job.json", self.data / "jobs" / f"{TECH_JOB['id']}.json")

    def write(self, record) -> Path:
        path = self.data / "material.json"
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        return path

    def test_validate_dispatches_on_the_kind(self):
        result = run_cli("material", "validate", str(TECH / "email-1.json"), data_dir=self.data)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {"valid": True, "errors": [], "warnings": []})
        bad = run_cli("material", "validate", str(self.write(with_segment(GREETING, 3, "我今年 23 岁。"))),
                      data_dir=self.data)
        self.assertEqual(bad.returncode, 1)
        self.assertFalse(json.loads(bad.stdout)["valid"])
        resume = run_cli("material", "validate", str(TECH / "resume-1.json"), data_dir=self.data)
        self.assertEqual(resume.returncode, 0, resume.stdout + resume.stderr)

    def test_template(self):
        result = run_cli("material", "template", TECH_JOB["id"], "--kind", "greeting", data_dir=self.data)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual((output["direction"], output["template"]), ("tech", "tech/greeting@1"))
        forced = run_cli("material", "template", TECH_JOB["id"], "--kind", "referral", "--direction", "ops",
                         data_dir=self.data)
        self.assertEqual(json.loads(forced.stdout)["template"], "ops/referral@1")
        # A job not stored is input read but naming no stored job (1); a direction that is no template and no
        # skill vocabulary group is not (2); one with no template of its own uses the default template.
        self.assertEqual(run_cli("material", "template", "job_00000000ffff", "--kind", "email",
                                 data_dir=self.data).returncode, 1)
        self.assertEqual(run_cli("material", "template", TECH_JOB["id"], "--kind", "email", "--direction", "x",
                                 data_dir=self.data).returncode, 2)
        fallback = run_cli("material", "template", TECH_JOB["id"], "--kind", "email", "--direction", "hr",
                           data_dir=self.data)
        self.assertEqual(fallback.returncode, 0, fallback.stderr)
        output = json.loads(fallback.stdout)
        self.assertEqual((output["direction"], output["template"]), ("default", "default/email@1"))
        self.assertIn("hr", output["reason"])

    def test_render_prints_text_ready_to_copy(self):
        result = run_cli("material", "render", str(TECH / "greeting-1.json"), data_dir=self.data)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, messages.render(GREETING, TECH_PROFILE, TECH_JOB) + "\n")
        self.assertEqual(result.stderr, "")
        warned = run_cli("material", "render", str(self.write(with_segment(GREETING, 3, "在吗？想聊聊。"))),
                         data_dir=self.data)
        self.assertEqual(warned.returncode, 0)
        self.assertIn("警告：segments[3].text: '在吗'", warned.stderr)

    def test_render_output_writes_the_text_and_a_build_note(self):
        source = self.data / "email-1.json"
        shutil.copy(TECH / "email-1.json", source)
        result = run_cli("material", "render", str(source), "--output", data_dir=self.data)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        email = load(TECH / "email-1.json")
        text = messages.render(email, TECH_PROFILE, TECH_JOB)
        path = self.data / "messages" / TECH_JOB["id"] / "email-1.txt"
        self.assertEqual(Path(output["text"]), path)
        self.assertEqual(path.read_text(encoding="utf-8"), f"{text}\n")
        self.assertEqual(output["chars"], len(text))
        # No body and no contact details on stdout: only the path, the count and the warnings.
        for value in TECH_PROFILE["contact"].values():
            if isinstance(value, str) and value:
                self.assertNotIn(value, result.stdout)
        from jobsearch_cn import review
        note = load(path.parent / "email-1.build.json")
        self.assertEqual((note["kind"], note["material"]), ("message-build", "email-1.json"))
        self.assertEqual(note["material_hash"], review.material_hash(email))
        self.assertEqual([entry["name"] for entry in note["files"]], ["email-1.txt"])
        changed = copy.deepcopy(email)
        changed["segments"][-1]["text"] += "谢谢。"
        source.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(run_cli("material", "render", str(source), "--output", data_dir=self.data).returncode, 0)
        self.assertNotEqual(load(path.parent / "email-1.build.json")["material_hash"], note["material_hash"])

    def test_render_output_refuses_a_bad_name_and_a_link(self):
        self.assertEqual(run_cli("material", "render", str(self.write(GREETING)), "--output",
                                 data_dir=self.data).returncode, 2)
        source = self.data / "email-1.json"
        shutil.copy(TECH / "greeting-1.json", source)  # a greeting under an email's name
        self.assertEqual(run_cli("material", "render", str(source), "--output", data_dir=self.data).returncode, 2)
        shutil.copy(TECH / "greeting-1.json", self.data / "greeting-1.json")
        directory = self.data / "messages" / TECH_JOB["id"]
        directory.mkdir(parents=True)
        target = self.data / "elsewhere.txt"
        target.write_text("old", encoding="utf-8")
        try:
            (directory / "greeting-1.txt").symlink_to(target)
        except OSError:
            self.skipTest("this system cannot make symbolic links")
        result = run_cli("material", "render", str(self.data / "greeting-1.json"), "--output", data_dir=self.data)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(target.read_text(encoding="utf-8"), "old")

    def test_render_refuses_a_failing_message_and_a_cv(self):
        bad = run_cli("material", "render", str(self.write(with_segment(GREETING, 3, "我今年 23 岁。"))),
                      data_dir=self.data)
        self.assertEqual(bad.returncode, 1)
        self.assertFalse(json.loads(bad.stdout)["valid"])
        self.assertEqual(run_cli("material", "render", str(TECH / "resume-1.json"), data_dir=self.data).returncode, 2)
        (self.data / "templates" / "messages").mkdir(parents=True)
        (self.data / "templates" / "messages" / "banned.json").write_text('["冒昧"]', encoding="utf-8")
        broken = run_cli("material", "render", str(TECH / "greeting-1.json"), data_dir=self.data)
        self.assertEqual(broken.returncode, 2)
        self.assertIn("banned.json", json.loads(broken.stderr)["error"])

    def test_validate_and_render_agree_on_a_failing_message(self):
        record = with_segment(GREETING, 1, "做过订单查询接口。", ["exp-1", "notes.md"])
        (self.data / "profile" / "notes.md").write_text("# 补充\n喜欢做后端。\n", encoding="utf-8")
        outputs = [json.loads(run_cli("material", command, str(self.write(record)), data_dir=self.data).stdout)
                   for command in ("validate", "render")]
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0]["errors"],
                         ["segments[1].refs[1]: a message does not cite notes.md; only a CV's summary does"])

    def test_validate_and_render_refuse_the_reviews_availability_cases(self):
        # Codex B's review of 762b9f6 ran these through both commands: each passed and rendered its promise.
        for text in ("每周至少到岗4天。", "能连续实习6个月以上。", "可以{availability.start_date}或明天到岗。",
                     "可以连续实习{availability.months}个半月。"):
            path = self.write(with_segment(GREETING, 2, text, ["availability"]))
            for command in ("validate", "render"):
                result = run_cli("material", command, str(path), data_dir=self.data)
                self.assertEqual(result.returncode, 1, (text, command, result.stdout + result.stderr))
                output = json.loads(result.stdout)
                self.assertFalse(output["valid"])
                self.assertEqual(len(output["errors"]), 1, (text, command, output))

    def test_a_misspelled_kind_names_all_four(self):
        record = dict(GREETING, kind="greet")
        path = self.write(record)
        for command in (("material", "validate"), ("material", "render")):
            result = run_cli(*command, str(path), data_dir=self.data)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout),
                             {"valid": False, "errors": ["kind: must be one of resume, greeting, email, referral"],
                              "warnings": []})
        resume = self.data / "resume-1.json"  # the name resume build asks for
        resume.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        built = run_cli("resume", "build", str(resume), data_dir=self.data)
        self.assertEqual(built.returncode, 1, built.stdout + built.stderr)
        self.assertEqual(json.loads(built.stderr)["errors"], ["kind: must be one of resume, greeting, email, referral"])

    def test_resume_build_takes_only_a_cv(self):
        path = self.data / "resume-1.json"  # the name resume build asks for, but a greeting inside
        path.write_text(json.dumps(GREETING, ensure_ascii=False), encoding="utf-8")
        result = run_cli("resume", "build", str(path), data_dir=self.data)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("resume build builds a CV", json.loads(result.stderr)["error"])
        self.assertFalse((self.data / "resume-1.pdf").exists())

    def test_review_draft_of_a_message_has_no_coverage_and_agrees_with_validate(self):
        # M3-6: a greeting, email or referral is reviewed too; the draft gives only E1/E3 style warnings.
        for name in ("greeting-1.json", "email-1.json", "referral-1.json"):
            result = run_cli("review", "draft", str(TECH / name), data_dir=self.data)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["coverage"], [], name)
            self.assertTrue(output["job_found"], name)
        spaced = self.write(with_segment(GREETING, 3, "我用过 Python 写服务。"))
        style = json.loads(run_cli("review", "draft", str(spaced), data_dir=self.data).stdout)["style"]
        self.assertIn("segments[3].text: E3 no space between Chinese and English or numbers", style)
        self.assertFalse(any("full stop" in warning for warning in style))  # a message is prose
        bad = self.write(with_segment(GREETING, 3, "我今年 23 岁。"))
        validated = run_cli("material", "validate", str(bad), data_dir=self.data)
        drafted = run_cli("review", "draft", str(bad), data_dir=self.data)
        self.assertEqual((validated.returncode, drafted.returncode), (1, 1))
        self.assertEqual(json.loads(drafted.stderr)["errors"], json.loads(validated.stdout)["errors"])

if __name__ == "__main__":
    unittest.main()
