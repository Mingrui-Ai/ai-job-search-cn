"""The two agent entry points (ADR-7) stay thin and agree with the CLI.

Claude Code's cn-jd-import skill and Codex's AGENTS.md both point at one
workflow, docs/cn/jd-import.md. These pin that both point there, that every
`jd` command the workflow tells an agent to run exists, and that the one Bash
grant the skill carries is registered in both permission allowlists.
"""
import contextlib
import io
import json
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = "docs/cn/jd-import.md"
SKILL = REPO / ".claude" / "skills" / "cn-jd-import" / "SKILL.md"
GRANT = "Bash(python -m jobsearch_cn jd:*)"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))
from jobsearch_cn import cli  # noqa: E402
import security_guards  # noqa: E402


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class EntryPoints(unittest.TestCase):
    def test_both_runtimes_point_at_the_one_workflow(self):
        self.assertTrue((REPO / WORKFLOW).is_file())
        self.assertIn(WORKFLOW, read(SKILL))
        self.assertIn(WORKFLOW, read(REPO / "AGENTS.md"))

    def test_the_skill_stays_a_thin_pointer(self):
        body = read(SKILL).split("---", 2)[2]
        self.assertNotIn("python -m jobsearch_cn", body, "commands belong in the shared workflow")
        self.assertLess(len(body.strip().splitlines()), 15)

    def test_the_skill_grant_is_in_both_allowlists(self):
        frontmatter = read(SKILL).split("---", 2)[1]
        self.assertIn(GRANT, frontmatter)
        self.assertIn(GRANT, security_guards.ALLOWED_PERMISSIONS)
        self.assertIn(GRANT, security_guards.ALLOWED_SKILL_TOOLS)
        allow = json.loads(read(REPO / ".claude" / "settings.json"))["permissions"]["allow"]
        self.assertIn(GRANT, allow)

    def test_every_command_in_the_workflow_exists(self):
        parser = cli.build_parser()
        used = set(re.findall(r"python -m jobsearch_cn jd (\w+)", read(REPO / WORKFLOW)))
        self.assertTrue({"parse", "save", "show", "list", "status", "validate"} <= used)
        for command in used:
            with self.subTest(command=command):
                with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(io.StringIO()):
                    parser.parse_args(["jd", command, "--help"])
                self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
