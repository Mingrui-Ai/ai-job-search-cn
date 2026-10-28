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

GROUPS = ("tech", "data", "product", "ops", "design", "market", "finance", "hr", "general")


class Builtin(unittest.TestCase):
    def setUp(self):
        self.vocabulary = vocab.load()

    def test_the_groups_with_chinese_labels(self):
        self.assertEqual(tuple(self.vocabulary.groups), GROUPS)
        labels = [g["label"] for g in self.vocabulary.groups.values()]
        self.assertEqual(labels, ["技术", "数据", "产品", "运营", "设计", "市场", "财务", "人力资源", "通用"])
        for key in GROUPS[:5]:
            self.assertGreaterEqual(len(self.vocabulary.groups[key]["terms"]), 5, key)
        # market and general (office software every direction uses) start small.
        self.assertEqual(self.vocabulary.groups["general"]["terms"], ["Excel", "PowerPoint", "PPT"])
        self.assertIn("市场调研", self.vocabulary.groups["market"]["terms"])

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
        self.assertEqual(self.vocabulary.group_of("Ｅｘｃｅｌ"), "general")
        self.assertEqual(self.vocabulary.group_of("公众号"), "ops")
        self.assertEqual(self.vocabulary.group_of("Figma"), "design")
        self.assertEqual(self.vocabulary.group_of("PRD"), "product")
        self.assertEqual(self.vocabulary.group_of("商务沟通"), "market")
        # From the V4 samples (H9): finance and HR JDs count as their own directions.
        self.assertEqual(self.vocabulary.group_of("财务分析"), "finance")
        self.assertEqual(self.vocabulary.group_of("招聘流程"), "hr")
        self.assertEqual(self.vocabulary.group_of("CRM"), "market")
        self.assertEqual(self.vocabulary.group_of("数据清洗"), "data")
        self.assertIsNone(self.vocabulary.group_of("打篮球"))

    def test_content_forms_are_not_skills_on_their_own(self):
        # A skill is written in full, as a JD asks for it: 文案写作, 短视频运营.
        for term in ("文案", "短视频", "直播"):
            self.assertIsNone(self.vocabulary.group_of(term), term)
        for term in ("文案写作", "短视频运营", "直播运营"):
            self.assertEqual(self.vocabulary.group_of(term), "ops", term)

    def test_synonyms_are_one_skill_to_matching(self):
        pairs = (("K8s", "kubernetes"), ("Golang", "Go"), ("NLP", "自然语言处理"), ("JS", "JavaScript"),
                 ("PPT", "PowerPoint"), ("文案撰写", "文案写作"), ("Ｐｙｔｈｏｎ", "python"))
        for a, b in pairs:
            with self.subTest(a=a, b=b):
                self.assertTrue(self.vocabulary.same(a, b))
                self.assertEqual(self.vocabulary.key(a), self.vocabulary.key(b))
        self.assertFalse(self.vocabulary.same("Go", "Java"))
        self.assertFalse(self.vocabulary.same("大模型", "LLM"))  # close, but not listed as the same skill
        self.assertEqual(self.vocabulary.key("打篮球"), "打篮球")

    def test_every_synonym_is_a_term_and_shares_its_group(self):
        self.assertGreaterEqual(len(self.vocabulary.same_as), 6)
        for entry in self.vocabulary.same_as:
            with self.subTest(entry=entry):
                groups = [self.vocabulary.group_of(term) for term in entry]
                self.assertNotIn(None, groups)
                self.assertEqual(len(set(groups)), 1)


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
            {"version": 1, "groups": {}, "sameAs": [["K8s", "Kubernetes"]]},
            {"version": 1, "groups": {}, "same_as": {"K8s": "Kubernetes"}},
            {"version": 1, "groups": {}, "same_as": [["K8s"]]},
            {"version": 1, "groups": {}, "same_as": [["K8s", "k8s"]]},
            {"version": 1, "groups": {}, "same_as": [["K8s", "容器编排"]]},
            {"version": 1, "groups": {}, "same_as": [["Python", "Excel"]]},
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

    def test_user_synonyms_add_and_join_the_builtin_ones(self):
        self.write({"version": 1,
                    "groups": {"ops": {"terms": ["私域运营", "私域流量运营"]}, "tech": {"terms": ["Kube"]}},
                    "same_as": [["私域运营", "私域流量运营"], ["Kube", "K8s"]]})
        vocabulary = vocab.load(self.data)
        self.assertTrue(vocabulary.same("私域流量运营", "私域运营"))
        self.assertTrue(vocabulary.same("Kube", "Kubernetes"))  # joined the built-in Kubernetes / K8s entry
        self.assertEqual([entry for entry in vocabulary.same_as if "K8s" in entry], [["Kubernetes", "K8s", "Kube"]])
        self.assertEqual(len(vocabulary.same_as), len(vocab.load().same_as) + 1)

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
        # 新媒体运营 is only in the title, and skills are read from the body.
        self.assertEqual(json.loads(proc.stdout)["jobs"][0]["requirements"]["skills"], ["私域运营"])

    def test_a_broken_vocabulary_is_an_input_error(self):
        (self.data / "config" / "skills.json").write_text("{oops", encoding="utf-8")
        proc = run_cli("jd", "parse", str(self.jd), data_dir=self.data)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("skills.json", proc.stderr.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
