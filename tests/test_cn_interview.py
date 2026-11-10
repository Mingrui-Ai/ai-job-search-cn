"""Public fictional interview acceptance tests; no private profile, network or held-out data."""
from copy import deepcopy
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from jobsearch_cn import applications, cli, interview, interview_files as files, interview_review

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests/fixtures/cn/material/tech-m3/profile"
JD = REPO / "tests/fixtures/cn/jd/boss_intern.txt"


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main([str(arg) for arg in args])
    return code, json.loads(out.getvalue()) if out.getvalue() else None, json.loads(err.getvalue()) if err.getvalue() else None


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class Data(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        shutil.copytree(FIXTURE, self.root / "profile")
        code, output, error = run("jd", "parse", JD, "--save", "--data-dir", self.root)
        self.assertEqual(code, 0, error)
        self.job_id = output["jobs"][0]["id"]
        self.job_path = self.root / "jobs" / (self.job_id + ".json")
        self.profile_path = self.root / "profile/profile.json"
        self.path = self.root / "interviews" / self.job_id / "prep-1.json"
        self.review_path = self.path.with_name("review-prep-1-r1.json")
        self.bank_path = self.root / "templates/interviews/tech.json"
        self.inputs = interview.load(self.root, self.job_id, "tech")
        self.pack = interview.template(self.root, self.job_id, "tech")["draft"]
        self.pack["requirements"] = [{"id": "req-1", "quote": "参与 MySQL、Redis 等存储方案的设计与优化"}]
        project = self.inputs.entries["proj-1"]
        bank = self.inputs.bank["questions"][0]
        self.pack["questions"] = [
            {"id": "q-1", "category": "jd", "origin": "agent_practice", "question": "怎样比较两种存储方案？",
             "requirement_refs": ["req-1"], "project_ref": None, "bank_ref": None, "facts": [],
             "unknowns": [{"id": "u-1", "prompt": "是否有可核验的存储方案比较经历？", "answer": None}]},
            {"id": "q-2", "category": "project", "origin": "agent_practice", "question": "课程助手中的资料检索如何验证？",
             "requirement_refs": ["req-1"], "project_ref": "proj-1", "bank_ref": None,
             "facts": [{"ref": "proj-1", "field": "name", "quote": project["name"]},
                       {"ref": "proj-1", "field": "bullets", "index": 0, "quote": project["bullets"][0]}], "unknowns": []},
            {"id": "q-3", "category": "general", "origin": "bank_practice", "question": bank["prompt"],
             "requirement_refs": [], "project_ref": None,
             "bank_ref": {"direction": "tech", "revision": 1, "id": bank["id"]}, "facts": [], "unknowns": []}]
        self.pack["coverage"] = [{"requirement_ref": "req-1", "question_refs": ["q-1", "q-2"]}]
        self.save()

    def save(self):
        write(self.path, self.pack)

    def call(self, action, target=None, *extra):
        return run("interview", action, target or self.path, *extra, "--data-dir", self.root)

    def rejected(self, code=None, action="validate", target=None):
        status, output, error = self.call(action, target)
        self.assertIn(status, (1, 2), (status, output, error))
        self.assertIsNone(output)
        if code:
            self.assertEqual(error["error"]["code"], code, error)
        return error

    def reviewed(self):
        interview.render(self.root, self.path, True)
        record = interview_review.draft(self.root, self.path)["draft"]
        record.update(verdict="pass", checked_question_ids=[q["id"] for q in self.pack["questions"]])
        write(self.review_path, record)
        return record


class Packs(Data):
    def test_three_categories_and_exact_facts_validate(self):
        status, result, err = self.call("validate")
        self.assertEqual(status, 0, err)
        self.assertEqual(result["question_count"], 3)
        self.assertTrue(result["coverage_complete"])

    def test_template_is_safe_but_empty_draft_cannot_render(self):
        before = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*"))
        template = interview.template(self.root, self.job_id)
        self.assertFalse(template["draft_ready"])
        self.assertIn("direction_unspecified", template["warnings"])
        raw = json.dumps(template, ensure_ascii=False)
        for private in ("13800000000", "liming@example.com", "resume.txt", str(self.root)):
            self.assertNotIn(private, raw)
        self.assertEqual(template["catalog"]["experience"][0]["source_type"], "source_file")
        self.assertEqual(before, sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*")))
        self.pack = template["draft"]
        self.save()
        self.rejected("invalid", "render")

    def test_generic_only_warns_without_claiming_complete_coverage(self):
        self.pack["questions"] = self.pack["questions"][-1:]
        self.pack["requirements"] = self.pack["coverage"] = []
        self.save()
        result = interview.validate(self.root, self.path)
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["warnings"], ["no_jd_requirements", "no_project_questions"])

    def test_question_id_and_unknown_id_uniqueness(self):
        original = deepcopy(self.pack)
        for field in ("question", "unknown"):
            with self.subTest(field=field):
                self.pack = deepcopy(original)
                if field == "question":
                    self.pack["questions"][1]["id"] = "q-1"
                else:
                    self.pack["questions"][1]["unknowns"] = deepcopy(self.pack["questions"][0]["unknowns"])
                self.save(); self.rejected("invalid")

    def test_unknown_must_stay_null(self):
        self.pack["questions"][0]["unknowns"][0]["answer"] = "我做过"
        self.save(); self.rejected("invalid")

    def test_coverage_is_bidirectional_and_complete(self):
        for value in ([], [{"requirement_ref": "req-1", "question_refs": ["q-1"]}],
                      [{"requirement_ref": "req-1", "question_refs": ["q-1", "q-2", "q-3"]}]):
            with self.subTest(value=value):
                self.pack["coverage"] = value
                self.save(); self.rejected("invalid_reference")

    def test_uncovered_requirement_is_explicit_warning(self):
        self.pack["requirements"].append({"id": "req-2", "quote": "每周至少实习4天"})
        self.pack["coverage"].append({"requirement_ref": "req-2", "question_refs": []})
        self.save()
        result = interview.validate(self.root, self.path)
        self.assertFalse(result["coverage_complete"])
        self.assertIn("uncovered_requirements", result["warnings"])

    def test_facts_require_full_same_project_field(self):
        fact = deepcopy(self.pack["questions"][1]["facts"][1])
        for delta in ({"ref": "exp-1"}, {"index": True}, {"index": -1}, {"quote": "基于 LangChain"}, {"source": "profile"}):
            with self.subTest(delta=delta):
                self.pack["questions"][1]["facts"][1] = {**fact, **delta}
                self.save(); self.rejected()

    def test_scalar_fact_cannot_have_index_and_general_cannot_have_facts(self):
        self.pack["questions"][1]["facts"][0]["index"] = 0
        self.save(); self.rejected("invalid")
        del self.pack["questions"][1]["facts"][0]["index"]
        self.pack["questions"][2]["facts"] = deepcopy(self.pack["questions"][1]["facts"])
        self.save(); self.rejected("invalid")

    def test_general_prompt_and_bank_revision_are_exact(self):
        self.pack["questions"][2]["question"] += "补充"
        self.save(); self.rejected("invalid_reference")
        self.pack["questions"][2]["question"] = self.inputs.bank["questions"][0]["prompt"]
        self.pack["questions"][2]["bank_ref"]["revision"] = True
        self.save(); self.rejected("invalid_reference")

    def test_limits_and_wrong_shapes_fail_without_traceback(self):
        original = deepcopy(self.pack)
        mutations = [("questions", []), ("questions", original["questions"] * 7), ("requirements", {}),
                     ("schema_version", True), ("context", {}), ("direction", []), ("created", "2026-11-11")]
        for field, value in mutations:
            with self.subTest(field=field):
                self.pack = {**deepcopy(original), field: value}
                self.save(); self.rejected("invalid")

    def test_nontech_and_custom_directions(self):
        for direction in ("default", "data", "product", "ops"):
            with self.subTest(direction=direction):
                result = interview.template(self.root, self.job_id, direction)
                self.assertEqual(result["catalog"]["bank"]["direction"], direction)
        bank = deepcopy(self.inputs.bank)
        bank["direction"] = "custom"
        for q in bank["questions"]: q["id"] = q["id"].replace("tech.", "custom.")
        write(self.bank_path.with_name("custom.json"), bank)
        self.assertEqual(interview.template(self.root, self.job_id, "custom")["catalog"]["bank"]["origin"], "local")


class Binding(Data):
    def test_json_format_and_key_order_do_not_invalidate(self):
        for path in (self.path, self.job_path, self.profile_path):
            value = json.loads(path.read_text(encoding="utf-8"))
            path.write_text(json.dumps(dict(reversed(list(value.items()))), ensure_ascii=False), encoding="utf-8")
        self.assertTrue(interview.validate(self.root, self.path)["valid"])

    def test_source_metadata_only_change_invalidates(self):
        job = json.loads(self.job_path.read_text(encoding="utf-8"))
        job["source"]["imported_at"] = "2026-11-10T00:00:00Z"
        write(self.job_path, job)
        self.rejected("stale_context")

    def test_contact_only_change_invalidates(self):
        profile = json.loads(self.profile_path.read_text(encoding="utf-8"))
        profile["contact"]["phone"] = "13900000000"
        write(self.profile_path, profile)
        self.rejected("stale_context")

    def test_pack_created_is_part_of_review_digest(self):
        self.reviewed()
        self.pack["created"] = "2026-11-09T00:00:00Z"
        self.save()
        self.rejected("stale_context", "review-validate", self.review_path)

    def test_same_bank_content_switching_origin_invalidates_both_ways(self):
        write(self.bank_path, self.inputs.bank)
        self.rejected("stale_context")
        self.pack["context"] = interview.template(self.root, self.job_id, "tech")["context"]
        self.save()
        self.assertTrue(interview.validate(self.root, self.path)["valid"])
        self.bank_path.unlink()
        self.rejected("stale_context")

    def test_full_provenance_change_invalidates_without_printing_it(self):
        bank = deepcopy(self.inputs.bank)
        write(self.bank_path, bank)
        self.pack["context"] = interview.template(self.root, self.job_id, "tech")["context"]
        self.save()
        bank["provenance"]["source_ref"] = "C:/private/source.txt"
        write(self.bank_path, bank)
        error = self.rejected("stale_context")
        self.assertNotIn("private", json.dumps(error))

    def test_unselected_broken_bank_is_not_read(self):
        self.bank_path.parent.mkdir(parents=True)
        self.bank_path.with_name("ops.json").write_bytes(b"not json")
        self.assertTrue(interview.validate(self.root, self.path)["valid"])

    def test_bound_missing_source_and_initial_missing_job_have_distinct_errors(self):
        self.job_path.unlink()
        self.rejected("stale_context")
        status, _, error = self.call("template", self.job_id)
        self.assertEqual((status, error["error"]["code"]), (1, "not_found"))

    def test_override_added_at_final_check_is_detected(self):
        recheck = interview.recheck_pack
        def changed(*args):
            write(self.bank_path, self.inputs.bank)
            return recheck(*args)
        with mock.patch.object(interview, "recheck_pack", side_effect=changed):
            self.rejected("stale_context", "render")


class Privacy(Data):
    def test_sensitive_strings_rejected_in_all_pack_text_slots(self):
        original = deepcopy(self.pack)
        samples = ["a@example.test", "https://example.test", "www.example.test", "mailto:a", "data:x", "file:x",
                   r"\\server\share", r"C:\private\x", "138 0000 0000", "微信：abc", "QQ:abc", "李明", "１３８００００００００", "a\x00b"]
        for sample in samples:
            for slot in ("question", "unknown", "quote", "fact"):
                with self.subTest(sample=sample, slot=slot):
                    self.pack = deepcopy(original)
                    if slot == "question": self.pack["questions"][0]["question"] = sample
                    elif slot == "unknown": self.pack["questions"][0]["unknowns"][0]["prompt"] = sample
                    elif slot == "quote": self.pack["requirements"][0]["quote"] = sample
                    else: self.pack["questions"][1]["facts"][0]["quote"] = sample
                    self.save(); self.rejected("unsafe_text")

    def test_sensitive_job_line_is_withheld_whole_and_safe_substring_cannot_escape(self):
        job = json.loads(self.job_path.read_text(encoding="utf-8"))
        job["raw_text"] += "\n独立安全片段 联系13800000000"
        write(self.job_path, job)
        template = interview.template(self.root, self.job_id, "tech")
        self.assertTrue(template["catalog"]["job"]["lines"][-1]["withheld"])
        self.assertNotIn("独立安全片段", json.dumps(template, ensure_ascii=False))
        self.pack["context"] = template["context"]
        self.pack["requirements"][0]["quote"] = "独立安全片段"
        self.save(); self.rejected("unsafe_text")

    def test_sensitive_profile_field_is_withheld_and_not_citable(self):
        profile = json.loads(self.profile_path.read_text(encoding="utf-8"))
        profile["experience"][1]["name"] = "课程系统 联系13800000000"
        write(self.profile_path, profile)
        template = interview.template(self.root, self.job_id, "tech")
        self.assertIsNone(template["catalog"]["experience"][1]["name"])
        self.pack["context"] = template["context"]
        self.pack["questions"][1]["facts"][0]["quote"] = profile["experience"][1]["name"]
        self.save(); self.rejected("unsafe_text")

    def test_markdown_external_text_is_fenced_without_language(self):
        text = "```\n<img src=x>\n[link](relative)\n~~~\n````"
        self.pack["questions"][0]["question"] = text
        self.save()
        result = interview.render(self.root, self.path)
        self.assertIn("`````\n" + text + "\n`````", result["markdown"])
        interview.render(self.root, self.path, True)
        self.assertEqual(self.path.with_suffix(".md").read_bytes(), result["markdown"].encode("utf-8"))
        self.assertNotIn("审核通过", result["markdown"])

    def test_bank_description_and_prompts_cannot_leak(self):
        for slot in ("notice", "license", "prompt", "tags", "prep_prompts"):
            with self.subTest(slot=slot):
                bank = deepcopy(self.inputs.bank)
                if slot in ("notice", "license"): bank["provenance"][slot] = "a@example.test"
                else: bank["questions"][0][slot] = ["a@example.test"] if slot != "prompt" else "a@example.test"
                write(self.bank_path, bank)
                status, _, error = self.call("template", self.job_id, "--direction", "tech")
                self.assertEqual(status, 2)
                self.assertEqual(error["error"]["code"], "configuration")
                self.assertNotIn("example.test", json.dumps(error))


class Parsing(Data):
    def test_strict_json_rejects_duplicate_nonfinite_unicode_and_encoding(self):
        for payload in (b'{"kind":1,"kind":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":1e9999}',
                        b'{"a":"\\ud800"}', b'\xff', b'[[[[', b'"' + b'a' * (files.LIMIT + 1) + b'"'):
            with self.subTest(payload=payload[:30]):
                self.path.write_bytes(payload)
                error = self.rejected()
                self.assertIn(error["error"]["code"], ("invalid_json", "too_large"))

    def test_timestamp_boundaries(self):
        for value in ("2026-11-11T00:00:00Z", "2026-11-11T00:00:00.123456+08:00"):
            files.timestamp(value)
        for value in ("9999-12-31T23:59:59Z", "0001-01-01T00:00:00+08:00", "2026-02-30T00:00:00Z",
                      "2026-11-11T00:00Z", "2026-11-11T00:00:00", "2026-11-11T00:00:00.1234567Z",
                      "2026-11-11T00:00:00+01:99", True):
            with self.subTest(value=value), self.assertRaises(files.Error): files.timestamp(value)

    def test_path_names_cross_job_and_ads_rejected(self):
        for path in (self.path.with_name("prep-01.json"), self.path.with_name("prep-1.json:secret"),
                     self.root / "prep-1.json", self.path.parent / ".." / self.path.parent.name / self.path.name):
            with self.subTest(path=path): self.rejected("unsafe_path", target=path)
        other = self.root / "interviews/job_aaaaaaaaaaaa/prep-1.json"
        write(other, self.pack)
        self.rejected("invalid_reference", target=other)

    def test_invalid_cli_arguments_are_safe_json_and_no_abbreviations(self):
        for args in (("render", self.path, "--out"), ("review-draft", self.path, "--round", "secret@example.test"),
                     ("template", self.job_id, "--profile", "C:/private/x"), ("unknown", "private")):
            status, _, error = run("interview", *args)
            self.assertEqual(status, 2)
            self.assertEqual(error["error"]["code"], "arguments")
            self.assertNotIn("secret", json.dumps(error))

    def test_malformed_source_is_safe_error(self):
        for value in ({}, [], {"contact": []}):
            write(self.profile_path, value)
            self.rejected("invalid_source")

    def test_cli_subprocess_utf8_and_no_unrelated_side_effects(self):
        before = {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.root.rglob("*") if p.is_file()}
        process = subprocess.run([sys.executable, "-m", "jobsearch_cn", "interview", "render", str(self.path),
                                  "--data-dir", str(self.root)], cwd=REPO, capture_output=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("面试准备包", json.loads(process.stdout.decode("utf-8"))["markdown"])
        after = {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


class Reviews(Data):
    def test_draft_does_not_preapprove_or_pretend_checked(self):
        interview.render(self.root, self.path, True)
        result = interview_review.draft(self.root, self.path)
        self.assertFalse(result["draft_ready"])
        self.assertIsNone(result["draft"]["verdict"])
        self.assertEqual(result["draft"]["checked_question_ids"], [])
        write(self.review_path, result["draft"])
        self.rejected("invalid", "review-validate", self.review_path)

    def test_final_review_must_check_each_question_once(self):
        record = self.reviewed()
        for checked in ([], ["q-1", "q-2"], ["q-1", "q-2", "q-3", "q-3"]):
            with self.subTest(checked=checked):
                record["checked_question_ids"] = checked
                write(self.review_path, record)
                self.rejected(action="review-validate", target=self.review_path)

    def test_revise_is_valid_and_self_is_disclosed(self):
        record = self.reviewed()
        record.update(verdict="revise", mode="self", findings=[{"item": "I3", "path": "questions[0].question",
                      "severity": "must", "reason": "题干需要澄清边界", "suggestion": None}])
        write(self.review_path, record)
        status, output, error = self.call("review-validate", self.review_path)
        self.assertEqual(status, 0, error)
        self.assertEqual(output["verdict"], "revise")
        self.assertIn("self_review", output["warnings"])
        record["verdict"] = "pass"
        write(self.review_path, record)
        self.rejected("invalid", "review-validate", self.review_path)

    def test_findings_paths_items_and_private_text_checked(self):
        record = self.reviewed()
        finding = {"item": "I3", "path": "questions[0].question", "severity": "suggest", "reason": "澄清边界", "suggestion": None}
        for delta in ({"item": "I9"}, {"path": "questions[5]"}, {"reason": "a@example.test"}, {"suggestion": "微信：abc"}):
            with self.subTest(delta=delta):
                record["findings"] = [{**finding, **delta}]
                write(self.review_path, record)
                self.rejected(action="review-validate", target=self.review_path)

    def test_output_bytes_and_completion_marker_are_required(self):
        self.reviewed()
        output = self.path.with_suffix(".md")
        output.write_bytes(output.read_bytes() + b"\n")
        self.rejected("invalid_output", "review-validate", self.review_path)
        output.unlink()
        self.rejected("invalid_output", "review-draft")

    def test_repeated_render_is_deterministic_and_review_remains_bound(self):
        self.reviewed()
        before = self.path.with_suffix(".md").read_bytes()
        interview.render(self.root, self.path, True)
        self.assertEqual(before, self.path.with_suffix(".md").read_bytes())
        self.assertEqual(interview_review.validate(self.root, self.review_path)["verdict"], "pass")


class Separation(Data):
    def test_application_core_rejects_interview_by_content_without_validator(self):
        disguised = self.path.with_name("resume-1.json")
        write(disguised, self.pack)
        for path in (self.path, disguised):
            with self.assertRaises(applications.ApplicationError):
                applications.prepare_materials(self.root, self.job_id, path)

    def test_followup_error_and_other_unknown_material_contract_unchanged(self):
        path = self.path.with_name("material.json")
        write(path, {"job_id": self.job_id, "kind": "followup"})
        with self.assertRaises(Exception) as caught:
            applications.prepare_materials(self.root, self.job_id, path)
        self.assertIn("followup materials cannot be archived", str(caught.exception))
        write(path, {"job_id": self.job_id, "kind": "old-unknown"})
        self.assertIsNotNone(applications.prepare_materials(self.root, self.job_id, path)["version"])

    def test_sent_attachment_remains_a_fact_record(self):
        result = applications.prepare_materials(self.root, self.job_id, sent_paths=[self.path])
        self.assertTrue(result["files"])

    def test_old_material_review_and_resume_commands_do_not_accept_prep_kind(self):
        for args in (("material", "validate", self.path), ("material", "render", self.path),
                     ("resume", "build", self.path), ("review", "draft", self.path)):
            with self.subTest(args=args):
                code, _, _ = run(*args, "--data-dir", self.root)
                self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
