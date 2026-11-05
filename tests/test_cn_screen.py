"""jd screen (M6-4, docs/cn/screen.md): inbox batches, dedup by the job board's id, what gets scored, the shortlist.

All data is made up: the JD texts are the public samples under tests/fixtures/cn/jd/, the links and job
board ids are invented, and tests/fixtures/cn/inbox/ is the sample batch screen.md shows the collector.
Expected scores come from score.score_job itself, so a rule change elsewhere does not touch these tests.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jobsearch_cn import jd_parser, match, schema, score, screen, store, vocab

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "cn"
SAMPLE = FIXTURES / "inbox" / "boss" / "20261105-103000"
NOW = datetime(2026, 11, 5, 10, 40, tzinfo=timezone(timedelta(hours=8)))
LATER = "2026-11-06T09:00:00+08:00"
VOCABULARY = vocab.load()
PROFILE = json.loads((FIXTURES / "profile" / "tech" / "profile.json").read_text(encoding="utf-8"))


def sample_text(name: str) -> str:
    return json.loads((SAMPLE / f"{name}.json").read_text(encoding="utf-8"))["text"]


DATA, BACKEND, OPS = sample_text("bx0001"), sample_text("bx0002"), sample_text("bx0003")
FIVE_DAYS = (FIXTURES / "jd" / "shixiseng_intern.txt").read_text(encoding="utf-8")  # 5 days a week: ruled out
EXPERIENCED = (FIXTURES / "jd" / "experienced_hire.txt").read_text(encoding="utf-8")  # 社招 in 上海: ruled out


def item(text: str, **fields) -> dict:
    data = {"format": screen.FORMAT, "fetched_at": "2026-11-05T10:31:20+08:00", "text": text}
    data.update(fields)
    return data


class Case(unittest.TestCase):
    """A data directory with the tech sample profile and an empty batch folder inbox/boss/20261105-103000/."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name) / "data"
        self.batch = self.data / "inbox" / "boss" / "20261105-103000"
        self.batch.mkdir(parents=True)
        self.store, self.matches = store.Store(self.data), store.MatchStore(self.data)
        self.profile = json.loads(json.dumps(PROFILE))

    def put(self, name: str, content) -> Path:
        path = self.batch / name
        if isinstance(content, bytes):
            path.write_bytes(content)
        elif isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        return path

    def run_batch(self, top=0, profile=None):
        return screen.run(self.batch, "boss", profile or self.profile, VOCABULARY, self.store, self.matches,
                          top=top, now=NOW)

    def five_jobs(self):
        self.put("a1.json", item(DATA, site_job_id="a1", url="https://www.zhipin.com/job_detail/a1.html"))
        self.put("b2.json", item(BACKEND, site_job_id="b2", url="https://www.zhipin.com/job_detail/b2.html"))
        self.put("c3.json", item(OPS, site_job_id="c3"))
        self.put("d4.json", item(FIVE_DAYS, site_job_id="d4"))
        self.put("e5.json", item(EXPERIENCED, site_job_id="e5"))


