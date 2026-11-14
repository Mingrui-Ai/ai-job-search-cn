"""Opt-in photo contract: generated geometric PNGs and existing fictional profile only.

No test reads the user's data. ZIP mutations change real packages, including both headers where
needed; isolated counter probes are labelled as such and are not claimed as legal extreme packages.
"""
import copy
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import FrozenInstanceError
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET
import zipfile
import zlib

from jobsearch_cn import build_notes, cli, material, profile, resume_docx, resume_pdf, resume_photo as p
from jobsearch_cn import resume_photo_docx as dx, review, score, vocab
from tests.test_cn_review import make_review

FIXTURE = Path(__file__).parent / "fixtures/cn/material/tech-m3"


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(w=40, h=60, channels=4, before=(), after=(), raw=None, compressed=None, **header):
    """Original asymmetric colored corners and a stepped diagonal; transparent bottom-right."""
    if raw is None:
        rows = []
        colors = ((230, 35, 45, 255), (30, 150, 70, 255), (35, 90, 220, 255), (240, 180, 30, 90))
        for y in range(h):
            row = bytearray([0])
            for x in range(w):
                color = colors[(2 if y * 2 >= h else 0) + (1 if x * 2 >= w else 0)]
                if x * h // w == y and x < w * 3 // 4:
                    color = (15, 15, 15, 255)
                row.extend(color[:channels])
            rows.append(bytes(row))
        raw = b"".join(rows)
    ihdr = struct.pack(">IIBBBBB", w, h, header.get("depth", 8), header.get("color", 6 if channels == 4 else 2),
                       header.get("compression", 0), header.get("filtering", 0), header.get("interlace", 0))
    return (p.PNG_SIGNATURE + chunk(b"IHDR", ihdr) + b"".join(chunk(k, v) for k, v in before)
            + chunk(b"IDAT", zlib.compress(raw) if compressed is None else compressed)
            + b"".join(chunk(k, v) for k, v in after) + chunk(b"IEND", b""))


def asset(source=None, name="portrait.png"):
    source = png() if source is None else source
    clean, w, h, removed = p.canonical_png(source)
    source_hash = hashlib.sha256(source).hexdigest()
    binding = json.dumps({"file": name, "source_sha256": source_hash}, ensure_ascii=False,
                         sort_keys=True, separators=(",", ":")).encode()
    return p.PhotoAsset(hashlib.sha256(binding).hexdigest(), source_hash, hashlib.sha256(clean).hexdigest(),
                        w, h, removed, clean)


def repack(container, mutate):
    with zipfile.ZipFile(io.BytesIO(container)) as archive:
        parts = {info.filename: archive.read(info) for info in archive.infolist()}
    mutate(parts)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return out.getvalue()


