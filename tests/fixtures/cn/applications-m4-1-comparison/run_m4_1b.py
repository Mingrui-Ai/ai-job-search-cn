"""Run B01-B30 without changing the V25 oracle or the earlier M4-1a runner.

Exit zero means evidence was collected, not that every scenario passed. The only test clock override
is a separately recorded B11 replay to create its historical follow-up dates through product commands.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import run_comparison as old


HEAD = "9db32876cde23bf2db1097b9a3599362cd0cbbeb"
RULING = "https://github.com/Mingrui-Ai/ai-job-search-cn/pull/126#issuecomment-6623727633"
REVIEW = "https://github.com/Mingrui-Ai/ai-job-search-cn/pull/126#issuecomment-6623854046"


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(old.sanitize(json.dumps(value, ensure_ascii=False, indent=2)) + "\n", encoding="utf-8", newline="\n")


class Context(old.Ctx):
    def __init__(self, sid, setup, clock=None):
        self.clock = clock
        self.steps = []
        self.states = []
        self.ruling_checks = []
        self.backup_result = None
        super().__init__(sid, setup)

    def raw(self, argv, data=True, cwd=None):
        args = list(map(str, argv))
        if data:
            args += ["--data-dir", str(self.data)]
        full = [sys.executable, "-m", "jobsearch_cn", *args]
        if self.clock:
            code = ("import sys;from datetime import date;from jobsearch_cn import applications,cli;"
                    "applications._today=lambda:date.fromisoformat(sys.argv[1]);"
                    "sys.exit(cli.main(sys.argv[2:]))")
            full = [sys.executable, "-c", code, self.clock, *args]
        env = {k: v for k, v in os.environ.items() if k != "JOBSEARCH_CN_DATA_DIR"}
        env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONPATH=str(old.OPTS.repo))
        proc = subprocess.run(full, cwd=cwd or old.OPTS.repo, capture_output=True, env=env, timeout=120)
        result = old.R(argv, (proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8")))
        self.log.append({"argv": args, "exit": result.exit, "stdout": result.stdout, "stderr": result.stderr,
                         "test_today_override": self.clock})
        return result

    def rule(self, desc, ok, detail=None):
        self.ruling_checks.append({"check": desc, "ok": bool(ok), "detail": detail})

    def preview(self, argv):
        before = old.tree(self.data)
        result = super().preview(argv)
        self.check("preview is read-only: " + argv[0], old.tree(self.data) == before)
        return result

    def checked_write(self, argv, desc):
        result = self.write(argv)
        self.check(desc, result.exit == 0, result.stderr)
        return result


def argv_for(c, text):
    # The frozen command strings intentionally leave multiword --summary/--text values unquoted.
    # Split at flags first, keeping the entire text value together; never execute them in a shell.
    pieces = re.split(r"\s+(?=--[a-z])", text)
    args = pieces[0].split()
    for piece in pieces[1:]:
        flag, _, value = piece.partition(" ")
        args.append(flag)
        if value:
            args.append(value)
    values = {"{JOB_A}": old.JOB_A, "{JOB_B}": old.JOB_B, "{APP}": c.app,
              "{MAT_A}": str(c.data / "materials" / old.JOB_A / "resume-1.json"),
              "{PDF_A}": str(c.data / "resumes" / old.JOB_A / "resume-1.pdf")}
    if "{REV}" in args:
        values["{REV}"] = str(c.rev())
    return [values.get(arg, arg) for arg in args]


def check_step(c, index, step, result, before):
    want = step["expect"] or {}
    name = f"step {index + 1} {step['cmd'].split()[0]}"
    if want.get("result") in ("accepted", "rejected"):
        c.check(name + " result", (result.exit == 0) == (want["result"] == "accepted"), result.exit)
    if isinstance(want.get("exit"), int):
        c.check(name + " exit", result.exit == want["exit"], result.exit)
    if want.get("error") not in (None, "impl"):
        c.check(name + " error", result.error == want["error"], result.error)
    if isinstance(want.get("warning"), bool):
        c.check(name + " warning", bool(result.warnings) == want["warning"], result.warnings)
        # B21's step says warning=false, while its final check requires contact warnings.
        if c.sid == "B21" and step["cmd"] == "validate":
            c.checks[-1]["ruling_ok"] = bool(result.warnings)
            c.checks[-1]["ruling_basis"] = "plan 2.7(5); frozen B21 final check also requires these warnings"
    if want.get("writes") is False or result.exit != 0 or step["mode"] == "read":
        c.check(name + " data unchanged", old.tree(c.data) == before)
    if "valid" in want:
        c.check(name + " valid", isinstance(result.out, dict) and result.out.get("valid") == want["valid"])
    if want.get("result") == "impl" or want.get("exit") == "impl":
        c.note(name, {"exit": result.exit, "error": result.error, "output": result.out})


def valid(c, desc="validate replays the stored projection"):
    result = c.app_cmd(["validate"])
    c.check(desc, result.exit == 0 and result.out.get("valid") is True and not result.out.get("errors"), result.out)
    return result


def b11(c):
    ids = {}
    for label, due, state in (("P", "2026-11-05", "applied"), ("Q", "2026-11-20", "applied"),
                              ("R", None, "applied"), ("D", None, "drafted"),
                              ("X", "2026-11-05", "rejected"), ("I", "2026-11-01", "interview")):
        r = c.checked_write(old.REC_A if state == "drafted" else old.REC_A_SUB, "setup " + label + " record")
        ids[label] = c.app
        if due:
            c.checked_write(["followup", c.app, "--due", due, "--expected-revision", c.rev()], "setup " + label + " followup")
        if state in ("rejected", "interview"):
            c.checked_write(["status", c.app, state, "--expected-revision", c.rev()], "setup " + label + " status")
    before = old.tree(c.data)
    result = c.app_cmd(["list", "--due", "--as-of", "2026-11-10"])
    c.check("list due accepts and is read-only", result.exit == 0 and old.tree(c.data) == before)
    out = result.out or {}
    c.check("due includes I then P", [a["application_id"] for a in out.get("due", [])] == [ids["I"], ids["P"]], out)
    c.check("unset includes R only", [a["application_id"] for a in out.get("unset", [])] == [ids["R"]], out)
    c.rule("plan 2.3 overdue days", [a["days_overdue"] for a in out.get("due", [])] == [9, 5], out)
    c.rule("plan 2.3 as_of", out.get("as_of") == "2026-11-10")
    valid(c)


def inspect(c):
    repo = old.OPTS.repo
    if c.sid == "B26":
        paths = [".claude/skills/cn-application/SKILL.md", ".dsh/skills/cn-application/SKILL.md", "AGENTS.md"]
        texts = {p: (repo / p).read_text(encoding="utf-8") for p in paths}
        for path, text in texts.items():
            c.check("entry points to shared workflow: " + path, "docs/cn/applications.md" in text)
        coverage = (repo / "tests/test_cn_agent_entry.py").read_text(encoding="utf-8")
        c.check("entry test includes cn-application", "cn-application" in coverage)
        c.note("approved entry count", 3)
        workflow = (repo / "docs/cn/applications.md").read_text(encoding="utf-8").split("## 16.", 1)[1]
        for word in ("--preview", "用户明确同意", "--request-id", "--actor", "codex", "/outcome", "/apply"):
            c.rule("shared workflow contains " + word, word in workflow)
        commands = [[sys.executable, "tools/lint_skills.py"],
                    [sys.executable, "-m", "unittest", "tests.test_cn_agent_entry", "-q"]]
    elif c.sid == "B27":
        grant = "Bash(python -m jobsearch_cn application:*)"
        for path in ("tools/security_guards.py", ".claude/settings.json", ".claude/skills/cn-application/SKILL.md"):
            c.check("application grant in " + path, grant in (repo / path).read_text(encoding="utf-8"))
        c.note("approved settings", ".claude/settings.json and two security_guards allowlists; no changes by verifier")
        commands = [[sys.executable, "tools/security_guards.py"]]
    else:
        text = (repo / "docs/cn/applications.md").read_text(encoding="utf-8")
        names = sorted(set(re.findall(r"python -m jobsearch_cn application ([a-z]+)", text)))
        c.check("documented command list nonempty", len(names) >= 10, names)
        for name in names:
            c.check("documented command --help: " + name, c.raw(["application", name, "--help"], data=False).exit == 0)
        resume = (repo / "docs/cn/resume-workflow.md").read_text(encoding="utf-8")
        c.check("handoff links application workflow", "applications.md" in resume.split("交给用户", 1)[1])
        commands = []
    for args in commands:
        proc = subprocess.run(args, cwd=repo, capture_output=True, encoding="utf-8", timeout=120,
                              env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        c.log.append({"argv": args[1:], "exit": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
        c.check("inspection check: " + " ".join(args[1:]), proc.returncode == 0, proc.stderr)


def restore(c):
    source = Path(c.backup_result.out["path"])
    target = c.work / "restored"
    (target / "applications").mkdir(parents=True)
    shutil.copy2(source / "applications.sqlite3", target / "applications/applications.sqlite3")
    shutil.copytree(source / "artifacts", target / "applications/artifacts")
    shutil.copytree(c.data / "jobs", target / "jobs")
    c.original_data, c.data = c.data, target


def final_checks(c, sid):
    app = c.show() if c.app else None
    events = app.get("events", []) if app else []
    last = events[-1] if events else {}
    if sid == "B01":
        c.check("reply payload, date, unchanged status and revision", last.get("type") == "reply_received"
                and last.get("payload") == {"summary": "对方约下周电话沟通"} and last.get("occurred_on") == "2026-10-30"
                and app["status"] == "applied" and app["revision"] == 3)
    elif sid == "B02":
        c.check("only 300-character reply recorded", len(events) == 3 and len(last["payload"]["summary"]) == 300)
    elif sid == "B03":
        c.check("undated reply has two null dates", last.get("type") == "reply_received"
                and last.get("occurred_at") is None and last.get("occurred_on") is None and len(events) == 3)
    elif sid == "B04":
        c.check("draft reply leaves status unchanged", app["status"] == "drafted")
        c.rule("plan 2.1 draft reply transition", c.steps[1]["exit"] == 1 and c.steps[1]["error"] == "transition")
    elif sid == "B05":
        c.check("note text, revision, unchanged status", last.get("type") == "note_added"
                and last.get("payload") == {"text": "二面约在周四"} and app["revision"] == 3 and app["status"] == "applied")
        c.rule("plan 2.7 note has no occurrence date", last.get("occurred_at") is None and last.get("occurred_on") is None)
    elif sid == "B06":
        c.check("terminal status unchanged", app["status"] == "rejected")
        c.rule("plan 2.1 terminal note accepted", c.steps[-1]["exit"] == 0 and last["type"] == "note_added")
    elif sid == "B07":
        c.check("scheduled payload and cancel clear date", c.states[1]["next_followup_on"] == "2026-11-10"
                and events[2]["payload"] == {"due_on": "2026-11-10"} and events[2]["type"] == "followup_scheduled"
                and app["next_followup_on"] is None and last["type"] == "followup_cancelled" and len(events) == 4)
    elif sid == "B08":
        c.check("invalid due dates append nothing", len(events) == 2 and app["next_followup_on"] is None)
    elif sid == "B09":
        c.rule("plan 2.2 past followup invalid", c.steps[-1]["exit"] == 1 and c.steps[-1]["error"] == "invalid")
    elif sid == "B10":
        c.check("terminal status clears followup", app["status"] == "rejected" and app["next_followup_on"] is None)
    elif sid == "B12":
        out = c.steps[0]["output"] or {}
        today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        c.check("missing database not created", not c.db.exists())
        c.rule("plan 2.3 default date and empty lists", c.steps[0]["exit"] == 0 and out.get("as_of") == today
               and out.get("due") == [] and out.get("unset") == [], out)
    elif sid in ("B13", "B14", "B29"):
        target, void = events[2:4]
        c.check("void keeps target and links both ways", target["type"] == "status_changed"
                and target["voided_by"] == void["event_id"] and void["type"] == "event_voided"
                and void["payload"]["target_event_id"] == target["event_id"] and bool(void["payload"]["reason"]))
        expected = {"B13": ("applied", 4), "B14": ("interview", 5), "B29": ("interview", 6)}[sid]
        c.check("void and subsequent actions replay correctly", (app["status"], app["revision"]) == expected and len(events) == expected[1])
        c.check("immediately after void status applied", c.states[2]["status"] == "applied")
    elif sid == "B15":
        c.check("void submitted returns drafted and null materials", app["status"] == "drafted"
                and app["submission"]["confirmed"] is False and app["submission"]["materials_recorded"] is None)
        c.check("archives unchanged by void", old.tree(c.appdir / "artifacts") == c.before_void_artifacts)
        c.rule("plan 2.4 material versions retained", len(app["material_versions"]) == 1)
        result = valid(c)
        c.check("voided materials not orphaned", not result.out["orphans"])
    elif sid == "B16":
        c.check("void restores previous followup", app["next_followup_on"] == "2026-11-10")
    elif sid == "B17":
        c.check("continuous void targets latest live event", len(events) == 5 and events[2]["voided_by"] == events[3]["event_id"]
                and events[1]["voided_by"] == events[4]["event_id"] and events[3]["voided_by"] is None)
        c.rule("plan 2.4 second void is submitted", app["status"] == "drafted" and app["submission"]["confirmed"] is False)
    elif sid == "B18":
        c.rule("plan 2.4 created cannot be voided", c.steps[-1]["exit"] == 1 and c.steps[-1]["error"] == "invalid" and len(events) == 1)
    elif sid == "B20":
        c.check("record submitted event voided, created survives", app["status"] == "drafted" and len(events) == 3
                and events[0]["voided_by"] is None and events[1]["voided_by"] == events[2]["event_id"])
    elif sid == "B21":
        out = c.steps[-1]["output"] or {}
        c.check("validate warns for phone email and URL", out.get("valid") is True and all(old.kinds_of(out.get("warnings", [])).values()), out)
    elif sid == "B22":
        c.check("retry and conflict do not duplicate events", len(events) == 3 and last["payload"] == {"text": "一面"})
        c.check("retry returns original event", c.steps[1]["output"] == {k: v for k, v in c.steps[2]["output"].items() if k != "repeated"}
                or c.steps[2]["output"].get("application") == c.steps[1]["output"].get("application"))
    elif sid in ("B23", "B25"):
        result = c.backup_result
        folder = Path(result.out["path"])
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        c.check("backup manifest and database digest", old.sha(folder / "applications.sqlite3") == manifest["database"]["sha256"])
        c.check("backup copies every listed attachment", bool(manifest["artifacts"]) and all(
            (folder / item["path"]).is_file() and old.sha(folder / item["path"]) == item["sha256"] for item in manifest["artifacts"]))
        c.rule("plan 2.5 backup validates independently", manifest["source_valid"] is True)
        if sid == "B23":
            restore(c)
        c.check("restored export equals source", old.strip_exported_at(c.export().stdout) == c.backup_export)
        valid(c, "restored database and archive validate")
    elif sid == "B24":
        c.check("missing database does not create empty backup", not c.appdir.exists())
        c.rule("backup without records not_found", c.steps[0]["exit"] == 1 and c.steps[0]["error"] == "not_found")
    elif sid == "B30":
        out = c.steps[-1]["output"]
        c.check("only referral due, portal unset", len(out["due"]) == len(out["unset"]) == 1
                and out["due"][0]["application_id"] == c.app and out["due"][0]["channel"]["kind"] == "referral"
                and out["unset"][0]["channel"]["kind"] == "portal"
                and out["due"][0]["job_id"] == out["unset"][0]["job_id"] == old.JOB_A)
    if c.db.exists() and sid not in ("B15", "B23", "B25"):
        valid(c)


def impl_controls(c, sid):
    """Exercise the explicitly open impl_check items against the approved plan, separately from strict checks."""
    if sid == "B04":
        for state in ("hired", "rejected", "withdrawn", "offer_declined"):
            recorded = c.write(old.REC_A_SUB)
            c.rule("terminal reply control setup", recorded.exit == 0)
            for target in ({"hired": ["offer", "hired"], "offer_declined": ["offer", "offer_declined"]}.get(state, [state])):
                result = c.write(["status", c.app, target, "--expected-revision", c.rev()])
                c.rule("terminal reply setup " + target, result.exit == 0)
            result = c.write(["reply", c.app, "--summary", "对方提供反馈", "--expected-revision", c.rev()])
            c.rule("plan 2.1 submitted terminal reply: " + state, result.exit == 0 and c.show()["status"] == state)
    elif sid == "B05":
        for flag, value in (("--on", "2026-10-30"), ("--at", "2026-10-30T09:00+08:00")):
            before = old.tree(c.data)
            result = c.preview(["note", c.app, "--text", "备注", "--expected-revision", c.rev(), flag, value])
            c.rule("plan 2.7 note does not accept " + flag, result.exit == 2 and old.tree(c.data) == before)
    elif sid == "B09":
        for state in ("drafted", "no_response", "hired", "rejected", "withdrawn", "offer_declined"):
            old.path_record(c, state)
            for option in (["--due", "2026-11-10"], ["--cancel"]):
                before = old.tree(c.data)
                result = c.write(["followup", c.app, *option, "--expected-revision", c.rev()])
                c.rule("plan 2.1 followup forbidden: " + state + " " + option[0], result.exit == 1
                       and result.error == "transition" and old.tree(c.data) == before, result.stderr)
    if sid in ("B04", "B05", "B09"):
        result = c.app_cmd(["validate"])
        c.rule("impl controls leave valid records", result.exit == 0 and result.out.get("valid") is True)


def run_case(c, case):
    sid = case["id"]
    if sid == "B11":
        return b11(c)
    if sid in ("B26", "B27", "B28"):
        return inspect(c)
    for index, step in enumerate(case["steps"]):
        if step["mode"] == "tamper":
            restore(c)
            continue
        args = argv_for(c, step["cmd"])
        before = old.tree(c.data)
        if args[0] == "void":
            c.before_void_artifacts = old.tree(c.appdir / "artifacts")
        if args[0] == "backup" and c.db.exists():
            c.backup_export = old.strip_exported_at(c.export().stdout)
            original_db, original_artifacts = old.sha(c.db), old.tree(c.appdir / "artifacts")
        mode = step["mode"]
        if mode == "two_phase":
            result = c.write(args)
        elif mode == "retry_same_request":
            result = c.commit(args, c.last_rid)
        elif mode == "reuse_request_of_prev":
            # This frozen mode explicitly reuses a prior id. Its preliminary preview can be stale;
            # the intentional conflicting commit must still be exercised with that prior id.
            c.preview(args)
            result = c.commit(args, c.last_rid)
        else:
            result = c.app_cmd(args)
        check_step(c, index, step, result, before)
        if args[0] == "backup" and result.exit == 0:
            c.backup_result = result
            c.check("backup leaves source database and archives unchanged", old.sha(c.db) == original_db
                    and old.tree(c.appdir / "artifacts") == original_artifacts)
            checked = c.app_cmd(["validate", "--backup", result.out["backup"]])
            c.rule("plan 2.5 validate --backup", checked.exit == 0 and checked.out.get("valid") is True, checked.out)
        c.steps.append({"index": index + 1, "frozen_command": step["cmd"], "expect": step["expect"],
                        "exit": result.exit, "error": result.error, "output": result.out})
        c.states.append(c.show() if c.app else None)
    final_checks(c, sid)
    impl_controls(c, sid)


def verdict(c):
    return all(x["ok"] for x in c.checks), all(x.get("ruling_ok", x["ok"]) for x in c.checks) and all(x["ok"] for x in c.ruling_checks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--typst", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.repo, args.output = args.repo.resolve(), args.output.resolve()
    if args.output.exists() or old.HOLDOUT == args.output or old.HOLDOUT in args.output.parents:
        parser.error("output must be new and outside the frozen corpus")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.repo, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=args.repo, text=True).strip()
    if head != HEAD or dirty:
        parser.error("implementation must be a clean checkout of " + HEAD)
    old.OPTS = args
    old.SANITIZE.extend([(str(args.output), "<output>"), (str(args.repo), "<repo>"),
                         (str(old.INPUTS), "<fixtures>"), (str(Path(args.typst)), "<typst>"),
                         (str(Path(sys.executable).parent), "<python>"), (str(Path.home()), "<home>")])
    args.output.mkdir(parents=True)
    verify = [sys.executable, str(old.HOLDOUT / "verify_oracle.py")]
    oracle_before = json.loads(subprocess.check_output(verify, encoding="utf-8"))
    old.make_templates()
    cases = json.loads((old.HOLDOUT / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
    results = []
    for case in [s for s in cases if s["part"] == "M4-1b"]:
        c = Context(case["id"], case["setup"])
        crash, replay = None, None
        try:
            run_case(c, case)
            strict, ruling = verdict(c)
            if case["id"] == "B11":
                replay = Context("B11-ruling", "base", clock="2026-11-01")
                run_case(replay, case)
                allowed = {"setup I followup", "due includes I then P", "unset includes R only"}
                failed = {x["check"] for x in c.checks if not x["ok"]}
                other_rules = [x for x in c.ruling_checks if x["check"] != "plan 2.3 overdue days"]
                ruling = failed <= allowed and all(x["ok"] for x in other_rules) and all(verdict(replay))
                dump(args.output / "cases/B11-historical-replay.json", {
                    "test_today_override": replay.clock, "checks": replay.checks,
                    "ruling_checks": replay.ruling_checks, "commands": replay.log})
        except Exception as exc:
            strict = ruling = False
            crash = f"{type(exc).__name__}: {exc}"
        row = {"id": case["id"], "title": case["title"], "strict_pass": strict, "ruling_pass": ruling,
               "crash": crash, "checks": c.checks, "ruling_checks": c.ruling_checks, "impl_observed": c.impl}
        results.append(row)
        dump(args.output / f"cases/{case['id']}.json", {**row, "steps": c.steps, "states": c.states, "commands": c.log})
        print(case["id"], "strict", strict, "ruling", ruling, "crash", crash, flush=True)
    oracle_after = json.loads(subprocess.check_output(verify, encoding="utf-8"))
    summary = {"tested_head": head, "implementation_clean": True, "ruling": RULING, "known_review": REVIEW,
               "oracle_before": oracle_before, "oracle_after": oracle_after, "total": len(results),
               "strict_passed": sum(r["strict_pass"] for r in results), "ruling_passed": sum(r["ruling_pass"] for r in results),
               "results": results}
    dump(args.output / "results.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, ensure_ascii=False))
    # The generated fictional databases and PDFs are local replay inputs, not publication artifacts.
    return 0


if __name__ == "__main__":
    sys.exit(main())
