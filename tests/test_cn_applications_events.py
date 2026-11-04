"""Application records, second part (M4-1b): reply, note, followup and list --due, void, backup.

Rulings in docs/cn/worklog/2026-11-04-m4-1b-applications.md; the format in docs/cn/applications.md. Every record
here is fictional: the public fixtures and temporary data directories of tests/test_cn_applications.py.
"""

import hashlib
import json
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from jobsearch_cn import applications
from tests.test_cn_applications import Data, run
from tests.test_cn_store_links import link


class Events(Data):
    def act(self, command, application_id, *args):
        """A committed write on an existing application at its current revision."""
        return self.write(command, application_id, "--expected-revision", self.show(application_id)["revision"],
                          *args)

    def refused(self, command, application_id, *args):
        """(exit code, error code) of a preview that is refused."""
        code, out, err = self.cli(command, application_id, "--expected-revision",
                                  self.show(application_id)["revision"], *args, "--preview")
        return code, (err or {}).get("error")


class Replies(Events):
    def test_a_reply_needs_a_sent_application_and_changes_no_status(self):
        drafted = self.drafted()
        self.assertEqual(self.refused("reply", drafted, "--summary", "HR 说下周给结果"), (1, "transition"))
        sent = self.historical()
        out = self.act("reply", sent, "--summary", "HR 说下周给结果", "--on", "2026-10-25")
        application = out["application"]
        self.assertEqual((application["status"], application["revision"]), ("applied", 3))
        [event] = out["events"]
        self.assertEqual((event["type"], event["payload"], event["occurred_on"]),
                         ("reply_received", {"summary": "HR 说下周给结果"}, "2026-10-25"))
        self.assertEqual(self.refused("reply", sent, "--summary", "未来的回复", "--on", "2099-01-01"), (1, "invalid"))
        self.move(sent, "rejected")
        self.assertEqual(self.act("reply", sent, "--summary", "对方给了反馈")["application"]["status"], "rejected")

    def test_a_reply_needs_a_submission_that_stands_not_only_a_status_past_drafted(self):
        """#126 P2-2: drafted -> withdrawn is allowed, so withdrawn alone does not say the application was sent."""
        never = self.drafted()
        self.move(never, "withdrawn", "--reason", "记录错误，没有投出")
        self.assertEqual(self.refused("reply", never, "--summary", "对方给了反馈"), (1, "transition"))
        code, _, err = self.cli("reply", never, "--expected-revision", 2, "--summary", "对方给了反馈",
                                "--request-id", applications.new_id("req"))  # a commit is refused too
        self.assertEqual((code, err["error"], err["status"]), (1, "transition", "withdrawn"))
        voided = self.write("record", self.job, "--channel", "email", "--submitted",
                            "--on", "2026-11-01")["application"]["application_id"]
        self.act("void", voided, "--reason", "其实没投")
        self.move(voided, "withdrawn", "--reason", "记错了")
        self.assertEqual(self.refused("reply", voided, "--summary", "对方给了反馈"), (1, "transition"))
        sent = self.write("record", self.job, "--channel", "portal", "--submitted",
                          "--on", "2026-11-01")["application"]["application_id"]
        self.move(sent, "withdrawn", "--reason", "不想去了")
        self.assertEqual(self.act("reply", sent, "--summary", "HR 表示理解")["application"]["status"], "withdrawn")
        code, checked, _ = self.cli("validate")
        self.assertEqual((code, checked["errors"]), (0, []))
        self.assertEqual(len(self.show(never)["events"]), 2)
        with self.connect() as connection:  # validate replays with the same rule
            connection.execute(
                "INSERT INTO events (application_id, seq, event_id, request_id, type, occurred_at, occurred_on, "
                "recorded_at, actor, source_kind, payload, voided_by) VALUES (?, 3, ?, ?, 'reply_received', NULL, "
                "NULL, '2026-11-04T00:00:00Z', 'user', 'user', ?, NULL)",
                (never, applications.new_id("evt"), applications.new_id("req"), json.dumps({"summary": "对方给了反馈"})))
        code, checked, _ = self.cli("validate")
        self.assertEqual(code, 1)
        self.assertIn(f"{never}: the events do not replay: a reply comes to an application that was sent",
                      "\n".join(checked["errors"]))

    def test_a_note_goes_on_any_status_and_has_no_date(self):
        drafted = self.drafted()
        self.assertEqual(self.act("note", drafted, "--text", "等内推人回复")["application"]["status"], "drafted")
        sent = self.historical()
        self.move(sent, "rejected")
        [event] = self.act("note", sent, "--text", "明年再试")["events"]
        self.assertEqual((event["type"], event["occurred_at"], event["occurred_on"]), ("note_added", None, None))
        with self.assertRaises(SystemExit) as refused:  # argparse: a note takes no --on
            self.cli("note", sent, "--expected-revision", 4, "--text", "x", "--on", "2026-10-01", "--preview")
        self.assertEqual(refused.exception.code, 2)

    def test_texts_are_checked_and_contact_details_warned_about(self):
        sent = self.historical()
        self.assertEqual(self.refused("note", sent, "--text", "长" * 301), (1, "invalid"))
        self.assertEqual(self.refused("reply", sent, "--summary", "  "), (1, "invalid"))
        out = self.act("reply", sent, "--summary", "让我打 13800000000")
        self.assertIn("--summary", "\n".join(out["warnings"]))
        code, checked, _ = self.cli("validate")
        self.assertEqual(code, 0)
        self.assertIn("summary", "\n".join(checked["warnings"]))


