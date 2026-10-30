"""Reproduce V15 on its frozen master using the public CLI and fresh local stores."""
import argparse
import copy
import datetime
import json
import os
import re
import subprocess
import sys
import unicodedata

from audit_oracle import FIX, ROOT, MANIFEST_HASH, read, verify


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def norm(value):
    return unicodedata.normalize("NFKC", value).casefold().strip()


def get(obj, field):
    for key in field.split("."):
        obj = obj[key]
    return obj


def put(obj, field, value):
    keys = field.split(".")
    for key in keys[:-1]:
        obj = obj[key]
    obj[keys[-1]] = copy.deepcopy(value)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="master-e99470e")
    args = parser.parse_args()
    assert re.fullmatch(r"[a-z0-9-]+", args.label)
    manifest, _ = verify()
    # Compare silently: do not inspect parser source or another implementation branch.
    subprocess.run(["git", "diff", "--quiet", manifest["base_commit"], "--", "jobsearch_cn", "tools"], cwd=ROOT, check=True)
    execution_commit = git("rev-parse", "HEAD").decode().strip()
    for name in ["oracle-manifest.json", *manifest["oracle_files_lf_sha256"]]:
        relative = (FIX / name).relative_to(ROOT).as_posix()
        assert git("show", "HEAD:" + relative) == (FIX / name).read_bytes(), "Commit the frozen inputs before execution"
    out = FIX / "actual" / args.label
    data = ROOT / "data/v15-check" / args.label
    assert not out.exists() and not data.exists(), "Use a fresh label; never overwrite earlier results"
    out.mkdir(parents=True)
    data.mkdir(parents=True)
    commands = []

    def cli(arguments, store=data):
        options = [] if arguments[:2] == ["jd", "validate"] else ["--data-dir", str(store)]
        command = [sys.executable, "-m", "jobsearch_cn", *map(str, arguments), *options]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, encoding="utf-8",
                                env={**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(ROOT)})
        public = ["python", *[v.replace(str(ROOT), "<workspace>") for v in command[1:]]]
        commands.append({"command": public, "exit_code": result.returncode,
                         "stderr": result.stderr.replace(str(ROOT), "<workspace>")})
        write(out / "commands.json", commands)
        assert result.returncode == 0 and not result.stderr.strip(), (public, result.returncode)
        return json.loads(result.stdout)

    summary = {
        "code_commit": manifest["base_commit"], "execution_commit": execution_commit,
        "manifest_sha256": MANIFEST_HASH, "python_version": sys.version.split()[0],
        "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "fully_decidable_field_groups": {"equal": 0, "total": 69},
        "definite_skills": {"matched": 0, "expected": 16, "missing": 0, "extra": 0},
        "positive_version_probes": {"matched": 0, "total": 10},
        "intrinsic_digit_probes": {"matched": 0, "total": 1},
        "console_probes": {"passed": 0, "total": 2},
        "forbidden_skill_traps": {"passed": 0, "total": 0},
        "alternative_group_checks": {"equal": 0, "total": 5},
        "filter_verdicts": {"equal": 0, "total": 10}, "hard_checks": {"equal": 0, "total": 70},
        "manual_validations": {"equal": 0, "total": 5},
        "manual_replay_verdicts": {"equal": 0, "total": 10},
        "manual_replay_checks": {"equal": 0, "total": 70}, "cases": {},
    }
    for path in sorted(FIX.glob("*.expected.json")):
        oracle = read(path)
        key = path.name.removesuffix(".expected.json")
        parsed = cli(["jd", "parse", FIX / oracle["fixture"], "--site", oracle["site_argument"], "--save"])
        assert len(parsed["jobs"]) == 1
        job = parsed["jobs"][0]
        observed = {norm(s) for s in job["requirements"]["skills"]}
        expected_skills = {norm(s) for s in oracle["fields"]["requirements.skills"]["value"]}
        pending_labels = {norm(s) for p in oracle["pending_adjudication"] for s in p["observed_labels"]}
        pending = [{"id": p["id"], "text": p["text"], "status": p["status"],
                    "observed_labels": [s for s in job["requirements"]["skills"]
                                        if norm(s) in {norm(v) for v in p["observed_labels"]}]}
                   for p in oracle["pending_adjudication"]]
        missing = sorted(expected_skills - observed)
        extra = sorted(observed - expected_skills - pending_labels)
        differences = {}
        field_equal = 0
        field_total = 0
        for field, entry in oracle["fields"].items():
            if "comparison" in entry:
                continue
            expected, actual = entry["value"], get(job, field)
            same = ({norm(s) for s in expected} == {norm(s) for s in actual}
                    if field in ("cities", "requirements.skills") else expected == actual)
            field_equal += same
            field_total += 1
            if not same:
                differences[field] = {"expected": expected, "actual": actual}
        summary["fully_decidable_field_groups"]["equal"] += field_equal
        summary["definite_skills"]["matched"] += len(expected_skills & observed)
        summary["definite_skills"]["missing"] += len(missing)
        summary["definite_skills"]["extra"] += len(extra)
        probes = []
        for probe in oracle["version_probes"]:
            if probe["decision"] == "must_not_map_console_to_photoshop":
                passed = not observed & {"ps", "photoshop", "ps4", "ps5"}
                summary["console_probes"]["passed"] += passed
            else:
                passed = norm(probe["expected_skill"]) in observed
                counter = "positive_version_probes" if probe["decision"] == "must_read" else "intrinsic_digit_probes"
                summary[counter]["matched"] += passed
            probes.append({**probe, "passed": passed})
        traps = []
        for trap in oracle["traps"]:
            if "forbidden_skills" in trap:
                hits = sorted(observed & {norm(s) for s in trap["forbidden_skills"]})
                traps.append({"text": trap["text"], "forbidden_hits": hits})
                summary["forbidden_skill_traps"]["total"] += 1
                summary["forbidden_skill_traps"]["passed"] += not hits
        alternatives = job["requirements"]["skill_alternatives"]
        summary["alternative_group_checks"]["equal"] += alternatives == []
        # Replay the frozen definite fields in an isolated store to separate extraction from filtering.
        # Pending skills remain outside this partial manual record and all skill verdicts.
        manual = copy.deepcopy(job)
        for field, entry in {**oracle["fields"], **oracle["additional_fields"]}.items():
            put(manual, field, entry["value"])
            if entry["value"] is None or entry["value"] == []:
                manual["evidence"].pop(field, None)
            else:
                manual["evidence"][field] = {"text": entry["evidence"], "method": "agent"}
        manual_path = data / "manual-input" / (key + ".json")
        write(manual_path, manual)
        validation = cli(["jd", "validate", manual_path])
        summary["manual_validations"]["equal"] += validation["valid"]
        saved = cli(["jd", "save", manual_path], data / "manual-store")
        actual = {"parse": parsed, "manual_fields_job": manual, "manual_validate": validation,
                  "manual_save": saved, "profiles": {}}
        for profile in ("tech", "ops"):
            pp = ROOT / "tests/fixtures/cn/profile" / profile / "profile.json"
            filtered = cli(["match", "filter", job["id"], "--profile", pp])
            replay = cli(["match", "filter", job["id"], "--profile", pp], data / "manual-store")
            human = oracle["human_match"][profile]
            comparisons = {}
            for label, result, vk, ck in (("parsed", filtered, "filter_verdicts", "hard_checks"),
                                         ("manual", replay, "manual_replay_verdicts", "manual_replay_checks")):
                checks = {c["check"]: c["result"] for c in result["checks"]}
                assert set(checks) == set(human["checks"])
                summary[vk]["equal"] += result["verdict"] == human["verdict"]
                diff = {name: {"expected": entry["result"], "actual": checks[name]}
                        for name, entry in human["checks"].items() if entry["result"] != checks[name]}
                summary[ck]["equal"] += len(checks) - len(diff)
                comparisons[label] = {"verdict_equal": result["verdict"] == human["verdict"], "check_differences": diff}
            actual["profiles"][profile] = {"filter": filtered, "manual_fields_filter": replay, "comparison": comparisons}
        case = {"field_groups": {"equal": field_equal, "total": field_total}, "differences": differences,
                "skills": {"expected": sorted(expected_skills), "actual": sorted(observed), "missing": missing, "extra": extra},
                "pending_adjudication": pending, "version_probes": probes, "forbidden_traps": traps,
                "alternative_groups": alternatives,
                "profiles": {p: v["comparison"] for p, v in actual["profiles"].items()}}
        actual["comparison"] = case
        summary["cases"][key] = case
        write(out / (key + ".json"), actual)
        print(key, f"fields {field_equal}/{field_total}", "missing", missing, "extra", extra, flush=True)
    verify()
    assert git("rev-parse", "HEAD").decode().strip() == execution_commit
    subprocess.run(["git", "diff", "--quiet", manifest["base_commit"], "--", "jobsearch_cn", "tools"], cwd=ROOT, check=True)
    summary["finished_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    summary["successful_cli_calls"] = len(commands)
    write(out / "summary.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "cases"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
