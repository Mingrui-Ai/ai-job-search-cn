"""material.render and `resume build` (M3-2, second part): from a checked material to the PDF and Word files.

render takes the names, schools, dates and contact details from the cited profile entries and lays them
out as the flat content resume_pdf and resume_docx print (resume_templates/sample.json). These pin each
layout rule the planner ruled on (worklog 2026-11-01-m3-2b-word.md), that every input is a valid profile and
material, and that the command checks the material before it writes anything, writes only inside the data
directory, never through a link, and fails when either file does not hold the content. A summary (M3-2c) is
the first section and changes nothing else; with none the content is what 201475a gave. material validate,
resume build and review draft read the same notes.md. The real build, with
Typst, is in test_cn_resume_pdf.RealRender, the class CI's real-render job runs.
"""
import copy
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from jobsearch_cn import cli, material, profile, resume_docx, resume_pdf, review, vocab  # noqa: E402
from tests.test_cn_resume_pdf import faked_typst, pdf_with_pages  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "cn" / "material" / "tech-m3"
VOCABULARY = vocab.load()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


PROFILE = load(FIXTURE / "profile" / "profile.json")
MATERIAL = load(FIXTURE / "resume-1.json")


def rendered(material_record: dict, profile_record: dict = PROFILE) -> dict:
    """render, after checking both inputs are what it is promised: a valid profile and material."""
    assert profile.validate(profile_record) == [], profile.validate(profile_record)
    errors, _ = material.validate(material_record, profile_record, VOCABULARY)
    assert errors == [], errors
    return material.render(material_record, profile_record, VOCABULARY)


def section(content: dict, title: str) -> dict:
    return next(item for item in content["sections"] if item["title"] == title)


def entry(**fields) -> dict:
    base = {"id": "exp-9", "type": "project", "name": None, "org": None, "role": None, "start": None, "end": None,
            "bullets": [], "source": "resume.txt"}
    return {**base, **fields}


class RenderFixture(unittest.TestCase):
    def test_without_a_summary_the_fixture_renders_as_before_the_summary_was_printed(self):
        # The content M3-2's second part (201475a) gave for this material, which had no place for a summary.
        self.assertEqual(rendered({**MATERIAL, "summary": None}), {
            "name": "李明",
            "contact": "13800000000 | liming@example.com | github.com/example",
            "intent": "求职意向：后端开发、大模型应用开发（实习） · 深圳、广州 · 每周 4 天，可实习 6 个月 · 2026.11.15 起可到岗",
            "sections": [
                {"title": "教育经历", "entries": [
                    {"left": "示例理工大学", "middle": "计算机科学与技术 · 硕士", "right": "2025.09 - 2027.06",
                     "bullets": ["GPA 3.6/4.0，专业前15%", "主修课程：机器学习、分布式系统"]},
                    {"left": "示例师范大学", "middle": "软件工程 · 本科", "right": "2021.09 - 2025.06", "bullets": []}]},
                {"title": "实习经历", "entries": [
                    {"left": "示例网络科技有限公司", "middle": "后端开发实习生", "right": "2026.03 - 2026.08",
                     "bullets": ["用 Go 重构订单查询接口，P99 延迟从 120ms 降到 45ms",
                                 "用 Python 编写 RAG 问答的检索评测脚本，覆盖 300 条测试问题"]}]},
                {"title": "项目经历", "entries": [
                    {"left": "课程助手问答系统", "middle": "", "right": "2025.10 - 2026.01",
                     "bullets": ["基于 LangChain 和 MySQL 搭建课程资料问答，支持 20 门课程"]}]},
                {"title": "专业技能", "lines": [
                    {"label": "熟练", "rest": "Python、Go"}, {"label": "熟悉", "rest": "MySQL、LangChain"},
                    {"label": "项目中使用", "rest": "RAG"}]},
                {"title": "荣誉与证书", "lines": [
                    {"label": "", "rest": "全国大学生数学建模竞赛 省级一等奖（2024.10）"}, {"label": "", "rest": "CET-6 552"}]},
            ],
        })

    def test_a_summary_is_the_first_section_and_changes_nothing_else(self):
        with_summary, without = rendered(MATERIAL), rendered({**MATERIAL, "summary": None})
        self.assertEqual(with_summary["sections"][0], {"title": "个人简介", "text": MATERIAL["summary"]["text"]})
        self.assertEqual({**with_summary, "sections": with_summary["sections"][1:]}, without)

    def test_the_word_version_of_the_rendered_content_passes_its_check(self):
        content = rendered(MATERIAL)
        self.assertIn(MATERIAL["summary"]["text"], resume_pdf.fields_of(content))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "resume-1.docx"
            resume_docx.write(content, path)
            self.assertEqual(resume_docx.check(path, resume_pdf.fields_of(content)), [])
            # The summary is held to the same check: a Word version without it fails.
            resume_docx.write({**content, "sections": content["sections"][1:]}, path)
            self.assertTrue(any(MATERIAL["summary"]["text"] in problem
                                for problem in resume_docx.check(path, resume_pdf.fields_of(content))))

    def test_nothing_listed_leaves_only_the_header(self):
        bare = {**MATERIAL, "summary": None, "education": [], "experience": [], "skills": [], "awards": [],
                "certificates": [], "languages": []}
        self.assertEqual(rendered(bare)["sections"], [])


