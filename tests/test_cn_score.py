"""Tests for jobsearch_cn/score.py and match score / validate / save / show / list (M2-4b).

Scoring is explainable only if it is reproducible and nobody can quietly bend
it, so these pin: each rule dimension, including every way it can be null;
the weighted total and its grade; gaps; that the same input gives the same
record; that a change to the job or profile marks a record stale and drops
what an agent added, while new weights mark it stale and keep it (M2-6d);
that match list --weights tries other weights, writing nothing, and ranks as
scoring again with them does; that validate refuses the four tamperings in the roadmap
(an edited total, a JD quote that is not in the JD, a profile id that does
not exist, an edited rule dimension); and the rule part for the ten sample
JDs (the five v0.1 samples and V2's five) against both sample profiles, each
row checked by hand.
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "cn"
PROFILES = FIXTURES / "profile"

sys.path.insert(0, str(REPO))
from jobsearch_cn import jd_parser, match, score, store, vocab  # noqa: E402

NOW = datetime(2026, 10, 27, 10, 0, tzinfo=timezone(timedelta(hours=8)))
LATER = NOW + timedelta(hours=1)
VOCABULARY = vocab.load()


def job_from(path: str) -> dict:
    [record], _ = jd_parser.parse_text((FIXTURES / path).read_text(encoding="utf-8"), now=NOW)
    return record


def profile_from(name: str) -> dict:
    return json.loads((PROFILES / name / "profile.json").read_text(encoding="utf-8"))


def setting(data: dict, path: str, value) -> dict:
    data = copy.deepcopy(data)
    *parents, leaf = path.split(".")
    target = data
    for part in parents:
        target = target[part]
    target[leaf] = value
    return data


def scored(job: dict, profile: dict, **options) -> dict:
    return score.score_job(job, profile, VOCABULARY, now=NOW, **options)


def with_skills(job: dict, skills: list) -> dict:
    return setting(job, "requirements.skills", skills)


class Case(unittest.TestCase):
    def setUp(self):
        self.job = job_from("jd/boss_intern.txt")
        self.tech = profile_from("tech")

    def dimension(self, name: str, job=None, profile=None) -> dict:
        return scored(job or self.job, profile or self.tech)["dimensions"][name]


class Skills(Case):
    def test_statistical_analysis_is_scored_without_inferring_related_skills(self):
        [job], _ = jd_parser.parse_text("任职要求：掌握统计分析方法", now=NOW)
        for name, expected in (("统计分析", 100), ("统计学", 0), ("数据分析", 0)):
            with self.subTest(profile_skill=name):
                profile = setting(self.tech, "skills", [
                    {"name": name, "level": "proficient", "used_in": [], "source": "user"},
                ])
                result = scored(job, profile)
                self.assertEqual(result["dimensions"]["skills"]["score"], expected)
                self.assertEqual(result["dimensions"]["skills"]["missing"], [] if expected else ["统计分析"])
                self.assertEqual(result["dimensions"]["direction"]["jd_groups"], {"data": 1})

    def test_each_level_earns_its_credit(self):
        # tech: Python proficient, Go proficient, MySQL working, RAG no level but used, PyTorch familiar.
        profile = setting(self.tech, "skills", self.tech["skills"] + [
            {"name": "Rust", "level": "expert", "used_in": [], "source": "user"},
            {"name": "Kafka", "level": None, "used_in": [], "source": "user"},
        ])
        for name, credit in (("Rust", 1), ("Python", 1), ("MySQL", 0.8), ("PyTorch", 0.5), ("RAG", 0.8),
                             ("Kafka", 0.5), ("Java", 0)):
            with self.subTest(skill=name):
                dimension = self.dimension("skills", job=with_skills(self.job, [name]), profile=profile)
                self.assertEqual(dimension["score"], credit * 100)
                self.assertEqual([m["credit"] for m in dimension["matched"]], [credit] if credit else [])

    def test_score_is_the_mean_credit_and_lists_what_is_missing(self):
        dimension = self.dimension("skills", job=with_skills(self.job, ["Python", "MySQL", "Kafka"]))
        self.assertEqual(dimension["score"], 60)  # (1 + 0.8 + 0) / 3
        self.assertEqual(dimension["missing"], ["Kafka"])
        self.assertEqual(dimension["reason"], "JD 要求 3 项技能，你有 2 项")

    def test_synonyms_and_case_are_one_skill(self):
        profile = setting(self.tech, "skills", [{"name": "Kubernetes", "level": "working", "used_in": [], "source": "user"}])
        dimension = self.dimension("skills", job=with_skills(self.job, ["K8s", "Kubernetes", "PYTHON"]), profile=profile)
        self.assertEqual(dimension["matched"], [{"jd": "K8s", "profile": "Kubernetes", "credit": 0.8}])
        self.assertEqual(dimension["missing"], ["PYTHON"])
        self.assertEqual(dimension["score"], 40)  # K8s and Kubernetes count once: (0.8 + 0) / 2

    def test_the_h18_spellings_are_one_skill_each(self):
        # 大模型 / LLM / 大语言模型, 提示词工程 / Prompt, Photoshop / PS (H18).
        profile = setting(self.tech, "skills", [
            {"name": "LLM", "level": "working", "used_in": [], "source": "user"},
            {"name": "提示词工程", "level": "familiar", "used_in": [], "source": "user"},
            {"name": "Photoshop", "level": "working", "used_in": [], "source": "user"},
        ])
        job = with_skills(self.job, ["大模型", "大语言模型", "Prompt", "PS"])
        dimension = self.dimension("skills", job=job, profile=profile)
        self.assertEqual(dimension["matched"], [{"jd": "大模型", "profile": "LLM", "credit": 0.8},
                                                {"jd": "Prompt", "profile": "提示词工程", "credit": 0.5},
                                                {"jd": "PS", "profile": "Photoshop", "credit": 0.8}])
        self.assertEqual(dimension["score"], 70)  # 大模型 and 大语言模型 count once: (0.8 + 0.5 + 0.8) / 3

    def test_a_related_skill_is_not_the_skill(self):
        # H18: tech lists RAG and LangChain, not 大模型. The rules infer nothing from them, so
        # 大模型 stays a gap; an agent credits the related work under experience instead.
        job = with_skills(self.job, ["大模型", "RAG", "LangChain"])
        dimension = self.dimension("skills", job=job)
        self.assertEqual(dimension["missing"], ["大模型"])
        self.assertIn({"kind": "skill", "item": "大模型", "jd": None}, scored(job, self.tech)["gaps"])

    def test_null_when_the_jd_names_no_skill(self):
        dimension = self.dimension("skills", job=with_skills(self.job, []))
        self.assertIsNone(dimension["score"])


def with_choices(job: dict, skills: list, groups: list) -> dict:
    """A job asking for skills, some of them as a choice (requirements.skill_alternatives, H16)."""
    return setting(with_skills(job, skills), "requirements.skill_alternatives", groups)


class Choices(Case):
    """H16: a group the JD offers a choice between is one requirement, earning its best-held skill."""

    def test_a_choice_counts_once_and_earns_its_best_skill(self):
        # tech holds Go (proficient, 1) and MySQL (working, 0.8), not Java.
        dimension = self.dimension("skills", job=with_choices(self.job, ["Java", "Go", "Docker"], [["Java", "Go"]]))
        self.assertEqual(dimension["matched"], [{"jd": "Java 或 Go", "profile": "Go", "credit": 1},
                                                {"jd": "Docker", "profile": "Docker", "credit": 0.8}])
        self.assertEqual(dimension["score"], 90)  # (1 + 0.8) / 2, not (0 + 1 + 0.8) / 3
        self.assertEqual(dimension["reason"], "JD 要求 2 项技能，你有 2 项（其中 1 项任选其一）")
        both = self.dimension("skills", job=with_choices(self.job, ["MySQL", "Go"], [["MySQL", "Go"]]))
        self.assertEqual(both["matched"], [{"jd": "MySQL 或 Go", "profile": "Go", "credit": 1}])

    def test_a_choice_with_nothing_held_is_one_gap_citing_the_choice(self):
        job = job_from("jd/boss_intern.txt")
        profile = setting(self.tech, "skills", [{"name": "Python", "level": "expert", "used_in": [], "source": "user"}])
        record = scored(job, profile)
        self.assertIn("Golang 或 Java", record["dimensions"]["skills"]["missing"])
        self.assertIn({"kind": "skill", "item": "Golang 或 Java", "jd": "熟悉 Golang 或 Java"}, record["gaps"])
        self.assertNotIn("Go", record["dimensions"]["skills"]["missing"])
        self.assertNotIn("Java", record["dimensions"]["skills"]["missing"])
        # The quote is the clause that offers the choice, not a snippet that happens to hold the skills.
        del job["evidence"]["requirements.skills"]
        self.assertIn({"kind": "skill", "item": "Golang 或 Java", "jd": "熟悉 Golang 或 Java"}, scored(job, profile)["gaps"])

    def test_a_grouped_skill_named_elsewhere_counts_only_in_its_group(self):
        # boss_intern: 职责 says "使用 Go 语言", 要求 says "熟悉 Golang 或 Java"; Go is Golang (same_as).
        dimension = self.dimension("skills")
        self.assertEqual(dimension["matched"][0], {"jd": "Golang 或 Java", "profile": "Go", "credit": 1})
        self.assertEqual(dimension["reason"], "JD 要求 5 项技能，你有 3 项（其中 1 项任选其一）")
        self.assertEqual(dimension["missing"], ["Redis", "Kubernetes"])

    def test_synonyms_and_overlapping_groups(self):
        # One skill in two spellings is no choice; two groups sharing a skill are one choice.
        same = self.dimension("skills", job=with_choices(self.job, ["Go", "Golang", "Rust"], [["Go", "Golang"]]))
        self.assertEqual((same["score"], same["missing"]), (50, ["Rust"]))
        joined = self.dimension("skills", job=with_choices(self.job, ["Rust", "Go", "Golang", "Java"],
                                                           [["Rust", "Go"], ["Golang", "Java"]]))
        self.assertEqual(joined["matched"], [{"jd": "Rust 或 Go 或 Java", "profile": "Go", "credit": 1}])

    def test_overlapping_choices_from_the_jd_to_the_gap(self):
        # Codex B's P2-1 and P2-2 on #59: parsed, merged into one choice, met by Java alone; with
        # nothing held, one gap citing each clause that offers part of the choice.
        java = setting(self.tech, "skills", [{"name": "Java", "level": "expert", "used_in": [], "source": "user"}])
        nothing = setting(self.tech, "skills", [])
        for text, label, clauses in (
                ("任职要求：\n熟悉 Python 或 Java；熟悉 Java 或 Go", "Python 或 Java 或 Go",
                 ["熟悉 Python 或 Java", "熟悉 Java 或 Go"]),                       # partly the same skills
                ("任职要求：\n熟悉 Rust 或 Go；熟悉 Golang 或 Java", "Rust 或 Go 或 Java",
                 ["熟悉 Rust 或 Go", "熟悉 Golang 或 Java"])):                      # Go and Golang: one skill
            with self.subTest(text=text):
                [job], _ = jd_parser.parse_text(text, now=NOW)
                met = scored(job, java)["dimensions"]["skills"]
                self.assertEqual((met["score"], met["missing"]), (100, []))
                self.assertEqual(met["matched"], [{"jd": label, "profile": "Java", "credit": 1}])
                gaps = [gap for gap in scored(job, nothing)["gaps"] if gap["kind"] == "skill"]
                self.assertEqual(gaps, [{"kind": "skill", "item": label, "jd": clauses}])

    def test_a_choice_counts_once_for_each_direction_it_offers(self):
        job = with_choices(self.job, ["Python", "Java", "Figma", "SQL"], [["Python", "Java"], ["Figma", "SQL"]])
        self.assertEqual(self.dimension("direction", job=job)["jd_groups"], {"tech": 1, "design": 1, "data": 1})
        # Office software stays out of directions: "Excel 或 SPSS" counts for data alone.
        job = with_choices(self.job, ["Excel", "SPSS"], [["Excel", "SPSS"]])
        self.assertEqual(self.dimension("direction", job=job)["jd_groups"], {"data": 1})

    def test_a_new_rules_version_marks_older_records_stale(self):
        self.assertEqual(score.RULES_VERSION, 7)  # 2: H18's synonyms; 3: H16's choices; 4: M2-6b's location;
        # 5: M2-6c's two checks; 6: H26's statistical analysis vocabulary; 7: M2-6e's salary tiers
        old = setting(scored(self.job, self.tech), "rules_version", 6)
        reasons = score.stale_reasons(old, self.job, score.profile_hash(self.tech), score.weights_of(self.tech))
        self.assertEqual(reasons, ["rules"])
        errors = score.validate(old, self.job, self.tech, VOCABULARY)
        self.assertTrue(any(e.startswith("rules_version: scored by other rules") for e in errors), errors)


class Direction(Case):
    def test_the_leading_group_decides(self):
        cases = (
            (["Python", "Go"], ["tech"], 100),          # tech leads, and tech is wanted
            (["Python", "SQL"], ["data"], 100),         # a tie: both lead
            (["Figma", "Sketch", "Python"], ["tech"], 50),  # design leads; one tech skill
            (["Figma", "Sketch"], ["tech"], 0),
        )
        for skills, directions, expected in cases:
            with self.subTest(skills=skills, directions=directions):
                profile = setting(self.tech, "target.directions", directions)
                dimension = self.dimension("direction", job=with_skills(self.job, skills), profile=profile)
                self.assertEqual(dimension["score"], expected)

    def test_general_skills_do_not_count(self):
        dimension = self.dimension("direction", job=with_skills(self.job, ["Excel", "PowerPoint", "Python"]))
        self.assertEqual(dimension["jd_groups"], {"tech": 1})

    def test_null_when_the_profile_names_no_direction_or_the_jd_no_grouped_skill(self):
        self.assertIsNone(self.dimension("direction", profile=setting(self.tech, "target.directions", []))["score"])
        for skills in ([], ["Excel", "PPT"], ["某个不在词表里的词"]):
            with self.subTest(skills=skills):
                self.assertIsNone(self.dimension("direction", job=with_skills(self.job, skills))["score"])


class Experience(Case):
    def test_left_to_an_agent_with_hints(self):
        dimension = self.dimension("experience", job=with_skills(self.job, ["Go", "RAG", "Kafka"]))
        self.assertEqual((dimension["score"], dimension["method"], dimension["evidence"]), (None, "agent", None))
        self.assertEqual(dimension["hints"], [{"jd": "Go", "profile": ["exp-1"]}, {"jd": "RAG", "profile": ["exp-1", "proj-1"]}])


class Salary(Case):
    def test_upper_bound_against_the_minimum_in_the_same_unit(self):
        job = setting(self.job, "salary", {"min": 100, "max": 150, "unit": "CNY/day", "months": None, "negotiable": False})
        self.assertEqual(self.dimension("salary", job=job)["score"], 100)  # 150 reaches 150
        job = setting(job, "salary.max", 149)
        self.assertEqual(self.dimension("salary", job=job)["score"], 0)

    def test_null_cases(self):
        negotiable = {"min": None, "max": None, "unit": None, "months": None, "negotiable": True}
        monthly = {"min": 8000, "max": 10000, "unit": "CNY/month", "months": None, "negotiable": False}
        cases = (
            (setting(self.job, "salary", None), self.tech, "JD 没写薪资"),
            (setting(self.job, "salary", negotiable), self.tech, "JD 薪资面议"),
            (setting(self.job, "salary", monthly), self.tech, "单位不同，不换算"),
            (self.job, setting(self.tech, "target.salary_min", None), "档案没写最低期望薪资"),
        )
        for job, profile, reason in cases:
            with self.subTest(reason=reason):
                dimension = self.dimension("salary", job=job, profile=profile)
                self.assertIsNone(dimension["score"])
                self.assertIn(reason, dimension["reason"])


def pay(low, high=None, unit="CNY/day") -> dict:
    return {"min": low, "max": high if high is not None else low, "unit": unit, "months": None, "negotiable": False}


def tiered(profile: dict, minimum, ideal, step, unit="CNY/day", **more) -> dict:
    """The profile with salary tiers (M2-6e); the figures are examples, nobody's own."""
    profile = setting(profile, "target.salary_min", {"amount": minimum, "unit": unit})
    profile = setting(profile, "target.salary_ideal", {"amount": ideal, "unit": unit})
    profile = setting(profile, "target.salary_step", step)
    for key, value in more.items():
        profile = setting(profile, f"target.{key}", value)
    return profile


