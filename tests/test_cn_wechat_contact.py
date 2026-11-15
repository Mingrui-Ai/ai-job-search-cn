"""Optional WeChat contacts stay private and render only in email signatures."""
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from jobsearch_cn import material, messages, profile, score
from tests.test_cn_messages import (
    EMAIL, GREETING, REFERRAL, TECH, TECH_JOB, TECH_PROFILE, check, run_cli, with_segment,
)


WECHAT = "example_wechat_2026"


def with_wechat(value=WECHAT):
    data = copy.deepcopy(TECH_PROFILE)
    data["contact"]["wechat"] = value
    return data


def email_with_wechat():
    return with_segment(EMAIL, -1, EMAIL["segments"][-1]["text"] + "\n微信：{contact.wechat}")


class ProfileWechat(unittest.TestCase):
    def test_wechat_is_optional_and_nullable(self):
        for data in (TECH_PROFILE, with_wechat(None), with_wechat()):
            with self.subTest(contact=data["contact"]):
                self.assertEqual(profile.validate(data), [])

    def test_invalid_wechat_values_do_not_leak_into_errors(self):
        for value in ("", " ", 123456, True, [WECHAT], {WECHAT: "private"}):
            with self.subTest(value=value):
                errors = profile.validate(with_wechat(value))
                self.assertIn("contact.wechat: must be null or a non-empty string", errors)
                self.assertNotIn(WECHAT, " ".join(errors))

    def test_wechat_uses_the_existing_contact_length_limit(self):
        self.assertEqual(profile.validate(with_wechat("a" * 200)), [])
        self.assertIn("contact.wechat: longer than 200 characters", profile.validate(with_wechat("a" * 201)))

    def test_wechat_is_redacted_without_changing_the_profile(self):
        data = with_wechat()
        shown = profile.redacted(data)
        self.assertEqual(shown["contact"]["wechat"], "***")
        self.assertNotIn(WECHAT, json.dumps(shown))
        self.assertEqual(data["contact"]["wechat"], WECHAT)
        self.assertIsNone(profile.redacted(with_wechat(None))["contact"]["wechat"])

    def test_adding_wechat_does_not_change_scores_or_resume_contacts(self):
        data = with_wechat()
        self.assertEqual(score.profile_hash(data), score.profile_hash(TECH_PROFILE))
        self.assertEqual(material._contact(data["contact"]), material._contact(TECH_PROFILE["contact"]))


class WechatSignature(unittest.TestCase):
    def test_profile_value_renders_in_an_email_signature(self):
        record, data = email_with_wechat(), with_wechat()
        self.assertEqual(check(record, profile_data=data), ([], []))
        self.assertIn("微信：" + WECHAT, messages.render(record, data, TECH_JOB))

    def test_wechat_is_rejected_outside_an_email_signature(self):
        data = with_wechat()
        cases = [with_segment(record, -1, "微信：{contact.wechat}") for record in (GREETING, REFERRAL)]
        cases.append(with_segment(EMAIL, 5, "微信：{contact.wechat}"))
        subject = copy.deepcopy(EMAIL)
        subject["subject"] = {"text": "微信：{contact.wechat}", "refs": []}
        cases.append(subject)
        for record in cases:
            with self.subTest(kind=record["kind"], subject=record["subject"]):
                errors, _ = check(record, profile_data=data)
                self.assertTrue(any("belong only in an email's signature segment" in e for e in errors), errors)
                self.assertNotIn(WECHAT, " ".join(errors))
        _, _, errors = messages.fill("微信：{contact.wechat}", data, TECH_JOB, {}, "request", "followup")
        self.assertTrue(any("belong only in an email's signature segment" in e for e in errors), errors)

    def test_missing_or_empty_wechat_is_not_invented(self):
        for data in (TECH_PROFILE, with_wechat(None), with_wechat(""), with_wechat(" ")):
            with self.subTest(contact=data["contact"]):
                errors, _ = check(email_with_wechat(), profile_data=data)
                self.assertIn("segments[6].text: {contact.wechat}: the profile has no contact.wechat", errors)

    def test_handwritten_wechat_is_rejected_even_when_it_matches_the_profile(self):
        errors, _ = check(with_segment(EMAIL, -1, "微信：" + WECHAT), profile_data=with_wechat())
        self.assertTrue(any("手写了微信号、QQ 号这类联系方式" in error for error in errors), errors)

    def test_existing_email_does_not_include_wechat_automatically(self):
        self.assertEqual(check(EMAIL, profile_data=with_wechat()), ([], []))
        self.assertEqual(messages.render(EMAIL, with_wechat(), TECH_JOB),
                         messages.render(EMAIL, TECH_PROFILE, TECH_JOB))


class WechatCli(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name)
        shutil.copytree(TECH / "profile", self.data / "profile")
        self.profile_path = self.data / "profile" / "profile.json"
        self.profile_path.write_text(json.dumps(with_wechat(), ensure_ascii=False), encoding="utf-8")
        (self.data / "jobs").mkdir()
        shutil.copy(TECH / "job.json", self.data / "jobs" / f"{TECH_JOB['id']}.json")

    def test_profile_validate_and_show_keep_wechat_private(self):
        before = self.profile_path.read_bytes()
        validated = run_cli("profile", "validate", data_dir=self.data)
        self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
        self.assertTrue(json.loads(validated.stdout)["valid"])
        shown = run_cli("profile", "show", data_dir=self.data)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertNotIn(WECHAT, validated.stdout + validated.stderr + shown.stdout + shown.stderr)
        explicit = run_cli("profile", "show", "--contact", data_dir=self.data)
        self.assertEqual(explicit.returncode, 0, explicit.stderr)
        self.assertIn(WECHAT, explicit.stdout)
        self.assertEqual(self.profile_path.read_bytes(), before)

    def test_email_validates_and_renders_wechat_only_to_the_requested_file(self):
        source = self.data / "email-1.json"
        source.write_text(json.dumps(email_with_wechat(), ensure_ascii=False), encoding="utf-8")
        before = self.profile_path.read_bytes()
        validated = run_cli("material", "validate", str(source), data_dir=self.data)
        self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
        rendered = run_cli("material", "render", str(source), "--output", data_dir=self.data)
        self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
        self.assertNotIn(WECHAT, validated.stdout + validated.stderr + rendered.stdout + rendered.stderr)
        output = json.loads(rendered.stdout)
        self.assertIn("微信：" + WECHAT, Path(output["text"]).read_text(encoding="utf-8"))
        self.assertNotIn(WECHAT, Path(output["build_note"]).read_text(encoding="utf-8"))
        self.assertEqual(self.profile_path.read_bytes(), before)