class ItemFormat(unittest.TestCase):
    def read(self, data, site="boss"):
        return screen.read_item(json.dumps(data, ensure_ascii=False).encode("utf-8"), site)

    def problem(self, data, site="boss") -> str:
        with self.assertRaises(screen.ItemError) as caught:
            self.read(data, site)
        return str(caught.exception)

    def test_the_sample_batch_is_in_the_format(self):
        names = sorted(path.name for path in SAMPLE.iterdir())
        self.assertEqual(names, ["bx0001.json", "bx0002.json", "bx0003.json"])
        for path in SAMPLE.iterdir():
            self.assertEqual(screen.read_item(path.read_bytes(), "boss")["format"], screen.FORMAT)

    def test_required_fields(self):
        for key in screen.REQUIRED:
            data = item(DATA)
            del data[key]
            self.assertIn(f"{key}: missing", self.problem(data))
            self.assertIn(f"{key}: missing", self.problem(dict(item(DATA), **{key: None})))

    def test_unknown_fields_are_errors_but_extra_holds_anything(self):
        self.assertIn("fetchedAt: unknown field", self.problem(item(DATA, fetchedAt=LATER)))
        self.read(item(DATA, extra={"query": "数据分析", "page": 2, "card": {"salary": "150-200元/天"}}))
        self.assertIn("extra: must be a JSON object", self.problem(item(DATA, extra=["x"])))

    def test_every_problem_is_named_at_once(self):
        data = item(DATA, title="数据分析实习生", url="ftp://example.com/1")
        del data["fetched_at"]
        message = self.problem(data)
        for expected in ("title: unknown field", "fetched_at: missing", "url: must be null or an http(s) URL"):
            self.assertIn(expected, message)

    def test_format_text_and_site(self):
        self.assertIn("format: must be", self.problem(item(DATA, format="jobsearch_cn.inbox/2")))
        self.assertIn("text: must be a non-empty string", self.problem(item(" \n ")))
        self.assertIn("text: must be a non-empty string", self.problem(item(5)))
        self.assertIn("is not the batch's site", self.problem(item(DATA, site="shixiseng")))
        self.read(item(DATA, site="boss"))

    def test_site_job_id(self):
        self.read(item(DATA, site_job_id="a1B2-c3_d4.e5~"))
        for bad in ("a/b", "a b", "", "x" * 129, 12):
            self.assertIn("site_job_id: must be null or 1-128", self.problem(item(DATA, site_job_id=bad)))
        self.assertIn("only for a job board", self.problem(item(DATA, site_job_id="7"), site="official"))

    def test_fetched_at_needs_a_utc_offset(self):
        self.assertIn("fetched_at: must be an ISO 8601", self.problem(item(DATA, fetched_at="2026-11-05T10:31:20")))
        self.read(item(DATA, fetched_at="2026-11-05T02:31:20Z"))

    def test_a_url_whose_port_cannot_be_read(self):
        for bad in ("https://example.invalid:abc/1", "https://example.invalid:99999/1", "http://[::1/1"):
            self.assertIn("url: not a readable URL", self.problem(item(DATA, url=bad)))
        self.read(item(DATA, url="https://example.invalid:8443/1"))
        self.assertIsNone(store.normalize_url("https://example.invalid:abc/1"))

    def test_not_json_not_utf8_not_one_object(self):
        for data, expected in ((b"{", "not valid JSON"), ("文本".encode("gbk"), "not UTF-8"),
                               (b"[]", "one JSON object")):
            with self.subTest(data=data), self.assertRaises(screen.ItemError) as caught:
                screen.read_item(data, "boss")
            self.assertIn(expected, str(caught.exception))
        screen.read_item(b"\xef\xbb\xbf" + json.dumps(item(DATA)).encode("utf-8"), "boss")  # Notepad's BOM


