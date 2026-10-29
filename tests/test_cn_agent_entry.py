"""The agent entry points (ADR-7) stay thin and agree with the CLI.

For each CN workflow, Claude Code's skill and Codex's AGENTS.md both point at
one document under docs/cn/. These pin that both point there, that every
command the document tells an agent to run exists, and that the one Bash grant
each skill carries is registered in both permission allowlists.
"""
import contextlib
import io
import json
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# skill name -> (workflow document, command group, commands it must document)
WORKFLOWS = {
    "cn-jd-import": ("docs/cn/jd-import.md", "jd", {"parse", "save", "show", "list", "status", "validate"}),
    "cn-setup": ("docs/cn/profile-setup.md", "profile", {"validate", "show"}),
    "cn-match": ("docs/cn/match.md", "match", {"score", "validate", "save", "show", "list"}),
}

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))
from jobsearch_cn import cli  # noqa: E402
import security_guards  # noqa: E402


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class EntryPoints(unittest.TestCase):
    def each(self):
        for skill, (workflow, group, commands) in WORKFLOWS.items():
            with self.subTest(skill=skill):
                yield REPO / ".claude" / "skills" / skill / "SKILL.md", workflow, group, commands

    def test_both_runtimes_point_at_the_one_workflow(self):
        for skill, workflow, _, _ in self.each():
            self.assertTrue((REPO / workflow).is_file())
            self.assertIn(workflow, read(skill))
            self.assertIn(workflow, read(REPO / "AGENTS.md"))

    def test_the_skill_stays_a_thin_pointer(self):
        for skill, _, _, _ in self.each():
            body = read(skill).split("---", 2)[2]
            self.assertNotIn("python -m jobsearch_cn", body, "commands belong in the shared workflow")
            self.assertLess(len(body.strip().splitlines()), 15)

    def test_the_skill_grant_is_in_both_allowlists(self):
        allow = json.loads(read(REPO / ".claude" / "settings.json"))["permissions"]["allow"]
        for skill, _, group, _ in self.each():
            grant = f"Bash(python -m jobsearch_cn {group}:*)"
            self.assertIn(grant, read(skill).split("---", 2)[1])
            self.assertIn(grant, security_guards.ALLOWED_PERMISSIONS)
            self.assertIn(grant, security_guards.ALLOWED_SKILL_TOOLS)
            self.assertIn(grant, allow)

    def test_every_command_in_the_workflow_exists(self):
        parser = cli.build_parser()
        for _, workflow, group, required in self.each():
            used = set(re.findall(rf"python -m jobsearch_cn {group} (\w+)", read(REPO / workflow)))
            self.assertTrue(required <= used, f"{workflow} should document {sorted(required - used)}")
            for command in used:
                with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(io.StringIO()):
                    parser.parse_args([group, command, "--help"])
                self.assertEqual(raised.exception.code, 0, f"{group} {command}")


if __name__ == "__main__":
    unittest.main()
