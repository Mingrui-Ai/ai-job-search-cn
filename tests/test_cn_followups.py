"""Followup source bindings and CLI delivery, using only fictional temporary records."""
import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from jobsearch_cn import applications, build_notes, cli, followups, messages, review, score
from tests.test_cn_applications import Data, FIXTURE
from tests.test_cn_messages import TECH_JOB, TECH_PROFILE, VOCABULARY


class Context(Data):
    def setUp(self):
        super().setUp()
        self.app = self.historical()

    def inputs(self, app=None, **kwargs):
        app = app or self.app
        return followups.load(self.data, app, self.job, self.show(app)["revision"], **kwargs)

    def record(self, inputs=None):
        inputs = inputs or self.inputs()
        return {"schema_version": 1, "kind": "followup", "job_id": self.job,
                "profile_hash": score.profile_hash(inputs.profile), "created": "2026-11-11T01:00:00+08:00",
                "direction": "default", "template": inputs.template["template"], "subject": None,
                "context": inputs.context, "segments": [
                    {"slot": "context", "text": "您好，我此前提交了{job.title}岗位的申请。",
                     "refs": ["job", inputs.submitted_id]},
                    {"slot": "request", "text": "想请问目前的招聘进展，是否还需要补充材料？谢谢。", "refs": []}]}

    def test_context_is_read_only_complete_and_uses_current_job(self):
        before = {p: p.read_bytes() for p in self.data.rglob("*") if p.is_file()}
        with mock.patch.object(Path, "mkdir", side_effect=AssertionError("read-only context")):
            result = self.inputs()
        self.assertEqual(before, {p: p.read_bytes() for p in self.data.rglob("*") if p.is_file()})
        self.assertEqual(result.facts["submitted_date"], "2026-10-20")
        self.assertEqual(result.facts["archived_job_comparison"], "unavailable")
        self.assertEqual(set(result.context), set(followups.KEYS))
        self.assertNotIn("contact", followups.template_result(result))
        self.assertEqual(followups.check(self.data, self.record(result)).context, result.context)

    def test_empty_database_lookup_creates_nothing(self):
        missing = self.data / "empty"
        with self.assertRaises(followups.ContextError):
            followups.load(missing, self.app, self.job, 1)
        self.assertFalse(missing.exists())

    def test_drafted_and_terminal_records_are_not_eligible(self):
        other = self.drafted()
        with self.assertRaisesRegex(followups.ContextError, "submitted"):
            self.inputs(other)
        for state in ("applied", "interview", "offer"):
            if state != "applied":
                self.move(self.app, state)
            self.assertEqual(self.inputs().facts["status"], state)
        self.move(self.app, "hired")
        with self.assertRaisesRegex(followups.ContextError, "not open"):
            self.inputs()

    def test_wrong_job_revision_and_projection_are_refused_safely(self):
        with self.assertRaisesRegex(followups.ContextError, "job_id"):
            followups.load(self.data, self.app, "job_000000000001", 2)
        with self.assertRaisesRegex(followups.ContextError, "stale_revision"):
            followups.load(self.data, self.app, self.job, 1)
        with self.connect() as connection:
            connection.execute("UPDATE applications SET channel_platform = ? WHERE application_id = ?",
                               ("private@example.com", self.app))
        with self.assertRaises(followups.ContextError) as error:
            self.inputs()
        self.assertNotIn("private@example.com", str(error.exception))

    def test_occurrence_date_is_not_recording_date_and_uses_beijing(self):
        other = self.write("record", self.job, "--channel", "other", "--submitted", "--historical")
        app = other["application"]["application_id"]
        self.assertIsNone(self.inputs(app).facts["submitted_date"])
        dated = self.write("record", self.job, "--channel", "other", "--submitted", "--historical",
                           "--at", "2026-10-10T18:00:00Z")["application"]["application_id"]
        self.assertEqual(self.inputs(dated).facts["submitted_date"], "2026-10-11")

    def test_full_profile_job_and_application_changes_invalidate(self):
        for field, path, mutate in (
            ("profile_input_hash", self.data / "profile" / "profile.json", lambda d: d["contact"].update(name="虚构新名字")),
            ("job_hash", self.data / "jobs" / f"{self.job}.json", lambda d: d.update(status="expired"))):
            original = path.read_bytes()
            record = self.record()
            data = json.loads(original)
            mutate(data)
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(followups.ContextError, field):
                followups.check(self.data, record)
            path.write_bytes(original)
        record = self.record()
        self.write("note", self.app, "--text", "虚构待办", "--expected-revision", record["context"]["application_revision"])
        with self.assertRaisesRegex(followups.ContextError, "stale_revision"):
            followups.check(self.data, record)

    def test_same_revision_different_payload_and_formatting(self):
        record = self.record()
        profile_path = self.data / "profile" / "profile.json"
        profile_path.write_text(json.dumps(json.loads(profile_path.read_bytes()), indent=7, sort_keys=True), encoding="utf-8")
        self.assertEqual(followups.check(self.data, record).context, record["context"])
        with self.connect() as connection:
            # Consistent row/events with the same revision, but a different original submission date.
            connection.execute("UPDATE events SET occurred_on = '2026-10-19' WHERE application_id = ? AND type = 'submitted'", (self.app,))
            connection.execute("UPDATE applications SET submitted_on = '2026-10-19' WHERE application_id = ?", (self.app,))
        with self.assertRaisesRegex(followups.ContextError, "application_hash"):
            followups.check(self.data, record)

    def test_job_hash_covers_raw_optional_fields_before_upgrade(self):
        path = self.data / "jobs" / f"{self.job}.json"
        data = json.loads(path.read_bytes())
        data.pop("interview")
        path.write_text(json.dumps(data), encoding="utf-8")
        record = self.record()
        data["interview"] = None
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(followups.ContextError, "job_hash"):
            followups.check(self.data, record)

    def test_sensitive_and_voided_events_are_not_referenceable(self):
        revision = self.show(self.app)["revision"]
        result = self.write("note", self.app, "--text", "虚构联系 private@example.com", "--expected-revision", revision)
        event_id = result["events"][0]["event_id"]
        inputs = self.inputs()
        self.assertNotIn(event_id, inputs.events)
        self.assertTrue(inputs.facts["events"][-1]["withheld"])
        self.assertNotIn("private@example.com", json.dumps(followups.template_result(inputs)))
        self.write("void", self.app, "--reason", "虚构纠错", "--expected-revision", self.show(self.app)["revision"])
        self.assertNotIn(event_id, {e["event_id"] for e in self.inputs().facts["events"]})


