"""Local, bounded, opt-in resume photos. png-v1 never rewrites the source.

Only this module opens the registered photo; renderers receive immutable canonical bytes.
Errors deliberately contain fixed codes, never supplied paths, names or metadata.
"""
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import stat
import struct
import unicodedata
import zlib

from . import store

PNG_LIMIT = 5 * 1024 * 1024
DOCX_LIMIT = 8 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
NOTE_KEYS = ("binding_hash", "source_sha256", "embedded_sha256", "width_px", "height_px", "policy")
_HASH = re.compile(r"[0-9a-f]{64}")
_DEVICE = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³]|CONIN\$|CONOUT\$|CLOCK\$)", re.I)


class PhotoError(ValueError):
    """A fixed, safe photo diagnostic."""


class ProfileInputError(PhotoError):
    """Unreadable explicit profile input (CLI exit 2)."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_basename(value) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= 128 and value not in (".", "..")
            and not any(c in value for c in '/\\:<>"|?*') and not value.endswith((".", " "))
            and not any(unicodedata.category(c).startswith("C") for c in value)
            and not _DEVICE.fullmatch(value.split(".")[0]))


def profile_errors(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, dict) or set(value) != {"file"}:
        return ["photo: photo.invalid_type"]
    return [] if safe_basename(value["file"]) else ["photo.file: photo.invalid_name"]


def selection_errors(value) -> list[str]:
    if value is None:
        return []
    if (not isinstance(value, dict) or set(value) != {"ref", "binding_hash"}
            or value.get("ref") != "profile.photo" or not _hash(value.get("binding_hash"))):
        return ["photo: photo.invalid_selection"]
    return []


def _hash(value) -> bool:
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


def _dimensions(w, h) -> bool:
    return type(w) is int and type(h) is int and 1 <= w <= 4096 and 1 <= h <= 4096 and w * h <= 4_000_000


def note_errors(value) -> list[str]:
    if not isinstance(value, dict) or set(value) != set(NOTE_KEYS):
        return ["build_note.photo: photo.invalid_type"]
    if any(not _hash(value[k]) for k in NOTE_KEYS[:3]):
        return ["build_note.photo: photo.invalid_digest"]
    if not _dimensions(value["width_px"], value["height_px"]):
        return ["build_note.photo: photo.invalid_dimensions"]
    return [] if value["policy"] == "png-v1" else ["build_note.photo: photo.unsupported_policy"]


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def _scanlines(compressed: bytes, w: int, h: int, channels: int) -> None:
    stride = 1 + w * channels
    expected = stride * h
    decoder = zlib.decompressobj()
    remaining, total = compressed, 0
    try:
        while remaining:
            block = decoder.decompress(remaining, min(65536, expected - total + 1))
            if total + len(block) > expected:
                raise PhotoError("photo: photo.pixel_budget")
            first = (-total) % stride
            if any(block[i] > 4 for i in range(first, len(block), stride)):
                raise PhotoError("photo: photo.invalid_filter")
            total += len(block)
            if decoder.unused_data:
                raise PhotoError("photo: photo.trailing_stream")
            remaining = decoder.unconsumed_tail
        if not decoder.eof or total != expected:
            raise PhotoError("photo: photo.invalid_stream")
    except zlib.error:
        raise PhotoError("photo: photo.invalid_stream") from None


def canonical_png(data: bytes) -> tuple[bytes, int, int, bool]:
    """Validate every compressed scanline with bounded zlib output; retain original IDAT bytes."""
    if type(data) is not bytes:
        raise PhotoError("photo: photo.invalid_type")
    if len(data) > PNG_LIMIT:
        raise PhotoError("photo: photo.file_budget")
    if not data.startswith(PNG_SIGNATURE):
        raise PhotoError("photo: photo.unsupported_format")
    offset, count, phase = 8, 0, 0  # before / within / after IDAT
    seen, idats, srgb, header, removed = set(), [], None, None, False
    ended = False
    while offset < len(data):
        count += 1
        if count > 256:
            raise PhotoError("photo: photo.chunk_budget")
        if len(data) - offset < 12:
            raise PhotoError("photo: photo.invalid_chunk")
        length = struct.unpack_from(">I", data, offset)[0]
        if length > PNG_LIMIT or offset + 12 + length > len(data):
            raise PhotoError("photo: photo.invalid_chunk")
        kind = data[offset + 4:offset + 8]
        body = data[offset + 8:offset + 8 + length]
        crc = struct.unpack_from(">I", data, offset + 8 + length)[0]
        if zlib.crc32(kind + body) != crc:
            raise PhotoError("photo: photo.invalid_crc")
        offset += length + 12
        if count == 1 and kind != b"IHDR":
            raise PhotoError("photo: photo.invalid_order")
        if kind in (b"IHDR", b"IEND", b"sRGB", b"pHYs", b"tIME") and kind in seen:
            raise PhotoError("photo: photo.duplicate_chunk")
        seen.add(kind)
        if kind == b"IHDR":
            if count != 1 or length != 13:
                raise PhotoError("photo: photo.invalid_header")
            w, h, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", body)
            if not _dimensions(w, h):
                raise PhotoError("photo: photo.invalid_dimensions")
            if (depth != 8 or color not in (2, 6) or compression != 0 or filtering != 0 or interlace != 0):
                raise PhotoError("photo: photo.unsupported_encoding")
            header = body
        elif kind == b"IDAT":
            if phase == 2:
                raise PhotoError("photo: photo.invalid_order")
            phase = 1
            idats.append(body)
        else:
            if phase == 1:
                phase = 2
            if kind == b"IEND":
                if body or not idats or offset != len(data):
                    raise PhotoError("photo: photo.invalid_end")
                ended = True
                break
            if kind == b"sRGB":
                if phase != 0 or length != 1 or body[0] > 3:
                    raise PhotoError("photo: photo.invalid_color")
                srgb = body
            elif kind in (b"tEXt", b"zTXt", b"iTXt", b"tIME", b"pHYs"):
                if kind == b"pHYs":
                    if phase != 0 or length != 9:
                        raise PhotoError("photo: photo.invalid_density")
                    x, y, unit = struct.unpack(">IIB", body)
                    if x == 0 or x != y or unit not in (0, 1):
                        raise PhotoError("photo: photo.invalid_density")
                if kind == b"tIME" and length != 7:
                    raise PhotoError("photo: photo.invalid_metadata")
                removed = True  # text is neither decoded nor decompressed
            else:
                raise PhotoError("photo: photo.unsupported_chunk")
    if not ended or header is None:
        raise PhotoError("photo: photo.invalid_end")
    compressed = b"".join(idats)
    _scanlines(compressed, w, h, 3 if color == 2 else 4)
    clean = (PNG_SIGNATURE + _chunk(b"IHDR", header)
             + (_chunk(b"sRGB", srgb) if srgb is not None else b"")
             + _chunk(b"IDAT", compressed) + _chunk(b"IEND", b""))
    return clean, w, h, removed


@dataclass(frozen=True)
class PhotoAsset:
    binding_hash: str
    source_sha256: str
    embedded_sha256: str
    width_px: int
    height_px: int
    metadata_removed: bool
    embedded_bytes: bytes = field(repr=False)
    policy: str = "png-v1"
    asset_name: str = "portrait.png"

    def __post_init__(self):
        errors = note_errors(self.note())
        if errors or type(self.metadata_removed) is not bool or self.asset_name != "portrait.png":
            raise PhotoError("photo: photo.invalid_asset")
        clean, w, h, removed = canonical_png(self.embedded_bytes)
        if (removed or clean != self.embedded_bytes or (w, h) != (self.width_px, self.height_px)
                or digest(clean) != self.embedded_sha256):
            raise PhotoError("photo: photo.invalid_asset")

    def note(self) -> dict:
        return {key: getattr(self, key) for key in NOTE_KEYS}

    def description(self) -> dict:
        return {**self.note(), "metadata_removed": self.metadata_removed}


def _guard(root: Path, path: Path, code: str) -> Path:
    """Chosen root may be a link; each lexical descendant must be a real regular file/directory."""
    root, path = Path(root).absolute(), Path(path).absolute()
    try:
        parts = path.relative_to(root).parts
        if not parts or parts[0] != "profile" or ".." in parts:
            raise PhotoError(code)
        current, real_root = root, root.resolve()
        for index, part in enumerate(parts):
            current = current / part
            if store._is_link(current) or not store._inside(current, real_root):
                raise PhotoError(code)
            info = current.stat()
            if index < len(parts) - 1:
                if not stat.S_ISDIR(info.st_mode):
                    raise PhotoError(code)
            elif not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
                raise PhotoError(code)
    except (OSError, RuntimeError, ValueError) as exc:
        if isinstance(exc, PhotoError):
            raise
        raise PhotoError(code) from None
    return path


def load_profile(root, profile_path) -> dict:
    """Safe explicit profile loading for the photo branch; never fall back to the default."""
    if profile_path is None:
        raise PhotoError("photo: photo.profile_required")
    path = Path(profile_path)
    # Check an outside/link path before any read, including a dangling link.
    try:
        _guard(Path(root), path, "photo: photo.profile_outside_root")
    except PhotoError:
        # A missing in-root ordinary path is an input error, not an implicit default.
        try:
            parts = path.absolute().relative_to(Path(root).absolute()).parts
            inside = len(parts) >= 2 and parts[0] == "profile" and ".." not in parts
            parent = path.parent
            while parent != Path(root).absolute() and parent != parent.parent:
                if store._is_link(parent):
                    inside = False
                parent = parent.parent
            if inside and not path.exists() and not store._is_link(path):
                raise ProfileInputError("photo: photo.profile_unreadable") from None
        except ValueError as exc:
            if isinstance(exc, PhotoError):
                raise
        raise
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise ProfileInputError("photo: photo.profile_unreadable") from None
    from . import profile
    if profile.validate(data):
        raise PhotoError("photo: photo.profile_invalid")
    return data


def prepare_photo(root, profile_path, profile_data) -> PhotoAsset:
    if profile_path is None:
        raise PhotoError("photo: photo.profile_required")
    _guard(Path(root), Path(profile_path), "photo: photo.profile_outside_root")
    value = profile_data.get("photo") if isinstance(profile_data, dict) else None
    if value is None or profile_errors(value):
        raise PhotoError("photo: photo.invalid_selection")
    filename = value["file"]
    if Path(filename).suffix.lower() != ".png":
        raise PhotoError("photo: photo.unsupported_format")
    path = _guard(Path(root), Path(root) / "profile" / filename, "photo: photo.source_unavailable")
    try:
        with path.open("rb") as stream:
            source = stream.read(PNG_LIMIT + 1)
    except OSError:
        raise PhotoError("photo: photo.source_unavailable") from None
    clean, w, h, removed = canonical_png(source)
    source_hash = digest(source)
    binding = json.dumps({"file": filename, "source_sha256": source_hash}, ensure_ascii=False,
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    return PhotoAsset(digest(binding), source_hash, digest(clean), w, h, removed, clean)


def require_photo_binding(selection, asset: PhotoAsset) -> None:
    if selection is None or selection_errors(selection):
        raise PhotoError("photo: photo.invalid_selection")
    if selection["binding_hash"] != asset.binding_hash:
        raise PhotoError("photo: photo.binding_mismatch")


def recheck_photo(root, profile_path, expected_asset: PhotoAsset) -> None:
    current = prepare_photo(root, profile_path, load_profile(root, profile_path))
    if current.note() != expected_asset.note() or current.embedded_bytes != expected_asset.embedded_bytes:
        raise PhotoError("photo: photo.source_changed")


def dimensions_emu(w: int, h: int) -> tuple[int, int]:
    if not _dimensions(w, h):
        raise PhotoError("photo: photo.invalid_dimensions")
    width, height = 900000, 1152000
    if width * h <= height * w:
        return width, (2 * width * h + w) // (2 * w)
    return (2 * height * w + h) // (2 * h), height


def check_docx_photo(container_bytes: bytes, asset: PhotoAsset) -> list[str]:
    from .resume_photo_docx import check
    return check(container_bytes, asset)
