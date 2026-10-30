"""Tests for jobsearch_cn/profile.py, `profile validate / show`, and the privacy guard.

The profile is the user's own data, so these pin three things: the validator
enforces docs/cn/profile.md (shared enums with job records, sources on every
fact, references that resolve), the commands keep contact details out of
ordinary output, and - because the upstream /setup writes personal data into
tracked files - that those files still hold their placeholders in this fork.
"""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "cn" / "profile.md"
FIXTURES = REPO / "tests" / "fixtures" / "cn" / "profile"

sys.path.insert(0, str(REPO))
from jobsearch_cn import profile, schema, store  # noqa: E402


def documented_example() -> dict:
    text = DOC.read_text(encoding="utf-8")
    block = re.search(r"```json\n(.*?)```", text, re.S).group(1)
    return json.loads(block)


def with_value(data: dict, path: str, value) -> dict:
    data = copy.deepcopy(data)
    target = data
    *parents, leaf = path.split(".")
    for part in parents:
        target = target[int(part)] if isinstance(target, list) else target[part]
    if isinstance(target, list):
        target[int(leaf)] = value
    else:
        target[leaf] = value
    return data


class Validate(unittest.TestCase):
    def setUp(self):
        self.example = documented_example()

    def assert_error(self, data, fragment, sources=None):
        errors = profile.validate(data, sources=sources)
        self.assertTrue(any(fragment in e for e in errors), f"{fragment!r} not in {errors}")

    def test_the_documented_example_is_valid(self):
        self.assertEqual(profile.validate(self.example, sources={"resume.pdf"}), [])

    def test_every_documented_key_is_in_the_doc(self):
        text = DOC.read_text(encoding="utf-8")
        names = set(profile.TOP_LEVEL_KEYS) | set(profile.SKILL_LEVELS) | set(profile.EXPERIENCE_TYPES)
        missing = sorted(n for n in names if n not in text)
        self.assertEqual(missing, [], "docs/cn/profile.md is out of step with jobsearch_cn/profile.py")

    def test_an_empty_profile_is_valid(self):
        empty = {
            "schema_version": 1,
            "contact": dict.fromkeys(profile.CONTACT_KEYS),
            "graduation": None,
            "education": [],
            "availability": {"start_date": None, "days_per_week": None, "months": None,
                             "cities": [], "acceptable_cities": [], "remote_ok": None, "relocate": None},
            "target": {"employment_types": [], "roles": [], "industries": [], "salary_min": None,
                       "directions": [], "weights": None},
            "skills": [], "experience": [], "awards": [], "certificates": [], "languages": [],
            "exclusions": {"cities": [], "companies": [], "keywords": []},
        }
        self.assertEqual(profile.validate(empty), [])

    def test_missing_and_unknown_keys(self):
        data = copy.deepcopy(self.example)
        del data["exclusions"]
        data["hobbies"] = []
        self.assert_error(data, "exclusions: missing")
        self.assert_error(data, "hobbies: unknown field")

    def test_enums_are_shared_with_job_records(self):
        self.assert_error(with_value(self.example, "education.0.level", "本科"), "education[0].level: must be one of")
        # A JD may say there is no minimum ("none"); a candidate always has a level.
        self.assert_error(with_value(self.example, "education.0.level", "none"), "education[0].level: must be one of")
        self.assert_error(with_value(self.example, "target.employment_types", ["实习"]), "target.employment_types[0]")
        self.assert_error(with_value(self.example, "target.salary_min.unit", "元/天"), "target.salary_min.unit")
        self.assertEqual(profile.validate(with_value(self.example, "education.0.level", "phd")), [])

    def test_ranges_and_dates(self):
        cases = {
            "availability.days_per_week": (8, "availability.days_per_week"),
            "availability.months": (0, "availability.months"),
            "graduation.year": (27, "graduation.year"),
            "graduation.month": (13, "graduation.month"),
            "availability.start_date": ("2026-11", "availability.start_date"),
            "experience.0.start": ("2026/03", "experience[0].start"),
            "awards.0.date": ("2025-13", "awards[0].date"),
        }
        for path, (value, fragment) in cases.items():
            with self.subTest(path=path):
                self.assert_error(with_value(self.example, path, value), fragment)

    def test_start_after_end(self):
        self.assert_error(with_value(self.example, "experience.0.start", "2026-09"), "experience[0]: start is after end")

    def test_every_fact_names_a_source(self):
        self.assert_error(with_value(self.example, "skills.0.source", None), "skills[0].source")
        self.assert_error(with_value(self.example, "experience.0.source", "../secret.pdf"), "not a path")
        self.assert_error(self.example, "no file 'resume.pdf' in sources/", sources={"cv.pdf"})
        self.assertEqual(profile.validate(with_value(self.example, "awards.0.source", "user"),
                                          sources={"resume.pdf"}), [])

    def test_experience_names_its_project_separately(self):
        data = copy.deepcopy(self.example)
        del data["experience"][0]["name"]
        self.assert_error(data, "experience[0].name: missing")
        self.assert_error(with_value(self.example, "experience.1.name", ""), "experience[1].name")

    def test_references_and_ids(self):
        self.assert_error(with_value(self.example, "skills.0.used_in", ["exp-9"]), "no experience with id 'exp-9'")
        data = copy.deepcopy(self.example)
        data["experience"].append(copy.deepcopy(data["experience"][0]))
        self.assert_error(data, "duplicate id 'exp-1'")
        self.assert_error(with_value(self.example, "experience.0.id", "Exp 1"), "experience[0].id")

    def test_duplicate_skills_fold_case_and_width(self):
        data = copy.deepcopy(self.example)
        data["skills"].append(dict(data["skills"][0], name="ｐｙｔｈｏｎ"))
        self.assert_error(data, f"skills[{len(data['skills']) - 1}].name: duplicate")

    def test_directions_are_vocabulary_groups(self):
        groups = {"tech", "data", "ops", "general", "game"}
        self.assertEqual(profile.validate(with_value(self.example, "target.directions", ["data", "game"]),
                                          groups=groups), [])
        errors = profile.validate(with_value(self.example, "target.directions", ["技术"]), groups=groups)
        expected = "'技术' is not a skill vocabulary group (data, game, ops, tech)"
        self.assertTrue(any(expected in e for e in errors), errors)
        self.assert_error(with_value(self.example, "target.directions", ["general"]), "not a direction")
        self.assert_error(with_value(self.example, "target.directions", ["tech", "tech"]), "duplicate")
        self.assert_error(with_value(self.example, "target.directions", None), "target.directions: must be a list")
        # Without the vocabulary (match filter checks structure only) any key passes.
        self.assertEqual(profile.validate(with_value(self.example, "target.directions", ["game"])), [])

    def test_weights_are_null_or_all_five(self):
        weights = {"skills": 40, "direction": 20, "experience": 30.5, "salary": 0, "location": 10}
        self.assertEqual(profile.validate(with_value(self.example, "target.weights", weights)), [])
        self.assert_error(with_value(self.example, "target.weights", {"skills": 100}),
                          "target.weights.direction: missing")
        # Weights written before M2-6b name four dimensions; the fifth must be added, even as 0.
        four = {key: value for key, value in weights.items() if key != "location"}
        self.assert_error(with_value(self.example, "target.weights", four), "target.weights.location: missing")
        for value in (-1, True, "35", None):
            with self.subTest(value=value):
                self.assert_error(with_value(self.example, "target.weights", dict(weights, skills=value)),
                                  "target.weights.skills: must be a number")
        self.assert_error(with_value(self.example, "target.weights", dict.fromkeys(profile.WEIGHT_KEYS, 0)),
                          "at least one weight must be above 0")
        self.assert_error(with_value(self.example, "target.weights", [35, 30, 25, 10]),
                          "target.weights: must be an object")

    def test_cities_without_an_answer_on_remote_or_moving_is_a_warning(self):
        # Valid either way; but every job outside the cities would be location unknown.
        self.assertEqual(profile.warnings(self.example), [])
        open_remote = with_value(self.example, "availability.remote_ok", None)
        self.assertEqual(profile.validate(open_remote), [])
        [warning] = profile.warnings(open_remote)
        self.assertTrue(warning.startswith("availability.remote_ok:"), warning)
        both = with_value(open_remote, "availability.relocate", None)
        self.assertEqual(len(profile.warnings(both)), 2)
        no_preferred = with_value(both, "availability.cities", [])
        self.assertEqual(len(profile.warnings(no_preferred)), 2, "acceptable cities alone ask the same question")
        self.assertEqual(profile.warnings(with_value(no_preferred, "availability.acceptable_cities", [])), [])

    def test_acceptable_cities_are_a_list_apart_from_the_preferred(self):
        # M2-6b: preferred cities stay in availability.cities; acceptable ones are the next best.
        self.assertEqual(self.example["availability"]["acceptable_cities"], ["佛山"])
        self.assert_error(with_value(self.example, "availability.acceptable_cities", None),
                          "availability.acceptable_cities: must be a list")
        self.assert_error(with_value(self.example, "availability.acceptable_cities", ["佛山", "佛山"]), "duplicate")
        self.assert_error(with_value(self.example, "availability.acceptable_cities", ["深圳"]),
                          "availability.acceptable_cities[0]: '深圳' is already a preferred city")
        older = with_value(self.example, "availability", {key: value for key, value in
                                                          self.example["availability"].items()
                                                          if key != "acceptable_cities"})
        self.assert_error(older, "availability.acceptable_cities: missing")

    def test_cities_compare_as_the_filter_and_the_score_compare_them(self):
        # Codex B on #68: the filter and the score take 深圳市 for 深圳 (match._city), so the validator does
        # too, across the two tiers either way round and within each.
        self.assert_error(with_value(self.example, "availability.acceptable_cities", ["深圳市"]),
                          "availability.acceptable_cities[0]: '深圳市' is already a preferred city")
        suffixed = with_value(self.example, "availability.cities", ["广州市", "深圳市"])
        self.assertEqual(profile.validate(suffixed), [])
        self.assert_error(with_value(suffixed, "availability.acceptable_cities", ["深圳"]),
                          "availability.acceptable_cities[0]: '深圳' is already a preferred city")
        self.assert_error(with_value(self.example, "availability.cities", ["深圳", "深圳市"]),
                          "availability.cities[1]: duplicate")
        self.assert_error(with_value(self.example, "availability.acceptable_cities", ["佛山市", "佛山"]),
                          "availability.acceptable_cities[1]: duplicate")

    def test_cities_that_are_not_a_list_are_an_error_not_a_crash(self):
        # Codex B on #68: a number here raised TypeError while comparing the two tiers.
        for key in ("cities", "acceptable_cities"):
            for value in (123, True, 1.5, "深圳"):
                with self.subTest(key=key, value=value):
                    self.assert_error(with_value(self.example, f"availability.{key}", value),
                                      f"availability.{key}: must be a list")

    def test_redaction_masks_contact_only(self):
        shown = profile.redacted(self.example)
        self.assertEqual(shown["contact"]["phone"], "***")
        self.assertIsNone(shown["contact"]["github"])
        self.assertEqual(shown["skills"], self.example["skills"])
        self.assertEqual(self.example["contact"]["name"], "张三", "redaction must not touch the original")


