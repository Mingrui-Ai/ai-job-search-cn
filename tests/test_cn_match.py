"""Tests for jobsearch_cn/match.py and `match filter`.

The filter may only rule a job out on facts both sides state, so these pin,
for every check, all three outcomes - match, conflict and unknown - and above
all that a value either side leaves empty is unknown, never a conflict. The
sample table runs the five sample JDs against the two sample profiles; each
row was checked by hand against the JD text (see the reasons in the table).
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
JDS = REPO / "tests" / "fixtures" / "cn" / "jd"
PROFILES = REPO / "tests" / "fixtures" / "cn" / "profile"

sys.path.insert(0, str(REPO))
from jobsearch_cn import jd_parser, match, store  # noqa: E402
from jobsearch_cn.match import CONFLICT, MATCH, NOT_APPLICABLE, UNKNOWN  # noqa: E402

NOW = datetime(2026, 10, 27, 10, 0, tzinfo=timezone(timedelta(hours=8)))


def job_from(name: str) -> dict:
    [record], _ = jd_parser.parse_text((JDS / name).read_text(encoding="utf-8"), now=NOW)
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


class CheckCase(unittest.TestCase):
    check = None

    def setUp(self):
        self.job = job_from("boss_intern.txt")
        self.profile = profile_from("tech")

    def result(self, job=None, profile=None) -> dict:
        out = match.filter_job(job or self.job, profile or self.profile)
        [item] = [c for c in out["checks"] if c["check"] == self.check]
        return item

    def assert_result(self, expected, job=None, profile=None):
        item = self.result(job, profile)
        self.assertEqual(item["result"], expected, item["reason"])
        return item


class Graduation(CheckCase):
    check = "graduation"

    def test_match(self):
        self.assert_result(MATCH)

    def test_strict_mismatch_is_a_conflict(self):
        job = setting(self.job, "requirements.graduation", {"years": [2026], "strict": True})
        self.assert_result(CONFLICT, job=job)

    def test_preferred_mismatch_is_only_a_note(self):
        job = setting(self.job, "requirements.graduation", {"years": [2026], "strict": False})
        item = self.assert_result(MATCH, job=job)
        self.assertIn("note", item)

    def test_unknown_either_side(self):
        self.assert_result(UNKNOWN, job=setting(self.job, "requirements.graduation", None))
        self.assert_result(UNKNOWN, profile=setting(self.profile, "graduation", None))


class Education(CheckCase):
    check = "education"

    def test_match_uses_the_highest_level(self):
        job = setting(self.job, "requirements.education", {"min": "master", "preferred": None})
        self.assert_result(MATCH, job=job)  # tech holds a bachelor's and a master's

    def test_conflict(self):
        job = setting(self.job, "requirements.education", {"min": "phd", "preferred": None})
        self.assert_result(CONFLICT, job=job)

    def test_preferred_level_alone_is_unknown_not_a_conflict(self):
        job = setting(self.job, "requirements.education", {"min": None, "preferred": "phd"})
        self.assert_result(UNKNOWN, job=job)

    def test_unknown_either_side(self):
        self.assert_result(UNKNOWN, job=setting(self.job, "requirements.education", None))
        self.assert_result(UNKNOWN, profile=setting(self.profile, "education", []))

    def test_no_minimum_matches_whatever_the_profile_holds(self):
        job = setting(self.job, "requirements.education", {"min": "none", "preferred": "master"})
        self.assert_result(MATCH, job=job)
        self.assert_result(MATCH, job=job, profile=setting(self.profile, "education", []))


class DaysAndMonths(CheckCase):
    LIMITS = (
        ("days_per_week", "requirements.days_per_week", "availability.days_per_week"),
        ("min_months", "requirements.min_months", "availability.months"),
    )

    def test_each_limit(self):
        for check, job_path, profile_path in self.LIMITS:
            with self.subTest(check=check):
                self.check = check
                profile = setting(self.profile, profile_path, 4)
                self.assert_result(MATCH, job=setting(self.job, job_path, 4), profile=profile)
                self.assert_result(CONFLICT, job=setting(self.job, job_path, 5), profile=profile)
                self.assert_result(UNKNOWN, job=setting(self.job, job_path, None), profile=profile)
                self.assert_result(UNKNOWN, job=setting(self.job, job_path, 5),
                                   profile=setting(self.profile, profile_path, None))

    def test_not_applicable_when_a_campus_or_experienced_hire_states_none(self):
        for check, job_path, profile_path in self.LIMITS:
            self.check = check
            profile = setting(self.profile, profile_path, 4)
            for kind in ("campus", "experienced"):
                with self.subTest(check=check, kind=kind):
                    job = setting(setting(self.job, "employment_type", kind), job_path, None)
                    item = self.assert_result(NOT_APPLICABLE, job=job, profile=profile)
                    self.assertEqual(item["jd"]["employment_type"]["value"], kind)
                    self.assert_result(NOT_APPLICABLE, job=job, profile=setting(self.profile, profile_path, None))
                    # A full-time hire that does state the days or months is compared as usual.
                    self.assert_result(CONFLICT, job=setting(job, job_path, 5), profile=profile)
            for kind in ("internship", None):
                with self.subTest(check=check, kind=kind):
                    job = setting(setting(self.job, "employment_type", kind), job_path, None)
                    self.assert_result(UNKNOWN, job=job, profile=profile)


class Location(CheckCase):
    check = "location"

    def place(self, cities, remote=None):
        return setting(setting(self.job, "cities", cities), "remote", remote)

    def wants(self, cities, remote_ok=None, relocate=None):
        profile = setting(self.profile, "availability.cities", cities)
        profile = setting(profile, "availability.remote_ok", remote_ok)
        return setting(profile, "availability.relocate", relocate)

    def test_shared_city_matches_ignoring_the_shi_suffix(self):
        self.assert_result(MATCH, job=self.place(["深圳"]), profile=self.wants(["深圳市"], False, False))

    def test_remote_both_ways_matches_without_a_shared_city(self):
        self.assert_result(MATCH, job=self.place(["北京"], True), profile=self.wants(["深圳"], True, False))

    def test_willing_to_relocate_matches_with_a_note(self):
        item = self.assert_result(MATCH, job=self.place(["北京"], False), profile=self.wants(["深圳"], False, True))
        self.assertIn("note", item)

    def test_no_shared_city_no_remote_no_move_is_a_conflict(self):
        # Remote ruled out by either side, and no move.
        self.assert_result(CONFLICT, job=self.place(["北京"], False), profile=self.wants(["深圳"], False, False))
        self.assert_result(CONFLICT, job=self.place(["北京"], None), profile=self.wants(["深圳"], False, False))
        self.assert_result(CONFLICT, job=self.place(["北京"], False), profile=self.wants(["深圳"], None, False))
        self.assert_result(CONFLICT, job=self.place(["北京"], False), profile=self.wants(["深圳"], True, False))
        self.assert_result(CONFLICT, job=self.place(["北京"], True), profile=self.wants(["深圳"], False, False))

    def test_unknown_when_a_way_out_is_unstated(self):
        cases = [
            (self.place([], None), self.wants(["深圳"], False, False)),         # JD names no city
            (self.place(["北京"], False), self.wants([], False, False)),        # profile names no city
            (self.place(["北京"], False), self.wants(["深圳"], False, None)),   # relocation unknown
            (self.place(["北京"], None), self.wants(["深圳"], True, False)),    # JD remote unknown
            (self.place(["北京"], True), self.wants(["深圳"], None, False)),    # profile remote unknown
            (self.place(["北京"], None), self.wants(["深圳"], None, False)),    # remote unstated on both sides
        ]
        for job, profile in cases:
            with self.subTest(job=job["cities"], profile=profile["availability"]):
                self.assert_result(UNKNOWN, job=job, profile=profile)

    def test_an_unknown_says_which_side_is_silent(self):
        # The case the user hit: the profile answers both questions, the JD neither.
        item = self.assert_result(UNKNOWN, job=self.place(["北京"], None), profile=self.wants(["深圳"], True, False))
        self.assertEqual(item["reason"], "北京不在意向城市内；JD 没写能否远程；你接受远程、不考虑异地")
        item = self.assert_result(UNKNOWN, job=self.place(["北京"], True), profile=self.wants(["深圳"], None, None))
        self.assertEqual(item["reason"], "北京不在意向城市内；JD 可远程；档案没写是否接受远程和是否愿意去其他城市")
        item = self.assert_result(UNKNOWN, job=self.place(["北京"], False), profile=self.wants(["深圳"], False, None))
        self.assertEqual(item["reason"], "北京不在意向城市内；JD 不支持远程；你不接受远程；档案没写是否愿意去其他城市")


class EmploymentType(CheckCase):
    check = "employment_type"

    def test_three_results(self):
        self.assert_result(MATCH)
        self.assert_result(CONFLICT, job=setting(self.job, "employment_type", "experienced"))
        self.assert_result(UNKNOWN, job=setting(self.job, "employment_type", None))
        self.assert_result(UNKNOWN, profile=setting(self.profile, "target.employment_types", []))


class Exclusions(CheckCase):
    check = "exclusions"

    def test_match(self):
        self.assert_result(MATCH)

    def test_keyword_in_the_title_is_a_conflict(self):
        self.assert_result(CONFLICT, job=setting(self.job, "title", "后端开发实习生（外包）"))

    def test_keyword_in_the_body_only_is_not(self):
        job = setting(self.job, "raw_text", self.job["raw_text"] + "\n本岗位不是外包。")
        self.assert_result(MATCH, job=job)

    def test_excluded_company_and_all_cities_excluded(self):
        profile = setting(self.profile, "exclusions.companies", ["示例互联网"])
        self.assert_result(CONFLICT, profile=profile)
        profile = setting(self.profile, "exclusions.cities", ["深圳"])
        self.assert_result(CONFLICT, profile=profile)

    def test_unknown_when_the_title_is_missing(self):
        self.assert_result(UNKNOWN, job=setting(self.job, "title", None))


class Verdict(CheckCase):
    def test_any_conflict_rules_out(self):
        out = match.filter_job(setting(self.job, "employment_type", "experienced"), self.profile)
        self.assertEqual(out["verdict"], "ineligible")

    def test_unknown_without_conflict_needs_checking(self):
        out = match.filter_job(setting(self.job, "requirements.days_per_week", None), self.profile)
        self.assertEqual(out["verdict"], "needs_check")

    def test_all_match_is_eligible(self):
        self.assertEqual(match.filter_job(self.job, self.profile)["verdict"], "eligible")

    def test_not_applicable_counts_like_a_match(self):
        job = setting(self.job, "employment_type", "campus")
        job = setting(setting(job, "requirements.days_per_week", None), "requirements.min_months", None)
        out = match.filter_job(job, setting(self.profile, "target.employment_types", ["campus"]))
        results = {c["check"]: c["result"] for c in out["checks"]}
        self.assertEqual((results["days_per_week"], results["min_months"]), (NOT_APPLICABLE, NOT_APPLICABLE))
        self.assertEqual(out["verdict"], "eligible")

    def test_an_empty_job_is_never_ruled_out(self):
        # Everything the parser could not read is unknown: the filter must not
        # cost the user a job over fields nobody filled in.
        [job], _ = jd_parser.parse_text("招人，有意私聊。", now=NOW)
        out = match.filter_job(job, self.profile)
        self.assertNotIn(CONFLICT, {c["result"] for c in out["checks"]})
        self.assertEqual(out["verdict"], "needs_check")

    def test_every_check_runs_once_and_cites_both_sides(self):
        out = match.filter_job(self.job, self.profile)
        self.assertEqual([c["check"] for c in out["checks"]], list(match.CHECKS))
        for item in out["checks"]:
            self.assertTrue(item["jd"] and item["profile"], item["check"])
        location = next(c for c in out["checks"] if c["check"] == "location")
        self.assertEqual(location["jd"]["cities"]["evidence"], self.job["evidence"]["cities"]["text"])

    def test_contact_details_never_appear(self):
        text = json.dumps(match.filter_job(self.job, self.profile), ensure_ascii=False)
        for value in self.profile["contact"].values():
            if value:
                self.assertNotIn(value, text)


G, E, D, M, L, T, X = match.CHECKS

# (JD fixture, profile) -> verdict and every non-match check. Checked by hand (the 校招 and 社招
# samples state no weekly days or internship length, so both are not_applicable for them):
#   tech  boss       all match (2026/2027届, 本科及以上, 4天, 6个月, 深圳, 实习)
#   tech  nowcoder   校招 vs 实习 -> conflict; 北京/杭州, JD silent on remote, no relocation -> unknown
#   tech  experienced 社招 -> conflict; 上海 and "不支持远程办公", no relocation -> conflict
#   tech  shixiseng  "每周到岗5天" > 4 -> conflict; 上海, JD silent on remote -> unknown;
#                    the headline "本科" is not read as a minimum -> unknown
#   tech  official   杭州 but "支持远程实习" and remote_ok -> match; no 届别 in the JD -> unknown
#   ops   boss       4天 > 3, 6个月 > 3, 深圳 with no remote or move -> three conflicts
#   ops   nowcoder   硕士 > 本科, 北京/杭州 -> conflicts; 校招 is in ops's target
#   ops   experienced 社招 -> conflict; 上海 matches
#   ops   shixiseng  5天 > 3 -> conflict; 3个月 = 3 and 上海 match
#   ops   official   硕士, 6个月, 杭州 (remote offered, ops refuses remote) -> conflicts
#   tech  boss_paste_backend  "5天/周" > 4 -> conflict; 北京, JD silent on remote, no relocation -> unknown
#   tech  boss_paste_ops      上海, JD silent on remote -> unknown; 4天 = 4 and 3个月 < 6 match
#   tech  boss_fullpage       no work city read (the address sits under a bare "工作地址" heading) -> unknown
#   ops   boss_paste_backend  5天 > 3, 4个月 > 3, 北京 with no remote or move -> three conflicts
#   ops   boss_paste_ops      4天 > 3 -> conflict; 3个月 = 3 and 上海 match
#   ops   boss_fullpage       4天 > 3, 6个月 > 3 -> conflicts; no work city -> unknown
SAMPLE_TABLE = {
    ("boss_intern.txt", "tech"): ("eligible", {}),
    ("nowcoder_campus.txt", "tech"): ("ineligible", {D: NOT_APPLICABLE, M: NOT_APPLICABLE, L: UNKNOWN, T: CONFLICT}),
    ("experienced_hire.txt", "tech"): ("ineligible", {G: UNKNOWN, D: NOT_APPLICABLE, M: NOT_APPLICABLE,
                                                      L: CONFLICT, T: CONFLICT}),
    ("shixiseng_intern.txt", "tech"): ("ineligible", {E: UNKNOWN, D: CONFLICT, L: UNKNOWN}),
    ("official_site.txt", "tech"): ("needs_check", {G: UNKNOWN}),
    ("boss_intern.txt", "ops"): ("ineligible", {D: CONFLICT, M: CONFLICT, L: CONFLICT}),
    ("nowcoder_campus.txt", "ops"): ("ineligible", {E: CONFLICT, D: NOT_APPLICABLE, M: NOT_APPLICABLE, L: CONFLICT}),
    ("experienced_hire.txt", "ops"): ("ineligible", {G: UNKNOWN, D: NOT_APPLICABLE, M: NOT_APPLICABLE, T: CONFLICT}),
    ("shixiseng_intern.txt", "ops"): ("ineligible", {E: UNKNOWN, D: CONFLICT}),
    ("official_site.txt", "ops"): ("ineligible", {G: UNKNOWN, E: CONFLICT, M: CONFLICT, L: CONFLICT}),
    ("boss_paste_backend_intern.txt", "tech"): ("ineligible", {D: CONFLICT, L: UNKNOWN}),
    ("boss_paste_ops_intern.txt", "tech"): ("needs_check", {L: UNKNOWN}),
    ("boss_fullpage_data_intern.txt", "tech"): ("needs_check", {L: UNKNOWN}),
    ("boss_paste_backend_intern.txt", "ops"): ("ineligible", {D: CONFLICT, M: CONFLICT, L: CONFLICT}),
    ("boss_paste_ops_intern.txt", "ops"): ("ineligible", {D: CONFLICT}),
    ("boss_fullpage_data_intern.txt", "ops"): ("ineligible", {D: CONFLICT, M: CONFLICT, L: UNKNOWN}),
}


class SampleTable(unittest.TestCase):
    def test_the_table_covers_every_sample(self):
        jds = {p.name for p in JDS.glob("*.txt")}
        profiles = {p.name for p in PROFILES.iterdir() if p.is_dir()}
        self.assertEqual(set(SAMPLE_TABLE), {(j, p) for j in jds for p in profiles})

    def test_each_pair(self):
        for (jd, name), (verdict, departures) in SAMPLE_TABLE.items():
            with self.subTest(jd=jd, profile=name):
                out = match.filter_job(job_from(jd), profile_from(name))
                results = {c["check"]: c["result"] for c in out["checks"]}
                self.assertEqual({k: v for k, v in results.items() if v != MATCH}, departures)
                self.assertEqual(out["verdict"], verdict)


def run_cli(*args, data_dir):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", **{store.DATA_DIR_ENV: str(data_dir)})
    return subprocess.run([sys.executable, "-m", "jobsearch_cn", *args], cwd=REPO, env=env, capture_output=True)


class Command(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name)
        shutil.copytree(PROFILES / "tech", self.data / "profile")
        proc = run_cli("jd", "parse", str(JDS / "boss_intern.txt"), "--save", data_dir=self.data)
        self.job_id = json.loads(proc.stdout)["saved"][0]["id"]

    def test_filter_a_stored_job(self):
        proc = run_cli("match", "filter", self.job_id, data_dir=self.data)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8"))
        out = json.loads(proc.stdout)
        self.assertEqual((out["job_id"], out["verdict"]), (self.job_id, "eligible"))
        self.assertNotIn("13800000000", proc.stdout.decode("utf-8"))

    def test_another_profile_file(self):
        proc = run_cli("match", "filter", self.job_id, "--profile", str(PROFILES / "ops" / "profile.json"),
                       data_dir=self.data)
        self.assertEqual(json.loads(proc.stdout)["verdict"], "ineligible")

    def test_nothing_is_written(self):
        before = sorted(p.relative_to(self.data) for p in self.data.rglob("*"))
        run_cli("match", "filter", self.job_id, data_dir=self.data)
        self.assertEqual(sorted(p.relative_to(self.data) for p in self.data.rglob("*")), before)

    def test_errors(self):
        self.assertEqual(run_cli("match", "filter", "job_000000000000", data_dir=self.data).returncode, 1)
        self.assertEqual(run_cli("match", "filter", "../x", data_dir=self.data).returncode, 2)
        bad = json.loads((self.data / "profile" / "profile.json").read_text(encoding="utf-8"))
        bad["availability"]["days_per_week"] = 9
        (self.data / "profile" / "profile.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(run_cli("match", "filter", self.job_id, data_dir=self.data).returncode, 1)
        (self.data / "profile" / "profile.json").unlink()
        self.assertEqual(run_cli("match", "filter", self.job_id, data_dir=self.data).returncode, 2)


if __name__ == "__main__":
    unittest.main()