class RenderRules(unittest.TestCase):
    def setUp(self):
        self.profile, self.material = copy.deepcopy(PROFILE), copy.deepcopy(MATERIAL)

    def experience(self, *entries) -> list:
        """The sections for a material that lists only these experience entries."""
        self.profile["experience"] = list(entries)
        self.material.update(summary=None, education=[], skills=[], awards=[], certificates=[], languages=[],
                             experience=[{"ref": item["id"], "bullets": []} for item in entries])
        for skill in self.profile["skills"]:
            skill["used_in"] = []
        return rendered(self.material, self.profile)["sections"]

    def test_dates_are_months_with_an_ascii_hyphen_and_an_open_end_is_today(self):
        sections = self.experience(entry(id="a", name="甲", start="2026-03-15", end=None),
                                   entry(id="b", name="乙", start=None, end="2025-06"),
                                   entry(id="c", name="丙"))
        self.assertEqual([item["right"] for item in sections[0]["entries"]], ["2026.03 - 至今", "2025.06", ""])

    def test_one_section_per_type_in_the_order_the_material_first_lists_it(self):
        sections = self.experience(entry(id="a", name="项目甲"), entry(id="b", type="internship", org="公司乙"),
                                   entry(id="c", name="项目丙"))
        self.assertEqual([(item["title"], [e["left"] for e in item["entries"]]) for item in sections],
                         [("项目经历", ["项目甲", "项目丙"]), ("实习经历", ["公司乙"])])

    def test_projects_contests_and_research_are_headed_by_name_jobs_and_campus_by_org(self):
        sections = self.experience(
            entry(id="a", type="competition", name="数学建模竞赛", org="学院代表队", role="队长"),
            entry(id="b", type="research", name="检索评测课题", org="信息检索实验室"),
            entry(id="c", type="work", name="订单系统", org="示例公司", role="工程师"),
            entry(id="d", type="campus", org="学生会外联部", role="副部长"),
            entry(id="e", type="project", org="开源社区"))  # no name: the org stands in
        heads = {item["title"]: [(e["left"], e["middle"]) for e in item["entries"]] for item in sections}
        self.assertEqual(heads, {"竞赛经历": [("数学建模竞赛", "队长")], "科研经历": [("检索评测课题", "")],
                                 "工作经历": [("示例公司", "工程师")], "校园经历": [("学生会外联部", "副部长")],
                                 "项目经历": [("开源社区", "")]})

    def test_skills_go_strongest_first_in_the_materials_order_and_spelling(self):
        self.profile["skills"] += [{"name": "Kubernetes", "level": "expert", "used_in": [], "source": "resume.txt"}]
        self.material["skills"] = ["PyTorch", "RAG", "LangChain", "Golang", "K8s", "Python"]
        lines = section(rendered(self.material, self.profile), "专业技能")["lines"]
        self.assertEqual(lines, [{"label": "精通", "rest": "K8s"}, {"label": "熟练", "rest": "Golang、Python"},
                                 {"label": "熟悉", "rest": "LangChain"}, {"label": "项目中使用", "rest": "RAG"},
                                 {"label": "了解", "rest": "PyTorch"}])

    def test_a_language_gets_its_own_line_unless_a_listed_certificate_says_its_level(self):
        self.profile["languages"] += [{"id": "lang-2", "name": "日语", "level": "N2", "source": "user"},
                                      {"id": "lang-3", "name": "粤语", "level": None, "source": "user"}]
        self.material["languages"] = [{"ref": "lang-1"}, {"ref": "lang-2"}, {"ref": "lang-3"}]
        texts = [line["rest"] for line in section(rendered(self.material, self.profile), "荣誉与证书")["lines"]]
        self.assertEqual(texts, ["全国大学生数学建模竞赛 省级一等奖（2024.10）", "CET-6 552", "日语 N2", "粤语"])
        self.material["certificates"] = []  # CET-6 not listed: the language line says it instead
        texts = [line["rest"] for line in section(rendered(self.material, self.profile), "荣誉与证书")["lines"]]
        self.assertIn("英语 CET-6 552", texts)

    def test_an_award_without_a_date_and_a_certificate_without_detail(self):
        self.profile["awards"][0]["date"] = None
        self.profile["certificates"][0]["detail"] = None
        self.material["languages"] = []
        texts = [line["rest"] for line in section(rendered(self.material, self.profile), "荣誉与证书")["lines"]]
        self.assertEqual(texts, ["全国大学生数学建模竞赛 省级一等奖", "CET-6"])

    def test_a_gpa_that_already_says_so_is_not_prefixed_again(self):
        school = self.profile["education"][0]
        for gpa, rank, expected in (("绩点 3.6", None, ["绩点 3.6"]), ("GPA: 3.6/4.0", None, ["GPA: 3.6/4.0"]),
                                    (None, "专业前15%", ["专业前15%"]), (None, None, [])):
            school["gpa"], school["rank"] = gpa, rank
            bullets = section(rendered(self.material, self.profile), "教育经历")["entries"][0]["bullets"]
            self.assertEqual(bullets, expected + ["主修课程：机器学习、分布式系统"], gpa)

    def test_the_intent_names_days_and_months_only_for_an_internship(self):
        self.profile["target"]["employment_types"] = ["campus", "experienced"]
        self.assertEqual(rendered(self.material, self.profile)["intent"],
                         "求职意向：后端开发、大模型应用开发（校招、社招） · 深圳、广州 · 2026.11.15 起可到岗")

    def test_the_intent_drops_what_the_profile_leaves_out(self):
        target, availability = self.profile["target"], self.profile["availability"]
        target["roles"], availability["cities"], availability["start_date"] = [], [], None
        availability["days_per_week"] = None
        self.assertEqual(rendered(self.material, self.profile)["intent"], "求职意向：实习 · 可实习 6 个月")
        target["employment_types"] = []
        self.assertEqual(rendered(self.material, self.profile)["intent"], "")

    def test_contact_skips_what_is_missing_and_a_missing_name_is_empty(self):
        self.profile["contact"].update(name=None, github=None, website="example.com")
        content = rendered(self.material, self.profile)
        self.assertEqual((content["name"], content["contact"]), ("", "13800000000 | liming@example.com | example.com"))


