"""Public fictional regressions for interview disappearance and source warnings."""
from copy import deepcopy
import contextlib
import json
from pathlib import Path
from unittest import mock

from jobsearch_cn import interview, interview_files as files, interview_review, profile
from tests.test_cn_interview import Data, write


DISAPPEARED = "interview input disappeared after selection; reload sources and render again before review"
NO_PROJECT = "没有可引用项目：当前安全来源目录中没有可供逐条引用的项目事实；可先准备通用练习，或补充、核对项目记录。"


class Disappearance(Data):
    def assert_error(self, result, code="stale_context", status=1, message=None):
        actual, output, error = result
        self.assertEqual((actual, output, error["error"]["code"]), (status, None, code))
        if code == "stale_context":
            message = DISAPPEARED if message is None else message
        if message is not None:
            self.assertEqual(error["error"]["message"], message)

    def test_initial_explicit_missing_inputs_keep_exit_two(self):
        self.path.unlink()
        for action, target in (("validate", self.path), ("render", self.path),
                               ("review-draft", self.path), ("review-validate", self.review_path)):
            with self.subTest(action=action):
                self.assert_error(self.call(action, target), "missing_input", 2)

    def test_initial_explicit_json_size_and_io_errors_keep_exit_two(self):
        for action, target in (("validate", self.path), ("review-validate", self.review_path)):
            for raw, expected in ((b"{", "invalid_json"), (b" " * (files.LIMIT + 1), "too_large")):
                with self.subTest(action=action, expected=expected):
                    target.write_bytes(raw)
                    self.assert_error(self.call(action, target), expected, 2)
            target.write_bytes(b"{}")
            with mock.patch.object(Path, "open", side_effect=PermissionError("private path")):
                self.assert_error(self.call(action, target), "io_error", 2)

    def test_initial_missing_sources_keep_not_found(self):
        for target in (self.job_path, self.profile_path):
            with self.subTest(target=target.name):
                raw = target.read_bytes()
                target.unlink()
                self.assert_error(self.call("template", self.job_id), "not_found", 1)
                target.write_bytes(raw)

    def test_delete_after_locate_is_stale_for_pack_and_review(self):
        self.reviewed()
        locate = files.locate
        for action, target in (("validate", self.path), ("review-validate", self.review_path)):
            with self.subTest(action=action):
                raw = target.read_bytes()
                def removed(*args, **kwargs):
                    result = locate(*args, **kwargs)
                    target.unlink()
                    return result
                with mock.patch.object(files, "locate", side_effect=removed):
                    self.assert_error(self.call(action, target))
                target.write_bytes(raw)

    def test_delete_after_each_safe_read_check_is_stale(self):
        safe = files.safe
        raw = self.path.read_bytes()
        parts = self.path.relative_to(self.root).parts
        for check_number in (1, 2):
            with self.subTest(check_number=check_number):
                calls = 0
                def removed(*args, **kwargs):
                    nonlocal calls
                    result = safe(*args, **kwargs)
                    calls += 1
                    if calls == check_number:
                        self.path.unlink()
                    return result
                with mock.patch.object(files, "safe", side_effect=removed):
                    with self.assertRaises(files.Error) as caught:
                        files.read_bytes(self.root, parts)
                self.assertEqual((caught.exception.code, caught.exception.exit_code,
                                  caught.exception.message), ("stale_context", 1, DISAPPEARED))
                self.path.write_bytes(raw)

    def test_delete_between_stat_and_open_is_stale(self):
        identity = files.identity
        def removed(path):
            result = identity(path)
            path.unlink()
            return result
        with mock.patch.object(files, "identity", side_effect=removed):
            self.assert_error(self.call("validate"))

    def test_selected_local_bank_deleted_after_close_is_stale(self):
        write(self.bank_path, self.inputs.bank)
        opened = Path.open
        @contextlib.contextmanager
        def removed(path, *args, **kwargs):
            with opened(path, *args, **kwargs) as source:
                yield source
            if path == self.bank_path:
                path.unlink()
        with mock.patch.object(Path, "open", removed):
            self.assert_error(self.call("template", self.job_id, "--direction", "tech"))

    def test_selected_local_bank_disappears_before_final_selection(self):
        write(self.bank_path, self.inputs.bank)
        recheck = interview.recheck
        read = files.read
        builtin_reads = []
        def observed(root, parts, **kwargs):
            if parts[0] == "interview_questions":
                builtin_reads.append(parts)
            return read(root, parts, **kwargs)
        def removed(root, inputs):
            self.bank_path.unlink()
            return recheck(root, inputs)
        with mock.patch.object(interview, "recheck", side_effect=removed), \
                mock.patch.object(files, "read", side_effect=observed):
            self.assert_error(self.call("template", self.job_id, "--direction", "tech"))
        self.assertEqual(builtin_reads, [])

    def test_initial_absent_local_uses_builtin_and_absent_direction_is_configuration(self):
        result = interview.template(self.root, self.job_id, "tech")
        self.assertEqual(result["catalog"]["bank"]["origin"], "builtin")
        self.assert_error(self.call("template", self.job_id, "--direction", "unconfigured"), "configuration", 2)

    def test_selected_builtin_disappears_on_final_check(self):
        safe = files.safe
        seen = 0
        def unavailable(root, parts, **kwargs):
            nonlocal seen
            if parts[0] == "interview_questions":
                seen += 1
                if seen >= 3:  # First read completed both safe checks.
                    files.fail("missing_input", "interview input is missing", 2)
            return safe(root, parts, **kwargs)
        with mock.patch.object(files, "safe", side_effect=unavailable):
            self.assert_error(self.call("template", self.job_id, "--direction", "tech"))

    def test_final_source_disappearance_and_pack_disappearance(self):
        recheck = interview.recheck_pack
        for target in (self.job_path, self.profile_path, self.path):
            with self.subTest(target=target.name):
                raw = target.read_bytes()
                def removed(*args):
                    target.unlink()
                    return recheck(*args)
                with mock.patch.object(interview, "recheck_pack", side_effect=removed):
                    self.assert_error(self.call("validate"))
                target.write_bytes(raw)

    def test_bound_existing_bad_source_and_configuration_keep_specific_errors(self):
        recheck = interview.recheck_pack
        for target, raw, code, status in (
                (self.profile_path, b"{", "invalid_json", 2),
                (self.job_path, b"{}", "invalid_source", 1),
                (self.bank_path, b"{}", "configuration", 2),
                (self.bank_path, b"{", "invalid_json", 2),
                (self.path, b" " * (files.LIMIT + 1), "too_large", 2)):
            with self.subTest(code=code, target=target.name):
                previous = target.read_bytes() if target.exists() else None
                def changed(*args):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw)
                    return recheck(*args)
                with mock.patch.object(interview, "recheck_pack", side_effect=changed):
                    self.assert_error(self.call("validate"), code, status)
                if previous is None:
                    target.unlink()
                else:
                    target.write_bytes(previous)

    def test_nonmissing_io_and_unsafe_paths_do_not_become_stale(self):
        for failure, code, status in ((PermissionError("private path"), "io_error", 2),
                                      (OSError("private path"), "io_error", 2),
                                      (files.Error("unsafe_path", "unsafe"), "unsafe_path", 1)):
            with self.subTest(code=code, failure=type(failure).__name__):
                with mock.patch.object(files, "identity", side_effect=failure):
                    self.assert_error(self.call("validate"), code, status)

    def test_valid_review_missing_indirect_pack_is_stale(self):
        self.reviewed()
        self.path.unlink()
        self.assert_error(self.call("review-validate", self.review_path))

    def test_malformed_review_hash_does_not_establish_binding(self):
        original = self.reviewed()
        self.path.unlink()
        for record in ({"pack_hash": original["pack_hash"]}, {**original, "mode": "invalid"},
                       {**original, "created": "invalid"}, {**original, "pack_hash": "invalid"}):
            with self.subTest(record=record):
                write(self.review_path, record)
                self.assert_error(self.call("review-validate", self.review_path), "invalid", 1)

    def test_review_disappears_before_final_reread(self):
        self.reviewed()
        recheck = interview.recheck_pack
        def removed(*args):
            self.review_path.unlink()
            return recheck(*args)
        with mock.patch.object(interview, "recheck_pack", side_effect=removed):
            self.assert_error(self.call("review-validate", self.review_path))

    def test_missing_and_deleted_derived_outputs_remain_invalid_output(self):
        self.reviewed()
        for suffix in (".md", ".build.json"):
            target = self.path.with_suffix(suffix)
            raw = target.read_bytes()
            for during_read in (False, True):
                with self.subTest(suffix=suffix, during_read=during_read):
                    safe = files.safe
                    def removed(root, parts, **kwargs):
                        result = safe(root, parts, **kwargs)
                        if result == target:
                            target.unlink()
                        return result
                    if not during_read:
                        target.unlink()
                    with mock.patch.object(files, "safe", side_effect=removed if during_read else safe):
                        self.assert_error(self.call("review-validate", self.review_path), "invalid_output", 1)
                    target.write_bytes(raw)


