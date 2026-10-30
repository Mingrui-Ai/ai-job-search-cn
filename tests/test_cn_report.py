"""Tests for match report (M2-6a; jobsearch_cn/report.py, docs/cn/match.md 评分报告).

The report is only useful if what it shows is what was saved, so these build
real records the way the scoring workflow does - sample JDs and the sample
tech profile, two of them with the experience an agent added in M2-4c - run
match report through the CLI, and check each job's section against match show
and the ranking against match list. Then the feedback form (BOM, CRLF, commas
and quotes, a JD title that looks like a formula), no contact details in
either file, stale records, a page that loads nothing from outside and
escapes the JD, the "how to settle it" for what is still open, and that the
command only reads.
"""
import copy
import csv
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "cn"
JUDGMENTS = FIXTURES / "match-m2-4c" / "agent-judgments.json"
# Eligible, needs_check, and two ineligible; the first two get the agent's experience.
SAMPLES = ("jd/boss_intern.txt", "jd/nowcoder_campus.txt", "jd/official_site.txt", "jd/experienced_hire.txt")
COMPLETED = ("jd/boss_intern.txt", "jd/nowcoder_campus.txt")

sys.path.insert(0, str(REPO))
from jobsearch_cn import cli, jd_parser, match, report, score, vocab  # noqa: E402

NOW = datetime(2026, 10, 29, 9, 30, tzinfo=timezone(timedelta(hours=8)))
VOCABULARY = vocab.load()


def run_cli(*args, data_dir):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", JOBSEARCH_CN_DATA_DIR=str(data_dir))
    return subprocess.run([sys.executable, "-m", "jobsearch_cn", *args], cwd=REPO, env=env, capture_output=True)


def experience_for(sample: str) -> dict:
    judgments = json.loads(JUDGMENTS.read_text(encoding="utf-8"))["judgments"]
    return next(j["experience"] for j in judgments if (j["sample"], j["profile"]) == (sample, "tech"))


