"""V8 black-box replay. Never import application code or rewrite frozen inputs.

Run with Python from the ai-job-search-cn environment. --code-dir must contain
the unchanged jobsearch_cn/ and tools/ trees from git archive of --commit.
Each label gets fresh local stores and immutable output snapshots.
"""
import argparse
import copy
import datetime
from fractions import Fraction
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import unicodedata

FIX = Path(__file__).resolve().parent
ROOT = FIX.parents[3]
MANIFEST_HASH = "be6a17191a51ef055e98626f8b9349cab1825ae9a26476dbe59ae11f41e5cd97"
ALIASES = (("Go", "Golang"), ("JavaScript", "JS"), ("Kubernetes", "K8s"),
           ("自然语言处理", "NLP"), ("文案写作", "文案撰写"), ("PowerPoint", "PPT"))


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def digest(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def norm(value):
    return "".join(unicodedata.normalize("NFKC", value).casefold().split())


def canonical(value):
    value = norm(value)
    for names in ALIASES:
        if value in map(norm, names):
            return norm(names[0])
    return value


def group_key(group, aliases=True):
    return tuple(sorted({(canonical if aliases else norm)(s) for s in group}))


def get(obj, path):
    for key in path.split("."):
        obj = obj[key]
    return obj


def put(obj, path, value):
    keys = path.split(".")
    for key in keys[:-1]:
        obj = obj[key]
    obj[keys[-1]] = copy.deepcopy(value)


def verify_frozen():
    assert digest(FIX / "oracle-manifest.json") == MANIFEST_HASH
    manifest = read(FIX / "oracle-manifest.json")
    for name, expected in manifest["oracle_files_lf_sha256"].items():
        assert digest(FIX / name) == expected, name
    for name, expected in manifest["source_files_lf_sha256"].items():
        if name.startswith("tests/fixtures/cn/profile/"):
            assert digest(ROOT / name) == expected, name
    return manifest


def verify_archive(code_dir, commit):
    archive = subprocess.check_output(["git", "archive", "--format=tar", commit], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
        names = set()
        for member in tree.getmembers():
            if member.isfile() and member.name.startswith(("jobsearch_cn/", "tools/")):
                names.add(member.name)
                assert (code_dir / member.name).read_bytes() == tree.extractfile(member).read(), member.name
    actual = {p.relative_to(code_dir).as_posix() for d in ("jobsearch_cn", "tools")
              for p in (code_dir / d).rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    assert actual == names, "code tree has extra or missing files"


def skill_expectation(skills, groups, profile):
    """Independent arithmetic from the public contract; all V8 groups are disjoint."""
    requirements = [set(group_key(group)) for group in groups]
    grouped = set().union(*requirements) if requirements else set()
    requirements += [{name} for name in sorted({canonical(s) for s in skills} - grouped)]
    credits = {}
    for skill in profile["skills"]:
        level = skill["level"]
        credit = {"expert": Fraction(1), "proficient": Fraction(1),
                  "working": Fraction(4, 5), "familiar": Fraction(1, 2)}.get(level)
        if credit is None:
            credit = Fraction(4, 5) if skill["used_in"] else Fraction(1, 2)
        key = canonical(skill["name"])
        credits[key] = max(credits.get(key, Fraction()), credit)
    values = [max((credits.get(s, Fraction()) for s in group), default=Fraction())
              for group in requirements]
    numerator = sum(values, Fraction())
    unrounded = numerator * 100 / len(requirements) if requirements else None
    rounded = (unrounded + Fraction(1, 2)).__floor__() if unrounded is not None else None
    return {"denominator": len(requirements), "credit_sum": str(numerator),
            "unrounded_score": str(unrounded), "score": rounded,
            "requirements": [sorted(group) for group in requirements],
            "credits": [str(value) for value in values],
            "missing": sorted(sorted(group) for group, value in zip(requirements, values) if not value)}


def score_check(score, expectation, job):
    dim = score["dimensions"]["skills"]
    observed_missing = sorted(sorted(group_key(item.split(" 或 "))) for item in dim["missing"])
    skill_gaps = [gap for gap in score["gaps"] if gap["kind"] == "skill"]
    gap_names = sorted(sorted(group_key(gap["item"].split(" 或 "))) for gap in skill_gaps)
    return {"score_equal": dim["score"] == expectation["score"],
            "item_count_equal": len(dim["matched"]) + len(dim["missing"]) == expectation["denominator"],
            "missing_equal": observed_missing == expectation["missing"],
            "skill_gap_names_equal": gap_names == expectation["missing"],
            "skill_gap_quotes_valid": all(gap["jd"] and gap["jd"] in job["raw_text"] for gap in skill_gaps),
            "rules_version_2": score["rules_version"] == 2,
            "experience_unfilled": score["dimensions"]["experience"]["score"] is None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code-dir", type=Path)
    parser.add_argument("--commit")
    parser.add_argument("--label")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    manifest = verify_frozen()
    if args.verify_only:
        print("V8 manifest, 13 frozen files and 2 profiles unchanged")
        return
    if not args.code_dir or not args.commit or not args.label:
        parser.error("--code-dir, --commit and --label required")
    assert re.fullmatch(r"[a-z0-9-]+", args.label)
    code_dir = args.code_dir.resolve()
    commit = subprocess.check_output(["git", "rev-parse", args.commit], cwd=ROOT, text=True).strip()
    verify_archive(code_dir, commit)
    out = FIX / "actual" / args.label
    data = ROOT / "data/v8-check" / args.label
    assert not out.exists() and not data.exists(), "use a fresh label; never overwrite results"
    out.mkdir(parents=True)
    data.mkdir(parents=True)
    invocations = []

    def cli(arguments, store=data):
        options = [] if arguments[:2] == ["jd", "validate"] else ["--data-dir", str(store)]
        command = [sys.executable, "-m", "jobsearch_cn", *map(str, arguments), *options]
        result = subprocess.run(command, cwd=code_dir, capture_output=True, encoding="utf-8",
                                env={**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(code_dir)})
        public_command = ["python", *[s.replace(str(ROOT), "<workspace>") for s in command[1:]]]
        invocations.append({"command": public_command, "exit_code": result.returncode,
                            "stderr": result.stderr.replace(str(ROOT), "<workspace>")})
        write(out / "commands.json", invocations)
        assert result.returncode == 0, (public_command, result.returncode, result.stdout, result.stderr)
        assert not result.stderr.strip(), result.stderr
        return json.loads(result.stdout)

    summary = {"code_commit": commit, "baseline_commit": manifest["base_commit"],
               "freeze_manifest_lf_sha256": MANIFEST_HASH,
               "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "python_version": sys.version.split()[0],
               "method": "Public CLI only; frozen sidecar mapped into documented H16 field; no Agent score completion",
               "field_groups": {"equal": 0, "total": 70},
               "skills": {"matched": 0, "expected": 24, "missing": 0, "extra": 0},
               "alternative_groups": {"exact": 0, "semantic": 0, "expected": 9, "extra": 0},
               "filter_verdicts": {"equal": 0, "total": 10},
               "hard_checks": {"equal": 0, "total": 70},
               "manual_replay_verdicts": {"equal": 0, "total": 10},
               "manual_replay_checks": {"equal": 0, "total": 70}, "cases": {}}
    sidecar = read(FIX / "alternative-groups.expected.json")["cases"]
    for path in sorted(FIX.glob("*.expected.json")):
        if path.name == "alternative-groups.expected.json":
            continue
        oracle = read(path)
        key = path.name.removesuffix(".expected.json")
        groups = sidecar[key]["groups"]
        parse = cli(["jd", "parse", FIX / oracle["fixture"], "--site", oracle["site_argument"], "--save"])
        assert len(parse["jobs"]) == 1
        job = parse["jobs"][0]
        differences = {}
        for field, entry in oracle["fields"].items():
            expected, actual = entry["value"], get(job, field)
            same = ({norm(s) for s in expected} == {norm(s) for s in actual}
                    if field in ("requirements.skills", "cities") else expected == actual)
            summary["field_groups"]["equal"] += same
            if not same:
                differences[field] = {"expected": expected, "actual": actual}
        expected_skills = {norm(s) for s in oracle["fields"]["requirements.skills"]["value"]}
        observed_skills = {norm(s) for s in job["requirements"]["skills"]}
        summary["skills"]["matched"] += len(expected_skills & observed_skills)
        summary["skills"]["missing"] += len(expected_skills - observed_skills)
        summary["skills"]["extra"] += len(observed_skills - expected_skills)
        actual_groups = job["requirements"]["skill_alternatives"]
        expected_groups = [group["skills"] for group in groups]
        observed_semantic = {group_key(group) for group in actual_groups}
        expected_semantic = {group_key(group) for group in expected_groups}
        quotes = job["evidence"].get("requirements.skill_alternatives", {}).get("text", [])
        if isinstance(quotes, str):
            quotes = [quotes]
        group_audit = {"expected": expected_groups, "actual": actual_groups,
                       "exact_matches": len({group_key(g, False) for g in expected_groups} &
                                            {group_key(g, False) for g in actual_groups}),
                       "semantic_matches": len(expected_semantic & observed_semantic),
                       "missing": [list(g) for g in sorted(expected_semantic - observed_semantic)],
                       "extra": [list(g) for g in sorted(observed_semantic - expected_semantic)],
                       "quotes": quotes,
                       "quotes_are_verbatim": all(q in job["raw_text"] for q in quotes),
                       "each_group_has_joint_quote": all(any(all(norm(s) in norm(q) for s in g)
                                                              for q in quotes) for g in actual_groups),
                       "not_groups": sidecar[key]["not_groups"]}
        for metric, audit_key in (("exact", "exact_matches"), ("semantic", "semantic_matches")):
            summary["alternative_groups"][metric] += group_audit[audit_key]
        summary["alternative_groups"]["extra"] += len(group_audit["extra"])
        actual = {"parse": parse, "differences": differences, "group_audit": group_audit, "profiles": {}}
        manual = copy.deepcopy(job)
        for field, entry in oracle["fields"].items():
            put(manual, field, entry["value"])
            if entry["value"] is None or entry["value"] == []:
                manual["evidence"].pop(field, None)
            else:
                manual["evidence"][field] = {"text": entry["evidence"], "method": "agent"}
        manual["requirements"]["skill_alternatives"] = expected_groups
        manual["evidence"]["requirements.skill_alternatives"] = {
            "text": [group["evidence"] for group in groups], "method": "agent"}
        manual_path = data / "manual-input" / (key + ".json")
        write(manual_path, manual)
        actual["manual_fields_job"] = manual
        actual["manual_validate"] = cli(["jd", "validate", manual_path])
        assert actual["manual_validate"]["valid"]
        actual["manual_save"] = cli(["jd", "save", manual_path], data / "manual-store")
        for profile_name in ("tech", "ops"):
            pp = ROOT / "tests/fixtures/cn/profile" / profile_name / "profile.json"
            profile = read(pp)
            observed = cli(["match", "filter", job["id"], "--profile", pp])
            score = cli(["match", "score", job["id"], "--profile", pp])
            replay = cli(["match", "filter", job["id"], "--profile", pp], data / "manual-store")
            manual_score = cli(["match", "score", job["id"], "--profile", pp], data / "manual-store")
            human = oracle["human_match"][profile_name]
            for f, vk, ck in ((observed, "filter_verdicts", "hard_checks"),
                              (replay, "manual_replay_verdicts", "manual_replay_checks")):
                assert {c["check"] for c in f["checks"]} == set(human["checks"])
                summary[vk]["equal"] += f["verdict"] == human["verdict"]
                summary[ck]["equal"] += sum(c["result"] == human["checks"][c["check"]]["result"] for c in f["checks"])
            arithmetic = skill_expectation(job["requirements"]["skills"], actual_groups, profile)
            manual_arithmetic = skill_expectation(manual["requirements"]["skills"], expected_groups, profile)
            actual["profiles"][profile_name] = {
                "filter": observed, "rule_score": score, "manual_fields_filter": replay,
                "manual_fields_rule_score": manual_score, "parsed_input_arithmetic": arithmetic,
                "manual_input_arithmetic": manual_arithmetic,
                "parsed_score_checks": score_check(score, arithmetic, job),
                "manual_score_checks": score_check(manual_score, manual_arithmetic, manual)}
        summary["cases"][key] = {
            "field_groups_equal": 14 - len(differences), "differences": differences,
            "groups": group_audit,
            "profiles": {p: {"parsed_skill_score": v["rule_score"]["dimensions"]["skills"]["score"],
                             "manual_skill_score": v["manual_fields_rule_score"]["dimensions"]["skills"]["score"],
                             "parsed_checks": v["parsed_score_checks"], "manual_checks": v["manual_score_checks"]}
                         for p, v in actual["profiles"].items()}}
        write(out / (key + ".json"), actual)
        print(key, "fields", 14 - len(differences), "/14; groups", group_audit["semantic_matches"],
              "/", len(groups), flush=True)
    verify_frozen()
    verify_archive(code_dir, commit)
    summary["finished_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    write(out / "summary.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "cases"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