class SalaryTiers(Case):
    """M2-6e: 50 from the minimum to the ideal, 10 a step above the ideal or below the minimum, within 0-100."""

    def setUp(self):
        super().setUp()
        self.daily = tiered(self.tech, 150, 220, 20)  # boss_intern pays 200-250 a day and asks 4 days a week

    def salary(self, job=None, profile=None) -> dict:
        return self.dimension("salary", job=job, profile=profile or self.daily)

    def test_the_tiers(self):
        cases = {150: 50, 200: 50, 220: 50, 230: 55, 260: 70, 320: 100, 330: 100,  # 50 + 10 * (pay - 220) / 20
                 140: 45, 125: 38, 50: 0, 30: 0}  # 50 - 10 * (150 - pay) / 20; 37.5 rounds to 38
        for amount, expected in cases.items():
            with self.subTest(pay=amount):
                self.assertEqual(self.salary(setting(self.job, "salary", pay(amount)))["score"], expected)

    def test_a_range_counts_its_lowest_figure(self):
        dimension = self.salary(setting(self.job, "salary", pay(200, 400)))
        self.assertEqual(dimension["score"], 50)
        self.assertTrue(dimension["reason"].startswith("JD 200–400 元/天，取最低的 200 元/天"), dimension["reason"])

    def test_pay_turns_into_the_profile_unit(self):
        monthly = tiered(self.tech, 2600, 3400, 160, unit="CNY/month", salary_days_per_week=4.5)
        # A day rate counts the JD's own days a week: 200 * 4 * 52 / 12 = 3466.7, 50 + 10 * 66.7 / 160 = 54.2.
        dimension = self.salary(profile=monthly)
        self.assertEqual(dimension["score"], 54)
        self.assertIn("折合 3466.7 元/月（按JD 写的每周 4 天、一年 52 周）", dimension["reason"])
        # The JD silent, the profile's: 200 * 4.5 * 52 / 12 = 3900, 50 + 10 * 500 / 160 = 81.25.
        silent = setting(self.job, "requirements.days_per_week", None)
        dimension = self.salary(silent, monthly)
        self.assertEqual(dimension["score"], 81)
        self.assertIn("按档案的每周 4.5 天", dimension["reason"])
        neither = self.salary(silent, setting(monthly, "target.salary_days_per_week", None))
        self.assertIsNone(neither["score"])
        self.assertIn("target.salary_days_per_week", neither["reason"])
        # A year is twelve months: 42000 / 12 = 3500, 50 + 10 * 100 / 160 = 56.25.
        self.assertEqual(self.salary(setting(self.job, "salary", pay(42000, unit="CNY/year")), monthly)["score"], 56)
        hourly = self.salary(setting(self.job, "salary", pay(40, unit="CNY/hour")), monthly)
        self.assertIsNone(hourly["score"])
        self.assertIn("按小时的不换算", hourly["reason"])

    def test_meals_add_their_value_and_one_meal_adds_points(self):
        profile = setting(setting(self.daily, "target.meal_value", {"amount": 25, "unit": "CNY/day"}),
                          "target.one_meal_points", 10)

        def with_meals(per_day, allowance=None):
            return self.salary(setting(self.job, "benefits.meals", {"per_day": per_day, "allowance": allowance}),
                               profile)

        self.assertEqual(with_meals(2)["score"], 53)  # 200 + 25 = 225: 52.5 rounds half up
        self.assertEqual(with_meals(3)["score"], 53)
        self.assertEqual(with_meals(None)["score"], 53)  # 包吃 with no count: two or more
        self.assertIn("包两餐，加 25 元/天；合计 225 元/天", with_meals(2)["reason"])
        self.assertEqual(with_meals(1)["score"], 60)  # 50 for 200 a day, and 10 points for the one meal
        self.assertIn("只包一餐，加 10 分", with_meals(1)["reason"])
        self.assertEqual(with_meals(0, {"amount": 20, "unit": "CNY/day"})["score"], 50)  # 220 is the ideal
        self.assertEqual(with_meals(2, {"amount": 20, "unit": "CNY/day"})["score"], 63)  # 245: 62.5
        # A monthly allowance is turned with the JD's days: 520 / (4 * 52 / 12) = 30 a day; 230 scores 55.
        self.assertEqual(with_meals(0, {"amount": 520, "unit": "CNY/month"})["score"], 55)
        plain = setting(self.job, "benefits.meals", {"per_day": 2, "allowance": None})
        self.assertIn("档案没写包餐折合多少", self.salary(plain)["reason"])  # no meal value: nothing added
        self.assertEqual(self.salary(plain)["score"], 50)

    def test_pay_below_the_minimum_is_a_gap(self):
        short = setting(self.job, "salary", pay(140))
        [gap] = [g for g in scored(short, self.daily)["gaps"] if g["kind"] == "salary"]
        self.assertEqual(gap["item"], "按 JD 最低的薪资算，是 140 元/天，低于你的最低期望 150 元/天")
        self.assertEqual([g for g in scored(self.job, self.daily)["gaps"] if g["kind"] == "salary"], [])
        # Points for one meal can lift the score; the pay is still short.
        lifted = tiered(self.tech, 150, 220, 20, one_meal_points=10)
        record = scored(setting(short, "benefits.meals", {"per_day": 1, "allowance": None}), lifted)
        self.assertEqual(record["dimensions"]["salary"]["score"], 55)
        self.assertEqual(len([g for g in record["gaps"] if g["kind"] == "salary"]), 1)

    def test_without_tiers_salary_scores_as_before(self):
        # The sample profiles leave the tier keys null: the upper figure reaches the minimum or not.
        self.assertEqual(self.dimension("salary")["score"], 100)
        self.assertEqual(self.dimension("salary", job=setting(self.job, "salary", pay(100, 140)))["score"], 0)

    def test_a_tiered_record_validates(self):
        record = scored(self.job, self.daily)
        self.assertEqual(score.validate(record, self.job, self.daily, VOCABULARY), [])


