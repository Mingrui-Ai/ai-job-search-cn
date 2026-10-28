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
                self.assertCountEqual(expected["fields"], schema.EVIDENCE_FIELDS)
                self.assertCountEqual(expected["human_match"], ["tech", "ops"])
                for judged in expected["human_match"].values():
                    self.assertCountEqual(judged["checks"], match.CHECKS)

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


class V2(Oracles, unittest.TestCase):
    directory = REPO / "tests" / "fixtures" / "cn" / "jd-m2-3"


class V4(Oracles, unittest.TestCase):
    directory = REPO / "tests" / "fixtures" / "cn" / "jd-m2-3-holdout"
    fold_skills = True
    field_exceptions = {
        ("boss_business_development_intern.txt", "requirements.skills"): (
            ["客户访谈", "CRM", "Excel"],
            "H9 (ruled in the roadmap): PPT is not a vocabulary term until M2-4a makes it PowerPoint's synonym",
        ),
    }


if __name__ == "__main__":
    unittest.main()
