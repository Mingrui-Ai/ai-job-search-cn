"""Compare frozen V9 inputs with an immutable git archive of PR #73 via public CLI."""
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

from run_baseline import FIXTURE, ROOT, compare, compare_filter, get, normalize, put, read, verify, write


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verdict(states):
    return "ineligible" if "conflict" in states else "needs_check" if "unknown" in states else "eligible"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="pr73-52fa555")
    parser.add_argument("--target", help="Full commit hash; preserves the original mapping and historical results")
    args = parser.parse_args()
    assert re.fullmatch(r"[a-z0-9-]+", args.label)
    mapping_path = FIXTURE / "pr73-mapping.json"
    mapping = read(mapping_path)
    manifest = read(FIXTURE / "oracle-manifest.json")
    verify(manifest)
    assert digest(FIXTURE / "oracle-manifest.json") == mapping["frozen_manifest_sha256"]
    target = args.target or mapping["target_commit"]
    assert re.fullmatch(r"[0-9a-f]{40}", target)
    out = FIXTURE / "actual" / args.label
    run = ROOT / "data/v9-check" / args.label
    assert not out.exists() and not run.exists(), "Choose a fresh label; never overwrite a run"
    source = run / "source"
    source.mkdir(parents=True)
    archive = subprocess.check_output(["git", "archive", "--format=tar", target], cwd=ROOT)
    source_hashes = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        # A nested repository's ignore rules trigger the enclosing repo's security guard.
        # Keep these configuration bytes as evidence outside the execution tree; runtime code is unchanged.
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
    # Keep the original profile inputs even when the target adds optional profile fields.
    profiles = {}
    profile_adaptations = {}
    for profile in ("tech", "ops"):
        rel = f"tests/fixtures/cn/profile/{profile}/profile.json"
        frozen_bytes = subprocess.check_output(["git", "show", f"{manifest['base_commit']}:{rel}"], cwd=ROOT)
        assert hashlib.sha256(frozen_bytes.replace(b"\r\n", b"\n")).hexdigest() == manifest["contract_and_profile_sha256"][rel]["lf_bytes"]
        target_bytes = subprocess.check_output(["git", "show", f"{target}:{rel}"], cwd=ROOT)
        frozen_profile, target_profile = json.loads(frozen_bytes), json.loads(target_bytes)
        if target_profile != frozen_profile:
            assert "acceptable_cities" not in frozen_profile["availability"]
            assert target_profile["availability"].get("acceptable_cities") == []
            upgraded = deepcopy(frozen_profile)
            upgraded["availability"]["acceptable_cities"] = []
            assert target_profile == upgraded, "Unexpected profile change requires a separate mapping"
            frozen_bytes = target_bytes
            profile_adaptations[profile] = "M2-6b requires availability.acceptable_cities; add [] in run copy only, all original values unchanged"
        path = run / "frozen-profiles" / profile / "profile.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(frozen_bytes)
        profiles[profile] = path
    commands = []
    def cli(*arguments, store=run / "parsed"):
        options = [] if arguments[:2] == ("jd", "validate") else ["--data-dir", str(store)]
        command = [sys.executable, "-m", "jobsearch_cn", *map(str, arguments), *options]
        result = subprocess.run(command, cwd=source, capture_output=True, encoding="utf-8",
                                env={**os.environ, "PYTHONPATH": str(source), "PYTHONUTF8": "1"})
        log = {"command": ["python", *[v.replace(str(ROOT), "<workspace>") for v in command[1:]]],
               "exit_code": result.returncode, "stderr": result.stderr.replace(str(ROOT), "<workspace>")}
        commands.append(log)
        write(out / "commands.json", commands)
        assert result.returncode == 0 and not result.stderr.strip(), log
        return json.loads(result.stdout)
    baseline = read(FIXTURE / "actual/master-a70dbc7-complete/summary.json")
    scheduling = read(FIXTURE / "scheduling-oracles.json")["fixtures"]
    counts = Counter()
    summary = {"target_commit": target, "profile_adaptations": profile_adaptations, "archive_sha256": hashlib.sha256(archive).hexdigest(),
               "manifest_sha256": mapping["frozen_manifest_sha256"], "mapping_sha256": digest(mapping_path),
               "python_version": sys.version.split()[0], "started_at_utc": datetime.now(timezone.utc).isoformat(),
               "cases": {}}
    for path in sorted(FIXTURE.glob("*.expected.json")):
        frozen = read(path)
        key = path.name.removesuffix(".expected.json")
        mapped = mapping["fixtures"][key]
        semantic = scheduling[frozen["fixture"]]
        parsed = cli("jd", "parse", FIXTURE / frozen["fixture"], "--site", frozen["site_argument"], "--save")
        assert len(parsed["jobs"]) == 1
        job = parsed["jobs"][0]
        fields = {k: compare(k, v["value"], get(job, k)) for k, v in frozen["fields"].items()}
        for result in fields.values():
            counts["old_fields_" + result["type"]] += 1
        want = set(map(normalize, frozen["fields"]["requirements.skills"]["value"]))
        found = set(map(normalize, job["requirements"]["skills"]))
        counts["skill_expected"] += len(want)
        counts["skill_hit"] += len(want & found)
        counts["skill_extra"] += len(found - want)
        expected_i, actual_i = mapped["interview"], job["interview"]
        new_fields = {"interview.mode": compare("mode", expected_i["mode"] if expected_i else None, actual_i["mode"] if actual_i else None),
                      "interview.cities": compare("cities", expected_i["cities"] if expected_i else [], actual_i["cities"] if actual_i else []),
                      "requirements.start": compare("requirements.start", mapped["start"], job["requirements"]["start"])}
        # Unknown interview is distinguished from an online interview whose cities are explicitly empty.
        new_fields["interview.cities"]["unknown_expected"] = expected_i is None
        new_fields["interview.cities"]["unknown_actual"] = actual_i is None
        if (expected_i is None) != (actual_i is None):
            new_fields["interview.cities"]["type"] = "missing" if actual_i is None else "extra"
        for result in new_fields.values():
            counts["new_fields_" + result["type"]] += 1
        evidence = {}
        for field in ("interview", "requirements.start"):
            value = get(job, field)
            item = job["evidence"].get(field)
            if value is not None:
                quotes = item["text"] if isinstance(item["text"], list) else [item["text"]] if item else []
                ok = bool(quotes) and all(q and q in job["raw_text"] for q in quotes)
                counts["new_evidence_values"] += 1
                counts["new_evidence_verbatim"] += ok
                evidence[field] = {"value": value, "evidence": item, "verbatim": ok}
        manual = deepcopy(job)
        for field, entry in frozen["fields"].items():
            put(manual, field, entry["value"])
            if entry["value"] is None or entry["value"] == []:
                manual["evidence"].pop(field, None)
            else:
                manual["evidence"][field] = {"text": entry["evidence"], "method": "agent"}
        for field, value, quote in (("interview", mapped["interview"], semantic["interview"]["evidence"]),
                                    ("requirements.start", mapped["start"], semantic["arrival"]["evidence"])):
            put(manual, field, value)
            if value is None:
                manual["evidence"].pop(field, None)
            else:
                manual["evidence"][field] = {"text": quote, "method": "agent"}
        manual_path = run / (key + ".manual.json")
        write(manual_path, manual)
        validation = cli("jd", "validate", manual_path)
        counts["manual_valid"] += validation["valid"]
        saved = cli("jd", "save", manual_path, store=run / "manual")
        record = {"parse": parsed, "old_fields": fields, "new_fields": new_fields, "new_evidence": evidence,
                  "manual_job": manual, "manual_validate": validation, "manual_save": saved, "profiles": {}}
        for profile, pp in profiles.items():
            filtered = cli("match", "filter", job["id"], "--profile", pp)
            replay = cli("match", "filter", job["id"], "--profile", pp, store=run / "manual")
            comparisons = {}
            for label, actual in (("parsed", filtered), ("manual", replay)):
                old = compare_filter(frozen["human_match"][profile], actual)
                checks = {c["check"]: c for c in actual["checks"]}
                new = {k: {"expected": v, "actual": checks[k]["result"], "match": checks[k]["result"] == v}
                       for k, v in mapped["new_checks"][profile].items()}
                counts[label + "_old_check_matches"] += old["check_matches"]
                counts[label + "_old_verdict_matches"] += old["verdict_match"]
                counts[label + "_new_check_matches"] += sum(v["match"] for v in new.values())
                expected_states = [c["result"] for c in frozen["human_match"][profile]["checks"].values()]
                expected_states += [v for v in mapped["new_checks"][profile].values() if v != "unknown"]
                mapped_verdict = verdict(expected_states)
                counts[label + "_mapped_verdict_matches"] += actual["verdict"] == mapped_verdict
                frozen_new = semantic["human_new_checks"][profile]
                differences = {field: {"frozen": frozen_new[old_field]["result"], "actual": checks[field]["result"]}
                               for field, old_field in (("interview", "interview"), ("start_date", "arrival"))
                               if frozen_new[old_field]["result"] != checks[field]["result"]}
                counts[label + "_frozen_scenario_check_matches"] += 2 - len(differences)
                counts[label + "_frozen_scenario_verdict_matches"] += actual["verdict"] == frozen_new["combined_verdict"]
                note = checks["interview"].get("note", "")
                travel_ok = "路费" in note and "时间" in note if mapped["travel_note_required"] else None
                inference_reason = checks["start_date"]["reason"]
                inference_ok = "推断" in inference_reason if mapped["inference_note_required"] else None
                if travel_ok is not None:
                    counts[label + "_travel_notes_expected"] += 1
                    counts[label + "_travel_notes_present"] += travel_ok
                if inference_ok is not None:
                    counts[label + "_inference_notes_expected"] += 1
                    counts[label + "_inference_notes_present"] += inference_ok
                comparisons[label] = {"old": old, "new": new, "mapped_verdict": mapped_verdict,
                                      "actual_verdict": actual["verdict"], "frozen_scenario_differences": differences,
                                      "frozen_scenario_verdict": frozen_new["combined_verdict"],
                                      "travel_note": note, "travel_note_ok": travel_ok,
                                      "inference_reason": inference_reason, "inference_note_ok": inference_ok}
            record["profiles"][profile] = {"filter": filtered, "manual_filter": replay, "comparison": comparisons}
        case = {"old_field_differences": {k: v for k, v in fields.items() if v["type"] != "match"},
                "new_field_differences": {k: v for k, v in new_fields.items() if v["type"] != "match"},
                "new_values": {"interview": job["interview"], "start": job["requirements"]["start"]},
                "new_evidence": evidence, "profiles": {p: r["comparison"] for p, r in record["profiles"].items()}}
        summary["cases"][key] = case
        write(out / (key + ".json"), record)
        print(key, "old", len(case["old_field_differences"]), "new", len(case["new_field_differences"]), flush=True)
    verify(manifest)
    assert all(digest(source / p) == h for p, h in source_hashes.items()), "Target archive source modified"
    summary.update({"counts": dict(counts), "baseline_counts": baseline["counts"], "successful_cli_calls": len(commands),
                    "frozen_files_verified": len(manifest["oracle_files_sha256"]), "source_archive_unchanged": True,
                    "finished_at_utc": datetime.now(timezone.utc).isoformat()})
    write(out / "summary.json", summary)
    print(json.dumps(summary["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