class Location(Case):
    """M2-6b: where the job is against the cities the profile names, 0-100, the best of the JD's cities."""

    def where(self, cities, remote=None):
        return setting(setting(self.job, "cities", cities), "remote", remote)

    def wants(self, cities, acceptable=(), remote_ok=None, relocate=None):
        availability = dict(self.tech["availability"], cities=cities, acceptable_cities=list(acceptable),
                            remote_ok=remote_ok, relocate=relocate)
        return setting(self.tech, "availability", availability)

    def location(self, job, profile):
        dimension = self.dimension("location", job=job, profile=profile)
        return dimension["score"], dimension["reason"]

    def test_each_city_case(self):
        profile = self.wants(["深圳"], ["杭州"], relocate=False)
        cases = (
            (self.where(["深圳市"]), profile, 100, "深圳市是你的首选城市"),
            (self.where(["杭州"]), profile, 60, "杭州是你可以接受的城市，不是首选"),
            (self.where(["北京"]), profile, 0, "北京不在你写的城市里，你不考虑异地"),
            (self.where(["北京"]), self.wants(["深圳"], relocate=None), 0, "北京不在你写的城市里，档案没写是否愿意去其他城市"),
            (self.where(["北京"]), self.wants(["深圳"], relocate=True), 30, "北京不在你写的城市里，你愿意去其他城市"),
            (self.where(["北京"]), self.wants([], ["杭州"], relocate=False), 0, "北京不在你写的城市里，你不考虑异地"),
        )
        for job, wanted, expected, reason in cases:
            with self.subTest(cities=job["cities"], availability=wanted["availability"]):
                self.assertEqual(self.location(job, wanted), (expected, reason))

    def test_several_cities_take_the_best(self):
        profile = self.wants(["深圳"], ["杭州"])
        self.assertEqual(self.location(self.where(["北京", "杭州"]), profile), (60, "杭州是你可以接受的城市，不是首选"))
        self.assertEqual(self.location(self.where(["杭州", "深圳"]), profile), (100, "深圳是你的首选城市"))

    def test_remote_counts_as_a_preferred_city_only_when_you_accept_it(self):
        self.assertEqual(self.location(self.where(["北京"], True), self.wants(["深圳"], remote_ok=True)),
                         (100, "JD 可远程，你接受远程"))
        self.assertEqual(self.location(self.where([], True), self.wants([], remote_ok=True)), (100, "JD 可远程，你接受远程"))
        for remote_ok in (False, None):
            with self.subTest(remote_ok=remote_ok):
                self.assertEqual(self.location(self.where(["北京"], True), self.wants(["深圳"], remote_ok=remote_ok))[0], 0)

    def test_null_when_a_side_names_no_city(self):
        self.assertEqual(self.location(self.where([]), self.wants(["深圳"])), (None, "JD 没写工作城市"))
        self.assertEqual(self.location(self.where([], False), self.wants(["深圳"])), (None, "JD 没写工作城市，也不能远程"))
        self.assertEqual(self.location(self.where(["北京"]), self.wants([], relocate=True)), (None, "档案没写意向城市"))
        record = scored(self.where([]), self.wants(["深圳"]))
        self.assertIn("location", record["total"]["missing"])

    def test_location_and_salary_offset_each_other(self):
        # Equal default weights (10 each). Experience is unscored, so the total is over 75:
        # preferred city, salary met:   (30*52 + 25*100 + 10*100 + 10*100) / 75 = 80.8 -> 81
        # acceptable city, salary met:  (30*52 + 25*100 + 10*100 + 10*60) / 75 = 75.5 -> 75
        # preferred city, salary short: (30*52 + 25*100 + 10*0 + 10*100) / 75 = 67.5 -> 67 (5060/75 = 67.47)
        # A salary that meets your minimum outweighs the step down to an acceptable city.
        self.assertEqual((score.DEFAULT_WEIGHTS["location"], score.DEFAULT_WEIGHTS["salary"]), (10, 10))
        profile = self.wants(["深圳"], ["杭州"])
        short = setting(profile, "target.salary_min", {"amount": 300, "unit": "CNY/day"})
        self.assertEqual([scored(self.where([city]), wanted)["total"]["score"]
                          for city, wanted in (("深圳", profile), ("杭州", profile), ("深圳", short))], [81, 75, 67])

    def test_an_agent_may_not_change_it(self):
        record = agent_filled(scored(self.job, self.tech))
        errors = score.validate(setting(record, "dimensions.location.score", 50), self.job, self.tech, VOCABULARY)
        self.assertIn("dimensions.location: a rule dimension; an agent does not change it", errors)


