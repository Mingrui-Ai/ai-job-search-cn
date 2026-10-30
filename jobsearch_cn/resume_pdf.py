"""Render a Chinese one-page resume to PDF with Typst, and check the result.

Typst is an external program, called with subprocess like pdftotext in
resume_extract (ADR-4): this module imports only the standard library, and the
template is package data that imports nothing from the network. Install notes:
docs/cn/resume-pdf.md.

The content goes to Typst as JSON, never spliced into markup, so nothing in it
needs escaping. Word output and the material format are M3-2's second part.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

from . import resume_extract

TYPST_ENV = "JOBSEARCH_CN_TYPST"
MIN_TYPST = (0, 13)  # the compiler habaneraa's typst.toml declares
TYPST_HELP = "安装方法见 docs/cn/resume-pdf.md（便携版，不要管理员权限）"
_TOOL_TIMEOUT = 30  # seconds
_COMPILE_TIMEOUT = 120

TEMPLATE = Path(__file__).resolve().parent / "resume_templates" / "habaneraa"
SAMPLE = TEMPLATE.parent / "sample.json"
VERIFY_PDF = Path(__file__).resolve().parent.parent / "tools" / "verify_pdf.py"

# Tried in order. Noto and Source Han are one design under two names; 微软雅黑 is for an
# older Windows without Noto (M3-0).
SERIF_FONTS = ("Noto Serif SC", "Noto Serif CJK SC", "Source Han Serif SC", "Microsoft YaHei")
SANS_FONTS = ("Noto Sans SC", "Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei")

# element-spaciness scales the margins, line and paragraph spacing together. M3-0 found these
# bounds, and that six halvings of them settle it to about 0.01.
LOOSEST, TIGHTEST = 1.5, 0.8
_HALVINGS = 6

# Look like 大 and 用 on the page, but a search or an ATS does not find them (M3-0).
RADICALS = ((0x2E80, 0x2FDF),)
# Icon fonts. nerd-icons' Material Design set sits in the supplementary planes.
PRIVATE_USE = ((0xE000, 0xF8FF), (0xF0000, 0xFFFFD), (0x100000, 0x10FFFD))


class ResumeError(Exception):
    """The PDF could not be made; the message says what to do."""


def find_typst(explicit: str | None = None) -> str:
    """The Typst program: an explicit path, else $JOBSEARCH_CN_TYPST, else typst on PATH."""
    chosen = explicit or os.environ.get(TYPST_ENV) or "typst"
    path = shutil.which(chosen)
    if not path:
        raise ResumeError(f"找不到 Typst（{chosen}）；{TYPST_HELP}")
    version = _typst_version(path)
    if version < MIN_TYPST:
        raise ResumeError(f"Typst 版本太旧（{'.'.join(map(str, version))}），至少要 "
                          f"{'.'.join(map(str, MIN_TYPST))}；{TYPST_HELP}")
    return path


def _run(command: list, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _typst_version(path: str) -> tuple:
    try:
        result = _run([path, "--version"], _TOOL_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        raise ResumeError(f"运行不了 Typst（{path}）；{TYPST_HELP}") from None
    found = re.match(r"typst (\d+)\.(\d+)", result.stdout)
    if result.returncode or not found:
        raise ResumeError(f"{path} 看起来不是 Typst；{TYPST_HELP}")
    return int(found.group(1)), int(found.group(2))


def _pick_font(available: set, families: tuple) -> str:
    for family in families:
        if family in available:
            return family
    raise ResumeError(f"没有可用的中文字体，请安装其中一款：{'、'.join(families)}（见 docs/cn/resume-pdf.md）")


def _fonts(typst: str) -> dict:
    """The families for this machine. Typst only warns about a missing one and prints empty boxes."""
    try:
        listed = _run([typst, "fonts"], _COMPILE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        raise ResumeError(f"Typst 列不出字体；{TYPST_HELP}") from None
    available = {line.strip() for line in listed.stdout.splitlines()}
    return {"serif": _pick_font(available, SERIF_FONTS), "sans": _pick_font(available, SANS_FONTS)}


def page_count(data: bytes) -> int:
    """Pages in a PDF Typst wrote. It keeps page objects out of object streams, which is checked."""
    if b"/ObjStm" in data:
        raise ResumeError("PDF 用了对象流，数不了页数；可能是 Typst 版本变了，请告诉维护者")
    return len(re.findall(rb"/Type\s*/Page(?![A-Za-z])", data))


def _compile(folder: Path, typst: str, fonts: dict, spaciness: float) -> bytes:
    out = folder / "resume.pdf"
    # Empty package folders: the template imports no package, and none could be fetched or found.
    command = [typst, "compile", "--root", str(folder),
               "--package-path", str(folder / "no-packages"), "--package-cache-path", str(folder / "no-packages"),
               "--input", f"spaciness={spaciness}", "--input", f"serif={fonts['serif']}",
               "--input", f"sans={fonts['sans']}", str(folder / "main.typ"), str(out)]
    try:
        result = _run(command, _COMPILE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        raise ResumeError(f"Typst 没有在 {_COMPILE_TIMEOUT} 秒内编译完") from None
    if result.returncode:
        raise ResumeError(f"Typst 编译失败：{result.stderr.strip()[:500]}")
    return out.read_bytes()


def _fit(compile_at) -> tuple:
    """(spaciness, pdf bytes) for the loosest spacing that fits one page; M3-0's halving."""
    loose = compile_at(LOOSEST)
    if page_count(loose) == 1:
        return LOOSEST, loose
    best = compile_at(TIGHTEST)
    pages = page_count(best)
    if pages > 1:
        raise ResumeError(f"内容太多：间距调到最紧（{TIGHTEST}）还有 {pages} 页，请删减内容")
    low, high = TIGHTEST, LOOSEST
    for _ in range(_HALVINGS):
        middle = round((low + high) / 2, 3)
        attempt = compile_at(middle)
        if page_count(attempt) == 1:
            low, best = middle, attempt
        else:
            high = middle
    return low, best


