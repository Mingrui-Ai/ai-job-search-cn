"""Reproduce V10 via public CLI with fresh stores; no application imports."""
import argparse
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unicodedata

FIX = Path(__file__).resolve().parent
ROOT = FIX.parents[3]
MANIFEST_HASH = "4c0a3dc79bd98532124b7c12c29bc3a4601cf800e7adbddf504cde3c88ec99c2"


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


def get(obj, dotted):
    for key in dotted.split("."):
        obj = obj[key]
    return obj


def put(obj, dotted, value):
    keys = dotted.split(".")
    for key in keys[:-1]:
        obj = obj[key]
    obj[keys[-1]] = copy.deepcopy(value)


def verify():
    assert digest(FIX / "oracle-manifest.json") == MANIFEST_HASH
    manifest = read(FIX / "oracle-manifest.json")
    for name, expected in manifest["oracle_files_lf_sha256"].items():
        assert digest(FIX / name) == expected, name
    for name, expected in manifest["source_files_lf_sha256"].items():
        if name.startswith("tests/fixtures/cn/profile/"):
            assert digest(ROOT / name) == expected, name
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="master-c6055cc")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    manifest = verify()
    if args.verify_only:
        print("V10 manifest, 12 frozen inputs, and two profiles unchanged")
        return
    assert re.fullmatch(r"[a-z0-9-]+", args.label)
    assert not subprocess.check_output(["git", "diff", manifest["base_commit"], "--", "jobsearch_cn", "tools"], cwd=ROOT).strip(), "baseline application/tool code changed"
    execution_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    out = FIX / "actual" / args.label
    data = ROOT / "data/v10-check" / args.label
    assert not out.exists() and not data.exists(), "choose a new label; never overwrite earlier outputs"
    out.mkdir(parents=True)
    data.mkdir(parents=True)
    commands = []

    def cli(arguments, store=data):
        options = [] if arguments[:2] == ["jd", "validate"] else ["--data-dir", str(store)]
        command = [sys.executable, "-m", "jobsearch_cn", *map(str, arguments), *options]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, encoding="utf-8",
                                env={**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(ROOT)})
        public_command = ["python", *[arg.replace(str(ROOT), "<workspace>") for arg in command[1:]]]
        commands.append({"command": public_command, "exit_code": result.returncode,
                         "stderr": result.stderr.replace(str(ROOT), "<workspace>")})
        write(out / "commands.json", commands)
        assert result.returncode == 0 and not result.stderr.strip(), (public_command, result.returncode)
        return json.loads(result.stdout)

    summary = {"code_commit": manifest["base_commit"], "execution_commit": execution_commit,
               "manifest_lf_sha256": MANIFEST_HASH, "python_version": sys.version.split()[0],
               "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "field_groups": {"equal": 0, "total": 70},
               "skills": {"matched": 0, "expected": 12, "missing": 0, "extra": 0},
               "filter_verdicts": {"equal": 0, "total": 10}, "hard_checks": {"equal": 0, "total": 70},
               "manual_validations": {"equal": 0, "total": 5},
               "manual_replay_verdicts": {"equal": 0, "total": 10},
               "manual_replay_checks": {"equal": 0, "total": 70}, "cases": {}}
    for path in sorted(FIX.glob("*.expected.json")):
        oracle = read(path)
        key = path.name.removesuffix(".expected.json")
        parsed = cli(["jd", "parse", FIX / oracle["fixture"], "--site", oracle["site_argument"], "--save"])
        assert len(parsed["jobs"]) == 1
        job = parsed["jobs"][0]
        differences = {}
        for field, entry in oracle["fields"].items():
            expected, actual = entry["value"], get(job, field)
            same = ({norm(s) for s in expected} == {norm(s) for s in actual}
                    if field in ("cities", "requirements.skills") else expected == actual)
            summary["field_groups"]["equal"] += same
            if not same:
                differences[field] = {"expected": expected, "actual": actual}
        expected_skills = {norm(s) for s in oracle["fields"]["requirements.skills"]["value"]}
        observed_skills = {norm(s) for s in job["requirements"]["skills"]}
        summary["skills"]["matched"] += len(expected_skills & observed_skills)
        summary["skills"]["missing"] += len(expected_skills - observed_skills)
        summary["skills"]["extra"] += len(observed_skills - expected_skills)
        manual = copy.deepcopy(job)
        for field, entry in oracle["fields"].items():
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
        actual = {"parse": parsed, "differences": differences, "manual_fields_job": manual,
                  "manual_validate": validation, "manual_save": saved, "profiles": {}}
        for profile in ("tech", "ops"):
            pp = ROOT / "tests/fixtures/cn/profile" / profile / "profile.json"
            filtered = cli(["match", "filter", job["id"], "--profile", pp])
            replay = cli(["match", "filter", job["id"], "--profile", pp], data / "manual-store")
            human = oracle["human_match"][profile]
            comparisons = {}
            for label, result, vk, ck in (("parsed", filtered, "filter_verdicts", "hard_checks"),
                                         ("manual", replay, "manual_replay_verdicts", "manual_replay_checks")):
                observed = {c["check"]: c["result"] for c in result["checks"]}
                assert set(observed) == set(human["checks"])
                summary[vk]["equal"] += result["verdict"] == human["verdict"]
                diff = {name: {"expected": expected["result"], "actual": observed[name]}
                        for name, expected in human["checks"].items() if expected["result"] != observed[name]}
                summary[ck]["equal"] += 7 - len(diff)
                comparisons[label] = {"verdict_equal": result["verdict"] == human["verdict"], "check_differences": diff}
            actual["profiles"][profile] = {"filter": filtered, "manual_fields_filter": replay,
                                            "comparison": comparisons}
        summary["cases"][key] = {"field_groups_equal": 14-len(differences), "differences": differences,
                                  "profiles": {p: v["comparison"] for p,v in actual["profiles"].items()}}
        write(out / (key + ".json"), actual)
        print(key, "fields", 14-len(differences), "/14", flush=True)
    verify()
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() == execution_commit
    assert not subprocess.check_output(["git", "diff", manifest["base_commit"], "--", "jobsearch_cn", "tools"], cwd=ROOT).strip()
    summary["finished_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    summary["successful_cli_calls"] = len(commands)
    write(out / "summary.json", summary)
    print(json.dumps({k:v for k,v in summary.items() if k != "cases"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