class ReportFromSavedRecords(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name)
        shutil.copytree(FIXTURES / "profile" / "tech", self.data / "profile")
        self.profile = json.loads((self.data / "profile" / "profile.json").read_text(encoding="utf-8"))
        self.ids = {}
        for sample in SAMPLES:
            job_id = self.cli("jd", "parse", str(FIXTURES / sample), "--save")["saved"][0]["id"]
            self.ids[sample] = job_id
            record = self.cli("match", "score", job_id, "--save")
            if sample in COMPLETED:
                record["dimensions"]["experience"].update(experience_for(sample))
                record["total"] = score.total(record["dimensions"], record["weights"], record["filter"]["verdict"])
                draft = self.data / "draft.json"
                draft.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
                self.assertEqual(self.cli("match", "save", str(draft))["saved"], "updated")

    def cli(self, *args, expect=0):
        proc = run_cli(*args, data_dir=self.data)
        self.assertEqual(proc.returncode, expect, proc.stdout.decode("utf-8") + proc.stderr.decode("utf-8", "replace"))
        return json.loads(proc.stdout) if proc.stdout.strip() else json.loads(proc.stderr or "{}")

    def generate(self, *ids):
        result = self.cli("match", "report", *ids)
        page = Path(result["report"]).read_text(encoding="utf-8")
        form = Path(result["feedback"]).read_bytes()
        return result, page, form

    @staticmethod
    def section(page: str, job_id: str) -> str:
        start = page.index(f'<section id="{job_id}">')
        return page[start:page.index("</section>", start)]

    @staticmethod
    def row(dims: str, key: str) -> str:
        start = dims.index(f"<td>{report.DIMENSIONS[key]}</td>")
        return html.unescape(dims[start:dims.index("</tr>", start)])

    def assert_rule_grounds(self, record: dict, job: dict, dims: str):
        """The rule dimensions show the JD text they rest on, taken from the stored job."""
        skills, quotes = record["dimensions"]["skills"], score.skill_quotes(job, VOCABULARY)
        for label in [hit["jd"] for hit in skills["matched"]] + skills["missing"]:
            quote = quotes[label]
            for snippet in [quote] if isinstance(quote, str) else quote or []:
                self.assertIn(snippet, self.row(dims, "skills"))
        salary = score._quote(job, "salary")
        if salary:
            self.assertIn(salary, self.row(dims, "salary"))
        for group, names in score.direction_skills(job, VOCABULARY).items():
            self.assertIn(f"{VOCABULARY.groups[group]['label']}（{group}）{len(names)} 项：{'、'.join(names)}",
                          self.row(dims, "direction"))
        cities = (job["evidence"].get("cities") or {}).get("text")
        for snippet in [cities] if isinstance(cities, str) else cities or []:
            self.assertIn(snippet, self.row(dims, "location"))

    def test_the_salary_quote_of_a_known_job(self):
        # Codex B's case in #65: the salary row was empty although the stored job quotes it.
        _, page, _ = self.generate()
        dims = self.section(page, self.ids["jd/boss_intern.txt"])
        self.assertIn("200-250元/天", self.row(dims, "salary"))

    def test_a_choice_counts_once_where_the_score_counted_it(self):
        # H16: boss_intern's "熟悉 Golang 或 Java" is one requirement; the direction counts it once,
        # and the report lists exactly what the score counted.
        _, page, _ = self.generate()
        job_id = self.ids["jd/boss_intern.txt"]
        record, job = self.cli("match", "show", job_id), self.cli("jd", "show", job_id)
        counted = score.direction_skills(job, VOCABULARY)
        choices = [label for labels in counted.values() for label in labels if " 或 " in label]
        self.assertEqual(len(choices), 1, counted)
        self.assertEqual({group: len(labels) for group, labels in counted.items()},
                         record["dimensions"]["direction"]["jd_groups"])
        direction = self.row(self.section(page, job_id), "direction")
        self.assertIn(choices[0], direction)
        self.assertEqual(direction.count(choices[0]), 1)
        self.assertIn("熟悉 Golang 或 Java", self.row(self.section(page, job_id), "skills"))

    def rescored_with(self, weights: dict, sample="jd/boss_intern.txt") -> tuple:
        return self.rescored("target.weights", weights, sample)

    def rescored(self, path: str, value, sample="jd/boss_intern.txt") -> tuple:
        """(record, report section) for one job scored again after one profile field changed."""
        (self.data / "profile" / "profile.json").write_text(
            json.dumps(setting(self.profile, path, value), ensure_ascii=False), encoding="utf-8")
        job_id = self.ids[sample]
        record = self.cli("match", "score", job_id, "--save")
        _, page, _ = self.generate(job_id)
        return record, self.section(page, job_id)

    @staticmethod
    def dimensions_part(part: str) -> str:
        """The 各维度 table only: 地点 names a hard condition too."""
        return part[part.index("<h3>各维度</h3>"):part.index("<h3>总分怎么算</h3>")]

    def test_the_location_row_quotes_the_cities_and_the_remote_offer_that_counted(self):
        # official_site: 杭州 is not one of tech's cities, but the JD offers remote work and tech accepts it.
        _, page, _ = self.generate()
        job_id = self.ids["jd/official_site.txt"]
        self.assertEqual(self.cli("match", "show", job_id)["dimensions"]["location"]["score"], 100)
        row = self.row(self.dimensions_part(self.section(page, job_id)), "location")
        self.assertIn("工作地点：杭州", row)
        self.assertIn("支持远程实习", row)
        # Not accepting remote work, the score rests on the city alone.
        record, part = self.rescored("availability.remote_ok", False, "jd/official_site.txt")
        self.assertEqual(record["dimensions"]["location"]["score"], 0)
        row = self.row(self.dimensions_part(part), "location")
        self.assertIn("工作地点：杭州", row)
        self.assertNotIn("支持远程实习", row)

    def test_a_total_near_a_half_is_explained_without_rounding_first(self):
        # Codex B's case in #65: skills 43, direction 100, weights 1.0001 and 1 give 71.498575…, which
        # was shown as 71.50 and then "rounded" to 71. Built by hand so later rule changes cannot move it.
        dimensions = {key: {"score": None, "method": "rule", "reason": "r"} for key in score.DIMENSIONS}
        dimensions["skills"]["score"], dimensions["direction"]["score"] = 43, 100
        weights = {"skills": 1.0001, "direction": 1, "experience": 0, "salary": 0, "location": 0}
        record = {"job_id": "job_0123456789ab", "filter": {"verdict": "eligible", "checks": []}, "gaps": [],
                  "dimensions": dimensions, "weights": weights, "total": score.total(dimensions, weights, "eligible")}
        self.assertEqual(record["total"]["score"], 71)
        part = report.build([report.entry(record, None, False)], {}, "2026-10-29T09:30:00+08:00", VOCABULARY)
        _, numerator, denominator = report.working(record)
        shown = report._decimal(numerator / denominator)
        self.assertEqual(shown, "71.498575…")
        self.assertIn(f"= {shown}。总分由这个精确值直接四舍五入为 <strong>71</strong>", part)
        self.assertNotIn("71.50", part)

    def test_scored_dimensions_that_weigh_nothing(self):
        record, part = self.rescored_with({"skills": 0, "direction": 0, "experience": 100, "salary": 0, "location": 0})
        self.assertIsNone(record["total"]["score"])
        self.assertIn("÷ 已评分维度的权重之和 0：已评分维度的权重之和为 0", part)
        self.assertIn("权重大于 0 的维度", part)
        self.assertNotIn("没有一个维度有分数", part)

    def test_each_section_matches_match_show(self):
        result, page, _ = self.generate()
        self.assertEqual(result["jobs"], len(SAMPLES))
        self.assertEqual(result["stale"], [])
        names = report._experience_names(self.profile)
        for sample, job_id in self.ids.items():
            with self.subTest(sample=sample):
                record, part = self.cli("match", "show", job_id), self.section(page, job_id)
                text = html.unescape(part)
                hard = html.unescape(part[part.index("<h3>硬性条件</h3>"):part.index("<h3>各维度</h3>")])
                dims = part[part.index("<h3>各维度</h3>"):part.index("<h3>总分怎么算</h3>")]
                total = record["total"]
                self.assertIn(report.conclusion(record), text)
                self.assertIn(f"四舍五入为 <strong>{total['score']}</strong>", part)
                for check in record["filter"]["checks"]:
                    self.assertIn(check["reason"], hard)
                    self.assertIn(report.RESULTS[check["result"]], hard)
                    for field in check["jd"].values():
                        for quote in [field["evidence"]] if isinstance(field["evidence"], str) else field["evidence"] or []:
                            self.assertIn(quote, hard)
                for key, dimension in record["dimensions"].items():
                    shown = "—" if dimension["score"] is None else dimension["score"]
                    self.assertIn(f"<td>{report.DIMENSIONS[key]}</td><td class=\"num\">{shown}</td>", dims)
                    self.assertNotIn(f"<td>{key}</td>", part, "every table names a dimension in Chinese")
                    self.assertIn(dimension["reason"], html.unescape(dims))
                    for skill in dimension.get("missing") or []:
                        self.assertIn(skill, html.unescape(dims))
                    evidence = dimension.get("evidence") or {}
                    for quote in evidence.get("jd") or []:
                        self.assertIn(quote, html.unescape(dims))
                    for ref in evidence.get("profile") or []:
                        self.assertIn(names[ref], html.unescape(dims))
                self.assert_rule_grounds(record, self.cli("jd", "show", job_id), dims)
                gaps = html.unescape(part[part.index("<h3>缺口</h3>"):part.index("<h3>待确认</h3>")])
                for gap in record["gaps"]:
                    self.assertIn(gap["reason"] if gap["kind"] == "filter" else gap["item"], gaps)
                    if gap["jd"]:
                        self.assertIn(gap["jd"], gaps)
                if not record["gaps"]:
                    self.assertIn("没有列出的缺口", gaps)
                opened = html.unescape(part[part.index("<h3>待确认</h3>"):])
                for check in record["filter"]["checks"]:
                    if check["result"] == "unknown":
                        self.assertIn(check["reason"], opened)
                for key in total["missing"]:
                    self.assertIn(f"{report.DIMENSIONS[key]}维度", opened)
                if sample in COMPLETED:
                    self.assertEqual(record["dimensions"]["experience"]["method"], "agent")
                    self.assertIn("<td>Agent</td>", part)

    def test_an_unknown_interview_or_start_date_is_no_hard_condition(self):
        # Codex B's P2-6 in #73: boss_intern passes every hard condition for tech and states neither its
        # interview nor a start date. As in the filter, the conclusion says it meets the hard conditions;
        # the two unknowns are listed only under 待确认.
        _, page, form = self.generate()
        job_id = self.ids["jd/boss_intern.txt"]
        record = self.cli("match", "show", job_id)
        self.assertEqual(record["filter"]["verdict"], "eligible")
        unknown = {c["check"] for c in record["filter"]["checks"] if c["result"] == "unknown"}
        self.assertEqual(unknown, {"interview", "start_date"})
        said = report.conclusion(record)
        self.assertTrue(said.startswith("符合硬性条件，"), said)
        self.assertNotIn("面试", said)
        part = html.unescape(self.section(page, job_id))
        self.assertIn(f"<strong>结论：</strong>{said}</p>", part)
        self.assertNotIn("待确认 2 项硬性条件", page)
        opened = part[part.index("<h3>待确认</h3>"):]
        for check in record["filter"]["checks"]:
            if check["check"] in unknown:
                self.assertIn(check["reason"], opened)
        rows = {row[0]: row for row in csv.reader(io.StringIO(form.decode("utf-8-sig")))}
        self.assertEqual(rows[job_id][5], said)
        # A hard condition still unknown is still counted, beside the two that are only to confirm.
        record["filter"]["verdict"] = "needs_check"
        record["filter"]["checks"][0]["result"] = "unknown"
        first = report.CHECKS[record["filter"]["checks"][0]["check"]]
        self.assertTrue(report.conclusion(record).startswith(f"待确认 1 项硬性条件（{first}），"))

    def test_the_working_gives_the_saved_total(self):
        for job_id in self.ids.values():
            record = self.cli("match", "show", job_id)
            _, numerator, denominator = report.working(record)
            self.assertEqual(score._round(numerator / denominator), record["total"]["score"])

    def test_the_ranking_is_match_list_order(self):
        _, page, form = self.generate()
        listed = [row["job_id"] for row in self.cli("match", "list")["matches"]]
        ranking = page[page.index('id="ranking"'):page.index("<section")]
        self.assertEqual(re.findall(r'href="#(job_[0-9a-f]+)"', ranking), listed)
        rows = list(csv.reader(io.StringIO(form.decode("utf-8-sig"))))
        self.assertEqual([row[0] for row in rows[1:]], listed)
        self.assertEqual(re.findall(r'<section id="(job_[0-9a-f]+)">', page), listed)

    def test_the_feedback_form(self):
        _, _, form = self.generate()
        self.assertTrue(form.startswith(b"\xef\xbb\xbf"), "UTF-8 with a BOM, so Excel and WPS read it")
        self.assertNotIn(b"\xef\xbb\xbf", form[3:])
        text = form[3:].decode("utf-8")
        self.assertEqual(text.count("\r\n"), len(SAMPLES) + 1)
        self.assertNotIn("\n", text.replace("\r\n", ""))
        header, *rows = csv.reader(io.StringIO(text))
        self.assertEqual(tuple(header), report.FEEDBACK_HEADER)
        for row in rows:
            record = self.cli("match", "show", row[0])
            job = self.cli("jd", "show", row[0])
            self.assertEqual(row[1:3], [job["title"] or "", job["company"] or ""])
            self.assertEqual(row[3], report.grade_text(record["total"]["grade"]))
            self.assertEqual(row[4], str(record["total"]["score"]))
            self.assertEqual(row[5], report.conclusion(record))
            self.assertEqual(row[6:], ["", "", ""])

    def test_no_contact_details(self):
        _, page, form = self.generate()
        contact = self.profile["contact"]
        for value in (contact["name"], contact["phone"], contact["email"], contact["github"]):
            with self.subTest(value=value):
                self.assertNotIn(value, page)
                self.assertNotIn(value, form.decode("utf-8-sig"))

    def test_a_changed_profile_marks_every_record_stale(self):
        changed = copy.deepcopy(self.profile)
        changed["availability"]["days_per_week"] = 3
        (self.data / "profile" / "profile.json").write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
        result, page, form = self.generate()
        self.assertEqual(sorted(result["stale"]), sorted(self.ids.values()))
        self.assertIn("条记录已过期", page)
        for job_id in self.ids.values():
            # The rule dimensions quote today's job, which may not be what was scored.
            self.assertIn("依据可能已变，请先重新评分", self.section(page, job_id))
        for row in list(csv.reader(io.StringIO(form.decode("utf-8-sig"))))[1:]:
            self.assertTrue(row[5].startswith("已过期，先重新评分。"))

    def test_named_jobs_only(self):
        job_id = self.ids["jd/official_site.txt"]
        result, page, _ = self.generate(job_id, job_id)
        self.assertEqual(result["jobs"], 1)
        self.assertEqual(re.findall(r'<section id="(job_[0-9a-f]+)">', page), [job_id])

    def test_the_page_loads_nothing_from_outside(self):
        _, page, _ = self.generate()
        for pattern in ("<script", "<link", "<img", "<iframe", "src=", "url(", "@import"):
            self.assertNotIn(pattern, page.lower())
        self.assertTrue(all(href.startswith("#") for href in re.findall(r'href="([^"]*)"', page)))

    def test_it_only_reads(self):
        def snapshot():
            return {path: path.read_bytes() for path in sorted(self.data.rglob("*"))
                    if path.is_file() and "reports" not in path.relative_to(self.data).parts}

        before = snapshot()
        self.generate()
        self.assertEqual(snapshot(), before)

    def test_each_report_gets_its_own_directory(self):
        first, second = self.cli("match", "report"), self.cli("match", "report")
        self.assertNotEqual(Path(first["report"]).parent, Path(second["report"]).parent)
        self.assertEqual(Path(first["report"]).parent.parent, self.data / "reports")
        with tempfile.TemporaryDirectory() as root:
            made = [cli._report_dir(Path(root), NOW) for _ in range(3)]
        self.assertEqual([path.name for path in made], ["20261029-093000", "20261029-093000-2", "20261029-093000-3"])

    def test_errors(self):
        self.cli("match", "report", "job_000000000000", expect=1)
        self.cli("match", "report", "not-an-id", expect=2)
        shutil.rmtree(self.data / "matches")
        self.assertIn("no saved match records", self.cli("match", "report", expect=1)["error"])


