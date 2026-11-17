"""Fixed six-part photo DOCX validation, from one immutable container snapshot.

This is deliberately narrower than a general Office reader. No extraction, network or repair.
"""
import io
import re
import struct
import xml.etree.ElementTree as ET
import zipfile
import zlib

from . import resume_photo as photo

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "rels": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
}
PART_LIMITS = {
    "[Content_Types].xml": 32 * 1024,
    "_rels/.rels": 32 * 1024,
    "word/document.xml": 1024 * 1024,
    "word/styles.xml": 64 * 1024,
    "word/_rels/document.xml.rels": 32 * 1024,
    "word/media/portrait.png": photo.PNG_LIMIT,
}
TOTAL_LIMIT = 7 * 1024 * 1024
NODE_LIMIT, DEPTH_LIMIT = 50000, 64


def q(name):
    prefix, local = name.split(":")
    return "{" + NS[prefix] + "}" + local


def drawing_xml(asset) -> str:
    cx, cy = photo.dimensions_emu(asset.width_px, asset.height_px)
    return f'''<w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">
<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="1" name="Resume photo" descr="Resume photo"/>
<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>
<a:graphic><a:graphicData uri="{NS['pic']}"><pic:pic>
<pic:nvPicPr><pic:cNvPr id="0" name="Resume photo"/><pic:cNvPicPr><a:picLocks noChangeAspect="1"/></pic:cNvPicPr></pic:nvPicPr>
<pic:blipFill><a:blip r:embed="rId2"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>
<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing>'''


def _fail(code):
    raise photo.PhotoError("outputs.docx.photo: photo." + code)


def _directory(data: bytes):
    # Check the EOCD before ZipFile can allocate objects for a large central directory.
    if len(data) < 22 or data[-22:-18] != b"PK\x05\x06":
        _fail("invalid_zip")
    disk, central_disk, here, total, size, offset, comment = struct.unpack_from("<4H2IH", data, len(data) - 18)
    if (disk or central_disk or here != 6 or total != 6 or comment or size > 16384
            or offset + size != len(data) - 22):
        _fail("zip_budget")
    cursor = offset
    for _ in range(6):
        if cursor + 46 > len(data) - 22 or data[cursor:cursor + 4] != b"PK\x01\x02":
            _fail("invalid_zip")
        name_len, extra_len, comment_len, start_disk = struct.unpack_from("<4H", data, cursor + 28)
        if extra_len or comment_len or start_disk:
            _fail("unsupported_zip")
        cursor += 46 + name_len
    if cursor != offset + size:
        _fail("invalid_zip")
    return offset


def _local_headers(data, infos, central_start):
    spans, payloads = [], {}
    for info in infos:
        pos = info.header_offset
        if pos < 0 or pos + 30 > central_start or data[pos:pos + 4] != b"PK\x03\x04":
            _fail("invalid_zip")
        _, flags, method, _, _, crc, packed, size, nlen, elen = struct.unpack_from("<5H3I2H", data, pos + 4)
        start = pos + 30 + nlen + elen
        end = start + info.compress_size
        payloads[info.filename] = (start, end)
        if (elen or flags != info.flag_bits or method != info.compress_type or start > central_start
                or end > central_start or data[pos + 30:pos + 30 + nlen] != info.filename.encode("utf-8")):
            _fail("invalid_zip")
        if flags & 8:
            marker = 4 if data[end:end + 4] == b"PK\x07\x08" else 0
            if end + marker + 12 > central_start:
                _fail("invalid_zip")
            if struct.unpack_from("<3I", data, end + marker) != (info.CRC, info.compress_size, info.file_size):
                _fail("invalid_zip")
            end += marker + 12
        elif (crc, packed, size) != (info.CRC, info.compress_size, info.file_size):
            _fail("invalid_zip")
        spans.append((pos, end))
    # Our fixed package has no prefix, hidden local files, gaps, or overlapping ranges.
    cursor = 0
    for start, end in sorted(spans):
        if start != cursor:
            _fail("invalid_zip")
        cursor = end
    if cursor != central_start:
        _fail("invalid_zip")
    return payloads


def _parts(data):
    central = _directory(data)
    parts, total = {}, 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) != 6 or {i.filename for i in infos} != set(PART_LIMITS):
            _fail("invalid_parts")
        for info in infos:
            if (info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    or info.flag_bits & ~(8 | 2048) or info.extra or info.comment
                    or info.extract_version >= 45 or info.file_size > PART_LIMITS[info.filename]):
                _fail("part_budget")
        payloads = _local_headers(data, infos, central)
        for info in infos:
            limit, count, blocks, crc = PART_LIMITS[info.filename], 0, [], 0
            start, end = payloads[info.filename]
            remaining = data[start:end]
            decoder = zlib.decompressobj(-15) if info.compress_type == zipfile.ZIP_DEFLATED else None
            # ZipExtFile truncates output to the declared file_size. Decode the complete bounded
            # compressed span ourselves so a forged smaller size/CRC cannot hide a suffix or bomb.
            while remaining:
                size = min(65536, limit - count + 1)
                if decoder is None:
                    block, remaining = remaining[:size], remaining[size:]
                else:
                    block = decoder.decompress(remaining, size)
                    remaining = decoder.unconsumed_tail
                    if decoder.unused_data:
                        _fail("invalid_zip")
                count += len(block)
                total += len(block)
                if count > limit or total > TOTAL_LIMIT:
                    _fail("part_budget")
                crc = zlib.crc32(block, crc)
                blocks.append(block)
            if count != info.file_size or crc != info.CRC or (decoder is not None and not decoder.eof):
                _fail("invalid_zip")
            parts[info.filename] = b"".join(blocks)
    return parts