class PNG(unittest.TestCase):
    def test_rgb_rgba_and_metadata_are_canonical_without_changing_pixels_or_source(self):
        for channels in (3, 4):
            base = png(channels=channels, before=((b"sRGB", b"\0"),))
            source = png(channels=channels, before=((b"sRGB", b"\0"), (b"pHYs", struct.pack(">IIB", 3000, 3000, 1)),
                         (b"zTXt", b"SECRET\0\0not-a-zlib-stream")), after=((b"tEXt", b"Name\0SECRET"),))
            value = asset(source)
            self.assertEqual(value.embedded_bytes, base)
            self.assertTrue(value.metadata_removed)
            self.assertNotIn("SECRET", repr(value))
            self.assertEqual(set(value.description()), set(p.NOTE_KEYS) | {"metadata_removed"})
            self.assertEqual(source, png(channels=channels, before=((b"sRGB", b"\0"),
                (b"pHYs", struct.pack(">IIB", 3000, 3000, 1)), (b"zTXt", b"SECRET\0\0not-a-zlib-stream")),
                after=((b"tEXt", b"Name\0SECRET"),)))
            with self.assertRaises(FrozenInstanceError):
                value.policy = "changed"

    def test_corruption_stream_length_crc_order_and_bombs_fail_safely(self):
        good = png(3, 7)
        bad = [good[:-1], good + b"trailer", good[:40] + bytes([good[40] ^ 1]) + good[41:],
               png(3, 7, raw=b"\0"), png(3, 7, raw=b"\x05" + b"\0" * 90),
               png(3, 7, compressed=zlib.compress(b"\0" * 91) + zlib.compress(b"suffix")),
               png(3, 7, compressed=zlib.compress(b"\0" * 91)[:-2]),
               png(3, 7, compressed=zlib.compress(b"\0" * 200000)),
               png(3, 7, after=((b"tEXt", b"x"), (b"IDAT", b""))),
               png(3, 7, before=((b"IHDR", b""),)), png(3, 7, after=((b"IEND", b""),))]
        for data in bad:
            with self.subTest(length=len(data)), self.assertRaises(p.PhotoError) as error:
                p.canonical_png(data)
            self.assertRegex(str(error.exception), r"^photo: photo\.[a-z_]+$")

    def test_all_filters_and_contiguous_idat_chunks(self):
        raw = b"".join(bytes([i]) + b"\0" * 12 for i in range(5))
        good = png(3, 5, raw=raw)
        compressed = zlib.compress(raw)
        split = (good[:33] + chunk(b"IDAT", compressed[:5]) + chunk(b"IDAT", compressed[5:])
                 + chunk(b"IEND", b""))
        self.assertEqual(p.canonical_png(split)[0], good)

    def test_unapproved_formats_and_color_direction_metadata(self):
        inputs = [b"\xff\xd8JPEG", b"PNG", png(depth=16), png(color=3), png(color=0), png(interlace=1),
                  png(compression=1), png(filtering=1)]
        inputs += [png(before=((kind, b"SECRET"),)) for kind in
                   (b"eXIf", b"iCCP", b"gAMA", b"cHRM", b"tRNS", b"acTL", b"fcTL", b"fdAT", b"other")]
        inputs += [png(before=((b"pHYs", struct.pack(">IIB", x, y, unit)),))
                   for x, y, unit in ((0, 0, 0), (300, 400, 1), (300, 300, 2))]
        inputs += [png(before=((b"sRGB", b"\4"),)), png(after=((b"sRGB", b"\0"),)),
                   png(before=((b"sRGB", b"\0"), (b"sRGB", b"\0")))]
        for data in inputs:
            with self.subTest(length=len(data)), self.assertRaises(p.PhotoError):
                p.canonical_png(data)

    def test_exact_file_chunk_dimension_pixel_bounds(self):
        base = png(1, 1)
        exact = png(1, 1, before=((b"tEXt", b"x" * (p.PNG_LIMIT - len(base) - 12)),))
        self.assertEqual(len(exact), p.PNG_LIMIT)
        self.assertEqual(p.canonical_png(exact)[1:3], (1, 1))
        with self.assertRaises(p.PhotoError):
            p.canonical_png(exact + b"x")
        self.assertEqual(p.canonical_png(png(1, 1, before=((b"tEXt", b"x"),) * 253))[1:3], (1, 1))
        with self.assertRaises(p.PhotoError):
            p.canonical_png(png(1, 1, before=((b"tEXt", b"x"),) * 254))
        for w, h in ((4096, 1), (1, 4096), (2000, 2000)):
            raw = (b"\0" * (1 + w * 4)) * h
            self.assertEqual(p.canonical_png(png(w, h, raw=raw))[1:3], (w, h))
        for w, h in ((4097, 1), (1, 4097), (2001, 2000), (0, 1)):
            with self.assertRaises(p.PhotoError):
                p.canonical_png(png(w, h, raw=b""))

    def test_types_keys_redaction_and_precise_emu(self):
        for value in ({}, [], True, 1, "file", {"file": "ok.png", "SECRET": "x"}):
            self.assertTrue(p.profile_errors(value))
            self.assertEqual(profile.redacted({"photo": value})["photo"], "***")
        for name in ("../a.png", "/a.png", "a/b.png", "a\\b.png", "a.png:stream", "NUL.png", "com1.PNG",
                     "LPT².png", "a.png.", "a.png ", "a\n.png", "\\\\server\\x", "x" * 129):
            self.assertTrue(p.profile_errors({"file": name}), name)
        for w, h, expected in ((400, 600, (768000, 1152000)), (800, 400, (900000, 450000)),
                               (3, 7, (493714, 1152000)), (64, 1, (900000, 14063))):
            self.assertEqual(p.dimensions_emu(w, h), expected)
        note = asset().note()
        for value in (True, 1.0, "1", None):
            self.assertTrue(p.note_errors({**note, "width_px": value}))
        for value in ("A" * 64, "a" * 64 + "\n", False, None):
            self.assertTrue(p.note_errors({**note, "binding_hash": value}))
            self.assertTrue(p.selection_errors({"ref": "profile.photo", "binding_hash": value}))
        for value in (None, {**note, "extra": 1}, {**note, "policy": "png-v2"}):
            self.assertTrue(p.note_errors(value))


