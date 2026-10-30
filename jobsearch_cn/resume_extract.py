"""Read resume text without saving it; optional PDF dependencies stay upstream."""

import io
import os
import signal
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path


class ExtractionError(Exception):
    """A resume cannot be read as supported text."""


_WORD_NAMESPACES = (
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://purl.oclc.org/ooxml/wordprocessingml/main",
)
_TOOLS = Path(__file__).resolve().parent.parent / "tools"
_PDF_HELP = "请让 Agent 直接读取 PDF，或者安装 pypdf"

# Budgets for a file the user points at (H25b). A real resume stays far below them; over one, the
# file is refused in words that quote none of it.
_MAX_INPUT_BYTES = 50 * 1024 * 1024
_MAX_XML_BYTES = 16 * 1024 * 1024  # word/document.xml, uncompressed
_MAX_XML_NODES = 200_000
_MAX_XML_DEPTH = 256
_DOCX_TOO_COMPLEX = "DOCX 的结构过于复杂或内容过大，已停止读取；请用 Word 或 WPS 重新另存为 .docx，或者让 Agent 直接读取"
_PDF_TIMEOUT = 60  # seconds, for the whole process tree
_REAP_TIMEOUT = 5  # seconds to collect the pipes once the tree is dead

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


def _leaf_text(element: ET.Element, prefix: str):
    """The text of an element that is not walked into; None for one that is."""
    if element.tag.startswith(prefix) and element.tag.endswith("Pr"):
        return ""  # Formatting properties can contain tab-stop definitions.
    if element.tag == prefix + "t":
        return element.text or ""
    if element.tag == prefix + "tab":
        return "\t"
    if element.tag in (prefix + "br", prefix + "cr"):
        return "\n"
    return None


def _word_text(body: ET.Element, namespace: str) -> str:
    """Walk body XML in document order, including tables and content controls.

    An explicit stack, not recursion (H25b): a frame is [kind, element, children left, out].
    "text" gathers its pieces in out, a "cell" too, for the row above it; a "row" gathers its
    cells in out, and a "wrap" - a content control can wrap a table cell - shares its row's.
    """
    prefix = "{" + namespace + "}"
    stack = [["text", body, iter(body), []]]
    while True:
        kind, element, children, out = stack[-1]
        child = next(children, None)
        if child is None:
            stack.pop()
            if kind == "wrap":
                continue
            if kind == "cell":
                stack[-1][3].append("".join(out).rstrip("\n"))
                continue
            text = "\t".join(out) + "\n" if kind == "row" else "".join(out)
            text += "\n" if kind == "text" and element.tag == prefix + "p" else ""
            if not stack:
                return text
            stack[-1][3].append(text)
        elif kind in ("row", "wrap"):
            cell = child.tag == prefix + "tc"
            stack.append(["cell" if cell else "wrap", child, iter(child), [] if cell else out])
        else:
            leaf = _leaf_text(child, prefix)
            if leaf is not None:
                out.append(leaf)
            elif child.tag == prefix + "tr":
                stack.append(["row", child, iter(child), []])
            else:
                stack.append(["text", child, iter(child), []])


def _parse_document(data: bytes) -> ET.Element:
    """word/document.xml, parsed within the node and depth budgets."""
    root, depth, nodes = None, 0, 0
    for event, element in ET.iterparse(io.BytesIO(data), events=("start", "end")):
        if event == "end":
            depth -= 1
            continue
        root = element if root is None else root
        depth, nodes = depth + 1, nodes + 1
        if depth > _MAX_XML_DEPTH or nodes > _MAX_XML_NODES:
            raise ExtractionError(_DOCX_TOO_COMPLEX)
    return root


def _extract_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > _MAX_XML_BYTES:
                raise ExtractionError(_DOCX_TOO_COMPLEX)
            with archive.open(info) as document:
                data = document.read(_MAX_XML_BYTES + 1)  # The size in the header can be a lie.
        if len(data) > _MAX_XML_BYTES:
            raise ExtractionError(_DOCX_TOO_COMPLEX)
        root = _parse_document(data)
    except (OSError, EOFError, zlib.error, zipfile.BadZipFile, KeyError, ET.ParseError, RuntimeError,
            NotImplementedError):
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


def _windows_job(process: subprocess.Popen):
    """A Job Object holding process, or None if Windows refuses one.

    What process starts later joins the job, and terminating or closing the job ends them all,
    so pdftotext goes with the bridge. The bridge is our own Python, which takes far longer to
    start than the call below, so it cannot start anything before it is assigned.
    """
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [("per_process_time", ctypes.c_int64), ("per_job_time", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                    ("max_working_set", ctypes.c_size_t), ("process_limit", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", BasicLimits), ("io_counters", ctypes.c_uint64 * 6),
                    ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                    ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if (kernel32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))  # ExtendedLimitInformation
            and kernel32.AssignProcessToJobObject(job, int(process._handle))):
        return kernel32, job
    kernel32.CloseHandle(job)
    return None


def _kill_tree(process: subprocess.Popen, job) -> None:
    """End process and everything it started: the job on Windows, the session on POSIX."""
    try:
        if job is not None:
            job[0].TerminateJobObject(job[1], 1)
        elif os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        process.kill()
    except OSError:
        pass  # Already gone.


def _run_tree(command: list, timeout: float) -> subprocess.CompletedProcess:
    """subprocess.run with its output captured and a timeout that holds for the whole process tree.

    subprocess.run kills only its child, then waits for the pipes the grandchildren inherited, so
    a stuck pdftotext outlived the timeout and held it open (H25b). tools/verify_pdf.py stays as
    upstream wrote it: the tree is contained from here.
    """
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=os.name == "posix")
    job = _windows_job(process) if os.name == "nt" else None
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    except BaseException:
        _kill_tree(process, job)
        try:
            process.communicate(timeout=_REAP_TIMEOUT)
        except (subprocess.TimeoutExpired, ValueError, OSError):
            pass  # Something outside the tree holds a pipe; the caller is not kept waiting for it.
        raise
    finally:
        if job is not None:
            job[0].CloseHandle(job[1])


def _extract_pdf(path: Path) -> str:
    poppler = _poppler_available()
    try:
        result = _run_tree(
            [sys.executable, "-B", "-c", _PDF_BRIDGE, str(_TOOLS), str(path.resolve()), "1" if poppler else "0"],
            _PDF_TIMEOUT,
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
    if path.stat().st_size > _MAX_INPUT_BYTES:
        raise ExtractionError(f"文件超过 {_MAX_INPUT_BYTES // (1024 * 1024)} MB，不像一份简历；请确认文件后重试")
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
