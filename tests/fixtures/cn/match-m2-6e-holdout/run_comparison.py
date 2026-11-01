"""Run V19's frozen cases against the exact #93 head without changing the oracle."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from verify_oracle import FIX, FROZEN_NAMES, digest, read, verify

ROOT = FIX.parents[3]
TARGET = "50b383e95a7c18c824ad9d4f8d036b22986148d1"
MANIFEST_HASH = "616aecd87d096684f633874cc26735d9de61d85dac1a2a5128538a28984ae032"
WEEKS = Fraction(52)


def git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd)


def rounded(value):
    if value is None:
        return None
    return int(value + Fraction(1, 2))


def in_months(amount, unit, days):
    amount = Fraction(str(amount))
    if unit == "CNY/month":
        return amount
    if unit == "CNY/year":
        return amount / 12
    if unit == "CNY/day" and days is not None:
        return amount * Fraction(str(days)) * WEEKS / 12
    return None


def semantic_result(job, profile):
    """Recompute only the public M2-6e contract from parsed fields, independent of score.py."""
    salary = job.get("salary") or {}
    amount = salary.get("min") if salary.get("min") is not None else salary.get("max")
    target = profile["target"]
    days = (job.get("requirements") or {}).get("days_per_week")
    if days is None:
        days = target["salary_days_per_week"]
    pay = None if amount is None else in_months(amount, salary.get("unit"), days)
    meals = (job.get("benefits") or {}).get("meals")
    if pay is not None and meals:
        if meals.get("per_day") in (2, 3, None):
            value = target["meal_value"]
            extra = in_months(value["amount"], value["unit"], days)
            pay = None if extra is None else pay + extra
        allowance = meals.get("allowance")
        if pay is not None and allowance:
            extra = in_months(allowance["amount"], allowance["unit"], days)
            pay = None if extra is None else pay + extra
    if pay is None:
        return None, None
    minimum = Fraction(str(target["salary_min"]["amount"]))
    ideal = Fraction(str(target["salary_ideal"]["amount"]))
    step = Fraction(str(target["salary_step"]))
    if pay < minimum:
        score = max(Fraction(0), 50 - 10 * (minimum - pay) / step)
    elif pay <= ideal:
        score = Fraction(50)
    else:
        score = min(Fraction(100), 50 + 10 * (pay - ideal) / step)
    if meals and meals.get("per_day") == 1:
        score = min(Fraction(100), score + Fraction(str(target["one_meal_points"])))
    return pay, rounded(score)


def issue_kind(expected, actual):
    if expected is None and actual is None:
        return None
    if expected is None:
        return "overread"
    if actual is None:
        return "missed"
    if expected != actual:
        return "wrong"
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="clean detached checkout at the exact PR head")
    parser.add_argument("--label", default="pr93-50b383e", help="new output label; never overwrite an earlier run")
    args = parser.parse_args()
    repo = args.repo.resolve()
    assert git("rev-parse", "HEAD", cwd=repo).decode().strip() == TARGET
    assert not git("status", "--porcelain", "--", "jobsearch_cn", "tools", cwd=repo).strip()
    assert digest(FIX / "oracle-manifest.json") == MANIFEST_HASH
    verify()
    frozen_commit = "f6f87bb"
    for name in [*FROZEN_NAMES, "oracle-manifest.json"]:
        relative = (FIX / name).relative_to(ROOT).as_posix()
        assert git("show", f"{frozen_commit}:{relative}") == (FIX / name).read_bytes(), name
    assert re.fullmatch(r"pr93-[a-f0-9]{7}(?:-[a-z0-9]+)?", args.label)
    out = FIX / "actual" / args.label
    data = ROOT / "data" / ("v19-" + args.label)
    assert not out.exists() and not data.exists(), "Never overwrite a recorded comparison."
    out.mkdir(parents=True)
    (data / "profile").mkdir(parents=True)

    mapping = read("comparison-mapping.json")
    assert mapping["target_commit"] == TARGET
    profile = read("baseline-profile.json")
    profile["graduation"] = None
    profile["target"].update(mapping["profile_additions"])
    (data / "profile" / "profile.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    commands = []

    def safe(value):
        if isinstance(value, str):
            for path, label in ((data, "<data-dir>"), (repo, "<target-repo>"), (ROOT, "<workspace>")):
                value = value.replace(str(path), label).replace(path.as_posix(), label)
            return value
        if isinstance(value, list):
            return [safe(item) for item in value]
        if isinstance(value, dict):
            return {key: safe(item) for key, item in value.items()}
        return value

    def write(name, value):
        (out / name).write_text(
            json.dumps(safe(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

    def cli(*tail):
        command = [sys.executable, "-m", "jobsearch_cn", *map(str, tail), "--data-dir", str(data)]
        result = subprocess.run(
            command, cwd=repo, capture_output=True, encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(repo)},
        )
        record = {"command": ["python", *command[1:]], "exit_code": result.returncode, "stderr": result.stderr}
        if result.returncode:
            record["stdout_on_failure"] = result.stdout
        commands.append(record)
        write("commands.json", commands)
        assert result.returncode == 0, (tail[:2], result.returncode, "see commands.json")
        assert not result.stderr.strip(), tail[:2]
        return json.loads(result.stdout)

    write("profile-projection.json", profile)
    validation = cli("profile", "validate")
    write("profile-validation.json", validation)
    frozen = {case["id"]: case for case in read("expectations.json")["cases"]}
    summary = {
        "target_commit": TARGET,
        "frozen_commit": frozen_commit,
        "manifest_sha256": MANIFEST_HASH,
        "python_version": sys.version.split()[0],
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "profile_additions": mapping["profile_additions"],
        "cases": [],
    }
    issues = []
    for case_id, expected in mapping["cases"].items():
        oracle = frozen[case_id]
        parsed = cli("jd", "parse", FIX / oracle["fixture"], "--site", "other", "--save")
        assert len(parsed["jobs"]) == 1
        job = parsed["jobs"][0]
        scored = cli("match", "score", job["id"])
        write(case_id + "-parse.json", parsed)
        write(case_id + "-score.json", scored)
        actual_meals = (job.get("benefits") or {}).get("meals")
        monthly, independent_score = semantic_result(job, profile)
        product_score = scored["dimensions"]["salary"]["score"]
        salary_issue = issue_kind(oracle["salary"], job.get("salary"))
        meals_issue = issue_kind(expected["meals"], actual_meals)
        for field, kind in (("salary", salary_issue), ("benefits.meals", meals_issue)):
            if kind:
                issues.append({"id": case_id, "field": field, "kind": kind})
        result = {
            "id": case_id,
            "parsed_salary": job.get("salary"),
            "parsed_meals": actual_meals,
            "comparable_monthly": None if monthly is None else float(monthly) if monthly.denominator != 1 else int(monthly),
            "independent_contract_score": independent_score,
            "product_score": product_score,
            "product_reason": scored["dimensions"]["salary"]["reason"],
            "salary_parse_issue": salary_issue,
            "meals_parse_issue": meals_issue,
            "matches_public_contract": {
                "salary": job.get("salary") == oracle["salary"],
                "meals": actual_meals == expected["meals"],
                "comparable_monthly": monthly == expected["comparable_monthly"],
                "independent_score": independent_score == expected["score"],
                "product_score": product_score == expected["score"],
                "product_equals_independent": product_score == independent_score,
            },
            "frozen_task_score_status": oracle["score_status"],
            "frozen_task_comparable_monthly": oracle["comparable_monthly"],
            "frozen_task_score": oracle["score"],
        }
        summary["cases"].append(result)
    summary["issue_counts"] = dict(Counter(item["kind"] for item in issues))
    summary["issues"] = issues
    summary["pass_counts"] = {
        key: sum(case["matches_public_contract"][key] for case in summary["cases"])
        for key in next(iter(summary["cases"]))["matches_public_contract"]
    }
    summary["commands"] = len(commands)
    verify()
    assert digest(FIX / "oracle-manifest.json") == MANIFEST_HASH
    write("summary.json", summary)
    hashes = {path.name: digest(path) for path in sorted(out.glob("*.json"))}
    write("output-manifest.json", {"sha256": hashes, "input_manifest_sha256": MANIFEST_HASH})
    print(json.dumps({"pass_counts": summary["pass_counts"], "issue_counts": summary["issue_counts"],
                      "commands": summary["commands"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
