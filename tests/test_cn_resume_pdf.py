"""resume_pdf: the Typst call, fitting to one page, and the PDF checks.

The pure tests run everywhere. The ones that really render need Typst, a Chinese
font and a PDF reader, as the pdftotext tests do, and skip without them, except
where JOBSEARCH_CN_REQUIRE_TYPST=1: CI's real-render job sets it, and there a
missing piece fails them instead (H31).
"""
import copy
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zlib
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from jobsearch_cn import cli, resume_extract, resume_pdf  # noqa: E402


PYPDF = importlib.util.find_spec("pypdf") is not None
REQUIRED = os.environ.get("JOBSEARCH_CN_REQUIRE_TYPST") == "1"


def _missing() -> str | None:
    """What the real-render tests lack here, or None. Where they are required every one of them
    runs, so the one that compares with pypdf's reading needs pypdf, not just a PDF reader."""
    try:
        resume_pdf._fonts(resume_pdf.find_typst())
    except resume_pdf.ResumeError as exc:
        return str(exc)
    if REQUIRED and not PYPDF:
        return "pypdf is not installed"
    if not (PYPDF or resume_extract._poppler_available()):
        return "there is no PDF reader (pypdf or pdftotext)"
    return None


MISSING = _missing()
NEEDS_TOOLCHAIN = "needs Typst, a Chinese font, and pypdf or pdftotext (docs/cn/resume-pdf.md)"


def stream(text: str) -> bytes:
    return b"1 0 obj\n<< /Filter /FlateDecode >>\nstream\n" + zlib.compress(text.encode("ascii")) + b"\nendstream\n"


def char_map(*chars: str) -> str:
    pairs = "\n".join(f"<{i:04X}> <{c.encode('utf-16-be').hex().upper()}>" for i, c in enumerate(chars, 1))
    return f"begincmap\n{len(chars)} beginbfchar\n{pairs}\nendbfchar\nendcmap"


def pdf_with_pages(pages: int, spaciness=None) -> bytes:
    return b"<</Type/Pages/Count %d>>" % pages + b"<</Type/Page>>" * pages + str(spaciness).encode()


@contextmanager
def faked_typst(pdf: bytes):
    """render's own steps with the Typst calls faked: every compile returns pdf."""
    with mock.patch.object(resume_pdf, "find_typst", return_value="typst"), \
            mock.patch.object(resume_pdf, "_fonts", return_value={"serif": "S", "sans": "S"}), \
            mock.patch.object(resume_pdf, "_compile", return_value=pdf):
        yield


class TemplateIsPackageData(unittest.TestCase):
    def test_nothing_comes_from_the_network_or_the_lgpl_icons(self):
        for name in ("lib.typ", "main.typ"):
            with self.subTest(file=name):
                text = (resume_pdf.TEMPLATE / name).read_text(encoding="utf-8")
                for banned in ("@preview", "@local", "nerd-icons", "nf-icon", "http://", "https://"):
                    self.assertNotIn(banned, text)

    def test_the_license_and_the_source_stay_with_it(self):
        self.assertIn("MIT License", (resume_pdf.TEMPLATE / "LICENSE").read_text(encoding="utf-8"))
        self.assertIn("Copyright (c) 2025 habaneraa", (resume_pdf.TEMPLATE / "LICENSE").read_text(encoding="utf-8"))
        source = (resume_pdf.TEMPLATE / "SOURCE.md").read_text(encoding="utf-8")
        self.assertIn("98aea62a4f37d9503247b4935087e26c84109a84", source)
        self.assertIn("habaneraa/typst-resume-one-page", source)

    def test_the_repo_lists_it_as_a_third_party_component(self):
        listing = (REPO / "THIRD_PARTY.md").read_text(encoding="utf-8")
        self.assertIn("jobsearch_cn/resume_templates/habaneraa/", listing)
        self.assertIn("98aea62", listing)

    def test_the_sample_has_every_kind_of_content_the_template_prints(self):
        sample = resume_pdf.sample()
        self.assertTrue(sample["contact"] and sample["intent"])
        self.assertTrue(any("entries" in section for section in sample["sections"]))
        self.assertTrue(any("lines" in section for section in sample["sections"]))
        self.assertTrue(any("text" in section for section in sample["sections"]))  # the summary (M3-2c)


