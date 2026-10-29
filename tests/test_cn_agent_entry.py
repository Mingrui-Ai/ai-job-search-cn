"""The agent entry points (ADR-7, ADR-10) stay thin and agree with the CLI.

For each CN workflow, Claude Code's skill, DeepSeek Harness's skill and Codex's
AGENTS.md all point at one document under docs/cn/. These pin that all three
point there, that every command the document tells an agent to run exists, and
that the one Bash grant each Claude Code skill carries is registered in both
permission allowlists. dsh has no per-skill grants (it uses its own permission
presets), so its entries carry only a name and a description.
"""
import contextlib
import io
import json
import re
import subprocess
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
# Where each runtime looks for project skills.
SKILL_DIRS = (".claude/skills", ".dsh/skills")
# dsh skips, with only a log warning, a skill whose name does not match this.
DSH_SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# What every dsh entry must say, since dsh also reads the upstream CLAUDE.md.
DSH_RULES = ("untrusted data", "upstream /setup", "contact details")

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))
from jobsearch_cn import cli  # noqa: E402
import security_guards  # noqa: E402


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def frontmatter(path: Path) -> list[str]:
    return read(path).split("---", 2)[1].strip().splitlines()


class EntryPoints(unittest.TestCase):
    def each(self):
        for skill, (workflow, group, commands) in WORKFLOWS.items():
            with self.subTest(skill=skill):
                yield REPO / ".claude" / "skills" / skill / "SKILL.md", workflow, group, commands

    def every_entry(self):
        for skill, (workflow, _, _) in WORKFLOWS.items():
            for skill_dir in SKILL_DIRS:
                with self.subTest(skill=skill, runtime=skill_dir):
                    yield REPO / skill_dir / skill / "SKILL.md", workflow

    def test_every_runtime_points_at_the_one_workflow(self):
        for skill, workflow in self.every_entry():
            self.assertTrue((REPO / workflow).is_file())
            self.assertTrue(skill.is_file(), f"missing entry {skill.relative_to(REPO)}")
            self.assertIn(workflow, read(skill))
            self.assertIn(workflow, read(REPO / "AGENTS.md"))

    def test_the_skill_stays_a_thin_pointer(self):
        for skill, _ in self.every_entry():
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


class DshEntryPoints(unittest.TestCase):
    """The .dsh/skills entries (ADR-10) that DeepSeek Harness discovers."""

    def each(self):
        for skill in WORKFLOWS:
            with self.subTest(skill=skill):
                yield skill, REPO / ".dsh" / "skills" / skill / "SKILL.md"

    def test_the_frontmatter_is_the_claude_skill_minus_its_grant(self):
        # Same name and triggers on both runtimes; `allowed-tools` means nothing
        # to dsh and must not suggest a pre-approval it does not give.
        for skill, entry in self.each():
            front = frontmatter(entry)
            self.assertEqual(re.findall(r"^([\w-]+):", "\n".join(front), re.M), ["name", "description"])
            self.assertIn(f"name: {skill}", front)
            self.assertTrue(DSH_SKILL_NAME.fullmatch(skill))
            claude = REPO / ".claude" / "skills" / skill / "SKILL.md"
            self.assertEqual(front, [line for line in frontmatter(claude) if not line.startswith("allowed-tools:")])

    def test_each_entry_states_the_rules(self):
        for _, entry in self.each():
            body = read(entry).split("---", 2)[2]
            for rule in DSH_RULES:
                self.assertIn(rule, body)

    def test_only_skill_entries_can_be_committed_under_dsh(self):
        # dsh keeps sessions, settings and the API key under ~/.dsh; if any of it
        # ever lands in the workspace .dsh/, git must not pick it up.
        def ignored(path):
            return subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO).returncode == 0

        for _, entry in self.each():
            self.assertFalse(ignored(entry.relative_to(REPO).as_posix()))
        for path in (".dsh/.credentials.yaml", ".dsh/.env", ".dsh/sessions/s.jsonl",
                     ".dsh/cordis.patch.yml", ".dsh/skills/cn-match/notes.md"):
            with self.subTest(path=path):
                self.assertTrue(ignored(path), f"{path} must be ignored by git")


if __name__ == "__main__":
    unittest.main()