class TemplateCompatibility(Data):
    def test_old_user_default_keeps_its_revision_and_only_followup_falls_back(self):
        user = self.data / messages.USER_DIR
        user.mkdir(parents=True)
        old = json.loads((messages.BUILTIN / "default.json").read_bytes())
        old.pop("followup")
        old["revision"] = 9
        old["greeting"]["max_chars"] = 91
        (user / "default.json").write_text(json.dumps(old), encoding="utf-8")
        templates = messages.load_templates(self.data)
        result = messages.template_for(TECH_JOB, TECH_PROFILE, VOCABULARY, templates, "followup")
        self.assertEqual((result["template"], result["template_source"]), ("default/followup@1", "builtin/default"))
        legacy = messages.template_for(TECH_JOB, TECH_PROFILE, VOCABULARY, templates, "greeting", "default")
        self.assertEqual((legacy["template"], legacy["spec"]["max_chars"]), ("default/greeting@9", 91))

    def test_user_followup_identity_and_nondefault_rejection(self):
        user = self.data / messages.USER_DIR
        user.mkdir(parents=True)
        custom = json.loads((messages.BUILTIN / "default.json").read_bytes())
        custom["revision"] = 7
        custom["followup"]["max_chars"] = 100
        (user / "default.json").write_text(json.dumps(custom), encoding="utf-8")
        templates = messages.load_templates(self.data)
        result = messages.template_for(TECH_JOB, TECH_PROFILE, VOCABULARY, templates, "followup", "default")
        self.assertEqual((result["template"], result["template_source"], result["spec"]["max_chars"]),
                         ("default/followup@7", "user/default", 100))
        with self.assertRaises(messages.TemplateError):
            messages.template_for(TECH_JOB, TECH_PROFILE, VOCABULARY, templates, "followup", "tech")

    def test_custom_spec_can_omit_optional_progress_but_cannot_drop_required_context(self):
        user = self.data / messages.USER_DIR
        user.mkdir(parents=True)
        custom = json.loads((messages.BUILTIN / "default.json").read_bytes())
        custom["followup"]["slots"] = [slot for slot in custom["followup"]["slots"] if slot["slot"] != "progress"]
        path = user / "default.json"
        path.write_text(json.dumps(custom), encoding="utf-8")
        self.assertEqual(len(messages.load_templates(self.data)["default"]["followup"]["slots"]), 2)
        custom["followup"]["slots"][0]["required"] = "true"
        path.write_text(json.dumps(custom), encoding="utf-8")
        with self.assertRaises(messages.TemplateError):
            messages.load_templates(self.data)


