"""V2 oracles: the M2-3 samples parse and filter the way the verifier expected.

The verifier (Codex) wrote the five JDs in tests/fixtures/cn/jd-m2-3/ and, for
each, the value of every Job Schema field group and the filter verdict and
check results against the two sample profiles - all frozen before the rules
first ran on them (oracle-manifest.json). These compare jd parse and match
filter with those expectations as written: 5 x 14 field groups, 10 verdicts,
10 x 7 checks. The expected files are never edited to fit the code. When the
code should not meet an expectation, that goes to the planner, and only an
exception the planner has ruled on is written here, with its reason.
"""
import hashlib
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ORACLES = REPO / "tests" / "fixtures" / "cn" / "jd-m2-3"
PROFILES = REPO / "tests" / "fixtures" / "cn" / "profile"

sys.path.insert(0, str(REPO))
from jobsearch_cn import jd_parser, match, schema  # noqa: E402

NOW = datetime(2026, 10, 27, 10, 0, tzinfo=timezone(timedelta(hours=8)))


def expectations() -> list:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(ORACLES.glob("*.expected.json"))]


def parsed(expected: dict) -> dict:
    text = (ORACLES / expected["fixture"]).read_text(encoding="utf-8")
    [record], _ = jd_parser.parse_text(text, source_type="file", site=expected["site_argument"], now=NOW)
    return record


def profile(name: str) -> dict:
    return json.loads((PROFILES / name / "profile.json").read_text(encoding="utf-8"))


class Oracles(unittest.TestCase):
    def test_the_frozen_files_are_unchanged(self):
        # The digests are of the LF text git stores; a Windows checkout may have CRLF.
        manifest = json.loads((ORACLES / "oracle-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["oracle_files_sha256"]), 10)
        for name, digest in manifest["oracle_files_sha256"].items():
            with self.subTest(file=name):
                data = (ORACLES / name).read_bytes().replace(b"\r\n", b"\n")
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)

    def test_five_samples_each_with_every_field_group_and_both_profiles(self):
        samples = expectations()
        self.assertEqual(sorted(e["fixture"] for e in samples), sorted(p.name for p in ORACLES.glob("*.txt")))
        self.assertEqual(len(samples), 5)
        for expected in samples:
            with self.subTest(sample=expected["fixture"]):
                self.assertCountEqual(expected["fields"], schema.EVIDENCE_FIELDS)
                self.assertCountEqual(expected["human_match"], ["tech", "ops"])
                for judged in expected["human_match"].values():
                    self.assertCountEqual(judged["checks"], match.CHECKS)

    def test_every_field_group(self):
        for expected in expectations():
            record = parsed(expected)
            for path, field in expected["fields"].items():
                with self.subTest(sample=expected["fixture"], field=path):
                    if isinstance(field["value"], list):
                        self.assertCountEqual(schema._field(record, path), field["value"])  # in any order
                    else:
                        self.assertEqual(schema._field(record, path), field["value"])

    def test_every_verdict_and_check(self):
        for expected in expectations():
            record = parsed(expected)
            for name, judged in expected["human_match"].items():
                out = match.filter_job(record, profile(name))
                results = {item["check"]: item["result"] for item in out["checks"]}
                with self.subTest(sample=expected["fixture"], profile=name):
                    self.assertEqual(out["verdict"], judged["verdict"])
                for check, human in judged["checks"].items():
                    with self.subTest(sample=expected["fixture"], profile=name, check=check):
                        self.assertEqual(results[check], human["result"])


if __name__ == "__main__":
    unittest.main()