class Reading(Case):
    def test_which_files_are_read(self):
        for name in ("b.TXT", "a.json", "notes.md", ".c.json.tmp", "~lock.json"):
            self.put(name, item(DATA) if name.endswith("json") else DATA)
        (self.batch / "sub").mkdir()
        self.put("big.json", b" " * (screen.MAX_FILE_BYTES + 1))
        files, ignored = screen.list_files(self.batch)
        self.assertEqual([path.name for path in files], ["a.json", "b.TXT"])
        self.assertEqual([entry["file"] for entry in ignored], ["big.json", "notes.md", "sub/"])

    def test_a_link_is_not_followed(self):
        target = self.batch.parent / "elsewhere.json"
        target.write_text(json.dumps(item(DATA)), encoding="utf-8")
        try:
            os.symlink(target, self.batch / "linked.json")
        except (OSError, NotImplementedError):
            self.skipTest("cannot create a symlink here")
        files, ignored = screen.list_files(self.batch)
        self.assertEqual(files, [])
        self.assertEqual(ignored[0]["file"], "linked.json")

    def test_json_text_is_one_posting_even_with_a_line_of_equals(self):
        path = self.put("x.json", item(BACKEND + "\n=====\n长期实习优先", site_job_id="x"))
        records, _ = screen.read_file(path, "boss", VOCABULARY, NOW)
        self.assertEqual(len(records), 1)
        self.assertIn("=====", records[0]["raw_text"])
        self.assertEqual(len(jd_parser.parse_text(BACKEND + "\n=====\n长期实习优先", now=NOW)[0]), 2)

    def test_source_fields(self):
        path = self.put("x.json", item(DATA, site_job_id="x9", url="https://www.zhipin.com/job_detail/x9.html"))
        [record], _ = screen.read_file(path, "boss", VOCABULARY, NOW)
        self.assertEqual(record["source"], {"type": "portal", "site": "boss",
                                            "url": "https://www.zhipin.com/job_detail/x9.html",
                                            "imported_at": "2026-11-05T10:40:00+08:00", "site_job_id": "x9",
                                            "fetched_at": "2026-11-05T10:31:20+08:00"})
        path = self.put("y.txt", DATA + "\n===\n" + OPS)
        records, _ = screen.read_file(path, "boss", VOCABULARY, NOW)
        self.assertEqual([r["source"]["type"] for r in records], ["file", "file"])
        self.assertEqual({(r["source"]["site_job_id"], r["source"]["fetched_at"]) for r in records}, {(None, None)})

    def test_txt_encodings(self):
        path = self.put("gbk.txt", DATA.encode("gbk"))
        records, warnings = screen.read_file(path, "boss", VOCABULARY, NOW)
        self.assertEqual(records[0]["title"], "数据分析实习生")
        self.assertEqual(warnings[0]["kind"], "encoding")
        path = self.put("ps.txt", b"???? ???? ????")
        with self.assertRaises(screen.ItemError):
            screen.read_file(path, "boss", VOCABULARY, NOW)

    def test_a_txt_of_several_jds_labels_each(self):
        self.put("manual.txt", DATA + "\n===\n" + OPS)
        payload = self.run_batch()
        rows = payload["shortlist"]["rows"] + payload["ruled_out"]["rows"]
        self.assertEqual(sorted(file for row in rows for file in row["files"]), ["manual.txt#1", "manual.txt#2"])

    def test_check_stores_nothing_and_finds_duplicates(self):
        self.put("a.json", item(DATA, site_job_id="a1"))
        self.put("b.json", item(DATA + "\n补充：可提前转正", site_job_id="a1"))
        self.put("c.json", item(OPS, fetchedAt=LATER))
        payload = screen.check(self.batch, "boss", VOCABULARY, NOW)
        self.assertEqual((payload["ok"], payload["failed"], payload["jobs"]), (2, 1, 2))
        self.assertEqual(payload["duplicates"], [["a.json", "b.json"]])
        self.assertEqual(payload["files"][0]["jobs"][0]["unread"], [])
        self.assertEqual(sorted(path.name for path in self.data.iterdir()), ["inbox"])

    def test_a_bad_url_skips_only_its_file(self):
        self.put("a.json", item(DATA, site_job_id="a1", url="https://example.invalid:abc/1"))
        self.put("b.json", item(BACKEND, site_job_id="b2", url="https://example.invalid/2"))
        payload = screen.check(self.batch, "boss", VOCABULARY, NOW)
        self.assertEqual((payload["ok"], payload["failed"], payload["jobs"]), (1, 1, 1))
        self.assertIn("url: not a readable URL", payload["files"][0]["reason"])
        payload = self.run_batch()
        self.assertEqual(payload["imported"], {"created": 1, "updated": 0, "unchanged": 0, "skipped": 1})
        self.assertEqual(payload["skipped"][0]["file"], "a.json")
        self.assertIn("url: not a readable URL", payload["skipped"][0]["reason"])

    def test_a_stored_record_with_a_bad_url_does_not_stop_the_batch(self):
        records, _ = jd_parser.parse_text(DATA, source_type="portal", site="boss", single=True, now=NOW,
                                          site_job_id="a1", fetched_at="2026-11-05T10:31:20+08:00")
        with self.assertRaisesRegex(store.StoreError, "not a readable URL"):
            self.store.save(dict(records[0], source=dict(records[0]["source"], url="https://example.invalid:abc/1")))
        self.store._write(dict(records[0], source=dict(records[0]["source"], url="https://example.invalid:abc/1")))
        self.put("b.json", item(BACKEND, site_job_id="b2"))
        self.assertEqual(self.run_batch()["imported"]["created"], 1)


