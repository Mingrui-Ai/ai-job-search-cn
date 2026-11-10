"""Tests for jobsearch_cn/review.py and the `review` commands (M3-3 part 2).

A review is the reviewer agent's verdict on one version of one material. These pin: a well-formed review
passes; each finding names a checklist item and a place that exists in the material; a pass carries no
'must' finding; a review of an older version of the material, or of another job's material, fails; at
most two rounds; a self-review passes with a warning. The machine draft sorts the JD's skills into covered
in the JD's wording, covered by another spelling, and gaps; the style rules are warnings only. The
commands find the material next to the review, render Markdown, and exit 0, 1 or 2.
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
SAMPLE = REPO / "tests" / "fixtures" / "cn" / "material" / "tech-m3"

sys.path.insert(0, str(REPO))
from jobsearch_cn import cli, review, score, store, vocab  # noqa: E402

VOCABULARY = vocab.load()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


PROFILE = load(SAMPLE / "profile" / "profile.json")
MATERIAL = load(SAMPLE / "resume-1.json")
JOB = {"requirements": {"skills": ["Golang", "Python", "Docker", "Rust", "langchain"]}}


def docker_only_in_exp1() -> tuple[dict, dict]:
    """The sample with Docker out of the skills list and named only in exp-1's own text."""
    profile = copy.deepcopy(PROFILE)
    profile["skills"] = [skill for skill in profile["skills"] if skill["name"] != "Docker"]
    exp1 = next(entry for entry in profile["experience"] if entry["id"] == "exp-1")
    exp1["bullets"].append("使用 Docker 部署服务")
    material = copy.deepcopy(MATERIAL)
    material["profile_hash"] = score.profile_hash(profile)
    return profile, material


def make_review(**changes) -> dict:
    data = {
        "schema_version": 1, "kind": "resume-review", "job_id": MATERIAL["job_id"],
        "material": "resume-1.json", "material_hash": review.material_hash(MATERIAL),
        "round": 1, "mode": "independent", "created": "2026-11-01T12:00:00+08:00", "verdict": "revise",
        "findings": [{"item": "B1", "path": "experience[0].bullets[1].text", "severity": "must",
                      "reason": "原文是参与，这里写成了负责", "suggestion": None}],
        "coverage": [{"requirement": "Docker", "status": "gap", "where": [], "note": "档案里有，材料没写"},
                     {"requirement": "Python", "status": "covered", "where": ["skills[0]"], "note": None}],
    }
    data.update(changes)
    return data


def errors_of(data, material=MATERIAL) -> list:
    return review.validate(data, material)[0]


