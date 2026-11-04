"""Summarize recorded V23 results under the PR #123 rulings; never change an oracle."""

import argparse
import json
from pathlib import Path


DEFERRED_CLICHES = {
    "warn-cliche-greeting", "warn-cliche-email", "warn-referral-salary-and-cliche",
}
RULINGS = [
    "https://github.com/Mingrui-Ai/ai-job-search-cn/pull/123#issuecomment-6608844037",
    "https://github.com/Mingrui-Ai/ai-job-search-cn/pull/123#issuecomment-6609267907",
    "https://github.com/Mingrui-Ai/ai-job-search-cn/pull/123#issuecomment-6622522832",
]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="completed run directory outside the frozen corpus")
    args = parser.parse_args()
    results, probes = read(args.run / "results.json"), read(args.run / "probes.json")
    rows = []
    for case in results["cases"]:
        problems = list(case["problems"])
        deferred = []
        if case["id"] in DEFERRED_CLICHES:
            allowed = {"expected warn, got accept", "missing required warning: ['cliche']"}
            deferred = [problem for problem in problems if problem in allowed]
            problems = [problem for problem in problems if problem not in allowed]
        if not case["setup_ok"]:
            problems.append("setup failed")
        if case.get("builtin_template_control_same_errors") is False:
            problems.append("built-in template control differs")
        rows.append({"id": case["id"], "strict_pass": case["pass"], "ruling_pass": not problems,
                     "deferred_a6": deferred, "remaining_problems": problems})
    explicit = [probe for probe in probes if "pass_under_ruling" in probe]
    summary = {
        "implementation": results["implementation"], "rulings": RULINGS,
        "frozen_total": len(rows), "strict_passed": results["passed"],
        "ruling_passed": sum(row["ruling_pass"] for row in rows),
        "deferred_a6_cases": [row["id"] for row in rows if row["deferred_a6"]],
        "probe_total": len(probes), "added_ruling_probe_total": len(explicit),
        "added_ruling_probe_passed": sum(probe["pass_under_ruling"] for probe in explicit),
        "added_ruling_probe_failures": [probe["id"] for probe in explicit if not probe["pass_under_ruling"]],
        "scope": "Probe results are separate from the 75 frozen cases; passing those cases alone is not overall acceptance.",
        "cases": rows,
    }
    (args.run / "adjudication.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({key: value for key, value in summary.items() if key != "cases"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