class Dedup(Case):
    def parsed(self, text: str, **source) -> dict:
        records, _ = jd_parser.parse_text(text, source_type="portal", site="boss", single=True, now=NOW,
                                          fetched_at=source.pop("fetched_at", "2026-11-05T10:31:20+08:00"), **source)
        return records[0]

    def test_the_same_job_board_id_with_edited_text_updates_in_place(self):
        action, first = self.store.save(self.parsed(DATA, site_job_id="a1"))
        self.assertEqual(action, "created")
        self.store.set_status(first["id"], "ranked")
        edited = self.parsed(DATA + "\n补充：表现优秀可转正", site_job_id="a1", fetched_at=LATER)
        self.assertNotEqual(edited["id"], first["id"])
        action, second = self.store.save(edited)
        self.assertEqual(action, "updated")
        self.assertEqual((second["id"], second["status"]), (first["id"], "ranked"))
        self.assertEqual(second["source"]["imported_at"], first["source"]["imported_at"])
        self.assertEqual((second["raw_text"], second["source"]["fetched_at"]), (edited["raw_text"], LATER))
        self.assertEqual(len(self.store.all()[0]), 1)

    def test_a_link_differing_only_in_tracking_parameters(self):
        self.store.save(self.parsed(DATA, url="https://www.zhipin.com/job_detail/x2.html?ka=search_list&lid=9&securityId=s"))
        action, stored = self.store.save(self.parsed(DATA + "\n补充：可提前转正", url="http://www.zhipin.com/job_detail/x2.html"))
        self.assertEqual(action, "updated")
        self.assertEqual(len(self.store.all()[0]), 1)

    def test_the_same_text_again_is_unchanged(self):
        self.store.save(self.parsed(DATA, site_job_id="a1"))
        action, stored = self.store.save(self.parsed(DATA, site_job_id="a1", fetched_at=LATER))
        self.assertEqual(action, "unchanged")
        self.assertEqual(stored["source"]["fetched_at"], "2026-11-05T10:31:20+08:00")  # the first fetch of this text

    def test_the_job_board_id_comes_before_the_fingerprint(self):
        _, a = self.store.save(self.parsed(DATA, site_job_id="y1"))
        [pasted], _ = jd_parser.parse_text(OPS, now=NOW)
        _, b = self.store.save(pasted)
        action, stored = self.store.save(self.parsed(OPS, site_job_id="y1"))
        self.assertEqual((action, stored["id"]), ("updated", a["id"]))
        self.assertEqual(self.store.get(b["id"])["raw_text"], b["raw_text"])

    def test_pasted_first_and_fetched_later_fills_the_source_and_keeps_the_match(self):
        [pasted], _ = jd_parser.parse_text(DATA, now=NOW)
        _, job = self.store.save(pasted)
        saved = score.score_job(job, self.profile, VOCABULARY, now=NOW)
        self.matches.save(saved)
        action, stored = self.store.save(self.parsed(DATA, site_job_id="z1", url="https://www.zhipin.com/job_detail/z1.html"))
        self.assertEqual((action, stored["id"]), ("updated", job["id"]))
        self.assertEqual({key: stored["source"][key] for key in ("type", "site", "site_job_id", "fetched_at")},
                         {"type": "paste", "site": "boss", "site_job_id": "z1", "fetched_at": "2026-11-05T10:31:20+08:00"})
        # job_hash leaves the source out (M6-4): the saved match is still current.
        self.assertEqual(score.stale_reasons(saved, stored, score.profile_hash(self.profile),
                                             score.weights_of(self.profile)), [])

    def test_a_record_stored_before_m6_4_reads_back_with_the_new_fields(self):
        _, job = self.store.save(self.parsed(DATA))
        path = self.data / "jobs" / f"{job['id']}.json"
        old = json.loads(path.read_text(encoding="utf-8"))
        del old["source"]["site_job_id"], old["source"]["fetched_at"]
        path.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        again = self.store.get(job["id"])
        self.assertEqual((again["source"]["site_job_id"], again["source"]["fetched_at"]), (None, None))
        self.assertEqual(schema.validate(again), [])
        self.assertEqual(score.job_hash(again), score.job_hash(job))

    def test_job_hash_leaves_the_source_out(self):
        _, job = self.store.save(self.parsed(DATA))
        moved = json.loads(json.dumps(job))
        moved["source"].update(url="https://www.zhipin.com/job_detail/q.html", site_job_id="q")
        self.assertEqual(score.job_hash(moved), score.job_hash(job))
        moved["title"] = "数据分析师"
        self.assertNotEqual(score.job_hash(moved), score.job_hash(job))

    def test_a_batch_reads_the_store_once(self):
        self.five_jobs()
        self.put("f6.json", item(DATA + "\n补充：可提前转正", site_job_id="a1"))  # the same posting as a1.json
        calls, original = [], store.Store.all

        def counted(job_store):
            calls.append(1)
            return original(job_store)

        store.Store.all = counted
        try:
            payload = self.run_batch()
        finally:
            store.Store.all = original
        self.assertEqual(len(calls), 1)
        self.assertEqual(payload["imported"], {"created": 5, "updated": 0, "unchanged": 0, "skipped": 0})
        duplicates = [w for w in payload["warnings"] if w["kind"] == "duplicate"]
        self.assertEqual([(w["file"], w["message"][:22]) for w in duplicates], [("f6.json", "the same posting as a1")])

    def test_an_update_frees_the_keys_it_moved_away_from(self):
        """(old, U1) -> (new, U1) updates it; (old, U2) is then another posting, with and without the index."""
        u1, u2 = "https://example.invalid/job/1", "https://example.invalid/job/2"
        sequence = [(DATA, "old", u1), (BACKEND, "new", u1), (OPS, "old", u2)]
        plain = []
        for text, site_job_id, url in sequence:
            action, _ = self.store.save(self.parsed(text, site_job_id=site_job_id, url=url))
            plain.append(action)
        self.assertEqual(plain, ["created", "updated", "created"])
        stored = {r["source"]["site_job_id"]: r["raw_text"] for r in self.store.all()[0]}
        shutil.rmtree(self.data / "jobs")
        index, batched = self.store.index(), []
        for text, site_job_id, url in sequence:
            action, _ = self.store.save(self.parsed(text, site_job_id=site_job_id, url=url), index)
            batched.append(action)
        self.assertEqual(batched, plain)
        self.assertEqual({r["source"]["site_job_id"]: r["raw_text"] for r in self.store.all()[0]}, stored)
        self.assertEqual(sorted(stored), ["new", "old"])
        shutil.rmtree(self.data / "jobs")
        for name, (text, site_job_id, url) in zip(("a.json", "b.json", "c.json"), sequence):
            self.put(name, item(text, site_job_id=site_job_id, url=url))
        payload = self.run_batch()
        self.assertEqual(payload["imported"], {"created": 2, "updated": 0, "unchanged": 0, "skipped": 0})
        self.assertEqual({r["source"]["site_job_id"]: r["raw_text"] for r in self.store.all()[0]}, stored)

    def test_the_first_text_again_after_an_edit_replaces_the_edit(self):
        edited = DATA.replace("150-200元/天", "180-220元/天", 1)
        self.assertNotEqual(edited, DATA)
        for key in ({"site_job_id": "a1"}, {"url": "https://example.invalid/job/7"}):
            with self.subTest(key=key):
                shutil.rmtree(self.data / "jobs", ignore_errors=True)
                actions = [self.store.save(self.parsed(text, **key))[0] for text in (DATA, edited, DATA)]
                self.assertEqual(actions, ["created", "updated", "updated"])
                [stored] = self.store.all()[0]
                self.assertEqual((stored["raw_text"], stored["salary"]["min"], stored["salary"]["max"]), (DATA, 150, 200))

    def test_a_batch_with_both_versions_runs_again_without_skipping(self):
        edited = DATA.replace("150-200元/天", "180-220元/天", 1)
        self.put("v1.json", item(DATA, site_job_id="a1"))
        self.put("v2.json", item(edited, site_job_id="a1"))
        for _ in range(2):
            payload = self.run_batch()
            self.assertEqual(payload["imported"]["skipped"], 0, payload["skipped"])
            [stored] = self.store.all()[0]
            self.assertEqual(stored["raw_text"], edited)  # the batch's last file wins


