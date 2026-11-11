"""The approved five interview actions remain finite in the static guards.

These exercise the real guard subprocess with temporary settings and skill
frontmatter. They do not claim to test Claude Code's runtime permission matcher.
"""
import json
import unittest

from tests.test_security_guards import GuardRepoFixture, REPO_ROOT, run_guards, security_guards


GRANTS = {
    "Bash(python -m jobsearch_cn interview template:*)",
    "Bash(python -m jobsearch_cn interview validate:*)",
    "Bash(python -m jobsearch_cn interview render:*)",
    "Bash(python -m jobsearch_cn interview review-draft:*)",
    "Bash(python -m jobsearch_cn interview review-validate:*)",
}
WIDENINGS = (
    "Bash(python -m jobsearch_cn:*)",
    "Bash(python -m jobsearch_cn interview:*)",
    "Bash(python -m jobsearch_cn interview delete:*)",
    "Bash(python -m jobsearch_cn interview review:*)",
    "Bash(python -m jobsearch_cn interview validate-extra:*)",
    "Bash(python -m jobsearch_cn interview rendering:*)",
)


class InterviewPermissionTests(GuardRepoFixture):
    def test_shipped_interview_grants_are_exactly_the_approved_five(self):
        settings = json.loads((REPO_ROOT / ".claude/settings.json").read_text(encoding="utf-8"))
        for grants in (
            settings["permissions"]["allow"],
            security_guards.ALLOWED_PERMISSIONS,
            security_guards.ALLOWED_SKILL_TOOLS,
        ):
            with self.subTest(grants=type(grants).__name__):
                interview = {grant for grant in grants if grant.startswith("Bash(python -m jobsearch_cn interview")}
                self.assertEqual(interview, GRANTS)

    def test_five_actions_pass_in_settings_and_skill_frontmatter(self):
        self.write_settings(sorted(security_guards.ALLOWED_PERMISSIONS | GRANTS))
        for grant in sorted(GRANTS):
            with self.subTest(grant=grant):
                self.write_skill(self.core_skill, "Read, " + grant)
                result = run_guards(self.root)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("security_guards: OK", result.stdout)

    def test_settings_reject_broader_or_unapproved_actions(self):
        for grant in WIDENINGS:
            with self.subTest(grant=grant):
                self.write_settings(sorted(security_guards.ALLOWED_PERMISSIONS) + [grant])
                result = run_guards(self.root)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("not in the reviewed allowlist", result.stdout)
                self.assertIn(grant, result.stdout)

    def test_skills_reject_broader_or_unapproved_actions(self):
        for grant in WIDENINGS:
            with self.subTest(grant=grant):
                self.write_skill(self.core_skill, "Read, " + grant)
                result = run_guards(self.root)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("allowed-tools entry not in the reviewed allowlist", result.stdout)
                self.assertIn(grant, result.stdout)


if __name__ == "__main__":
    unittest.main()