class Validate(unittest.TestCase):
    def test_a_well_formed_review_is_valid(self):
        self.assertEqual(review.validate(make_review(), MATERIAL), ([], []))

    def test_a_pass_has_no_must_finding(self):
        self.assertIn("verdict: 'pass' with 1 'must' finding(s); a pass has none",
                      errors_of(make_review(verdict="pass")))
        suggestion = make_review(verdict="pass")
        suggestion["findings"][0]["severity"] = "suggest"
        self.assertEqual(errors_of(suggestion), [])

    def test_revise_without_a_must_finding_warns(self):
        data = make_review(findings=[])
        self.assertEqual(review.validate(data, MATERIAL)[1],
                         ["verdict: 'revise' without a 'must' finding; is it a pass with suggestions?"])

    def test_a_self_review_passes_with_a_warning(self):
        errors, warnings = review.validate(make_review(mode="self"), MATERIAL)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("self-review", warnings[0])
        self.assertIn("mode: must be one of", errors_of(make_review(mode="peer"))[0])

    def test_findings_name_a_checklist_item_and_a_real_place(self):
        data = make_review()
        data["findings"][0].update(item="H1", path="experience[5].bullets[0]", severity="meh", reason=" ")
        self.assertEqual(errors_of(data), [
            "findings[0].item: 'H1' is not a checklist item (A1-G8)",
            "findings[0].path: 'experience[5].bullets[0]' is not a place in the material",
            "findings[0].severity: must be one of must, suggest",
            "findings[0].reason: must be a non-empty string",
        ])

    def test_a_review_of_a_message(self):
        # M3-6: kind follows the material, the paths are segments[i].text and subject.text, coverage is [].
        email = load(SAMPLE / "email-1.json")
        data = make_review(kind="email-review", material="email-1.json", material_hash=review.material_hash(email),
                           coverage=[], findings=[
                               {"item": "G3", "path": "segments[1].text", "severity": "must",
                                "reason": "提到附件，但还没有审核通过的简历", "suggestion": None},
                               {"item": "E1", "path": "subject.text", "severity": "suggest",
                                "reason": "标题用了半角标点", "suggestion": None}])
        self.assertEqual(errors_of(data, email), [])
        self.assertEqual(errors_of({**data, "kind": "resume-review"}, email),
                         ["kind: 'resume-review' does not fit a email material; use 'email-review'"])
        self.assertEqual(errors_of(make_review(kind="greeting-review"))[0],
                         "kind: 'greeting-review' does not fit a resume material; use 'resume-review'")
        self.assertEqual(errors_of({**data, "coverage": make_review()["coverage"]}, email),
                         ["coverage: a greeting, email or referral has no coverage table; write []"])
        data["findings"][0]["path"] = "segments[99].text"
        self.assertEqual(errors_of(data, email),
                         ["findings[0].path: 'segments[99].text' is not a place in the material"])

    def test_a_finding_about_the_whole_material_has_no_path(self):
        data = make_review()
        data["findings"][0].update(item="D1", path=None)
        self.assertEqual(errors_of(data), [])

    def test_the_checklist_items(self):
        self.assertEqual(len(review.ITEMS), 41)
        self.assertEqual((review.ITEMS[0], review.ITEMS[-1]), ("A1", "G8"))
        self.assertNotIn("A6", review.ITEMS)

    def test_paths(self):
        for path in ("summary", "summary.text", "skills[2]", "experience[1].bullets[0].text", "education[0].courses[1]"):
            self.assertTrue(review.resolve(MATERIAL, path), path)
        for path in ("", "nope", "skills[99]", "experience.bullets", "[0]", "skills[0].x", "skills[-1]",
                     "experience[0]bullets", "summary..text"):
            self.assertFalse(review.resolve(MATERIAL, path), path)
        self.assertTrue(review.resolve(MATERIAL, "skills[002]"))  # leading zeros read as before

    def test_a_very_long_index_is_a_place_that_does_not_exist(self):
        # #112 P3-3: int() refuses digit strings this long; the check must not raise.
        huge = "skills[" + "9" * 5000 + "]"
        self.assertFalse(review.resolve(MATERIAL, huge))
        self.assertFalse(review.resolve(MATERIAL, "skills[" + "0" * 4999 + "9]"))
        data = make_review()
        data["findings"][0]["path"] = huge
        [error] = errors_of(data)
        self.assertTrue(error.startswith("findings[0].path: 'skills[999"), error)
        self.assertTrue(error.endswith("…' is not a place in the material"), error)
        self.assertLess(len(error), 200)

    def test_only_ascii_digits_are_an_index(self):
        # int() reads full-width, Arabic-Indic and other Unicode digits; a path names a place by ASCII only.
        self.assertTrue(review.resolve(MATERIAL, "skills[1]"))
        for path in ("skills[１]", "skills[١]", "skills[۱]", "skills[१]", "experience[０].bullets[0].text",
                     "experience[0].bullets[０].text"):
            self.assertFalse(review.resolve(MATERIAL, path), path)
        data = make_review()
        data["findings"][0]["path"] = "skills[１]"
        self.assertEqual(errors_of(data), ["findings[0].path: 'skills[１]' is not a place in the material"])

    def test_a_review_of_an_older_material_fails(self):
        changed = copy.deepcopy(MATERIAL)
        changed["skills"].pop()
        self.assertEqual(errors_of(make_review(), changed),
                         ["material_hash: the material has changed since this review; review the current version"])

    def test_a_review_of_another_jobs_material_fails(self):
        self.assertIn("job_id: 'job_000000000002' is not the material's job",
                      errors_of(make_review(job_id="job_000000000002"))[0])

    def test_at_most_two_rounds(self):
        self.assertEqual(errors_of(make_review(round=2)), [])
        for value in (0, 3, True, "1"):
            self.assertEqual(errors_of(make_review(round=value)), ["round: must be 1 or 2 (at most 2 rounds)"])

    def test_coverage_rows(self):
        data = make_review(coverage=[
            {"requirement": "Docker", "status": "gap", "where": ["skills[0]"], "note": None},
            {"requirement": "Python", "status": "covered", "where": [], "note": None},
            {"requirement": "Go", "status": "maybe", "where": ["skills[9]"], "note": ""},
        ])
        self.assertEqual(errors_of(data), [
            "coverage[0].where: a gap has no place in the material",
            "coverage[1].where: say where the material covers it",
            "coverage[2].status: must be one of covered, synonym, gap",
            "coverage[2].note: must be a non-empty string or null",
            "coverage[2].where[0]: 'skills[9]' is not a place in the material",
        ])

    def test_fields_are_all_required_and_nothing_extra(self):
        data = make_review(extra=1)
        del data["coverage"]
        errors = errors_of(data)
        self.assertTrue(any("coverage" in e for e in errors), errors)
        self.assertTrue(any("extra" in e for e in errors), errors)
        self.assertEqual(errors_of([]), ["review: must be a JSON object"])
        self.assertIn("material: must be a non-empty string", errors_of(make_review(material=None)))


