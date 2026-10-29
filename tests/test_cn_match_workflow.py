"""M2-4c: the agent scoring workflow (docs/cn/match.md, 评分工作流), end to end.

Two parts. The documented steps run through the real CLI on two sample JDs,
the way an agent follows them: score with --draft, write the experience into
the draft, validate (which names the total to copy), save, show and list. And
the experience judgments an agent made for the ten sample JDs against both
sample profiles (tests/fixtures/cn/match-m2-4c/agent-judgments.json), written
before the verifier's V5 judgments were seen and frozen by digest for the
M2-4c acceptance comparison: each validates against its job and profile, and
together they give the totals and rankings recorded here. Those rankings must
keep meeting the acceptance against the verifier's human rankings (V5,
tests/fixtures/cn/match-m2-4/), whatever later rule changes do to the totals.
"""
import copy
import hashlib
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
FIXTURES = REPO / "tests" / "fixtures" / "cn"
JUDGMENTS = FIXTURES / "match-m2-4c" / "agent-judgments.json"
# The LF digest when the judgments were written, before V5 was seen. Changing a
# judgment is a planner's call; update the digest with it and say why.
FROZEN_SHA256 = "9d0fe6b0ff5c89055882d4d5b1bda516b0b4ed43189727fa642544faf52c3c21"
# V5's human judgments (PR #29), frozen before any scoring code ran; the LF digest of
# its rankings as its oracle-manifest.json records them.
V5 = FIXTURES / "match-m2-4"
V5_RANKINGS_SHA256 = "6b3cac544d97340553d14365e6b61f5379d8def48c4fe9adf3f9ce32f0fa089f"

sys.path.insert(0, str(REPO))
from jobsearch_cn import jd_parser, score, store, vocab  # noqa: E402

NOW = datetime(2026, 10, 27, 10, 0, tzinfo=timezone(timedelta(hours=8)))
VOCABULARY = vocab.load()
# The ten samples of the M2-4b table (tests/test_cn_score.py) and of V5.
SAMPLES = (
    "jd/boss_intern.txt", "jd/shixiseng_intern.txt", "jd/nowcoder_campus.txt", "jd/official_site.txt",
    "jd/experienced_hire.txt", "jd-m2-3/boss_ai_product_intern.txt", "jd-m2-3/shixiseng_content_ops_intern.txt",
    "jd-m2-3/ats_ui_design_intern.txt", "jd-m2-3/nowcoder_test_dev_intern.txt",
    "jd-m2-3/official_marketing_campus.txt",
)


def judgments() -> list:
    return json.loads(JUDGMENTS.read_text(encoding="utf-8"))["judgments"]


def judged(sample: str, name: str) -> dict:
    return next(j["experience"] for j in judgments() if (j["sample"], j["profile"]) == (sample, name))


def job_from(sample: str) -> dict:
    [record], _ = jd_parser.parse_text((FIXTURES / sample).read_text(encoding="utf-8"), now=NOW)
    return record


def profile_from(name: str) -> dict:
    return json.loads((FIXTURES / "profile" / name / "profile.json").read_text(encoding="utf-8"))


def completed(record: dict, experience: dict) -> dict:
    """What the agent hands back: the experience filled in; the total as validate gives it."""
    record = copy.deepcopy(record)
    record["dimensions"]["experience"].update(experience)
    record["total"] = score.total(record["dimensions"], record["weights"], record["filter"]["verdict"])
    return record


def records(name: str) -> list:
    """(sample, job, profile, record) for each sample against one sample profile, the frozen judgment filled in."""
    out = []
    for sample in SAMPLES:
        job, profile = job_from(sample), profile_from(name)
        record = completed(score.score_job(job, profile, VOCABULARY, now=NOW), judged(sample, name))
        out.append((sample, job, profile, record))
    return out


def ranked(name: str) -> list:
    """The samples in match list order (score.list_key) for one sample profile."""
    order = sorted(records(name), key=lambda item: score.list_key(
        item[3]["total"]["grade"], item[3]["total"]["score"], item[3]["job_id"]))
    return [sample for sample, _, _, _ in order]


def run_cli(*args, data_dir):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", **{store.DATA_DIR_ENV: str(data_dir)})
    return subprocess.run([sys.executable, "-m", "jobsearch_cn", *args], cwd=REPO, env=env, capture_output=True)


