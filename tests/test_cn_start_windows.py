"""A labeled start window must not turn its first date into a deadline."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.test_cn_jd_parser import parse_one
from tests.test_cn_match import PROFILES, run_cli


HEADER = "职位名称：软件开发工程师\n公司名称：示例科技有限公司\n发布日期：2026-10-01\n"


class StartWindows(unittest.TestCase):
    def assert_unknown(self, text):
        record = parse_one(HEADER + text)
        self.assertIsNone(record["requirements"]["start"])
        self.assertNotIn("requirements.start", record["evidence"])

    def test_labeled_windows_and_choices_remain_unknown(self):
        for text in (
            "入职时间：2026年11月1日-2026年11月15日",
            "到岗日期：11月1日至11月15日",
            "报到时间：11月1日至15日",
            "上岗日期：11月1号到15号",
            "入职时间：11月至12月",
            "入职日期：11月1日或12月1日",
            "入职时间：为 11 月 1 日 ～ 11 月 15 日",
        ):
            with self.subTest(text=text):
                self.assert_unknown(text)

    def test_supported_range_and_choice_separators(self):
        for separator in ("或", "或者", "、", "/", "／", "和", "至", "到", "-", "－", "—", "–", "~", "～"):
            with self.subTest(separator=separator):
                self.assert_unknown(f"入职时间：11月1日{separator}11月15日")

    def test_an_ambiguous_window_keeps_an_independent_asap_requirement(self):
        record = parse_one(HEADER + "入职时间：11月1日至15日\n尽快到岗")
        self.assertEqual(record["requirements"]["start"], {"by": None, "asap": True})
        self.assertEqual(record["evidence"]["requirements.start"],
                         {"text": "尽快到岗", "method": "rule"})

    def test_single_dates_keep_the_existing_deadline_behavior(self):
        for text, expected in (
            ("入职时间：11月1日", "2026-11-01"),
            ("到岗日期：2026年11月15日", "2026-11-15"),
            ("11月15日前到岗", "2026-11-15"),
            ("入职时间：11月底", "2026-11-30"),
            ("入职日期：11月", "2026-11-30"),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_one(HEADER + text)["requirements"]["start"],
                                 {"by": expected, "asap": False})

    def test_an_unrelated_date_after_a_clause_or_line_does_not_clear_the_deadline(self):
        for boundary in ("，", "；", "。", "\n"):
            text = f"入职时间：11月1日{boundary}或12月1日参加培训"
            with self.subTest(boundary=boundary):
                self.assertEqual(parse_one(HEADER + text)["requirements"]["start"],
                                 {"by": "2026-11-01", "asap": False})

    def test_existing_date_first_ambiguity_and_preferences_remain_unknown(self):
        for text in ("11月1日至11月15日到岗", "11月1日或12月1日到岗",
                     "入职时间：11月1日后", "入职时间：11月1日优先"):
            with self.subTest(text=text):
                self.assert_unknown(text)

    def test_cli_saved_window_does_not_reject_a_candidate_available_within_it(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            shutil.copytree(PROFILES / "tech", data / "profile")  # synthetic November 15 start
            source = data / "jd.txt"
            for text, expected in (("入职时间：11月1日至11月15日", "unknown"),
                                   ("入职时间：11月1日或12月1日", "unknown"),
                                   ("入职时间：11月1日", "conflict")):
                with self.subTest(text=text):
                    source.write_text(HEADER + text, encoding="utf-8")
                    parsed = run_cli("jd", "parse", str(source), "--save", data_dir=data)
                    self.assertEqual(parsed.returncode, 0, parsed.stderr.decode("utf-8"))
                    job_id = json.loads(parsed.stdout)["saved"][0]["id"]
                    filtered = run_cli("match", "filter", job_id, data_dir=data)
                    self.assertEqual(filtered.returncode, 0, filtered.stderr.decode("utf-8"))
                    checks = json.loads(filtered.stdout)["checks"]
                    start = next(c for c in checks if c["check"] == "start_date")
                    self.assertEqual(start["result"], expected, start["reason"])


if __name__ == "__main__":
    unittest.main()