class Delivery(Data):
    inputs = Context.inputs
    record = Context.record

    def setUp(self):
        super().setUp()
        self.app = self.historical()
        self.source = self.material.parent / "followup-1.json"
        self.review_file = self.material.parent / "review-followup-1-r1.json"

    def command(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main([*map(str, args), "--data-dir", str(self.data)])
        return code, out.getvalue(), err.getvalue()

    def save_record(self, record):
        self.source.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    def prepare(self, record=None, *, profile_path=None):
        record = record or self.record()
        self.save_record(record)
        extra = ["--profile", profile_path] if profile_path else []
        code, out, err = self.command("material", "render", self.source, "--output", *extra)
        self.assertEqual(code, 0, out + err)
        self.rendered = json.loads(out)
        # Synthetic pass exercises the validator; it is not an independent review of real material.
        report = {"schema_version": 1, "kind": "followup-review", "job_id": self.job,
                  "material": self.source.name, "material_hash": review.material_hash(record),
                  "round": 1, "mode": "independent", "created": "2026-11-11T01:00:00+08:00",
                  "verdict": "pass", "findings": [], "coverage": []}
        self.review_file.write_text(json.dumps(report), encoding="utf-8")
        return record

    def five(self, expected, fragment=None, extra=()):
        commands = [("material", "validate", self.source), ("material", "render", self.source, "--output"),
                    ("review", "draft", self.source), ("review", "validate", self.review_file),
                    ("review", "show", self.review_file)]
        for args in commands:
            with self.subTest(command=args[:2]):
                code, out, err = self.command(*args, *extra)
                self.assertEqual(code, expected, out + err)
                if fragment:
                    self.assertIn(fragment, out + err)

    def test_full_template_render_review_loop_does_not_change_sources(self):
        code, out, err = self.command("material", "template", self.job, "--kind", "followup",
                                       "--application", self.app, "--expected-revision", 2)
        self.assertEqual(code, 0, err)
        template = json.loads(out)
        self.assertEqual(template["context"], self.inputs().context)
        source_files = [self.paths.db, self.data / "jobs" / f"{self.job}.json", self.data / "profile" / "profile.json"]
        before = {p: p.read_bytes() for p in source_files}
        self.prepare()
        self.five(0)
        self.assertEqual(before, {p: p.read_bytes() for p in source_files})
        text = Path(self.rendered["text"]).read_text(encoding="utf-8")
        self.assertNotIn("标题", text)
        self.assertIn("此前提交", text)
        self.assertEqual(self.rendered["max_chars"], 300)
        self.assertEqual(self.rendered["context_status"], "current_at_check")

    def test_all_five_reject_each_source_change_even_with_old_pass_and_output(self):
        profile_file = self.data / "profile" / "profile.json"
        job_file = self.data / "jobs" / f"{self.job}.json"
        user = self.data / messages.USER_DIR
        user.mkdir(parents=True)
        banned_file = user / "banned.json"
        for field, path, changed in (
            ("profile_input_hash", profile_file, lambda d: d["contact"].update(name="虚构新姓名")),
            ("job_hash", job_file, lambda d: d.update(status="expired"))):
            with self.subTest(field=field):
                raw = path.read_bytes()
                self.prepare()
                original_output = Path(self.rendered["text"]).read_bytes()
                value = json.loads(raw)
                changed(value)
                path.write_text(json.dumps(value), encoding="utf-8")
                self.five(1, field)
                self.assertEqual(Path(self.rendered["text"]).read_bytes(), original_output)
                path.write_bytes(raw)
        self.prepare()
        banned_file.write_text(json.dumps({"warnings": [{"words": ["虚构警告"], "reason": "测试"}]}), encoding="utf-8")
        self.five(1, "template_hash")
        banned_file.unlink()
        self.prepare()
        self.write("reply", self.app, "--summary", "虚构回复：等待安排", "--expected-revision", 2)
        self.five(1, "stale_revision")

    def test_event_mutations_and_terminal_qualification_reach_all_five(self):
        actions = [("note", "--text", "虚构补充"), ("followup", "--due", "2099-01-05"),
                   ("followup", "--cancel"), ("void", "--reason", "虚构撤销")]
        for command, *extra in actions:
            self.prepare()
            self.write(command, self.app, *extra, "--expected-revision", self.show(self.app)["revision"])
            self.five(1, "stale_revision")
        self.prepare()
        self.move(self.app, "no_response")
        self.five(1, "not open")

    def test_typed_dates_and_events_cannot_back_skills_or_numbers(self):
        inputs = self.inputs()
        record = self.record(inputs)
        record["segments"][0]["text"] = "您好，我在{" + inputs.submitted_id + ".occurred_date}提交了{job.title}岗位申请。"
        self.prepare(record)
        self.assertIn("2026年10月20日", Path(self.rendered["text"]).read_text(encoding="utf-8"))
        result = self.write("note", self.app, "--text", "岗位要求 51 年 Java", "--expected-revision", 2)
        event_id = result["events"][0]["event_id"]
        record = self.record()
        record["segments"].insert(1, {"slot": "progress", "text": "我有 51 年 Java 经历。", "refs": [event_id]})
        self.save_record(record)
        code, out, _ = self.command("material", "validate", self.source)
        self.assertEqual(code, 1)
        self.assertIn("51", out)
        self.assertIn("Java", out)
        self.assertNotIn("岗位要求", out)

    def test_unknown_date_foreign_withheld_and_unsupported_refs(self):
        other = self.write("record", self.job, "--channel", "other", "--submitted", "--historical")["application"]["application_id"]
        unknown = self.inputs(other)
        record = self.record(unknown)
        record["segments"][0]["text"] = "在{" + unknown.submitted_id + ".occurred_date}提交申请。"
        self.save_record(record)
        self.assertIn("unknown", self.command("material", "validate", self.source)[1])
        self.write("note", self.app, "--text", "虚构 private@example.com", "--expected-revision", 2)
        app = self.show(self.app)
        blocked = [unknown.submitted_id, app["events"][0]["event_id"], app["events"][-1]["event_id"], "evt_" + "0" * 32]
        for event_id in blocked:
            record = self.record()
            record["segments"].insert(1, {"slot": "progress", "text": "询问进展。", "refs": [event_id]})
            self.save_record(record)
            code, out, _ = self.command("material", "validate", self.source)
            self.assertEqual(code, 1, out)
            self.assertIn("not a usable effective event", out)

    def test_context_shape_required_submission_ref_and_subject(self):
        base = self.record()
        changes = [("context", None), ("context", {**base["context"], "application_revision": True}),
                   ("context", {**base["context"], "job_hash": "x"}), ("context", {**base["context"], "path": "secret"}),
                   ("subject", {"text": "标题", "refs": []}), ("direction", "tech"), ("template", "default/followup@99")]
        for key, value in changes:
            self.save_record({**base, key: value})
            self.assertEqual(self.command("material", "validate", self.source)[0], 1, key)
        record = copy.deepcopy(base)
        record["segments"][0]["refs"].remove(self.inputs().submitted_id)
        self.save_record(record)
        self.assertIn("must cite", self.command("material", "validate", self.source)[1])

    def test_custom_profile_review_and_last_check_detect_changes(self):
        profile_file = self.data / "custom-profile.json"
        data = json.loads((self.data / "profile" / "profile.json").read_bytes())
        data["contact"]["name"] = "虚构另名"
        profile_file.write_text(json.dumps(data), encoding="utf-8")
        record = self.record(self.inputs(profile_path=profile_file))
        self.prepare(record, profile_path=profile_file)
        self.five(0, extra=("--profile", profile_file))
        self.five(1, "profile_input_hash")
        self.prepare()
        original = Path(self.rendered["text"]).read_bytes()
        render = messages.render
        def during_render(*args, **kwargs):
            text = render(*args, **kwargs)
            self.write("note", self.app, "--text", "虚构并发", "--expected-revision", self.show(self.app)["revision"])
            return text
        with mock.patch.object(messages, "render", during_render):
            self.assertEqual(self.command("material", "render", self.source, "--output")[0], 1)
        self.assertEqual(Path(self.rendered["text"]).read_bytes(), original)
        for command in ("validate", "show"):
            self.prepare()
            check = build_notes.check_outputs
            def during_review(*args):
                errors = check(*args)
                self.write("note", self.app, "--text", "虚构并发", "--expected-revision", self.show(self.app)["revision"])
                return errors
            with mock.patch.object(build_notes, "check_outputs", during_review):
                code, out, err = self.command("review", command, self.review_file)
            self.assertEqual(code, 1, out + err)
            self.assertIn("stale_revision", out)

    def test_output_identity_damage_and_failed_write(self):
        self.prepare()
        Path(self.rendered["text"]).write_text("虚构被换产物", encoding="utf-8")
        self.assertEqual(self.command("review", "validate", self.review_file)[0], 1)
        self.prepare()
        Path(self.rendered["build_note"]).unlink()
        self.assertEqual(self.command("review", "show", self.review_file)[0], 1)
        with mock.patch.object(cli, "_write_build_note", side_effect=OSError("synthetic disk error")):
            code, out, _ = self.command("material", "render", self.source, "--output")
        self.assertEqual(code, 1)
        self.assertIn("complete followup outputs", out)
        self.assertEqual(self.command("review", "validate", self.review_file)[0], 1)

    def test_limits_h_checklist_and_resume_build_rejection(self):
        record = self.prepare()
        for size, expected in ((300, 0), (301, 1)):
            record["segments"][1]["text"] = "谢" * (size - len(self.inputs().job["title"]) - len("您好，我此前提交了岗位的申请。"))
            self.save_record(record)
            self.assertEqual(self.command("material", "validate", self.source)[0], expected)
        self.prepare()
        self.assertEqual(self.command("resume", "build", self.source)[0], 2)
        report = json.loads(self.review_file.read_bytes())
        report["findings"] = [{"item": "H2", "path": "segments[0].text", "severity": "suggest",
                               "reason": "虚构语义检查", "suggestion": None}]
        self.review_file.write_text(json.dumps(report), encoding="utf-8")
        self.assertEqual(self.command("review", "validate", self.review_file)[0], 0)

    def test_old_kind_context_and_new_flags_are_not_silently_accepted(self):
        base = self.record()
        self.save_record({**base, "kind": "greeting"})
        self.assertEqual(self.command("material", "validate", self.source)[0], 1)
        self.assertEqual(self.command("material", "template", self.job, "--kind", "email", "--application", self.app)[0], 2)
        self.assertEqual(self.command("material", "template", self.job, "--kind", "followup")[0], 2)

    @unittest.skipUnless(os.name == "nt", "real Windows junctions")
    def test_source_and_output_junctions_do_not_read_or_write_their_targets(self):
        import _winapi
        self.prepare()
        paths = (self.data / "jobs", self.data / "profile", self.data / "messages")
        for path in paths:
            with self.subTest(path=path.name):
                target = self.data / (path.name + "-fictional-target")
                path.rename(target)
                _winapi.CreateJunction(str(target), str(path))
                before = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
                read_bytes = Path.read_bytes
                def no_read(linked):
                    if path in linked.parents:
                        raise AssertionError("must reject junction before reading its target")
                    return read_bytes(linked)
                with mock.patch.object(Path, "read_bytes", no_read):
                    commands = [("material", "validate", self.source), ("review", "validate", self.review_file)]
                    if path.name == "messages":
                        commands = [("material", "render", self.source, "--output"), ("review", "show", self.review_file)]
                    for command in commands:
                        self.assertIn(self.command(*command)[0], (1, 2))
                self.assertEqual(before, {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()})
                path.rmdir()  # remove only this test-created junction, never its target
                target.rename(path)


class SubmissionArchive(Data):
    """A valid followup is local drafting material, never a first-submission material."""

    inputs = Context.inputs
    record = Context.record
    command = Delivery.command

    def setUp(self):
        super().setUp()
        self.app = self.historical()
        self.source = self.material.parent / "followup-1.json"
        self.source.write_text(json.dumps(self.record(), ensure_ascii=False), encoding="utf-8")
        code, out, err = self.command("material", "render", self.source, "--output")
        self.assertEqual(code, 0, out + err)

    def snapshot(self):
        # Include directories, source files, database bytes (events/requests/projections) and archives.
        return {p.relative_to(self.data).as_posix(): p.read_bytes() if p.is_file() else None
                for p in self.data.rglob("*")}

    def test_cli_record_and_submit_refuse_followup_before_preview_or_write_even_when_renamed(self):
        draft = self.drafted()
        routes = (("record", self.job, "--channel", "email", "--submitted"),
                  ("submit", draft, "--expected-revision", 1))
        for name in ("followup-1.json", "resume-2.json", "email-2.json", "renamed.json"):
            source = self.source.with_name(name)
            source.write_bytes(self.source.read_bytes())
            for route in routes:
                args = (*route, "--on", "2026-11-10", "--actor", "codex")
                before = self.snapshot()
                # A real supported-material preview supplies the unused request id for a write attempt.
                code, preview, err = self.cli(*args, "--material", self.material, "--preview")
                self.assertEqual(code, 0, err)
                for mode in (("--preview",), ("--request-id", preview["request_id"])):
                    with self.subTest(name=name, route=route[0], mode=mode[0]):
                        code, out, err = self.cli(*args, "--material", source, *mode)
                        self.assertEqual((code, out), (1, None), err)
                        self.assertEqual(err["error"], "invalid")
                        self.assertIn("followup", err["message"])
                        self.assertIn("first-submission", err["message"])
                        self.assertEqual(self.snapshot(), before)

    def test_direct_api_cannot_bypass_the_boundary_by_omitting_or_relaxing_the_callback(self):
        draft = self.drafted()
        routes = ((applications.record, self.job, {"channel": "email", "submitted": True}),
                  (applications.submit, draft, {"expected_revision": 1}))
        for check in (None, mock.Mock(return_value=([], []))):
            before = self.snapshot()
            with self.assertRaisesRegex(applications.ApplicationError, "followup.*first-submission"):
                applications.prepare_materials(self.data, self.job, self.source, check_material=check)
            for call, identity, options in routes:
                preview = call(self.data, identity, material=self.material, preview=True, **options)
                for mode in ({"preview": True}, {"request_id": preview["request_id"]}):
                    with self.subTest(route=call.__name__, mode=mode, callback=check is not None):
                        with self.assertRaisesRegex(applications.ApplicationError, "followup.*first-submission"):
                            call(self.data, identity, material=self.source, check_material=check, **options, **mode)
                        self.assertEqual(self.snapshot(), before)
            if check is not None:
                check.assert_not_called()

    def test_legacy_resume_and_three_messages_still_preview_and_archive_for_both_routes(self):
        for kind in ("resume", "greeting", "email", "referral"):
            source = self.material.with_name(f"{kind}-1.json")
            record = {**json.loads((FIXTURE / source.name).read_bytes()), "job_id": self.job}
            source.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            draft = self.drafted()
            routes = (("record", self.job, "--channel", "email", "--submitted"),
                      ("submit", draft, "--expected-revision", 1))
            for route in routes:
                with self.subTest(kind=kind, route=route[0]):
                    args = (*route, "--material", source, "--on", "2026-11-10", "--actor", "codex")
                    before = self.snapshot()
                    code, preview, err = self.cli(*args, "--preview")
                    self.assertEqual(code, 0, err)
                    self.assertEqual(self.snapshot(), before)
                    self.assertEqual([item["file_id"] for item in preview["materials"]], ["material"])
                    code, out, err = self.cli(*args, "--request-id", preview["request_id"])
                    self.assertEqual(code, 0, err)
                    application = out["application"]
                    self.assertEqual(application["status"], "applied")
                    [version] = application["material_versions"]
                    self.assertEqual(version["material_hash"], review.material_hash(record))
                    [archived] = version["files"]
                    self.assertEqual((self.paths.dir / archived["path"]).read_bytes(), source.read_bytes())
        self.assertEqual(self.cli("validate")[0], 0)
