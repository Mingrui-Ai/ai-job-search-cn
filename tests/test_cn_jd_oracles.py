"""Verifier oracles: frozen sample JDs parse and filter the way the verifier expected.

The verifier (Codex) wrote each set of five JDs and, for each, the value of
every Job Schema field group and the filter verdict and check results against
the two sample profiles - all frozen before the rules first ran on them
(oracle-manifest.json). These compare jd parse and match filter with those
expectations as written: per set, 5 x 14 field groups, 10 verdicts, 10 x 7
checks. The expected files are never edited to fit the code. When the code
should not meet an expectation, that goes to the planner, and only an
exception the planner has ruled on is written here, with its reason.

- V2 (tests/fixtures/cn/jd-m2-3/, M2-3): compared exactly.
- V4 (tests/fixtures/cn/jd-m2-3-holdout/): the holdout for M2-3, a regression
  set since H9 tuned rules on it. Skills compare ignoring case and spaces, as
  its expectations were written (PowerBI is Power BI).
- V6 (tests/fixtures/cn/jd-h9-holdout/): the holdout for H9, a regression set
  since H12 tuned rules on it (H15). Skills compare as in V4. Its exceptions are
  the rule-level expectations the verifier froze beside the human truth.
- V8 (tests/fixtures/cn/jd-h16-holdout/): the holdout for H16; only the minimum
  degree, the skills and the education check, which H20 fixed (V8Education).
"""
import hashlib
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROFILES = REPO / "tests" / "fixtures" / "cn" / "profile"

sys.path.insert(0, str(REPO))
from jobsearch_cn import jd_parser, match, schema  # noqa: E402

NOW = datetime(2026, 10, 27, 10, 0, tzinfo=timezone(timedelta(hours=8)))
# Fields added after the expectations were frozen (H16, M2-6c).
LATER_FIELDS = (schema.ALTERNATIVES, "requirements.start", "interview")


def profile(name: str) -> dict:
    return json.loads((PROFILES / name / "profile.json").read_text(encoding="utf-8"))