class FormAndPage(unittest.TestCase):
    """report.py on hand-made records: CSV escaping, HTML escaping, how what is open gets settled."""

    @staticmethod
    def record(**changes) -> dict:
        record = {
            "job_id": "job_0123456789ab",
            "filter": {"verdict": "eligible", "checks": []},
            "dimensions": {key: {"score": 50, "method": "rule", "reason": "r"} for key in score.DIMENSIONS},
            "weights": dict(score.DEFAULT_WEIGHTS),
            "total": {"score": 50, "grade": "moderate", "complete": True, "missing": []},
            "gaps": [],
        }
        record.update(changes)
        return record

    def test_numbers_are_cut_not_rounded(self):
        cases = {Fraction(5, 2): "2.5", Fraction(35): "35", Fraction(1, 3): "0.333333…",
                 Fraction(1999999, 4000000): "0.499999…", Fraction("1.0001"): "1.0001", Fraction(2, 3): "0.666666…"}
        for value, shown in cases.items():
            with self.subTest(value=value):
                self.assertEqual(report._decimal(value), shown)
        self.assertEqual(report._decimal(12.5), "12.5")

    def test_commas_quotes_and_line_breaks_round_trip(self):
        job = {"title": '数据分析实习生, "急招"\n可转正', "company": "示例,公司"}
        text = report.feedback_csv([report.entry(self.record(), job, False)])
        [_, row] = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
        self.assertEqual(row[1:3], [job["title"], job["company"]])
        self.assertIn('"数据分析实习生, ""急招""\n可转正"', text)

    def test_a_title_that_looks_like_a_formula_stays_text(self):
        for title in ("=HYPERLINK(\"x\")", "+1", "-1", "@SUM(A1)"):
            with self.subTest(title=title):
                text = report.feedback_csv([report.entry(self.record(), {"title": title, "company": None}, False)])
                [_, row] = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
                self.assertEqual(row[1], "'" + title)

    def test_a_formula_behind_a_line_break_or_blanks_stays_text(self):
        # V18 P2-4: an importer may skip leading whitespace and control characters, so the guard looks past them.
        for title in ("\n=SUM(1,1)", " =1", "\x1b=1", "　+1", "\r\n@x", "\t-1"):
            with self.subTest(title=title):
                text = report.feedback_csv([report.entry(self.record(), {"title": title, "company": None}, False)])
                [_, row] = list(csv.reader(io.StringIO(text.lstrip("﻿"), newline="")))
                self.assertEqual(row[1], "'" + title)
        cells = ("\x00=1", "\nplain", "a=1", " 数据分析", "")
        self.assertEqual([report._cell(v) for v in cells], ["'\x00=1", "'\nplain", "a=1", " 数据分析", ""])

    def test_no_cell_starts_a_formula(self):
        # Every column passes the guard, not just the title: the company comes from the JD too.
        job = {"title": "=1+1", "company": "@公司"}
        text = report.feedback_csv([report.entry(self.record(), job, True)])
        for row in csv.reader(io.StringIO(text.lstrip("﻿"))):
            for cell in row:
                self.assertNotIn(cell[:1], ("=", "+", "-", "@", "\t", "\r", "\n"), row)
        self.assertEqual([report._cell(v) for v in ("-5", "\tx", None, 7)], ["'-5", "'\tx", "", "7"])

    def test_the_grade_names_are_the_ones_in_match_md(self):
        # match.md holds the one table of grade names; the report must not drift from it.
        text = (REPO / "docs" / "cn" / "match.md").read_text(encoding="utf-8")
        start = text.index("- **等级**")
        text = text[start:text.index("\n- **", start + 1)]
        table = dict(re.findall(r"^\s*\| `(\w+)` \| ([^|]+?) \|", text, re.M))
        self.assertEqual(table, report.GRADES)
        self.assertEqual(set(table), {name for name, _ in score.GRADES} | {score.INELIGIBLE})
        legend = report._legend()
        for name, floor in score.GRADES:
            self.assertIn(f"{report.GRADES[name]}（{name}）", legend)
        self.assertIn("很匹配（strong）≥ 75", legend)
        self.assertIn("不匹配（poor）< 30", legend)

    def test_jd_text_is_escaped(self):
        job = {"title": "<script>alert(1)</script>", "company": "A&B"}
        page = report.build([report.entry(self.record(), job, False)], {}, "2026-10-29T09:30:00+08:00", VOCABULARY)
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("A&amp;B", page)

    def test_how_to_settle_what_is_open(self):
        checks = [
            {"check": "graduation", "result": "unknown", "reason": "JD 没写届别；你是 2027 届"},
            {"check": "days_per_week", "result": "unknown", "reason": "JD 要求每周到岗 4 天；档案没写每周能到岗几天"},
            {"check": "min_months", "result": "unknown", "reason": "JD 没写实习时长要求；档案没写能实习几个月"},
            {"check": "education", "result": "match", "reason": "最高学历硕士，满足本科及以上"},
        ]
        dimensions = {key: {"score": None, "method": "rule", "reason": "r"} for key in score.DIMENSIONS}
        record = self.record(filter={"verdict": "needs_check", "checks": checks}, dimensions=dimensions,
                             total={"score": None, "grade": None, "complete": False, "missing": list(score.DIMENSIONS)})
        job = {"salary": {"min": None, "max": None, "unit": None, "negotiable": True}}
        profile = {"experience": [{"id": "exp-1"}], "target": {"directions": [], "salary_min": None}}
        how = {item: settle for item, _, settle in report.pending(record, job, profile)}
        self.assertEqual(how, {
            "届别": report.ASK_JD,
            "每周到岗": report.FILL_PROFILE,
            "实习时长": f"{report.ASK_JD}；{report.FILL_PROFILE}",
            "技能维度": report.ASK_JD,
            "方向维度": report.FILL_PROFILE,
            "经历维度": report.ASK_AGENT,
            "薪资维度": "问 HR 薪资范围",
            "地点维度": f"{report.ASK_JD}；{report.FILL_PROFILE}",  # neither side names a city
        })
        unit = {"salary": {"min": 5000, "max": 8000, "unit": "CNY/month", "negotiable": False}}
        wanted = {"target": {"salary_min": {"amount": 150, "unit": "CNY/day"}}}
        self.assertIn("单位", report._settle("salary", unit, wanted))
        self.assertEqual(report._settle("salary", unit, {"target": {}}), report.FILL_PROFILE)
        acceptable = {"availability": {"cities": [], "acceptable_cities": ["杭州"]}}
        self.assertEqual(report._settle("location", {"cities": []}, acceptable), report.ASK_JD)
        self.assertEqual(report._settle("location", {"cities": ["杭州"]}, {"availability": {}}), report.FILL_PROFILE)

    def test_every_dimension_has_a_chinese_name(self):
        self.assertEqual(list(report.DIMENSIONS), list(score.DIMENSIONS))
        page = report.build([report.entry(self.record(), None, False)], {}, "2026-10-29T09:30:00+08:00", VOCABULARY)
        for key, name in report.DIMENSIONS.items():
            with self.subTest(key=key):
                self.assertEqual(page.count(f"<td>{name}</td>"), 2, "the dimensions and the working of the total")
                self.assertNotIn(f"<td>{key}</td>", page)

    def test_conclusions(self):
        conflict = {"check": "location", "result": "conflict", "reason": "x"}
        ineligible = self.record(filter={"verdict": "ineligible", "checks": [conflict]},
                                 total={"score": 46, "grade": "ineligible", "complete": False, "missing": ["salary"]})
        self.assertEqual(report.conclusion(ineligible), "不符合硬性条件（冲突：地点），各维度加权 46 分，仅供参考；缺薪资维度")
        self.assertEqual(report.conclusion(self.record(), stale=True), "已过期，先重新评分。符合硬性条件，一般（moderate），总分 50 分")


