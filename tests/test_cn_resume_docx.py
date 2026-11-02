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


if __name__ == "__main__":
    unittest.main()
