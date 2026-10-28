"""H11: generated resumes only; never read a candidate's real material."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from jobsearch_cn import resume_extract


REPO = Path(__file__).resolve().parent.parent
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
PDF_AVAILABLE = importlib.util.find_spec("pypdf") is not None or shutil.which("pdftotext") is not None


def make_docx(path, body, namespace=WORD_NS):
    xml = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{namespace}"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml.encode("utf-8"))


def paragraph(text):
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def make_pdf(path):
    """Small synthetic Unicode PDF with a text layer, built using stdlib only.

    A ToUnicode CMap makes extraction independent of installed Chinese fonts.
    The page contains two paragraphs and a two-column education row.
    """
    fragments = [(50, 780, "合成简历"), (50, 750, "项目经历：样例服务"),
                 (50, 710, "示例大学"), (250, 710, "计算机本科")]
    characters = sorted(set("".join(text for _, _, text in fragments)))
    mappings = "\n".join(f"<{ord(c):04X}> <{c.encode('utf-16-be').hex().upper()}>" for c in characters)
    cmap = ("/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
            "/CMapName /SyntheticUnicode def\n/CMapType 2 def\n"
            "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
            f"{len(characters)} beginbfchar\n{mappings}\nendbfchar\n"
            "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n").encode("ascii")
    content = "\n".join(f"BT /F1 12 Tf 1 0 0 1 {x} {y} Tm <{text.encode('utf-16-be').hex()}> Tj ET"
                        for x, y, text in fragments).encode("ascii")

    def stream(data):
        return f"<< /Length {len(data)} >>\nstream\n".encode("ascii") + data + b"\nendstream"

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 7 0 R >>",
        b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-H /DescendantFonts [5 0 R] /ToUnicode 6 0 R >>",
        b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light /CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> /FontDescriptor 8 0 R /DW 1000 >>",
        stream(cmap), stream(content),
        b"<< /Type /FontDescriptor /FontName /STSong-Light /Flags 6 /FontBBox [-25 -254 1000 880] /ItalicAngle 0 /Ascent 880 /Descent -120 /CapHeight 880 /StemV 80 >>",
    ]
    data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    path.write_bytes(data)


class ResumeExtract(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.sources = self.root / "data" / "profile" / "sources"
        self.sources.mkdir(parents=True)
        (self.sources.parent / "profile.json").write_text('{"sentinel": "unchanged"}', encoding="utf-8")

    def cli(self, file, **env_overrides):
        env = dict(os.environ, PYTHONPATH=str(REPO), PYTHONDONTWRITEBYTECODE="1",
                   PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
        env.update(env_overrides)
        return subprocess.run([sys.executable, "-B", "-m", "jobsearch_cn", "profile", "extract", str(file)],
                              cwd=self.root, env=env, capture_output=True)

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() if p.is_file() else None
                for p in self.root.rglob("*")}

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stderr, b"")
        return json.loads(result.stdout.decode("utf-8"))

    def assert_failure(self, result, message):
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(message, json.loads(result.stderr.decode("utf-8"))["error"])
        self.assertNotIn(b"Traceback", result.stderr)

    def test_docx_paragraphs_tables_and_runs_keep_document_order_without_writes(self):
        path = self.sources / "合成 简历.DOCX"
        body = ("<w:p><w:pPr><w:tabs><w:tab w:val='left' w:pos='720'/></w:tabs></w:pPr>"
                "<w:r><w:t>合成</w:t></w:r><w:hyperlink><w:r><w:t>简历</w:t></w:r></w:hyperlink></w:p>"
                "<w:tbl><w:tr><w:tc>" + paragraph("学校") + "</w:tc><w:tc>" + paragraph("专业") + "</w:tc></w:tr>"
                "<w:tr><w:tc>" + paragraph("示例大学") + paragraph("2024-2028") + "</w:tc><w:sdt><w:sdtContent><w:tc>" + paragraph("计算机") + "</w:tc></w:sdtContent></w:sdt></w:tr></w:tbl>"
                "<w:sdt><w:sdtContent>" + paragraph("项目经历") + "</w:sdtContent></w:sdt>"
                "<w:p><w:r><w:t>Python</w:t><w:tab/><w:t>服务开发</w:t><w:br/><w:t>合作完成</w:t></w:r></w:p>"
                + paragraph("结束"))
        make_docx(path, body)
        before = self.snapshot()
        result = self.assert_success(self.cli(path.relative_to(self.root)))
        self.assertEqual(result, {"source": path.name, "text": "合成简历\n学校\t专业\n示例大学\n2024-2028\t计算机\n项目经历\nPython\t服务开发\n合作完成\n结束"})
        self.assertEqual(self.snapshot(), before, "extraction must not save dumps, profiles, or logs")

    def test_strict_docx_namespace(self):
        path = self.sources / "strict.docx"
        make_docx(path, paragraph("严格格式简历"), "http://purl.oclc.org/ooxml/wordprocessingml/main")
        self.assertEqual(self.assert_success(self.cli(path))["text"], "严格格式简历")

    def test_rejects_old_doc_and_other_formats(self):
        for name in ("old.doc", "resume.rtf", "resume.txt", "resume.docm", "resume"):
            with self.subTest(name=name):
                path = self.sources / name
                path.write_bytes(b"synthetic unsupported input")
                before = self.snapshot()
                self.assert_failure(self.cli(path), "另存为 .docx")
                self.assertEqual(self.snapshot(), before)

    def test_missing_file_and_directory(self):
        self.assert_failure(self.cli(self.sources / "missing.docx"), "文件不存在")
        self.assert_failure(self.cli(self.sources), "不是普通文件")

    def test_corrupt_docx_or_missing_document_is_a_clean_input_error(self):
        path = self.sources / "broken.docx"
        path.write_bytes(b"not a zip file")
        self.assert_failure(self.cli(path), "无法读取 DOCX")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/header1.xml", "unused")
        self.assert_failure(self.cli(path), "word/document.xml")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", "<broken>")
        self.assert_failure(self.cli(path), "无法读取 DOCX")

    def test_empty_docx_is_not_a_successful_resume(self):
        path = self.sources / "empty.docx"
        make_docx(path, "<w:p/>")
        self.assert_failure(self.cli(path), "没有可提取的文字")

    @unittest.skipUnless(PDF_AVAILABLE, "PDF extraction needs pypdf or pdftotext")
    def test_synthetic_pdf_chinese_paragraphs_and_table_without_writes(self):
        path = self.sources / "合成 简历.pdf"
        make_pdf(path)
        before = self.snapshot()
        payload = self.assert_success(self.cli(path.relative_to(self.root)))
        self.assertEqual(payload["source"], path.name)
        text = payload["text"]
        terms = ["合成简历", "项目经历：样例服务", "示例大学", "计算机本科"]
        for term in terms:
            self.assertIn(term, text)
        self.assertEqual([text.index(t) for t in terms], sorted(text.index(t) for t in terms))
        self.assertEqual(self.snapshot(), before)

    def block_pypdf(self):
        stub = self.root / "unavailable"
        stub.mkdir()
        (stub / "pypdf.py").write_text('raise ImportError("disabled for synthetic test")\n', encoding="utf-8")
        return os.pathsep.join((str(stub), str(REPO)))

    def test_pdf_without_either_backend_gives_actionable_error_and_no_output_file(self):
        path = self.sources / "unavailable.pdf"
        make_pdf(path)
        pythonpath = self.block_pypdf()
        before = self.snapshot()
        proc = self.cli(path, PYTHONPATH=pythonpath, PATH="")
        self.assert_failure(proc, "请让 Agent 直接读取 PDF，或者安装 pypdf")
        self.assertEqual(self.snapshot(), before)

    @unittest.skipUnless(shutil.which("pdftotext"), "Poppler fallback requires pdftotext")
    def test_pdf_falls_back_to_pdftotext_when_pypdf_is_absent(self):
        path = self.sources / "fallback.pdf"
        make_pdf(path)
        payload = self.assert_success(self.cli(path, PYTHONPATH=self.block_pypdf()))
        self.assertIn("合成简历", payload["text"])

    def test_backend_failure_never_echoes_resume_text_in_diagnostics(self):
        path = self.sources / "error.pdf"
        make_pdf(path)
        result = subprocess.CompletedProcess([], 1, b"private resume fragment", b"sensitive diagnostic")
        with patch.object(resume_extract.subprocess, "run", return_value=result):
            with self.assertRaises(resume_extract.ExtractionError) as caught:
                resume_extract.extract_text(path)
        self.assertNotIn("private", str(caught.exception))
        self.assertNotIn("sensitive", str(caught.exception))

    def test_empty_pdf_text_layer_has_direct_read_guidance(self):
        path = self.sources / "scan.pdf"
        make_pdf(path)
        with patch.object(resume_extract.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"\n\f", b"")):
            with self.assertRaisesRegex(resume_extract.ExtractionError, "没有可提取的文本层"):
                resume_extract.extract_text(path)

    def test_pdf_backend_timeout_is_an_input_error(self):
        path = self.sources / "timeout.pdf"
        make_pdf(path)
        with patch.object(resume_extract.subprocess, "run", side_effect=subprocess.TimeoutExpired("python", 60)):
            with self.assertRaisesRegex(resume_extract.ExtractionError, "请让 Agent 直接读取 PDF"):
                resume_extract.extract_text(path)


if __name__ == "__main__":
    unittest.main()
