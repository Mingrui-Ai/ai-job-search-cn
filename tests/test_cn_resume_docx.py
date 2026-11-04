"""Tests for jobsearch_cn/resume_docx.py (M3-2, second part): the Word version of the resume.

The Word version must say what the PDF says, so these pin: the sample content gives a .docx that
resume_extract reads; every field is in it and nothing else but the bullets and label colons; text
that means something in XML stays text; and check() reports a field that is missing, text that is not
the content's, and a file that is no .docx. Opening it in Word or WPS is checked by hand (worklog).
"""
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from jobsearch_cn import resume_docx, resume_extract, resume_pdf  # noqa: E402

SAMPLE = resume_pdf.sample()
FIELDS = resume_pdf.fields_of(SAMPLE)


class Build(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "resume.docx"

    def write(self, content: dict) -> Path:
        self.path.write_bytes(resume_docx.build(content))
        return self.path

    def test_the_sample_passes_its_own_check(self):
        self.assertEqual(resume_docx.check(self.write(SAMPLE), FIELDS), [])

    def test_every_part_is_well_formed_xml(self):
        with zipfile.ZipFile(BytesIO(resume_docx.build(SAMPLE))) as archive:
            self.assertEqual(sorted(archive.namelist()), ["[Content_Types].xml", "_rels/.rels",
                                                          "word/_rels/document.xml.rels", "word/document.xml",
                                                          "word/styles.xml"])
            for name in archive.namelist():
                with self.subTest(part=name):
                    ET.fromstring(archive.read(name))

    def test_the_font_is_set_for_chinese_and_latin_text(self):
        with zipfile.ZipFile(BytesIO(resume_docx.build(SAMPLE))) as archive:
            styles = archive.read("word/styles.xml").decode("utf-8")
        for attribute in ("ascii", "hAnsi", "eastAsia"):
            self.assertIn(f'w:{attribute}="{resume_docx.FONT}"', styles)

    def test_the_text_reads_in_the_order_of_the_content(self):
        text = resume_extract.extract_text(self.write(SAMPLE))
        lines = text.split("\n")
        self.assertEqual(lines[:6], [SAMPLE["name"], SAMPLE["contact"], SAMPLE["intent"],
                                     "个人简介", SAMPLE["sections"][0]["text"], "教育经历"])
        self.assertIn("示例理工大学\t计算机科学与技术 · 硕士\t2025.09 - 2027.06", lines)
        self.assertIn(f"{resume_docx.BULLET} 熟练：Python、Go", lines)
        self.assertIn(f"{resume_docx.BULLET} CET-6 552", lines)  # a line without a label has no colon

    def test_markup_characters_stay_text(self):
        content = {**SAMPLE, "intent": 'R&D <后端> "实习" \x07'}
        text = resume_extract.extract_text(self.write(content))
        self.assertIn('R&D <后端> "实习" ', text)


class Check(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "resume.docx"
        self.path.write_bytes(resume_docx.build(SAMPLE))

    def test_a_field_missing_from_the_document(self):
        problems = resume_docx.check(self.path, FIELDS + ["熟悉 Kubernetes"])
        self.assertEqual(problems, ["Word 版里找不到：熟悉 Kubernetes"])

    def test_text_that_is_not_the_contents(self):
        problems = resume_docx.check(self.path, [field for field in FIELDS if field != "CET-6 552"])
        self.assertEqual(problems, ["Word 版里有内容之外的文字：CET-6552"])

    def test_a_file_that_is_no_docx(self):
        self.path.write_bytes(b"not a zip")
        [problem] = resume_docx.check(self.path, FIELDS)
        self.assertTrue(problem.startswith("读不了 Word 版的文字："), problem)


class SameText(unittest.TestCase):
    """same_text holds the PDF and the Word version to each other, read whole (#111 P3-1)."""

    CONTENT = {"name": "李明", "contact": "", "intent": "求职意向：后端 · 深圳", "sections": [
        {"title": "教育经历", "entries": [
            {"left": "示例大学", "middle": "软件工程 · 本科", "right": "2021.09 - 2025.06", "bullets": ["GPA 3.6"]},
            {"left": "课程项目", "middle": "", "right": "2025.10", "bullets": []}]}]}
    # As the PDF template prints it: " · " after each title with a subtitle, and line breaks anywhere.
    PDF = ("李明\n求职意向：后端 · 深\n圳\n教育经历\n示例大学 · 软件工程 · 本科 2021.09 - 2025.06\n• GPA 3.6\n"
           "课程项目 2025.10")
    DOCX = "李明\n\n求职意向：后端 · 深圳\n教育经历\n示例大学\t软件工程 · 本科\t2021.09 - 2025.06\n• GPA 3.6\n课程项目\t\t2025.10"

    def same(self, pdf: str, docx: str, content: dict = None) -> list:
        texts = {"resume.pdf": pdf, "resume.docx": docx}
        with mock.patch.object(resume_extract, "extract_text", side_effect=lambda path: texts[path.name]):
            return resume_docx.same_text(Path("resume.pdf"), Path("resume.docx"), content or self.CONTENT)

    def test_whitespace_and_one_separator_per_entry_with_a_subtitle_are_allowed(self):
        self.assertEqual(self.same(self.PDF, self.DOCX), [])

    def test_any_other_difference_is_reported_where_it_starts(self):
        problems = self.same(self.PDF, self.DOCX.replace("GPA 3.6", "GPA 3.8"))
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("PDF 和 Word 版的全文不一致：PDF「"), problems[0])
        self.assertIn("GPA3.6", problems[0])
        self.assertIn("GPA3.8", problems[0])
        # Order counts too: the same fields in another order are not the same text.
        swapped = self.DOCX.replace("• GPA 3.6\n课程项目\t\t2025.10", "课程项目\t\t2025.10\n• GPA 3.6")
        self.assertTrue(self.same(self.PDF, swapped))

    def test_a_separator_more_or_less_than_the_entries_explain_is_reported(self):
        # One the PDF lacks: an entry printed without its separator.
        self.assertIn("按条目应当多 1 个",
                      self.same(self.PDF.replace("示例大学 · 软件", "示例大学 软件"), self.DOCX)[0])
        # One the content does not explain: an entry with an empty subtitle gets none in the PDF.
        self.assertTrue(self.same(self.PDF.replace("课程项目 2025", "课程项目 · 2025"), self.DOCX))

    def test_a_file_that_cannot_be_read_is_left_to_the_other_checks(self):
        with mock.patch.object(resume_extract, "extract_text", side_effect=resume_extract.ExtractionError("坏了")):
            self.assertEqual(resume_docx.same_text(Path("a.pdf"), Path("a.docx"), self.CONTENT), [])


if __name__ == "__main__":
    unittest.main()