class Draft(unittest.TestCase):
    def test_coverage_sorts_the_jds_skills(self):
        rows = {row["requirement"]: row for row in review.coverage(MATERIAL, PROFILE, JOB, VOCABULARY)}
        self.assertEqual(list(rows), JOB["requirements"]["skills"])
        self.assertEqual(rows["Python"]["status"], "covered")
        self.assertEqual(rows["Python"]["where"][0], "skills[0]")
        self.assertEqual(rows["langchain"]["status"], "covered")  # case alone is E2's business
        self.assertEqual(rows["Golang"]["status"], "synonym")
        self.assertIn("材料写作 Go，JD 写作 Golang", rows["Golang"]["note"])
        self.assertEqual(rows["Docker"], {"requirement": "Docker", "status": "gap", "where": [],
                                          "note": "档案里有，材料没写"})
        self.assertEqual(rows["Rust"]["note"], "技能列表未列，需核对经历原文")

    def test_a_skill_only_in_a_cited_entrys_text_is_not_called_missing(self):
        # Codex B on #112: the material may rest a skill on an experience's own text alone.
        profile, material = docker_only_in_exp1()
        rows = {row["requirement"]: row for row in review.coverage(material, profile, JOB, VOCABULARY)}
        self.assertEqual(rows["Docker"], {"requirement": "Docker", "status": "gap", "where": [],
                                          "note": "技能列表未列，所引条目原文里有，材料没写"})

    def test_a_skill_only_in_an_entry_the_material_leaves_out_is_left_to_the_reviewer(self):
        profile, material = docker_only_in_exp1()
        material["experience"] = [item for item in material["experience"] if item["ref"] != "exp-1"]
        material["summary"]["refs"] = [ref for ref in material["summary"]["refs"] if ref != "exp-1"]
        self.assertNotIn("exp-1", json.dumps(material))
        rows = {row["requirement"]: row for row in review.coverage(material, profile, JOB, VOCABULARY)}
        self.assertEqual(rows["Docker"]["note"], "技能列表未列，需核对经历原文")

    def test_draft_coverage_is_a_valid_review_coverage(self):
        data = make_review(coverage=review.coverage(MATERIAL, PROFILE, JOB, VOCABULARY))
        self.assertEqual(errors_of(data), [])

    def test_no_stored_job_means_no_rows(self):
        self.assertEqual(review.coverage(MATERIAL, PROFILE, None, VOCABULARY), [])

    def test_a_skill_the_jd_lists_twice_is_one_row(self):
        job = {"requirements": {"skills": ["Go", "Golang"]}}
        self.assertEqual(len(review.coverage(MATERIAL, PROFILE, job, VOCABULARY)), 1)

    def test_a_choice_of_skills_is_one_row_covered_by_any_of_them(self):
        # The M3-3c dry run: "熟悉 Golang 或 Java" with Go written; Java is no gap.
        job = {"requirements": {"skills": ["Go", "MySQL", "Golang", "Java"], "skill_alternatives": [["Golang", "Java"]]}}
        rows = review.coverage(MATERIAL, PROFILE, job, VOCABULARY)
        self.assertEqual([row["requirement"] for row in rows], ["Golang 或 Java", "MySQL"])
        self.assertEqual(rows[0]["status"], "covered")  # the JD also writes Go, so Go is its wording
        self.assertIn("skills[1]", rows[0]["where"])

    def test_a_choice_written_another_way_is_a_synonym(self):
        job = {"requirements": {"skills": ["Golang", "Java"], "skill_alternatives": [["Golang", "Java"]]}}
        [row] = review.coverage(MATERIAL, PROFILE, job, VOCABULARY)
        self.assertEqual((row["requirement"], row["status"]), ("Golang 或 Java", "synonym"))
        self.assertIn("材料写作 Go，JD 写作 Golang", row["note"])

    def test_a_choice_none_of_which_is_written_is_one_gap(self):
        job = {"requirements": {"skills": ["Rust", "Docker", "Java"], "skill_alternatives": [["Rust", "Docker", "Java"]]}}
        self.assertEqual(review.coverage(MATERIAL, PROFILE, job, VOCABULARY),
                         [{"requirement": "Rust 或 Docker 或 Java", "status": "gap", "where": [],
                           "note": "Docker：档案里有，材料没写"}])
        job = {"requirements": {"skills": ["Rust", "Java"], "skill_alternatives": [["Rust", "Java"]]}}
        self.assertEqual(review.coverage(MATERIAL, PROFILE, job, VOCABULARY)[0]["note"], "技能列表未列，需核对经历原文")

    def test_without_choices_the_rows_are_unchanged(self):
        job = dict(JOB, requirements=dict(JOB["requirements"], skill_alternatives=[]))
        self.assertEqual(review.coverage(MATERIAL, PROFILE, job, VOCABULARY),
                         review.coverage(MATERIAL, PROFILE, JOB, VOCABULARY))
        self.assertEqual([row["requirement"] for row in review.coverage(MATERIAL, PROFILE, JOB, VOCABULARY)],
                         JOB["requirements"]["skills"])

    def test_style_warnings(self):
        data = copy.deepcopy(MATERIAL)
        data["summary"]["text"] = "后端开发实习一段。"
        data["experience"][0]["bullets"] = [
            {"text": "用Go重构订单查询接口。", "refs": ["exp-1"]},
            {"text": "接口重构,延迟下降", "refs": ["exp-1"]},
            {"text": "用 Go 重构订单查询接口", "refs": ["exp-1"]},
        ]
        data["experience"][1]["bullets"] = [{"text": "用Python写评测脚本", "refs": ["proj-1"]}]
        self.assertEqual(review.style(data), [
            "experience[0].bullets[0].text: E1 ends with a full stop; bullets end without one",
            "experience[0].bullets[1].text: E1 use full-width punctuation (，；：) in Chinese text",
            "experience[0].bullets[2].text: E3 no space between Chinese and English or numbers",
        ])