class Followups(Events):
    def test_a_followup_is_for_a_sent_application_still_open(self):
        self.assertEqual(self.refused("followup", self.drafted(), "--due", "2099-01-05"), (1, "transition"))
        sent = self.historical()
        out = self.act("followup", sent, "--due", "2099-01-05")
        self.assertEqual(out["application"]["next_followup_on"], "2099-01-05")
        self.assertEqual(out["events"][0]["payload"], {"due_on": "2099-01-05"})
        self.move(sent, "rejected")
        self.assertIsNone(self.show(sent)["next_followup_on"])
        self.assertEqual(self.refused("followup", sent, "--due", "2099-01-05"), (1, "transition"))

    def test_no_response_is_no_longer_waiting(self):
        sent = self.historical()
        self.act("followup", sent, "--due", "2099-01-05")
        self.move(sent, "no_response")
        self.assertIsNone(self.show(sent)["next_followup_on"])
        self.assertEqual(self.refused("followup", sent, "--due", "2099-01-05"), (1, "transition"))
        self.move(sent, "interview", "--reason", "迟到的面试邀请")
        self.assertEqual(self.act("followup", sent, "--due", "2099-01-06")["application"]["next_followup_on"],
                         "2099-01-06")

    def test_the_day_may_be_today_not_past(self):
        sent = self.historical()
        self.assertEqual(self.refused("followup", sent, "--due", "2020-01-01"), (1, "invalid"))
        today = applications._today().isoformat()
        self.assertEqual(self.act("followup", sent, "--due", today)["application"]["next_followup_on"], today)

    def test_the_same_request_retried_the_next_day_returns_what_it_wrote(self):
        """#126 P2-3: "not before today" holds new requests only; a retry of one already written gets its result."""
        sent = self.historical()
        args = ("followup", sent, "--expected-revision", 2, "--due", "2030-05-01")
        with mock.patch.object(applications, "_today", return_value=date(2030, 5, 1)):
            code, preview, err = self.cli(*args, "--preview")
            self.assertEqual(code, 0, err)
            first = self.cli(*args, "--request-id", preview["request_id"])[1]
            self.assertEqual(self.cli(*args, "--request-id", preview["request_id"])[1]["repeated"], True)
        with mock.patch.object(applications, "_today", return_value=date(2030, 5, 2)):
            code, retry, err = self.cli(*args, "--request-id", preview["request_id"])
            self.assertEqual((code, retry["repeated"], retry["events"]), (0, True, first["events"]), err)
            self.assertEqual(retry["application"]["next_followup_on"], "2030-05-01")
            changed = ("followup", sent, "--expected-revision", 2, "--due", "2030-05-03")
            code, _, err = self.cli(*changed, "--request-id", preview["request_id"])
            self.assertEqual((code, err["error"]), (1, "request_conflict"))
            again = ("followup", sent, "--expected-revision", 3, "--due", "2030-05-01")  # a new request, the next day
            self.assertEqual(self.cli(*again, "--preview")[2]["error"], "invalid")
            code, _, err = self.cli(*again, "--request-id", applications.new_id("req"))
            self.assertEqual((code, err["error"]), (1, "invalid"))
        self.assertEqual(len(self.show(sent)["events"]), 3)

    def test_cancel_needs_a_day_set_and_clears_it(self):
        sent = self.historical()
        self.assertEqual(self.refused("followup", sent, "--cancel"), (1, "invalid"))
        self.act("followup", sent, "--due", "2099-01-05")
        out = self.act("followup", sent, "--cancel")
        self.assertIsNone(out["application"]["next_followup_on"])
        self.assertEqual((out["events"][0]["type"], out["events"][0]["payload"]), ("followup_cancelled", {}))

    def test_list_due_lists_what_came_due_and_what_has_no_day(self):
        later, sooner = self.historical("2026-10-01"), self.historical("2026-10-02")
        self.act("followup", later, "--due", "2099-01-05")
        self.act("followup", sooner, "--due", "2099-01-01")
        old, recent = self.historical("2026-09-01"), self.historical("2026-10-20")
        unknown = self.write("record", self.job, "--channel", "email", "--submitted",
                             "--historical")["application"]["application_id"]
        self.drafted()  # never listed
        ended = self.historical()
        self.move(ended, "rejected")
        waiting_no_more = self.historical()
        self.move(waiting_no_more, "no_response")
        code, out, err = self.cli("list", "--due", "--as-of", "2099-01-05")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["as_of"], "2099-01-05")
        self.assertEqual([(item["application_id"], item["days_overdue"]) for item in out["due"]],
                         [(sooner, 4), (later, 0)])
        self.assertEqual([item["application_id"] for item in out["unset"]], [old, recent, unknown])
        self.assertEqual([item["application_id"] for item in self.cli("list", "--due", "--as-of", "2099-01-02")[1]
                          ["due"]], [sooner])
        with mock.patch.object(applications, "_today", return_value=date(2099, 1, 5)):
            self.assertEqual(self.cli("list", "--due")[1]["as_of"], "2099-01-05")
        self.assertEqual(self.cli("list", "--as-of", "2099-01-05")[0], 1)  # --as-of goes with --due
        listed = {item["application_id"]: item for item in self.cli("list")[1]["applications"]}
        self.assertEqual(listed[later]["next_followup_on"], "2099-01-05")

    def test_list_due_without_records(self):
        with tempfile.TemporaryDirectory() as empty:
            code, out, _ = self.cli("list", "--due", "--as-of", "2099-01-05", "--data-dir", empty)
        self.assertEqual((code, out["due"], out["unset"]), (0, [], []))