class Scoring(Case):
    def test_new_jobs_are_scored_as_match_score_does(self):
        self.five_jobs()
        payload = self.run_batch()
        self.assertEqual(payload["scored"], 5)
        for job in self.store.all()[0]:
            self.assertEqual(self.matches.get(job["id"]), score.score_job(job, self.profile, VOCABULARY, now=NOW))

    def test_a_second_run_scores_nothing_and_writes_nothing(self):
        self.five_jobs()
        first = self.run_batch()
        before = {path: path.read_bytes() for path in sorted(self.data.rglob("*")) if path.is_file()}
        second = self.run_batch()
        self.assertEqual(second["scored"], 0)
        self.assertEqual(second["imported"], {"created": 0, "updated": 0, "unchanged": 5, "skipped": 0})
        self.assertEqual(before, {path: path.read_bytes() for path in sorted(self.data.rglob("*")) if path.is_file()})
        strip = lambda rows: [(r["job_id"], r["score"], r["grade"]) for r in rows]  # noqa: E731
        self.assertEqual(strip(second["shortlist"]["rows"]), strip(first["shortlist"]["rows"]))
        self.assertTrue(all(row["line"].endswith("以前导入过") for row in second["shortlist"]["rows"]))

    def agent_experience(self, job_id: str) -> dict:
        record = self.matches.get(job_id)
        record["dimensions"]["experience"].update(score=90, method="agent", reason="做过同类工作")
        record["total"] = score.total(record["dimensions"], record["weights"], record["filter"]["verdict"])
        self.matches.save(record)
        return record

    def test_a_current_record_with_agent_work_is_kept(self):
        self.five_jobs()
        self.run_batch()
        backend = next(job["id"] for job in self.store.all()[0] if job["title"].startswith("后端"))
        kept = self.agent_experience(backend)
        payload = self.run_batch()
        self.assertEqual(self.matches.get(backend), kept)
        row = next(row for row in payload["shortlist"]["rows"] if row["job_id"] == backend)
        self.assertEqual(row["score"], kept["total"]["score"])

    def test_new_weights_keep_the_agent_work_and_a_changed_profile_drops_it(self):
        self.five_jobs()
        self.run_batch()
        backend = next(job["id"] for job in self.store.all()[0] if job["title"].startswith("后端"))
        self.agent_experience(backend)
        self.profile["target"]["weights"] = {"skills": 20, "direction": 20, "experience": 40, "salary": 10,
                                             "location": 10}
        payload = self.run_batch()
        self.assertEqual(payload["scored"], 5)
        self.assertEqual(self.matches.get(backend)["dimensions"]["experience"]["score"], 90)
        self.profile["availability"]["months"] = 8
        self.assertEqual(self.run_batch()["scored"], 5)
        self.assertIsNone(self.matches.get(backend)["dimensions"]["experience"]["score"])

    def test_jobs_marked_not_to_list_are_counted_only(self):
        self.five_jobs()
        self.run_batch()
        backend = next(job["id"] for job in self.store.all()[0] if job["title"].startswith("后端"))
        self.store.set_status(backend, "skipped")
        self.profile["availability"]["months"] = 8  # every record stale: only the four listed are scored again
        payload = self.run_batch()
        self.assertEqual((payload["scored"], payload["not_listed"]), (4, {"skipped": 1, "expired": 0, "unreachable": 0}))
        listed = [row["job_id"] for row in payload["shortlist"]["rows"] + payload["ruled_out"]["rows"]]
        self.assertNotIn(backend, listed)
        self.assertEqual(len(listed), 4)


