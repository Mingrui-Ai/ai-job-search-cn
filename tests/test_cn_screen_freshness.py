"""Publication-age screening uses fictional inbox data and isolated temporary stores only."""

import copy
import json
import unittest
from collections import Counter
from datetime import date
from unittest.mock import patch

from jobsearch_cn import profile, score, screen
from tests.test_cn_screen import BACKEND, EXPERIENCED, FIVE_DAYS, NOW, PROFILE, VOCABULARY, Case, item, run_cli


class Configuration(unittest.TestCase):
    def test_optional_null_and_positive_integer(self):
        self.assertEqual(profile.validate(PROFILE), [])
        for value in (None, 1, 60, 1000000):
            with self.subTest(value=value):
                data = copy.deepcopy(PROFILE)
                data["target"]["max_job_age_days"] = value
                self.assertEqual(profile.validate(data), [])

    def test_invalid_values(self):
        for value in (True, False, 0, -1, 1.5, 60.0, "60", "", [], {}):
            with self.subTest(value=value):
                data = copy.deepcopy(PROFILE)
                data["target"]["max_job_age_days"] = value
                self.assertEqual(profile.validate(data),
                                 ["target.max_job_age_days: must be null or a positive integer"])

    def test_hash_unchanged_for_every_valid_setting(self):
        digest = score.profile_hash(PROFILE)
        for value in (None, 1, 60, 365):
            data = copy.deepcopy(PROFILE)
            data["target"]["max_job_age_days"] = value
            self.assertEqual(score.profile_hash(data), digest)
        data["target"]["roles"] = ["另一个方向"]
        self.assertNotEqual(score.profile_hash(data), digest)


