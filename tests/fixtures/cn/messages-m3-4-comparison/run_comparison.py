#!/usr/bin/env python
"""Run the frozen V23 scenarios against one checkout of the M3-4 CLI and record what it does.

It never writes under the frozen directory and does not generate expectations. Exit 0 means the run
finished, not that the scenarios passed: read results.json. Only fictional fixtures are used, always through
an explicit --data-dir, so the user's data directory is never touched.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FROZEN = HERE.parent / "messages-m3-4-holdout"
LOCKED_HEAD = "2c84d966c673550fae95ba6bdc46ba6606145f61"
CREATED = "2026-11-01T08:00:00+08:00"
BODY_SLOTS = {"greeting": ["body"], "email": ["body", "signature"], "referral": ["body"]}
UNBOUND = re.compile(r"\{\{(\w+)\}\}")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


class Runner:
    def __init__(self, impl: Path, output: Path):
        self.impl, self.output, self.work = impl, output, output / "_work"
        self.env = {k: v for k, v in os.environ.items() if k != "JOBSEARCH_CN_DATA_DIR"}
        self.env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONPATH=str(impl), PYTHONDONTWRITEBYTECODE="1")
        self.counter = 0

    def clean(self, text: str, data: Path = None) -> str:
        pairs = [(self.impl, "<repo>"), (self.work, "<work>"), (Path(sys.executable).parent, "<python>")]
        if data:
            pairs.insert(0, (data, "<data>"))
        for path, name in pairs:
            raw = str(path)
            for form in (raw.replace("\\", "\\\\"), raw, raw.replace("\\", "/")):
                text = text.replace(form, name)
        return text

    def cli(self, *args, data: Path = None):
        full = [sys.executable, "-m", "jobsearch_cn", *map(str, args)]
        done = subprocess.run(full, cwd=self.impl, env=self.env, capture_output=True, encoding="utf-8", timeout=120)
        return {"argv": self.clean(" ".join(map(str, args)), data), "exit": done.returncode,
                "stdout": self.clean(done.stdout, data), "stderr": self.clean(done.stderr, data)}

    def profile_hash(self, profile_path: Path) -> str:
        code = ("import json,sys;from jobsearch_cn import score;"
                "print(score.profile_hash(json.load(open(sys.argv[1],encoding='utf-8'))))")
        done = subprocess.run([sys.executable, "-c", code, str(profile_path)], cwd=self.impl, env=self.env,
                              capture_output=True, encoding="utf-8", check=True)
        return done.stdout.strip()

    def data_dir(self, context: str, overrides=(), directions=None):
        """A fresh data dir with one fictional context, overrides on a copy: (dir, profile, job, setup checks)."""
        self.counter += 1
        data = self.work / f"d{self.counter:04d}"
        source = FROZEN / "contexts" / context
        shutil.copytree(source / "profile", data / "profile")
        profile, job = load(source / "profile" / "profile.json"), load(source / "job.json")
        for item in overrides:
            target = job if item["record"] == "job" else profile
            parts = item["pointer"].strip("/").split("/")
            for part in parts[:-1]:
                target = target[int(part)] if isinstance(target, list) else target[part]
            target[parts[-1]] = item["value"]
        if directions is not None:
            profile["target"]["directions"] = directions
        dump(data / "profile" / "profile.json", profile)
        job_file = data / "job-input.json"
        dump(job_file, job)
        checks = [self.cli("profile", "validate", "--data-dir", data, data=data),
                  self.cli("jd", "save", job_file, "--data-dir", data, data=data)]
        return data, profile, job, checks

    def write_template(self, data: Path, direction: str, kinds=BODY_SLOTS, revision=None, limits=None):
        doc = load(self.impl / "jobsearch_cn" / "message_templates" / f"{direction}.json")
        for kind, slots in kinds.items():
            doc[kind]["slots"] = [{"slot": slot, "required": slot == "body"} for slot in slots]
        if revision:
            doc["revision"] = revision
        for key, value in (limits or {}).items():
            kind, field = key.split(".")
            doc[kind][field] = value
        dump(data / "templates" / "messages" / f"{direction}.json", doc)


def pointer_value(record, pointer):
    for part in pointer.strip("/").split("/"):
        record = record[int(part)] if isinstance(record, list) else record[part]
    return record


def to_grammar(text, slots, mapping, records):
    """(text in the PR's grammar, refs its placeholders need)."""
    needed = []

    def one(match):
        name = match.group(1)
        if name not in slots:
            return "{" + name + "}"
        slot = slots[name]
        entry = mapping["placeholders"][f"{slot['record']}:{slot['pointer']}"]
        if entry.get("inline"):
            return str(pointer_value(records[slot["record"]], slot["pointer"]))
        if entry["ref"] and entry["ref"] not in needed:
            needed.append(entry["ref"])
        return entry["placeholder"]

    return UNBOUND.sub(one, text), needed


def frozen_final(text, slots, records):
    """The final text the frozen case means, in one substitution round, with the published date rendering."""
    def one(match):
        slot = slots.get(match.group(1))
        if slot is None:
            return "{" + match.group(1) + "}"
        value = pointer_value(records[slot["record"]], slot["pointer"])
        if slot["pointer"].endswith("start_date"):
            year, month, day = str(value).split("-")
            return f"{int(year)}年{int(month)}月{int(day)}日"
        return UNBOUND.sub(lambda m: "{" + m.group(1) + "}", str(value))

    return UNBOUND.sub(one, text)


def build_material(case, mapping, profile, job, phash):
    records = {"job": job, "profile": profile}
    slots, kind, direction = case.get("slots") or {}, case["kind"], case["context"]
    frozen_refs = case.get("refs") or []

    def piece(slot, text):
        converted, needed = to_grammar(text, slots, mapping, records)
        refs = list(frozen_refs) + [ref for ref in needed if ref not in frozen_refs]
        return {"slot": slot, "text": converted, "refs": refs} if slot else {"text": converted, "refs": refs}

    split = mapping["signature_splits"].get(case["id"])
    if split:
        assert "".join(part["text"] for part in split) == case["body"], case["id"]
        segments = [piece(part["slot"], part["text"]) for part in split]
    else:
        segments = [piece("body", case["body"])]
    return {"schema_version": 1, "kind": kind, "job_id": job["id"], "profile_hash": phash, "created": CREATED,
            "direction": direction, "template": f"{direction}/{kind}@1",
            "subject": piece(None, case["subject"]) if case.get("subject") else None, "segments": segments}


def parse_json(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


def categories(messages, table):
    return sorted(name for name, pattern in table.items() if any(re.search(pattern, m) for m in messages))


def rendered_parts(text, kind):
    text = text[:-1] if text.endswith("\n") else text
    if kind != "email":
        return None, text
    head, _, body = text.partition("\n\n")
    return head.removeprefix("标题："), body


def judge_candidate(case, expect, validate, render, mapping, records):
    report = parse_json(validate["stdout"]) or {}
    errors, warnings = report.get("errors") or [], report.get("warnings") or []
    if validate["exit"] == 1:
        actual = "reject"
    elif validate["exit"] == 0:
        actual = "warn" if warnings else "accept"
    else:
        actual = "error"
    got_err = categories(errors, mapping["error_categories"])
    got_warn = categories(warnings, mapping["warning_categories"])
    problems = []
    want = expect["outcome"]
    if want == "accept" and actual not in ("accept", "warn"):
        problems.append(f"expected accept, got {actual}")
    if want == "warn" and actual != "warn":
        problems.append(f"expected warn, got {actual}")
    if want == "reject" and actual != "reject":
        problems.append(f"expected reject, got {actual}")
    missing_err = [c for c in expect["required_error_categories"] if c not in got_err]
    missing_warn = [c for c in expect["required_warning_categories"] if c not in got_warn]
    if want == "reject" and actual == "reject" and missing_err:
        problems.append(f"rejected without the required category: {missing_err}")
    if missing_warn and actual in ("accept", "warn"):
        problems.append(f"missing required warning: {missing_warn}")

    focus = case.get("focus_field", "")
    on_subject = focus == "email_subject" or case["id"] in mapping["must_be_reported_on_subject"]
    if want == "reject" and actual == "reject":
        patterns = [mapping["error_categories"][c] for c in expect["required_error_categories"]]
        hits = [e for e in errors if any(re.search(p, e) for p in patterns)]
        if on_subject and hits and not any(e.startswith("subject") for e in hits):
            problems.append("the error is not reported on the subject")
        if focus.endswith("_body") and hits and not any(e.startswith("segments") for e in hits):
            problems.append("the error is not reported on the body")

    counts = expect.get("rendered_codepoints") or {}
    observed_counts = {}
    if actual == "reject":
        if render["exit"] != 1 or (parse_json(render["stdout"]) or {}).get("valid") is not False:
            problems.append("render did not refuse a rejected candidate")
    if want == "reject":
        for part, count in counts.items():
            prefix = "subject" if part == "subject" else "segments"
            found = [e for e in errors if e.startswith(prefix) and "characters once filled" in e]
            observed_counts[part] = int(re.search(r"(\d+) characters", found[0]).group(1)) if found else None
            if observed_counts[part] != count:
                problems.append(f"{part}: reported {observed_counts[part]} characters, frozen {count}")

    final_text_ok = None
    if render["exit"] == 0:
        subject, body = rendered_parts(render["stdout"], case["kind"])
        observed_counts = {"subject": len(subject) if subject is not None else None, "body": len(body)}
        if want != "reject":
            for part, count in counts.items():
                if observed_counts.get(part) != count:
                    problems.append(f"{part}: rendered {observed_counts.get(part)} characters, frozen {count}")
            if "rendered_utf8_bytes" in expect and len(body.encode("utf-8")) != expect["rendered_utf8_bytes"]["body"]:
                problems.append("UTF-8 byte count differs from the frozen one")
        slots = case.get("slots") or {}
        final_text_ok = body.replace("\n\n", "") == frozen_final(case["body"], slots, records)
        if case.get("subject"):
            final_text_ok = final_text_ok and subject == frozen_final(case["subject"], slots, records)
        if not final_text_ok:
            problems.append("ADAPTER: the rendered text is not the frozen text")
    elif actual in ("accept", "warn"):
        problems.append(f"render exited {render['exit']} on a passing candidate")

    offending = expect.get("offending_text")
    quoted = None if offending is None else any(offending in e for e in errors)
    return {"expected": want, "actual": actual, "pass": not problems, "problems": problems,
            "error_categories": got_err, "warning_categories": got_warn, "errors": errors, "warnings": warnings,
            "rendered_codepoints": observed_counts, "final_text_matches": final_text_ok,
            "offending_text": offending, "offending_text_quoted_in_errors": quoted}


def run_select(runner, case, expect):
    data, _, job, checks = runner.data_dir(case["context"])
    run = runner.cli("material", "template", job["id"], "--kind", case["kind"], "--direction",
                     case["requested_direction"], "--data-dir", data, data=data)
    out = parse_json(run["stdout"]) or {}
    family, kind = expect["template_family"], expect["template_kind"]
    problems = []
    if run["exit"] != 0:
        problems.append(f"exit {run['exit']}: {run['stderr'].strip()}")
    else:
        if out.get("direction") != family:
            problems.append(f"direction {out.get('direction')!r}, frozen {family!r}")
        if out.get("kind") != kind or not str(out.get("template", "")).startswith(f"{family}/{kind}@"):
            problems.append(f"template {out.get('template')!r}, frozen {family}/{kind}")
        if not (out.get("spec") or {}).get("slots"):
            problems.append("no slots in the template")
    judged = {"expected": expect["outcome"], "actual": "accept" if run["exit"] == 0 else "error", "pass": not problems,
              "problems": problems, "template": out.get("template"), "direction": out.get("direction"),
              "reason": out.get("reason")}
    return {"id": case["id"], "setup": checks, "commands": [run], "judgement": judged}


def adapt_overrides(case):
    """The frozen overrides with the grammar rewrite, on a copy: the frozen files stay as they are."""
    return [{**item, "value": UNBOUND.sub(lambda m: "{" + m.group(1) + "}", item["value"])
             if isinstance(item["value"], str) else item["value"]} for item in case.get("overrides") or []]


def run_candidate(runner, case, expect, mapping):
    data, profile, job, checks = runner.data_dir(case["context"], adapt_overrides(case))
    runner.write_template(data, case["context"])
    material = build_material(case, mapping, profile, job, runner.profile_hash(data / "profile" / "profile.json"))
    path = data / f"{case['kind']}-1.json"
    dump(path, material)
    validate = runner.cli("material", "validate", path, "--data-dir", data, data=data)
    render = runner.cli("material", "render", path, "--data-dir", data, data=data)
    judged = judge_candidate(case, expect, validate, render, mapping, {"job": job, "profile": profile})

    # Control: the same candidate against the built-in template. Slot errors are expected there; every other
    # error must be the same, which shows the one-slot template hides no rule.
    control = data / "control"
    shutil.copytree(data, control, ignore=shutil.ignore_patterns("templates", "control"))
    swapped = copy.deepcopy(material)
    for segment in swapped["segments"]:
        if segment["slot"] == "body":
            segment["slot"] = "opening"
    control_path = control / f"{case['kind']}-1.json"
    dump(control_path, swapped)
    control_run = runner.cli("material", "validate", control_path, "--data-dir", control, data=control)
    report = parse_json(control_run["stdout"]) or {}
    slot_error = re.compile(r"the required '\w+' segment is missing|\.slot: ")
    other = sorted(e for e in report.get("errors") or [] if not slot_error.search(e))
    judged["builtin_template_control_same_errors"] = other == sorted(judged["errors"])
    return {"id": case["id"], "setup": checks, "material": material, "commands": [validate, render, control_run],
            "judgement": judged}


# ---------------------------------------------------------------- probes: outside the 75, no frozen verdict

TITLE_FIELDS = ("/title", "/evidence/title/text")


def title_override(context, title):
    job = load(FROZEN / "contexts" / context / "job.json")
    raw = job["raw_text"].replace(job["title"], title)
    return [{"record": "job", "pointer": p, "value": title} for p in TITLE_FIELDS] + \
           [{"record": "job", "pointer": "/raw_text", "value": raw}]


def message(job, phash, kind, segments, subject=None, direction="tech", template=None):
    return {"schema_version": 1, "kind": kind, "job_id": job["id"], "profile_hash": phash, "created": CREATED,
            "direction": direction, "template": template or f"{direction}/{kind}@1", "subject": subject,
            "segments": segments}


def run_probes(runner):
    results = []

    def record(probe_id, rule, commands, note=None):
        results.append({"id": probe_id, "rule": rule, "note": note,
                        "exits": [c["exit"] for c in commands], "commands": commands})

    def check(probe_id, rule, context, segments, *, kind="greeting", overrides=(), subject=None, slots=True,
              limits=None, revision=None, template=None, note=None):
        data, _, job, setup = runner.data_dir(context, overrides)
        if slots:
            runner.write_template(data, context, revision=revision, limits=limits)
        phash = runner.profile_hash(data / "profile" / "profile.json")
        path = data / f"{kind}-1.json"
        dump(path, message(job, phash, kind, segments, subject, direction=context, template=template))
        commands = [runner.cli("material", "validate", path, "--data-dir", data, data=data),
                    runner.cli("material", "render", path, "--data-dir", data, data=data)]
        if any(c["exit"] for c in setup):
            note = (note or "") + f" SETUP FAILED: {setup}"
        record(probe_id, rule, commands, note)

    def seg(text, refs=()):
        return [{"slot": "body", "text": text, "refs": list(refs)}]

    def long_title(count):
        return ("示例测试岗位说明" * 30)[:count]

    # (b) substitution by render, with the built-in slots
    check("b1-render-builtin-template", "占位符由渲染代入", "tech", [
        {"slot": "opening", "text": "您好，我是{edu-v23.school}{edu-v23.major}专业的{edu-v23.level}生，想应聘贵司的{job.title}。",
         "refs": ["edu-v23", "job"]},
        {"slot": "evidence", "text": "用 Python 整理了 8 项检索校验记录。", "refs": ["proj-v23"]},
        {"slot": "availability", "text": "可以{availability.start_date}起到岗，每周{availability.days_per_week}天。",
         "refs": ["availability"]},
        {"slot": "closing", "text": "方便的话我把简历发给您。", "refs": []}], slots=False)
    check("b1-placeholder-not-on-the-list", "占位符由渲染代入：不在白名单的报错", "tech",
          seg("您好，{proj-v23.bullets}", ["proj-v23"]))

    # (b) five template families
    data, _, job, _ = runner.data_dir("tech")
    record("b2-unknown-direction", "第一版五个方向：完全不存在的方向",
           [runner.cli("material", "template", job["id"], "--kind", "greeting", "--direction", "nosuch",
                       "--data-dir", data, data=data)])
    results[-1]["templates_on_disk"] = sorted(
        p.stem for p in (runner.impl / "jobsearch_cn" / "message_templates").glob("*.json"))
    for direction in ("design", "market", "finance", "hr"):
        data, _, job, setup = runner.data_dir("default", directions=[direction])
        record(f"b2-implicit-fallback-{direction}", "不给 --direction、档案写这个方向时回退 default",
               [setup[0], runner.cli("material", "template", job["id"], "--kind", "email", "--data-dir", data, data=data)])
    data, _, job, setup = runner.data_dir("default", directions=["general"])
    record("b2-general-not-a-profile-direction", "general 不能写进档案的 target.directions（档案校验报错）", [setup[0]])
    data, _, job, setup = runner.data_dir("default")
    record("b2-no-direction-default", "档案没写方向时用 default",
           [runner.cli("material", "template", job["id"], "--kind", "email", "--data-dir", data, data=data)])
    for context in ("tech", "data", "product", "ops"):
        data, _, job, _ = runner.data_dir(context)
        record(f"b2-implicit-{context}", "不给 --direction 时按 JD 和档案选",
               [runner.cli("material", "template", job["id"], "--kind", "greeting", "--data-dir", data, data=data)])

    # (b) limits after substitution; a user file can only lower them
    job_refs = ["job"]
    check("b3-raise-greeting-limit-ignored", "用户把上限改大不生效：151 字仍拒绝", "tech", seg("{job.title}", job_refs),
          overrides=title_override("tech", long_title(151)), limits={"greeting.max_chars": 9999})
    check("b3-lower-greeting-limit-101", "用户改小上限 100：101 字拒绝", "tech", seg("{job.title}", job_refs),
          overrides=title_override("tech", long_title(101)), limits={"greeting.max_chars": 100})
    check("b3-lower-greeting-limit-100", "用户改小上限 100：100 字通过", "tech", seg("{job.title}", job_refs),
          overrides=title_override("tech", long_title(100)), limits={"greeting.max_chars": 100})
    check("b3-raise-subject-limit-ignored", "用户把标题上限改大不生效：41 字仍拒绝", "tech", seg("您好，烦请查阅申请材料。"),
          kind="email", subject={"text": "{job.title}", "refs": ["job"]},
          overrides=title_override("tech", long_title(41)), limits={"email.subject_max_chars": 200})

    # (b) drafting belongs to M3-6
    record("b4-no-draft-command", "起草流程归 M3-6：material 只有 validate、template、render，没有 --output",
           [runner.cli("material", "--help"), runner.cli("material", "render", "x.json", "--output", "y.txt")])

    # (b) job counts for numbers only
    check("b5-skill-in-title-cited-job", "job 不算技能依据：岗位名有 Rust，引 job 也拒绝", "tech",
          seg("您好，我熟练使用 Rust。", ["job"]), overrides=title_override("tech", "Rust 后端检索实习生"))
    check("b5-required-skill-cited-job", "job 不算技能依据：JD 要求 Rust，引 job 也拒绝", "tech",
          seg("您好，我熟练使用 Rust，希望了解后端检索岗位。", ["proj-v23", "job"]))
    check("b5-number-in-title-cited-job", "job 算数字依据：岗位名有 2027，引 job 通过", "tech",
          seg("您好，我想应聘 2027 届的岗位。", ["job"]), overrides=title_override("tech", "2027 届后端检索实习生"))
    check("b5-number-in-title-no-ref", "同一句不引 job：拒绝", "tech",
          seg("您好，我想应聘 2027 届的岗位。"), overrides=title_override("tech", "2027 届后端检索实习生"))
    check("b5-salary-cited-job", "引 job 也不能借薪资数字：job 的原文只有岗位名和公司名", "tech",
          seg("您好，我整理了 180 项检索校验记录，希望交流。", ["proj-v23", "job"]), kind="email",
          subject={"text": "后端检索岗位申请", "refs": []})

    # (b) template id
    check("b6-old-revision-warns", "模板 revision 变了只警告", "tech", seg("您好，希望了解岗位。"), revision=2)
    check("b6-wrong-kind-in-id", "编号的方向或种类不符报错", "tech", seg("您好，希望了解岗位。"), template="tech/email@1")

    # (b) notes.md
    check("b7-cites-notes", "沟通材料引 notes.md：validate 和 render 都报错", "tech", seg("您好，希望了解岗位。", ["notes.md"]))

    # (b) wrong material for the command
    data, _, job, _ = runner.data_dir("tech")
    runner.write_template(data, "tech")
    phash = runner.profile_hash(data / "profile" / "profile.json")
    greeting = message(job, phash, "greeting", seg("您好，希望了解岗位。"))
    named = data / "resume-1.json"
    dump(named, greeting)
    plain = data / "greeting-1.json"
    dump(plain, greeting)
    record("b8-resume-build-given-message", "resume build 拿到沟通材料：退出码 2",
           [runner.cli("resume", "build", named, "--data-dir", data, data=data),
            runner.cli("resume", "build", plain, "--data-dir", data, data=data)],
           "第一条文件名合规，走到种类检查；第二条是文件名检查先拒绝")
    record("b8-review-draft-given-message", "review draft 拿到沟通材料：退出码 2",
           [runner.cli("review", "draft", plain, "--data-dir", data, data=data)])
    resume = {"schema_version": 1, "kind": "resume", "job_id": job["id"], "profile_hash": phash, "created": CREATED,
              "summary": None, "sections": []}
    resume_path = data / "resume-2.json"
    dump(resume_path, resume)
    record("b8-render-given-resume", "material render 拿到简历：退出码 2",
           [runner.cli("material", "render", resume_path, "--data-dir", data, data=data)])

    # (a) evidence beyond the frozen wording of the same rule
    check("x1-unknown-availability-cited", "冻结规则：缺失值不能变成随时到岗；引 availability 后", "data",
          seg("您好，我随时可以到岗。", ["availability"]))
    check("x1-tomorrow-cited", "冻结规则：不能承诺比档案更早；引 availability 后", "tech",
          seg("您好，我明天即可到岗。", ["availability"]), kind="email", subject={"text": "岗位申请", "refs": []})
    check("x2-months-from-date", "冻结规则：不能承诺更长；档案 3 个月，写 12 个月（日期里的 12）", "tech",
          seg("您好，我可以连续实习 12 个月。", ["availability"]))
    check("x2-days-from-date", "冻结规则：不能多于档案；档案每周 4 天，写 7 天（日期里的 07）", "tech",
          seg("您好，我每周可以到岗 7 天，烦请告知申请方式。", ["availability"]), kind="referral")
    check("x2-control-days-5-cited", "对照：写 5 天并引 availability（日期里没有 5）", "tech",
          seg("您好，我每周可以到岗 5 天，烦请告知申请方式。", ["availability"]), kind="referral")
    check("x2-control-months-6-cited", "对照：写 6 个月并引 availability（日期里没有 6）", "tech",
          seg("您好，我可以连续实习 6 个月。", ["availability"]))
    check("x7-wechat-without-digits", "冻结规则：不能手写微信；微信号不带数字，排除冻结样例 v23 里 23 的偶然命中", "tech",
          seg("您好，微信号：fake_only_handle，方便时烦请告知申请方式。"), kind="referral")
    check("x3-residual-literal-frozen-notation", "替换值残留槽位，用冻结文件的 {{ }} 记法", "tech",
          seg("您好，想了解{job.title}的申请方式。", ["job"]), kind="referral",
          overrides=title_override("tech", "示例{{unfilled_title}}岗位"))
    check("x4-unfilled-literal-frozen-notation", "未代入槽位，用冻结文件的 {{ }} 记法", "tech",
          seg("您好，我想申请{{unfilled_role}}。"))
    check("x5-contact-email-in-body", "未拆 signature：valid-contact-from-profile 的正文原样放进 body", "tech",
          seg("您好，我是{contact.name}，希望了解岗位工作。联系邮箱：{contact.email}。"), kind="email",
          subject={"text": "岗位申请", "refs": []})
    check("x6-unknown-availability-omitted-cited", "valid-unknown-availability-omitted 加引 availability 后", "data",
          seg("您好，我做过数据字段核对，希望了解岗位安排。到岗安排尚待确认。", ["proj-v23", "availability"]))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--impl", required=True, help="a checkout of the implementation under test")
    parser.add_argument("--output", required=True, help="a directory that does not exist yet, outside the frozen one")
    args = parser.parse_args()
    impl, output = Path(args.impl).resolve(), Path(args.output).resolve()
    if output.exists() or FROZEN in output.parents:
        parser.error("--output must not exist and must be outside the frozen directory")
    head = subprocess.run(["git", "-C", str(impl), "rev-parse", "HEAD"], capture_output=True, encoding="utf-8",
                          check=True).stdout.strip()
    if head != LOCKED_HEAD:
        parser.error(f"--impl is at {head}, not {LOCKED_HEAD}")
    dirty = subprocess.run(["git", "-C", str(impl), "status", "--porcelain"], capture_output=True, encoding="utf-8",
                           check=True).stdout
    oracle = subprocess.run([sys.executable, str(FROZEN / "verify_oracle.py")], capture_output=True, encoding="utf-8",
                            env={**os.environ, "PYTHONUTF8": "1"})
    if oracle.returncode:
        parser.error(f"verify_oracle failed: {oracle.stdout}{oracle.stderr}")

    inputs, oracle_doc = load(FROZEN / "inputs.json"), load(FROZEN / "expectations.json")
    expected = {case["id"]: case for case in oracle_doc["cases"]}
    mapping = load(HERE / "comparison-mapping.json")
    output.mkdir(parents=True)
    runner = Runner(impl, output)
    summary = []
    for case in inputs["cases"]:
        if case["operation"] == "select_template":
            result = run_select(runner, case, expected[case["id"]])
        else:
            result = run_candidate(runner, case, expected[case["id"]], mapping)
        result["setup_ok"] = all(check["exit"] == 0 for check in result["setup"])
        dump(output / "cases" / f"{case['id']}.json", result)
        judged = result["judgement"]
        summary.append({"id": case["id"], "operation": case["operation"], "setup_ok": result["setup_ok"],
                        **{k: v for k, v in judged.items() if k not in ("errors", "warnings")}})
        print(case["id"], "PASS" if judged["pass"] else "FAIL", judged["problems"], flush=True)
    probes = run_probes(runner)
    dump(output / "probes.json", probes)
    shutil.rmtree(runner.work)
    passed = [row for row in summary if row["pass"]]
    dump(output / "results.json", {
        "implementation": head, "implementation_clean": not dirty, "oracle": json.loads(oracle.stdout),
        "total": len(summary), "passed": len(passed), "failed": len(summary) - len(passed),
        "setup_failures": [row["id"] for row in summary if not row["setup_ok"]], "cases": summary})
    print(f"total {len(summary)}, passed {len(passed)}, failed {len(summary) - len(passed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