class Shortlist(Case):
    def test_order_and_what_is_ruled_out(self):
        self.five_jobs()
        payload = self.run_batch()
        records = {job["id"]: self.matches.get(job["id"]) for job in self.store.all()[0]}
        key = lambda job_id: score.list_key(records[job_id]["total"]["grade"], records[job_id]["total"]["score"], job_id)  # noqa: E731
        ruled_out = sorted((i for i, r in records.items() if r["filter"]["verdict"] == match.INELIGIBLE), key=key)
        listed = sorted((i for i in records if i not in ruled_out), key=key)
        self.assertTrue(listed and ruled_out, "the sample batch has both")
        self.assertEqual([row["job_id"] for row in payload["shortlist"]["rows"]], listed)
        self.assertEqual([row["rank"] for row in payload["shortlist"]["rows"]], list(range(1, len(listed) + 1)))
        self.assertEqual([row["job_id"] for row in payload["ruled_out"]["rows"]], ruled_out)
        conflicts = Counter(check["check"] for i in ruled_out for check in records[i]["filter"]["checks"]
                            if check["result"] == match.CONFLICT)
        self.assertEqual({item["check"]: item["jobs"] for item in payload["ruled_out"]["by_check"]}, dict(conflicts))
        self.assertEqual(payload["ruled_out"]["jobs"], len(ruled_out))
        self.assertTrue(any("过滤掉" in line for line in payload["summary"]))

    def test_top(self):
        self.five_jobs()
        whole = self.run_batch(top=0)["shortlist"]
        cut = self.run_batch(top=2)["shortlist"]
        self.assertEqual((cut["total"], cut["shown"]), (whole["total"], 2))
        self.assertEqual(cut["rows"], [dict(row, action="unchanged", line=row["line"] + "｜以前导入过")
                                       for row in whole["rows"][:2]])

    def test_the_line(self):
        self.put("b2.json", item(BACKEND, site_job_id="b2", url="https://www.zhipin.com/job_detail/b2.html"))
        [row] = self.run_batch()["shortlist"]["rows"]
        grade = {"strong": "很匹配", "good": "较匹配", "moderate": "一般", "weak": "较弱", "poor": "不匹配"}[row["grade"]]
        self.assertTrue(row["line"].startswith(f"1. 后端开发实习生（Go方向）｜示例互联网科技（深圳）有限公司｜深圳｜200–250 元/天｜"
                                               f"{row['score']} 分，{grade}"), row["line"])
        self.assertEqual((row["url"], row["files"], row["action"]),
                         ("https://www.zhipin.com/job_detail/b2.html", ["b2.json"], "created"))

    def test_salary_text(self):
        day = {"min": 150, "max": 200, "unit": "CNY/day", "months": None, "negotiable": False}
        self.assertEqual(screen.salary_text(day), "150–200 元/天")
        self.assertEqual(screen.salary_text(dict(day, min=15000, max=25000, unit="CNY/month", months=13)),
                         "15000–25000 元/月 · 13 薪")
        self.assertEqual(screen.salary_text(dict(day, max=150)), "150 元/天")
        self.assertEqual(screen.salary_text(dict(day, min=None, max=None, unit=None, negotiable=True)), "面议")
        self.assertIsNone(screen.salary_text(None))

    def test_points_to_confirm(self):
        def check(name, result, reason):
            return {"check": name, "result": result, "reason": reason}
        record = {
            "filter": {"verdict": "needs_check", "checks": [
                check("graduation", "unknown", "JD 没写届别；你是 2027 届"),
                check("days_per_week", "unknown", "JD 要求每周到岗 4 天；档案没写每周能到岗几天"),
                check("interview", "unknown", "JD 写要现场面试，在北京，不在你的意向城市内；你暂时不去外地面试，投之前先问能不能线上面试"),
                check("start_date", "unknown", "JD 没写到岗时间；你 2026-11-15 可以到岗"),
                check("education", "match", "本科不低于本科")]},
            "dimensions": {"skills": {"score": 80}, "direction": {"score": 100}, "experience": {"score": None},
                           "salary": {"score": None}, "location": {"score": 100}},
        }
        job = {"title": None, "company": "示例公司", "cities": ["广州"], "guard": {"verdict": "warn"},
               "salary": {"min": None, "max": None, "unit": None, "months": None, "negotiable": True}}
        points, gaps = screen.confirm_points(job, record, self.profile)
        self.assertEqual(points, ["届别（JD 没写届别）", "面试（只在外地现场面，先问能不能线上）", "薪资（面议）",
                                  "职位名（没读出，看原文）", "JD 里有像是写给 AI 的句子（摘录见 warnings）"])
        self.assertEqual(gaps, [("days_per_week", "每周到岗", "档案没写每周能到岗几天")])

    def test_profile_gaps_are_summed_once(self):
        self.five_jobs()
        del self.profile["target"]["directions"]
        payload = self.run_batch()
        [gap] = [gap for gap in payload["profile_gaps"] if gap["check"] == "direction"]
        self.assertEqual(gap["jobs"], 5)
        self.assertFalse(any("方向" in point for row in payload["shortlist"]["rows"] for point in row["to_confirm"]))
        self.assertTrue(any("档案没写求职方向（5 个岗位）" in line for line in payload["summary"]))