class Freshness(Case):
    def put_job(self, name, published=None, text=BACKEND, **metadata):
        text += f"\n样例编号：{name}"
        if published is not None:
            text += f"\n发布时间：{published}"
        return self.put(name + ".json", item(text, site_job_id=name, **metadata))

    def screen(self, as_of="2026-11-10", top=0):
        return screen.run(self.batch, "boss", self.profile, VOCABULARY, self.store, self.matches,
                          now=NOW, as_of=as_of, top=top)

    def enable(self, days=60):
        self.profile["target"]["max_job_age_days"] = days

    def snapshot(self):
        return {path: path.read_bytes() for path in self.data.rglob("*") if path.is_file()}

    def test_missing_and_null_leave_the_existing_shortlist_alone(self):
        self.put_job("old", "2020-01-01")
        self.put_job("unknown")
        self.put_job("future", "2027-01-01")
        first = self.screen()
        self.assertEqual(first["shortlist"]["total"], 3)
        self.assertEqual(first["freshness"], {"as_of": "2026-11-10", "max_job_age_days": None,
                                             "excluded": {"jobs": 0, "rows": []}})
        for row in first["shortlist"]["rows"]:
            self.assertNotIn("freshness", row)
            self.assertFalse(any("发布时间" in point for point in row["to_confirm"]))
        self.enable(None)
        snapshot = self.snapshot()
        second = self.screen()
        self.assertEqual(second["scored"], 0)
        self.assertEqual(second["shortlist"]["total"], 3)
        self.assertEqual(snapshot, self.snapshot())

    def test_today_boundary_and_one_day_over(self):
        self.enable()
        for name, published in (("today", "2026-11-10"), ("boundary", "2026-09-11"), ("old", "2026-09-10")):
            self.put_job(name, published)
        payload = self.screen()
        self.assertEqual(payload["shortlist"]["total"], 2)
        self.assertEqual(sorted(row["freshness"]["age_days"] for row in payload["shortlist"]["rows"]), [0, 60])
        excluded = payload["freshness"]["excluded"]
        self.assertEqual(excluded["jobs"], 1)
        row = excluded["rows"][0]
        self.assertEqual(row["freshness"], {"published_at": "2026-09-10", "age_days": 61, "status": "too_old"})
        self.assertIn("61 天", row["reason"])
        self.assertIn("60 天", row["line"])
        self.assertEqual(len(self.store.all()[0]), 3)
        self.assertEqual(payload["scored"], 3)
        self.assertTrue(all(job["status"] != "expired" for job in self.store.all()[0]))

    def test_unknown_and_future_are_pending_not_new(self):
        self.enable()
        self.put_job("unknown", fetched_at="2020-01-01T00:00:00+08:00")
        self.put_job("future", "2026-11-11")
        payload = self.screen()
        rows = {row["files"][0]: row for row in payload["shortlist"]["rows"]}
        self.assertEqual(payload["freshness"]["excluded"]["jobs"], 0)
        self.assertEqual(rows["unknown.json"]["freshness"],
                         {"published_at": None, "age_days": None, "status": "unknown"})
        self.assertIn("发布时间（JD 没写", rows["unknown.json"]["line"])
        self.assertEqual(rows["future.json"]["freshness"]["age_days"], -1)
        self.assertEqual(rows["future.json"]["freshness"]["status"], "future")
        self.assertIn("晚于参考日期 2026-11-10", rows["future.json"]["line"])
        self.assertTrue(any("需核实" in point for point in rows["future.json"]["to_confirm"]))

    def test_calendar_month_year_and_leap_day_boundaries(self):
        cases = (("2026-01-31", "2026-03-01", 29), ("2025-12-31", "2026-01-01", 1),
                 ("2024-02-28", "2024-03-01", 2), ("2024-02-29", "2024-03-01", 1),
                 ("2024-12-31", "2025-03-01", 60))
        for index, (published, as_of, age) in enumerate(cases):
            with self.subTest(published=published, as_of=as_of):
                self.enable(age)
                path = self.put_job(f"calendar{index}", published)
                payload = self.screen(as_of)
                row = next(row for row in payload["shortlist"]["rows"] if row["files"] == [path.name])
                self.assertEqual(row["freshness"]["age_days"], age)
                self.assertEqual(row["freshness"]["status"], "recent")

    def test_default_uses_local_day_once_not_import_timestamp(self):
        self.enable()
        self.put_job("boundary", "2026-09-11")
        with patch.object(screen, "date", wraps=date) as clock:
            clock.today.return_value = date(2026, 11, 10)
            payload = self.screen(as_of=None)
        clock.today.assert_called_once_with()
        self.assertEqual(payload["freshness"]["as_of"], "2026-11-10")
        self.assertEqual(payload["shortlist"]["rows"][0]["freshness"]["age_days"], 60)

    def test_date_and_preference_changes_recompute_without_rescoring_agent_work(self):
        self.put_job("boundary", "2026-09-11")
        first = self.screen()
        job_id = first["shortlist"]["rows"][0]["job_id"]
        record = self.matches.get(job_id)
        record["dimensions"]["experience"].update(
            score=80, reason="做过同类后端工作",
            evidence={"jd": ["参与公司核心业务系统的后端开发"], "profile": ["exp-1"]})
        record["total"] = score.total(record["dimensions"], record["weights"], record["filter"]["verdict"])
        self.matches.save(record)
        before = self.snapshot()
        for days, as_of, count in ((60, "2026-11-10", 1), (60, "2026-11-11", 0),
                                  (61, "2026-11-11", 1), (1, "2026-11-10", 0),
                                  (None, "2026-11-11", 1), (60, "2026-11-10", 1)):
            with self.subTest(days=days, as_of=as_of):
                self.enable(days)
                result = self.screen(as_of)
                self.assertEqual(result["scored"], 0)
                self.assertEqual(result["shortlist"]["total"], count)
                self.assertEqual(before, self.snapshot())
                self.assertEqual(self.matches.get(job_id), record)
                self.assertEqual(score.stale_reasons(record, self.store.get(job_id),
                                                    score.profile_hash(self.profile), score.weights_of(self.profile)), [])

    def test_hard_conflicts_preserve_reasons_counts_and_take_precedence(self):
        self.put_job("oldconflict", "2026-01-01", FIVE_DAYS)
        self.put_job("futureconflict", "2027-01-01", EXPERIENCED)
        self.put_job("unknownconflict", text=EXPERIENCED)
        self.put_job("old", "2026-01-01")
        self.put_job("new", "2026-11-10")
        baseline = self.screen()
        self.enable()
        filtered = self.screen()
        self.assertEqual(filtered["ruled_out"]["jobs"], 3)
        self.assertEqual(filtered["ruled_out"]["by_check"], baseline["ruled_out"]["by_check"])
        conflicts = {row["job_id"]: row["conflicts"] for row in baseline["ruled_out"]["rows"]}
        for row in filtered["ruled_out"]["rows"]:
            self.assertEqual(row["conflicts"], conflicts[row["job_id"]])
        counts = Counter(row["freshness"]["status"] for row in filtered["ruled_out"]["rows"])
        self.assertEqual(counts, {"too_old": 1, "future": 1, "unknown": 1})
        self.assertEqual(filtered["freshness"]["excluded"]["jobs"], 1)
        self.assertEqual(filtered["shortlist"]["total"], 1)

    def test_education_and_graduation_conflicts_still_apply(self):
        self.profile["education"] = [self.profile["education"][-1]]  # bachelor only
        self.profile["graduation"]["year"] = 2030
        text = BACKEND.replace("本科及以上在读", "硕士及以上在读")
        for name, published in (("old", "2026-01-01"), ("future", "2027-01-01"), ("unknown", None)):
            self.put_job(name, published, text)
        baseline = self.screen()
        self.enable()
        result = self.screen()
        checks = {item["check"] for item in result["ruled_out"]["by_check"]}
        self.assertTrue({"education", "graduation"}.issubset(checks), checks)
        self.assertEqual(result["ruled_out"]["by_check"], baseline["ruled_out"]["by_check"])
        self.assertEqual(result["shortlist"]["total"], 0)
        self.assertEqual(result["freshness"]["excluded"]["jobs"], 0)

    def test_sort_top_duplicate_and_status_counts_remain_consistent(self):
        old_path = self.put_job("old", "2026-01-01")
        self.put("duplicate.json", old_path.read_bytes())
        for index in range(4):
            self.put_job(f"new{index}", "2026-11-10")
        self.put_job("conflict", "2026-01-01", FIVE_DAYS)
        baseline = self.screen()
        marked = next(row["job_id"] for row in baseline["shortlist"]["rows"] if row["files"] == ["new0.json"])
        self.store.set_status(marked, "skipped")
        baseline = self.screen()
        self.enable()
        result = self.screen(top=2)
        kept = [row["job_id"] for row in baseline["shortlist"]["rows"]
                if self.store.get(row["job_id"])["published_at"] == "2026-11-10"]
        self.assertEqual([row["job_id"] for row in result["shortlist"]["rows"]], kept[:2])
        self.assertEqual([row["rank"] for row in result["shortlist"]["rows"]], [1, 2])
        self.assertEqual(result["shortlist"]["total"], len(kept))
        self.assertEqual(result["not_listed"]["skipped"], 1)
        self.assertEqual(result["freshness"]["excluded"]["jobs"], 1)
        self.assertEqual(sorted(result["freshness"]["excluded"]["rows"][0]["files"]),
                         ["duplicate.json", "old.json"])
        total = (result["shortlist"]["total"] + result["ruled_out"]["jobs"]
                 + result["freshness"]["excluded"]["jobs"] + sum(result["not_listed"].values()))
        self.assertEqual(total, 6)
        all_rows = result["ruled_out"]["rows"] + result["freshness"]["excluded"]["rows"]
        self.assertNotIn(marked, [row["job_id"] for row in all_rows])
        self.assertEqual(result["imported"]["unchanged"], 6)

    def test_invalid_api_input_writes_nothing(self):
        self.put_job("new", "2026-11-10")
        before = self.snapshot()
        for value in ("2026-02-29", "2026-11-31", "20261110", "2026-W46-2", "2026-11-10T00:00:00", ""):
            with self.subTest(value=value), self.assertRaises(screen.BatchError):
                self.screen(value)
        self.enable(True)
        with self.assertRaises(screen.BatchError):
            self.screen()
        self.assertEqual(before, self.snapshot())


    def write_profile(self):
        directory = self.data / "profile"
        directory.mkdir(exist_ok=True)
        (directory / "profile.json").write_text(json.dumps(self.profile, ensure_ascii=False), encoding="utf-8")

    def cli(self, *args, expect=0):
        proc = run_cli("jd", "screen", str(self.batch), *args, data_dir=self.data)
        self.assertEqual(proc.returncode, expect, proc.stdout.decode("utf-8") + proc.stderr.decode("utf-8"))
        return json.loads(proc.stderr if expect else proc.stdout)

    def test_cli_json_freshness_and_rerun(self):
        self.put_job("boundary", "2026-09-11")
        self.enable()
        self.write_profile()
        first = self.cli("--as-of", "2026-11-10")
        self.assertEqual(first["freshness"]["as_of"], "2026-11-10")
        self.assertEqual(first["freshness"]["max_job_age_days"], 60)
        self.assertEqual(first["shortlist"]["total"], 1)
        before = self.snapshot()
        second = self.cli("--as-of", "2026-11-11")
        self.assertEqual(second["scored"], 0)
        self.assertEqual(second["shortlist"]["total"], 0)
        self.assertEqual(second["freshness"]["excluded"]["jobs"], 1)
        self.assertEqual(before, self.snapshot())
        self.assertNotIn("13800000000", json.dumps(second))
        self.assertNotIn("liming@example.com", json.dumps(second))

    def test_cli_default_reference_day_is_explicit(self):
        self.put_job("unknown")
        self.write_profile()
        before = date.today().isoformat()
        result = self.cli()
        self.assertIn(result["freshness"]["as_of"], (before, date.today().isoformat()))
        self.assertIsNone(result["freshness"]["max_job_age_days"])

    def test_cli_invalid_dates_are_json_errors_before_writes(self):
        self.put_job("new", "2026-11-10")
        self.write_profile()
        before = self.snapshot()
        for value in ("2026-02-29", "2026-13-01", "2026-11-00", "0000-01-01", "20261110", "2026-W46-2",
                      "2026-1-1", "2026-11-10T00:00:00+08:00", "2026-11-10\n", ""):
            with self.subTest(value=value):
                self.assertIn("--as-of", self.cli("--as-of", value, expect=2)["error"])
        self.assertEqual(before, self.snapshot())

    def test_cli_invalid_preferences_are_json_errors_before_writes(self):
        self.put_job("new", "2026-11-10")
        for value in (True, False, 0, -1, 1.5, 60.0, "60", [], {}):
            with self.subTest(value=value):
                self.enable(value)
                self.write_profile()
                before = self.snapshot()
                error = self.cli("--as-of", "2026-11-10", expect=1)
                self.assertIn("target.max_job_age_days", error["errors"][0])
                self.assertEqual(before, self.snapshot())
                self.assertFalse((self.data / "jobs").exists())
                self.assertFalse((self.data / "matches").exists())

    def test_check_still_needs_no_profile_and_validates_explicit_date(self):
        self.put_job("new", "2026-11-10")
        before = self.snapshot()
        result = self.cli("--check", "--as-of", "2024-02-29")
        self.assertEqual(result["jobs"], 1)
        self.assertNotIn("freshness", result)
        self.cli("--check", "--as-of", "2026-02-29", expect=2)
        self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