class FindTypst(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(resume_pdf.TYPST_ENV, None)

    def version(self, stdout="typst 0.15.1 (9dfd3a08)\n", code=0):
        return mock.patch.object(resume_pdf, "_run", return_value=subprocess.CompletedProcess([], code, stdout, ""))

    def test_an_explicit_path_beats_the_variable_and_the_variable_beats_path(self):
        os.environ[resume_pdf.TYPST_ENV] = "from-env"
        with mock.patch("shutil.which", side_effect=lambda name: f"/bin/{name}") as which, self.version():
            self.assertEqual(resume_pdf.find_typst("explicit"), "/bin/explicit")
            self.assertEqual(resume_pdf.find_typst(), "/bin/from-env")
            del os.environ[resume_pdf.TYPST_ENV]
            self.assertEqual(resume_pdf.find_typst(), "/bin/typst")
        self.assertEqual([call.args[0] for call in which.call_args_list], ["explicit", "from-env", "typst"])

    def test_not_found_says_how_to_install(self):
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaisesRegex(resume_pdf.ResumeError, "docs/cn/resume-pdf.md"):
                resume_pdf.find_typst()

    def test_too_old_is_refused_and_the_oldest_allowed_is_not(self):
        with mock.patch("shutil.which", return_value="/bin/typst"):
            with self.version("typst 0.12.0\n"), self.assertRaisesRegex(resume_pdf.ResumeError, "0.12.*0.13"):
                resume_pdf.find_typst()
            with self.version("typst 0.13.0\n"):
                self.assertEqual(resume_pdf.find_typst(), "/bin/typst")

    def test_a_program_that_is_not_typst_is_refused(self):
        with mock.patch("shutil.which", return_value="/bin/other"):
            for stdout, code in (("other 1.0\n", 0), ("typst 0.15.1\n", 1)):
                with self.subTest(stdout=stdout, code=code), self.version(stdout, code):
                    with self.assertRaisesRegex(resume_pdf.ResumeError, "不是 Typst"):
                        resume_pdf.find_typst()
        with mock.patch("shutil.which", return_value="/bin/typst"), \
                mock.patch.object(resume_pdf, "_run", side_effect=OSError):
            with self.assertRaisesRegex(resume_pdf.ResumeError, "运行不了"):
                resume_pdf.find_typst()


class PickFonts(unittest.TestCase):
    def listed(self, *families):
        return mock.patch.object(resume_pdf, "_run", return_value=subprocess.CompletedProcess(
            [], 0, "".join(f"{family}\n" for family in families), ""))

    def test_noto_first_then_its_other_names_then_yahei(self):
        with self.listed("Microsoft YaHei", "Noto Serif CJK SC", "Noto Sans SC"):
            self.assertEqual(resume_pdf._fonts("typst"), {"serif": "Noto Serif CJK SC", "sans": "Noto Sans SC"})
        with self.listed("Microsoft YaHei"):
            self.assertEqual(resume_pdf._fonts("typst"), {"serif": "Microsoft YaHei", "sans": "Microsoft YaHei"})

    def test_no_chinese_font_is_an_error_rather_than_empty_boxes(self):
        with self.listed("DejaVu Sans Mono", "Libertinus Serif"):
            with self.assertRaisesRegex(resume_pdf.ResumeError, "中文字体"):
                resume_pdf._fonts("typst")


class FitToOnePage(unittest.TestCase):
    def fit(self, needs: float, pages_over=2):
        """Content that fits one page at spaciness <= needs."""
        tried = []

        def compile_at(value):
            tried.append(value)
            return pdf_with_pages(1 if value <= needs else pages_over, value)
        return *resume_pdf._fit(compile_at), tried

    def test_room_to_spare_stays_at_the_loosest(self):
        spaciness, data, tried = self.fit(9.0)
        self.assertEqual((spaciness, tried), (resume_pdf.LOOSEST, [resume_pdf.LOOSEST]))
        self.assertEqual(resume_pdf.page_count(data), 1)

    def test_too_much_for_the_loosest_finds_the_loosest_that_fits(self):
        spaciness, data, tried = self.fit(1.051)
        self.assertLessEqual(spaciness, 1.051)
        self.assertGreater(spaciness, 1.051 - 0.012)
        self.assertEqual(len(tried), 8)
        # The bytes are those of the spacing it reports, not of the last attempt.
        self.assertTrue(data.endswith(str(spaciness).encode()))
        self.assertEqual(resume_pdf.page_count(data), 1)

    def test_exactly_the_tightest_still_fits(self):
        spaciness, data, _ = self.fit(resume_pdf.TIGHTEST)
        self.assertEqual(spaciness, resume_pdf.TIGHTEST)
        self.assertEqual(resume_pdf.page_count(data), 1)

    def test_too_much_for_the_tightest_says_to_cut(self):
        with self.assertRaisesRegex(resume_pdf.ResumeError, "还有 3 页"):
            self.fit(0.1, pages_over=3)


class PageCount(unittest.TestCase):
    def test_the_page_tree_node_is_not_a_page(self):
        self.assertEqual(resume_pdf.page_count(pdf_with_pages(2)), 2)
        self.assertEqual(resume_pdf.page_count(b"<< /Type /Page >> << /Type /Pages >>"), 1)

    def test_a_pdf_it_cannot_count_is_an_error_not_zero(self):
        with self.assertRaises(resume_pdf.ResumeError):
            resume_pdf.page_count(b"<< /Type /ObjStm >>")


class MappedText(unittest.TestCase):
    def test_single_characters(self):
        self.assertEqual(resume_pdf.mapped_text(stream(char_map("大", "A"))), "大A")

    def test_ranges_and_arrays(self):
        text = "begincmap\n2 beginbfrange\n<01> <03> <4E00>\n<04> <05> [<0041> <0042>]\nendbfrange\nendcmap"
        self.assertEqual(resume_pdf.mapped_text(stream(text)), "一丁丂AB")

    def test_a_character_outside_the_bmp(self):
        self.assertEqual(resume_pdf.mapped_text(stream(char_map("\U000F0000"))), "\U000F0000")

    def test_several_fonts_add_up_and_other_streams_are_left_out(self):
        data = stream(char_map("甲")) + stream("BT (not a map) Tj ET") + stream(char_map("乙"))
        self.assertEqual(resume_pdf.mapped_text(data), "甲乙")

    def test_none_when_no_font_has_a_map(self):
        self.assertIsNone(resume_pdf.mapped_text(stream("BT ET")))


class Check(unittest.TestCase):
    """verify_pdf and the text reader have their own tests; here, what check adds to them."""

    def check(self, data: bytes, fields=(), text="示例 理工\n大学", verify=()):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "x.pdf"
            path.write_bytes(data)
            with mock.patch.object(resume_pdf, "_verify_pdf", return_value=list(verify)), \
                    mock.patch.object(resume_extract, "extract_text", return_value=text):
                return resume_pdf.check(path, fields)

    def test_a_clean_pdf_has_no_problems(self):
        self.assertEqual(self.check(stream(char_map("大", "学", "•"))), [])

    def test_the_ends_of_the_radical_range_are_caught_and_their_neighbours_are_not(self):
        for char, caught in (("⹿", False), ("⺀", True), ("⼤", True), ("⿟", True), ("⿠", False)):
            with self.subTest(char=f"{ord(char):04X}"):
                self.assertEqual(any("康熙部首" in p for p in self.check(stream(char_map(char)))), caught)

    def test_private_use_in_each_plane_is_caught_and_its_neighbours_are_not(self):
        for char, caught in (("", True), ("", True), ("豈", False),
                             ("\U000F0000", True), ("\U000FFFFD", True), ("\U00100000", True), ("\U0010FFFD", True),
                             ("\U000EFFFF", False)):
            with self.subTest(char=f"{ord(char):04X}"):
                self.assertEqual(any("私用区" in p for p in self.check(stream(char_map(char)))), caught)

    def test_no_map_is_a_problem_rather_than_a_pass(self):
        self.assertTrue(any("查不了" in p for p in self.check(stream("BT ET"))))

    def test_a_type3_font_is_a_problem(self):
        self.assertTrue(any("Type 3" in p for p in self.check(stream(char_map("大")) + b"<</Subtype/Type3>>")))

    def test_fields_compare_ignoring_whitespace_and_a_missing_one_is_named(self):
        data = stream(char_map("大"))
        self.assertEqual(self.check(data, ["示例理工大学", "示例 理工"]), [])
        problems = self.check(data, ["示例理工大学", "不存在的字段"])
        self.assertEqual(len(problems), 1)
        self.assertIn("不存在的字段", problems[0])
        self.assertNotIn("示例理工大学", problems[0])

    def test_verify_pdf_problems_are_passed_on(self):
        self.assertEqual(self.check(stream(char_map("大")), verify=["verify_pdf：2 pages"]), ["verify_pdf：2 pages"])

    def test_an_unreadable_text_layer_is_a_problem_and_the_others_stay(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "x.pdf"
            path.write_bytes(stream(char_map("⼤")))
            with mock.patch.object(resume_pdf, "_verify_pdf", return_value=[]), \
                    mock.patch.object(resume_extract, "extract_text", side_effect=resume_extract.ExtractionError("坏了")):
                problems = resume_pdf.check(path, ["字段"])
        self.assertEqual(len(problems), 2)
        self.assertIn("康熙部首", problems[0])
        self.assertIn("坏了", problems[1])


class VerifyPdfCall(unittest.TestCase):
    def test_it_asks_for_one_page_and_ascii_dates(self):
        with mock.patch.object(resume_pdf, "_run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            self.assertEqual(resume_pdf._verify_pdf(Path("x.pdf")), [])
        command = run.call_args.args[0]
        self.assertEqual(command[:3], [sys.executable, str(resume_pdf.VERIFY_PDF), "x.pdf"])
        self.assertEqual(command[3:], ["--pages", "1", "--ascii-dates"])

    def test_the_tool_exists_where_the_package_expects_it(self):
        self.assertTrue(resume_pdf.VERIFY_PDF.is_file())

    def test_a_failure_carries_its_message(self):
        failed = subprocess.CompletedProcess([], 1, "", "expected 1 pages, found 2\n")
        with mock.patch.object(resume_pdf, "_run", return_value=failed):
            self.assertEqual(resume_pdf._verify_pdf(Path("x.pdf")), ["verify_pdf：expected 1 pages, found 2"])
        with mock.patch.object(resume_pdf, "_run", side_effect=subprocess.TimeoutExpired("x", 1)):
            self.assertEqual(resume_pdf._verify_pdf(Path("x.pdf")), ["verify_pdf 没有运行完"])


class FieldsOf(unittest.TestCase):
    def test_every_string_at_any_depth_and_no_blank_or_other_value(self):
        content = {"a": "甲", "b": ["乙", {"c": "丙", "d": " "}], "e": 3, "f": None, "g": ""}
        self.assertEqual(resume_pdf.fields_of(content), ["甲", "乙", "丙"])


class Command(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_without_typst_it_says_how_to_install_and_writes_no_pdf(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch("shutil.which", return_value=None):
            code, _, err = self.run_cli("resume", "sample", "--data-dir", temp)
            self.assertEqual(code, 1)
            self.assertIn("docs/cn/resume-pdf.md", json.loads(err)["error"])
            self.assertFalse((Path(temp) / "resumes" / "sample.pdf").exists())

    def test_problems_fail_the_command_and_are_reported(self):
        def render(content, output, typst):
            output.write_bytes(b"pdf")
            return {"pdf": str(output)}
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(resume_pdf, "render", render), \
                mock.patch.object(resume_pdf, "check", return_value=["有问题"]):
            code, out, _ = self.run_cli("resume", "sample", "--data-dir", temp)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["problems"], ["有问题"])

    def test_the_explicit_path_reaches_the_renderer(self):
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(resume_pdf, "render", return_value={}) as render, \
                mock.patch.object(resume_pdf, "check", return_value=[]):
            code, _, _ = self.run_cli("resume", "sample", "--data-dir", temp, "--typst", "my-typst")
        self.assertEqual(code, 0)
        self.assertEqual(render.call_args.args[2], "my-typst")

    def test_a_link_for_the_output_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root, outside = Path(temp) / "data", Path(temp) / "outside.pdf"
            (root / "resumes").mkdir(parents=True)
            outside.write_bytes(b"keep")
            try:
                (root / "resumes" / "sample.pdf").symlink_to(outside)
            except OSError:
                self.skipTest("creating a link needs a privilege here")
            code, _, err = self.run_cli("resume", "sample", "--data-dir", str(root))
            self.assertEqual(code, 2)
            self.assertIn("link", json.loads(err)["error"])
            self.assertEqual(outside.read_bytes(), b"keep")

    def test_a_hard_link_for_the_output_is_replaced_and_the_file_it_shared_is_kept(self):
        with tempfile.TemporaryDirectory() as temp:
            root, outside = Path(temp) / "data", Path(temp) / "outside.pdf"
            output = root / "resumes" / "sample.pdf"
            output.parent.mkdir(parents=True)
            outside.write_bytes(b"keep")
            try:
                os.link(outside, output)
            except OSError:
                self.skipTest("this file system has no hard links")
            with faked_typst(pdf_with_pages(1)), mock.patch.object(resume_pdf, "check", return_value=[]):
                code, _, _ = self.run_cli("resume", "sample", "--data-dir", str(root))
            self.assertEqual(code, 0)
            self.assertEqual(outside.read_bytes(), b"keep")
            self.assertEqual(output.read_bytes(), pdf_with_pages(1))
            self.assertFalse(os.path.samefile(outside, output))


class ReplaceOutput(unittest.TestCase):
    def test_a_failed_write_keeps_the_old_pdf_and_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "sample.pdf"
            output.write_bytes(b"old")
            full = OSError(28, "No space left on device", str(Path(temp) / ".tmp-x.pdf"))
            with faked_typst(pdf_with_pages(1)), \
                    mock.patch.object(resume_pdf.os, "replace", side_effect=full) as replace:
                # V24 P3-1: a ResumeError, which the commands print as JSON; the reason without the path.
                with self.assertRaises(resume_pdf.ResumeError) as raised:
                    resume_pdf.render(resume_pdf.sample(), output)
            self.assertEqual(str(raised.exception), "写不了 sample.pdf（No space left on device）")
            self.assertEqual(output.read_bytes(), b"old")
            self.assertEqual(os.listdir(temp), ["sample.pdf"])
            # Beside the output, inside the folder safe_dir checked, so the rename stays on one disk.
            self.assertEqual(Path(replace.call_args.args[0]).parent, output.parent)


class RequiredToolchain(unittest.TestCase):
    """The switch CI's real-render job relies on, run where Typst cannot be found."""

    def real_render(self, required: bool) -> subprocess.CompletedProcess:
        env = {**os.environ, resume_pdf.TYPST_ENV: str(Path(tempfile.gettempdir()) / "no-such-typst")}
        env.pop("JOBSEARCH_CN_REQUIRE_TYPST", None)
        if required:
            env["JOBSEARCH_CN_REQUIRE_TYPST"] = "1"
        return subprocess.run([sys.executable, "-X", "utf8", "-m", "unittest", "tests.test_cn_resume_pdf.RealRender"],
                              cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")

    def test_without_typst_they_skip_as_before(self):
        result = self.real_render(required=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stderr, r"OK \(skipped=\d+\)")

    def test_where_required_a_missing_typst_fails_them_and_says_what_is_missing(self):
        result = self.real_render(required=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("JOBSEARCH_CN_REQUIRE_TYPST=1, but", result.stderr)
        self.assertIn("no-such-typst", result.stderr)


def page_texts(path: Path) -> list:
    if PYPDF:
        from pypdf import PdfReader
        return [page.extract_text() for page in PdfReader(str(path)).pages]
    pages, number = [], 1
    while True:
        result = subprocess.run(["pdftotext", "-f", str(number), "-l", str(number), "-enc", "UTF-8", str(path), "-"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode or not result.stdout.strip():
            return pages
        pages.append(result.stdout)
        number += 1


@unittest.skipUnless(MISSING is None or REQUIRED, NEEDS_TOOLCHAIN)
class RealRender(unittest.TestCase):
    def test_photo_geometric_portrait_landscape_alpha_and_dense_header(self):
        from tests.test_cn_resume_photo import asset, png
        from jobsearch_cn import resume_docx, resume_photo
        for w, h, channels in ((40, 60, 4), (80, 40, 3), (40, 40, 4)):
            with self.subTest(width=w, height=h):
                picture = asset(png(w, h, channels=channels))
                content = resume_pdf.sample()
                content['name'] = '虚构几何照片验证示例'
                content['contact'] = 'example@example.test · https://example.test/fictional-geometric-resume-validation'
                content['intent'] = '后端开发与数据工程实习 · 深圳及广州 · 每周至少四天 · 可连续六个月'
                result = resume_pdf.render(content, self.output, photo=picture)
                docx = self.output.with_suffix('.docx')
                resume_docx.write(content, docx, photo=picture)
                fields = resume_pdf.fields_of(content)
                self.assertEqual(resume_pdf.page_count(self.output.read_bytes()), 1)
                self.assertEqual(resume_pdf.check(self.output, fields), [])
                self.assertEqual(resume_docx.check(docx, fields), [])
                self.assertEqual(resume_docx.same_text(self.output, docx, content), [])
                self.assertEqual(resume_photo.check_docx_photo(docx.read_bytes(), picture), [])
                self.assertGreaterEqual(result['spaciness'], resume_pdf.TIGHTEST)

    @classmethod
    def setUpClass(cls):
        if MISSING:  # reached only where they are required
            raise AssertionError(f"JOBSEARCH_CN_REQUIRE_TYPST=1, but {MISSING}")

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp, self.output = temp.name, Path(temp.name) / "out.pdf"

    def stretched(self, times: int) -> dict:
        """The sample with its internship and project entries repeated, as M3-0's stress test."""
        content = copy.deepcopy(resume_pdf.sample())
        for section in content["sections"]:
            if section["title"] in ("实习经历", "项目经历"):
                section["entries"] = [copy.deepcopy(entry) for _ in range(times) for entry in section["entries"]]
        return content

    def compiled(self, content: dict, spaciness: float = 1.0) -> Path:
        typst = resume_pdf.find_typst()
        folder = resume_pdf._build_folder(self.temp + "/" + str(len(os.listdir(self.temp))), content)
        path = folder / "out.pdf"
        path.write_bytes(resume_pdf._compile(folder, typst, resume_pdf._fonts(typst), spaciness))
        return path

    def test_a_material_builds_a_one_page_pdf_and_a_word_version_that_pass_every_check(self):
        fixture = REPO / "tests" / "fixtures" / "cn" / "material" / "tech-m3"
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = cli.main(["resume", "build", str(fixture / "resume-1.json"), "--data-dir", self.temp,
                             "--profile", str(fixture / "profile" / "profile.json")])
        result = json.loads(out.getvalue())
        self.assertEqual((code, result["problems"]), (0, []))
        self.assertEqual(resume_pdf.page_count(Path(result["pdf"]).read_bytes()), 1)
        self.assertTrue(Path(result["docx"]).is_file())

    def test_a_material_without_a_summary_builds_too(self):
        fixture = REPO / "tests" / "fixtures" / "cn" / "material" / "tech-m3"
        record = json.loads((fixture / "resume-1.json").read_text(encoding="utf-8"))
        record["summary"] = None
        path = Path(self.temp) / "resume-2.json"
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = cli.main(["resume", "build", str(path), "--data-dir", self.temp,
                             "--profile", str(fixture / "profile" / "profile.json")])
        result = json.loads(out.getvalue())
        self.assertEqual((code, result["problems"]), (0, []))
        self.assertEqual(resume_pdf.page_count(Path(result["pdf"]).read_bytes()), 1)
        self.assertNotIn("个人简介", "".join(resume_extract.extract_text(Path(result["pdf"])).split()))

    def test_the_pdf_and_the_word_version_of_the_sample_hold_the_same_text(self):
        # #111 P3-1: read whole, the two differ only in whitespace and the entry separator.
        from jobsearch_cn import resume_docx
        content = resume_pdf.sample()
        resume_pdf.render(content, self.output)
        docx = Path(self.temp) / "out.docx"
        resume_docx.write(content, docx)
        self.assertEqual(resume_docx.same_text(self.output, docx, content), [])
        changed = copy.deepcopy(content)
        changed["sections"][1]["entries"][0]["bullets"][0] = "GPA 3.9/4.0"
        resume_docx.write(changed, docx)
        self.assertTrue(resume_docx.same_text(self.output, docx, content))

    def test_a_short_part_of_the_intent_line_is_never_split(self):
        # Seen in a real run: "2026.11.15 起可到岗" broke after the date. Each part up to 20 characters keeps
        # to one line, and " · " stays at the end of the line it follows.
        content = resume_pdf.sample()
        parts = ["后端开发、大模型应用开发（实习）", "深圳、广州", "每周 4 天，可实习 6 个月", "2026.11.15 起可到岗"]
        for extra in ("", "、杭州", "、杭州、成都", "、杭州、成都、武汉", "、杭州、成都、武汉、西安"):
            parts[1] = "深圳、广州" + extra
            content["intent"] = "求职意向：" + " · ".join(parts)
            resume_pdf.render(content, self.output)
            lines = [" ".join(line.split()) for line in resume_extract.extract_text(self.output).splitlines()]
            start = next(index for index, line in enumerate(lines) if line.startswith("求职意向"))
            intent = lines[start:start + 2] if not lines[start + 1].startswith("个人简介") else lines[start:start + 1]
            with self.subTest(extra=extra):
                for part in parts[1:]:
                    self.assertTrue(any(" ".join(part.split()) in line for line in intent), (part, intent))
                self.assertFalse(any(line.startswith("·") for line in intent), intent)

    def test_the_sample_is_one_page_and_passes_every_check(self):
        content = resume_pdf.sample()
        result = resume_pdf.render(content, self.output)
        self.assertEqual(result["spaciness"], resume_pdf.LOOSEST)
        self.assertEqual(resume_pdf.check(self.output, resume_pdf.fields_of(content)), [])
        self.assertEqual(resume_pdf.page_count(self.output.read_bytes()), 1)

    def test_contact_details_are_plain_text(self):
        resume_pdf.render(resume_pdf.sample(), self.output)
        self.assertNotIn(b"/Link", self.output.read_bytes())
        for detail in ("13800000000", "liming@example.com", "github.com/example"):
            self.assertIn(detail, "".join(resume_extract.extract_text(self.output).split()))

    def test_too_long_for_the_loosest_is_tightened_to_one_page(self):
        content = self.stretched(4)
        result = resume_pdf.render(content, self.output)
        self.assertLess(result["spaciness"], resume_pdf.LOOSEST)
        self.assertGreaterEqual(result["spaciness"], resume_pdf.TIGHTEST)
        self.assertEqual(resume_pdf.check(self.output), [])

    def test_too_long_for_the_tightest_writes_nothing(self):
        with self.assertRaisesRegex(resume_pdf.ResumeError, "请删减内容"):
            resume_pdf.render(self.stretched(12), self.output)
        self.assertFalse(self.output.exists())

    def test_content_is_never_read_as_typst_markup(self):
        content = resume_pdf.sample()
        marks = ['#read("/etc/hostname")', '#import "@preview/x:0.1.0": *', "*星号* = _下划线_ $x$ <标签>"]
        sections = {section["title"]: section for section in content["sections"]}
        sections["教育经历"]["entries"][0]["bullets"] = marks
        sections["个人简介"]["text"] = "- 不是列表 #emph[不是强调] = 不是标题"
        content["name"] = "#panic()"
        resume_pdf.render(content, self.output)
        text = "".join(resume_extract.extract_text(self.output).split())
        for mark in [*marks, "#panic()", sections["个人简介"]["text"]]:
            self.assertIn("".join(mark.split()), text)

    def test_a_radical_in_the_content_is_reported(self):
        content = resume_pdf.sample()
        content["name"] = "李⼤明"
        resume_pdf.render(content, self.output)
        self.assertTrue(any("康熙部首" in p for p in resume_pdf.check(self.output)))

    @unittest.skipUnless(PYPDF, "the comparison is with pypdf's reading")
    def test_the_maps_hold_the_same_characters_pypdf_reads(self):
        # The check reads the maps so that it needs no pypdf; where pypdf is here, it must agree.
        content = resume_pdf.sample()
        content["name"] = "李⼤明"
        resume_pdf.render(content, self.output)
        mapped = set(resume_pdf.mapped_text(self.output.read_bytes()))
        self.assertIn("⼤", mapped)
        self.assertEqual(mapped - set(" \n"), set("".join(page_texts(self.output))) - set(" \n"))

    def test_a_section_title_never_ends_a_page(self):
        # Sweeps the length past where the rule used to go over and leave the title behind (M3-0).
        seen_two_pages = False
        for filler in range(40, 56):
            content = resume_pdf.sample()
            content["sections"] = [
                {"title": "填充", "lines": [{"label": "", "rest": f"第{n}行内容"} for n in range(filler)]},
                {"title": "末尾标题", "lines": [{"label": "", "rest": "末尾内容"}]},
            ]
            pages = page_texts(self.compiled(content))
            seen_two_pages = seen_two_pages or len(pages) > 1
            for page in pages[:-1]:
                lines = [line.strip() for line in page.splitlines() if line.strip()]
                with self.subTest(filler=filler):
                    self.assertNotEqual(lines[-1], "末尾标题")
        self.assertTrue(seen_two_pages, "sanity: the sweep must cross a page")


if __name__ == "__main__":
    unittest.main()