class DocumentedSteps(unittest.TestCase):
    """The 评分工作流 steps, in order, for the tech profile and two JDs (the work log walks the same)."""

    SAMPLES = ("jd/boss_intern.txt", "jd/official_site.txt")

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name)
        shutil.copytree(FIXTURES / "profile" / "tech", self.data / "profile")
        self.ids = [self.cli("jd", "parse", str(FIXTURES / sample), "--save")["saved"][0]["id"]
                    for sample in self.SAMPLES]

    def cli(self, *args, expect=0):
        proc = run_cli(*args, data_dir=self.data)
        self.assertEqual(proc.returncode, expect, proc.stdout.decode("utf-8") + proc.stderr.decode("utf-8", "replace"))
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def draft(self, job_id: str) -> Path:
        return self.data / "matches" / "drafts" / f"{job_id}.json"

    def test_the_prerequisites_hold(self):
        self.assertTrue(self.cli("profile", "validate")["valid"])
        self.assertEqual(sorted(job["id"] for job in self.cli("jd", "list")["jobs"]), sorted(self.ids))

    def test_score_with_draft_writes_the_record_for_the_agent(self):
        job_id = self.ids[0]
        record = self.cli("match", "score", job_id, "--draft")
        data = self.draft(job_id).read_bytes()
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"), "UTF-8 without a BOM")
        self.assertEqual(json.loads(data.decode("utf-8")), record)
        self.assertEqual(self.cli("match", "list")["matches"], [], "a draft is not a saved match")
        self.assertEqual(self.cli("match", "validate", str(self.draft(job_id))), {"valid": True, "errors": []})

    def test_the_whole_workflow(self):
        for sample, job_id in zip(self.SAMPLES, self.ids):
            with self.subTest(sample=sample):
                self.cli("match", "score", job_id, "--draft")                                   # step 2
                draft = json.loads(self.draft(job_id).read_text(encoding="utf-8"))
                draft["dimensions"]["experience"].update(judged(sample, "tech"))               # step 3
                self.draft(job_id).write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
                out = self.cli("match", "validate", str(self.draft(job_id)), expect=1)        # step 4
                [error] = out["errors"]
                self.assertTrue(error.startswith("total: "), error)
                draft["total"] = json.loads(error.split("they give ", 1)[1])                   # copied, not worked out
                self.draft(job_id).write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
                self.assertEqual(self.cli("match", "validate", str(self.draft(job_id))), {"valid": True, "errors": []})
                self.assertEqual(self.cli("match", "save", str(self.draft(job_id))),           # step 5
                                 {"saved": "created", "job_id": job_id})
                shown = self.cli("match", "show", job_id)
                self.assertEqual(shown["dimensions"]["experience"]["score"], judged(sample, "tech")["score"])
        rows = [(row["job_id"], row["grade"], row["score"], row["complete"], row["stale"])            # step 6
                for row in self.cli("match", "list")["matches"]]
        self.assertEqual(rows, [(self.ids[0], "strong", 79, True, False), (self.ids[1], "moderate", 49, False, False)])
        # Scoring an unchanged job again carries the agent's work into the next draft.
        again = self.cli("match", "score", self.ids[0], "--draft")
        self.assertEqual(again["dimensions"]["experience"]["score"], 85)
        self.assertEqual(json.loads(self.draft(self.ids[0]).read_text(encoding="utf-8")), again)