def setting(data: dict, path: str, value) -> dict:
    data = copy.deepcopy(data)
    *parents, leaf = path.split(".")
    target = data
    for part in parents:
        target = target[part]
    target[leaf] = value
    return data


class ReasonWording(unittest.TestCase):
    """The report tells the user whether to ask about the job or fill in the profile by reading the
    filter's reasons for "JD 没写" and "档案没写" (the wording H17 fixed). Pin that, check by check, so
    a rewording fails here instead of quietly sending the user to the wrong place."""

    # check -> (JD field left unstated, profile field left unstated or None when the profile cannot be the gap)
    SILENT = {
        "graduation": (("requirements.graduation", None), ("graduation.year", None)),
        "education": (("requirements.education.min", None), ("education", [])),
        "days_per_week": (("requirements.days_per_week", None), ("availability.days_per_week", None)),
        "min_months": (("requirements.min_months", None), ("availability.months", None)),
        "location": (("cities", []), ("availability.cities", [])),
        "employment_type": (("employment_type", None), ("target.employment_types", [])),
        "exclusions": (("title", None), None),
        "interview": (("interview", None), None),
        "start_date": (("requirements.start", None), ("availability.start_date", None)),
    }
    # What the JD must state for the profile to be the only gap.
    STATED = {"start_date": ("requirements.start", {"by": "2026-12-31", "asap": False})}
    # Unknowns where the JD says something, but not enough: still the JD to read, then HR to ask.
    VAGUE = {
        "interview": ("interview", {"mode": "onsite", "cities": []}),
        "start_date": ("requirements.start", {"by": None, "asap": True}),
    }

    def setUp(self):
        sample = (FIXTURES / "jd" / "boss_intern.txt").read_text(encoding="utf-8")
        [self.job], _ = jd_parser.parse_text(sample, now=NOW)
        self.profile = json.loads((FIXTURES / "profile" / "tech" / "profile.json").read_text(encoding="utf-8"))

    def advice(self, job, profile, check):
        result = next(c for c in match.filter_job(job, profile)["checks"] if c["check"] == check)
        self.assertEqual(result["result"], match.UNKNOWN, result["reason"])
        record = {"filter": {"verdict": match.NEEDS_CHECK, "checks": [result]},
                  "total": {"missing": []}, "dimensions": {}}
        [(_, reason, how)] = report.pending(record, job, profile)
        return reason, how

    def test_every_check_is_covered(self):
        self.assertEqual(set(self.SILENT), set(match.CHECKS))

    def test_a_silent_jd_sends_the_user_to_the_jd(self):
        for check, (jd_side, _) in self.SILENT.items():
            with self.subTest(check=check):
                reason, how = self.advice(setting(self.job, *jd_side), self.profile, check)
                self.assertIn("JD 没写", reason)
                self.assertNotIn("档案没写", reason)
                self.assertEqual(how, report.ASK_JD)

    def test_a_silent_profile_sends_the_user_to_the_profile(self):
        for check, (_, profile_side) in self.SILENT.items():
            if profile_side is None:
                continue
            with self.subTest(check=check):
                job = setting(self.job, *self.STATED[check]) if check in self.STATED else self.job
                reason, how = self.advice(job, setting(self.profile, *profile_side), check)
                self.assertIn("档案没写", reason)
                self.assertNotIn("JD 没写", reason)
                self.assertEqual(how, report.FILL_PROFILE)

    def test_a_vague_jd_sends_the_user_to_the_jd(self):
        for check, jd_side in self.VAGUE.items():
            with self.subTest(check=check):
                reason, how = self.advice(setting(self.job, *jd_side), self.profile, check)
                self.assertIn("JD 没写", reason)
                self.assertNotIn("档案没写", reason)
                self.assertEqual(how, report.ASK_JD)

    def test_a_null_location_sends_the_user_to_the_side_without_a_city(self):
        # M2-6b: the location dimension is null when the JD names no city, or the profile neither tier.
        cases = {"JD 没写工作城市": (setting(self.job, "cities", []), self.profile, report.ASK_JD),
                 "档案没写意向城市": (self.job, setting(self.profile, "availability.cities", []), report.FILL_PROFILE)}
        for reason, (job, profile, how) in cases.items():
            with self.subTest(reason=reason):
                record = score.score_job(job, profile, VOCABULARY, now=NOW)
                location = record["dimensions"]["location"]
                self.assertEqual((location["score"], location["reason"]), (None, reason))
                self.assertIn(("地点维度", reason, how), report.pending(record, job, profile))


if __name__ == "__main__":
    unittest.main()