class Voids(Events):
    def test_a_void_takes_back_the_latest_event_and_steps_back_one_at_a_time(self):
        sent = self.write("record", self.job, "--channel", "email", "--submitted",
                          "--on", "2026-11-01")["application"]["application_id"]
        self.move(sent, "interview")
        self.act("note", sent, "--text", "二面")
        first = self.act("void", sent, "--reason", "记错了")
        self.assertEqual((first["voids"]["seq"], first["application"]["status"]), (4, "interview"))
        events = first["application"]["events"]
        self.assertEqual(events[3]["voided_by"], events[4]["event_id"])
        self.assertEqual(events[4]["payload"], {"target_event_id": events[3]["event_id"], "reason": "记错了"})
        second = self.act("void", sent, "--reason", "其实没面试")
        self.assertEqual((second["voids"]["seq"], second["application"]["status"]), (3, "applied"))
        third = self.act("void", sent, "--reason", "其实没投")  # the voids themselves are passed over
        application = third["application"]
        self.assertEqual((third["voids"]["type"], application["status"]), ("submitted", "drafted"))
        self.assertEqual(application["submission"], {"confirmed": False, "occurred_at": None, "occurred_on": None,
                                                     "materials_recorded": None, "materials_check": None})
        self.assertEqual(application["revision"], 7)
        self.assertEqual(self.refused("void", sent, "--reason", "整条记错了"), (1, "invalid"))
        self.move(sent, "withdrawn", "--reason", "记错了")
        self.assertTrue(self.cli("validate")[1]["valid"])

    def test_a_historical_submission_is_not_voided_alone(self):
        sent = self.historical()
        self.assertEqual(self.refused("void", sent, "--reason", "记错了"), (1, "invalid"))

    def test_a_voided_submission_keeps_its_archive_and_a_new_one_keeps_the_first_snapshot(self):
        out = self.write("record", self.job, "--channel", "portal", "--submitted", "--on", "2026-11-02",
                         "--material", self.material, "--sent", self.pdf)
        application_id = out["application"]["application_id"]
        snapshot = out["application"]["context_snapshot"]
        self.act("void", application_id, "--reason", "还没投")
        shown = self.show(application_id)
        self.assertEqual(shown["status"], "drafted")
        [version] = shown["material_versions"]
        for item in version["files"]:
            self.assertTrue((self.paths.dir / item["path"]).is_file())
        again = self.act("submit", application_id, "--on", "2026-11-03", "--material", self.material,
                         "--sent", self.pdf)["application"]
        self.assertEqual((again["status"], len(again["material_versions"])), ("applied", 2))
        self.assertEqual(again["context_snapshot"], snapshot)
        self.assertEqual(again["submission"]["occurred_on"], "2026-11-03")
        code, checked, err = self.cli("validate")
        self.assertEqual((code, checked["errors"]), (0, []), err)

    def test_the_preview_names_the_target_and_a_retry_returns_the_first_result(self):
        sent = self.write("record", self.job, "--channel", "email", "--submitted",
                          "--on", "2026-11-01")["application"]["application_id"]
        code, preview, _ = self.cli("void", sent, "--expected-revision", 2, "--reason", "记错了", "--preview")
        self.assertEqual((code, preview["voids"]["type"], preview["status"]), (0, "submitted",
                                                                               {"from": "applied", "to": "drafted"}))
        args = ("void", sent, "--expected-revision", 2, "--reason", "记错了", "--request-id", preview["request_id"])
        first, retry = self.cli(*args)[1], self.cli(*args)[1]
        self.assertEqual((first["repeated"], retry["repeated"]), (False, True))
        self.assertEqual(retry["events"], first["events"])
        self.assertEqual(len(self.show(sent)["events"]), 3)
        code, _, err = self.cli("void", sent, "--expected-revision", 2, "--reason", "记错了", "--preview")
        self.assertEqual((code, err["error"]), (1, "stale_revision"))

    def test_validate_reports_a_void_that_does_not_hold(self):
        sent = self.historical()
        self.move(sent, "interview")
        self.act("void", sent, "--reason", "记错了")
        connection = self.connect()
        with connection:
            connection.execute("UPDATE events SET voided_by = NULL WHERE application_id = ? AND seq = 3", (sent,))
        code, checked, _ = self.cli("validate")
        self.assertEqual(code, 1)
        self.assertIn("whose voided_by does not name it", "\n".join(checked["errors"]))
        with connection:
            void_id = connection.execute("SELECT event_id FROM events WHERE seq = 4").fetchone()[0]
            connection.execute("UPDATE events SET voided_by = ? WHERE application_id = ? AND seq IN (2, 3)",
                               (void_id, sent))
        code, checked, _ = self.cli("validate")
        self.assertEqual(code, 1)
        self.assertIn("voided_by names no void", "\n".join(checked["errors"]))


