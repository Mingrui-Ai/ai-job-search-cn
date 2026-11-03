"""Application records (M4-1a): the database, the state machine, previews and retries, concurrency and archives.

Each class pins one acceptance item of the M4-1 design (§11, docs/cn/worklog/2026-11-03-m4-1-applications-design.md)
that M4-1a covers; the format and commands are docs/cn/applications.md. Everything runs in a temporary data
directory with public fictional data: the tech-m3 profile and material, and the BOSS intern JD.
"""
import argparse
import contextlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from jobsearch_cn import applications, cli, review, store  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "cn" / "material" / "tech-m3"
JD = REPO / "tests" / "fixtures" / "cn" / "jd" / "boss_intern.txt"
MATERIAL = json.loads((FIXTURE / "resume-1.json").read_text(encoding="utf-8"))
CONTACTS = ("13800000000", "liming@example.com")  # the fixture profile's contact details


def run(*args):
    """cli.main in-process: (exit code, stdout JSON or None, stderr JSON or None)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main([str(arg) for arg in args])
    return code, json.loads(out.getvalue()) if out.getvalue() else None, \
        json.loads(err.getvalue()) if err.getvalue() else None


class Data(unittest.TestCase):
    """A temporary data directory with the profile, one stored job, its material, a built PDF and a review."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name)
        shutil.copytree(FIXTURE / "profile", self.data / "profile")
        code, out, _ = run("jd", "parse", JD, "--save", "--data-dir", self.data)
        self.assertEqual(code, 0)
        self.job = out["jobs"][0]["id"]
        self.material = self.data / "materials" / self.job / "resume-1.json"
        self.material.parent.mkdir(parents=True)
        self.material.write_text(json.dumps({**MATERIAL, "job_id": self.job}, ensure_ascii=False), encoding="utf-8")
        self.pdf = self.data / "resumes" / self.job / "resume-1.pdf"
        self.pdf.parent.mkdir(parents=True)
        self.pdf.write_bytes(b"%PDF-1.7 fictional resume\n")
        self.paths = applications.Paths(self.data)

    def cli(self, *args):
        return run("application", *args, "--data-dir", self.data)

    def write(self, *args):
        """Preview, then commit with the preview's request id. Returns the committed output."""
        code, preview, err = self.cli(*args, "--preview")
        self.assertEqual(code, 0, err)
        code, out, err = self.cli(*args, "--request-id", preview["request_id"])
        self.assertEqual(code, 0, err)
        return out

    def drafted(self, channel="portal") -> str:
        return self.write("record", self.job, "--channel", channel)["application"]["application_id"]

    def historical(self, on="2026-10-20") -> str:
        out = self.write("record", self.job, "--channel", "email", "--submitted", "--historical", "--on", on)
        return out["application"]["application_id"]

    def status(self, application_id, to, *extra):
        revision = self.show(application_id)["revision"]
        return self.cli("status", application_id, to, "--expected-revision", revision, *extra, "--preview")

    def move(self, application_id, to, *extra):
        revision = self.show(application_id)["revision"]
        return self.write("status", application_id, to, "--expected-revision", revision, *extra)

    def show(self, application_id) -> dict:
        code, out, err = self.cli("show", application_id)
        self.assertEqual(code, 0, err)
        return out["application"]

    def connect(self):
        connection = sqlite3.connect(self.paths.db)
        self.addCleanup(connection.close)
        return connection

    def files(self) -> list:
        return sorted(path.relative_to(self.data).as_posix() for path in self.data.rglob("*"))

    def build_note(self, material_hash=None, sha=None):
        """resume-1.build.json as resume build writes it for self.material and self.pdf (applications.md §12)."""
        record = json.loads(self.material.read_text(encoding="utf-8"))
        note = {"schema_version": 1, "kind": "resume-build", "material": "resume-1.json",
                "material_hash": material_hash or review.material_hash(record), "profile_hash": "x",
                "built_at": "2026-11-03T10:00:00+08:00",
                "files": [{"name": "resume-1.pdf", "sha256": sha or applications._sha256(self.pdf.read_bytes())}]}
        (self.pdf.parent / "resume-1.build.json").write_text(json.dumps(note), encoding="utf-8")


class Schema(Data):
    def test_a_new_database_has_the_tables_version_1_and_foreign_keys(self):
        self.drafted()
        connection = self.connect()
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables, set(applications.TABLES))
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        own, _ = applications._connect(self.paths, write=True)
        self.addCleanup(own.close)
        with self.assertRaises(sqlite3.IntegrityError):
            own.execute("INSERT INTO events VALUES ('app_' || hex(randomblob(16)), 1, 'evt_x', 'req_x', 'created', "
                        "NULL, NULL, '2026-11-03T00:00:00Z', 'user', 'user', '{}', NULL)")

    def test_a_newer_database_is_refused_with_exit_2_and_left_alone(self):
        application_id = self.drafted()
        with self.connect() as connection:
            connection.execute("PRAGMA user_version = 2")
        before = self.paths.db.read_bytes()
        for args in (("show", application_id), ("list",), ("validate",), ("export",),
                     ("record", self.job, "--channel", "portal", "--preview"),
                     ("status", application_id, "withdrawn", "--expected-revision", "1", "--preview")):
            code, out, err = self.cli(*args)
            self.assertEqual(code, 2, args)
            self.assertIn("newer", err["error"])
        code, preview, _ = self.cli("record", self.job, "--channel", "portal", "--preview")
        self.assertEqual(code, 2)
        code, _, err = self.cli("record", self.job, "--channel", "portal", "--request-id", "req_" + "1" * 32)
        self.assertEqual(code, 2)
        self.assertEqual(self.paths.db.read_bytes(), before)

    def test_a_file_that_is_not_an_application_database_is_refused(self):
        self.paths.dir.mkdir()
        self.paths.db.write_bytes(b"not sqlite at all, just some bytes that are long enough to matter" * 4)
        code, _, err = self.cli("list")
        self.assertEqual(code, 2)
        connection = sqlite3.connect(self.paths.db.with_name("other.sqlite3"))
        connection.execute("CREATE TABLE something (x)")
        connection.commit()
        connection.close()
        self.paths.db.unlink()
        self.paths.db.with_name("other.sqlite3").rename(self.paths.db)
        code, _, err = self.cli("record", self.job, "--channel", "portal", "--request-id", "req_" + "2" * 32)
        self.assertEqual(code, 2)
        self.assertIn("not one", err["error"])


