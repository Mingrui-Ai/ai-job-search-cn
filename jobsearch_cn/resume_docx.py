"""Render the resume content to a Word document (.docx), and check it against the PDF.

The content is the flat JSON the PDF is made from (resume_pdf, resume_templates/sample.json), so the
two versions hold the same text. Only the standard library: a .docx is a zip of a few XML parts.
The layout follows the habaneraa template, but only the PDF is kept to one page; Word lays the text
out with its own fonts and may break the page elsewhere (docs/cn/resume-pdf.md).
"""

import io
import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from . import resume_extract

# 等线 is the East Asian font Office has installed since 2016, on Windows and on the Mac alike, so a
# resume opened on either shows the same face. The Noto fonts the PDF uses are not on every machine.
FONT = "等线"

_PAGE_WIDTH, _PAGE_HEIGHT, _MARGIN = 11906, 16838, 850  # twips: A4, 1.5 cm margins
_TEXT_WIDTH = _PAGE_WIDTH - 2 * _MARGIN
_BODY, _SMALL, _TITLE, _NAME = 21, 19, 24, 36  # half-points: 10.5, 9.5, 12 and 18 pt
BULLET = "•"
LABEL_END = "："
# What the document adds around the content's fields; anything else in its text is not from the content.
DECORATIONS = BULLET + LABEL_END

# Not allowed in XML 1.0, so they cannot go into document.xml even escaped.
_NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""
_PACKAGE_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
_DOCUMENT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""


def _styles(font: str) -> str:
    font = escape(font, {'"': "&quot;"})
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{_W}">
<w:docDefaults>
<w:rPrDefault><w:rPr><w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:eastAsia="{font}" w:cs="{font}"/>
<w:sz w:val="{_BODY}"/><w:szCs w:val="{_BODY}"/><w:lang w:val="en-US" w:eastAsia="zh-CN"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
</w:styles>"""


def _run(text: str, bold: bool = False, size: int | None = None) -> str:
    props = ("<w:b/>" if bold else "") + (f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>' if size else "")
    text = escape(_NOT_XML.sub("", text))
    return f'<w:r>{f"<w:rPr>{props}</w:rPr>" if props else ""}<w:t xml:space="preserve">{text}</w:t></w:r>'


def _tab() -> str:
    return "<w:r><w:tab/></w:r>"


def _paragraph(runs: str, props: str = "") -> str:
    return f"<w:p>{f'<w:pPr>{props}</w:pPr>' if props else ''}{runs}</w:p>"


def _bullet(runs: str) -> str:
    return _paragraph(_run(BULLET + " ") + runs, '<w:ind w:left="240" w:hanging="240"/>')


def _entry(entry: dict) -> list:
    # Title at the left margin, subtitle centred, date flush right: the template's resume-entry row.
    stops = (f'<w:tabs><w:tab w:val="center" w:pos="{_TEXT_WIDTH // 2}"/>'
             f'<w:tab w:val="right" w:pos="{_TEXT_WIDTH}"/></w:tabs><w:spacing w:before="60"/>')
    head = _run(entry.get("left", ""), bold=True) + _tab() + _run(entry.get("middle", "")) + _tab()
    head += _run(entry.get("right", ""))
    return [_paragraph(head, stops)] + [_bullet(_run(text)) for text in entry.get("bullets") or []]


def _line(line: dict) -> str:
    label = line.get("label", "")
    return _bullet((_run(label + LABEL_END, bold=True) if label else "") + _run(line.get("rest", "")))


def _section(section: dict) -> list:
    rule = '<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="000000"/></w:pBdr>'
    paragraphs = [_paragraph(_run(section.get("title", ""), bold=True, size=_TITLE),
                             f'{rule}<w:spacing w:before="160" w:after="60"/>')]
    for entry in section.get("entries") or []:
        paragraphs += _entry(entry)
    paragraphs += [_line(line) for line in section.get("lines") or []]
    return paragraphs


def _document(content: dict) -> str:
    paragraphs = [
        _paragraph(_run(content.get("name", ""), bold=True, size=_NAME), '<w:jc w:val="center"/>'),
        _paragraph(_run(content.get("contact", ""), size=_SMALL), '<w:jc w:val="center"/>'),
        _paragraph(_run(content.get("intent", ""), size=_SMALL), '<w:jc w:val="center"/>'),
    ]
    for section in content.get("sections") or []:
        paragraphs += _section(section)
    page = (f'<w:sectPr><w:pgSz w:w="{_PAGE_WIDTH}" w:h="{_PAGE_HEIGHT}"/>'
            f'<w:pgMar w:top="{_MARGIN}" w:right="{_MARGIN}" w:bottom="{_MARGIN}" w:left="{_MARGIN}"'
            ' w:header="0" w:footer="0" w:gutter="0"/></w:sectPr>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<w:document xmlns:w="{_W}"><w:body>{"".join(paragraphs)}{page}</w:body></w:document>')


def build(content: dict, font: str = FONT) -> bytes:
    """The .docx for the content, as bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _PACKAGE_RELS)
        archive.writestr("word/_rels/document.xml.rels", _DOCUMENT_RELS)
        archive.writestr("word/styles.xml", _styles(font))
        archive.writestr("word/document.xml", _document(content))
    return buffer.getvalue()


def _squeezed(text: str) -> str:
    return "".join(text.split())


def check(path: Path, fields=()) -> list:
    """What is wrong with a written .docx, as sentences for the user; empty when nothing is.

    Every field of the content must be in its text, and nothing else may be but the bullets and
    label colons it adds - so the Word version says what the PDF says (resume_pdf.check holds the
    PDF to the same fields).
    """
    try:
        text = _squeezed(resume_extract.extract_text(path))
    except resume_extract.ExtractionError as exc:
        return [f"读不了 Word 版的文字：{exc}"]
    problems = []
    missing = [field for field in fields if _squeezed(field) not in text]
    if missing:
        problems.append(f"Word 版里找不到：{'；'.join(missing)}")
    rest = text
    for field in sorted({_squeezed(field) for field in fields}, key=len, reverse=True):
        rest = rest.replace(field, "")
    extra = "".join(char for char in rest if char not in DECORATIONS)
    if extra:
        problems.append(f"Word 版里有内容之外的文字：{extra[:200]}")
    return problems