class DOCX(unittest.TestCase):
    def setUp(self):
        self.asset = asset()
        self.content = {"name": "Example", "contact": "example@example.test", "intent": "Engineer"}
        self.container = resume_docx.build(self.content, photo=self.asset)

    def test_real_parts_relationships_sizes_and_text(self):
        for w, h in ((400, 600), (800, 400), (3, 7), (64, 1)):
            value = asset(png(w, h))
            data = resume_docx.build(self.content, photo=value)
            self.assertEqual(p.check_docx_photo(data, value), [])
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertEqual(set(archive.namelist()), set(dx.PART_LIMITS))
                self.assertEqual(archive.read("word/media/portrait.png"), value.embedded_bytes)
                doc = ET.fromstring(archive.read("word/document.xml"))
                self.assertEqual([int(doc.find('.//wp:extent', dx.NS).get(k)) for k in ("cx", "cy")],
                                 list(p.dimensions_emu(w, h)))
        with zipfile.ZipFile(io.BytesIO(resume_docx.build(self.content))) as archive:
            self.assertEqual(len(archive.namelist()), 5)
            self.assertFalse(any("media" in name for name in archive.namelist()))

    def test_media_relationship_or_drawing_tamper_refused_even_with_valid_zip(self):
        changes = [
            ("word/media/portrait.png", lambda b: png(40, 60, channels=3)),
            ("word/_rels/document.xml.rels", lambda b: b.replace(b'Target="media/', b'TargetMode="External" Target="media/')),
            ("word/_rels/document.xml.rels", lambda b: b.replace(b'rId2', b'rId1')),
            ("word/_rels/document.xml.rels", lambda b: b.replace(b'media/portrait.png', b'./media/portrait.png')),
            ("word/document.xml", lambda b: b.replace(b'r:embed="rId2"', b'r:embed="rId1"')),
            ("word/document.xml", lambda b: b.replace(b'r:embed=', b'r:link=')),
            ("word/document.xml", lambda b: b.replace(b'cx="768000"', b'cx="768001"', 1)),
            ("word/document.xml", lambda b: b.replace(b'cy="1152000"', b'cy="+1152000"')),
            ("word/document.xml", lambda b: b.replace(b'<a:xfrm>', b'<a:xfrm rot="1">')),
            ("word/document.xml", lambda b: b.replace(b'<a:stretch>', b'<a:srcRect/><a:stretch>')),
            ("word/document.xml", lambda b: b.replace(b'wp:inline', b'wp:anchor')),
            ("word/document.xml", lambda b: b.replace(b'noChangeAspect="1"', b'noChangeAspect="0"')),
            ("word/document.xml", lambda b: b.replace(b'Resume photo', b'SECRET')),
            ("[Content_Types].xml", lambda b: b.replace(b'image/png', b'image/jpeg')),
        ]
        for name, change in changes:
            with self.subTest(part=name):
                bad = repack(self.container, lambda parts: parts.__setitem__(name, change(parts[name])))
                self.assertTrue(p.check_docx_photo(bad, self.asset))
        bad = repack(self.container, lambda parts: parts.__setitem__("word/media/extra.png", png()))
        self.assertTrue(p.check_docx_photo(bad, self.asset))
        # Prefix aliases preserve URI identity and are accepted.
        equivalent = repack(self.container, lambda parts: parts.__setitem__("word/document.xml",
            parts["word/document.xml"].replace(b"xmlns:pic=", b"xmlns:image=").replace(b"pic:", b"image:")))
        self.assertEqual(p.check_docx_photo(equivalent, self.asset), [])

    def test_budget_xml_eocd_and_container_input_types(self):
        for data in (bytearray(self.container), Path("never-open"), self.container + b"x",
                     b"x" * (p.DOCX_LIMIT + 1)):
            self.assertTrue(p.check_docx_photo(data, self.asset))
        for content in (b'<?xml version="1.0" encoding="UTF-16"?><x/>', b'<!DOCTYPE x><x/>', b'<x>\0</x>',
                        b'<x>' * 65 + b'</x>' * 65, b'<x>' + b'<y/>' * 50000 + b'</x>',
                        b'x' * (dx.PART_LIMITS["word/styles.xml"] + 1)):
            bad = repack(self.container, lambda parts: parts.__setitem__("word/styles.xml", content))
            self.assertTrue(p.check_docx_photo(bad, self.asset))
        for offset, value in ((-12, b"\xff\xff"), (-10, b"\xff\xff\xff\xff")):
            bad = bytearray(self.container)
            bad[offset:offset + len(value)] = value
            with mock.patch.object(dx.zipfile, 'ZipFile', side_effect=AssertionError('must reject before ZipFile')):
                self.assertTrue(p.check_docx_photo(bytes(bad), self.asset))

    def test_forged_smaller_uncompressed_size_cannot_hide_a_suffix(self):
        # Forge matching central/local declared length and prefix CRC, keeping complete compressed data.
        bad = bytearray(self.container)
        with zipfile.ZipFile(io.BytesIO(self.container)) as archive:
            info = archive.getinfo("word/styles.xml")
            original = archive.read(info)
        size, crc = 12, zlib.crc32(original[:12])
        struct.pack_into('<I', bad, info.header_offset + 14, crc)
        struct.pack_into('<I', bad, info.header_offset + 22, size)
        pos = bad.find(b'PK\x01\x02')
        while pos >= 0:
            nlen = struct.unpack_from('<H', bad, pos + 28)[0]
            if bad[pos + 46:pos + 46 + nlen] == b'word/styles.xml':
                struct.pack_into('<I', bad, pos + 16, crc)
                struct.pack_into('<I', bad, pos + 24, size)
                break
            pos = bad.find(b'PK\x01\x02', pos + 46 + nlen)
        self.assertTrue(p.check_docx_photo(bytes(bad), self.asset))