# (sample, profile) -> (experience, total, grade). Rule parts as in tests/test_cn_score.py,
# experience from the frozen judgments; totals weigh skills 35, direction 30, experience 25,
# salary 10 over what is scored, rounded half up. E.g. tech boss: (35*52 + 30*100 + 25*85 +
# 10*100) / 100 = 79.45 -> 79 strong (76 before H16 read "Golang 或 Java" as one choice: skills
# 43 -> 52); ops marketing: (35*20 + 30*50 + 25*70) / 90 = 43.9 -> 44 weak.
EXPECTED = {
    ("jd/boss_intern.txt", "tech"): (85, 79, "strong"),
    ("jd/shixiseng_intern.txt", "tech"): (50, 61, "ineligible"),
    ("jd/nowcoder_campus.txt", "tech"): (80, 71, "ineligible"),
    ("jd/official_site.txt", "tech"): (45, 49, "moderate"),
    ("jd/experienced_hire.txt", "tech"): (40, 44, "ineligible"),
    ("jd-m2-3/boss_ai_product_intern.txt", "tech"): (45, 21, "poor"),
    ("jd-m2-3/shixiseng_content_ops_intern.txt", "tech"): (5, 11, "ineligible"),
    ("jd-m2-3/ats_ui_design_intern.txt", "tech"): (5, 1, "poor"),
    ("jd-m2-3/nowcoder_test_dev_intern.txt", "tech"): (60, 50, "moderate"),
    ("jd-m2-3/official_marketing_campus.txt", "tech"): (5, 1, "ineligible"),
    ("jd/boss_intern.txt", "ops"): (5, 1, "ineligible"),
    ("jd/shixiseng_intern.txt", "ops"): (20, 6, "ineligible"),
    ("jd/nowcoder_campus.txt", "ops"): (5, 1, "ineligible"),
    ("jd/official_site.txt", "ops"): (5, 1, "ineligible"),
    ("jd/experienced_hire.txt", "ops"): (5, 1, "ineligible"),
    ("jd-m2-3/boss_ai_product_intern.txt", "ops"): (20, 6, "ineligible"),
    ("jd-m2-3/shixiseng_content_ops_intern.txt", "ops"): (85, 77, "strong"),
    ("jd-m2-3/ats_ui_design_intern.txt", "ops"): (35, 15, "ineligible"),
    ("jd-m2-3/nowcoder_test_dev_intern.txt", "ops"): (5, 1, "ineligible"),
    ("jd-m2-3/official_marketing_campus.txt", "ops"): (70, 44, "weak"),
}

# match list order (score.list_key): grade, then total, then job id for ties.
RANKINGS = {
    "tech": ["jd/boss_intern.txt", "jd-m2-3/nowcoder_test_dev_intern.txt", "jd/official_site.txt",
             "jd-m2-3/boss_ai_product_intern.txt", "jd-m2-3/ats_ui_design_intern.txt", "jd/nowcoder_campus.txt",
             "jd/shixiseng_intern.txt", "jd/experienced_hire.txt", "jd-m2-3/shixiseng_content_ops_intern.txt",
             "jd-m2-3/official_marketing_campus.txt"],
    "ops": ["jd-m2-3/shixiseng_content_ops_intern.txt", "jd-m2-3/official_marketing_campus.txt",
            "jd-m2-3/ats_ui_design_intern.txt", "jd-m2-3/boss_ai_product_intern.txt", "jd/shixiseng_intern.txt",
            "jd-m2-3/nowcoder_test_dev_intern.txt", "jd/boss_intern.txt", "jd/nowcoder_campus.txt",
            "jd/experienced_hire.txt", "jd/official_site.txt"],
}


class FrozenJudgments(unittest.TestCase):
    def test_the_judgments_are_the_ones_frozen(self):
        data = JUDGMENTS.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(data).hexdigest(), FROZEN_SHA256)

    def test_one_for_each_sample_and_profile_and_only_the_agent_part(self):
        pairs = [(j["sample"], j["profile"]) for j in judgments()]
        self.assertEqual(sorted(pairs), sorted((sample, name) for sample in SAMPLES for name in ("tech", "ops")))
        self.assertEqual(sorted(EXPECTED), sorted(pairs))
        for j in judgments():
            with self.subTest(sample=j["sample"], profile=j["profile"]):
                self.assertEqual(sorted(j["experience"]), ["evidence", "reason", "score"])

    def test_each_validates_and_gives_the_expected_total(self):
        for name in ("tech", "ops"):
            for sample, job, profile, record in records(name):
                with self.subTest(sample=sample, profile=name):
                    self.assertEqual(score.validate(record, job, profile, VOCABULARY), [])
                    self.assertEqual((record["dimensions"]["experience"]["score"], record["total"]["score"],
                                      record["total"]["grade"]), EXPECTED[(sample, name)])

    def test_the_rankings(self):
        for name, expected in RANKINGS.items():
            with self.subTest(profile=name):
                self.assertEqual(ranked(name), expected)


def v5_rankings() -> dict:
    """V5's ranking for each sample profile: every job in order with its grade, and the ones it recommends."""
    return json.loads((V5 / "rankings.json").read_text(encoding="utf-8"))["profiles"]


