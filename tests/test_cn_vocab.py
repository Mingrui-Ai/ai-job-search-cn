"""Tests for jobsearch_cn/vocab.py and the skill vocabulary in jd parse.

The vocabulary moved out of the parser into jobsearch_cn/skills.json (M2-3) so
that it is grouped by job direction and a user can extend it without touching
code. These pin the built-in groups, that a user file only ever adds, that a
malformed file fails loudly instead of being half-read, and that jd parse
reads the user's terms from the data directory.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO))
from jobsearch_cn import jd_parser, schema, store, vocab  # noqa: E402

GROUPS = ("tech", "data", "product", "ops", "design")


class Builtin(unittest.TestCase):
    def setUp(self):
        self.vocabulary = vocab.load()

    def test_the_five_directions_with_chinese_labels(self):
        self.assertEqual(tuple(self.vocabulary.groups), GROUPS)
        labels = [g["label"] for g in self.vocabulary.groups.values()]
        self.assertEqual(labels, ["技术", "数据", "产品", "运营", "设计"])
        for key in GROUPS:
            self.assertGreaterEqual(len(self.vocabulary.groups[key]["terms"]), 5, key)

    def test_no_term_is_listed_twice_even_across_groups(self):
        folded = [schema.normalize_for_match(t) for t in self.vocabulary.terms]
        self.assertEqual(len(folded), len(set(folded)))

    def test_every_term_still_found_by_the_parser(self):
        # Each term must be readable in a sentence of its own, so a typo or a
        # pattern the matcher cannot express does not sit in the file unused.
        for term in self.vocabulary.terms:
            with self.subTest(term=term):
                [record], _ = jd_parser.parse_text(f"任职要求：熟悉{term}。", vocabulary=self.vocabulary)
                self.assertIn(term, record["requirements"]["skills"])

    def test_group_of(self):
        self.assertEqual(self.vocabulary.group_of("python"), "tech")
        self.assertEqual(self.vocabulary.group_of("Ｅｘｃｅｌ"), "data")
        self.assertEqual(self.vocabulary.group_of("公众号"), "ops")
        self.assertEqual(self.vocabulary.group_of("Figma"), "design")
        self.assertEqual(self.vocabulary.group_of("PRD"), "product")
        self.assertIsNone(self.vocabulary.group_of("打篮球"))


class UserFile(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name)
        (self.data / "config").mkdir()

    def write(self, doc):
        text = doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False)
        (self.data / "config" / "skills.json").write_text(text, encoding="utf-8")

    def test_no_user_file_is_the_builtin(self):
        self.assertEqual(vocab.load(self.data).terms, vocab.load().terms)

    def test_terms_extend_a_group_and_a_new_group_is_added(self):
        self.write({"version": 1, "groups": {"ops": {"terms": ["私域运营"]},
                                             "game": {"label": "游戏", "terms": ["Unity"]}}})
        vocabulary = vocab.load(self.data)
        self.assertEqual(vocabulary.group_of("私域运营"), "ops")
        self.assertEqual(vocabulary.groups["game"], {"label": "游戏", "terms": ["Unity"]})
        self.assertEqual(vocabulary.groups["ops"]["label"], "运营")

    def test_a_user_cannot_remove_or_move_a_builtin_term(self):
        self.write({"version": 1, "groups": {"design": {"terms": ["Python"]}, "tech": {"terms": []}}})
        vocabulary = vocab.load(self.data)
        self.assertEqual(vocabulary.group_of("Python"), "tech")
        self.assertEqual(vocabulary.terms.count("Python"), 1)
        self.assertTrue(set(vocab.load().terms) <= set(vocabulary.terms))

    def test_malformed_files_fail_loudly(self):
        bad = [
            "{not json",
            {"groups": {}},
            {"version": 2, "groups": {}},
            {"version": 1, "groups": {"Ops!": {"terms": []}}},
            {"version": 1, "groups": {"ops": ["私域运营"]}},
            {"version": 1, "groups": {"ops": {"terms": [" 私域运营"]}}},
            {"version": 1, "groups": {"ops": {"terms": [""]}}},
            {"version": 1, "groups": {"ops": {"terms": ["x" * 51]}}},
            {"version": 1, "groups": {"ops": {"label": "", "terms": []}}},
        ]
        for doc in bad:
            with self.subTest(doc=doc):
                self.write(doc)
                with self.assertRaises(vocab.VocabularyError):
                    vocab.load(self.data)

    def test_a_bom_from_notepad_is_fine(self):
        doc = json.dumps({"version": 1, "groups": {"ops": {"terms": ["私域运营"]}}}, ensure_ascii=False)
        (self.data / "config" / "skills.json").write_bytes(b"\xef\xbb\xbf" + doc.encode("utf-8"))
        self.assertEqual(vocab.load(self.data).group_of("私域运营"), "ops")

    def test_the_parser_reads_user_terms_and_cites_them(self):
        self.write({"version": 1, "groups": {"ops": {"terms": ["私域运营"]}}})
        [record], _ = jd_parser.parse_text("负责私域运营和社群运营。", vocabulary=vocab.load(self.data))
        self.assertEqual(record["requirements"]["skills"], ["私域运营", "社群运营"])
        self.assertEqual(schema.validate(record), [])
        [plain], _ = jd_parser.parse_text("负责私域运营和社群运营。")
        self.assertEqual(plain["requirements"]["skills"], ["社群运营"])


def run_cli(*args, data_dir):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", **{store.DATA_DIR_ENV: str(data_dir)})
    return subprocess.run([sys.executable, "-m", "jobsearch_cn", *args], cwd=REPO, env=env, capture_output=True)


class Command(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name)
        (self.data / "config").mkdir()
        self.jd = self.data / "jd.txt"
        self.jd.write_text("新媒体运营实习生\n负责私域运营。", encoding="utf-8")

    def test_jd_parse_uses_the_data_dir_vocabulary(self):
        (self.data / "config" / "skills.json").write_text(
            json.dumps({"version": 1, "groups": {"ops": {"terms": ["私域运营"]}}}, ensure_ascii=False),
            encoding="utf-8")
        proc = run_cli("jd", "parse", str(self.jd), data_dir=self.data)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8"))
        self.assertEqual(json.loads(proc.stdout)["jobs"][0]["requirements"]["skills"], ["新媒体运营", "私域运营"])

    def test_a_broken_vocabulary_is_an_input_error(self):
        (self.data / "config" / "skills.json").write_text("{oops", encoding="utf-8")
        proc = run_cli("jd", "parse", str(self.jd), data_dir=self.data)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("skills.json", proc.stderr.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