class Oracles:
    """The checks for one frozen set; a subclass names its directory and any ruled exceptions."""

    directory: Path = None
    fold_skills = False
    # (sample, field) / (sample, profile, check) / (sample, profile) -> (value, reason)
    field_exceptions: dict = {}
    check_exceptions: dict = {}
    verdict_exceptions: dict = {}

    def expectations(self) -> list:
        return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(self.directory.glob("*.expected.json"))]

    def parsed(self, expected: dict) -> dict:
        text = (self.directory / expected["fixture"]).read_text(encoding="utf-8")
        [record], _ = jd_parser.parse_text(text, source_type="file", site=expected["site_argument"], now=NOW)
        return record

    def test_the_frozen_files_are_unchanged(self):
        # The digests are of the LF text git stores; a Windows checkout may have CRLF.
        manifest = json.loads((self.directory / "oracle-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["oracle_files_sha256"]), 10)
        for name, digest in manifest["oracle_files_sha256"].items():
            with self.subTest(file=name):
                data = (self.directory / name).read_bytes().replace(b"\r\n", b"\n")
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)

    def test_five_samples_each_with_every_field_group_and_both_profiles(self):
        samples = self.expectations()
        self.assertEqual(sorted(e["fixture"] for e in samples), sorted(p.name for p in self.directory.glob("*.txt")))
        self.assertEqual(len(samples), 5)
        for expected in samples:
            with self.subTest(sample=expected["fixture"]):
                # Frozen before H16 added requirements.skill_alternatives, and M2-6c the interview and
                # the start date with their checks: the expectations do not compare those.
                self.assertCountEqual(expected["fields"], [f for f in schema.EVIDENCE_FIELDS if f not in LATER_FIELDS])
                self.assertCountEqual(expected["human_match"], ["tech", "ops"])
                for judged in expected["human_match"].values():
                    self.assertCountEqual(judged["checks"], [c for c in match.CHECKS if c not in match.TO_CONFIRM])

    def test_every_exception_departs_from_a_frozen_value_and_says_why(self):
        # A stale exception - one the code no longer needs, or one naming nothing - fails here.
        frozen = {}
        for expected in self.expectations():
            name = expected["fixture"]
            frozen.update({(name, path): field["value"] for path, field in expected["fields"].items()})
            for who, judged in expected["human_match"].items():
                frozen[(name, who)] = judged["verdict"]
                frozen.update({(name, who, check): human["result"] for check, human in judged["checks"].items()})
        exceptions = {**self.field_exceptions, **self.check_exceptions, **self.verdict_exceptions}
        for key, (value, reason) in exceptions.items():
            with self.subTest(exception=key):
                self.assertIn(key, frozen)
                self.assertNotEqual(value, frozen[key])
                self.assertTrue(reason.strip())

    def assert_field(self, path: str, actual, expected):
        if path == "requirements.skills" and self.fold_skills:
            self.assertEqual({schema.normalize_for_match(s) for s in actual},
                             {schema.normalize_for_match(s) for s in expected})
        elif isinstance(expected, list):
            self.assertCountEqual(actual, expected)  # in any order
        else:
            self.assertEqual(actual, expected)

    def test_every_field_group(self):
        for expected in self.expectations():
            record = self.parsed(expected)
            for path, field in expected["fields"].items():
                key = (expected["fixture"], path)
                value = self.field_exceptions[key][0] if key in self.field_exceptions else field["value"]
                with self.subTest(sample=expected["fixture"], field=path):
                    self.assert_field(path, schema._field(record, path), value)

    def test_every_verdict_and_check(self):
        for expected in self.expectations():
            record = self.parsed(expected)
            name = expected["fixture"]
            for who, judged in expected["human_match"].items():
                out = match.filter_job(record, profile(who))
                results = {item["check"]: item["result"] for item in out["checks"]}
                verdict = self.verdict_exceptions.get((name, who), (judged["verdict"],))[0]
                with self.subTest(sample=name, profile=who):
                    self.assertEqual(out["verdict"], verdict)
                for check, human in judged["checks"].items():
                    result = self.check_exceptions.get((name, who, check), (human["result"],))[0]
                    with self.subTest(sample=name, profile=who, check=check):
                        self.assertEqual(results[check], result)


# M2-4a (roadmap) added contract values the frozen expectations predate; the planner
# listed what they change. A JD that says outright there is no minimum degree is min
# "none", which the filter takes as a match; a campus hire states no weekly days or
# internship length, which are not_applicable to it, so nothing unknown is left for ops.
NO_MINIMUM = "M2-4a: 不设最低学历门槛 is a stated minimum, none"
NONE_MATCHES = "M2-4a: a JD with no minimum degree matches any candidate"
CAMPUS = "M2-4a: a 校招 that states no weekly days or internship length asks none"


class V2(Oracles, unittest.TestCase):
    directory = REPO / "tests" / "fixtures" / "cn" / "jd-m2-3"
    field_exceptions = {
        ("ats_ui_design_intern.txt", "requirements.education"): ({"min": "none", "preferred": "master"}, NO_MINIMUM),
    }
    check_exceptions = {
        ("ats_ui_design_intern.txt", "tech", "education"): ("match", NONE_MATCHES),
        ("ats_ui_design_intern.txt", "ops", "education"): ("match", NONE_MATCHES),
        ("official_marketing_campus.txt", "tech", "days_per_week"): ("not_applicable", CAMPUS),
        ("official_marketing_campus.txt", "tech", "min_months"): ("not_applicable", CAMPUS),
        ("official_marketing_campus.txt", "ops", "days_per_week"): ("not_applicable", CAMPUS),
        ("official_marketing_campus.txt", "ops", "min_months"): ("not_applicable", CAMPUS),
    }
    verdict_exceptions = {
        ("official_marketing_campus.txt", "ops"): ("eligible", CAMPUS + "; nothing is unknown any more"),
    }


class V4(Oracles, unittest.TestCase):
    directory = REPO / "tests" / "fixtures" / "cn" / "jd-m2-3-holdout"
    fold_skills = True
    check_exceptions = {
        ("official_finance_campus.txt", "tech", "days_per_week"): ("not_applicable", CAMPUS),
        ("official_finance_campus.txt", "tech", "min_months"): ("not_applicable", CAMPUS),
        ("official_finance_campus.txt", "ops", "days_per_week"): ("not_applicable", CAMPUS),
        ("official_finance_campus.txt", "ops", "min_months"): ("not_applicable", CAMPUS),
    }
    verdict_exceptions = {
        ("official_finance_campus.txt", "ops"): ("eligible", CAMPUS + "; nothing is unknown any more"),
    }


# H9 (roadmap): when a JD gives different internship lengths, the rule leaves min_months
# blank rather than pick one. Two V6 samples quote a platform's 3 months beside the
# role's 4. Their human truth stays 4, and the verifier froze the rule's blank and the
# filter results that follow from it next to it (rule_expectations, policy_blank_match).
POLICY_BLANK = "H9: 3 and 4 months both appear, so the rule leaves min_months blank"
MONTHS_UNKNOWN = "H9: a blank min_months is unknown to the filter"
DURATION_SAMPLES = ("official_test_duration.txt", "ats_recruiting_duration.txt")


class V6(Oracles, unittest.TestCase):
    directory = REPO / "tests" / "fixtures" / "cn" / "jd-h9-holdout"
    fold_skills = True
    field_exceptions = {(name, "requirements.min_months"): (None, POLICY_BLANK) for name in DURATION_SAMPLES}
    check_exceptions = {(name, who, "min_months"): ("unknown", MONTHS_UNKNOWN)
                        for name in DURATION_SAMPLES for who in ("tech", "ops")}
    verdict_exceptions = {
        ("official_test_duration.txt", "tech"): ("needs_check", MONTHS_UNKNOWN),
        ("ats_recruiting_duration.txt", "tech"): ("needs_check", MONTHS_UNKNOWN),
        ("ats_recruiting_duration.txt", "ops"): ("needs_check", MONTHS_UNKNOWN),
    }

    def test_the_exceptions_are_the_frozen_rule_expectations(self):
        # Every exception, and nothing more, is a value the verifier froze for the blank.
        frozen = {}
        for expected in self.expectations():
            name = expected["fixture"]
            for path, rule in expected.get("rule_expectations", {}).items():
                frozen[(name, path)] = rule["value"]
            for who, judged in expected.get("policy_blank_match", {}).items():
                human = expected["human_match"][who]
                if judged["verdict"] != human["verdict"]:
                    frozen[(name, who)] = judged["verdict"]
                for check, result in judged["checks"].items():
                    if result["result"] != human["checks"][check]["result"]:
                        frozen[(name, who, check)] = result["result"]
        exceptions = {**self.field_exceptions, **self.check_exceptions, **self.verdict_exceptions}
        self.assertEqual({key: value for key, (value, _) in exceptions.items()}, frozen)


class V8Education(unittest.TestCase):
    """H20: V8 (tests/fixtures/cn/jd-h16-holdout/, the holdout for H16) found two misreads the rules
    had before H16 - a choice of degrees took the higher one, a major was read as a skill. Its
    minimum degrees, skills and education checks now meet the frozen expectations; the rest of
    V8 is compared in its own reports, not here."""

    directory = REPO / "tests" / "fixtures" / "cn" / "jd-h16-holdout"
    FIELDS = ("requirements.education", "requirements.skills")

    def expectations(self) -> list:
        manifest = json.loads((self.directory / "oracle-manifest.json").read_text(encoding="utf-8"))
        samples = []
        for name, digest in manifest["oracle_files_lf_sha256"].items():
            if name.endswith(".expected.json") and name != "alternative-groups.expected.json":
                data = (self.directory / name).read_bytes().replace(b"\r\n", b"\n")
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest, name)  # frozen, never edited
                samples.append(json.loads(data.decode("utf-8")))
        self.assertEqual(len(samples), 5)
        return samples

    def test_education_and_skills(self):
        for expected in self.expectations():
            text = (self.directory / expected["fixture"]).read_text(encoding="utf-8")
            [record], _ = jd_parser.parse_text(text, source_type="file", site=expected["site_argument"], now=NOW)
            for path in self.FIELDS:
                with self.subTest(sample=expected["fixture"], field=path):
                    self.assertEqual(schema._field(record, path), expected["fields"][path]["value"])
            for who, judged in expected["human_match"].items():
                checks = {c["check"]: c["result"] for c in match.filter_job(record, profile(who))["checks"]}
                with self.subTest(sample=expected["fixture"], profile=who):
                    self.assertEqual(checks["education"], judged["checks"]["education"]["result"])


if __name__ == "__main__":
    unittest.main()
