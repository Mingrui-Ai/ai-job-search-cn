"""Tests for jobsearch_cn/score.py and match score / validate / save / show / list (M2-4b).

Scoring is explainable only if it is reproducible and nobody can quietly bend
it, so these pin: each rule dimension, including every way it can be null;
the weighted total and its grade; gaps; that the same input gives the same
record; that a change to the job or profile marks a record stale and drops
what an agent added; that validate refuses the four tamperings in the roadmap
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


class Total(Case):
    def dims(self, **scores):
        return {name: {"score": scores.get(name)} for name in score.DIMENSIONS}

    def test_weighted_mean_of_the_scored_dimensions_rounded_half_up(self):
        weights = score.DEFAULT_WEIGHTS
        self.assertEqual(score.total(self.dims(skills=50, direction=75), weights, "eligible"),
                         {"score": 62, "grade": "good", "complete": False, "missing": ["experience", "salary"]})  # 4000/65 = 61.5
        # 62.5 rounds up to 63, not to the even 62.
        self.assertEqual(score.total(self.dims(skills=25, direction=100), {"skills": 1, "direction": 1,
                                                                            "experience": 1, "salary": 1}, "eligible")["score"], 63)

    def test_grades(self):
        for value, grade in ((75, "strong"), (74, "good"), (60, "good"), (59, "moderate"), (45, "moderate"),
                             (44, "weak"), (30, "weak"), (29, "poor"), (0, "poor")):
            with self.subTest(score=value):
                self.assertEqual(score.total(self.dims(skills=value), score.DEFAULT_WEIGHTS, "needs_check")["grade"], grade)

    def test_ruled_out_jobs_are_ineligible_but_keep_their_scores(self):
        result = score.total(self.dims(skills=100, direction=100, experience=100, salary=100), score.DEFAULT_WEIGHTS,
                             "ineligible")
        self.assertEqual((result["score"], result["grade"], result["complete"]), (100, "ineligible", True))

    def test_nothing_scored_has_no_total(self):
        self.assertEqual(score.total(self.dims(), score.DEFAULT_WEIGHTS, "needs_check"),
                         {"score": None, "grade": None, "complete": False, "missing": list(score.DIMENSIONS)})
        # A weight of 0 leaves a dimension out too.
        zero = dict(score.DEFAULT_WEIGHTS, skills=0)
        self.assertIsNone(score.total(self.dims(skills=80), zero, "eligible")["score"])

    def test_profile_weights_replace_the_defaults(self):
        weights = {"skills": 10, "direction": 10, "experience": 0, "salary": 80}
        record = scored(self.job, setting(self.tech, "target.weights", weights))
        self.assertEqual(record["weights"], weights)
        self.assertEqual(record["total"]["score"], 94)  # (10*43 + 10*100 + 80*100) / 100


class Gaps(Case):
    def test_missing_skills_low_salary_and_filter_findings_each_cite_the_jd(self):
        profile = setting(self.tech, "target.salary_min", {"amount": 300, "unit": "CNY/day"})
        profile = setting(profile, "availability.days_per_week", 3)
        gaps = scored(self.job, profile)["gaps"]
        self.assertIn({"kind": "skill", "item": "Redis", "jd": "参与 MySQL、Redis 等存储方案的设计与优化"}, gaps)
        self.assertIn({"kind": "salary", "item": "JD 上限 250 元/天，低于你的最低期望 300 元/天", "jd": "200-250元/天"}, gaps)
        [days] = [gap for gap in gaps if gap["kind"] == "filter"]
        self.assertEqual((days["item"], days["result"], days["jd"]), ("days_per_week", "conflict", "4天/周"))

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
        self.assertEqual(self.record["total"]["score"], 75)  # (35*43 + 30*100 + 25*80 + 10*100) / 100 = 75.05

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


# The rule part for the ten sample JDs against both sample profiles; experience is null
# (an agent's), so totals weigh skills 35, direction 30 and salary 10 over what is scored.
# Credits (match.md): 精通/熟练 1, 熟悉 0.8, 了解 0.5; no level 0.8 if used in an experience.
#   tech: Python 1, Go 1, MySQL 0.8, LangChain 0.8, RAG 0.8 (no level, used), Docker 0.8, PyTorch 0.5;
#         directions [tech]; salary_min 150 元/天.  ops: Excel 1, 秀米 1, 剪映 0.8, Photoshop 0.8;
#         directions [ops]; no salary_min (so salary is null for every ops row).
# Checked by hand:
#   boss_intern       tech  Go=Golang counted once, 6 skills: Go 1 + MySQL 0.8 + Docker 0.8 = 2.6/6 -> 43;
#                           all tech -> 100; 250 >= 150 -> 100; (35*43+30*100+10*100)/75 = 73.4 -> 73 good
#                     ops   no skill held -> 0; tech only, no ops skill -> 0; total 0; filter conflicts -> ineligible
#   shixiseng_intern  tech  4 skills, Python 1 -> 25; data 2 = tech 2, a tie both lead -> 100; 200 >= 150 -> 100;
#                           (875+3000+1000)/75 = 65; the filter rules it out (每周5天 > 4) -> ineligible
#   nowcoder_campus   tech  8 skills: RAG 0.8 + Python 1 + PyTorch 0.5 + LangChain 0.8 = 3.1/8 -> 39; tech -> 100;
#                           元/月 vs 元/天 -> null; (1365+3000)/65 = 67.2 -> 67; 校招 vs 实习 -> ineligible
#   official_site     tech  6 skills, PyTorch 0.5 -> 8; tech -> 100; 面议 -> null; (280+3000)/65 = 50.5 -> 50;
#                           no 届别 in the JD -> needs_check, so the grade stands: moderate
#   experienced_hire  tech  none of 8 held -> 0; tech -> 100; 元/月 -> null; 3000/65 = 46.2 -> 46; 社招 -> ineligible
#   boss_ai_product   tech  none held -> 0; product 4 leads, no tech skill -> 0; 220 >= 150 -> 100; 1000/75 = 13.3
#                           -> 13; the filter passes it -> poor
#                     ops   0; product leads, no ops skill -> 0; 0 -> ineligible (4天 > 3, 广州)
#   shixiseng_content tech  none held -> 0; ops 5 leads -> 0; 180 >= 150 -> 100; 13; 上海 -> ineligible
#                     ops   7 skills: 秀米 1 + 剪映 0.8 + Photoshop 0.8 + Excel 1 = 3.6/7 -> 51 (Excel is general:
#                           held, but no direction); ops leads -> 100; (1785+3000)/65 = 73.6 -> 74 good
#   ats_ui_design     tech  none held -> 0; design 6 -> 0; 面议 -> null; 0; needs_check -> poor
#                     ops   Photoshop 0.8/6 -> 13; design -> 0; 455/65 = 7; 杭州 -> ineligible
#   nowcoder_test_dev tech  none of the 6 test skills held -> 0; tech -> 100; 元/小时 -> null; 46 moderate
#   official_marketing tech none held -> 0; market 2 leads, no tech skill -> 0; 元/月 -> null; 0; 校招 -> ineligible
#                     ops   Excel 1/5 -> 20; market leads, 活动策划 is ops -> 50; (700+1500)/65 = 33.8 -> 34 weak
#   Every other ops row: no skill held, no ops skill -> 0 and 0, ruled out by the filter -> ineligible.
EXPECTED = {
    # (sample, profile): (skills, direction, salary, total, grade)
    ("jd/boss_intern.txt", "tech"): (43, 100, 100, 73, "good"),
    ("jd/shixiseng_intern.txt", "tech"): (25, 100, 100, 65, "ineligible"),
    ("jd/nowcoder_campus.txt", "tech"): (39, 100, None, 67, "ineligible"),
    ("jd/official_site.txt", "tech"): (8, 100, None, 50, "moderate"),
    ("jd/experienced_hire.txt", "tech"): (0, 100, None, 46, "ineligible"),
    ("jd-m2-3/boss_ai_product_intern.txt", "tech"): (0, 0, 100, 13, "poor"),
    ("jd-m2-3/shixiseng_content_ops_intern.txt", "tech"): (0, 0, 100, 13, "ineligible"),
    ("jd-m2-3/ats_ui_design_intern.txt", "tech"): (0, 0, None, 0, "poor"),
    ("jd-m2-3/nowcoder_test_dev_intern.txt", "tech"): (0, 100, None, 46, "moderate"),
    ("jd-m2-3/official_marketing_campus.txt", "tech"): (0, 0, None, 0, "ineligible"),
    ("jd/boss_intern.txt", "ops"): (0, 0, None, 0, "ineligible"),
    ("jd/shixiseng_intern.txt", "ops"): (0, 0, None, 0, "ineligible"),
    ("jd/nowcoder_campus.txt", "ops"): (0, 0, None, 0, "ineligible"),
    ("jd/official_site.txt", "ops"): (0, 0, None, 0, "ineligible"),
    ("jd/experienced_hire.txt", "ops"): (0, 0, None, 0, "ineligible"),
    ("jd-m2-3/boss_ai_product_intern.txt", "ops"): (0, 0, None, 0, "ineligible"),
    ("jd-m2-3/shixiseng_content_ops_intern.txt", "ops"): (51, 100, None, 74, "good"),
    ("jd-m2-3/ats_ui_design_intern.txt", "ops"): (13, 0, None, 7, "ineligible"),
    ("jd-m2-3/nowcoder_test_dev_intern.txt", "ops"): (0, 0, None, 0, "ineligible"),
    ("jd-m2-3/official_marketing_campus.txt", "ops"): (20, 50, None, 34, "weak"),
}


class SampleTable(unittest.TestCase):
    def test_ten_samples_by_two_profiles(self):
        self.assertEqual(len({sample for sample, _ in EXPECTED}), 10)
        self.assertEqual(len(EXPECTED), 20)

    def test_each_pair(self):
        for (sample, name), (skills, direction, salary, total, grade) in EXPECTED.items():
            with self.subTest(sample=sample, profile=name):
                record = scored(job_from(sample), profile_from(name))
                dimensions = record["dimensions"]
                self.assertEqual((dimensions["skills"]["score"], dimensions["direction"]["score"],
                                  dimensions["experience"]["score"], dimensions["salary"]["score"]),
                                 (skills, direction, None, salary))
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
        self.assertEqual(record["total"]["score"], 73)
        self.assertFalse((self.data / "matches").exists(), "score without --save writes nothing")
        for job_id in self.ids:
            self.cli("match", "score", job_id, "--save")
        self.assertEqual(dict(self.cli("match", "show", boss), scored_at=None), dict(record, scored_at=None))
        self.assertEqual(self.listed(), [(boss, "good", 73, False), (test_dev, "moderate", 46, False),
                                         (product, "poor", 13, False), (ruled_out, "ineligible", 65, False)])
        self.cli("match", "show", "job_000000000000", expect=1)

    def test_new_weights_reorder_the_list_once_rescored(self):
        boss, test_dev, product, ruled_out = self.ids
        for job_id in self.ids:
            self.cli("match", "score", job_id, "--save")
        before = [row[0] for row in self.listed()]
        self.assertEqual(before, [boss, test_dev, product, ruled_out])  # 73 good, 46 moderate, 13 poor, ineligible
        self.write_profile(setting(profile_from("tech"), "target.weights",
                                   {"skills": 10, "direction": 10, "experience": 0, "salary": 80}))
        self.assertTrue(all(row[3] for row in self.listed()), "a changed profile makes every record stale")
        for job_id in self.ids:
            self.cli("match", "score", job_id, "--save")
        # boss (10*43+10*100+80*100)/100 = 94; product 8000/100 = 80; test_dev has no salary: 1000/20 = 50;
        # the ruled-out job (250+1000+8000)/100 = 92.5 -> 93 still lists last.
        self.assertEqual(self.listed(), [(boss, "strong", 94, False), (product, "strong", 80, False),
                                         (test_dev, "moderate", 50, False), (ruled_out, "ineligible", 93, False)])

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
