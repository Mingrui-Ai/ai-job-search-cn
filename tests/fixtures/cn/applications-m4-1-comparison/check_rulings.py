"""Read-only checks of the V25 build-note rulings, using a completed comparison run.

Run after run_comparison.py with --repo <tested tree> --run <comparison output>.
Writes ruling-checks.json in that run directory; does not change its strict results.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from run_comparison import SANITIZE, sanitize, tree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run.resolve()
    baseline = json.loads((run / "results.json").read_text(encoding="utf-8"))
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if head != baseline["tested_head"]:
        parser.error("--repo must be at the completed comparison's tested_head")
    output = run / "ruling-checks.json"
    if output.exists():
        parser.error("ruling-checks.json already exists; use a fresh comparison run")
    SANITIZE.extend([(str(run / "work"), "<work>"), (str(run), "<output>"),
                     (str(repo), "<repo>"), (str(Path.home()), "<home>")])
    records = []
    expected = {"A43": "match", "A47": "mismatch", "A48": "mismatch",
                "A49": "match", "A50": "unchecked"}
    for sid, state in expected.items():
        data = run / "work" / sid / "data"
        if not (data / "applications" / "applications.sqlite3").is_file():
            parser.error(f"missing completed scenario data: {sid}")
        before = tree(data)
        logs, docs, codes = [], {}, {}
        for command in ("export", "validate"):
            argv = ["application", command, "--data-dir", str(data)]
            proc = subprocess.run([sys.executable, "-m", "jobsearch_cn", *argv], cwd=repo,
                                  env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1"),
                                  capture_output=True, text=True, encoding="utf-8", timeout=120)
            logs.append({"argv": [sanitize(a) for a in argv], "exit": proc.returncode,
                         "stdout": sanitize(proc.stdout), "stderr": sanitize(proc.stderr)})
            codes[command] = proc.returncode
            docs[command] = json.loads(proc.stdout) if proc.returncode == 0 else {}
        apps = docs["export"].get("applications", [])
        validation = docs["validate"]
        warnings = validation.get("warnings", [])
        related = [w for w in warnings if "materials_check" in w]
        checks = [
            {"check": "export contains the expected materials_check", "ok":
             codes["export"] == 0 and len(apps) == 1
             and apps[0]["submission"]["materials_check"] == state},
            {"check": "validate exits 0, valid=true, no errors", "ok":
             codes["validate"] == 0 and validation.get("valid") is True
             and validation.get("errors") == []},
            {"check": "validate warns for mismatch/unchecked, not match", "ok":
             any(f"materials_check {state}" in w for w in related)
             if state != "match" else not related},
            {"check": "export and validate leave the entire data directory unchanged", "ok":
             tree(data) == before},
        ]
        records.append({"id": sid, "expected_materials_check": state,
                        "verdict": "pass" if all(c["ok"] for c in checks) else "fail",
                        "checks": checks, "logs": logs})
    summary = {"tested_head": head,
               "scope": "Supplementary ruling checks; excluded from the 80 strict scenario verdicts",
               "counts": {v: sum(r["verdict"] == v for r in records) for v in ("pass", "fail")},
               "checks_passed": sum(c["ok"] for r in records for c in r["checks"]),
               "checks_total": sum(len(r["checks"]) for r in records), "results": records}
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("counts", "checks_passed", "checks_total")}))
    return 1 if summary["counts"]["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