class Total(Case):
    def dims(self, **scores):
        return {name: {"score": scores.get(name)} for name in score.DIMENSIONS}

    def test_weighted_mean_of_the_scored_dimensions_rounded_half_up(self):
        weights = score.DEFAULT_WEIGHTS
        self.assertEqual(score.total(self.dims(skills=50, direction=75), weights, "eligible"),
                         {"score": 61, "grade": "good", "complete": False,
                          "missing": ["experience", "salary", "location"]})  # (30*50 + 25*75) / 55 = 61.4
        # 62.5 rounds up to 63, not to the even 62.
        self.assertEqual(score.total(self.dims(skills=25, direction=100), {"skills": 1, "direction": 1,
                                                                            "experience": 1, "salary": 1,
                                                                            "location": 1}, "eligible")["score"], 63)

    def test_grades(self):
        for value, grade in ((75, "strong"), (74, "good"), (60, "good"), (59, "moderate"), (45, "moderate"),
                             (44, "weak"), (30, "weak"), (29, "poor"), (0, "poor")):
            with self.subTest(score=value):
                self.assertEqual(score.total(self.dims(skills=value), score.DEFAULT_WEIGHTS, "needs_check")["grade"], grade)

    def test_ruled_out_jobs_are_ineligible_but_keep_their_scores(self):
        result = score.total(self.dims(skills=100, direction=100, experience=100, salary=100, location=100),
                             score.DEFAULT_WEIGHTS, "ineligible")
        self.assertEqual((result["score"], result["grade"], result["complete"]), (100, "ineligible", True))

    def test_nothing_scored_has_no_total(self):
        self.assertEqual(score.total(self.dims(), score.DEFAULT_WEIGHTS, "needs_check"),
                         {"score": None, "grade": None, "complete": False, "missing": list(score.DIMENSIONS)})
        # A weight of 0 leaves a dimension out too.
        zero = dict(score.DEFAULT_WEIGHTS, skills=0)
        self.assertIsNone(score.total(self.dims(skills=80), zero, "eligible")["score"])

    def test_profile_weights_replace_the_defaults(self):
        weights = {"skills": 10, "direction": 10, "experience": 0, "salary": 80, "location": 0}
        record = scored(self.job, setting(self.tech, "target.weights", weights))
        self.assertEqual(record["weights"], weights)
        self.assertEqual(record["total"]["score"], 95)  # (10*52 + 10*100 + 80*100) / 100 = 95.2


class Gaps(Case):
    def test_missing_skills_low_salary_and_filter_findings_each_cite_the_jd(self):
        profile = setting(self.tech, "target.salary_min", {"amount": 300, "unit": "CNY/day"})
        profile = setting(profile, "availability.days_per_week", 3)
        gaps = scored(self.job, profile)["gaps"]
        self.assertIn({"kind": "skill", "item": "Redis", "jd": "参与 MySQL、Redis 等存储方案的设计与优化"}, gaps)
        self.assertIn({"kind": "salary", "item": "JD 上限 250 元/天，低于你的最低期望 300 元/天", "jd": "200-250元/天"}, gaps)
        filters = {gap["item"]: gap for gap in gaps if gap["kind"] == "filter"}
        self.assertEqual((filters["days_per_week"]["result"], filters["days_per_week"]["jd"]), ("conflict", "4天/周"))
        # The JD says nothing of the interview or the start date: both are listed to confirm (M2-6c).
        self.assertEqual(sorted(filters), ["days_per_week", "interview", "start_date"])
        self.assertEqual({filters[key]["result"] for key in ("interview", "start_date")}, {"unknown"})

    def test_an_unknown_check_is_a_gap_too(self):
        job = setting(self.job, "requirements.graduation", None)
        del job["evidence"]["requirements.graduation"]  # as a JD that never names its 届别 is parsed
        gaps = scored(job, self.tech)["gaps"]
        self.assertIn({"kind": "filter", "item": "graduation", "result": "unknown",
                       "reason": "JD 没写届别；你是 2027 届", "jd": None}, gaps)


