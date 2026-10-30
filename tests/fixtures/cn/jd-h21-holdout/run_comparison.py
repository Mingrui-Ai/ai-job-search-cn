"""Compare frozen V15 inputs with an immutable archive of H21 PR #91."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile

from audit_oracle import FIX, ROOT, MANIFEST_HASH, read, verify
from run_baseline import get, norm, put, write


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify(field, expected, actual):
    if field in ("cities", "requirements.skills"):
        wanted = {norm(value): value for value in expected}
        found = {norm(value): value for value in actual}
        missing = [wanted[key] for key in sorted(wanted.keys() - found.keys())]
        extra = [found[key] for key in sorted(found.keys() - wanted.keys())]
        kind = "wrong" if missing and extra else "missing" if missing else "extra" if extra else "match"
        return {"type": kind, "expected": expected, "actual": actual, "missing": missing, "extra": extra}
    kind = ("match" if expected == actual else "missing" if actual is None else
            "extra" if expected is None else "wrong")
    return {"type": kind, "expected": expected, "actual": actual}


def git_bytes(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Full immutable target commit")
    parser.add_argument("--label", required=True, help="Fresh output label")
    args = parser.parse_args()
    assert re.fullmatch(r"[0-9a-f]{40}", args.target)
    assert re.fullmatch(r"[a-z0-9-]+", args.label)
    manifest, _ = verify()
    assert digest(FIX / "oracle-manifest.json") == MANIFEST_HASH
    adjudication = read(FIX / "adjudication.json")
    out = FIX / "actual" / args.label
    run = ROOT / "data/v15-check" / args.label
    assert not out.exists() and not run.exists(), "Use a fresh label; never overwrite a run"
    source = run / "source"
    source.mkdir(parents=True)
    out.mkdir(parents=True)

    archive = git_bytes("archive", "--format=tar", args.target)
    source_hashes = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        entries = []
        for entry in tar.getmembers():
            if entry.isfile() and Path(entry.name).name == ".gitignore":
                metadata = run / "archive-metadata" / (entry.name + ".txt")
                metadata.parent.mkdir(parents=True, exist_ok=True)
                metadata.write_bytes(tar.extractfile(entry).read())
            else:
                entries.append(entry)
        tar.extractall(source, members=entries, filter="data")
        for entry in entries:
            if entry.isfile():
                source_hashes[entry.name] = digest(source / entry.name)

    profiles, adaptations = {}, {}
    for profile in ("tech", "ops"):
        rel = f"tests/fixtures/cn/profile/{profile}/profile.json"
        frozen_bytes = git_bytes("show", manifest["base_commit"] + ":" + rel)
        assert hashlib.sha256(frozen_bytes.replace(b"\r\n", b"\n")).hexdigest() == manifest["source_git_blob_sha256"][rel]
        frozen = json.loads(frozen_bytes)
        target = json.loads(git_bytes("show", args.target + ":" + rel))
        adapted = deepcopy(frozen)
        if "acceptable_cities" not in adapted["availability"]:
            adapted["availability"]["acceptable_cities"] = []
            adaptations[profile] = "Add availability.acceptable_cities=[] to the temporary run copy only"
        assert adapted == target, "Unexpected profile change needs an explicit mapping"
        path = run / "profiles" / profile / "profile.json"
        write(path, adapted)
        profiles[profile] = path

    commands = []

    def cli(*arguments, store=run / "parsed"):
        options = [] if arguments[:2] == ("jd", "validate") else ["--data-dir", str(store)]
        argv = [sys.executable, "-m", "jobsearch_cn", *map(str, arguments), *options]
        process = subprocess.run(argv, cwd=source, capture_output=True, encoding="utf-8",
                                 env={**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(source)})

        def safe(value):
            return value.replace(str(source), "<target-archive>").replace(str(ROOT), "<workspace>")

        logged = {"command": ["python", *[safe(value) for value in argv[1:]]],
                  "exit_code": process.returncode, "stderr": safe(process.stderr)}
        commands.append(logged)
        write(out / "commands.json", commands)
        assert process.returncode == 0 and not process.stderr.strip(), logged
        return json.loads(process.stdout)

    baseline_dir = FIX / "actual/master-e99470e"
    counts = Counter()
    summary = {
        "target_commit": args.target,
        "baseline_commit": manifest["base_commit"],
        "manifest_sha256": MANIFEST_HASH,
        "adjudication_sha256": digest(FIX / "adjudication.json"),
        "archive_sha256": hashlib.sha256(archive).hexdigest(),
        "profile_adaptations": adaptations,
        "python_version": sys.version.split()[0],
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "cases": {},
    }
    for path in sorted(FIX.glob("*.expected.json")):
        oracle = read(path)
        key = path.name.removesuffix(".expected.json")
        ruling = adjudication["fixtures"].get(key, {})
        expected_skills = [*oracle["fields"]["requirements.skills"]["value"],
                           *ruling.get("adjudicated_skills", [])]
        parsed = cli("jd", "parse", FIX / oracle["fixture"], "--site", oracle["site_argument"], "--save")
        assert len(parsed["jobs"]) == 1
        job = parsed["jobs"][0]
        fields = {}
        for field, entry in oracle["fields"].items():
            expected = expected_skills if field == "requirements.skills" else entry["value"]
            fields[field] = classify(field, expected, get(job, field))
            counts["fields_" + fields[field]["type"]] += 1
        skill_result = fields["requirements.skills"]
        counts["skills_expected"] += len(expected_skills)
        counts["skills_hit"] += len(expected_skills) - len(skill_result["missing"])
        counts["skills_missing"] += len(skill_result["missing"])
        counts["skills_extra"] += len(skill_result["extra"])

        probes = []
        for probe in [*oracle["version_probes"], *ruling.get("probes", [])]:
            if probe.get("decision") == "must_not_map_console_to_photoshop":
                passed = not {norm(value) for value in job["requirements"]["skills"]} & {"ps", "photoshop", "ps4", "ps5"}
                counts["console_probes_total"] += 1
                counts["console_probes_passed"] += passed
            else:
                passed = norm(probe["expected_skill"]) in {norm(value) for value in job["requirements"]["skills"]}
                counter = "intrinsic_digit" if probe.get("decision") == "must_keep_intrinsic_digit" else "version"
                counts[counter + "_probes_total"] += 1
                counts[counter + "_probes_passed"] += passed
            probes.append({**probe, "passed": passed})

        evidence = {}
        for field, comparison in fields.items():
            if comparison["actual"] is None or comparison["actual"] == []:
                continue
            item = job["evidence"].get(field)
            quotes = item.get("text") if item else None
            quotes = quotes if isinstance(quotes, list) else [quotes]
            verbatim = bool(quotes) and all(isinstance(quote, str) and quote and quote in job["raw_text"] for quote in quotes)
            evidence[field] = {"evidence": item, "verbatim": verbatim}
            counts["evidence_values"] += 1
            counts["evidence_verbatim"] += verbatim

        manual = deepcopy(job)
        for field, entry in oracle["fields"].items():
            value = expected_skills if field == "requirements.skills" else entry["value"]
            put(manual, field, value)
            if value is None or value == []:
                manual["evidence"].pop(field, None)
            else:
                quote = entry["evidence"]
                if field == "requirements.skills" and ruling:
                    quote = [*quote, *[probe["text"] for probe in ruling["probes"]]]
                manual["evidence"][field] = {"text": quote, "method": "agent"}
        for field, entry in oracle["additional_fields"].items():
            put(manual, field, entry["value"])
        manual_path = run / "manual-input" / (key + ".json")
        write(manual_path, manual)
        validated = cli("jd", "validate", manual_path)
        counts["manual_valid"] += validated["valid"]
        saved = cli("jd", "save", manual_path, store=run / "manual")
        counts["manual_saved"] += len(saved["saved"]) == 1

        record = {"parse": parsed, "fields": fields, "evidence": evidence, "probes": probes,
                  "manual_job": manual, "manual_validate": validated, "manual_save": saved, "profiles": {}}
        for profile, profile_path in profiles.items():
            filtered = cli("match", "filter", job["id"], "--profile", profile_path)
            replay = cli("match", "filter", job["id"], "--profile", profile_path, store=run / "manual")
            human = oracle["human_match"][profile]
            comparisons = {}
            for label, result in (("parsed", filtered), ("manual", replay)):
                observed = {check["check"]: check["result"] for check in result["checks"]}
                differences = {name: {"expected": entry["result"], "actual": observed[name]}
                               for name, entry in human["checks"].items() if entry["result"] != observed[name]}
                additional = {name: value for name, value in observed.items() if name not in human["checks"]}
                counts[label + "_old_checks_equal"] += len(human["checks"]) - len(differences)
                counts[label + "_verdicts_equal"] += result["verdict"] == human["verdict"]
                comparisons[label] = {"expected_verdict": human["verdict"], "actual_verdict": result["verdict"],
                                      "old_check_differences": differences, "additional_checks": additional}
            record["profiles"][profile] = {"filter": filtered, "manual_filter": replay, "comparison": comparisons}

        old_job = read(baseline_dir / (key + ".json"))["parse"]["jobs"][0]
        changed = {field: {"before": get(old_job, field), "after": get(job, field)}
                   for field in oracle["fields"] if get(old_job, field) != get(job, field)}
        case = {"field_groups_equal": sum(value["type"] == "match" for value in fields.values()),
                "differences": {field: value for field, value in fields.items() if value["type"] != "match"},
                "changes_from_baseline": changed, "skills": skill_result, "probes": probes,
                "profiles": {profile: value["comparison"] for profile, value in record["profiles"].items()}}
        summary["cases"][key] = case
        record["comparison"] = case
        write(out / (key + ".json"), record)
        print(key, f"fields {case['field_groups_equal']}/14", "missing", skill_result["missing"],
              "extra", skill_result["extra"], flush=True)

    supplemental = {}
    for probe in adjudication["supplemental_probes"]:
        probe_path = run / "supplemental" / (probe["id"] + ".txt")
        probe_path.parent.mkdir(parents=True, exist_ok=True)
        probe_path.write_text(probe["text"] + "\n", encoding="utf-8", newline="\n")
        parsed = cli("jd", "parse", probe_path, "--site", "ats", store=run / "supplemental-store")
        assert len(parsed["jobs"]) == 1
        job = parsed["jobs"][0]
        comparison = classify("requirements.skills", probe["expected_skills"], job["requirements"]["skills"])
        counts["supplemental_probes_total"] += 1
        counts["supplemental_probes_passed"] += comparison["type"] == "match"
        supplemental[probe["id"]] = {"expected": probe["expected_skills"],
                                     "actual": job["requirements"]["skills"],
                                     "comparison": comparison,
                                     "evidence": job["evidence"].get("requirements.skills")}

    verify()
    assert all(digest(source / name) == value for name, value in source_hashes.items()), "Target archive changed"
    summary.update({"supplemental_ruling_probes": supplemental,
                    "counts": dict(counts), "successful_cli_calls": len(commands),
                    "frozen_files_verified": len(manifest["oracle_files_lf_sha256"]),
                    "source_archive_unchanged": True,
                    "finished_at_utc": datetime.now(timezone.utc).isoformat()})
    write(out / "summary.json", summary)
    print(json.dumps(summary["counts"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
