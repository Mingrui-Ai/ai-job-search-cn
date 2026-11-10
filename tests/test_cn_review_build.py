"""Review CLI must bind current synthetic materials to complete, unchanged build outputs."""
import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from jobsearch_cn import build_notes, cli, review, store
from tests.test_cn_review import MATERIAL, PROFILE


class GeneratedReview(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "data"
        self.material = copy.deepcopy(MATERIAL)

    def setup_case(self, kind="resume", verdict="pass"):
        self.material = {**copy.deepcopy(MATERIAL), "kind": kind}
        self.source = self.root / f"{kind}-1.json"
        self.source.write_text(json.dumps(self.material), encoding="utf-8")
        self.review = {"schema_version": 1, "kind": f"{kind}-review", "job_id": self.material["job_id"],
                       "material": self.source.name, "material_hash": review.material_hash(self.material),
                       "round": 1, "mode": "independent", "created": "2026-11-10T21:20:00+08:00",
                       "verdict": verdict, "findings": [], "coverage": []}
        self.review_file = self.root / "review-1-r1.json"
        self.review_file.write_text(json.dumps(self.review), encoding="utf-8")
        self.outputs = self.data / ("resumes" if kind == "resume" else "messages") / self.material["job_id"]
        self.outputs.mkdir(parents=True, exist_ok=True)
        self.files = [self.outputs / f"{kind}-1.{ext}" for ext in (("pdf", "docx") if kind == "resume" else ("txt",))]
        for path in self.files:
            path.write_bytes(b"Synthetic artifact " + path.name.encode())
        self.note_path = cli._write_build_note(self.outputs, self.source.stem, self.material, PROFILE, self.files,
                                              "resume-build" if kind == "resume" else "message-build")
        self.note = json.loads(self.note_path.read_text(encoding="utf-8"))

    def run_cli(self, command, *args, explicit=True):
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = ["review", command, str(self.review_file), *map(str, args)]
        if explicit:
            argv.extend(["--data-dir", str(self.data)])
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def assert_pair(self, expected, fragment=None):
        results = [self.run_cli(command) for command in ("validate", "show")]
        for code, stdout, stderr in results:
            self.assertEqual(code, expected, stdout + stderr)
            self.assertEqual(stderr, "")
            if fragment:
                self.assertIn(fragment, stdout)
        if expected == 1:
            self.assertEqual(json.loads(results[0][1]), json.loads(results[1][1]))

    def write_note(self, note):
        self.note_path.write_text(json.dumps(note), encoding="utf-8")

    def test_all_material_kinds_and_verdicts_require_current_outputs(self):
        for kind in ("resume", "greeting", "email", "referral"):
            for verdict in ("pass", "revise"):
                with self.subTest(kind=kind, verdict=verdict):
                    self.setup_case(kind, verdict)
                    self.assert_pair(0)
                    self.material["created"] = "2026-11-10T20:00:00+08:00"
                    self.source.write_text(json.dumps(self.material), encoding="utf-8")
                    self.review["material_hash"] = review.material_hash(self.material)
                    self.review_file.write_text(json.dumps(self.review), encoding="utf-8")
                    self.assert_pair(1, "build_note.material_hash")

    def test_missing_note_and_each_output_are_errors_without_any_writes(self):
        self.setup_case()
        for path in [self.note_path, *self.files]:
            with self.subTest(path=path.name):
                saved = path.read_bytes()
                path.unlink()
                before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
                self.assert_pair(1, "missing")
                self.assertEqual({p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}, before)
                path.write_bytes(saved)
        absent = self.root / "absent-data"
        with mock.patch.object(store, "DEFAULT_DATA_DIR", absent), mock.patch.dict(os.environ, {}, clear=True):
            for command in ("validate", "show"):
                self.assertEqual(self.run_cli(command, explicit=False)[0], 1)
        self.assertFalse(absent.exists())

    def test_unreadable_and_invalid_note_shapes_are_errors(self):
        self.setup_case()
        cases = [None, [], 3, {}, {**self.note, "schema_version": True}, {**self.note, "schema_version": 2},
                 {**self.note, "profile_hash": "wrong"}, {**self.note, "built_at": "2026-11-10"},
                 {**self.note, "material_hash": "wrong"}, {**self.note, "files": None},
                 {**self.note, "files": [None]}, {**self.note, "extra": "not a v1 field"},
                 {**self.note, "files": [{**item, "sha256": []} for item in self.note["files"]]},
                 {**self.note, "files": [{**item, "unexpected": True} for item in self.note["files"]]}]
        for note in cases:
            with self.subTest(note=note):
                self.write_note(note)
                self.assert_pair(1, "build_note")
        for raw in (b"{bad json", b"\xff\xfe"):
            self.note_path.write_bytes(raw)
            self.assert_pair(1, "unreadable")

    def test_unreadable_output_returns_an_error_without_printing_bytes(self):
        self.setup_case("email")
        read = Path.read_bytes
        def unavailable(path):
            if path == self.files[0]:
                raise PermissionError("synthetic permission refusal")
            return read(path)
        with mock.patch.object(Path, "read_bytes", unavailable):
            self.assert_pair(1, "cannot read email-1.txt")

    def test_note_identity_and_cross_job_copy_do_not_pass(self):
        self.setup_case()
        other_job = {**self.material, "job_id": "job_abcdef012345"}
        for update in ({"kind": "message-build"}, {"material": "resume-2.json"},
                       {"material_hash": review.material_hash(other_job)}):
            with self.subTest(update=update):
                self.write_note({**self.note, **update})
                self.assert_pair(1, "build_note")

    def test_profile_hash_can_differ_and_files_may_be_listed_in_reverse(self):
        self.setup_case()
        note = {**self.note, "profile_hash": "f" * 64, "files": list(reversed(self.note["files"]))}
        self.assertNotEqual(note["profile_hash"], self.material["profile_hash"])
        self.write_note(note)
        self.assert_pair(0)
        self.assertFalse((self.data / "profile").exists())

    def test_file_names_are_complete_unique_and_never_followed_as_paths(self):
        self.setup_case()
        outside = self.root / "outside-secret"
        outside.write_bytes(b"must not be opened by the build checker")
        names = [str(outside), "../outside-secret", "..\\outside-secret", "C:\\private\\resume-1.pdf",
                 "\\\\host\\share\\resume-1.pdf", "/tmp/resume-1.pdf", "resume-1.pdf:stream", "elsewhere/resume-1.pdf"]
        cases = [self.note["files"][:1], self.note["files"] + self.note["files"][:1],
                 self.note["files"] + [{"name": "resume-2.pdf", "sha256": "a" * 64}]]
        cases += [[{**self.note["files"][0], "name": name}, self.note["files"][1]] for name in names]
        read = Path.read_bytes
        def protected(path):
            self.assertNotEqual(path, outside)
            return read(path)
        for files in cases:
            with self.subTest(files=files), mock.patch.object(Path, "read_bytes", protected):
                self.write_note({**self.note, "files": files})
                self.assert_pair(1, "build_note.files")

    def test_replaced_empty_and_swapped_outputs_fail_name_bound_hashes(self):
        self.setup_case()
        self.files[0].write_bytes(b"different bytes with the same name")
        self.assert_pair(1, "differs")
        self.files[0].write_bytes(b"")
        note = copy.deepcopy(self.note)
        note["files"][0]["sha256"] = hashlib.sha256(b"").hexdigest()
        self.write_note(note)
        self.assert_pair(1, "empty")
        self.setup_case()
        note = copy.deepcopy(self.note)
        note["files"][0]["sha256"], note["files"][1]["sha256"] = note["files"][1]["sha256"], note["files"][0]["sha256"]
        self.write_note(note)
        self.assert_pair(1, "differs")

    def test_explicit_root_beats_environment_and_environment_beats_default(self):
        self.setup_case()
        absent = self.root / "absent"
        with mock.patch.dict(os.environ, {store.DATA_DIR_ENV: str(absent)}):
            self.assert_pair(0)
        with mock.patch.dict(os.environ, {store.DATA_DIR_ENV: str(self.data)}), mock.patch.object(store, "DEFAULT_DATA_DIR", absent):
            for command in ("validate", "show"):
                self.assertEqual(self.run_cli(command, explicit=False)[0], 0)
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(store, "DEFAULT_DATA_DIR", self.data):
            self.assertEqual(self.run_cli("validate", explicit=False)[0], 0)

    def test_declared_paths_are_rejected_but_explicit_outside_material_is_allowed(self):
        self.setup_case()
        self.assertEqual(self.run_cli("validate", "--material", self.source)[0], 0)
        for name in ("../resume-1.json", "..\\resume-1.json", str(self.source), "C:\\resume-1.json",
                     "resume-1.json\0", "resume-1.json\n", "NUL", "CON", "resume-01.json",
                     "resume-1000000.json", "resume-１.json"):
            self.review["material"] = name
            self.review_file.write_text(json.dumps(self.review), encoding="utf-8")
            self.assert_pair(1, "bare file name")
        self.review["material"] = "resume-2.json"
        self.review_file.write_text(json.dumps(self.review), encoding="utf-8")
        self.assertEqual(self.run_cli("validate", "--material", self.source)[0], 1)

    def test_old_review_still_fails_before_build_check(self):
        self.setup_case()
        self.material["created"] = "2026-11-10T20:00:00+08:00"
        self.source.write_text(json.dumps(self.material), encoding="utf-8")
        self.assert_pair(1, "material has changed since this review")

    def test_invalid_job_id_and_wrong_kind_filename_never_read_outputs(self):
        self.setup_case()
        for key, value in (("job_id", "../../outside"), ("kind", "greeting")):
            target = {**self.material, key: value}
            with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("unexpected output read")):
                self.assertTrue(build_notes.check_outputs(self.data, self.source, target, self.source.name))

    def test_file_symlinks_are_not_read(self):
        self.setup_case()
        elsewhere = self.root / "external-artifact"
        elsewhere.write_bytes(b"external")
        for path in [self.note_path, *self.files]:
            saved = path.read_bytes()
            path.unlink()
            try:
                path.symlink_to(elsewhere)
            except OSError as exc:
                path.write_bytes(saved)
                self.skipTest(f"symlinks unavailable (error {exc.errno})")
            self.assert_pair(1, "link or junction")
            path.unlink()
            path.write_bytes(saved)

    def test_output_directory_links_rejected_and_chosen_root_link_allowed(self):
        self.setup_case()
        actual = self.data
        chosen = self.root / "chosen-data"
        try:
            chosen.symlink_to(actual, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symlinks unavailable (error {exc.errno})")
        self.data = chosen
        self.assert_pair(0)
        self.data = actual
        redirected = self.root / "redirected"
        self.outputs.rename(redirected)
        self.outputs.symlink_to(redirected, target_is_directory=True)
        self.assert_pair(1, "link or junction")

    @unittest.skipUnless(os.name == "nt", "Windows junction boundary")
    def test_windows_junction_is_rejected(self):
        self.setup_case()
        actual = self.data
        chosen = self.root / "chosen-junction"
        proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(chosen), str(actual)], capture_output=True)
        if proc.returncode:
            self.skipTest("junction creation unavailable")
        self.data = chosen
        self.assert_pair(0)  # an explicitly selected data root may itself be a link
        self.data = actual
        redirected = self.root / "junction-target"
        self.outputs.rename(redirected)
        proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(self.outputs), str(redirected)], capture_output=True)
        if proc.returncode:
            self.skipTest("junction creation unavailable")
        self.assert_pair(1, "link or junction")


if __name__ == "__main__":
    unittest.main()