def run_cli(*args, data_dir):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", **{store.DATA_DIR_ENV: str(data_dir)})
    return subprocess.run([sys.executable, "-m", "jobsearch_cn", *args], cwd=REPO, env=env, capture_output=True)


class Commands(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name)
        self.root = self.data / "profile"
        (self.root / "sources").mkdir(parents=True)
        (self.root / "sources" / "resume.pdf").write_bytes(b"%PDF-1.4 sample")
        (self.root / "notes.md").write_text("# 自我介绍\n", encoding="utf-8")
        self.write(documented_example())

    def write(self, data):
        (self.root / "profile.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_validate_a_complete_profile(self):
        proc = run_cli("profile", "validate", data_dir=self.data)
        self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8"))
        self.assertEqual(json.loads(proc.stdout), {"valid": True, "errors": [], "warnings": []})

    def test_a_source_file_that_is_not_there_fails(self):
        (self.root / "sources" / "resume.pdf").unlink()
        proc = run_cli("profile", "validate", data_dir=self.data)
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(any("resume.pdf" in e for e in json.loads(proc.stdout)["errors"]))

    def test_missing_notes_is_a_warning_and_gbk_notes_an_error(self):
        (self.root / "notes.md").unlink()
        out = json.loads(run_cli("profile", "validate", data_dir=self.data).stdout)
        self.assertTrue(out["valid"])
        self.assertEqual(len(out["warnings"]), 1)
        (self.root / "notes.md").write_bytes("自我介绍".encode("gbk"))
        self.assertEqual(run_cli("profile", "validate", data_dir=self.data).returncode, 1)

    def test_no_profile_is_an_input_error_pointing_at_cn_setup(self):
        (self.root / "profile.json").unlink()
        proc = run_cli("profile", "validate", data_dir=self.data)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("profile-setup.md", proc.stderr.decode("utf-8"))

    def test_show_hides_contact_unless_asked(self):
        hidden = run_cli("profile", "show", data_dir=self.data).stdout.decode("utf-8")
        self.assertNotIn("13800000000", hidden)
        self.assertNotIn("a@example.com", hidden)
        self.assertIn("13800000000", run_cli("profile", "show", "--contact", data_dir=self.data).stdout.decode("utf-8"))

    def test_an_explicit_file(self):
        other = self.data / "draft.json"
        other.write_text(json.dumps(documented_example(), ensure_ascii=False), encoding="utf-8")
        proc = run_cli("profile", "validate", str(other), data_dir=self.data)
        self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8"))

    def test_validate_warns_of_cities_without_an_answer_on_moving(self):
        self.write(with_value(documented_example(), "availability.relocate", None))
        out = json.loads(run_cli("profile", "validate", data_dir=self.data).stdout)
        self.assertTrue(out["valid"])
        self.assertTrue(any(w.startswith("availability.relocate:") for w in out["warnings"]), out["warnings"])

    def test_cities_that_are_not_a_list_are_reported_as_json(self):
        # Codex B on #68: profile validate crashed here, with nothing on stdout.
        for key in ("cities", "acceptable_cities"):
            for value in (123, True):
                with self.subTest(key=key, value=value):
                    self.write(with_value(documented_example(), f"availability.{key}", value))
                    proc = run_cli("profile", "validate", data_dir=self.data)
                    self.assertEqual(proc.returncode, 1, proc.stderr.decode("utf-8", "replace"))
                    out = json.loads(proc.stdout)
                    self.assertFalse(out["valid"])
                    self.assertIn(f"availability.{key}: must be a list ([] when there is nothing)", out["errors"])

    def test_directions_are_checked_against_the_data_dir_vocabulary(self):
        self.write(with_value(documented_example(), "target.directions", ["game"]))
        proc = run_cli("profile", "validate", data_dir=self.data)
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(any("'game' is not a skill vocabulary group" in e for e in json.loads(proc.stdout)["errors"]))
        (self.data / "config").mkdir()
        vocabulary = self.data / "config" / "skills.json"
        vocabulary.write_text(json.dumps({"version": 1, "groups": {"game": {"label": "游戏", "terms": ["Unity"]}}}),
                              encoding="utf-8")
        proc = run_cli("profile", "validate", data_dir=self.data)
        self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8"))
        vocabulary.write_text("{oops", encoding="utf-8")
        proc = run_cli("profile", "validate", data_dir=self.data)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("skills.json", proc.stderr.decode("utf-8"))


class Fixtures(unittest.TestCase):
    """The sample profiles later matching tests use: one technical, one not."""

    def test_there_is_a_technical_and_a_non_technical_profile(self):
        self.assertEqual(sorted(p.name for p in FIXTURES.iterdir() if p.is_dir()), ["ops", "tech"])

    def test_each_states_its_direction_and_keeps_the_default_weights(self):
        for name in ("tech", "ops"):
            data = json.loads((FIXTURES / name / "profile.json").read_text(encoding="utf-8"))
            with self.subTest(profile=name):
                self.assertEqual(data["target"]["directions"], [name])
                self.assertIsNone(data["target"]["weights"])

    def test_each_passes_profile_validate(self):
        for directory in sorted(FIXTURES.iterdir()):
            with self.subTest(profile=directory.name), tempfile.TemporaryDirectory() as tmp:
                shutil.copytree(directory, Path(tmp) / "profile")
                proc = run_cli("profile", "validate", data_dir=tmp)
                self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8"))
                self.assertEqual(json.loads(proc.stdout)["warnings"], [])

    def test_they_follow_the_filling_conventions(self):
        # docs/cn/profile.md, "填写约定": a project's name lives in name, never
        # in org or role; a skill without a level (seen only in an experience)
        # points at that experience.
        for directory in sorted(FIXTURES.iterdir()):
            data = json.loads((directory / "profile.json").read_text(encoding="utf-8"))
            with self.subTest(profile=directory.name):
                for item in data["experience"]:
                    if item["type"] in ("project", "competition", "research"):
                        self.assertTrue(item["name"], item["id"])
                    self.assertNotIn(item["role"], ("个人项目", "项目", "课程项目"), item["id"])
                for skill in data["skills"]:
                    if skill["level"] is None:
                        self.assertTrue(skill["used_in"], skill["name"])

    def test_contact_details_are_obviously_fake(self):
        for directory in sorted(FIXTURES.iterdir()):
            contact = json.loads((directory / "profile.json").read_text(encoding="utf-8"))["contact"]
            with self.subTest(profile=directory.name):
                self.assertEqual(contact["phone"], "13800000000")
                self.assertTrue(contact["email"].endswith("@example.com"), contact["email"])

    def test_profile_show_hides_their_contact_details(self):
        for directory in sorted(FIXTURES.iterdir()):
            contact = json.loads((directory / "profile.json").read_text(encoding="utf-8"))["contact"]
            with self.subTest(profile=directory.name), tempfile.TemporaryDirectory() as tmp:
                shutil.copytree(directory, Path(tmp) / "profile")
                shown = run_cli("profile", "show", data_dir=tmp).stdout.decode("utf-8")
                for value in contact.values():
                    if value is not None:
                        self.assertNotIn(value, shown)
                self.assertIn(contact["phone"], run_cli("profile", "show", "--contact", data_dir=tmp)
                              .stdout.decode("utf-8"))

    def test_every_fact_from_the_resume_is_in_the_resume(self):
        # The fixtures model the cn-setup rule: nothing beyond the source.
        for directory in sorted(FIXTURES.iterdir()):
            data = json.loads((directory / "profile.json").read_text(encoding="utf-8"))
            resume = schema.normalize_for_match((directory / "sources" / "resume.txt").read_text(encoding="utf-8"))
            facts = []
            for item in data["experience"]:
                facts += [(item["source"], bullet) for bullet in item["bullets"]]
                facts += [(item["source"], item[key]) for key in ("name", "org", "role") if item[key]]
            for key, field in (("skills", "name"), ("education", "school"), ("awards", "name"),
                               ("certificates", "name")):
                facts += [(item["source"], item[field]) for item in data[key]]
            for source, fact in facts:
                if source == "resume.txt":
                    with self.subTest(profile=directory.name, fact=fact):
                        self.assertIn(schema.normalize_for_match(fact), resume)


# The sentinels upstream CI checks (ci.yml "Placeholder integrity"). Upstream
# runs that job only on its own repository, so a fork that ran /setup and
# committed would never be told. This fork keeps the templates pristine
# (ADR-6): personal data lives in data/profile/.
TEMPLATE_SENTINELS = {
    "CLAUDE.md": "[YOUR_NAME]",
    "cv/main_example.tex": "\\name{[First]}{[Last]}",
    "cover_letters/cover_example.tex": "[YOUR NAME]",
    ".claude/skills/job-application-assistant/01-candidate-profile.md": "[YOUR_EMAIL]",
    ".claude/skills/job-application-assistant/04-job-evaluation.md": "[YOUR_PRIMARY_SKILLS]",
}


class Privacy(unittest.TestCase):
    def test_upstream_profile_templates_keep_their_placeholders(self):
        for rel, sentinel in TEMPLATE_SENTINELS.items():
            with self.subTest(file=rel):
                self.assertIn(sentinel, (REPO / rel).read_text(encoding="utf-8"),
                              f"{rel} lost its placeholder: was the upstream /setup run? Use cn-setup instead.")

    def test_profile_data_is_gitignored(self):
        proc = subprocess.run(["git", "check-ignore", "-q", "data/profile/profile.json"], cwd=REPO)
        self.assertEqual(proc.returncode, 0, "data/profile/ must be ignored by git")

    def test_the_default_profile_location_is_under_data(self):
        self.assertEqual(store.DEFAULT_DATA_DIR / "profile", REPO / "data" / "profile")
        self.assertEqual(profile.SKILL_LEVELS, ("familiar", "working", "proficient", "expert"))
        self.assertTrue(set(schema.EDUCATION_LEVELS) >= {"bachelor", "master"})


if __name__ == "__main__":
    unittest.main()