def v5_samples() -> dict:
    """V5's job names -> the samples here (boss_backend -> jd/boss_intern.txt), as its expected files name them."""
    samples = {}
    for path in V5.glob("*.expected.json"):
        fixture = json.loads(path.read_text(encoding="utf-8"))["fixture"]
        samples[path.name.removesuffix(".expected.json")] = Path(fixture).relative_to("tests/fixtures/cn").as_posix()
    return samples


def v5_misses(order: list, human: dict, samples: dict) -> list:
    """Where a ranking (samples, best first) falls short of V5's for one profile; [] when it meets the acceptance.

    The planner's ruling on #48: with k = min(3, the number of jobs V5 recommends), at least
    min(2, k) of the first k are jobs V5 recommends, and none is a job V5 graded ineligible or poor.
    """
    recommended = {samples[row["job"]] for row in human["full_order"] if row["recommended_top_k"]}
    ruled_out = {samples[row["job"]]: row["grade"] for row in human["full_order"]
                 if row["grade"] in ("ineligible", "poor")}
    k = min(3, len(recommended))
    first = order[:k]
    misses = [("ruled out", sample, ruled_out[sample]) for sample in first if sample in ruled_out]
    hits = sum(sample in recommended for sample in first)
    if hits < min(2, k):
        misses.append(("too few recommended", hits, k))
    return misses


class V5Acceptance(unittest.TestCase):
    """The M2-4c acceptance against V5 (roadmap H19): the ranking above meets V5's recommendations.

    V5's scores are not compared one by one: the experience in each is a different agent's
    judgment, and the verifier's comparison (tests/fixtures/cn/match-m2-4/comparison.md) lists
    where they differ. The frozen judgments' digest is checked in FrozenJudgments.
    """

    def test_the_rankings_are_the_ones_frozen(self):
        data = (V5 / "rankings.json").read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(data).hexdigest(), V5_RANKINGS_SHA256)
        manifest = json.loads((V5 / "oracle-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["oracle_files_sha256"]["rankings.json"], V5_RANKINGS_SHA256)

    def test_v5_judged_these_samples_as_they_are(self):
        # Matched by content, as the verifier's comparison did: each sample is the text V5 judged.
        samples = v5_samples()
        self.assertEqual(sorted(samples.values()), sorted(SAMPLES))
        sources = json.loads((V5 / "oracle-manifest.json").read_text(encoding="utf-8"))["source_files"]
        for name, sample in samples.items():
            with self.subTest(job=name):
                data = (FIXTURES / sample).read_bytes().replace(b"\r\n", b"\n")
                self.assertEqual(hashlib.sha256(data).hexdigest(), sources[f"tests/fixtures/cn/{sample}"]["lf_sha256"])
        for name, human in v5_rankings().items():
            with self.subTest(profile=name):
                self.assertEqual(sorted(samples[row["job"]] for row in human["full_order"]), sorted(SAMPLES))
                self.assertEqual([row["job"] for row in human["full_order"] if row["recommended_top_k"]],
                                 human["recommended_top_k"])

    def test_the_first_k_meet_the_acceptance(self):
        rankings, samples = v5_rankings(), v5_samples()
        # As ruled: k is 3 for tech, and 2 for ops, for which V5 recommends only two jobs.
        self.assertEqual({name: min(3, len(human["recommended_top_k"])) for name, human in rankings.items()},
                         {"tech": 3, "ops": 2})
        for name, human in rankings.items():
            with self.subTest(profile=name):
                self.assertEqual(v5_misses(ranked(name), human, samples), [])

    def test_a_ranking_that_falls_short_fails(self):
        # The two mutations the acceptance names, made to the ranking itself.
        samples = v5_samples()
        for name, human in v5_rankings().items():
            order = ranked(name)
            recommended = [sample for sample in order if sample in {samples[job] for job in human["recommended_top_k"]}]
            ineligible = next(samples[row["job"]] for row in human["full_order"] if row["grade"] == "ineligible")
            with self.subTest(profile=name, mutation="a job V5 graded ineligible moved first"):
                moved = [ineligible] + [sample for sample in order if sample != ineligible]
                self.assertIn(("ruled out", ineligible, "ineligible"), v5_misses(moved, human, samples))
            with self.subTest(profile=name, mutation="the jobs V5 recommends pushed out of the first k"):
                pushed = [sample for sample in order if sample not in recommended] + recommended
                self.assertIn(("too few recommended", 0, min(3, len(recommended))), v5_misses(pushed, human, samples))


if __name__ == "__main__":
    unittest.main()