class Records(Case):
    def test_the_same_input_gives_the_same_record(self):
        first, second = scored(self.job, self.tech), score.score_job(self.job, self.tech, VOCABULARY, now=LATER)
        self.assertNotEqual(first["scored_at"], second["scored_at"])
        self.assertEqual(dict(first, scored_at=None), dict(second, scored_at=None))
        self.assertEqual(json.loads(json.dumps(first, ensure_ascii=False)), first)

    def test_hashes_ignore_contact_and_status_but_not_content(self):
        base = scored(self.job, self.tech)
        self.assertEqual(scored(self.job, setting(self.tech, "contact.phone", "13900000000"))["profile_hash"],
                         base["profile_hash"])
        self.assertEqual(scored(setting(self.job, "status", "ranked"), self.tech)["job_hash"], base["job_hash"])
        self.assertNotEqual(scored(self.job, setting(self.tech, "availability.days_per_week", 5))["profile_hash"],
                            base["profile_hash"])
        self.assertNotEqual(scored(setting(self.job, "title", "后端开发实习生"), self.tech)["job_hash"], base["job_hash"])

    def test_no_contact_detail_reaches_a_record(self):
        text = json.dumps(scored(self.job, self.tech), ensure_ascii=False)
        for value in self.tech["contact"].values():
            if value:
                self.assertNotIn(value, text)

    def test_rescoring_keeps_an_agents_work_until_a_side_changes(self):
        filled = agent_filled(scored(self.job, self.tech))
        again = score.score_job(self.job, self.tech, VOCABULARY, previous=filled, now=LATER)
        self.assertEqual(again["dimensions"]["experience"], filled["dimensions"]["experience"])
        self.assertEqual(again["total"], filled["total"])
        changed = setting(self.tech, "availability.days_per_week", 5)
        fresh = score.score_job(self.job, changed, VOCABULARY, previous=filled, now=LATER)
        self.assertIsNone(fresh["dimensions"]["experience"]["score"])
        edited = setting(self.job, "title", "后端开发实习生")
        fresh = score.score_job(edited, self.tech, VOCABULARY, previous=filled, now=LATER)
        self.assertIsNone(fresh["dimensions"]["experience"]["score"])

    def test_the_profile_hash_leaves_out_the_weights(self):
        # M2-6d: the agent's judgments do not rest on the weights, and a record keeps the weights it used.
        base = scored(self.job, self.tech)
        heavier = setting(self.tech, "target.weights", dict(score.DEFAULT_WEIGHTS, location=40))
        record = scored(self.job, heavier)
        self.assertEqual(record["profile_hash"], base["profile_hash"])
        self.assertEqual(record["weights"], heavier["target"]["weights"])
        self.assertNotEqual(record["total"], base["total"])

    def test_new_weights_keep_the_agents_work_and_redo_the_total(self):
        job = with_skills(self.job, ["Excel"])  # nothing grouped: the agent gives the direction as well
        filled = agent_filled(scored(job, self.tech))
        filled["dimensions"]["direction"].update(score=100, method="agent", reason="标题是后端开发，属于技术方向",
                                                 evidence={"jd": ["后端开发实习生（Go方向）"], "profile": []})
        filled["total"] = score.total(filled["dimensions"], filled["weights"], filled["filter"]["verdict"])
        weights = {"skills": 10, "direction": 40, "experience": 40, "salary": 0, "location": 10}
        again = score.score_job(job, setting(self.tech, "target.weights", weights), VOCABULARY,
                                previous=filled, now=LATER)
        for key in ("experience", "direction"):
            self.assertEqual(again["dimensions"][key], filled["dimensions"][key])
        self.assertEqual(again["weights"], weights)
        self.assertEqual(again["total"], score.trial_total(filled, weights))
        self.assertNotEqual(again["total"], filled["total"])
        # Anything else in the profile still clears the agent's work, here what an experience says.
        rewritten = copy.deepcopy(self.tech)
        rewritten["experience"][0]["bullets"] = ["重写了订单服务"]
        fresh = score.score_job(job, rewritten, VOCABULARY, previous=filled, now=LATER)
        self.assertIsNone(fresh["dimensions"]["experience"]["score"])
        self.assertIsNone(fresh["dimensions"]["direction"]["score"])

    def test_why_a_record_is_stale(self):
        record = scored(self.job, self.tech)

        def reasons(job=self.job, profile=self.tech, saved=record):
            return score.stale_reasons(saved, job, score.profile_hash(profile), score.weights_of(profile))

        self.assertEqual(reasons(), [])
        self.assertEqual(reasons(job=None), ["job_gone"])
        self.assertEqual(reasons(job=setting(self.job, "title", "后端开发实习生")), ["job"])
        self.assertEqual(reasons(profile=setting(self.tech, "availability.days_per_week", 5)), ["profile"])
        self.assertEqual(reasons(profile=setting(self.tech, "target.weights", dict(score.DEFAULT_WEIGHTS, location=40))),
                         ["weights"])
        self.assertEqual(reasons(saved=dict(record, rules_version=score.RULES_VERSION - 1)), ["rules"])


class Trial(Case):
    """M2-6d: match list --weights works out what scoring again with other weights would give."""

    def test_a_trial_total_is_what_scoring_again_with_those_weights_gives(self):
        record = agent_filled(scored(self.job, self.tech))
        self.assertEqual(score.trial_total(record, record["weights"]), record["total"])
        for weights in ({"skills": 0, "direction": 0, "experience": 0, "salary": 0, "location": 1},
                        dict(score.DEFAULT_WEIGHTS, location=40)):
            with self.subTest(weights=weights):
                again = scored(self.job, setting(self.tech, "target.weights", weights), previous=record)
                self.assertEqual(score.trial_total(record, weights), again["total"])

    def test_a_dimension_the_record_lacks_counts_as_null(self):
        # A record saved before M2-6b has no location; it is stale, but a trial must not fail on it.
        record = agent_filled(scored(self.job, self.tech))
        del record["dimensions"]["location"]
        self.assertEqual(score.trial_total(record, score.DEFAULT_WEIGHTS)["missing"], ["location"])
        self.assertEqual(score.trial_total({}, score.DEFAULT_WEIGHTS),
                         {"score": None, "grade": None, "complete": False, "missing": list(score.DIMENSIONS)})

    def test_shares_are_percentages_of_the_sum(self):
        self.assertEqual(score.shares(score.DEFAULT_WEIGHTS), score.DEFAULT_WEIGHTS)  # they add up to 100
        # Raising one weight keeps the others' numbers but not their shares: 30 of 130 is 23.08%.
        self.assertEqual(score.shares(dict(score.DEFAULT_WEIGHTS, location=40)),
                         {"skills": 23.1, "direction": 19.2, "experience": 19.2, "salary": 7.7, "location": 30.8})
        self.assertEqual(score.shares({"skills": 1, "direction": 1, "experience": 1, "salary": 0, "location": 0}),
                         {"skills": 33.3, "direction": 33.3, "experience": 33.3, "salary": 0, "location": 0})


def agent_filled(record: dict) -> dict:
    """What an agent hands back: experience scored, with a reason and evidence; the total redone."""
    record = copy.deepcopy(record)
    record["dimensions"]["experience"].update(
        score=80, reason="做过订单服务重写，和 JD 的后端开发对口",
        evidence={"jd": ["参与公司核心业务系统的后端开发"], "profile": ["exp-1"]})
    record["total"] = score.total(record["dimensions"], record["weights"], record["filter"]["verdict"])
    return record


