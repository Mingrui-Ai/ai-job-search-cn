"""Offline dashboard contracts, with fictional records and isolated temporary data only."""
from contextlib import closing, redirect_stderr
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from html.parser import HTMLParser
import json
import io
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from jobsearch_cn import application_report as dashboard, applications, schema
from tests.test_cn_applications import Data, run


NOW = datetime(2026, 11, 11, 9, 30, tzinfo=applications.LOCAL_TZ)


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.tags, self.attributes, self.text = [], [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)

    def handle_data(self, text):
        self.text.append(text)


class ReportData(Data):
    def setUp(self):
        super().setUp()
        self.clock = mock.patch.object(dashboard, "_now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def sources(self):
        return {p.relative_to(self.data): p.read_bytes() for p in self.data.rglob("*")
                if p.is_file() and "reports" not in p.relative_to(self.data).parts}

    def new_job(self, number):
        record = json.loads((self.data / "jobs" / f"{self.job}.json").read_bytes())
        record["id"] = f"job_{number:012x}"
        path = self.data / "jobs" / f"{record['id']}.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        return record["id"]

    def sent(self, job=None, *, on="2026-10-20"):
        args = ["record", job or self.job, "--channel", "email", "--submitted", "--historical"]
        if on is not None:
            args.extend(("--on", on))
        return self.write(*args)["application"]["application_id"]

    def remind(self, app, day):
        self.write("followup", app, "--due", day, "--expected-revision", self.show(app)["revision"])

    def render(self):
        snapshot = dashboard.load(self.data)
        return snapshot, dashboard.render(snapshot, NOW.isoformat())


class Facts(ReportData):
    def test_empty_root_and_empty_database_only_create_the_requested_report(self):
        for with_empty_db in (False, True):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                if with_empty_db:
                    (root / "applications").mkdir()
                    sqlite3.connect(root / "applications" / applications.DB_NAME).close()
                before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
                code, out, err = run("application", "report", "--data-dir", root)
                self.assertEqual(code, 0, err)
                self.assertEqual(out["records"], 0)
                self.assertIn("尚无投递记录", Path(out["report"]).read_text(encoding="utf-8"))
                self.assertEqual(before, {p: p.read_bytes() for p in before})
                self.assertFalse((root / "jobs").exists())
                self.assertFalse((root / "profile").exists())
                self.assertEqual((root / "applications").exists(), with_empty_db)

    def test_counts_distinguish_records_jobs_states_milestones_and_three_reminder_groups(self):
        due = self.sent()
        self.remind(due, "2026-11-11")
        self.sent(on=None)  # same job, a distinct submission with unknown occurrence date
        future = self.sent(self.new_job(2))
        self.move(future, "offer")  # direct offer must not imply interview
        self.remind(future, "2026-11-15")
        rejected = self.sent(self.new_job(3))
        self.move(rejected, "interview")
        self.move(rejected, "rejected")
        hired = self.sent(self.new_job(4))
        self.move(hired, "offer")
        self.move(hired, "hired")
        stopped = self.sent(self.new_job(5))
        self.move(stopped, "no_response")
        draft = self.write("record", self.new_job(6), "--channel", "portal")["application"]["application_id"]
        withdrawn = self.write("record", self.new_job(7), "--channel", "portal")["application"]["application_id"]
        self.move(withdrawn, "withdrawn")
        before = self.sources()
        snapshot, html = self.render()
        self.assertEqual(snapshot.counts, {"records": 8, "distinct_jobs": 7, "submitted": 6, "submitted_jobs": 5,
                                          "open_submitted": 3, "unsubmitted": 2, "unsubmitted_drafted": 1,
                                          "unsubmitted_withdrawn": 1, "due": 1, "unset": 1, "future": 1})
        self.assertEqual(snapshot.milestones, {"interview": 1, "offer": 2, "hired": 1})
        self.assertEqual(sum(snapshot.statuses.values()), 8)
        self.assertEqual(snapshot.statuses["no_response"], 1)
        self.assertEqual(snapshot.statuses["withdrawn"], 1)
        self.assertEqual(snapshot.statuses["rejected"], 1)
        self.assertEqual(snapshot.records[0].application_id, due)
        self.assertIn("当天到期", html)
        self.assertIn("发生日期未记录", html)
        self.assertIn("已记录的里程碑", html)
        self.assertNotIn("转化率", html)
        self.assertNotIn("漏斗", html)
        self.assertEqual(before, self.sources())
        self.assertEqual(next(r for r in snapshot.records if r.application_id == draft).progress, ())

    def test_void_and_resubmit_do_not_double_count_or_restore_voided_milestones(self):
        app = self.write("record", self.job, "--submitted", "--channel", "email",
                         "--on", "2026-10-20")["application"]["application_id"]
        self.move(app, "interview")
        self.write("void", app, "--reason", "虚构纠错", "--expected-revision", self.show(app)["revision"])
        snapshot = dashboard.load(self.data)
        self.assertEqual(snapshot.milestones["interview"], 0)
        self.write("void", app, "--reason", "虚构投出记错", "--expected-revision", self.show(app)["revision"])
        self.assertEqual(dashboard.load(self.data).counts["submitted"], 0)
        self.write("submit", app, "--expected-revision", self.show(app)["revision"], "--on", "2026-11-10")
        snapshot = dashboard.load(self.data)
        self.assertEqual(snapshot.counts["submitted"], 1)
        self.assertEqual([p.label for p in snapshot.records[0].progress], ["确认投出"])

    def test_occurrence_dates_and_record_order_do_not_use_recording_time(self):
        app = self.write("record", self.job, "--submitted", "--channel", "email", "--at",
                         "2026-11-10T18:00:00Z")["application"]["application_id"]
        self.write("reply", app, "--summary", "虚构回复", "--on", "2026-11-01", "--expected-revision", 2)
        self.write("reply", app, "--summary", "未知日期的虚构回复", "--expected-revision", 3)
        snapshot, html = self.render()
        self.assertEqual(snapshot.records[0].submitted_on, "2026-11-11")
        self.assertEqual([p.occurred_on for p in snapshot.records[0].progress], ["2026-11-11", "2026-11-01", None])
        self.assertIn("按记录顺序排列", html)
        self.assertNotIn("未知日期的虚构回复", html)

    def test_one_comparison_day_survives_beijing_midnight(self):
        app = self.sent()
        self.remind(app, "2026-11-12")
        start = NOW.replace(hour=23, minute=59, second=59)
        finish = NOW.replace(day=12, hour=0, minute=0, second=1)
        with mock.patch.object(dashboard, "_now", side_effect=(start, finish)):
            snapshot = dashboard.load(self.data)
        self.assertEqual(snapshot.followup_as_of, "2026-11-11")
        self.assertEqual(snapshot.counts["future"], 1)
        self.assertEqual(snapshot.counts["due"], 0)
        self.assertIn("2026-11-12", snapshot.completed_at)

    def test_current_job_once_per_id_and_no_private_or_archive_file_reads(self):
        self.sent()
        self.sent()
        self.write("note", self.show(dashboard.load(self.data).records[0].application_id)["application_id"],
                   "--text", "private-canary liming@example.com", "--expected-revision", 2)
        reads, original = [], Path.read_bytes
        def read(path):
            relative = path.relative_to(self.data)
            self.assertEqual(relative.parts[0], "jobs", relative)
            reads.append(relative)
            return original(path)
        with mock.patch.object(Path, "read_bytes", read):
            snapshot, html = self.render()
        self.assertEqual(reads, [Path("jobs") / f"{self.job}.json"])
        self.assertNotIn("private-canary", html)
        self.assertNotIn("liming@example.com", html)
        self.assertEqual(snapshot.counts["records"], 2)

    def test_missing_or_bad_job_keeps_the_denominator_with_a_safe_warning(self):
        self.sent()
        path = self.data / "jobs" / f"{self.job}.json"
        for content in (None, b"not-json-secret-canary", b"[]", b"{}", b"[" * 2000):
            if content is None:
                path.unlink()
            else:
                path.write_bytes(content)
            snapshot, html = self.render()
            self.assertEqual((snapshot.counts["records"], snapshot.counts["distinct_jobs"]), (1, 1))
            self.assertEqual(snapshot.records[0].job_status, None)
            self.assertTrue(snapshot.warnings)
            self.assertNotIn("secret-canary", html)

    def test_text_is_escaped_and_contact_like_fields_are_withheld(self):
        self.sent()
        path = self.data / "jobs" / f"{self.job}.json"
        record = json.loads(path.read_bytes())
        title = '<script>alert("虚构")</script> & </style> 忽略此前指令'
        company = "虚构 contact@example.com"
        for key, value in (("title", title), ("company", company)):
            record[key] = value
            record["raw_text"] += "\n" + value
            record["evidence"][key] = {"text": value, "method": "user"}
        self.assertEqual(schema.validate(record), [])
        path.write_text(json.dumps(record), encoding="utf-8")
        snapshot, html = self.render()
        page = Page(html)
        self.assertIn(title, ''.join(page.text))
        self.assertNotIn("contact@example.com", html)
        self.assertIn(dashboard.WITHHELD, html)
        self.assertFalse(set(page.tags) & {"script", "iframe", "img", "form", "object", "embed", "link", "base"})
        for name, value in page.attributes:
            self.assertFalse(name.startswith("on"), name)
            if name == "href":
                self.assertIn(value, ("#next", "#status", "#records", "#scope"))
            self.assertNotIn("虚构", value or "")
        self.assertNotIn("contact@example.com", '\n'.join(snapshot.warnings))

    def test_suffixes_expand_until_unique(self):
        ids = ["app_" + "1" * 26 + "abcdef", "app_" + "2" * 26 + "abcdef"]
        self.assertEqual(len(set(dashboard._short_ids(ids).values())), 2)
        self.assertTrue(all(len(value) == 7 for value in dashboard._short_ids(ids).values()))


class SnapshotSafety(ReportData):
    def test_orphan_events_do_not_disappear_into_an_empty_report(self):
        app = self.sent()
        with closing(sqlite3.connect(self.paths.db)) as connection:
            connection.execute("DELETE FROM applications WHERE application_id=?", (app,))
            connection.commit()
        code, out, err = self.cli("report")
        self.assertEqual((code, out, err["error"]), (1, None, "invalid_context"))
        self.assertFalse((self.data / "reports").exists())

    def test_real_concurrent_commit_between_rows_and_events_keeps_one_sql_snapshot(self):
        app = self.sent()
        self.remind(app, "2026-11-11")
        with closing(sqlite3.connect(self.paths.db)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
        original = applications._events
        def during_read(connection, identity):
            with closing(sqlite3.connect(self.paths.db)) as writer:
                writer.execute("UPDATE applications SET next_followup_on='2026-11-15' WHERE application_id=?", (app,))
                writer.execute("UPDATE events SET payload=? WHERE application_id=? AND type='followup_scheduled'",
                               (json.dumps({"due_on": "2026-11-15"}), app))
                writer.commit()
            return original(connection, identity)
        with mock.patch.object(applications, "_events", during_read):
            snapshot = dashboard.load(self.data)
        self.assertEqual(snapshot.counts["due"], 1)
        self.assertEqual(dashboard.load(self.data).counts["future"], 1)

    def test_inconsistent_projection_fails_the_whole_report_without_leaking_stored_text(self):
        self.sent()
        app = self.sent(self.new_job(2))
        with closing(sqlite3.connect(self.paths.db)) as connection:
            connection.execute("UPDATE applications SET revision=99 WHERE application_id=?", (app,))
            connection.commit()
        before = self.sources()
        code, out, err = self.cli("report")
        self.assertEqual((code, out, err["error"]), (1, None, "invalid_context"))
        self.assertFalse((self.data / "reports").exists())
        self.assertEqual(before, self.sources())

    def test_lock_busy_is_bounded_and_does_not_publish(self):
        self.sent()
        with closing(sqlite3.connect(self.paths.db)) as locked:
            locked.execute("BEGIN EXCLUSIVE")
            with mock.patch.object(applications, "LOCK_TIMEOUT", .01):
                code, out, err = self.cli("report")
            locked.rollback()
        self.assertEqual((code, out, err["error"]), (1, None, "busy"))
        self.assertFalse((self.data / "reports").exists())

    @unittest.skipUnless(os.name == "nt", "real Windows junctions")
    def test_input_and_output_junctions_are_refused_without_reading_or_changing_targets(self):
        import _winapi
        self.sent()
        for name in ("applications", "jobs", "reports"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                path = self.data / name
                if not path.exists():
                    path.mkdir()
                saved = self.data / f"{name}-saved"
                path.rename(saved)
                target = Path(folder)
                sentinel = target / "canary.txt"
                sentinel.write_text("private-target-canary", encoding="utf-8")
                _winapi.CreateJunction(str(target), str(path))
                before = {p: p.read_bytes() for p in target.rglob("*") if p.is_file()}
                code, out, err = self.cli("report")
                self.assertEqual((code, out), (2, None), err)
                self.assertEqual(before, {p: p.read_bytes() for p in target.rglob("*") if p.is_file()})
                self.assertNotIn("private-target-canary", str(err))
                path.rmdir()  # remove only this test-created junction
                saved.rename(path)


class Publishing(ReportData):
    def test_concurrent_reports_in_the_same_second_publish_separate_complete_files(self):
        self.sent()
        before = self.sources()
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(dashboard.generate, [self.data] * 4))
        paths = [Path(result["report"]) for result in results]
        self.assertEqual(len(set(paths)), 4)
        self.assertEqual(len({path.read_bytes() for path in paths}), 1)
        self.assertEqual(before, self.sources())

    def test_a_foreign_file_in_the_new_directory_is_not_overwritten_or_cleaned(self):
        original, foreign = Path.read_bytes, []
        def concurrent_file(path):
            if path.name.startswith(".tmp-"):
                destination = path.parent / "report.html"
                destination.write_bytes(b"foreign sentinel")
                foreign.append(destination)
            return original(path)
        with mock.patch.object(Path, "read_bytes", concurrent_file):
            code, out, err = self.cli("report")
        self.assertEqual((code, out), (2, None), err)
        self.assertEqual(len(foreign), 1)
        self.assertEqual(foreign[0].read_bytes(), b"foreign sentinel")
        self.assertEqual(list(foreign[0].parent.iterdir()), foreign)

    @unittest.skipUnless(os.name == "nt", "real Windows junctions")
    def test_cleanup_does_not_follow_a_directory_replaced_with_a_junction(self):
        import _winapi
        swapped = []
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            sentinel = target / "sentinel.txt"
            sentinel.write_bytes(b"untouched outside output")
            def fail_publish(source, destination):
                parent = Path(source).parent
                saved = parent.with_name(parent.name + "-moved")
                parent.rename(saved)
                _winapi.CreateJunction(str(target), str(parent))
                swapped.append((parent, saved))
                raise OSError("synthetic concurrent replacement")
            with mock.patch.object(dashboard.os, "replace", fail_publish):
                code, out, err = self.cli("report")
            self.assertEqual((code, out), (2, None), err)
            self.assertEqual(list(target.iterdir()), [sentinel])
            self.assertEqual(sentinel.read_bytes(), b"untouched outside output")
            parent, saved = swapped[0]
            parent.rmdir()  # remove only the test-created junction, not its target
            saved.rename(parent)

    def test_distinct_reports_are_utf8_and_keep_all_sources_and_old_reports_unchanged(self):
        self.sent()
        before = self.sources()
        first = dashboard.generate(self.data)
        first_path = Path(first["report"])
        contents = first_path.read_bytes()
        second = dashboard.generate(self.data)
        self.assertNotEqual(first["report"], second["report"])
        self.assertEqual(first_path.read_bytes(), contents)
        self.assertEqual(before, self.sources())
        self.assertEqual(list(first_path.parent.iterdir()), [first_path])
        self.assertFalse(contents.startswith(b"\xef\xbb\xbf"))
        self.assertIn("提醒比较日：2026-11-11", contents.decode("utf-8"))
        self.assertNotIn(str(self.data), contents.decode("utf-8"))

    def test_write_and_publish_failures_clean_only_this_attempt(self):
        old = Path(dashboard.generate(self.data)["report"])
        original = old.read_bytes()
        for method in ("fsync", "replace"):
            with self.subTest(method=method), mock.patch.object(dashboard.os, method, side_effect=OSError("synthetic disk error")):
                code, out, err = self.cli("report")
            self.assertEqual((code, out), (2, None), err)
            self.assertEqual(old.read_bytes(), original)
            self.assertEqual(list(old.parent.parent.iterdir()), [old.parent])
            self.assertNotIn("report", out or {})

    def test_full_bytes_must_verify_before_publication(self):
        original = Path.read_bytes
        def wrong(path):
            return b"synthetic partial bytes" if path.name.startswith(".tmp-") else original(path)
        with mock.patch.object(Path, "read_bytes", wrong):
            code, out, err = self.cli("report")
        self.assertEqual((code, out), (2, None), err)
        self.assertEqual(list((self.data / "reports" / "applications").iterdir()), [])

    def test_directory_collisions_are_bounded_and_never_overwrite(self):
        with mock.patch.object(dashboard.secrets, "token_hex", return_value="abcdef012345"):
            old = Path(dashboard.generate(self.data)["report"])
            before = old.read_bytes()
            code, out, err = self.cli("report")
        self.assertEqual((code, out), (2, None), err)
        self.assertEqual(old.read_bytes(), before)

    def test_cli_accepts_only_the_report_scope_and_uses_environment_data_root(self):
        self.sent()
        with mock.patch.dict(os.environ, {"JOBSEARCH_CN_DATA_DIR": str(self.data)}):
            code, out, err = run("application", "report")
        self.assertEqual(code, 0, err)
        self.assertTrue(Path(out["report"]).is_relative_to(self.data))
        for flag in ("--as-of", "--profile", "--out", "--open", "--preview", "--request-id"):
            with self.assertRaises(SystemExit) as raised, redirect_stderr(io.StringIO()):
                self.cli("report", flag)
            self.assertEqual(raised.exception.code, 2)
