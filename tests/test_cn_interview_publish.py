"""Fault injection at interview publication boundaries, with public temporary inputs."""
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest import mock

from jobsearch_cn import interview, interview_files as files, interview_review
from tests.test_cn_interview import Data, write


class Publication(Data):
    def test_output_changed_during_final_source_check_cannot_report_success(self):
        actual = interview.recheck_pack
        calls = 0
        def recheck(*args):
            nonlocal calls
            calls += 1
            if calls == 4:
                self.path.with_suffix(".md").write_bytes(b"changed")
            return actual(*args)
        with mock.patch.object(interview, "recheck_pack", side_effect=recheck):
            with self.assertRaises(files.Error) as caught: interview.render(self.root, self.path, True)
        self.assertEqual(caught.exception.code, "invalid_output")
        self.assertFalse(self.path.with_suffix(".build.json").exists())

    def test_failed_fsync_cleans_only_files_this_writer_created(self):
        for failing_call in (1, 2, 3):
            with self.subTest(call=failing_call):
                actual = os.fsync
                count = 0
                def fsync(descriptor):
                    nonlocal count
                    count += 1
                    if count == failing_call: raise OSError("failed flush")
                    actual(descriptor)
                with mock.patch.object(files.os, "fsync", side_effect=fsync):
                    with self.assertRaises(OSError): interview.render(self.root, self.path, True)
                self.assertFalse(self.path.with_suffix(".writer").exists())
                self.assertFalse(list(self.path.parent.glob(".interview-*.tmp")))
                self.assertFalse(self.path.with_suffix(".build.json").exists())

    def test_each_replace_failure_before_or_after_success_closes_marker(self):
        real_replace = os.replace
        for failing_call in (1, 2):
            for after in (False, True):
                with self.subTest(call=failing_call, after=after):
                    self.reviewed()
                    count = 0
                    def replace(source, target):
                        nonlocal count
                        count += 1
                        if count == failing_call:
                            if after: real_replace(source, target)
                            raise OSError("private error text must not escape")
                        return real_replace(source, target)
                    with mock.patch.object(files.os, "replace", side_effect=replace):
                        status, _, error = self.call("render", None, "--output")
                    self.assertEqual(status, 2)
                    self.assertNotIn("private", json.dumps(error))
                    self.assertFalse(self.path.with_suffix(".build.json").exists())
                    self.assertFalse(self.path.with_suffix(".writer").exists())
                    self.assertFalse(list(self.path.parent.glob(".interview-*.tmp")))
                    self.rejected("invalid_output", "review-validate", self.review_path)

    def test_old_build_removed_before_first_replace_and_new_marker_last(self):
        self.reviewed()
        real_replace = os.replace
        seen = []
        def replace(source, target):
            seen.append(Path(target).suffix)
            if len(seen) == 1:
                self.assertFalse(self.path.with_suffix(".build.json").exists())
                self.assertTrue(self.path.with_suffix(".writer").exists())
            return real_replace(source, target)
        with mock.patch.object(files.os, "replace", side_effect=replace):
            interview.render(self.root, self.path, True)
        self.assertEqual(seen, [".md", ".json"])

    def test_final_output_verification_failure_invalidates_new_marker(self):
        self.reviewed()
        with mock.patch.object(interview_review, "outputs", side_effect=files.Error("invalid_output", "failed verification")):
            with self.assertRaises(files.Error): interview.render(self.root, self.path, True)
        self.assertFalse(self.path.with_suffix(".build.json").exists())
        self.rejected("invalid_output", "review-validate", self.review_path)

    def test_recheck_source_change_after_staging_preserves_pack_but_cannot_pass(self):
        self.reviewed()
        before = self.path.read_bytes()
        real_recheck = interview.recheck_pack
        calls = 0
        def changed(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                profile = json.loads(self.profile_path.read_text(encoding="utf-8"))
                profile["contact"]["phone"] = "13900000000"
                write(self.profile_path, profile)
            return real_recheck(*args)
        with mock.patch.object(interview, "recheck_pack", side_effect=changed):
            with self.assertRaises(files.Error) as caught: interview.render(self.root, self.path, True)
        self.assertEqual(caught.exception.code, "stale_context")
        self.assertEqual(before, self.path.read_bytes())
        self.rejected("stale_context", "review-validate", self.review_path)

    def test_residual_writer_blocks_render_and_both_review_actions(self):
        self.reviewed()
        writer = self.path.with_suffix(".writer")
        writer.write_bytes(b"unknown owner")
        with self.assertRaises(files.Error) as caught: interview.render(self.root, self.path, True)
        self.assertEqual(caught.exception.code, "busy")
        self.rejected("busy", "review-draft")
        self.rejected("busy", "review-validate", self.review_path)
        self.assertEqual(writer.read_bytes(), b"unknown owner")

    def test_second_writer_cannot_enter_while_first_stages(self):
        real_recheck = interview.recheck_pack
        seen = []
        def recheck(*args):
            if self.path.with_suffix(".writer").exists() and not seen:
                seen.append(True)
                with self.assertRaises(files.Error) as caught: interview.render(self.root, self.path, True)
                self.assertEqual(caught.exception.code, "busy")
            return real_recheck(*args)
        with mock.patch.object(interview, "recheck_pack", side_effect=recheck):
            interview.render(self.root, self.path, True)
        self.assertEqual(seen, [True])
        self.assertTrue(interview_review.draft(self.root, self.path))

    def test_writer_replaced_during_publish_is_not_cleaned_as_ours(self):
        real_recheck = interview.recheck_pack
        calls = 0
        writer = self.path.with_suffix(".writer")
        def recheck(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                writer.unlink()
                writer.write_bytes(b"another owner")
            return real_recheck(*args)
        with mock.patch.object(interview, "recheck_pack", side_effect=recheck):
            with self.assertRaises(files.Error): interview.render(self.root, self.path, True)
        self.assertEqual(writer.read_bytes(), b"another owner")

    def test_read_detects_changed_identity_and_size_is_bounded(self):
        real_identity = files.identity
        calls = 0
        def changed(path):
            nonlocal calls
            calls += 1
            result = real_identity(path)
            return result if calls == 1 else (*result[:3], result[3] + 1)
        with mock.patch.object(files, "identity", side_effect=changed):
            with self.assertRaises(files.Error) as caught: files.read_bytes(self.root, ("interviews", self.job_id, "prep-1.json"))
        self.assertEqual(caught.exception.code, "stale_context")

    def test_process_interruption_leaves_writer_and_no_acceptable_review(self):
        self.reviewed()
        script = """
import os, sys
from jobsearch_cn import interview, interview_files as files
real = os.replace
count = 0
def replace(source, target):
    global count
    real(source, target)
    count += 1
    if count == 1:
        os._exit(73)
files.os.replace = replace
interview.render(sys.argv[1], sys.argv[2], True)
"""
        process = subprocess.run([sys.executable, "-c", script, str(self.root), str(self.path)], capture_output=True)
        self.assertEqual(process.returncode, 73, process.stderr)
        self.assertTrue(self.path.with_suffix(".writer").exists())
        self.assertFalse(self.path.with_suffix(".build.json").exists())
        self.rejected("busy", "review-validate", self.review_path)


class LinkedPaths(Data):
    def test_windows_junction_descendant_is_refused(self):
        if os.name != "nt":
            self.skipTest("Windows junction contract")
        actual = self.root / "actual-profile"
        (self.root / "profile").rename(actual)
        junction = self.root / "profile"
        process = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(actual)], capture_output=True)
        if process.returncode:
            self.skipTest("junction creation unavailable")
        self.addCleanup(junction.rmdir)
        self.rejected("unsafe_path")

    def link(self, target, link, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("symlink creation unavailable: " + type(exc).__name__)

    def test_linked_data_root_allowed_but_linked_descendant_refused(self):
        alias = self.root / "root-alias"
        self.link(self.root, alias, True)
        self.assertTrue(interview.validate(alias, alias / self.path.relative_to(self.root))["valid"])
        alias.unlink()
        outside = self.root / "separate-profile.json"
        self.profile_path.rename(outside)
        self.link(outside, self.profile_path)
        self.rejected("unsafe_path")

    def test_preexisting_output_link_is_never_overwritten(self):
        outside = self.root / "untouched.txt"
        outside.write_text("untouched", encoding="utf-8")
        self.link(outside, self.path.with_suffix(".md"))
        with self.assertRaises(files.Error): interview.render(self.root, self.path, True)
        self.assertEqual(outside.read_text(encoding="utf-8"), "untouched")

    def test_cleanup_rechecks_parent_and_leaves_outside_object(self):
        folder = self.root / "owned"
        folder.mkdir()
        owned = folder / "temp"
        owned.write_bytes(b"ours")
        token = files.identity(owned)
        moved = self.root / "moved"
        folder.rename(moved)
        self.link(moved, folder, True)
        files._remove_owned(self.root, ("owned", "temp"), token)
        self.assertTrue((moved / "temp").exists())

    def test_target_replaced_with_link_at_second_recheck_is_refused(self):
        probe = self.root / "probe-link"
        self.link(self.root, probe, True)
        probe.unlink()
        real_recheck = interview.recheck_pack
        calls = 0
        outside = self.root / "outside.txt"
        outside.write_bytes(b"untouched")
        def recheck(*args):
            nonlocal calls
            calls += 1
            if calls == 3:
                self.path.with_suffix(".build.json").symlink_to(outside)
            return real_recheck(*args)
        with mock.patch.object(interview, "recheck_pack", side_effect=recheck):
            with self.assertRaises(files.Error): interview.render(self.root, self.path, True)
        self.assertEqual(outside.read_bytes(), b"untouched")