class Validate(Case):
    def setUp(self):
        super().setUp()
        self.record = agent_filled(scored(self.job, self.tech))

    def errors(self, record=None, job=None, profile=None) -> list:
        return score.validate(record or self.record, job or self.job, profile or self.tech, VOCABULARY)

    def assert_refused(self, record, fragment):
        errors = self.errors(record)
        self.assertTrue(any(fragment in error for error in errors), f"{fragment!r} not in {errors}")

    def test_a_rule_record_and_an_agent_completed_one_are_valid(self):
        self.assertEqual(self.errors(scored(self.job, self.tech)), [])
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.record["total"]["score"], 81)  # (30*52 + 25*100 + 25*80 + 10*100 + 10*100) / 100 = 80.6

    def test_the_four_tamperings(self):
        self.assert_refused(setting(self.record, "total.score", 95), "total: does not follow")
        # The error carries the total the dimensions give, for an agent to copy.
        self.assert_refused(setting(self.record, "total.score", 95), json.dumps(self.record["total"], ensure_ascii=False))
        self.assert_refused(setting(self.record, "dimensions.experience.evidence.jd", ["精通分布式系统设计"]),
                            "dimensions.experience.evidence.jd[0]: not found in the JD text")
        self.assert_refused(setting(self.record, "dimensions.experience.evidence.profile", ["exp-9"]),
                            "no experience with id 'exp-9'")
        self.assert_refused(setting(self.record, "dimensions.skills.score", 90), "dimensions.skills: a rule dimension")

    def test_other_edits_an_agent_may_not_make(self):
        self.assert_refused(setting(self.record, "dimensions.direction.score", 50), "the rules scored it")
        self.assert_refused(setting(self.record, "gaps", []), "gaps: not what the rules give")
        self.assert_refused(setting(self.record, "dimensions.experience.score", 101), "whole number from 0 to 100")
        self.assert_refused(setting(self.record, "dimensions.experience.reason", " "), "say why")
        self.assert_refused(setting(self.record, "dimensions.experience.evidence.profile", []), "name the experience")
        self.assert_refused(setting(self.record, "dimensions.experience.hints", []), "experience.hints")
        self.assert_refused(dict(self.record, extra=1), "extra: unknown field")

    def test_an_evidence_reference_that_is_not_an_id_is_an_error_not_a_crash(self):
        # Codex's P2 on #41: an object here once raised TypeError inside validate.
        for ref in ({}, ["exp-1"], 1, ""):
            with self.subTest(ref=ref):
                record = setting(self.record, "dimensions.experience.evidence.profile", [ref])
                self.assertEqual(self.errors(record),
                                 ["dimensions.experience.evidence.profile[0]: must be an experience id (a string)"])

    def test_an_agent_may_fill_a_direction_the_rules_left_null(self):
        job = with_skills(self.job, ["Excel"])  # nothing grouped: the rules leave the direction to an agent
        record = scored(job, self.tech)
        self.assertIsNone(record["dimensions"]["direction"]["score"])
        record["dimensions"]["direction"].update(score=100, method="agent", reason="标题是后端开发，属于技术方向",
                                                 evidence={"jd": ["后端开发实习生（Go方向）"], "profile": []})
        record["total"] = score.total(record["dimensions"], record["weights"], record["filter"]["verdict"])
        self.assertEqual(score.validate(record, job, self.tech, VOCABULARY), [])

    def test_a_stale_record_must_be_scored_again(self):
        errors = self.errors(profile=setting(self.tech, "availability.days_per_week", 5))
        self.assertTrue(any("run match score again" in e for e in errors), errors)
        errors = self.errors(job=setting(self.job, "title", "后端开发实习生"))
        self.assertTrue(any("run match score again" in e for e in errors), errors)
        heavier = setting(self.tech, "target.weights", dict(score.DEFAULT_WEIGHTS, location=40))
        self.assertEqual(self.errors(profile=heavier),
                         ["weights: the profile's weights changed since scoring; run match score again"])


# The rule part for the ten sample JDs against both sample profiles; experience is null
# (an agent's), so totals weigh skills 30, direction 25, salary 10 and location 10 over what
# is scored (M2-6b; 35, 30, 10 and no location before).
# Credits (match.md): 精通/熟练 1, 熟悉 0.8, 了解 0.5; no level 0.8 if used in an experience.
#   tech: Python 1, Go 1, MySQL 0.8, LangChain 0.8, RAG 0.8 (no level, used), Docker 0.8, PyTorch 0.5;
#         directions [tech]; salary_min 150 元/天; cities 深圳、广州, remote_ok, no relocating.
#   ops:  Excel 1, 秀米 1, 剪映 0.8, Photoshop 0.8; directions [ops]; no salary_min (so salary is
#         null for every ops row); cities 上海, no remote, no relocating.
# Location (M2-6b): a preferred city, or remote work you accept, 100; any other city 0 here, since
# neither profile names acceptable cities or relocates.
# Checked by hand (skills, direction and salary as before M2-6b; location and the totals new):
#   boss_intern       tech  "熟悉 Golang 或 Java" is one choice (H16), and the Go of 职责 is the same skill, so it
#                           counts there: 5 skills, Go|Java 1 (Go held) + MySQL 0.8 + Redis 0 + Docker 0.8 +
#                           Kubernetes 0 = 2.6/5 -> 52 (43 before H16: Go, Java apart, 2.6/6);
#                           all tech -> 100; 250 >= 150 -> 100; 深圳 preferred -> 100;
#                           (30*52+25*100+10*100+10*100)/75 = 80.8 -> 81 strong
#                     ops   no skill held -> 0; tech only, no ops skill -> 0; 深圳 -> 0; 0; filter -> ineligible
#   shixiseng_intern  tech  4 skills, Python 1 -> 25; data 2 = tech 2, a tie both lead -> 100; 200 >= 150 -> 100;
#                           上海 -> 0; (750+2500+1000)/75 = 56.7 -> 57; the filter rules it out (每周5天 > 4)
#                     ops   0, 0; 上海 -> 100; 1000/65 = 15.4 -> 15; ineligible
#   nowcoder_campus   tech  8 skills: RAG 0.8 + Python 1 + PyTorch 0.5 + LangChain 0.8 = 3.1/8 -> 39; tech -> 100;
#                           元/月 vs 元/天 -> null; 北京、杭州 -> 0; (1170+2500)/65 = 56.5 -> 56; 校招 -> ineligible
#   official_site     tech  6 skills, PyTorch 0.5 -> 8; tech -> 100; 面议 -> null; 杭州, but remote and you accept
#                           remote -> 100; (240+2500+1000)/65 = 57.5 -> 58; no 届别 -> needs_check: moderate
#                     ops   杭州, remote, but ops does not accept remote -> 0; 0
#   experienced_hire  tech  none of 8 held -> 0; tech -> 100; 元/月 -> null; 上海 -> 0; 2500/65 = 38.5 -> 38;
#                           社招 -> ineligible
#                     ops   0, 0; 上海 -> 100; 1000/65 = 15.4 -> 15; ineligible
#   boss_ai_product   tech  none held -> 0; product 4 leads, no tech skill -> 0; 220 >= 150 -> 100; 广州 -> 100;
#                           2000/75 = 26.7 -> 27; the filter passes it -> poor
#                     ops   0; product leads, no ops skill -> 0; 广州 -> 0; 0 -> ineligible (4天 > 3, 广州)
#   shixiseng_content tech  none held -> 0; ops 5 leads -> 0; 180 >= 150 -> 100; 上海 -> 0; 1000/75 = 13.3 -> 13;
#                           上海 -> ineligible
#                     ops   7 skills: 秀米 1 + 剪映 0.8 + Photoshop 0.8 + Excel 1 = 3.6/7 -> 51 (Excel is general:
#                           held, but no direction); ops leads -> 100; 上海 -> 100;
#                           (1530+2500+1000)/65 = 77.4 -> 77 strong
#   ats_ui_design     tech  none held -> 0; design 6 -> 0; 面议 -> null; 杭州, remote, accepted -> 100;
#                           1000/65 = 15.4 -> 15; needs_check -> poor
#                     ops   Photoshop 0.8/6 -> 13; design -> 0; 杭州 -> 0; 390/65 = 6; 杭州 -> ineligible
#   nowcoder_test_dev tech  none of the 6 test skills held -> 0; tech -> 100; 元/小时 -> null; 深圳 -> 100;
#                           3500/65 = 53.8 -> 54 moderate
#   official_marketing tech none held -> 0; market 2 leads, no tech skill -> 0; 元/月 -> null; 上海 -> 0; 0;
#                           校招 -> ineligible
#                     ops   Excel 1/5 -> 20; market leads, 活动策划 is ops -> 50; 上海 -> 100;
#                           (600+1250+1000)/65 = 43.8 -> 44 weak
#   Every other ops row: no skill held, no ops skill, not in 上海 -> 0, 0 and 0; ruled out by the filter.
EXPECTED = {
    # (sample, profile): (skills, direction, salary, location, total, grade)
    ("jd/boss_intern.txt", "tech"): (52, 100, 100, 100, 81, "strong"),
    ("jd/shixiseng_intern.txt", "tech"): (25, 100, 100, 0, 57, "ineligible"),
    ("jd/nowcoder_campus.txt", "tech"): (39, 100, None, 0, 56, "ineligible"),
    ("jd/official_site.txt", "tech"): (8, 100, None, 100, 58, "moderate"),
    ("jd/experienced_hire.txt", "tech"): (0, 100, None, 0, 38, "ineligible"),
    ("jd-m2-3/boss_ai_product_intern.txt", "tech"): (0, 0, 100, 100, 27, "poor"),
    ("jd-m2-3/shixiseng_content_ops_intern.txt", "tech"): (0, 0, 100, 0, 13, "ineligible"),
    ("jd-m2-3/ats_ui_design_intern.txt", "tech"): (0, 0, None, 100, 15, "poor"),
    ("jd-m2-3/nowcoder_test_dev_intern.txt", "tech"): (0, 100, None, 100, 54, "moderate"),
    ("jd-m2-3/official_marketing_campus.txt", "tech"): (0, 0, None, 0, 0, "ineligible"),
    ("jd/boss_intern.txt", "ops"): (0, 0, None, 0, 0, "ineligible"),
    ("jd/shixiseng_intern.txt", "ops"): (0, 0, None, 100, 15, "ineligible"),
    ("jd/nowcoder_campus.txt", "ops"): (0, 0, None, 0, 0, "ineligible"),
    ("jd/official_site.txt", "ops"): (0, 0, None, 0, 0, "ineligible"),
    ("jd/experienced_hire.txt", "ops"): (0, 0, None, 100, 15, "ineligible"),
    ("jd-m2-3/boss_ai_product_intern.txt", "ops"): (0, 0, None, 0, 0, "ineligible"),
    ("jd-m2-3/shixiseng_content_ops_intern.txt", "ops"): (51, 100, None, 100, 77, "strong"),
    ("jd-m2-3/ats_ui_design_intern.txt", "ops"): (13, 0, None, 0, 6, "ineligible"),
    ("jd-m2-3/nowcoder_test_dev_intern.txt", "ops"): (0, 0, None, 0, 0, "ineligible"),
    ("jd-m2-3/official_marketing_campus.txt", "ops"): (20, 50, None, 100, 44, "weak"),
}


