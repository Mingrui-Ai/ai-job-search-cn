"""The agent entry points (ADR-7, ADR-10) stay thin and agree with the CLI.

For each CN workflow, Claude Code's skill, DeepSeek Harness's skill and Codex's
AGENTS.md all point at one document under docs/cn/. These pin that all three
point there, that every command the document tells an agent to run exists, and
that each Claude Code skill carries a Bash grant for exactly the command groups
its document uses, each registered in both permission allowlists. Review
subagents point at the same document and have no Edit, Write or web tools.
dsh has no per-skill grants (it uses its own permission
presets), so its entries carry only a name and a description. A changed
greeting, email or referral is rendered again, not built, before the next
review round, and every entry says so.
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
# skill name -> (workflow document, {command group: commands the document must use})
WORKFLOWS = {
    "cn-jd-import": ("docs/cn/jd-import.md", {"jd": {"parse", "save", "show", "list", "status", "validate"}}),
    "cn-setup": ("docs/cn/profile-setup.md", {"profile": {"validate", "show"}}),
    "cn-match": ("docs/cn/match.md", {"match": {"score", "validate", "save", "show", "list", "report"},
                                      "jd": {"list", "show"}, "profile": {"validate", "show"}}),
    "cn-resume": ("docs/cn/resume-workflow.md", {
        "material": {"validate", "template", "render"}, "resume": {"build"},
        "review": {"draft", "validate", "show"},
        "jd": {"list", "show"}, "profile": {"validate", "show"}, "match": {"list", "show"}}),
}
# Subagents a workflow dispatches: agent name -> the workflow document it follows.
REVIEWERS = {"cn-resume-reviewer": "docs/cn/resume-workflow.md"}
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
        for skill, (workflow, groups) in WORKFLOWS.items():
            with self.subTest(skill=skill):
                yield REPO / ".claude" / "skills" / skill / "SKILL.md", workflow, groups

    def every_entry(self):
        for skill, (workflow, _) in WORKFLOWS.items():
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
        for skill, _, groups in self.each():
            for group in groups:
                grant = f"Bash(python -m jobsearch_cn {group}:*)"
                self.assertIn(grant, read(skill).split("---", 2)[1])
                self.assertIn(grant, security_guards.ALLOWED_PERMISSIONS)
                self.assertIn(grant, security_guards.ALLOWED_SKILL_TOOLS)
                self.assertIn(grant, allow)

    def test_the_skill_grants_only_its_workflow_groups(self):
        for skill, _, groups in self.each():
            granted = set(re.findall(r"Bash\(python -m jobsearch_cn (\w+):\*\)", read(skill).split("---", 2)[1]))
            self.assertEqual(granted, set(groups))

    def test_every_command_in_the_workflow_exists(self):
        parser = cli.build_parser()
        for _, workflow, groups in self.each():
            text = read(REPO / workflow)
            for group, required in groups.items():
                used = set(re.findall(rf"python -m jobsearch_cn {group} (\w+)", text))
                self.assertTrue(required <= used, f"{workflow} should document {group} {sorted(required - used)}")
                for command in used:
                    with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(io.StringIO()):
                        parser.parse_args([group, command, "--help"])
                    self.assertEqual(raised.exception.code, 0, f"{group} {command}")

    def test_the_workflow_uses_no_other_command_group(self):
        for _, workflow, groups in self.each():
            used = set(re.findall(r"python -m jobsearch_cn (\w+)", read(REPO / workflow)))
            self.assertTrue(used <= set(groups), f"{workflow} uses {sorted(used - set(groups))} without a grant")


class ReviewerAgents(unittest.TestCase):
    """The review subagents (review-checklist.md §5.1): no Edit, Write or web tools, pointing at the workflow.
    Their Bash still runs whatever the allow list lets through, writing commands included; only the
    workflow text keeps them to the read ones, which these tests do not check."""

    def each(self):
        for name, workflow in REVIEWERS.items():
            with self.subTest(agent=name):
                yield REPO / ".claude" / "agents" / f"{name}.md", workflow

    def test_the_agent_points_at_the_workflow(self):
        for agent, workflow in self.each():
            self.assertIn(f"name: {agent.stem}", frontmatter(agent))
            self.assertIn(workflow, read(agent))

    def test_the_agent_has_no_edit_write_or_web_tools(self):
        for agent, _ in self.each():
            tools = next(line for line in frontmatter(agent) if line.startswith("tools:"))
            self.assertEqual({t.strip() for t in tools.split(":", 1)[1].split(",")}, {"Read", "Glob", "Grep", "Bash"})


class MessageDrafts(unittest.TestCase):
    """How a changed greeting, email or referral gets its text again (resume-workflow.md section 5). Codex B on
    #127 (0faf0ed): section 3 said to rerun resume build, which takes only a CV, so a changed greeting kept its
    old text file while a round-2 review of the new version still validated."""

    def section(self) -> str:
        return read(REPO / "docs/cn/resume-workflow.md").split("\n## 5.", 1)[1]

    def test_a_changed_message_is_rendered_again(self):
        step = re.search(r"^\d+\. \*\*修改\*\*.*$", self.section(), re.M).group(0)
        self.assertEqual(re.findall(r"python -m jobsearch_cn (\w+ \w+)", step), ["material validate", "material render"])
        self.assertIn("--output", step)

    def test_the_reviewer_checks_the_text_is_of_this_version(self):
        step = re.search(r"^\d+\. \*\*审核\*\*.*(?:\n   .*)*", self.section(), re.M).group(0)
        for text in (step, read(REPO / ".claude" / "agents" / "cn-resume-reviewer.md")):
            for word in ("build_note", "material_hash", "review draft"):
                self.assertIn(word, text)

    def test_every_entry_says_to_rerun_what_made_the_files(self):
        for entry in [REPO / d / "cn-resume" / "SKILL.md" for d in SKILL_DIRS] + [REPO / "AGENTS.md"]:
            with self.subTest(entry=entry.relative_to(REPO).as_posix()):
                text = read(entry)
                body = text.split("---", 2)[2] if entry.name == "SKILL.md" else text
                for command in ("resume build", "material render --output"):
                    self.assertIn(command, body)


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