class States(Data):
    # How to bring a fresh application to each status, from applied (a historical record is applied at once).
    ROUTES = {
        "applied": [], "interview": ["interview"], "offer": ["offer"], "no_response": ["no_response"],
        "hired": ["offer", "hired"], "rejected": ["rejected"], "withdrawn": ["withdrawn"],
        "offer_declined": ["offer", "offer_declined"],
    }

    def at(self, status) -> str:
        if status == "drafted":
            return self.drafted()
        application_id = self.historical()
        for step in self.ROUTES[status]:
            self.move(application_id, step)
        self.assertEqual(self.show(application_id)["status"], status)
        return application_id

    def test_every_allowed_change_is_written_and_every_other_is_refused(self):
        for before in applications.STATUSES:
            for after in applications.STATUSES[1:]:  # drafted is never a target the command accepts
                with self.subTest(before=before, after=after):
                    application_id = self.at(before)
                    reason = ("--reason", "对方回复约面") if before == "no_response" else ()
                    code, out, err = self.status(application_id, after, *reason)
                    allowed = after in applications.TRANSITIONS[before] and after != "applied"
                    if allowed:
                        self.assertEqual(code, 0, err)
                        out = self.move(application_id, after, *reason)
                        self.assertEqual(out["application"]["status"], after)
                    else:
                        self.assertEqual((code, err["error"]), (1, "transition"))
                        self.assertEqual(self.show(application_id)["status"], before)

    def test_terminal_statuses_allow_nothing(self):
        for status in applications.TERMINAL:
            self.assertEqual(applications.TRANSITIONS[status], ())

    def test_drafted_becomes_applied_only_through_submit(self):
        application_id = self.drafted()
        code, _, err = self.status(application_id, "applied")
        self.assertEqual(err["error"], "transition")
        self.assertIn("submit", err["message"])
        out = self.write("submit", application_id, "--expected-revision", "1", "--on", "2026-11-02")
        self.assertEqual(out["application"]["status"], "applied")
        code, _, err = self.cli("submit", application_id, "--expected-revision", "2", "--preview")
        self.assertEqual((code, err["error"]), (1, "transition"))

    def test_a_late_reply_needs_a_reason(self):
        application_id = self.at("no_response")
        code, _, err = self.status(application_id, "interview")
        self.assertEqual((code, err["error"]), (1, "invalid"))
        self.assertEqual(self.move(application_id, "interview", "--reason", "迟到的面试邀请")["application"]["status"],
                         "interview")

    def test_replay_is_the_one_rule_for_writing_and_checking(self):
        application_id = self.at("offer")
        events = self.show(application_id)["events"]
        self.assertEqual(applications.replay(events)["status"], "offer")
        bad = events + [dict(events[-1], seq=len(events) + 1,
                             payload={"from": "offer", "to": "interview", "reason": None})]
        with self.assertRaises(applications.ApplicationError) as caught:
            applications.replay(bad)
        self.assertEqual(caught.exception.code, "transition")