class Backups(Events):
    def sha(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def backed_up(self) -> tuple:
        self.write("record", self.job, "--channel", "portal", "--submitted", "--on", "2026-11-02",
                   "--material", self.material, "--sent", self.pdf)
        before = self.sha(self.paths.db)
        code, out, err = self.cli("backup")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sha(self.paths.db), before)  # a backup changes no record
        return out, self.paths.dir / "backups" / out["backup"]

    def test_a_backup_holds_the_database_the_archive_and_a_manifest(self):
        out, folder = self.backed_up()
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest, out["manifest"])
        self.assertEqual((manifest["kind"], manifest["counts"], manifest["source_valid"]),
                         ("applications-backup", {"applications": 1, "events": 2}, True))
        self.assertEqual(manifest["database"]["sha256"], self.sha(folder / "applications.sqlite3"))
        self.assertEqual(len(manifest["artifacts"]), 3)  # material, sent-1 and the job; this job was never scored
        for item in manifest["artifacts"]:
            self.assertEqual(self.sha(folder / item["path"]), self.sha(self.paths.dir / item["path"]))
        code, checked, err = self.cli("validate", "--backup", out["backup"])
        self.assertEqual((code, checked["valid"], checked["backup"]), (0, True, out["backup"]), err)

    def test_a_changed_or_incomplete_backup_is_reported(self):
        out, folder = self.backed_up()
        copied = folder / out["manifest"]["artifacts"][0]["path"]
        copied.write_bytes(copied.read_bytes() + b"changed")
        code, checked, _ = self.cli("validate", "--backup", out["backup"])
        self.assertEqual(code, 1)
        self.assertIn(out["manifest"]["artifacts"][0]["path"], "\n".join(checked["errors"]))
        with open(folder / "applications.sqlite3", "ab") as handle:
            handle.write(b"\0")
        self.assertIn("not the database", "\n".join(self.cli("validate", "--backup", out["backup"])[1]["errors"]))
        (folder / "manifest.json").unlink()
        self.assertIn("manifest.json", "\n".join(self.cli("validate", "--backup", out["backup"])[1]["errors"]))

    def test_a_backup_is_named_by_its_utc_time_and_never_reuses_a_name(self):
        with tempfile.TemporaryDirectory() as directory:
            backups = Path(directory)
            self.assertEqual(applications.backup_name(backups, "20990101T000000Z"), "20990101T000000Z")
            (backups / "20990101T000000Z").mkdir()
            (backups / "20990101T000000Z-2.tmp").mkdir()
            self.assertEqual(applications.backup_name(backups, "20990101T000000Z"), "20990101T000000Z-3")

    def test_names_that_are_no_backup_and_no_records(self):
        code, _, err = self.cli("backup")
        self.assertEqual((code, err["error"]), (1, "not_found"))
        self.assertFalse((self.paths.dir / "backups").exists())
        self.historical()
        for name, error in (("../applications", "invalid"), ("20990101T000000Z", "not_found")):
            code, _, err = self.cli("validate", "--backup", name)
            self.assertEqual((code, err["error"]), (1, error), name)

    def test_an_unfinished_backup_is_an_orphan(self):
        self.historical()
        (self.paths.dir / "backups" / "20990101T000000Z.tmp").mkdir(parents=True)
        code, checked, _ = self.cli("validate")
        self.assertEqual((code, checked["orphans"]), (0, ["backups/20990101T000000Z.tmp/"]))

    def restored(self, folder: Path) -> tuple:
        """(exit code, validate output) once the backup in folder alone is copied into a new data directory, by the
        manual steps of docs/cn/applications.md §15."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        target = Path(directory.name) / "applications"
        target.mkdir()
        shutil.copy2(folder / "applications.sqlite3", target)
        if (folder / "artifacts").is_dir():
            shutil.copytree(folder / "artifacts", target / "artifacts")
        code, checked, _ = run("application", "validate", "--data-dir", directory.name)
        return code, checked

    def test_a_backup_restores_on_its_own_into_a_new_data_directory(self):
        out, folder = self.backed_up()
        code, checked = self.restored(folder)
        self.assertEqual((code, checked["valid"], checked["orphans"]), (0, True, []), checked["errors"])

    # #126 P2-1: Windows also splits on \, starts over at a drive, and drops a trailing dot; none of these may
    # carry a recorded path out of artifacts/, on any system.
    ESCAPES = ("artifacts/..\\..\\review-marker.txt", "artifacts\\..\\..\\review-marker.txt",
               "artifacts/C:review-marker.txt", "artifacts/C:\\review-marker.txt", "artifacts/../../review-marker.txt",
               "/review-marker.txt", "C:/review-marker.txt", "artifacts/x/sent-1.pdf:stream", "artifacts/x/sent-1.pdf.",
               "artifacts/x/NUL.pdf", "artifacts//sent-1.pdf")

    def tampered(self, relative: str) -> None:
        """The sent file's row names relative, with the digest and size of a marker in the data root (Codex B's
        repro, step 2; only this fictional temporary database is changed)."""
        marker = self.data / "review-marker.txt"
        marker.write_bytes(b"fictional review marker\n")
        with self.connect() as connection:
            connection.execute("UPDATE material_files SET path = ?, sha256 = ?, size_bytes = ? WHERE file_id = 'sent-1'",
                               (relative, self.sha(marker), marker.stat().st_size))

    def test_a_path_windows_would_read_out_of_artifacts_is_refused_on_every_system(self):
        self.write("record", self.job, "--channel", "portal", "--submitted", "--on", "2026-11-02",
                   "--material", self.material, "--sent", self.pdf)
        backups = self.paths.dir / "backups"
        for relative in self.ESCAPES:
            with self.subTest(relative=relative):
                self.tampered(relative)
                refused = f"archive path {relative!r} is not a plain path under artifacts/"
                code, checked, _ = self.cli("validate")
                self.assertEqual(code, 1)
                self.assertIn(refused, "\n".join(checked["errors"]))
                outside = [item for item in self.files() if not item.startswith("applications/backups")]
                code, out, err = self.cli("backup")
                self.assertEqual(code, 0, err)  # the records are kept as they are, and said not to pass
                self.assertFalse(out["manifest"]["source_valid"])
                self.assertIn(f"{refused}; not copied", out["warnings"])
                self.assertNotIn(relative, [item["path"] for item in out["manifest"]["artifacts"]])
                self.assertEqual([item for item in self.files() if not item.startswith("applications/backups")],
                                 outside)  # nothing written beside the data, and nothing in backups/ but backups
                self.assertTrue(all(item.is_dir() and applications._BACKUP_NAME.fullmatch(item.name)
                                    for item in backups.iterdir()))
                code, checked, _ = self.cli("validate", "--backup", out["backup"])
                self.assertEqual((code, checked["valid"]), (1, False))
                self.assertIn(refused, "\n".join(checked["errors"]))
                self.assertEqual(self.restored(backups / out["backup"])[0], 1)

    def test_a_manifest_path_out_of_the_backup_is_refused(self):
        out, folder = self.backed_up()
        marker = folder.parent / "review-marker.txt"  # where artifacts/..\..\ leads from inside the backup
        marker.write_bytes(b"fictional review marker\n")
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        relative = self.ESCAPES[0]
        manifest["artifacts"][0] = {"path": relative, "sha256": self.sha(marker), "size_bytes": marker.stat().st_size}
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        code, checked, _ = self.cli("validate", "--backup", out["backup"])
        self.assertEqual(code, 1)
        self.assertIn(f"manifest: archive path {relative!r} is not a plain path under artifacts/",
                      "\n".join(checked["errors"]))

    def test_an_archive_folder_that_is_a_link_is_not_followed(self):
        out = self.write("record", self.job, "--channel", "portal", "--submitted", "--on", "2026-11-02",
                         "--material", self.material, "--sent", self.pdf)
        [version] = out["application"]["material_versions"]
        linked = Path(version["files"][0]["path"]).parent.as_posix()  # artifacts/<application>/mv_...
        moved = self.data / "elsewhere"
        shutil.move(str(self.paths.dir / linked), str(moved))
        link(self.paths.dir / linked, moved)  # the same files, reached through a link or junction
        code, checked, _ = self.cli("validate")
        self.assertEqual(code, 1)
        self.assertIn("leads out of artifacts/ through a link or junction", "\n".join(checked["errors"]))
        code, out, err = self.cli("backup")
        self.assertEqual((code, out["manifest"]["source_valid"]), (0, False), err)
        self.assertFalse([item for item in out["manifest"]["artifacts"] if item["path"].startswith(linked + "/")])
        self.assertFalse((self.paths.dir / "backups" / out["backup"] / linked).exists())
        self.assertEqual(self.cli("validate", "--backup", out["backup"])[0], 1)

    def test_a_lock_held_before_the_backup_starts_ends_it_as_busy(self):
        self.historical()
        holder = sqlite3.connect(self.paths.db, isolation_level=None)
        self.addCleanup(holder.close)
        holder.execute("BEGIN EXCLUSIVE")
        with mock.patch.object(applications, "LOCK_TIMEOUT", 0.3):
            code, _, err = self.cli("backup")
        holder.execute("ROLLBACK")
        self.assertEqual((code, err["error"]), (1, "busy"))
        self.assertFalse((self.paths.dir / "backups").exists())

    def test_a_lock_taken_after_the_backup_opened_the_records_ends_it_as_busy_in_time(self):
        """#126 P2-4: Connection.backup retries a locked step without end; the backup gives up at LOCK_TIMEOUT."""
        self.historical()
        before = self.sha(self.paths.db)
        holder = sqlite3.connect(self.paths.db, isolation_level=None, check_same_thread=False)
        self.addCleanup(holder.close)
        release = threading.Timer(3.0, holder.execute, ("ROLLBACK",))  # without the limit, the backup waits for it
        opened = applications._reader

        def reader(paths):  # the records are open, then another program takes the lock (Codex B's timing)
            connection = opened(paths)
            if paths.dir == self.paths.dir and not holder.in_transaction:
                holder.execute("BEGIN EXCLUSIVE")
            return connection
        release.start()
        try:
            with mock.patch.object(applications, "LOCK_TIMEOUT", 0.5), \
                    mock.patch.object(applications, "_reader", reader):
                started = time.monotonic()
                code, _, err = self.cli("backup")
                waited = time.monotonic() - started
        finally:
            release.cancel()
            release.join()
        if holder.in_transaction:
            holder.execute("ROLLBACK")
        self.assertEqual(code, 1, "the backup waited until the lock was released")
        self.assertEqual(err["error"], "busy")
        self.assertTrue(0.3 <= waited < 2.0, waited)
        self.assertEqual(list((self.paths.dir / "backups").iterdir()), [])  # its .tmp folder is gone
        self.assertEqual(self.sha(self.paths.db), before)
        code, out, err = self.cli("backup")
        self.assertEqual((code, out["manifest"]["source_valid"]), (0, True), err)


if __name__ == "__main__":
    unittest.main()