class Markdown(unittest.TestCase):
    def test_the_markdown_shows_the_verdict_findings_and_coverage(self):
        data = make_review(mode="self")
        data["findings"].insert(0, {"item": "E4", "path": None, "severity": "suggest",
                                    "reason": "要点用动词开头", "suggestion": "实现……"})
        text = review.markdown(data)
        self.assertIn("- 结论：需修改", text)
        self.assertIn("自审", text)
        self.assertLess(text.index("**必改** B1"), text.index("**建议** E4"))
        self.assertIn("  - 建议改成：实现……", text)
        self.assertIn("| Docker | 缺口 | - | 档案里有，材料没写 |", text)

    def test_the_markdown_of_a_message_review_says_it_has_no_coverage(self):
        text = review.markdown(make_review(kind="greeting-review", coverage=[]))
        self.assertIn("沟通草稿没有覆盖表。", text)
        self.assertNotIn("没有列出。", text)
        self.assertIn("没有列出。", review.markdown(make_review(coverage=[])))

    def test_a_line_break_in_any_free_text_keeps_the_structure(self):
        # Planner on the #112 P3 PR: findings, the heading and the summary lines too, not just the table.
        data = make_review()
        data["findings"] = [{"item": "B1", "path": None, "severity": "must",
                             "reason": "第一行\n- 不是新的一项\n# 不是标题", "suggestion": "甲\r\n乙"},
                            {"item": "E4", "path": None, "severity": "suggest", "reason": "一行", "suggestion": None}]
        data.update(material="resume-1.json\n# 假标题", job_id="job_1\n- 假的一行")
        lines = review.markdown(data).splitlines()
        self.assertEqual([line for line in lines if line.startswith("#")],
                         ["# 审核结果：resume-1.json<br># 假标题（第 1 轮）", "## 问题", "## 岗位要求覆盖"])
        self.assertIn("- 岗位：job_1<br>- 假的一行", lines)
        self.assertIn("- **必改** B1：第一行<br>- 不是新的一项<br># 不是标题", lines)
        self.assertIn("  - 建议改成：甲<br>乙", lines)
        self.assertEqual(sum(line.startswith("- **") for line in lines), 2)

    def test_a_pipe_or_line_break_in_a_cell_keeps_the_table_whole(self):
        # #112 P3-2: legal text must not add columns or break a row.
        data = make_review()
        data["coverage"] = [{"requirement": "检索 | 排序", "status": "gap", "where": [], "note": "第一行\n第二行\r\n第三行"},
                            {"requirement": "C:\\tools\\|x", "status": "gap", "where": [], "note": None}]
        self.assertEqual(errors_of(data), [])
        rows = [line for line in review.markdown(data).splitlines() if line.startswith("|")]
        self.assertEqual(len(rows), 4)  # header, rule, two rows
        for line in rows:
            self.assertEqual(re.sub(r"\\.", "", line).count("|"), 5, line)  # four cells
        self.assertEqual(rows[2], "| 检索 \\| 排序 | 缺口 | - | 第一行<br>第二行<br>第三行 |")
        self.assertEqual(rows[3], "| C:\\\\tools\\\\\\|x | 缺口 | - | - |")

    def test_both_free_text_cells_are_handled_alike(self):
        # #112 P3-2 the other way round: line breaks in the requirement, a pipe and a backslash in the note.
        data = make_review()
        data["coverage"] = [{"requirement": "检索\r排序\n推荐", "status": "gap", "where": [],
                             "note": "要 A | B，见 C:\\docs\\|y"}]
        self.assertEqual(errors_of(data), [])
        rows = [line for line in review.markdown(data).splitlines() if line.startswith("|")]
        self.assertEqual(len(rows), 3)  # header, rule, one row
        self.assertEqual(re.sub(r"\\.", "", rows[2]).count("|"), 5, rows[2])  # four cells
        self.assertEqual(rows[2], "| 检索<br>排序<br>推荐 | 缺口 | - | 要 A \\| B，见 C:\\\\docs\\\\\\|y |")