class SampleTable(unittest.TestCase):
    def test_ten_samples_by_two_profiles(self):
        self.assertEqual(len({sample for sample, _ in EXPECTED}), 10)
        self.assertEqual(len(EXPECTED), 20)

    def test_each_pair(self):
        for (sample, name), (skills, direction, salary, location, total, grade) in EXPECTED.items():
            with self.subTest(sample=sample, profile=name):
                record = scored(job_from(sample), profile_from(name))
                dimensions = record["dimensions"]
                self.assertEqual((dimensions["skills"]["score"], dimensions["direction"]["score"],
                                  dimensions["experience"]["score"], dimensions["salary"]["score"],
                                  dimensions["location"]["score"]),
                                 (skills, direction, None, salary, location))
                self.assertEqual((record["total"]["score"], record["total"]["grade"]), (total, grade))
                self.assertEqual(score.validate(record, job_from(sample), profile_from(name), VOCABULARY), [])


def run_cli(*args, data_dir, input_bytes=None):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", **{store.DATA_DIR_ENV: str(data_dir)})
    return subprocess.run([sys.executable, "-m", "jobsearch_cn", *args], cwd=REPO, env=env, input=input_bytes,
                          capture_output=True)


class Commands(unittest.TestCase):
    # The last one scores 65 but the filter rules it out (每周5天 > 4): it lists after a 13-point job.
    SAMPLES = ("jd/boss_intern.txt", "jd-m2-3/nowcoder_test_dev_intern.txt", "jd-m2-3/boss_ai_product_intern.txt",
               "jd/shixiseng_intern.txt")

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name)
        (self.data / "profile").mkdir()
        self.write_profile(profile_from("tech"))
        self.ids = []
        for sample in self.SAMPLES:
            out = self.cli("jd", "parse", str(FIXTURES / sample), "--save")
            self.ids.append(out["saved"][0]["id"])

    def write_profile(self, data):
        (self.data / "profile" / "profile.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def cli(self, *args, expect=0, input_bytes=None):
        proc = run_cli(*args, data_dir=self.data, input_bytes=input_bytes)
        self.assertEqual(proc.returncode, expect, proc.stdout.decode("utf-8") + proc.stderr.decode("utf-8", "replace"))
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def listed(self):
        return [(row["job_id"], row["grade"], row["score"], row["stale"]) for row in self.cli("match", "list")["matches"]]

    def test_score_save_show_and_list(self):
        boss, test_dev, product, ruled_out = self.ids
        record = self.cli("match", "score", boss)
        self.assertEqual(record["total"]["score"], 81)
        self.assertFalse((self.data / "matches").exists(), "score without --save writes nothing")
        for job_id in self.ids:
            self.cli("match", "score", job_id, "--save")
        self.assertEqual(dict(self.cli("match", "show", boss), scored_at=None), dict(record, scored_at=None))
        self.assertEqual(self.listed(), [(boss, "strong", 81, False), (test_dev, "moderate", 54, False),
                                         (product, "poor", 27, False), (ruled_out, "ineligible", 57, False)])
        self.cli("match", "show", "job_000000000000", expect=1)

    def test_new_weights_reorder_the_list_once_rescored(self):
        boss, test_dev, product, ruled_out = self.ids
        for job_id in self.ids:
            self.cli("match", "score", job_id, "--save")
        before = [row[0] for row in self.listed()]
        self.assertEqual(before, [boss, test_dev, product, ruled_out])  # 81 strong, 54 moderate, 27 poor, ineligible
        self.write_profile(setting(profile_from("tech"), "target.weights",
                                   {"skills": 10, "direction": 10, "experience": 0, "salary": 80, "location": 0}))
        self.assertTrue(all(row[3] for row in self.listed()), "a changed profile makes every record stale")
        for job_id in self.ids:
            self.cli("match", "score", job_id, "--save")
        # Location weighs 0 here. boss (10*52+10*100+80*100)/100 = 95.2 -> 95; product 8000/100 = 80; test_dev has no
        # salary: 1000/20 = 50; the ruled-out job (250+1000+8000)/100 = 92.5 -> 93 still lists last.
        self.assertEqual(self.listed(), [(boss, "strong", 95, False), (product, "strong", 80, False),
                                         (test_dev, "moderate", 50, False), (ruled_out, "ineligible", 93, False)])

    def snapshot(self) -> dict:
        return {path: path.read_bytes() for path in sorted(self.data.rglob("*")) if path.is_file()}

    def save_agent_experience(self, job_id: str) -> dict:
        record = agent_filled(self.cli("match", "show", job_id))
        path = self.data / "draft.json"
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        self.cli("match", "save", str(path))
        path.unlink()
        return record

    def test_a_trial_writes_nothing_and_says_so(self):
        for job_id in self.ids:
            self.cli("match", "score", job_id, "--save")
        listed, before = self.cli("match", "list"), self.snapshot()
        self.assertNotIn("trial", listed)
        self.assertNotIn("saved", listed["matches"][0])
        out = self.cli("match", "list", "--weights", "skills=30,direction=25,experience=25,salary=10,location=40")
        self.assertEqual(self.snapshot(), before, "a trial writes no file")
        self.assertIn("试算", out["trial"]["note"])
        self.assertEqual(out["trial"]["weights"], dict(score.DEFAULT_WEIGHTS, location=40))
        self.assertEqual(out["trial"]["shares"], score.shares(dict(score.DEFAULT_WEIGHTS, location=40)))
        self.assertEqual(out["trial"]["profile"], {"weights": score.DEFAULT_WEIGHTS, "shares": score.DEFAULT_WEIGHTS})
        saved = {row["job_id"]: {"grade": row["grade"], "score": row["score"]} for row in listed["matches"]}
        self.assertEqual({row["job_id"]: row["saved"] for row in out["matches"]}, saved)
        # boss: (30*52 + 25*100 + 10*100 + 40*100) / 105 = 86.3 -> 86, from 81.
        boss = next(row for row in out["matches"] if row["job_id"] == self.ids[0])
        self.assertEqual((boss["grade"], boss["score"], boss["stale"]), ("strong", 86, False))

    def test_a_trial_ranks_as_scoring_again_with_those_weights_does(self):
        # The M2-6d acceptance: try the weights, then write them to the profile and score every job again.
        boss, test_dev, product, ruled_out = self.ids
        for job_id in self.ids:
            self.cli("match", "score", job_id, "--save")
        record = self.save_agent_experience(boss)
        weights = {"skills": 10, "direction": 10, "experience": 20, "salary": 60, "location": 0}
        text = ",".join(f"{key}={value}" for key, value in weights.items())
        trial = [(row["job_id"], row["grade"], row["score"], row["complete"])
                 for row in self.cli("match", "list", "--weights", text)["matches"]]
        # boss (520+1000+1600+6000)/100 = 91.2 -> 91, which needs its experience (94 without); product
        # 6000/80 = 75; test_dev 1000/20 = 50, so product now ranks above it; the ruled-out job 7250/80 = 90.6 -> 91.
        self.assertEqual([row[:3] for row in trial], [(boss, "strong", 91), (product, "strong", 75),
                                                      (test_dev, "moderate", 50), (ruled_out, "ineligible", 91)])
        self.write_profile(setting(profile_from("tech"), "target.weights", weights))
        self.assertEqual([row["stale_reasons"] for row in self.cli("match", "list")["matches"]],
                         [["weights"]] * len(self.ids))
        for job_id in self.ids:
            self.cli("match", "score", job_id, "--save")
        self.assertEqual(self.cli("match", "show", boss)["dimensions"]["experience"], record["dimensions"]["experience"])
        rescored = [(row["job_id"], row["grade"], row["score"], row["complete"], row["stale"])
                    for row in self.cli("match", "list")["matches"]]
        self.assertEqual(rescored, [row + (False,) for row in trial])

    def test_the_list_says_why_a_record_is_stale(self):
        self.cli("match", "score", self.ids[0], "--save")
        for path, value, reasons in (("target.weights", dict(score.DEFAULT_WEIGHTS, location=40), ["weights"]),
                                     ("availability.days_per_week", 5, ["profile"])):
            with self.subTest(path=path):
                self.write_profile(setting(profile_from("tech"), path, value))
                [row] = self.cli("match", "list")["matches"]
                self.assertEqual((row["stale"], row["stale_reasons"]), (True, reasons))
        self.write_profile(profile_from("tech"))
        [row] = self.cli("match", "list")["matches"]
        self.assertEqual((row["stale"], row["stale_reasons"]), (False, []))

    def test_trial_weights_must_be_five_numbers(self):
        self.cli("match", "score", self.ids[0], "--save")
        before = self.snapshot()
        for text, fragment in (
                ("skills=30,direction=25,experience=25,salary=10", "--weights.location: missing"),
                ("skills=30,direction=25,experience=25,salary=10,location=10,city=5", "--weights.city: unknown field"),
                ("skills=30,direction=25,experience=25,salary=10,location=-1", "is not one dimension=number"),
                ("skills=30,direction=25,experience=25,salary=10,location=ten", "is not one dimension=number"),
                ("skills=30,skills=25,experience=25,salary=10,location=10", "is not one dimension=number"),
                ('{"skills": 30, "direction": 25}', "is not one dimension=number"),
                ("skills=0,direction=0,experience=0,salary=0,location=0", "at least one weight must be above 0")):
            with self.subTest(text=text):
                proc = run_cli("match", "list", "--weights", text, data_dir=self.data)
                self.assertEqual((proc.returncode, proc.stdout), (2, b""))
                self.assertIn(fragment, json.loads(proc.stderr)["error"])
        self.assertEqual(self.snapshot(), before)
        spaced = self.cli("match", "list", "--weights", "skills=1.5, direction=0, experience=0, salary=0, location=0")
        self.assertEqual(spaced["trial"]["weights"]["skills"], 1.5)

    def test_validate_and_save_an_agents_record(self):
        boss = self.ids[0]
        record = agent_filled(self.cli("match", "score", boss))
        path = self.data / "draft.json"
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.cli("match", "validate", str(path)), {"valid": True, "errors": []})
        self.assertEqual(self.cli("match", "save", str(path)), {"saved": "created", "job_id": boss})
        self.assertEqual(self.cli("match", "show", boss)["dimensions"]["experience"]["score"], 80)
        # Rescoring an unchanged pair keeps what the agent added.
        self.assertEqual(self.cli("match", "score", boss, "--save")["dimensions"]["experience"]["score"], 80)
        tampered = setting(record, "total.score", 99)
        out = self.cli("match", "save", "-", expect=1, input_bytes=json.dumps(tampered, ensure_ascii=False).encode())
        self.assertFalse(out["valid"])
        self.assertEqual(self.cli("match", "show", boss)["total"]["score"], record["total"]["score"])

    def test_a_bad_evidence_reference_is_reported_as_json(self):
        record = agent_filled(self.cli("match", "score", self.ids[0]))
        path = self.data / "draft.json"
        for ref in ({}, ["exp-1"], 1):
            with self.subTest(ref=ref):
                bad = setting(record, "dimensions.experience.evidence.profile", [ref])
                path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
                out = self.cli("match", "validate", str(path), expect=1)
                self.assertEqual(out, {"valid": False, "errors": [
                    "dimensions.experience.evidence.profile[0]: must be an experience id (a string)"]})
                self.assertFalse(self.cli("match", "save", str(path), expect=1)["valid"])
        self.cli("match", "show", self.ids[0], expect=1)  # nothing was saved

    def test_errors_and_privacy(self):
        self.cli("match", "score", "job_000000000000", expect=1)
        bad = self.data / "bad.json"
        bad.write_text("{oops", encoding="utf-8")
        self.cli("match", "validate", str(bad), expect=2)
        bad.write_text(json.dumps({"job_id": "job_000000000000"}), encoding="utf-8")
        self.assertFalse(self.cli("match", "validate", str(bad), expect=1)["valid"])
        self.cli("match", "score", self.ids[0], "--save")
        outputs = [run_cli("match", *args, data_dir=self.data).stdout.decode("utf-8")
                   for args in (("score", self.ids[0]), ("show", self.ids[0]), ("list",))]
        for value in profile_from("tech")["contact"].values():
            if value:
                self.assertFalse(any(value in text for text in outputs), value)


if __name__ == "__main__":
    unittest.main()
