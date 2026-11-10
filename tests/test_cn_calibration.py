"""Fictional application histories: facts, archive integrity, old scores and read consistency."""
from copy import deepcopy
import hashlib
import json
import math
from unittest import mock

from jobsearch_cn import applications, calibration, score
from tests import test_cn_applications as fixtures


class Retrospective(fixtures.Data):
    def setUp(self):
        super().setUp()
        self.job_record = json.loads((self.data / "jobs" / (self.job + ".json")).read_text(encoding="utf-8"))
        self.old_score = {
            "schema_version": 1, "job_id": self.job, "rules_version": 2,
            "scored_at": "2026-10-19T10:00:00+08:00", "job_hash": score.job_hash(self.job_record),
            "profile_hash": "a" * 64, "weights": {"skills": 30, "direction": 25, "experience": 25, "salary": 20},
            "dimensions": {key: {"score": value, "method": "rule", "reason": "private history text"}
                           for key, value in (("skills", 80), ("direction", 60), ("experience", 40), ("salary", None))},
            # Deliberately unlike today's weighted arithmetic: preserve, do not recompute old results.
            "total": {"score": 87, "grade": "strong", "complete": False, "missing": ["salary"]},
        }
        self.match = self.data / "matches" / (self.job + ".json")
        self.match.parent.mkdir()
        self.match.write_text(json.dumps(self.old_score), encoding="utf-8")

    def submitted(self, *time):
        return self.write("record", self.job, "--channel", "portal", "--submitted",
                          *(time or ("--on", "2026-10-20")))["application"]["application_id"]

    def retro(self, *ids):
        code, out, err = self.cli("retrospective", *ids)
        self.assertEqual(code, 0, err)
        return out

    def one(self, identity):
        return self.retro(identity)["rows"][0]

    def refused(self, identity=None, code=1, error=None):
        status, out, err = self.cli("retrospective", *((identity,) if identity else ()))
        self.assertEqual(status, code, (out, err))
        self.assertIsNone(out)
        if error:
            self.assertEqual(err["error"], error)
        self.assertNotIn(str(self.data), json.dumps(err))
        return err

    def archive(self, identity, kind="match"):
        return self.paths.dir / self.show(identity)["context_snapshot"][kind]["path"]

    def change_archive(self, identity, value, kind="match"):
        path = self.archive(identity, kind)
        body = value if isinstance(value, bytes) else json.dumps(value).encode("utf-8")
        path.write_bytes(body)
        with self.connect() as connection:
            connection.execute("UPDATE snapshots SET sha256=? WHERE application_id=? AND kind=?",
                               (hashlib.sha256(body).hexdigest(), identity, kind))

    def fingerprints(self):
        return {path.relative_to(self.data).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.data.rglob("*") if path.is_file()}

    def test_empty_missing_and_invalid_ids_have_no_creation(self):
        absent = self.data / "new-root"
        code, out, err = fixtures.run("application", "retrospective", "--data-dir", absent)
        self.assertEqual(code, 0, err)
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["summary"]["application_count"], 0)
        for identity, expected in (("app_" + "0" * 32, "not_found"), ("private@example.com", "invalid")):
            code, out, err = fixtures.run("application", "retrospective", identity, "--data-dir", absent)
            self.assertEqual((code, out, err["error"]), (1, None, expected))
            self.assertNotIn("private@example.com", json.dumps(err))
        self.assertFalse(absent.exists())

    def test_ids_are_deduplicated_sorted_and_missing_selection_fails(self):
        first, second = self.submitted(), self.historical()
        out = self.retro(second, first, second)
        self.assertEqual(out["scope"]["application_ids"], sorted([first, second]))
        self.assertEqual(out["summary"]["application_count"], 2)
        self.refused("app_" + "0" * 32, error="not_found")

    def test_waiting_and_unsubmitted_withdrawn_are_not_failures(self):
        waiting, drafted = self.submitted(), self.drafted()
        self.move(drafted, "withdrawn")
        out = self.retro()
        self.assertEqual(out["summary"]["submitted_application_count"], 1)
        self.assertEqual(out["summary"]["current_status_counts"]["applied"], 1)
        self.assertEqual(out["summary"]["current_status_counts"]["withdrawn"], 1)
        self.assertFalse(self.one(drafted)["submission"]["confirmed"])
        self.assertFalse(self.one(waiting)["reply_recorded"]["recorded"])
        self.assertNotIn("success_rate", json.dumps(out))

    def test_milestones_overlap_and_do_not_invent_skipped_stages(self):
        interviewed, offered, hired = self.submitted(), self.submitted(), self.submitted()
        self.move(interviewed, "interview")
        self.move(interviewed, "rejected")
        self.move(offered, "offer")
        self.move(offered, "offer_declined")
        self.move(hired, "offer")
        self.move(hired, "hired")
        out = self.retro()
        self.assertEqual(out["summary"]["milestone_counts"],
                         {"interview_recorded": 1, "offer_recorded": 2, "hired_recorded": 1})
        self.assertEqual(out["summary"]["application_count"], 3)
        self.assertEqual(out["summary"]["distinct_job_count"], 1)
        self.assertEqual(out["summary"]["duplicate_jobs"][0]["application_count"], 3)
        self.assertFalse(self.one(offered)["milestones"]["interview_recorded"]["recorded"])

    def test_voided_reply_and_status_do_not_count_and_text_is_omitted(self):
        identity = self.submitted()
        self.write("reply", identity, "--expected-revision", 2, "--summary", "private@example.com")
        self.write("void", identity, "--expected-revision", 3, "--reason", "mistaken private note")
        self.move(identity, "interview", "--reason", "private interview reason")
        self.write("void", identity, "--expected-revision", 5, "--reason", "mistaken")
        out = self.retro()
        row = out["rows"][0]
        self.assertFalse(row["reply_recorded"]["recorded"])
        self.assertFalse(row["milestones"]["interview_recorded"]["recorded"])
        self.assertEqual(row["status"], "applied")
        text = json.dumps(out)
        for private in ("private@example.com", "private interview reason", "private history text"):
            self.assertNotIn(private, text)
        self.assertTrue(any(e["voided_by"] for e in row["events"]))

    def test_old_values_and_missing_dimension_are_preserved_without_rescoring(self):
        identity = self.submitted()
        with mock.patch.object(score, "validate", side_effect=AssertionError("current validation forbidden")), \
                mock.patch.object(score, "score_job", side_effect=AssertionError("rescoring forbidden")), \
                mock.patch.object(score, "total", side_effect=AssertionError("recalculation forbidden")):
            row = self.one(identity)
        historical = row["historical_score"]
        self.assertEqual(historical["rules_version"], 2)
        self.assertEqual(historical["total"]["score"], 87)
        self.assertEqual(historical["total"]["missing"], ["salary"])
        self.assertIsNone(historical["dimensions"]["location"])
        self.assertEqual(historical["absent_dimensions"], ["location"])
        self.assertTrue(row["descriptive_comparison"]["eligible"])
        self.assertEqual(row["quality"]["historical_profile_check"], "unavailable")

    def test_historical_and_registered_null_snapshots_keep_facts(self):
        historical = self.historical()
        self.match.unlink()
        identity = self.submitted()
        for item in (historical, identity):
            row = self.one(item)
            self.assertTrue(row["submission"]["confirmed"])
            self.assertIsNone(row["historical_score"])
            self.assertFalse(row["descriptive_comparison"]["eligible"])
        self.assertEqual(self.one(historical)["quality"]["snapshot_origin"], "historical_without_snapshot")
        self.assertIsNone(self.one(identity)["snapshots"]["match"])

    def test_void_and_resubmit_keeps_first_archive_as_background(self):
        identity = self.submitted()
        first = self.one(identity)["submission"]["event_id"]
        self.write("void", identity, "--expected-revision", 2, "--reason", "wrong date")
        self.assertFalse(self.one(identity)["submission"]["confirmed"])
        self.write("submit", identity, "--expected-revision", 3, "--on", "2026-10-21")
        row = self.one(identity)
        self.assertEqual(row["submission"]["first_registered_event_id"], first)
        self.assertNotEqual(row["submission"]["event_id"], first)
        self.assertEqual(row["quality"]["submission_binding"], "first_submission_reused")
        self.assertFalse(row["descriptive_comparison"]["eligible"])

    def test_timing_exact_dates_timezones_and_unknown(self):
        cases = [("2026-10-20T08:00:00+08:00", ("--at", "2026-10-20T01:00:00Z"), "before"),
                 ("2026-10-20T02:00:00Z", ("--at", "2026-10-20T09:00:00+08:00"), "after"),
                 ("2026-10-20T01:00:00Z", ("--at", "2026-10-20T09:00:00+08:00"), "at_submission"),
                 ("2026-10-19T17:00:00Z", ("--on", "2026-10-20"), "same_day_order_unknown"),
                 ("2026-10-18T23:00:00-07:00", ("--on", "2026-10-20"), "before"),
                 ("2026-10-20T18:00:00Z", ("--on", "2026-10-20"), "after")]
        for scored_at, timing, expected in cases:
            with self.subTest(expected=expected):
                identity = self.submitted(*timing)
                value = deepcopy(self.old_score); value["scored_at"] = scored_at
                self.change_archive(identity, value)
                row = self.one(identity)
                self.assertEqual(row["quality"]["score_timing"], expected)
                self.assertEqual(row["descriptive_comparison"]["eligible"], expected in ("before", "at_submission"))
        unknown = self.write("record", self.job, "--channel", "portal", "--submitted")["application"]["application_id"]
        self.assertEqual(self.one(unknown)["quality"]["score_timing"], "unknown")

    def test_old_job_digest_mismatch_is_not_byte_corruption(self):
        identity = self.submitted()
        value = deepcopy(self.old_score); value["job_hash"] = "0" * 64
        self.change_archive(identity, value)
        row = self.one(identity)
        self.assertEqual(row["quality"]["archive_integrity"], "verified")
        self.assertEqual(row["quality"]["job_binding"], "not_verified")
        self.assertEqual(row["historical_score"]["total"]["score"], 87)
        self.assertFalse(row["descriptive_comparison"]["eligible"])

    def test_comparison_groups_keep_rules_profile_weights_and_scored_dimensions_apart(self):
        identities = [self.submitted() for _ in range(5)]
        for index, identity in enumerate(identities[1:], 1):
            value = deepcopy(self.old_score)
            if index == 1: value["rules_version"] = 3
            if index == 2: value["profile_hash"] = "b" * 64
            if index == 3: value["weights"]["skills"] = 40
            if index == 4: value["dimensions"]["salary"]["score"] = 50
            self.change_archive(identity, value)
        out = self.retro()
        self.assertEqual(len(out["summary"]["basis_groups"]), 5)
        self.assertEqual(out["summary"]["comparison_count"], 5)
        self.assertEqual({r["basis_group_id"] for r in out["rows"]},
                         {g["basis_group_id"] for g in out["summary"]["basis_groups"]})

    def test_current_files_and_unrelated_materials_are_never_read(self):
        identity = self.submitted()
        archive = self.archive(identity)
        for path in (self.match, self.material, self.pdf, self.data / "jobs" / (self.job + ".json")):
            path.unlink()
        before = self.fingerprints()
        from pathlib import Path
        original = Path.read_bytes
        def guarded(path):
            self.assertNotIn("profile", path.parts)
            self.assertTrue(path == self.archive(identity, "job") or path == archive)
            return original(path)
        with mock.patch.object(Path, "read_bytes", guarded):
            self.assertEqual(self.one(identity)["historical_score"]["total"]["score"], 87)
        self.assertEqual(before, self.fingerprints())

    def test_registered_missing_or_changed_file_is_error_not_missing_score(self):
        for kind in ("job", "match"):
            identity = self.submitted()
            self.archive(identity, kind).unlink()
            self.refused(identity, error="archive_integrity")
        identity = self.submitted()
        self.archive(identity).write_bytes(b'{"changed":true}')
        self.refused(identity, error="archive_integrity")

    def test_unsafe_or_cross_application_context_path_is_refused(self):
        first, second = self.submitted(), self.submitted()
        cross = self.show(second)["context_snapshot"]["match"]["path"]
        for path in (cross, "../private.json", "C:/private.json", "artifacts/x/y/file:stream", "/private.json"):
            with self.subTest(path=path), self.connect() as connection:
                connection.execute("UPDATE snapshots SET path=? WHERE application_id=? AND kind='match'", (path, first))
            self.refused(first, error="archive_integrity")

    def test_internal_junction_cannot_borrow_context(self):
        import os
        import shutil
        import sys
        first, second = self.submitted(), self.submitted()
        first_path, second_path = self.archive(first), self.archive(second)
        shutil.rmtree(first_path.parent)
        try:
            first_path.parent.symlink_to(second_path.parent, target_is_directory=True)
        except OSError:
            if sys.platform != "win32": self.skipTest("symlinks unavailable")
            import _winapi
            _winapi.CreateJunction(str(second_path.parent), str(first_path.parent))
        self.addCleanup(lambda: first_path.parent.unlink() if first_path.parent.is_symlink()
                        else os.rmdir(first_path.parent))
        self.refused(first, error="archive_integrity")

    def test_leaf_symlink_cannot_borrow_context(self):
        first, second = self.submitted(), self.submitted()
        path = self.archive(first)
        path.unlink()
        try:
            path.symlink_to(self.archive(second))
        except OSError:
            self.skipTest("file symlink creation unavailable")
        self.refused(first, error="archive_integrity")

    def test_job_id_in_either_archive_must_match_application(self):
        for kind, key in (("job", "id"), ("match", "job_id")):
            identity = self.submitted()
            value = deepcopy(self.job_record if kind == "job" else self.old_score)
            value[key] = "job_000000000099"
            self.change_archive(identity, value, kind)
            self.refused(identity, error="job_binding")

    def test_unsupported_match_content_keeps_facts_excludes_numeric_values(self):
        variants = [b'{broken', b'{"schema_version":1,"schema_version":1}', b'{"score":NaN}', b'{"score":1e999}',
                    b'{"private":"\\ud800"}']
        for key, bad in (("schema_version", 2), ("rules_version", True), ("profile_hash", "contact@example.com")):
            value = deepcopy(self.old_score); value[key] = bad; variants.append(value)
        for bad in (True, -1, 101, math.inf):
            value = deepcopy(self.old_score); value["dimensions"]["skills"]["score"] = bad; variants.append(value)
        for bad in (True, -1, math.inf):
            value = deepcopy(self.old_score); value["weights"]["skills"] = bad; variants.append(value)
        for bad in (True, -1, 101):
            value = deepcopy(self.old_score); value["total"]["score"] = bad; variants.append(value)
        for index, value in enumerate(variants):
            with self.subTest(index=index):
                identity = self.submitted(); self.change_archive(identity, value)
                out = self.retro(identity); row = out["rows"][0]
                self.assertTrue(row["submission"]["confirmed"])
                self.assertIsNone(row["historical_score"])
                self.assertEqual(row["quality"]["readability"]["match"], "unsupported")
                self.assertEqual(out["summary"]["historical_score_count"], 0)
                self.assertTrue(out["warnings"])

    def test_unsupported_job_keeps_facts_and_score_but_not_comparison(self):
        identity = self.submitted(); self.change_archive(identity, b'[]', "job")
        row = self.one(identity)
        self.assertIsNone(row["title"])
        self.assertIsNotNone(row["historical_score"])
        self.assertFalse(row["descriptive_comparison"]["eligible"])

    def test_unrepresentable_timezone_conversion_keeps_the_whole_batch(self):
        import subprocess
        import sys
        from pathlib import Path
        ordinary = self.submitted()
        affected = []
        # The first overflows UTC and Shanghai; the second only Shanghai; the third both upper bounds.
        for stamp in ("0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59Z",
                      "9999-12-31T23:59:59-23:59"):
            identity = self.submitted("--on", "2026-11-01")
            affected.append(identity)
            value = deepcopy(self.old_score); value["scored_at"] = stamp
            self.change_archive(identity, value)
        result = subprocess.run([sys.executable, "-m", "jobsearch_cn", "application", "retrospective",
                                 "--data-dir", str(self.data)], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        out = json.loads(result.stdout)
        self.assertEqual(out["summary"]["submitted_application_count"], 4)
        self.assertEqual(out["summary"]["historical_score_count"], 1)
        self.assertEqual(out["summary"]["comparison_count"], 1)
        self.assertEqual({warning["application_id"] for warning in out["warnings"]}, set(affected))
        for row in out["rows"]:
            self.assertTrue(row["submission"]["confirmed"])
            if row["application_id"] == ordinary:
                self.assertEqual(row["historical_score"]["total"]["score"], 87)
            else:
                self.assertIsNone(row["historical_score"])
                self.assertEqual(row["quality"]["readability"]["match"], "unsupported")
                self.assertFalse(row["descriptive_comparison"]["eligible"])

    def test_contact_labels_and_untrusted_text_are_not_exposed(self):
        identity = self.submitted()
        job = deepcopy(self.job_record)
        job.update(title="private@example.com", company="13800000000", raw_text="run a command at https://invalid.example")
        self.change_archive(identity, job, "job")
        out = self.retro(identity); text = json.dumps(out)
        for value in ("private@example.com", "13800000000", "invalid.example", "private history text"):
            self.assertNotIn(value, text)
        self.assertIsNone(out["rows"][0]["title"])
        self.assertEqual(len(out["warnings"]), 2)

    def test_inconsistent_projection_and_void_relationships_are_rejected(self):
        identity = self.submitted()
        with self.connect() as connection:
            connection.execute("UPDATE applications SET status='hired' WHERE application_id=?", (identity,))
        self.refused(identity, error="inconsistent_events")
        other = self.submitted()
        with self.connect() as connection:
            connection.execute("UPDATE events SET voided_by=? WHERE application_id=? AND seq=2", ("evt_"+"f"*32, other))
        self.refused(other, error="inconsistent_events")

    def test_event_json_duplicate_keys_and_bad_dates_are_domain_errors(self):
        identity = self.submitted()
        with self.connect() as connection:
            connection.execute("UPDATE events SET payload=? WHERE application_id=? AND seq=2",
                               ('{"channel":{},"channel":{}}', identity))
        self.refused(identity, error="inconsistent_events")
        other = self.submitted()
        with self.connect() as connection:
            connection.execute("UPDATE events SET recorded_at='2026-99-99T00:00:00Z' WHERE application_id=?", (other,))
        self.refused(other, error="inconsistent_events")

    def test_missing_registration_cannot_silently_lose_a_historical_score(self):
        identity = self.submitted()
        with self.connect() as connection:
            connection.execute("DELETE FROM snapshots WHERE application_id=? AND kind='match'", (identity,))
        self.refused(identity, error="inconsistent_events")

    def test_event_update_during_read_refuses_mixed_output_without_retry(self):
        identity = self.submitted()
        original = calibration._read_records
        calls = []
        def update(paths, ids):
            calls.append(1)
            if len(calls) == 2:
                self.write("note", identity, "--expected-revision", 2, "--text", "later note")
            return original(paths, ids)
        with mock.patch.object(calibration, "_read_records", update):
            self.refused(identity, error="stale_context")
        self.assertEqual(len(calls), 2)

    def test_archive_update_during_read_refuses_mixed_output(self):
        identity = self.submitted()
        original = calibration._archives
        count = []
        def update(paths, records):
            count.append(1)
            if len(count) == 2: self.archive(identity).write_bytes(b'changed')
            return original(paths, records)
        with mock.patch.object(calibration, "_archives", update):
            self.refused(identity, error="archive_integrity")
        self.assertEqual(len(count), 2)

    def test_evidence_hash_stable_but_all_event_payload_changes_bind(self):
        identity = self.submitted()
        before = self.fingerprints()
        with mock.patch.object(applications, "now_utc", return_value="2026-11-01T00:00:00Z"):
            first = self.retro(identity)
        with mock.patch.object(applications, "now_utc", return_value="2026-11-02T00:00:00Z"):
            second = self.retro(identity)
        self.assertNotEqual(first.pop("generated_at"), second.pop("generated_at"))
        self.assertEqual(first, second)
        self.assertEqual(before, self.fingerprints())
        self.write("note", identity, "--expected-revision", 2, "--text", "first note")
        third = self.retro(identity)
        with self.connect() as connection:
            connection.execute("UPDATE events SET payload=? WHERE application_id=? AND type='note_added'",
                               ('{"text":"different private note"}', identity))
        fourth = self.retro(identity)
        self.assertEqual(third["rows"], fourth["rows"])
        self.assertNotEqual(third["evidence_hash"], fourth["evidence_hash"])

    def test_io_and_database_version_errors_exit_two_without_private_paths(self):
        identity = self.submitted()
        with mock.patch.object(calibration, "_archive_bytes", side_effect=PermissionError("private path")):
            err = self.refused(identity, code=2)
            self.assertNotIn("private path", json.dumps(err))
        with self.connect() as connection:
            connection.execute("PRAGMA user_version=999")
        self.refused(identity, code=2)

    def test_no_write_weight_or_as_of_switches_exist(self):
        import contextlib
        import io
        from jobsearch_cn import cli
        parser = cli.build_parser()
        for switch in ("--save", "--out", "--weights", "--profile", "--as-of"):
            with self.subTest(switch=switch), self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(io.StringIO()):
                parser.parse_args(["application", "retrospective", switch, "x"])
            self.assertEqual(raised.exception.code, 2)

    def test_selected_scope_ignores_unrelated_corrupt_application(self):
        selected, unrelated = self.submitted(), self.submitted()
        with self.connect() as connection:
            connection.execute("UPDATE applications SET status='hired' WHERE application_id=?", (unrelated,))
        self.assertEqual(self.retro(selected)["scope"]["application_ids"], [selected])
        self.refused(error="inconsistent_events")

    def test_real_cli_emits_one_json_object_without_writes(self):
        import subprocess
        import sys
        from pathlib import Path
        identity = self.submitted()
        before = self.fingerprints()
        result = subprocess.run([sys.executable, "-m", "jobsearch_cn", "application", "retrospective", identity,
                                 "--data-dir", str(self.data)], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(json.loads(result.stdout)["scope"]["application_ids"], [identity])
        self.assertEqual(result.stderr, b"")
        self.assertEqual(before, self.fingerprints())