def run_cli(*args, data_dir, cwd=REPO):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", **{store.DATA_DIR_ENV: str(data_dir)})
    return subprocess.run([sys.executable, "-m", "jobsearch_cn", *args], cwd=cwd, env=env, capture_output=True)


class Command(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name) / "data"
        (self.data / "profile").mkdir(parents=True)
        (self.data / "profile" / "profile.json").write_text(json.dumps(PROFILE, ensure_ascii=False), encoding="utf-8")
        self.batch = self.data / "inbox" / "boss" / SAMPLE.name
        shutil.copytree(SAMPLE, self.batch)

    def cli(self, *args, expect=0):
        proc = run_cli(*args, data_dir=self.data)
        self.assertEqual(proc.returncode, expect, proc.stdout.decode("utf-8") + proc.stderr.decode("utf-8", "replace"))
        return proc

    def snapshot(self):
        return {path: path.read_bytes() for path in sorted(self.data.rglob("*")) if path.is_file()}

    def test_check_needs_no_profile_and_writes_nothing(self):
        (self.data / "profile" / "profile.json").unlink()
        before = self.snapshot()
        out = json.loads(self.cli("jd", "screen", str(self.batch), "--check").stdout)
        self.assertEqual((out["ok"], out["failed"], out["jobs"], out["duplicates"]), (3, 0, 3, []))
        self.assertEqual(self.snapshot(), before)
        (self.batch / "bad.json").write_text(json.dumps(item(DATA, fetchedAt=LATER)), encoding="utf-8")
        self.cli("jd", "screen", str(self.batch), "--check", expect=1)

    def test_screen_the_sample_batch(self):
        proc = self.cli("jd", "screen", str(self.batch))
        out = json.loads(proc.stdout)
        self.assertEqual(out["imported"], {"created": 3, "updated": 0, "unchanged": 0, "skipped": 0})
        self.assertEqual(out["shortlist"]["total"] + out["ruled_out"]["jobs"], 3)
        self.assertEqual(len(json.loads(self.cli("jd", "list").stdout)["jobs"]), 3)
        self.assertEqual(len(json.loads(self.cli("match", "list").stdout)["matches"]), 3)
        text = proc.stdout.decode("utf-8")
        for contact in ("13800000000", "liming@example.com"):  # the sample profile's made-up contact details
            self.assertNotIn(contact, text)
        self.assertEqual(json.loads(self.cli("jd", "screen", str(self.batch)).stdout)["scored"], 0)

    def test_exit_codes(self):
        self.cli("jd", "screen", str(self.data / "nowhere"), expect=2)
        elsewhere = self.data / "inbox" / "mystery" / "b1"
        shutil.copytree(SAMPLE, elsewhere)
        self.cli("jd", "screen", str(elsewhere), expect=2)  # the folder holding it names no site
        self.cli("jd", "screen", str(elsewhere), "--site", "boss", "--check")
        empty = self.data / "inbox" / "boss" / "empty"
        empty.mkdir()
        self.cli("jd", "screen", str(empty), expect=1)
        self.cli("jd", "screen", str(self.batch), "--top", "-1", expect=2)
        self.cli("jd", "screen", str(self.batch), "--top", "x", expect=2)

    def test_an_invalid_profile_stores_nothing(self):
        (self.data / "profile" / "profile.json").write_text('{"schema_version": 99}', encoding="utf-8")
        self.cli("jd", "screen", str(self.batch), expect=1)
        self.assertFalse((self.data / "jobs").exists())
        self.assertFalse((self.data / "matches").exists())


if __name__ == "__main__":
    unittest.main()
