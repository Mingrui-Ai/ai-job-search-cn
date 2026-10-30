"""Verify frozen V15 inputs without application imports or writes."""
import hashlib
import json
from pathlib import Path
import subprocess

FIX = Path(__file__).resolve().parent
ROOT = FIX.parents[3]
FIELDS = {
    "title", "company", "cities", "remote", "employment_type", "salary",
    "requirements.graduation", "requirements.days_per_week", "requirements.min_months",
    "requirements.education", "requirements.skills", "return_offer", "published_at", "deadline",
}
CHECKS = {"graduation", "education", "days_per_week", "min_months", "location", "employment_type", "exclusions"}
MANIFEST_HASH = "009b07fcb5a743fabfd9774a4cddafe95f346dc881ed37bd5a5aa53aaf0d7c5f"


def digest(path, lf=False):
    raw = path.read_bytes()
    return hashlib.sha256(raw.replace(b"\r\n", b"\n") if lf else raw).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def audit():
    paths = sorted(FIX.glob("*.expected.json"))
    assert len(paths) == 5
    assert {p.name for p in FIX.glob("*.txt")} == {read(p)["fixture"] for p in paths}
    stats = {"jd_count": 5, "field_groups": 0, "fully_decidable_field_groups": 0,
             "definite_skill_occurrences": 0, "positive_version_probes": 0,
             "intrinsic_digit_probes": 0, "console_probes": 0,
             "pending_adjudications": 0, "verbatim_evidence_snippets": 0,
             "human_matches": 0, "hard_check_states": 0, "additional_fields": 0}
    for path in paths:
        oracle = read(path)
        raw = (FIX / oracle["fixture"]).read_text(encoding="utf-8")
        assert oracle["method"] == "agent" and oracle["job_schema_version"] == 1
        assert set(oracle["fields"]) == FIELDS
        assert set(oracle["additional_fields"]) == {"requirements.skill_alternatives"}
        assert oracle["additional_fields"]["requirements.skill_alternatives"]["value"] == []
        stats["field_groups"] += len(FIELDS)
        stats["additional_fields"] += 1
        for field, entry in {**oracle["fields"], **oracle["additional_fields"]}.items():
            assert isinstance(entry["evidence"], list)
            if entry["value"] is not None and entry["value"] != []:
                assert entry["evidence"], (path.name, field)
            for snippet in entry["evidence"]:
                assert snippet and snippet in raw, (path.name, field, snippet)
                stats["verbatim_evidence_snippets"] += 1
            if field in FIELDS:
                stats["fully_decidable_field_groups"] += "comparison" not in entry
        skills = oracle["fields"]["requirements.skills"]["value"]
        assert len(set(skills)) == len(skills)
        stats["definite_skill_occurrences"] += len(skills)
        for probe in oracle["version_probes"]:
            assert probe["text"] in raw
            if probe["expected_skill"] is not None:
                assert probe["expected_skill"] in skills
            stats[{"must_read": "positive_version_probes",
                   "must_keep_intrinsic_digit": "intrinsic_digit_probes",
                   "must_not_map_console_to_photoshop": "console_probes"}[probe["decision"]]] += 1
        for trap in oracle["traps"]:
            assert trap["text"] in raw and trap["interpretation"]
            assert not set(trap.get("forbidden_skills", [])) & set(skills)
        for pending in oracle["pending_adjudication"]:
            assert pending["status"] == "待规划者裁定" and pending["text"] in raw
            assert pending["question"] and pending["observed_labels"]
            assert not set(pending["observed_labels"]) & set(skills)
            stats["pending_adjudications"] += 1
        assert set(oracle["human_match"]) == {"tech", "ops"}
        for human in oracle["human_match"].values():
            assert set(human["checks"]) == CHECKS
            states = {c["result"] for c in human["checks"].values()}
            assert states <= {"match", "conflict", "unknown", "not_applicable"}
            assert all(c["reason"] for c in human["checks"].values())
            verdict = "ineligible" if "conflict" in states else "needs_check" if "unknown" in states else "eligible"
            assert human["verdict"] == verdict
            stats["human_matches"] += 1
            stats["hard_check_states"] += len(CHECKS)
    files = [FIX / ".gitattributes", FIX / "README.md", *sorted(FIX.glob("*.txt")), *paths]
    for path in files:
        raw = path.read_bytes()
        raw.decode("utf-8", errors="strict")
        assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and raw.endswith(b"\n"), path.name
    assert stats["fully_decidable_field_groups"] == 69
    assert stats["definite_skill_occurrences"] == 16
    assert stats["positive_version_probes"] == 10
    assert stats["pending_adjudications"] == 3
    return files, stats


def verify():
    _, stats = audit()
    manifest_path = FIX / "oracle-manifest.json"
    assert digest(manifest_path) == MANIFEST_HASH
    manifest = read(manifest_path)
    for name, expected in manifest["oracle_files_lf_sha256"].items():
        assert digest(FIX / name, lf=True) == expected, name
    for name, expected in manifest["source_git_blob_sha256"].items():
        blob = subprocess.check_output(["git", "show", manifest["base_commit"] + ":" + name], cwd=ROOT)
        assert hashlib.sha256(blob).hexdigest() == expected, name
    return manifest, stats


def main():
    _, stats = verify()
    manifest_path = FIX / "oracle-manifest.json"
    print(json.dumps({"audit": stats, "manifest_sha256": digest(manifest_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
