"""Generic list summary protection, using fictional URLs."""
import json
from tests.test_cn_screen import Case, DATA, NOW, VOCABULARY, item
from jobsearch_cn import screen

URL = "https://jobs.example.invalid/openings/s1.html"
DETAIL = DATA
EDITED = DATA + "\n另外负责维护数据看板"
CARD = "数据分析实习生 150-200元/天\n广州 本科\n示例数据科技"
CHANGED_CARD = "数据分析实习生 300-400元/天\n广州 本科\n示例数据科技"


def clip(text: str, **extra) -> dict:
    return item(text, site="official", url=URL, extra=extra)


class ListSummary(Case):
    """A list card (extra.page == "list") never replaces a stored job; everything else behaves as before."""

    def batch_of(self, name: str, *contents):
        batch = self.data / "inbox" / "official" / name
        batch.mkdir(parents=True, exist_ok=True)
        for number, content in enumerate(contents):
            (batch / f"{number:02}.json").write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        return batch

    def screen(self, batch) -> dict:
        return screen.run(batch, "official", self.profile, VOCABULARY, self.store, self.matches, top=0, now=NOW)

    def stored(self) -> dict:
        records, _ = self.store.all()
        self.assertEqual(len(records), 1)
        return records[0]

    def assert_result(self, payload: dict, action: str, *kinds) -> None:
        self.assertEqual(payload["imported"][action], 1, payload["imported"])
        self.assertEqual(sorted(w["kind"] for w in payload["warnings"]), sorted(kinds))

    def test_same_batch_card_then_detail(self):
        self.assert_result(self.screen(self.batch_of("b", clip(CARD, page="list"), clip(DETAIL, page="detail"))),
                           "created", "duplicate")
        self.assertEqual(self.stored()["raw_text"], DETAIL)

    def test_same_batch_detail_then_card(self):
        self.assert_result(self.screen(self.batch_of("b", clip(DETAIL, page="detail"), clip(CARD, page="list"))),
                           "created", "duplicate", "summary_kept")
        self.assertEqual(self.stored()["raw_text"], DETAIL)

    def test_later_batch_card_then_detail(self):
        self.assert_result(self.screen(self.batch_of("b1", clip(CARD, page="list"))), "created")
        self.assertEqual(self.stored()["raw_text"], CARD)
        self.assert_result(self.screen(self.batch_of("b2", clip(DETAIL, page="detail"))), "updated")
        self.assertEqual(self.stored()["raw_text"], DETAIL)

    def test_later_batch_detail_then_card_writes_nothing_and_still_lists_the_job(self):
        self.screen(self.batch_of("b1", clip(DETAIL, page="detail")))
        [job_file] = (self.data / "jobs").glob("job_*.json")
        [match_file] = (self.data / "matches").glob("*.json")
        before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in (job_file, match_file)]
        payload = self.screen(self.batch_of("b2", clip(CARD, page="list")))
        self.assert_result(payload, "unchanged", "summary_kept")
        self.assertEqual([(path.read_bytes(), path.stat().st_mtime_ns) for path in (job_file, match_file)], before)
        [warning] = payload["warnings"]
        self.assertEqual(warning["file"], "00.json")
        self.assertIn("detail page", warning["message"])
        self.assertEqual(payload["scored"], 0)
        rows = payload["shortlist"]["rows"] + payload["ruled_out"]["rows"]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].get("jd_changed"))

    def test_a_card_can_still_add_a_new_job(self):
        self.assert_result(self.screen(self.batch_of("b", clip(CARD, page="list"))), "created")
        self.assertEqual(self.stored()["raw_text"], CARD)

    def test_a_card_does_not_refresh_a_card(self):
        self.screen(self.batch_of("b1", clip(CARD, page="list")))
        self.assert_result(self.screen(self.batch_of("b2", clip(CHANGED_CARD, page="list"))), "unchanged", "summary_kept")
        self.assertEqual(self.stored()["raw_text"], CARD)

    def test_the_same_card_again_is_plain_unchanged(self):
        self.screen(self.batch_of("b1", clip(CARD, page="list")))
        self.assert_result(self.screen(self.batch_of("b2", clip(CARD, page="list"))), "unchanged")

    def test_a_detail_still_replaces_a_detail(self):
        self.screen(self.batch_of("b1", clip(DETAIL, page="detail")))
        self.assert_result(self.screen(self.batch_of("b2", clip(EDITED, page="detail"))), "updated")
        self.assertEqual(self.stored()["raw_text"], EDITED)

    def test_a_card_keeps_a_detail_saved_without_a_marker(self):
        self.screen(self.batch_of("b1", clip(DETAIL, collector="example-collect")))
        self.assert_result(self.screen(self.batch_of("b2", clip(CARD, page="list"))), "unchanged", "summary_kept")
        self.assertEqual(self.stored()["raw_text"], DETAIL)

    def test_a_card_keeps_a_job_found_by_its_link_alone(self):
        self.screen(self.batch_of("b1", item(DETAIL, site="official", url=URL)))
        self.assert_result(self.screen(self.batch_of("b2", clip(CARD, page="list"))), "unchanged", "summary_kept")
        self.assertEqual(self.stored()["raw_text"], DETAIL)

    def test_only_the_exact_marker_counts(self):
        self.screen(self.batch_of("b1", clip(DETAIL)))
        for name, text, extra in (("b2", EDITED, {"page": 2}), ("b3", CARD, {"page": "List"}), ("b4", CHANGED_CARD, {})):
            self.assert_result(self.screen(self.batch_of(name, clip(text, **extra))), "updated")
            self.assertEqual(self.stored()["raw_text"], text)

    def test_running_an_old_card_batch_again_keeps_the_detail(self):
        old = self.batch_of("b1", clip(CARD, page="list"))
        self.screen(old)
        self.screen(self.batch_of("b2", clip(DETAIL, page="detail")))
        self.assert_result(self.screen(old), "unchanged", "summary_kept")
        self.assertEqual(self.stored()["raw_text"], DETAIL)

    def test_running_a_card_and_detail_batch_again_changes_nothing(self):
        batch = self.batch_of("b", clip(CARD, page="list"), clip(DETAIL, page="detail"))
        self.screen(batch)
        before = self.stored()
        self.assert_result(self.screen(batch), "unchanged", "duplicate", "summary_kept")
        self.assertEqual(self.stored(), before)

    def test_a_kept_job_keeps_its_status(self):
        self.screen(self.batch_of("b1", clip(DETAIL)))
        self.store.set_status(self.stored()["id"], "skipped")
        payload = self.screen(self.batch_of("b2", clip(CARD, page="list")))
        self.assertEqual(self.stored()["status"], "skipped")
        self.assertEqual(self.stored()["raw_text"], DETAIL)
        self.assertEqual(payload["shortlist"]["rows"], [])