def run_cli(*args, data_dir):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", **{store.DATA_DIR_ENV: str(data_dir)})
    return subprocess.run([sys.executable, "-m", "jobsearch_cn", *args], cwd=REPO, env=env, capture_output=True)


class Command(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name)
        shutil.copytree(SAMPLE / "profile", self.data / "profile")
        self.folder = self.data / "materials" / MATERIAL["job_id"]
        self.folder.mkdir(parents=True)
        self.material = self.folder / "resume-1.json"
        self.material.write_text(json.dumps(MATERIAL, ensure_ascii=False), encoding="utf-8")
        self.review = self.folder / "review-1-r1.json"
        outputs = self.data / "resumes" / MATERIAL["job_id"]
        outputs.mkdir(parents=True)
        files = [outputs / f"resume-1.{ext}" for ext in ("pdf", "docx")]
        for path in files:
            path.write_bytes(b"Synthetic review fixture: " + path.suffix.encode())
        cli._write_build_note(outputs, "resume-1", MATERIAL, PROFILE, files)

    def write_review(self, data) -> None:
        self.review.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False),
                               encoding="utf-8")

    def test_draft_reads_the_stored_job(self):
        jobs = self.data / "jobs"
        jobs.mkdir()
        (jobs / f"{MATERIAL['job_id']}.json").write_text(json.dumps(JOB), encoding="utf-8")
        proc = run_cli("review", "draft", str(self.material), data_dir=self.data)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8"))
        result = json.loads(proc.stdout)
        self.assertEqual(result["material_hash"], review.material_hash(MATERIAL))
        self.assertTrue(result["job_found"])
        self.assertEqual([row["status"] for row in result["coverage"]],
                         ["synonym", "covered", "gap", "gap", "covered"])
        self.assertEqual(len(result["style"]), 4)  # the sample spaces Chinese from English

    def test_draft_of_a_skill_only_in_an_experiences_text(self):
        # The repro from Codex B's review of #112, through the command.
        profile, material = docker_only_in_exp1()
        (self.data / "profile" / "profile.json").write_text(json.dumps(profile, ensure_ascii=False),
                                                            encoding="utf-8")
        self.material.write_text(json.dumps(material, ensure_ascii=False), encoding="utf-8")
        jobs = self.data / "jobs"
        jobs.mkdir()
        (jobs / f"{MATERIAL['job_id']}.json").write_text(json.dumps(JOB), encoding="utf-8")
        proc = run_cli("review", "draft", str(self.material), data_dir=self.data)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8"))
        rows = {row["requirement"]: row for row in json.loads(proc.stdout)["coverage"]}
        self.assertEqual((rows["Docker"]["status"], rows["Docker"]["note"]),
                         ("gap", "技能列表未列，所引条目原文里有，材料没写"))

    def test_draft_without_a_stored_job_and_of_an_invalid_material(self):
        result = json.loads(run_cli("review", "draft", str(self.material), data_dir=self.data).stdout)
        self.assertEqual((result["job_found"], result["coverage"]), (False, []))
        broken = copy.deepcopy(MATERIAL)
        broken["skills"].append("Rust")
        self.material.write_text(json.dumps(broken), encoding="utf-8")
        self.assertEqual(run_cli("review", "draft", str(self.material), data_dir=self.data).returncode, 1)

    def test_draft_gives_no_warnings_of_the_material_check(self):
        # #132 P3-1: review draft runs material validate's check only for its errors. A changed profile is
        # warned of by material validate, which the reviewer runs too, and review draft prints none of it.
        self.material.write_text(json.dumps({**MATERIAL, "profile_hash": "0" * 64}, ensure_ascii=False),
                                 encoding="utf-8")
        checked = run_cli("material", "validate", str(self.material), data_dir=self.data)
        self.assertEqual(checked.returncode, 0, checked.stderr.decode("utf-8"))
        self.assertTrue(any(warning.startswith("profile_hash: ") for warning in json.loads(checked.stdout)["warnings"]))
        proc = run_cli("review", "draft", str(self.material), data_dir=self.data)
        self.assertEqual((proc.returncode, proc.stderr), (0, b""))
        self.assertEqual(list(json.loads(proc.stdout)), ["material_hash", "job_found", "coverage", "style"])
        self.assertNotIn(b"profile_hash", proc.stdout)

    def test_validate_finds_the_material_next_to_the_review(self):
        self.write_review(make_review())
        proc = run_cli("review", "validate", str(self.review), data_dir=self.data)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8"))
        self.assertEqual(json.loads(proc.stdout), {"valid": True, "errors": [], "warnings": []})

    def test_the_material_field_is_only_a_file_name(self):
        elsewhere = self.data / "other.json"
        changed = copy.deepcopy(MATERIAL)
        changed["skills"].pop()
        elsewhere.write_text(json.dumps(changed), encoding="utf-8")
        self.write_review(make_review(material="../../other.json"))
        # A declared path is rejected without reading it, including with an explicit material override.
        self.assertEqual(run_cli("review", "validate", str(self.review), data_dir=self.data).returncode, 1)
        proc = run_cli("review", "validate", str(self.review), "--material", str(elsewhere), data_dir=self.data)
        self.assertEqual(proc.returncode, 1)

    def test_show_renders_markdown_or_lists_errors(self):
        self.write_review(make_review())
        proc = run_cli("review", "show", str(self.review), data_dir=self.data)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8"))
        self.assertTrue(proc.stdout.decode("utf-8").startswith("# 审核结果：resume-1.json（第 1 轮）"))
        self.write_review(make_review(verdict="pass"))
        proc = run_cli("review", "show", str(self.review), data_dir=self.data)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(json.loads(proc.stdout)["valid"])

    def test_validate_reports_a_very_long_index_as_json(self):
        data = make_review()
        data["findings"][0]["path"] = "skills[" + "9" * 5000 + "]"
        self.write_review(data)
        proc = run_cli("review", "validate", str(self.review), data_dir=self.data)
        self.assertEqual(proc.returncode, 1, proc.stderr.decode("utf-8"))
        self.assertEqual(proc.stderr, b"")
        self.assertFalse(json.loads(proc.stdout)["valid"])

    def test_unreadable_input_exits_2(self):
        self.write_review("{not json")
        self.assertEqual(run_cli("review", "validate", str(self.review), data_dir=self.data).returncode, 2)
        self.assertEqual(run_cli("review", "validate", str(self.folder / "absent.json"),
                                 data_dir=self.data).returncode, 2)


if __name__ == "__main__":
    unittest.main()