def _build_folder(temp: str, content: dict) -> Path:
    """A copy of the template with the content beside it: Typst reads only inside --root."""
    folder = Path(temp) / "build"
    shutil.copytree(TEMPLATE, folder)
    (folder / "no-packages").mkdir()
    (folder / "resume.json").write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    return folder


def render(content: dict, output: Path, typst: str | None = None) -> dict:
    """Write content to output as a one-page PDF; nothing is written when it does not fit."""
    program = find_typst(typst)
    fonts = _fonts(program)
    with tempfile.TemporaryDirectory(prefix="jobsearch-cn-resume-") as temp:
        folder = _build_folder(temp, content)
        spaciness, data = _fit(lambda value: _compile(folder, program, fonts, value))
    output.write_bytes(data)
    return {"pdf": str(output), "spaciness": spaciness, "fonts": fonts}


def fields_of(content) -> list:
    """Every string in the content, the unit a text layer is compared by."""
    if isinstance(content, str):
        return [content] if content.strip() else []
    items = content.values() if isinstance(content, dict) else content if isinstance(content, list) else ()
    return [field for item in items for field in fields_of(item)]


def _streams(data: bytes):
    for found in re.finditer(rb"stream\r?\n", data):
        end = data.find(b"endstream", found.end())
        try:
            yield zlib.decompress(data[found.end():end])
        except zlib.error:
            continue


def _bfrange_targets(block: str):
    for low, high, target in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
        for step in range(int(high, 16) - int(low, 16) + 1):
            yield f"{int(target, 16) + step:0{len(target)}X}"
    for array in re.findall(r"\[([^\]]*)\]", block):
        yield from re.findall(r"<([0-9A-Fa-f]+)>", array)


def mapped_text(data: bytes) -> str | None:
    """What the fonts' ToUnicode maps turn glyphs into, or None when the PDF has no such map.

    A text layer is what an ATS reads, but only pypdf shows it raw: pdftotext folds radicals back
    to ideographs, and pypdf is optional. The maps need neither, and are the source of both.
    """
    chars, seen = [], False
    for stream in _streams(data):
        if b"begincmap" not in stream:
            continue
        seen, text = True, stream.decode("latin-1")
        targets = [pair[1] for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S)
                   for pair in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block)]
        targets += [target for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S)
                    for target in _bfrange_targets(block)]
        chars += [bytes.fromhex(target).decode("utf-16-be", "replace") for target in targets if len(target) % 2 == 0]
    return "".join(chars) if seen else None


def _in_ranges(char: str, ranges) -> bool:
    return any(low <= ord(char) <= high for low, high in ranges)


def _verify_pdf(path: Path) -> list:
    """Page count, text layer and ASCII date ranges, by the upstream tool."""
    try:
        result = _run([sys.executable, str(VERIFY_PDF), str(path), "--pages", "1", "--ascii-dates"], _COMPILE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return ["verify_pdf 没有运行完"]
    return [f"verify_pdf：{result.stderr.strip()[:500]}"] if result.returncode else []


def check(path: Path, fields=()) -> list:
    """What is wrong with a rendered PDF, as sentences for the user; empty when nothing is."""
    data = path.read_bytes()
    problems = _verify_pdf(path)
    mapped = mapped_text(data)
    if mapped is None:
        problems.append("PDF 里没有 ToUnicode 映射，查不了康熙部首和私用区字符")
    else:
        radicals = sorted({char for char in mapped if _in_ranges(char, RADICALS)})
        if radicals:
            problems.append(f"文本层有康熙部首或部首补充字符：{' '.join(radicals)}，搜索和 ATS 对不上；换一款字体")
        private = sorted({char for char in mapped if _in_ranges(char, PRIVATE_USE)})
        if private:
            problems.append(f"文本层有私用区字符（图标字体）：{' '.join(f'U+{ord(c):04X}' for c in private)}")
    if re.search(rb"/Subtype\s*/Type3", data):
        problems.append("PDF 里有 Type 3 字体，文本层可能读不出来")
    try:
        text = "".join(resume_extract.extract_text(path).split())
    except resume_extract.ExtractionError as exc:
        return [*problems, f"读不了文本层：{exc}"]
    missing = [field for field in fields if "".join(field.split()) not in text]
    if missing:
        problems.append(f"文本层里找不到：{'；'.join(missing)}")
    return problems


def sample() -> dict:
    """The fixed fictional content this part renders until the material format exists (M3-1)."""
    return json.loads(SAMPLE.read_text(encoding="utf-8"))