class Command(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.temp = Path(directory.name)
        self.root = self.temp / "data"
        self.folder = self.root / "resumes" / MATERIAL["job_id"]

    def write_material(self, record: dict = MATERIAL, name: str = "resume-2.json") -> Path:
        path = self.temp / name
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        return path

    def run_cli(self, path: Path, *extra):
        out, err = io.StringIO(), io.StringIO()
        argv = ["resume", "build", str(path), "--profile", str(FIXTURE / "profile" / "profile.json"),
                "--data-dir", str(self.root), *extra]
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_both_files_are_named_after_the_material_and_hold_the_content(self):
        with faked_typst(pdf_with_pages(1)), mock.patch.object(resume_pdf, "check", return_value=[]) as check:
            code, out, _ = self.run_cli(self.write_material())
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertEqual((result["pdf"], result["docx"]),
                         (str(self.folder / "resume-2.pdf"), str(self.folder / "resume-2.docx")))
        self.assertEqual((result["problems"], result["warnings"], result["font"]), ([], [], resume_docx.FONT))
        self.assertEqual((self.folder / "resume-2.pdf").read_bytes(), pdf_with_pages(1))
        self.assertEqual(check.call_args.args[1], resume_pdf.fields_of(rendered(MATERIAL)))
        self.assertEqual(sorted(os.listdir(self.folder)), ["resume-2.build.json", "resume-2.docx", "resume-2.pdf"])
        note = json.loads((self.folder / "resume-2.build.json").read_text(encoding="utf-8"))
        self.assertEqual((note["kind"], note["material"], note["material_hash"]),
                         ("resume-build", "resume-2.json", review.material_hash(MATERIAL)))
        self.assertEqual({item["name"]: item["sha256"] for item in note["files"]},
                         {name: hashlib.sha256((self.folder / name).read_bytes()).hexdigest()
                          for name in ("resume-2.pdf", "resume-2.docx")})
        self.assertRegex(note["built_at"], r"[+-]\d\d:\d\d$")

    def test_a_changed_resume_is_built_again_for_the_next_round(self):
        # The reviewer's first check (resume-workflow.md section 2, step 2): the build note carries the
        # material_hash review draft gives. After a change it does not, until resume build runs again.
        path = self.write_material()
        with faked_typst(pdf_with_pages(1)), mock.patch.object(resume_pdf, "check", return_value=[]):
            self.assertEqual(self.run_cli(path)[0], 0)
        note = self.folder / "resume-2.build.json"
        changed = {**MATERIAL, "summary": None}
        path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(["review", "draft", str(path), "--profile", str(FIXTURE / "profile" / "profile.json"),
                             "--data-dir", str(self.root)])
        self.assertEqual(code, 0)
        drafted = json.loads(out.getvalue())["material_hash"]
        self.assertNotEqual(json.loads(note.read_text(encoding="utf-8"))["material_hash"], drafted)
        with faked_typst(pdf_with_pages(1)), mock.patch.object(resume_pdf, "check", return_value=[]):
            code, built, _ = self.run_cli(path)
        self.assertEqual(code, 0)
        self.assertEqual(Path(json.loads(built)["build_note"]), note)
        self.assertEqual(json.loads(note.read_text(encoding="utf-8"))["material_hash"], drafted)

    def test_an_invalid_material_writes_nothing(self):
        record = copy.deepcopy(MATERIAL)
        record["experience"][0]["bullets"][0]["text"] = "P99 延迟降到 30ms"
        code, out, err = self.run_cli(self.write_material(record))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("the number '30'", json.loads(err)["errors"][0])
        self.assertFalse((self.root / "resumes").exists())

    def test_the_material_must_be_named_resume_n(self):
        for name in ("material.json", "resume-0.json", "resume-1.json.bak"):
            code, _, err = self.run_cli(self.write_material(name=name))
            self.assertEqual(code, 2, name)
            self.assertIn("resume-<n>.json", json.loads(err)["error"])
        self.assertFalse(self.root.exists())

    def test_a_job_id_that_is_no_job_id_cannot_name_a_folder(self):
        record = {**MATERIAL, "job_id": "../../outside"}
        code, _, err = self.run_cli(self.write_material(record))
        self.assertEqual(code, 2)
        self.assertIn("job id", json.loads(err)["error"])
        self.assertFalse(self.root.exists())

    def test_a_pdf_that_does_not_fit_writes_no_word_version(self):
        with mock.patch.object(resume_pdf, "render", side_effect=resume_pdf.ResumeError("内容太多")):
            code, _, err = self.run_cli(self.write_material())
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "内容太多")
        self.assertEqual(os.listdir(self.folder), [])

    def test_a_failed_build_keeps_the_earlier_build_note(self):
        self.folder.mkdir(parents=True)
        earlier = self.folder / "resume-2.build.json"
        earlier.write_text('{"kind": "resume-build", "earlier": true}', encoding="utf-8")
        with mock.patch.object(resume_pdf, "render", side_effect=resume_pdf.ResumeError("内容太多")):
            code, _, err = self.run_cli(self.write_material())
        self.assertEqual((code, json.loads(err)["error"]), (1, "内容太多"))
        self.assertEqual(earlier.read_text(encoding="utf-8"), '{"kind": "resume-build", "earlier": true}')
        self.assertIsNone(cli._write_build_note(self.folder, "resume-3", MATERIAL, {}, (self.folder / "resume-3.pdf",)))
        self.assertFalse((self.folder / "resume-3.build.json").exists())

    def assert_json_error_without_path(self, code, out, err, *hidden):
        """V24 P3-1: a failed write is one JSON error on stderr, exit 1, with no traceback and no path."""
        self.assertEqual((code, out), (1, ""))
        error = json.loads(err)["error"]
        self.assertNotIn("Traceback", err)
        for text in hidden:
            self.assertNotIn(text, err)
        return error

    def test_a_temporary_folder_that_cannot_be_made_is_a_json_error_without_its_path(self):
        # V24: in Codex's Windows sandbox, making build/ inside the temporary directory gave WinError 5.
        temp = str(Path(tempfile.gettempdir()) / "jobsearch-cn-resume-x1" / "build")
        denied = PermissionError(13, "拒绝访问。", temp)
        for target in ("_build_folder", "_compile"):
            with self.subTest(failing=target), faked_typst(pdf_with_pages(1)), \
                    mock.patch.object(resume_pdf, target, side_effect=denied):
                error = self.assert_json_error_without_path(*self.run_cli(self.write_material()),
                                                            temp, "jobsearch-cn-resume-", tempfile.gettempdir())
                self.assertIn("临时目录", error)
                self.assertIn("拒绝访问。", error)
                self.assertEqual(os.listdir(self.folder), [])

    def test_a_copy_of_the_template_that_fails_shows_no_paths(self):
        # shutil.Error is an OSError whose only content is the paths that failed.
        failed = shutil.Error([(str(resume_pdf.TEMPLATE), "C:/Users/someone/AppData/Local/Temp/x", "denied")])
        with faked_typst(pdf_with_pages(1)), mock.patch.object(resume_pdf.shutil, "copytree", side_effect=failed):
            error = self.assert_json_error_without_path(*self.run_cli(self.write_material()), "someone", "AppData")
        self.assertIn("（Error）", error)

    @unittest.skipUnless(sys.platform == "win32", "only Windows sets winerror")
    def test_the_windows_error_number_is_kept_for_the_workflow_note(self):
        # resume-workflow.md section 2 tells Codex what to do on WinError 5; the number names no path.
        denied = OSError(None, "拒绝访问。", str(Path(tempfile.gettempdir()) / "jobsearch-cn-resume-x1" / "build"), 5)
        with faked_typst(pdf_with_pages(1)), mock.patch.object(resume_pdf, "_build_folder", side_effect=denied):
            error = self.assert_json_error_without_path(*self.run_cli(self.write_material()), "jobsearch-cn-resume-")
        self.assertIn("（[WinError 5] 拒绝访问。）", error)

    def test_an_output_that_cannot_be_written_is_a_json_error_naming_only_the_file(self):
        # A folder where a file should go: a real failed write (WinError 5 on Windows, EISDIR elsewhere).
        path = self.write_material()
        for name in ("resume-2.pdf", "resume-2.docx", "resume-2.build.json"):
            shutil.rmtree(self.root, ignore_errors=True)
            (self.folder / name).mkdir(parents=True)
            with self.subTest(failing=name), faked_typst(pdf_with_pages(1)), \
                    mock.patch.object(resume_pdf, "check", return_value=[]), \
                    mock.patch.object(resume_docx, "check", return_value=[]), \
                    mock.patch.object(resume_docx, "same_text", return_value=[]):
                error = self.assert_json_error_without_path(*self.run_cli(path), str(self.root), str(self.temp))
                self.assertTrue(error.startswith(("写不了 resume-2.pdf（", f"cannot write {name}: ")), error)
                self.assertIn(name, error)
                self.assertEqual([entry for entry in os.listdir(self.folder) if entry.startswith(".tmp-")], [])

    def test_a_data_folder_that_cannot_be_made_is_a_json_error(self):
        self.root.mkdir()
        (self.root / "resumes").write_text("a file where the folder goes", encoding="utf-8")
        error = self.assert_json_error_without_path(*self.run_cli(self.write_material()), str(self.root))
        self.assertTrue(error.startswith(f"cannot make the folder resumes/{MATERIAL['job_id']} in the data directory: "),
                        error)

    def test_problems_in_either_file_fail_the_command(self):
        with faked_typst(pdf_with_pages(1)), mock.patch.object(resume_pdf, "check", return_value=["PDF 有问题"]), \
                mock.patch.object(resume_docx, "check", return_value=["Word 版有问题"]):
            code, out, _ = self.run_cli(self.write_material())
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["problems"], ["PDF 有问题", "Word 版有问题"])

    def test_the_explicit_typst_path_reaches_the_renderer(self):
        with mock.patch.object(resume_pdf, "render", return_value={}) as render, \
                mock.patch.object(resume_pdf, "check", return_value=[]):
            code, _, _ = self.run_cli(self.write_material(), "--typst", "my-typst")
        self.assertEqual(code, 0)
        self.assertEqual(render.call_args.args[2], "my-typst")

    def test_a_link_for_the_word_version_is_refused_before_anything_is_written(self):
        outside = self.temp / "outside.docx"
        outside.write_bytes(b"keep")
        self.folder.mkdir(parents=True)
        try:
            (self.folder / "resume-2.docx").symlink_to(outside)
        except OSError:
            self.skipTest("creating a link needs a privilege here")
        with mock.patch.object(resume_pdf, "render") as render:
            code, _, err = self.run_cli(self.write_material())
        self.assertEqual(code, 2)
        self.assertIn("link", json.loads(err)["error"])
        render.assert_not_called()
        self.assertEqual(outside.read_bytes(), b"keep")