class ProjectWarnings(Data):
    def candidate(self, entries):
        candidate = deepcopy(self.inputs.profile)
        candidate["experience"] = entries
        for skill in candidate["skills"]:
            skill["used_in"] = []
        self.assertEqual(profile.validate(candidate), [])
        write(self.profile_path, candidate)

    def template(self, warning=True):
        before = self.profile_path.read_bytes()
        status, result, error = self.call("template", self.job_id)
        self.assertEqual(status, 0, error)
        self.assertFalse(result["draft_ready"])
        self.assertEqual(result["warnings"], ["direction_unspecified"] + ([NO_PROJECT] if warning else []))
        self.assertEqual(self.profile_path.read_bytes(), before)
        return result

    def test_empty_experience_warns_but_generic_pack_still_validates(self):
        self.candidate([])
        result = self.template()
        self.assertEqual(result["catalog"]["experience"], [])
        self.pack = result["draft"]
        self.pack["direction"] = "tech"
        self.pack["context"] = interview.load(self.root, self.job_id, "tech").context
        bank = self.inputs.bank["questions"][0]
        self.pack["questions"] = [{"id": "q-1", "category": "general", "origin": "bank_practice",
            "question": bank["prompt"], "requirement_refs": [], "project_ref": None,
            "bank_ref": {"direction": "tech", "revision": 1, "id": bank["id"]}, "facts": [], "unknowns": []}]
        self.save()
        checked = interview.validate(self.root, self.path)
        self.assertEqual(checked["warnings"], ["no_jd_requirements", "no_project_questions"])
        self.assertFalse(checked["coverage_complete"])

    def test_all_ids_withheld_warns_without_leaking(self):
        entry = deepcopy(self.inputs.entries["proj-1"])
        entry["id"] = "private-marker"
        self.candidate([entry])
        candidate = json.loads(self.profile_path.read_text(encoding="utf-8"))
        candidate["contact"]["name"] = entry["id"]
        write(self.profile_path, candidate)
        result = self.template()
        self.assertEqual(result["catalog"]["experience"], [])
        self.assertGreater(result["catalog"]["withheld_count"], 0)
        self.assertNotIn(entry["id"], json.dumps(result, ensure_ascii=False))

    def test_ref_without_citable_facts_warns_and_preserves_projection(self):
        for value in ("联系 13800000000", None):
            with self.subTest(value=value):
                entry = deepcopy(self.inputs.entries["proj-1"])
                entry.update(name=value, org=None, role=None, bullets=[value] if value else [])
                self.candidate([entry])
                expected = interview.catalog(interview.load(self.root, self.job_id))
                result = self.template()
                self.assertEqual(result["catalog"], expected)
                self.assertEqual(result["catalog"]["experience"][0]["ref"], "proj-1")

    def test_any_experience_type_and_complete_safe_scalar_or_bullet_counts(self):
        for field in ("name", "org", "role", "bullets"):
            with self.subTest(field=field):
                entry = deepcopy(self.inputs.entries["exp-1"])
                entry.update(name="联系 13800000000", org=None, role=None, bullets=[])
                entry[field] = ["练" * 300] if field == "bullets" else "练" * 200
                self.candidate([entry])
                result = self.template(False)
                self.assertEqual(result["catalog"]["experience"][0]["type"], "internship")

    def test_warning_uses_one_safe_projection(self):
        inputs = interview.load(self.root, self.job_id)
        projected = interview.catalog(inputs)
        projected["experience"] = []
        with mock.patch.object(interview, "catalog", return_value=projected) as catalog:
            self.template()
        catalog.assert_called_once()

    def test_projected_fact_must_fit_complete_quote_limit(self):
        # Profile currently has tighter limits; exercise the catalog consumer's
        # fact boundary without treating oversized raw profile data as valid.
        projected = interview.catalog(interview.load(self.root, self.job_id))
        entry = projected["experience"][0]
        projected["experience"] = [entry]
        for field in ("name", "org", "role", "bullets"):
            for length in (500, 501):
                with self.subTest(field=field, length=length):
                    entry.update(name=None, org=None, role=None, bullets=[])
                    entry[field] = [{"index": 0, "text": "练" * length}] if field == "bullets" else "练" * length
                    with mock.patch.object(interview, "catalog", return_value=projected):
                        self.template(warning=length > 500)
