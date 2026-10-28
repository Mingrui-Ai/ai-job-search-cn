"""Read resume text without saving it; optional PDF dependencies stay upstream."""

import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


class ExtractionError(Exception):
    """A resume cannot be read as supported text."""


_WORD_NAMESPACES = (
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://purl.oclc.org/ooxml/wordprocessingml/main",
)
_TOOLS = Path(__file__).resolve().parent.parent / "tools"
_PDF_HELP = "请让 Agent 直接读取 PDF，或者安装 pypdf"

# This fixed bridge runs in the same Python environment, never through a shell.
# Reuse upstream's optional-pypdf extraction and Poppler command/error handling.
# We need text only: unlike extract_text_layer(), this does not also need pdfinfo.
# No --dump-text, temporary files, or optional imports in the CN process.
_PDF_BRIDGE = """\
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from verify_pdf import _extract_pypdf, run_tool
path = Path(sys.argv[2])
result = _extract_pypdf(path)
if result is not None:
    text = result[0]
elif sys.argv[3] == "1":
    text = run_tool(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"])
else:
    raise RuntimeError("No usable PDF text backend")
sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.write(text)
"""


def _word_text(element: ET.Element, namespace: str) -> str:
    """Walk body XML in document order, including tables and content controls."""
    prefix = "{" + namespace + "}"
    if element.tag.startswith(prefix) and element.tag.endswith("Pr"):
        return ""  # Formatting properties can contain tab-stop definitions.
    if element.tag == prefix + "t":
        return element.text or ""
    if element.tag == prefix + "tab":
        return "\t"
    if element.tag in (prefix + "br", prefix + "cr"):
        return "\n"
    if element.tag == prefix + "tr":
        cells = []

        def read_cells(wrapper):
            for child in wrapper:
                if child.tag == prefix + "tc":
                    cells.append(_word_text(child, namespace).rstrip("\n"))
                else:
                    read_cells(child)  # A content control can wrap a table cell.

        read_cells(element)
        return "\t".join(cells) + "\n"
    text = "".join(_word_text(child, namespace) for child in element)
    return text + "\n" if element.tag == prefix + "p" else text


def _extract_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            with archive.open("word/document.xml") as document:
                root = ET.parse(document).getroot()
    except (OSError, zipfile.BadZipFile, KeyError, ET.ParseError, RuntimeError, NotImplementedError):
        raise ExtractionError("无法读取 DOCX 的 word/document.xml；请用 Word 或 WPS 重新另存为 .docx") from None
    for namespace in _WORD_NAMESPACES:
        body = root.find("{" + namespace + "}body")
        if body is not None:
            return _word_text(body, namespace).rstrip("\n")
    raise ExtractionError("DOCX 中没有可读取的文档正文；请重新另存为 .docx")


def _poppler_available() -> bool:
    """Only enable the Poppler fallback, not Git for Windows' xpdf build."""
    try:
        result = subprocess.run(
            ["pdftotext", "-v"], stdin=subprocess.DEVNULL, capture_output=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    banner = (result.stdout + result.stderr).decode("utf-8", "replace").casefold()
    return result.returncode == 0 and "poppler" in banner and "glyph & cog" not in banner


def _pdf_text_is_damaged(text: str) -> bool:
    """Reject substantial replacement/control noise, allowing layout whitespace.

    Three or more bad characters at >=2% of non-whitespace text, or 20 anywhere,
    is substantial. An isolated missing glyph is not enough to reject a resume.
    """
    bad = sum(char == "\ufffd" or (char not in "\t\r\n\f" and
                                  (ord(char) < 32 or 127 <= ord(char) <= 159))
              for char in text)
    nonspace = max(1, sum(not char.isspace() for char in text))
    return bad >= 20 or (bad >= 3 and bad / nonspace >= 0.02)


def _extract_pdf(path: Path) -> str:
    poppler = _poppler_available()
    try:
        result = subprocess.run(
            [sys.executable, "-B", "-c", _PDF_BRIDGE, str(_TOOLS), str(path.resolve()), "1" if poppler else "0"],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ExtractionError(f"无法提取 PDF 文本；{_PDF_HELP}") from None
    # Backend diagnostics can contain resume text; never echo them or log them.
    if result.returncode:
        raise ExtractionError(f"无法提取 PDF 文本；{_PDF_HELP}")
    try:
        text = result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise ExtractionError(f"PDF 提取结果不是 UTF-8 文本；{_PDF_HELP}") from None
    if _pdf_text_is_damaged(text):
        raise ExtractionError(f"PDF 文本含大量替换字符或控制字符；{_PDF_HELP}")
    return text


def extract_text(source: str | Path) -> str:
    """Read a DOCX or PDF path; callers keep the result in memory."""
    path = Path(source)
    if not path.is_file():
        raise ExtractionError(f"文件不存在或不是普通文件：{path}")
    suffix = path.suffix.lower()
    if suffix == ".docx":
        text = _extract_docx(path)
    elif suffix == ".pdf":
        text = _extract_pdf(path)
    else:
        raise ExtractionError(f"不支持 {suffix or '无扩展名'} 格式；请另存为 .docx 后重试")
    if not text.strip():
        if suffix == ".pdf":
            raise ExtractionError(f"PDF 没有可提取的文本层（可能是扫描件）；{_PDF_HELP}")
        raise ExtractionError("DOCX 正文没有可提取的文字；请检查材料后重试")
    return text