class NotesAgree(unittest.TestCase):
    """material validate, resume build and review draft read the same notes.md and come to the same verdict
    (M3-2c); a material that does not cite it drafts the same review with or without the file."""

    COMMANDS = ("material validate", "resume build", "review draft")

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.temp = Path(directory.name)
        shutil.copytree(FIXTURE / "profile", self.temp / "profile")
        self.write({**MATERIAL, "summary": {"text": "计算机硕士在读，有后端和大模型应用的实习与项目经验",
                                            "refs": ["notes.md"]}})

    def write(self, record: dict) -> None:
        self.path = self.temp / "resume-1.json"
        self.path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    def run_command(self, command: str) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        argv = [*command.split(), str(self.path), "--profile", str(self.temp / "profile" / "profile.json"),
                "--data-dir", str(self.temp / "data")]
        with redirect_stdout(out), redirect_stderr(err), faked_typst(pdf_with_pages(1)), \
                mock.patch.object(resume_pdf, "check", return_value=[]):
            code = cli.main(argv)
        return code, json.loads(out.getvalue() or err.getvalue())

    def verdicts(self) -> list:
        """(exit code, errors) from each command."""
        return [(code, result.get("errors", [])) for code, result in map(self.run_command, self.COMMANDS)]

    def test_with_the_notes_all_pass_and_without_them_all_fail_alike(self):
        self.assertEqual(self.verdicts(), [(0, [])] * 3)
        (self.temp / "profile" / "notes.md").unlink()
        expected = ["summary.refs[0]: cites notes.md, but there is no notes.md beside the profile that reads as "
                    "UTF-8 text"]
        self.assertEqual(self.verdicts(), [(1, expected)] * 3)

    def test_a_number_only_in_the_preference_log_fails_all_alike(self):
        with open(self.temp / "profile" / "notes.md", "a", encoding="utf-8") as notes:
            notes.write("\n## 偏好记录\n```text\n## 示例\n```\n- `target.weights` → {\"skills\": 73}\n")
        self.write({**MATERIAL, "summary": {"text": "做过73次评测", "refs": ["notes.md"]}})
        verdicts = self.verdicts()
        self.assertEqual([code for code, _ in verdicts], [1, 1, 1])
        self.assertEqual(len({tuple(errors) for _, errors in verdicts}), 1)
        self.assertIn("the number '73'", verdicts[0][1][0])

    def test_a_material_not_citing_the_notes_drafts_the_same_review_without_them(self):
        self.write(MATERIAL)
        with_notes = self.run_command("review draft")
        (self.temp / "profile" / "notes.md").unlink()
        self.assertEqual(self.run_command("review draft"), with_notes)
        self.assertEqual(with_notes[0], 0)

    def test_notes_are_read_only_when_the_summary_cites_them(self):
        # #115 P3: a material that does not cite notes.md never opens it, in any of the three commands.
        for record in (MATERIAL, {**MATERIAL, "summary": None}):
            self.write(record)
            with mock.patch.object(material, "read_notes") as read:
                self.assertEqual([code for code, _ in map(self.run_command, self.COMMANDS)], [0, 0, 0])
            read.assert_not_called()
        self.write({**MATERIAL, "summary": {"text": "计算机硕士在读", "refs": ["exp-1", "notes.md"]}})
        with mock.patch.object(material, "read_notes", wraps=material.read_notes) as read:
            self.assertEqual([code for code, _ in map(self.run_command, self.COMMANDS)], [0, 0, 0])
        self.assertEqual(read.call_count, 3)
        self.assertEqual(read.call_args.args[0], self.temp / "profile" / "notes.md")


class WriteWord(unittest.TestCase):
    def test_a_hard_link_for_the_output_is_replaced_and_the_file_it_shared_is_kept(self):
        with tempfile.TemporaryDirectory() as temp:
            outside, output = Path(temp) / "outside.docx", Path(temp) / "resume-1.docx"
            outside.write_bytes(b"keep")
            try:
                os.link(outside, output)
            except OSError:
                self.skipTest("this file system has no hard links")
            resume_docx.write(resume_pdf.sample(), output)
            self.assertEqual(outside.read_bytes(), b"keep")
            self.assertEqual(output.read_bytes()[:2], b"PK")

    def test_a_failed_write_keeps_the_old_file_and_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "resume-1.docx"
            output.write_bytes(b"old")
            with mock.patch.object(resume_pdf.os, "replace", side_effect=OSError("disk full")) as replace:
                with self.assertRaises(OSError):
                    resume_docx.write(resume_pdf.sample(), output)
            self.assertEqual(output.read_bytes(), b"old")
            self.assertEqual(os.listdir(temp), ["resume-1.docx"])
            self.assertEqual(Path(replace.call_args.args[0]).suffix, ".docx")


if __name__ == "__main__":
    unittest.main()