def _xml(data: bytes, budget: list):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        _fail("invalid_xml")
    if "\x00" in text or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        _fail("invalid_xml")
    declaration = re.match(r"\ufeff?<\?xml\s+(.*?)\?>", text, re.S)
    if declaration:
        encoding = re.search(r"encoding\s*=\s*(['\"])(.*?)\1", declaration[1])
        if encoding and encoding[2].upper() != "UTF-8":
            _fail("invalid_xml")
    depth = 0
    iterator = ET.iterparse(io.BytesIO(data), events=("start", "end"))
    for event, _ in iterator:
        if event == "start":
            depth += 1
            budget[0] += 1
            if depth > DEPTH_LIMIT or budget[0] > NODE_LIMIT:
                _fail("xml_budget")
        else:
            depth -= 1
    return iterator.root


def _relationships(root, expected):
    if root.tag != q("rels:Relationships") or root.attrib or len(root) != len(expected):
        _fail("invalid_relationships")
    seen = set()
    for item in root:
        attrs = dict(item.attrib)
        if attrs.pop("TargetMode", "Internal") != "Internal":
            _fail("invalid_relationships")
        ident = attrs.get("Id")
        if (item.tag != q("rels:Relationship") or len(item) or ident in seen
                or ident not in expected or attrs != expected[ident]):
            _fail("invalid_relationships")
        seen.add(ident)


def _tree(node):
    return node.tag, node.attrib, (node.text or "").strip(), tuple(_tree(child) for child in node)


def _structure(roots, asset):
    ct = roots["[Content_Types].xml"]
    content_types = {
        (q("ct:Default"), ("Extension", "rels"), ("ContentType", "application/vnd.openxmlformats-package.relationships+xml")),
        (q("ct:Default"), ("Extension", "xml"), ("ContentType", "application/xml")),
        (q("ct:Default"), ("Extension", "png"), ("ContentType", "image/png")),
        (q("ct:Override"), ("PartName", "/word/document.xml"), ("ContentType", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml")),
        (q("ct:Override"), ("PartName", "/word/styles.xml"), ("ContentType", "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml")),
    }
    actual = {(i.tag, ("Extension" if i.tag == q("ct:Default") else "PartName",
                        i.get("Extension" if i.tag == q("ct:Default") else "PartName")),
               ("ContentType", i.get("ContentType"))) for i in ct}
    if (ct.tag != q("ct:Types") or ct.attrib or len(ct) != 5 or actual != content_types
            or any(len(i) or len(i.attrib) != 2 for i in ct)):
        _fail("invalid_content_types")
    base = NS["r"] + "/"
    _relationships(roots["_rels/.rels"], {"rId1": {"Id": "rId1", "Type": base + "officeDocument", "Target": "word/document.xml"}})
    _relationships(roots["word/_rels/document.xml.rels"], {
        "rId1": {"Id": "rId1", "Type": base + "styles", "Target": "styles.xml"},
        "rId2": {"Id": "rId2", "Type": base + "image", "Target": "media/portrait.png"}})
    document = roots["word/document.xml"]
    if document.tag != q("w:document") or roots["word/styles.xml"].tag != q("w:styles"):
        _fail("invalid_xml")
    drawings = list(document.iter(q("w:drawing")))
    namespaces = " ".join(f'xmlns:{key}="{value}"' for key, value in NS.items())
    expected = ET.fromstring(f"<root {namespaces}>" + drawing_xml(asset) + "</root>")[0]
    if len(drawings) != 1 or _tree(drawings[0]) != _tree(expected):
        _fail("invalid_drawing")
    picture_nodes = set(drawings[0].iter())
    parents = {child: parent for parent in document.iter() for child in parent}
    if (parents.get(drawings[0]) is None or parents[drawings[0]].tag != q("w:r")
            or parents.get(parents[drawings[0]]) is None or parents[parents[drawings[0]]].tag != q("w:p")):
        _fail("invalid_drawing")
    for root in roots.values():
        for node in root.iter():
            if (node.tag in {q("wp:anchor"), q("w:pict"), q("w:object"), q("w:altChunk")}
                    or q("r:link") in node.attrib):
                _fail("invalid_drawing")
            if (node.tag.startswith(tuple("{" + NS[p] + "}" for p in ("wp", "a", "pic")))
                    or node.tag == q("w:drawing")) and node not in picture_nodes:
                _fail("invalid_drawing")
            if q("r:embed") in node.attrib and node not in picture_nodes:
                _fail("invalid_drawing")


def check(container_bytes: bytes, asset: photo.PhotoAsset) -> list[str]:
    try:
        if type(container_bytes) is not bytes:
            _fail("invalid_type")
        if len(container_bytes) > photo.DOCX_LIMIT:
            _fail("container_budget")
        parts = _parts(container_bytes)
        media = parts["word/media/portrait.png"]
        clean, w, h, removed = photo.canonical_png(media)
        if (removed or clean != media or media != asset.embedded_bytes or photo.digest(media) != asset.embedded_sha256
                or (w, h) != (asset.width_px, asset.height_px)):
            _fail("image_mismatch")
        budget = [0]
        roots = {name: _xml(data, budget) for name, data in parts.items() if name != "word/media/portrait.png"}
        _structure(roots, asset)
    except photo.PhotoError as exc:
        return [str(exc)]
    except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile, RuntimeError, EOFError, struct.error, zlib.error):
        return ["outputs.docx.photo: photo.invalid_container"]
    return []