class PreviewAndRetry(Data):
    def test_a_preview_writes_nothing_and_creates_no_database(self):
        before = self.files()
        code, out, _ = self.cli("record", self.job, "--channel", "portal", "--submitted", "--on", "2026-11-01",
                                "--material", self.material, "--sent", self.pdf, "--preview")
        self.assertEqual(code, 0)
        self.assertTrue(out["preview"])
        self.assertRegex(out["request_id"], r"^req_[0-9a-f]{32}$")
        self.assertEqual([event["type"] for event in out["events"]], ["created", "submitted"])
        self.assertEqual([item["file_id"] for item in out["materials"]], ["material", "sent-1"])
        self.assertEqual(self.files(), before)
        code, _, err = self.cli("status", "app_" + "a" * 32, "withdrawn", "--expected-revision", "1", "--preview")
        self.assertEqual((code, err["error"]), (1, "not_found"))
        self.assertEqual(self.files(), before)

    def test_a_write_needs_a_preview_or_a_request_id(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run("application", "record", self.job, "--channel", "portal", "--data-dir", self.data)
        code, _, err = self.cli("record", self.job, "--channel", "portal", "--request-id", "abc")
        self.assertEqual((code, err["error"]), (1, "invalid"))
        self.assertFalse(self.paths.db.exists())

    def test_a_retry_with_the_same_request_returns_the_first_result_and_writes_nothing_more(self):
        code, preview, _ = self.cli("record", self.job, "--channel", "portal", "--submitted",
                                    "--material", self.material, "--sent", self.pdf, "--preview")
        args = ("record", self.job, "--channel", "portal", "--submitted", "--material", self.material,
                "--sent", self.pdf, "--request-id", preview["request_id"])
        code, first, _ = self.cli(*args)
        self.assertEqual(code, 0)
        self.assertFalse(first["repeated"])
        archived = self.files()
        code, again, _ = self.cli(*args)
        self.assertEqual(code, 0)
        self.assertTrue(again["repeated"])
        self.assertEqual(again["application"]["application_id"], first["application"]["application_id"])
        self.assertEqual(again["events"], first["events"])
        self.assertEqual(self.files(), archived)
        connection = self.connect()
        self.assertEqual(connection.execute("SELECT count(*) FROM applications").fetchone()[0], 1)
        self.assertEqual(connection.execute("SELECT count(*) FROM events").fetchone()[0], 2)

    def test_a_retried_submit_or_status_returns_the_first_result_although_the_revision_moved_on(self):
        application_id = self.drafted()
        code, preview, _ = self.cli("submit", application_id, "--expected-revision", "1", "--sent", self.pdf,
                                    "--preview")
        args = ("submit", application_id, "--expected-revision", "1", "--sent", self.pdf,
                "--request-id", preview["request_id"])
        first = self.cli(*args)[1]
        code, again, err = self.cli(*args)
        self.assertEqual(code, 0, err)
        self.assertTrue(again["repeated"])
        self.assertEqual(again["events"], first["events"])
        code, preview, _ = self.status(application_id, "interview")
        args = ("status", application_id, "interview", "--expected-revision", "2",
                "--request-id", preview["request_id"])
        first = self.cli(*args)[1]
        code, again, err = self.cli(*args)
        self.assertEqual(code, 0, err)
        self.assertTrue(again["repeated"])
        self.assertEqual(again["events"], first["events"])
        self.assertEqual(len(self.show(application_id)["events"]), 3)
        self.assertEqual(len(list(self.paths.artifacts.glob("*/mv_*"))), 1)

    def test_the_same_request_id_for_another_request_is_a_conflict(self):
        code, preview, _ = self.cli("record", self.job, "--channel", "portal", "--preview")
        self.cli("record", self.job, "--channel", "portal", "--request-id", preview["request_id"])
        code, _, err = self.cli("record", self.job, "--channel", "email", "--request-id", preview["request_id"])
        self.assertEqual((code, err["error"]), (1, "request_conflict"))
        application_id = self.drafted()
        code, _, err = self.cli("status", application_id, "withdrawn", "--expected-revision", "1",
                                "--request-id", preview["request_id"])
        self.assertEqual((code, err["error"]), (1, "request_conflict"))
        self.assertEqual(self.show(application_id)["status"], "drafted")
        self.assertEqual(self.connect().execute("SELECT count(*) FROM applications").fetchone()[0], 2)

    def test_a_changed_material_under_the_same_request_id_is_a_conflict(self):
        code, preview, _ = self.cli("record", self.job, "--channel", "portal", "--submitted",
                                    "--sent", self.pdf, "--preview")
        args = ("record", self.job, "--channel", "portal", "--submitted", "--sent", self.pdf,
                "--request-id", preview["request_id"])
        self.assertEqual(self.cli(*args)[0], 0)
        self.pdf.write_bytes(b"%PDF-1.7 rebuilt\n")
        code, _, err = self.cli(*args)
        self.assertEqual((code, err["error"]), (1, "request_conflict"))


class Concurrency(Data):
    def test_two_processes_with_the_same_revision_one_wins_the_other_is_stale(self):
        application_id = self.historical()
        commands = []
        for to in ("interview", "rejected"):
            code, preview, _ = self.status(application_id, to)
            commands.append([sys.executable, "-m", "jobsearch_cn", "application", "status", application_id, to,
                             "--expected-revision", "2", "--request-id", preview["request_id"],
                             "--data-dir", str(self.data)])
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        processes = [subprocess.Popen(command, cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for command in commands]
        results = [(process.wait(timeout=60), process.stdout.read(), process.stderr.read()) for process in processes]
        for process in processes:
            process.stdout.close()
            process.stderr.close()
        self.assertEqual(sorted(code for code, _, _ in results), [0, 1], results)
        loser = next(json.loads(err.decode("utf-8")) for code, _, err in results if code == 1)
        self.assertEqual(loser["error"], "stale_revision")
        self.assertEqual(loser["revision"], 3)
        self.assertEqual([event["seq"] for event in loser["events"]], [3])
        shown = self.show(application_id)
        self.assertEqual(shown["revision"], 3)
        self.assertEqual(len(shown["events"]), 3)
        self.assertEqual(run("application", "validate", "--data-dir", self.data)[0], 0)

    def test_a_write_landing_between_reading_the_row_and_its_events_is_stale_not_invalid(self):
        application_id = self.historical()
        code, preview, _ = self.status(application_id, "interview")
        real, raced = applications._existing, []

        def racing(*args, **kwargs):
            connection, row = real(*args, **kwargs)
            if not raced:
                raced.append(True)
                with mock.patch.object(applications, "_existing", real):
                    self.move(application_id, "rejected")
            return connection, row
        with mock.patch.object(applications, "_existing", racing):
            code, _, err = self.cli("status", application_id, "interview", "--expected-revision", "2",
                                    "--request-id", preview["request_id"])
        self.assertEqual((code, err["error"], err["revision"]), (1, "stale_revision", 3))
        self.assertEqual(self.show(application_id)["status"], "rejected")

    def test_a_writer_holding_the_lock_makes_the_other_report_busy(self):
        application_id = self.historical()
        code, preview, _ = self.status(application_id, "interview")
        holder = sqlite3.connect(self.paths.db, isolation_level=None)
        self.addCleanup(holder.close)
        holder.execute("BEGIN IMMEDIATE")
        with mock.patch.object(applications, "LOCK_TIMEOUT", 0.2):
            code, _, err = self.cli("status", application_id, "interview", "--expected-revision", "2",
                                    "--request-id", preview["request_id"])
        holder.execute("ROLLBACK")
        self.assertEqual((code, err["error"]), (1, "busy"))
        self.assertEqual(self.show(application_id)["revision"], 2)
        code, out, _ = self.cli("status", application_id, "interview", "--expected-revision", "2",
                                "--request-id", preview["request_id"])
        self.assertEqual((code, out["application"]["status"]), (0, "interview"))

    def test_a_failure_inside_the_transaction_leaves_no_half_record_and_no_archive(self):
        code, preview, _ = self.cli("record", self.job, "--channel", "portal", "--submitted",
                                    "--material", self.material, "--sent", self.pdf, "--preview")
        real = applications._dump

        def failing(payload):
            if "material_version_ids" in payload:
                raise sqlite3.OperationalError("disk I/O error")
            return real(payload)
        with mock.patch.object(applications, "_dump", failing):
            code, _, err = self.cli("record", self.job, "--channel", "portal", "--submitted", "--material",
                                    self.material, "--sent", self.pdf, "--request-id", preview["request_id"])
        self.assertEqual(code, 2)
        connection = self.connect()
        # Even the tables of this first write were rolled back with it: the file holds an empty database.
        self.assertEqual(connection.execute("SELECT count(*) FROM sqlite_master").fetchone()[0], 0)
        self.assertEqual(list(self.paths.artifacts.rglob("*")), [])
        self.assertEqual(self.cli("list")[1]["applications"], [])
        # On a database that already has records, the failing request leaves the earlier ones as they were.
        application_id, draft = self.historical(), self.drafted()
        code, preview, _ = self.cli("submit", draft, "--expected-revision", "1", "--preview")
        before = self.cli("export")[1]["applications"]
        with mock.patch.object(applications, "_dump", failing):
            code, _, _ = self.cli("submit", draft, "--expected-revision", "1", "--material", self.material,
                                  "--sent", self.pdf, "--request-id", preview["request_id"])
        self.assertEqual(code, 2)
        self.assertEqual(self.cli("export")[1]["applications"], before)
        self.assertEqual(self.cli("validate")[1]["orphans"], [])
        self.assertEqual(self.show(application_id)["status"], "applied")


class Materials(Data):
    def submitted(self, *extra) -> dict:
        return self.write("record", self.job, "--channel", "portal", "--platform", "BOSS直聘", "--submitted",
                          "--on", "2026-11-02", "--material", self.material, "--sent", self.pdf, *extra)

    def test_the_material_and_the_sent_files_are_copied_with_their_digests(self):
        out = self.submitted()
        application = out["application"]
        self.assertTrue(application["submission"]["materials_recorded"])
        [version] = application["material_versions"]
        self.assertEqual(version["material_path"], f"materials/{self.job}/resume-1.json")
        self.assertEqual(version["profile_hash"], MATERIAL["profile_hash"])
        files = {item["file_id"]: item for item in version["files"]}
        self.assertEqual(set(files), {"material", "sent-1"})
        self.assertEqual(files["sent-1"]["path"].rsplit("/", 1)[1], "sent-1.pdf")
        for item in files.values():
            data = (self.paths.dir / item["path"]).read_bytes()
            self.assertEqual(applications._sha256(data), item["sha256"])
            self.assertEqual(len(data), item["size_bytes"])
        self.assertEqual((self.paths.dir / files["sent-1"]["path"]).read_bytes(), self.pdf.read_bytes())
        submitted = application["events"][1]["payload"]
        self.assertEqual(submitted["material_version_ids"], [version["version_id"]])
        self.assertEqual(submitted["sent_file_refs"], [{"version_id": version["version_id"], "file_id": "sent-1"}])
        snapshot = application["context_snapshot"]
        self.assertIsNotNone(snapshot["job"])
        self.assertIsNone(snapshot["match"])  # this job was never scored

    def test_later_edits_do_not_change_what_was_recorded(self):
        application_id = self.submitted()["application"]["application_id"]
        before = self.show(application_id)
        self.material.write_text(json.dumps({**MATERIAL, "job_id": self.job, "summary": None}), encoding="utf-8")
        self.pdf.write_bytes(b"%PDF-1.7 rebuilt later\n")
        profile = self.data / "profile" / "profile.json"
        profile.write_text(profile.read_text(encoding="utf-8").replace("示例理工大学", "示例科技大学"),
                           encoding="utf-8")
        job = self.data / "jobs" / f"{self.job}.json"
        job.write_text(job.read_text(encoding="utf-8").replace("实习", "全职"), encoding="utf-8")
        self.assertEqual(self.show(application_id), before)
        code, out, _ = self.cli("validate")
        self.assertEqual((code, out["errors"]), (0, []))

    def test_a_missing_or_changed_archive_is_reported(self):
        application = self.submitted()["application"]
        files = application["material_versions"][0]["files"]
        (self.paths.dir / files[0]["path"]).unlink()
        (self.paths.dir / application["context_snapshot"]["job"]["path"]).write_text("{}", encoding="utf-8")
        code, out, _ = self.cli("validate")
        self.assertEqual(code, 1)
        self.assertTrue(any("missing" in error for error in out["errors"]), out)
        self.assertTrue(any("changed since" in error for error in out["errors"]), out)

    def test_an_interrupted_archive_is_listed_as_an_orphan_and_nothing_in_the_database(self):
        self.submitted()
        stray = self.paths.artifacts / ("app_" + "c" * 32) / ("mv_" + "d" * 32 + ".tmp")
        stray.mkdir(parents=True)
        (stray / "sent-1.pdf").write_bytes(b"half")
        code, out, _ = self.cli("validate")
        self.assertEqual(code, 0)
        self.assertEqual(out["orphans"], [f"artifacts/app_{'c' * 32}/"])
        with mock.patch.object(applications.os, "rename", side_effect=OSError(28, "No space left on device")):
            code, preview, _ = self.cli("record", self.job, "--channel", "email", "--submitted", "--sent", self.pdf,
                                        "--preview")
            code, _, err = self.cli("record", self.job, "--channel", "email", "--submitted", "--sent", self.pdf,
                                    "--request-id", preview["request_id"])
        self.assertEqual(code, 2)
        self.assertEqual(self.connect().execute("SELECT count(*) FROM applications").fetchone()[0], 1)
        self.assertEqual(self.cli("validate")[1]["orphans"], [f"artifacts/app_{'c' * 32}/"])

    def test_the_passing_review_of_this_version_is_found(self):
        review = {"material": "resume-1.json", "material_hash": None, "verdict": "pass"}
        from jobsearch_cn import review as review_mod
        current = json.loads(self.material.read_text(encoding="utf-8"))
        folder = self.material.parent
        (folder / "review-1-r1.json").write_text(json.dumps({**review, "verdict": "revise",
                                                            "material_hash": review_mod.material_hash(current)}))
        (folder / "review-1-r2.json").write_text(json.dumps({**review,
                                                            "material_hash": review_mod.material_hash(current)}))
        version = self.submitted()["application"]["material_versions"][0]
        self.assertEqual(version["review_path"], f"materials/{self.job}/review-1-r2.json")
        self.assertEqual(version["material_hash"], review_mod.material_hash(current))

    def test_no_review_and_a_file_built_elsewhere_are_warnings(self):
        elsewhere = self.data / "改过的简历.docx"
        elsewhere.write_bytes(b"PK edited by hand")
        out = self.write("record", self.job, "--channel", "portal", "--submitted", "--material", self.material,
                         "--sent", self.pdf, elsewhere)
        warnings = "\n".join(out["warnings"])
        self.assertIn("no review", warnings)
        self.assertIn("改过的简历.docx", warnings)
        files = out["application"]["material_versions"][0]["files"]
        self.assertEqual([item["path"].rsplit("/", 1)[1] for item in files], ["material.json", "sent-1.pdf",
                                                                              "sent-2.docx"])

    def submit_with_material(self, *sent):
        return self.write("record", self.job, "--channel", "portal", "--submitted", "--material", self.material,
                          "--sent", *(sent or (self.pdf,)))

    def test_sent_files_are_checked_against_their_build_note(self):
        self.build_note()
        out = self.submit_with_material()
        self.assertEqual(out["application"]["submission"]["materials_check"], "match")
        self.assertEqual(out["application"]["events"][1]["payload"]["materials_check"], "match")
        self.assertNotIn("build", "\n".join(out["warnings"]))

    def test_a_mismatch_is_warned_recorded_and_exported(self):
        for case in ({"sha": "0" * 64}, {"material_hash": "f" * 64}):
            with self.subTest(case=case):
                self.build_note(**case)
                out = self.submit_with_material()
                application = out["application"]
                self.assertEqual(application["submission"]["materials_check"], "mismatch")
                self.assertIn("resume-1.build.json", "\n".join(out["warnings"]))
                self.assertTrue(application["submission"]["materials_recorded"])
                code, exported, err = self.cli("export")
                self.assertEqual(code, 0, err)
                mine = [item for item in exported["applications"]
                        if item["application_id"] == application["application_id"]]
                self.assertEqual(mine[0]["submission"]["materials_check"], "mismatch")
        code, out, err = self.cli("validate")
        self.assertEqual(code, 0, err)

    def test_the_material_s_build_note_checks_every_sent_file_renamed_or_not(self):
        """With --material, its note decides, not the sent file's name: a renamed copy matches, an edited one is a
        mismatch, not unchecked."""
        self.build_note()
        renamed = self.data / "姓名-岗位.pdf"
        renamed.write_bytes(self.pdf.read_bytes())
        out = self.submit_with_material(renamed)
        self.assertEqual(out["application"]["submission"]["materials_check"], "match")
        edited = self.data / "姓名-岗位-改.pdf"
        edited.write_bytes(self.pdf.read_bytes() + b"edited by hand\n")
        out = self.submit_with_material(renamed, edited)
        self.assertEqual(out["application"]["submission"]["materials_check"], "mismatch")
        warnings = "\n".join(out["warnings"])
        self.assertIn("姓名-岗位-改.pdf: not a file resume-1.build.json records", warnings)
        self.assertNotIn("姓名-岗位.pdf: not a file", warnings)

    def test_without_a_material_each_sent_file_is_looked_up_by_its_own_name(self):
        self.build_note()
        out = self.write("record", self.job, "--channel", "portal", "--submitted", "--sent", self.pdf)
        self.assertEqual(out["application"]["submission"]["materials_check"], "match")
        renamed = self.data / "姓名-岗位.pdf"
        renamed.write_bytes(self.pdf.read_bytes())
        out = self.write("record", self.job, "--channel", "portal", "--submitted", "--sent", renamed, self.pdf)
        self.assertEqual(out["application"]["submission"]["materials_check"], "unchecked")
        self.assertIn("姓名-岗位.pdf: no resume build note 姓名-岗位.build.json", "\n".join(out["warnings"]))

    def test_unchecked_is_warned_about_recorded_and_listed_by_validate(self):
        recorded = []
        for note in (None, "not json"):
            with self.subTest(note=note):
                if note is not None:
                    (self.pdf.parent / "resume-1.build.json").write_text(note, encoding="utf-8")
                out = self.submit_with_material()
                application = out["application"]
                self.assertEqual(application["submission"]["materials_check"], "unchecked")
                self.assertTrue(application["submission"]["materials_recorded"])
                self.assertRegex("\n".join(out["warnings"]),
                                 "resume-1.pdf: no resume build note resume-1.build.json" if note is None else
                                 "resume-1.build.json: the build note is unreadable; resume-1.pdf recorded unchecked")
                recorded.append(application["application_id"])
        code, out, err = self.cli("validate")
        self.assertEqual(code, 0, err)
        self.assertTrue(out["valid"])
        for application_id in recorded:
            self.assertIn(f"{application_id}: materials_check unchecked", "\n".join(out["warnings"]))

    def test_no_sent_file_is_null_and_not_warned_about(self):
        out = self.write("record", self.job, "--channel", "email", "--submitted")
        self.assertIsNone(out["application"]["submission"]["materials_check"])
        self.assertNotIn("build note", "\n".join(out["warnings"]))
        self.assertNotIn("materials_check", "\n".join(self.cli("validate")[1]["warnings"]))

    def test_a_material_for_another_job_or_an_invalid_one_is_refused(self):
        other = self.data / "resume-1.json"
        other.write_text(json.dumps(MATERIAL, ensure_ascii=False), encoding="utf-8")
        code, _, err = self.cli("record", self.job, "--channel", "portal", "--submitted", "--material", other,
                                "--preview")
        self.assertEqual((code, err["error"]), (1, "invalid"))
        self.assertIn("not for", err["message"])
        broken = {**MATERIAL, "job_id": self.job, "experience": [{"ref": "exp-404", "bullets": []}]}
        self.material.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
        code, _, err = self.cli("record", self.job, "--channel", "portal", "--submitted", "--material",
                                self.material, "--preview")
        self.assertEqual((code, err["error"]), (1, "invalid"))
        self.assertTrue(err["errors"])
        self.material.write_text("{not json", encoding="utf-8")
        code, _, err = self.cli("record", self.job, "--channel", "portal", "--submitted", "--material",
                                self.material, "--preview")
        self.assertEqual(code, 2)

    def test_a_current_submission_without_material_is_recorded_with_a_warning(self):
        out = self.write("record", self.job, "--channel", "portal", "--platform", "BOSS直聘", "--submitted")
        self.assertIn("材料未记录", "\n".join(out["warnings"]))
        application = out["application"]
        self.assertIs(application["submission"]["materials_recorded"], False)
        self.assertEqual(application["material_versions"], [])
        self.assertIsNotNone(application["context_snapshot"]["job"])
        code, result, _ = self.cli("validate")
        self.assertEqual(code, 0)
        self.assertIn("材料未记录", "\n".join(result["warnings"]))

    def test_submit_archives_like_record_and_keeps_the_snapshot_of_that_moment(self):
        application_id = self.drafted()
        self.assertIsNone(self.show(application_id)["submission"]["materials_recorded"])
        out = self.write("submit", application_id, "--expected-revision", "1", "--channel", "email",
                         "--material", self.material, "--sent", self.pdf)
        application = out["application"]
        self.assertEqual(application["channel"], {"kind": "email", "platform": None})
        self.assertEqual(len(application["material_versions"]), 1)
        self.assertIsNotNone(application["context_snapshot"]["job"])

    def test_material_and_sent_files_belong_to_a_submission(self):
        code, _, err = self.cli("record", self.job, "--channel", "portal", "--sent", self.pdf, "--preview")
        self.assertEqual((code, err["error"]), (1, "invalid"))

    def test_a_historical_record_needs_no_stored_job_material_or_date(self):
        missing = "job_" + "0" * 11 + "9"
        out = self.write("record", missing, "--channel", "unknown", "--submitted", "--historical")
        application = out["application"]
        self.assertEqual((application["record_origin"], application["status"]), ("historical", "applied"))
        self.assertEqual(application["context_snapshot"], {"job": None, "match": None})
        self.assertNotIn("材料未记录", "\n".join(out["warnings"]))
        code, _, err = self.cli("record", missing, "--channel", "portal", "--preview")
        self.assertEqual((code, err["error"]), (1, "not_found"))
        code, _, err = self.cli("record", self.job, "--channel", "portal", "--historical", "--preview")
        self.assertEqual((code, err["error"]), (1, "invalid"))


class Times(Data):
    def test_a_date_a_moment_or_neither_are_kept_as_given(self):
        on = self.write("record", self.job, "--channel", "portal", "--submitted", "--on", "2026-11-02")
        at = self.write("record", self.job, "--channel", "email", "--submitted", "--at", "2026-11-02T14:30+08:00")
        neither = self.write("record", self.job, "--channel", "referral", "--submitted")
        self.assertEqual(on["application"]["submission"]["occurred_on"], "2026-11-02")
        self.assertIsNone(on["application"]["submission"]["occurred_at"])
        self.assertEqual(at["application"]["submission"]["occurred_at"], "2026-11-02T06:30:00Z")
        self.assertIsNone(at["application"]["submission"]["occurred_on"])
        self.assertEqual({key: value for key, value in neither["application"]["submission"].items()
                          if key.startswith("occurred")}, {"occurred_at": None, "occurred_on": None})
        exported = {item["channel"]["kind"]: item["submission"] for item in self.cli("export")[1]["applications"]}
        self.assertEqual(exported["portal"]["occurred_on"], "2026-11-02")
        self.assertIsNone(exported["referral"]["occurred_on"])
        self.assertEqual(self.write("record", self.job, "--channel", "other", "--submitted", "--at",
                                    "2026-11-02T06:30:00Z")["application"]["submission"]["occurred_at"],
                         "2026-11-02T06:30:00Z")

    def test_a_moment_without_a_time_zone_and_impossible_dates_are_refused(self):
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat()
        for flag, value in (("--at", "2026-11-02T14:30"), ("--at", "2026-11-02"), ("--on", "2026-02-30"),
                            ("--on", "2026/11/02"), ("--on", tomorrow), ("--at", tomorrow + "T10:00+08:00")):
            with self.subTest(value=value):
                code, _, err = self.cli("record", self.job, "--channel", "portal", "--submitted", flag, value,
                                        "--preview")
                self.assertEqual((code, err["error"]), (1, "invalid"))

    def test_a_status_change_keeps_its_own_date(self):
        application_id = self.historical(on="2026-10-01")
        out = self.move(application_id, "interview", "--on", "2026-10-15")
        event = out["events"][0]
        self.assertEqual((event["occurred_on"], event["payload"]), ("2026-10-15", {
            "from": "applied", "to": "interview", "reason": None}))
        self.assertEqual(out["application"]["submission"]["occurred_on"], "2026-10-01")


class DraftsAndChannels(Data):
    def test_a_draft_is_only_drafted_and_a_second_channel_is_a_second_application(self):
        first = self.drafted("portal")
        code, preview, _ = self.cli("record", self.job, "--channel", "email", "--preview")
        self.assertIn(first, "\n".join(preview["warnings"]))
        second = self.write("record", self.job, "--channel", "email")
        self.assertIn(first, "\n".join(second["warnings"]))
        listed = self.cli("list")[1]["applications"]
        self.assertEqual(len(listed), 2)
        self.assertEqual({item["status"] for item in listed}, {"drafted"})
        self.assertEqual({item["submission"]["confirmed"] for item in listed}, {False})
        job = json.loads((self.data / "jobs" / f"{self.job}.json").read_text(encoding="utf-8"))
        self.assertEqual({(item["title"], item["company"]) for item in listed}, {(job["title"], job["company"])})

    def test_list_filters_and_puts_the_latest_submission_first(self):
        old = self.historical(on="2026-09-01")
        new = self.historical(on="2026-10-30")
        draft = self.drafted()
        self.move(old, "rejected")
        ids = [item["application_id"] for item in self.cli("list")[1]["applications"]]
        self.assertEqual(ids, [new, old, draft])
        self.assertEqual([item["application_id"] for item in self.cli("list", "--status", "rejected", "drafted")[1]
                          ["applications"]], [old, draft])
        self.assertEqual(self.cli("list", "--job", "job_" + "f" * 12)[1]["applications"], [])
        code, _, err = self.cli("list", "--job", "nope")
        self.assertEqual(code, 1)


class Export(Data):
    def test_two_exports_of_the_same_records_are_the_same_but_for_the_time(self):
        self.write("record", self.job, "--channel", "portal", "--submitted", "--material", self.material,
                   "--sent", self.pdf)
        self.historical()
        with mock.patch.object(applications, "now_utc", return_value="2026-11-03T00:00:00Z"):
            first = io.StringIO()
            with contextlib.redirect_stdout(first):
                cli.main(["application", "export", "--data-dir", str(self.data)])
            second = io.StringIO()
            with contextlib.redirect_stdout(second):
                cli.main(["application", "export", "--data-dir", str(self.data)])
        self.assertEqual(first.getvalue(), second.getvalue())
        document = json.loads(first.getvalue())
        self.assertEqual(list(document), ["schema_version", "exported_at", "applications"])
        ids = [item["application_id"] for item in document["applications"]]
        self.assertEqual(ids, sorted(ids))

    def test_out_takes_a_file_name_and_writes_into_exports(self):
        self.historical()
        for name in ("../escape.json", "sub/x.json", str(self.data / "x.json"), "x.txt", "CON.json", ".json"):
            with self.subTest(name=name):
                code, _, err = self.cli("export", "--out", name)
                self.assertEqual((code, err["error"]), (1, "invalid"))
        self.assertFalse((self.paths.dir / "exports").exists())
        code, out, _ = self.cli("export", "--out", "all.json")
        self.assertEqual((code, out["applications"]), (0, 1))
        written = json.loads((self.paths.dir / "exports" / "all.json").read_text(encoding="utf-8"))
        self.assertEqual(len(written["applications"]), 1)

    def test_export_of_named_applications(self):
        first, second = self.historical(), self.historical()
        document = self.cli("export", second)[1]
        self.assertEqual([item["application_id"] for item in document["applications"]], [second])
        code, _, err = self.cli("export", "app_" + "e" * 32)
        self.assertEqual((code, err["error"]), (1, "not_found"))


class Privacy(Data):
    def test_the_database_its_journal_exports_and_archives_are_ignored_by_git(self):
        paths = ["data/applications/applications.sqlite3", "data/applications/applications.sqlite3-journal",
                 "data/applications/applications.sqlite3-wal", "data/applications/applications.sqlite3-shm",
                 "data/applications/exports/all.json", "data/applications/backups/x.sqlite3",
                 "data/applications/artifacts/app_x/mv_y/sent-1.pdf"]
        result = subprocess.run(["git", "check-ignore", "--no-index", *paths], cwd=REPO, capture_output=True,
                                text=True)
        if result.returncode == 128:
            self.skipTest("not a git checkout")
        self.assertEqual(result.stdout.split(), paths)

    def test_show_list_and_export_hold_no_contact_details(self):
        application_id = self.write("record", self.job, "--channel", "portal", "--submitted", "--material",
                                    self.material, "--sent", self.pdf)["application"]["application_id"]
        for args in (("show", application_id), ("list",), ("export",)):
            text = json.dumps(self.cli(*args)[1], ensure_ascii=False)
            for contact in CONTACTS:
                self.assertNotIn(contact, text, args)

    def test_contact_details_in_a_reason_or_platform_are_warned_about(self):
        application_id = self.historical()
        code, preview, _ = self.status(application_id, "interview", "--reason", "HR 留了电话 13900001111")
        self.assertIn("phone", "\n".join(preview["warnings"]))
        self.move(application_id, "interview", "--reason", "见 https://example.com/x")
        self.assertIn("link", "\n".join(self.cli("validate")[1]["warnings"]))
        code, _, err = self.status(application_id, "offer", "--reason", "x" * 301)
        self.assertEqual((code, err["error"]), (1, "invalid"))


class ReadOnly(Data):
    def test_reading_commands_create_nothing(self):
        before = self.files()
        self.assertEqual(self.cli("list")[1], {"applications": [], "note": "no application records yet"})
        self.assertEqual(self.cli("validate")[0], 0)
        self.assertEqual(self.cli("export")[1]["applications"], [])
        code, _, err = self.cli("show", "app_" + "b" * 32)
        self.assertEqual((code, err["error"]), (1, "not_found"))
        self.assertEqual(self.files(), before)

    def test_reading_an_existing_database_changes_no_byte(self):
        application_id = self.historical()
        before = {path: path.read_bytes() for path in self.paths.dir.rglob("*") if path.is_file()}
        for args in (("show", application_id), ("list",), ("validate",), ("export",)):
            self.assertEqual(self.cli(*args)[0], 0)
        after = {path: path.read_bytes() for path in self.paths.dir.rglob("*") if path.is_file()}
        self.assertEqual(after, before)


class Validate(Data):
    def test_a_projection_that_disagrees_with_the_events_is_an_error(self):
        application_id = self.historical()
        with self.connect() as connection:
            connection.execute("UPDATE applications SET status = 'offer' WHERE application_id = ?",
                               (application_id,))
        code, out, _ = self.cli("validate")
        self.assertEqual(code, 1)
        self.assertTrue(any("status" in error for error in out["errors"]), out)

    def test_a_gap_in_the_events_or_a_bad_payload_is_an_error(self):
        application_id = self.historical()
        with self.connect() as connection:
            connection.execute("UPDATE events SET payload = '{\"x\": 1}' WHERE application_id = ? AND seq = 2",
                               (application_id,))
        self.assertTrue(any("payload" in error for error in self.cli("validate")[1]["errors"]))
        with self.connect() as connection:
            connection.execute("UPDATE events SET seq = 5 WHERE application_id = ? AND seq = 2", (application_id,))
        self.assertTrue(any("numbered" in error for error in self.cli("validate")[1]["errors"]))

    def test_a_clean_database_is_valid(self):
        application_id = self.drafted()
        self.build_note()
        self.write("submit", application_id, "--expected-revision", "1", "--material", self.material,
                   "--sent", self.pdf)
        self.move(application_id, "interview")
        self.assertEqual(self.cli("validate")[1], {"valid": True, "errors": [], "warnings": [], "orphans": []})


class Document(unittest.TestCase):
    def test_the_document_names_exactly_the_commands_the_cli_has(self):
        text = (REPO / "docs" / "cn" / "applications.md").read_text(encoding="utf-8")
        documented = set(re.findall(r"python -m jobsearch_cn application ([a-z]+)", text))
        parser = cli.build_parser()
        group = next(action for action in parser._subparsers._group_actions[0].choices["application"]._actions
                     if isinstance(action, argparse._SubParsersAction))
        self.assertEqual(documented, set(group.choices))
        for code in ("invalid", "transition", "stale_revision", "request_conflict", "busy", "not_found"):
            self.assertIn(f"`{code}`", text)
        for status in applications.STATUSES:
            self.assertIn(f"`{status}`", text)
        for channel in applications.CHANNELS:
            self.assertIn(f"`{channel}`", text)


if __name__ == "__main__":
    unittest.main()