class Workflow(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        shutil.copytree(FIXTURE / 'profile', self.root / 'profile')
        self.profile_path = self.root / 'profile/alternate.json'
        self.profile = json.loads((self.root / 'profile/profile.json').read_text(encoding='utf-8'))
        self.profile['photo'] = {'file': 'chosen.png'}
        self.source = png(before=((b'tEXt', b'Name\0SECRET'),))
        (self.root / 'profile/chosen.png').write_bytes(self.source)
        self.write(self.profile_path, self.profile)
        default = {**self.profile, 'photo': {'file': 'default.png'}}
        self.write(self.root / 'profile/profile.json', default)
        (self.root / 'profile/default.png').write_bytes(png(80, 40))
        self.asset = asset(self.source, 'chosen.png')
        self.record = json.loads((FIXTURE / 'resume-1.json').read_text(encoding='utf-8'))
        self.record['photo'] = {'ref': 'profile.photo', 'binding_hash': self.asset.binding_hash}
        self.record['job_id'] = 'job_000000000001'
        self.material_path = self.root / 'materials/job_000000000001/resume-1.json'
        self.write(self.material_path, self.record)
        self.review_path = self.material_path.with_name('review-1.json')
        self.write(self.review_path, make_review(job_id=self.record['job_id'], material_hash=review.material_hash(self.record),
                                               findings=[], coverage=[], verdict='pass'))
        self.folder = self.root / 'resumes' / self.record['job_id']
        self.folder.mkdir(parents=True)
        (self.folder / 'resume-1.pdf').write_bytes(b'fake staged PDF')
        (self.folder / 'resume-1.docx').write_bytes(resume_docx.build({'name': 'Example'}, photo=self.asset))
        cli._write_build_note(self.folder, 'resume-1', self.record, self.profile,
                              (self.folder / 'resume-1.pdf', self.folder / 'resume-1.docx'), photo=self.asset)

    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def call(self, *args, alternate=True):
        argv = [*map(str, args), '--data-dir', str(self.root)]
        if alternate:
            argv += ['--profile', str(self.profile_path)]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def check(self):
        return build_notes.check_outputs(self.root, self.material_path, self.record, 'resume-1.json',
                                         profile_path=self.profile_path)

    def test_alternate_full_chain_and_default_or_missing_profile_do_not_fallback(self):
        observed = []
        prepare = p.prepare_photo
        def spy(root, path, data):
            observed.append(path)
            return prepare(root, path, data)
        with mock.patch.object(p, 'prepare_photo', side_effect=spy):
            code, output, _ = self.call('profile', 'validate', self.profile_path, '--photo', alternate=False)
            self.assertEqual(code, 0, output)
            self.assertEqual(json.loads(output)['photo'], self.asset.description())
            for group, command, path in (('material', 'validate', self.material_path), ('review', 'draft', self.material_path),
                                         ('review', 'validate', self.review_path), ('review', 'show', self.review_path)):
                result = self.call(group, command, path)
                self.assertEqual(result[0], 0, result)
                result = self.call(group, command, path, alternate=False)
                self.assertEqual(result[0], 1, result)
            self.assertIn(self.profile_path, observed)
            self.assertIn(self.root / 'profile/profile.json', observed)
        self.assertEqual(self.check(), [])
        self.profile_path.unlink()
        self.assertEqual(self.call('review', 'validate', self.review_path)[0], 2)

    def test_no_photo_never_opens_asset_and_score_hash_is_unchanged(self):
        original_hash = score.profile_hash(self.profile)
        for value in (None, {'file': 'missing.jpeg'}):
            self.profile['photo'] = value
            self.write(self.profile_path, self.profile)
            self.assertEqual(score.profile_hash(self.profile), original_hash)
        self.record.pop('photo')
        self.write(self.material_path, self.record)
        with mock.patch.object(p, 'prepare_photo', side_effect=AssertionError('no-photo opened source')):
            self.assertEqual(self.call('material', 'validate', self.material_path)[0], 0)
        self.assertTrue(review.validate(json.loads(self.review_path.read_text()), self.record)[0])

    def test_changed_deleted_renamed_source_invalidates_all_current_entrypoints(self):
        source_path = self.root / 'profile/chosen.png'
        stamp = source_path.stat().st_mtime_ns
        for action in ('bytes', 'metadata', 'delete', 'name'):
            with self.subTest(action=action):
                source_path.write_bytes(self.source)
                self.profile['photo'] = {'file': 'chosen.png'}
                self.write(self.profile_path, self.profile)
                if action == 'bytes':
                    source_path.write_bytes(png(60, 40))
                    os.utime(source_path, ns=(stamp, stamp))
                elif action == 'metadata':
                    source_path.write_bytes(png(before=((b'tEXt', b'Name\0changed'),)))
                elif action == 'delete':
                    source_path.unlink()
                else:
                    (self.root / 'profile/renamed.png').write_bytes(self.source)
                    self.profile['photo']['file'] = 'renamed.png'
                    self.write(self.profile_path, self.profile)
                for command in (('material', 'validate', self.material_path), ('resume', 'build', self.material_path),
                                ('review', 'draft', self.material_path), ('review', 'validate', self.review_path),
                                ('review', 'show', self.review_path)):
                    result = self.call(*command)
                    self.assertEqual(result[0], 1, result)
                    self.assertNotIn('SECRET', result[1] + result[2])

    def test_mtime_and_moved_data_keep_binding(self):
        os.utime(self.root / 'profile/chosen.png', (100, 100))
        self.assertEqual(self.check(), [])
        moved = self.root / 'moved'
        shutil.copytree(self.root / 'profile', moved / 'profile')
        found = p.prepare_photo(moved, moved / 'profile/alternate.json', self.profile)
        self.assertEqual(found, self.asset)

    def test_profile_boundary_and_hardlinks(self):
        outside = self.root / 'outside.json'
        self.write(outside, self.profile)
        with self.assertRaises(p.PhotoError):
            p.load_profile(self.root, outside)
        picture = self.root / 'profile/chosen.png'
        alias = self.root / 'profile/alias.png'
        try:
            os.link(picture, alias)
        except OSError as exc:
            self.skipTest(f'hardlinks unavailable: {type(exc).__name__}')
        with self.assertRaises(p.PhotoError):
            p.prepare_photo(self.root, self.profile_path, self.profile)
        alias.unlink()

    def test_symlink_descendants_and_explicit_root_link(self):
        picture = self.root / 'profile/chosen.png'
        alias = self.root / 'profile/alias.png'
        try:
            alias.symlink_to(picture)
        except OSError as exc:
            self.skipTest(f'symlinks unavailable: {type(exc).__name__}')
        with self.assertRaises(p.PhotoError):
            p.prepare_photo(self.root, self.profile_path, {**self.profile, 'photo': {'file': 'alias.png'}})
        alias.unlink()
        chosen_root = self.root / 'chosen-root'
        chosen_root.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(p.prepare_photo(chosen_root, chosen_root / 'profile/alternate.json', self.profile), self.asset)

    @unittest.skipUnless(os.name == 'nt', 'Windows junction fixture')
    def test_actual_junction_descendants_refused_and_chosen_root_allowed(self):
        def junction(path, target):
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            command = 'New-Item -ItemType Junction -Path ' + quote(path) + ' -Target ' + quote(target) + ' | Out-Null'
            run = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            if run.returncode:
                self.fail('Windows junction creation failed; do not treat this fixture as passed')
            self.addCleanup(os.rmdir, path)  # removes only the exact junction, never traverses its target
            self.assertTrue(p.store._is_link(path))

        child_root = self.root / 'child-root'
        child_root.mkdir()
        junction(child_root / 'profile', self.root / 'profile')
        with mock.patch.object(Path, 'open', side_effect=AssertionError('junction read entered')):
            with self.assertRaises(p.PhotoError):
                p.load_profile(child_root, child_root / 'profile/alternate.json')
            with self.assertRaises(p.PhotoError):
                p.prepare_photo(child_root, child_root / 'profile/alternate.json', self.profile)
        nested = self.root / 'profile/nested'
        junction(nested, self.root / 'profile')
        with self.assertRaises(p.PhotoError):
            p.load_profile(self.root, nested / 'alternate.json')
        junction(self.root / 'profile/directory.png', self.root / 'profile')
        with self.assertRaises(p.PhotoError):
            p.prepare_photo(self.root, self.profile_path, {**self.profile, 'photo': {'file': 'directory.png'}})
        selected = self.root / 'selected-root'
        junction(selected, self.root)
        self.assertEqual(p.prepare_photo(selected, selected / 'profile/alternate.json', self.profile), self.asset)

    def test_docx_single_limited_read_and_path_swap_use_identical_bytes(self):
        path = self.folder / 'resume-1.docx'
        captured = path.read_bytes()
        original_open, original_read = Path.open, Path.read_bytes
        calls, inputs = [], []
        class Reader(io.BytesIO):
            def read(stream, size=-1):
                self.assertEqual(size, p.DOCX_LIMIT + 1)
                calls.append(size)
                return super().read(size)
        def guarded_open(item, *args, **kwargs):
            return Reader(captured) if item == path else original_open(item, *args, **kwargs)
        def no_unbounded(item):
            if item == path:
                raise AssertionError('old unbounded read entered')
            return original_read(item)
        real_check = p.check_docx_photo
        def structural(data, selected):
            inputs.append(data)
            with original_open(path, 'wb') as stream:
                stream.write(b'replacement after hash check')
            return real_check(data, selected)
        with mock.patch.object(Path, 'open', guarded_open), mock.patch.object(Path, 'read_bytes', no_unbounded), \
                mock.patch.object(p, 'check_docx_photo', side_effect=structural):
            self.assertEqual(self.check(), [])
        self.assertEqual(calls, [p.DOCX_LIMIT + 1])
        self.assertEqual(inputs, [captured])
        self.assertTrue(self.check())  # a later check sees the replaced path

    def test_note_and_container_budget_fail_before_structure(self):
        docx = self.folder / 'resume-1.docx'
        docx.write_bytes(b'x' * (p.DOCX_LIMIT + 1))
        with mock.patch.object(p, 'check_docx_photo', side_effect=AssertionError('over-limit reached structure')):
            self.assertIn('container_budget', str(self.check()))
        note = self.folder / 'resume-1.build.json'
        original = json.loads(note.read_text())
        for value in (None, {**self.asset.note(), 'width_px': True}, {**self.asset.note(), 'embedded_sha256': 'a' * 64}):
            self.write(note, {**original, 'photo': value})
            self.assertTrue(self.check())

    def fake_build(self, failure=None):
        assets = []
        def pdf(content, output, typst=None, *, photo=None):
            assets.append(photo)
            output.write_bytes(b'new fake PDF')
            if failure == 'source':
                (self.root / 'profile/chosen.png').write_bytes(png(60, 40))
            return {'pdf': str(output), 'spaciness': 1.0, 'fonts': {}}
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(resume_pdf, 'render', side_effect=pdf))
            stack.enter_context(mock.patch.object(resume_pdf, 'check', return_value=[]))
            stack.enter_context(mock.patch.object(resume_docx, 'same_text', return_value=[]))
            if failure == 'docx':
                stack.enter_context(mock.patch.object(resume_docx, 'write', side_effect=OSError('private-path')))
            elif failure == 'note':
                stack.enter_context(mock.patch.object(cli, '_write_build_note', side_effect=OSError('private-path')))
            elif failure == 'timeout':
                stack.enter_context(mock.patch.object(resume_pdf, 'render', side_effect=resume_pdf.ResumeError('timeout')))
            result = self.call('resume', 'build', self.material_path)
        return result, assets

    def test_build_uses_one_asset_and_publishes_complete_note(self):
        result, assets = self.fake_build()
        self.assertEqual(result[0], 0, result)
        self.assertEqual(assets, [self.asset])
        self.assertEqual(self.check(), [])
        self.assertFalse(list(self.folder.glob('.photo-build-*')))
        self.assertEqual((self.root / 'profile/chosen.png').read_bytes(), self.source)

    def test_failed_builds_do_not_report_success_or_leave_temporary_copies(self):
        for failure in ('docx', 'timeout', 'note', 'source'):
            with self.subTest(failure=failure):
                result, _ = self.fake_build(failure)
                self.assertEqual(result[0], 1, result)
                self.assertFalse(list(self.folder.glob('.photo-build-*')))
                self.assertNotIn('private-path', result[1] + result[2])
                if failure in ('note', 'source'):
                    self.assertTrue(self.check())


if __name__ == '__main__':
    unittest.main()
