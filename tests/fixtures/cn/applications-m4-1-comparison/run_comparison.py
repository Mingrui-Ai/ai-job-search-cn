"""Run V25's frozen M4-1a scenarios against an application implementation.

Usage (repository root of the holdout clone, conda env ai-job-search-cn):

    python tests/fixtures/cn/applications-m4-1-comparison/run_comparison.py \
        --repo <tree under test> --typst <typst.exe> --output <new dir outside the frozen dirs>

Runs the product only as a subprocess (`python -m jobsearch_cn ...` with cwd=--repo), on fictional data
in fresh data directories under --output. Never writes the frozen holdout. Exit 0 means the comparison
completed; the verdicts are in results.json, not in the exit code.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOLDOUT = HERE.parent / "applications-m4-1-holdout"
INPUTS = HOLDOUT / "inputs"
JOB_A, JOB_B, JOB_C = "job_fa26c5d52ff7", "job_af4d7dd8c3a6", "job_cb7cb4d6e51d"
MAT_HASH = "ee15c290c88fcab0ca9fadf21d6f52b9fabba24ff5a0e462b271ed5905e54250"
MAT_HASH_EDITED = "3d974d1cc93641d7a9526d60f3fada3024edfbd51e10f5bf2b85a3ab716a4ea9"
PROFILE_HASH = "670f4cbd7fcb8de44ed4c1b65cb0f884e93984d6a5c55afa2e255a94cb7206a2"
STATES = ["drafted", "applied", "interview", "offer", "no_response",
          "hired", "rejected", "withdrawn", "offer_declined"]
ALLOWED = {
    "drafted": {"withdrawn"}, "applied": {"interview", "offer", "rejected", "withdrawn", "no_response"},
    "interview": {"offer", "rejected", "withdrawn", "no_response"},
    "offer": {"hired", "offer_declined", "rejected", "withdrawn"},
    "no_response": {"interview", "offer", "rejected"},
    "hired": set(), "rejected": set(), "withdrawn": set(), "offer_declined": set(),
}
REC_A = ["record", JOB_A, "--channel", "portal", "--platform", "示例招聘站"]
REC_A_SUB = REC_A + ["--submitted", "--on", "2026-10-28"]
TOPS = ["application_id", "job_id", "record_origin", "channel", "created_at", "updated_at", "revision",
        "status", "submission", "next_followup_on", "context_snapshot", "material_versions", "events"]
EVENT_KEYS = ["event_id", "seq", "request_id", "type", "occurred_at", "occurred_on", "recorded_at",
              "actor", "payload", "voided_by"]

OPTS = None
SANITIZE = []


def sanitize(text):
    for raw, label in SANITIZE:
        text = text.replace(raw, label)
        text = text.replace(raw.replace("\\", "\\\\"), label)
        text = text.replace(raw.replace("\\", "\\\\\\\\"), label)  # repr() inside a JSON message
        text = text.replace(raw.replace("\\", "/"), label)
    return text


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree(root):
    root = Path(root)
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): (sha(p) if p.is_file() else "<dir>")
            for p in sorted(root.rglob("*"))}


def parse(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


class R:
    def __init__(self, argv, proc_or_tuple):
        self.argv = argv
        self.exit, self.stdout, self.stderr = proc_or_tuple
        self.out = parse(self.stdout)
        self.err = parse(self.stderr)

    @property
    def error(self):
        return self.err.get("error") if isinstance(self.err, dict) else None

    @property
    def warnings(self):
        if isinstance(self.out, dict):
            return self.out.get("warnings") or []
        return []

    @property
    def app(self):
        return (self.out or {}).get("application") if isinstance(self.out, dict) else None


class Ctx:
    def __init__(self, sid, setup):
        self.sid = sid
        self.work = OPTS.output / "work" / sid
        if self.work.exists():
            shutil.rmtree(self.work)
        self.work.mkdir(parents=True)
        self.data = self.work / "data"
        self.outside = self.work / "outside"
        self.outside.mkdir()
        self.log = []
        self.checks = []
        self.impl = []
        self.app = None
        self.last_rid = None
        prepare(self, setup)

    # ---- running the product
    def raw(self, argv, data=True, cwd=None):
        full = [sys.executable, "-m", "jobsearch_cn"] + [str(a) for a in argv]
        if data:
            full += ["--data-dir", str(self.data)]
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        proc = subprocess.run(full, cwd=cwd or OPTS.repo, capture_output=True, env=env, timeout=120)
        r = R(argv, (proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")))
        self.log.append({"argv": [sanitize(str(a)) for a in argv], "exit": r.exit,
                         "stdout": sanitize(r.stdout), "stderr": sanitize(r.stderr)})
        return r

    def app_cmd(self, argv):
        return self.raw(["application"] + list(argv))

    def preview(self, argv):
        return self.app_cmd(list(argv) + ["--preview"])

    def write(self, argv, rid=None):
        """Two phases: preview, then commit with the preview's request_id (or rid). Returns the deciding R."""
        p = self.preview(argv)
        if p.exit != 0:
            return p
        use = rid or p.out["request_id"]
        r = self.app_cmd(list(argv) + ["--request-id", use])
        r.preview_result = p
        r.rid = use
        if r.exit == 0:
            self.last_rid = use
            if argv[0] == "record" and r.app:
                self.app = r.app["application_id"]
        return r

    def commit(self, argv, rid):
        r = self.app_cmd(list(argv) + ["--request-id", rid])
        return r

    def show(self, app=None):
        r = self.app_cmd(["show", app or self.app])
        out = r.out
        if isinstance(out, dict) and "application" in out and "application_id" not in out:
            out = out["application"]
        return out

    def export(self, *ids):
        return self.app_cmd(["export"] + list(ids))

    def rev(self, app=None):
        return (self.show(app) or {}).get("revision")

    @property
    def appdir(self):
        return self.data / "applications"

    @property
    def db(self):
        return self.appdir / "applications.sqlite3"

    # ---- recording
    def check(self, desc, ok, detail=None):
        self.checks.append({"check": desc, "ok": bool(ok), "detail": None if detail is None else sanitize(str(detail))})
        return ok

    def note(self, desc, observed):
        self.impl.append({"item": desc, "observed": sanitize(str(observed))})

    def accepted(self, r, desc, warning=None):
        ok = r.exit == 0
        self.check(f"{desc}：接受（退出 0）", ok, f"exit={r.exit} err={r.stderr[:300]}")
        if ok and warning is not None:
            self.check(f"{desc}：{'有' if warning else '没有'}警告", bool(r.warnings) == warning, r.warnings)
        return ok

    def rejected(self, r, desc, error=None, exit=1, before=None):
        if exit == "nonzero":
            self.check(f"{desc}：拒绝（退出非 0）", r.exit != 0, f"exit={r.exit}")
        else:
            self.check(f"{desc}：拒绝（退出 {exit}）", r.exit == exit, f"exit={r.exit} err={r.stderr[:300]}")
        if error:
            self.check(f"{desc}：error={error}", r.error == error, f"error={r.error}")
        if before is not None:
            self.check(f"{desc}：没有写入", tree(self.data) == before)


# ------------------------------------------------------------------ setups

TEMPLATES = {}


def cli_setup(data, argv):
    full = [sys.executable, "-m", "jobsearch_cn"] + [str(a) for a in argv] + ["--data-dir", str(data)]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = subprocess.run(full, cwd=OPTS.repo, capture_output=True, env=env, timeout=180)
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")


def build(data, material="resume-1.json"):
    return cli_setup(data, ["resume", "build", data / "materials" / JOB_A / material, "--typst", OPTS.typst])


def make_templates():
    base = OPTS.output / "templates" / "base"
    if base.parent.exists():
        shutil.rmtree(base.parent)
    base.mkdir(parents=True)
    for name in ("v25-jd-a-backend.txt", "v25-jd-b-dataplatform.txt"):
        code, out, err = cli_setup(base, ["jd", "parse", INPUTS / "jd" / name, "--save"])
        assert code == 0, err
    jobs = sorted(p.stem for p in (base / "jobs").glob("*.json"))
    assert jobs == sorted([JOB_A, JOB_B]), jobs
    shutil.copytree(INPUTS / "profile", base / "profile")
    (base / "materials" / JOB_A).mkdir(parents=True)
    shutil.copy(INPUTS / "material" / "resume-1.json", base / "materials" / JOB_A / "resume-1.json")
    code, out, err = cli_setup(base, ["match", "score", JOB_A, "--save"])
    assert code == 0, err
    built = base.parent / "built"
    shutil.copytree(base, built)
    code, out, err = build(built)
    assert code == 0, err
    TEMPLATES["base"] = base
    TEMPLATES["built"] = built
    TEMPLATES["build_output"] = parse(out)


def prepare(ctx, setup):
    if setup in ("none", "repo"):
        return
    name = setup.split("+")[0]
    template = "built" if name in ("built", "reviewed", "edited_after_build", "edited_pdf", "outside_docx",
                                   "no_sidecar", "built_invalid_material") else "base"
    shutil.copytree(TEMPLATES[template], ctx.data)
    mats = ctx.data / "materials" / JOB_A
    res = ctx.data / "resumes" / JOB_A
    if name in ("reviewed", "edited_after_build"):
        shutil.copy(INPUTS / "review" / "review-1-r1.json", mats / "review-1-r1.json")
    if name == "edited_after_build":
        shutil.copy(INPUTS / "material" / "resume-1.edited.json", mats / "resume-1.json")
    if name == "edited_pdf":
        (res / "resume-1.edited.pdf").write_bytes((res / "resume-1.pdf").read_bytes() + b"\n% v25 edited\n")
    if name == "outside_docx":
        shutil.copy(res / "resume-1.docx", ctx.outside / "resume-1-final.docx")
    if name == "no_sidecar":
        (res / "resume-1.build.json").unlink()
    if name in ("base_invalid_material", "built_invalid_material"):
        shutil.copy(INPUTS / "material" / "resume-9.invalid.json", mats / "resume-9.json")


# ------------------------------------------------------------------ helpers

def path_record(ctx, state):
    """Bring a fresh application to `state` with M4-1a commands; returns its id."""
    steps = {
        "drafted": [], "applied": [], "interview": ["interview"], "offer": ["offer"],
        "no_response": ["no_response"], "hired": ["offer", "hired"], "rejected": ["rejected"],
        "withdrawn": ["withdrawn"], "offer_declined": ["offer", "offer_declined"],
    }[state]
    first = REC_A if state in ("drafted", "withdrawn") else REC_A + ["--submitted", "--on", "2026-10-20"]
    r = ctx.write(first)
    if r.exit != 0:
        return None
    app = ctx.app
    rev = r.app["revision"]
    for to in steps:
        r = ctx.write(["status", app, to, "--expected-revision", rev])
        if r.exit != 0:
            return None
        rev = r.app["revision"]
    return app


def doc_app(doc, app):
    for item in (doc or {}).get("applications", []):
        if item["application_id"] == app:
            return item
    return None


def artifact(ctx, rel):
    for base in (ctx.appdir, ctx.data):
        p = base / rel
        if p.is_file():
            return p
    return None


def kinds_of(warnings):
    text = " ".join(map(str, warnings)).lower()
    return {"phone": bool(re.search(r"phone|手机|电话", text)),
            "email": bool(re.search(r"e-?mail|邮箱", text)),
            "url": bool(re.search(r"url|link|链接|网址", text))}


def strip_exported_at(text):
    """Without exported_at and with LF line ends (stdout on Windows is CRLF, the --out file is LF)."""
    return re.sub(r'"exported_at": "[^"]*"', '"exported_at": "<x>"', text.replace("\r\n", "\n"))


# ------------------------------------------------------------------ scenarios

SC = {}


def scenario(sid):
    def wrap(fn):
        SC[sid] = fn
        return fn
    return wrap


@scenario("A01")
def a01(c):
    r = c.write(REC_A)
    c.accepted(r, "record")
    c.check("建出 applications/applications.sqlite3", c.db.is_file())
    con = sqlite3.connect(c.db)
    c.check("user_version = 1", con.execute("PRAGMA user_version").fetchone()[0] == 1)
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    want = {"applications", "events", "requests", "material_versions", "material_files", "snapshots"}
    c.check("§3 的六张表都在", want <= tables, sorted(tables))
    con.execute("PRAGMA foreign_keys=ON")
    try:
        con.execute("INSERT INTO events (application_id, seq, event_id, request_id, type, recorded_at, actor,"
                    " source_kind, payload) VALUES ('app_none', 1, 'evt_x', 'req_x', 'note_added', 'x', 'user',"
                    " 'user', '{}')")
        fk = False
    except sqlite3.DatabaseError as exc:
        fk = "FOREIGN KEY" in str(exc).upper() or "constraint" in str(exc).lower()
    con.rollback()
    con.close()
    c.check("外键生效：插入不存在投递的事件失败", fk)
    left = sorted(p.name for p in c.appdir.iterdir() if re.search(r"-(journal|wal|shm)$", p.name))
    c.check("写完不残留 -journal/-wal/-shm", not left, left)
    c.note("其余列名", sorted(tables))


@scenario("A02")
def a02(c):
    c.write(REC_A)
    con = sqlite3.connect(c.db)
    con.execute("PRAGMA user_version = 2")
    con.commit()
    con.close()
    before = tree(c.data)
    r = c.write(["status", c.app, "withdrawn", "--expected-revision", 1])
    c.rejected(r, "库版本更高时写", exit=2, before=before)
    c.note("写入被拒的错误输出", r.stderr.strip()[:300])
    s = c.app_cmd(["show", c.app])
    c.note("库版本更高时 show", f"exit={s.exit} {s.stderr.strip()[:200]}")


@scenario("A03")
def a03(c):
    for argv in (["show", "app_00000000000000000000000000000001"], ["list"], ["validate"], ["export"]):
        r = c.app_cmd(argv)
        c.note(f"库不存在时 {argv[0]}", f"exit={r.exit} out={r.stdout.strip()[:160]} err={r.stderr.strip()[:160]}")
    c.check("四条命令后没有 applications/", not c.appdir.exists())


@scenario("A04")
def a04(c):
    p = c.preview(REC_A)
    c.check("库不存在时预览退出 0、preview=true、有 request_id",
            p.exit == 0 and p.out.get("preview") is True and p.out.get("request_id"))
    c.check("预览带将写的 created 事件", [e["type"] for e in p.out.get("events", [])] == ["created"])
    c.note("新建时预览的 application", json.dumps(p.out.get("application"), ensure_ascii=False)[:120])
    c.check("预览后 applications/ 不存在", not c.appdir.exists())
    c.write(REC_A)
    before = tree(c.data)
    p = c.preview(["status", c.app, "withdrawn", "--expected-revision", 1])
    c.check("已有库时预览退出 0、preview=true", p.exit == 0 and p.out.get("preview") is True)
    c.check("预览前后数据目录（含库文件）不变", tree(c.data) == before)
    app = c.show()
    c.check("预览后 revision=1、status=drafted", app["revision"] == 1 and app["status"] == "drafted")
    c.note("request_id 格式", p.out.get("request_id"))


@scenario("A05")
def a05(c):
    r = c.write(REC_A)
    c.accepted(r, "record 提交")
    out = r.out
    c.check("preview=false，request_id 与预览相同", out["preview"] is False and out["request_id"] == r.preview_result.out["request_id"])
    a = r.app
    c.check("application_id 形如 app_+32 位十六进制", re.fullmatch(r"app_[0-9a-f]{32}", a["application_id"]))
    ev = out["events"]
    c.check("只有一条 created，seq=1", [e["type"] for e in ev] == ["created"] and ev[0]["seq"] == 1)
    c.check("created payload", ev[0]["payload"] == {"job_id": JOB_A, "record_origin": "current",
                                                    "channel": {"kind": "portal", "platform": "示例招聘站"}}, ev[0]["payload"])
    c.check("status=drafted，revision=1，confirmed=false，materials_recorded=null",
            a["status"] == "drafted" and a["revision"] == 1 and a["submission"]["confirmed"] is False
            and a["submission"]["materials_recorded"] is None, a["submission"])
    c.check("actor=user，recorded_at 有值", ev[0]["actor"] == "user" and ev[0]["recorded_at"])
    c.note("created 事件的发生时间", (ev[0]["occurred_at"], ev[0]["occurred_on"]))


@scenario("A06")
def a06(c):
    r1 = c.write(REC_A)
    r2 = c.commit(REC_A, r1.rid)
    c.check("重试退出 0", r2.exit == 0, r2.stderr[:200])
    same = r2.app and r2.app["application_id"] == r1.app["application_id"] and \
        [(e["event_id"], e["seq"]) for e in r2.out["events"]] == [(e["event_id"], e["seq"]) for e in r1.out["events"]]
    c.check("application_id、event_id、seq 与第一次相同", same)
    doc = c.export().out
    c.check("仍只有 1 条投递、1 条事件，revision=1",
            len(doc["applications"]) == 1 and len(doc["applications"][0]["events"]) == 1
            and doc["applications"][0]["revision"] == 1)
    c.note("重试输出是否标出重放", f"repeated={r2.out.get('repeated')}")


@scenario("A07")
def a07(c):
    r1 = c.write(REC_A)
    c.preview(["record", JOB_A, "--channel", "email"])
    before = tree(c.data)
    r = c.commit(["record", JOB_A, "--channel", "email"], r1.rid)
    c.rejected(r, "同 request_id 不同内容", "request_conflict", before=before)


@scenario("A08")
def a08(c):
    before = tree(c.data)
    r = c.app_cmd(REC_A)
    c.check("不预览也不带 request_id 时没有写入", tree(c.data) == before)
    c.note("直接写", f"exit={r.exit} {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ''}")
    p = c.preview(REC_A)
    made = "req_00000000000000000000000000000abc"
    r2 = c.commit(REC_A, made)
    c.note("自拟 request_id 提交", f"exit={r2.exit} {r2.stderr.strip()[:200]}")


@scenario("A09")
def a09(c):
    before = tree(c.data)
    r = c.write(["record", JOB_C, "--channel", "portal"])
    c.rejected(r, "当前流程岗位不在库里", exit="nonzero", before=before)
    c.note("岗位不在库里", f"exit={r.exit} error={r.error}")


@scenario("A10")
def a10(c):
    r = c.write(REC_A_SUB)
    c.accepted(r, "record --submitted --on", warning=True)
    ev = r.out["events"]
    c.check("同一 request 写 created+submitted，seq 1、2",
            [(e["type"], e["seq"]) for e in ev] == [("created", 1), ("submitted", 2)]
            and len({e["request_id"] for e in ev}) == 1)
    a = r.app
    c.check("revision=2，status=applied", a["revision"] == 2 and a["status"] == "applied")
    sub = a["submission"]
    c.check("submission 四个字段", (sub["confirmed"], sub["occurred_at"], sub["occurred_on"], sub["materials_recorded"])
            == (True, None, "2026-10-28", False), sub)
    c.check("submitted 事件 occurred_on，不补午夜", ev[1]["occurred_on"] == "2026-10-28" and ev[1]["occurred_at"] is None)
    pl = ev[1]["payload"]
    c.check("submitted payload：channel、material_version_ids=[]、sent_file_refs=[]",
            pl.get("channel") == {"kind": "portal", "platform": "示例招聘站"} and pl.get("material_version_ids") == []
            and pl.get("sent_file_refs") == [], pl)


@scenario("A11")
def a11(c):
    r = c.write(REC_A + ["--submitted", "--at", "2026-10-28T14:30+08:00"])
    c.accepted(r, "--at 带时区", warning=True)
    sub = r.app["submission"]
    at = sub["occurred_at"] or ""
    c.check("与 2026-10-28T06:30:00Z 同一时刻，occurred_on=null",
            re.fullmatch(r"2026-10-28T06:30(:00)?(Z|\+00:00)", at) and sub["occurred_on"] is None, sub)
    c.note("UTC 写法", at)


@scenario("A12")
def a12(c):
    r = c.write(REC_A + ["--submitted"])
    c.accepted(r, "日期未知", warning=True)
    sub = r.app["submission"]
    c.check("confirmed=true，两种时间都是 null", sub["confirmed"] is True and sub["occurred_at"] is None
            and sub["occurred_on"] is None, sub)
    c.check("recorded_at 有值", all(e["recorded_at"] for e in r.out["events"]))


@scenario("A13")
def a13(c):
    for extra in (["--at", "2026-10-28T14:30"], ["--at", "2026-10-28T14:30:00"], ["--on", "2026-02-30"],
                  ["--on", "2026/10/28"], ["--on", "2099-01-01"], ["--at", "2099-01-01T09:00+08:00"]):
        before = tree(c.data)
        r = c.write(REC_A + ["--submitted"] + extra)
        c.rejected(r, " ".join(extra), "invalid", before=before)
    before = tree(c.data)
    r = c.write(REC_A + ["--submitted", "--on", "2026-10-28", "--at", "2026-10-28T14:30+08:00"])
    c.rejected(r, "--on 与 --at 同给", exit="nonzero", before=before)
    c.note("--on 与 --at 同给", f"exit={r.exit}")
    c.check("库不存在时也没建库", not c.appdir.exists())


@scenario("A14")
def a14(c):
    r = c.write(REC_A + ["--on", "2026-10-28"])
    c.note("record 不带 --submitted 给 --on", f"exit={r.exit} error={r.error} {r.stderr.strip()[:160]}")
    if r.exit == 0:
        evs = r.out["events"]
        c.check("若接受：只是 drafted，没有投出日期",
                r.app["status"] == "drafted" and all(e["type"] != "submitted" for e in evs)
                and r.app["submission"]["confirmed"] is False)


@scenario("A15")
def a15(c):
    before = tree(c.data)
    r = c.write(REC_A + ["--material", c.data / "materials" / JOB_A / "resume-1.json",
                         "--sent", c.data / "resumes" / JOB_A / "resume-1.pdf"])
    c.rejected(r, "--material/--sent 不随投出", exit=1, before=before)
    c.note("错误码", r.error)


@scenario("A16")
def a16(c):
    before = tree(c.data)
    r = c.write(REC_A + ["--historical"])
    c.rejected(r, "--historical 不带 --submitted", exit=1, before=before)
    c.note("错误码", r.error)


@scenario("A17")
def a17(c):
    before = tree(c.data)
    r = c.write(REC_A + ["--note", "测试"])
    c.rejected(r, "record --note", exit="nonzero", before=before)
    c.note("退出码", r.exit)


@scenario("A18")
def a18(c):
    r = c.write(["record", JOB_C, "--channel", "portal", "--platform", "示例招聘站", "--historical", "--submitted"])
    c.accepted(r, "补录岗位不在库里", warning=True)
    a = r.app
    c.check("status=applied，record_origin=historical", a["status"] == "applied" and a["record_origin"] == "historical")
    c.check("警告说明岗位不在库里", any(JOB_C in w or "岗位库" in w or "not in" in w.lower() for w in r.warnings), r.warnings)
    c.check("context_snapshot 两项都是 null", a["context_snapshot"] == {"job": None, "match": None}, a["context_snapshot"])
    files = [p for p in (c.appdir / "artifacts").rglob("*") if p.is_file()] if (c.appdir / "artifacts").exists() else []
    c.check("artifacts 下没有快照文件", not files, files)
    sub = a["submission"]
    c.check("submission：confirmed、两个 null、materials_recorded=false",
            (sub["confirmed"], sub["occurred_at"], sub["occurred_on"], sub["materials_recorded"]) == (True, None, None, False), sub)
    rows = c.app_cmd(["list"]).out["applications"]
    c.check("list 里看得出补录", rows and rows[0].get("record_origin") == "historical")
    c.note("补录缺材料是否另警告", r.warnings)


@scenario("A19")
def a19(c):
    r = c.write(["record", JOB_B, "--channel", "company_site", "--historical", "--submitted", "--on", "2026-09-28"])
    c.accepted(r, "补录岗位在库里")
    a = r.app
    c.check("historical，occurred_on=2026-09-28，materials_recorded=false",
            a["record_origin"] == "historical" and a["submission"]["occurred_on"] == "2026-09-28"
            and a["submission"]["materials_recorded"] is False, a["submission"])
    c.note("补录岗位在库里时的快照", a["context_snapshot"])
    c.note("补录岗位在库里时的警告", r.warnings)


@scenario("A20")
def a20(c):
    r = c.write(["record", JOB_C, "--channel", "referral", "--historical", "--submitted", "--on", "2026-09-20"])
    c.accepted(r, "补录 referral", warning=True)
    ev = r.out["events"][-1]
    c.check("submitted occurred_on=2026-09-20，recorded_at 是今天写入时刻",
            ev["occurred_on"] == "2026-09-20" and ev["recorded_at"] and not ev["recorded_at"].startswith("2026-09-20"), ev)
    c.check("channel={referral, null}", r.app["channel"] == {"kind": "referral", "platform": None}, r.app["channel"])


@scenario("A21")
def a21(c):
    for kind in ["portal", "company_site", "email", "referral", "campus", "offline", "other", "unknown"]:
        p = c.preview(["record", JOB_A, "--channel", kind])
        c.check(f"channel {kind} 接受", p.exit == 0)
    p = c.preview(["record", JOB_A, "--channel", "portal"])
    plat = p.out["events"][0]["payload"]["channel"]["platform"] if p.exit == 0 else "?"
    c.check("不带 --platform 时 platform=null", plat is None, plat)
    p = c.preview(["record", JOB_A, "--channel", "wechat"])
    c.check("未知 kind 拒绝", p.exit != 0)
    c.note("未知 kind", f"exit={p.exit}")
    p = c.preview(["record", JOB_A, "--channel", "portal", "--platform", "台" * 40])
    c.check("平台名 40 字接受", p.exit == 0, p.stderr[:200])
    p = c.preview(["record", JOB_A, "--channel", "portal", "--platform", "台" * 41])
    c.check("平台名 41 字 invalid", p.exit == 1 and p.error == "invalid", f"exit={p.exit} {p.error}")
    c.note("预览阶段是否做参数检查", "是（以上均在预览阶段判定）")


@scenario("A22")
def a22(c):
    c.write(REC_A_SUB)
    first = c.app
    r = c.write(["record", JOB_A, "--channel", "email"])
    c.accepted(r, "同一岗位再记", warning=True)
    c.note("重复警告原文", r.warnings)
    c.check("两条 application_id 不同，第二条 drafted", c.app != first and r.app["status"] == "drafted")
    rows = c.app_cmd(["list", "--job", JOB_A]).out["applications"]
    c.check("list --job 列出两条", len(rows) == 2)


@scenario("A23")
def a23(c):
    c.write(REC_A)
    c.write(["status", c.app, "withdrawn", "--expected-revision", 1])
    r = c.write(["record", JOB_A, "--channel", "email"])
    c.accepted(r, "之前的已结束时再记", warning=False)


@scenario("A24")
def a24(c):
    c.write(REC_A)
    r = c.write(["submit", c.app, "--expected-revision", 1, "--on", "2026-10-29"])
    c.accepted(r, "submit", warning=True)
    a = r.app
    ev = r.out["events"]
    c.check("applied，revision=2，submitted(seq 2) occurred_on=2026-10-29",
            a["status"] == "applied" and a["revision"] == 2 and [(e["type"], e["seq"]) for e in ev] == [("submitted", 2)]
            and ev[0]["occurred_on"] == "2026-10-29")
    c.check("payload.channel 等于 created 时的渠道", ev[0]["payload"]["channel"] == {"kind": "portal", "platform": "示例招聘站"})
    c.check("confirmed=true，materials_recorded=false", a["submission"]["confirmed"] is True and a["submission"]["materials_recorded"] is False)


@scenario("A25")
def a25(c):
    c.write(REC_A_SUB)
    before = tree(c.data)
    r = c.write(["submit", c.app, "--expected-revision", 2])
    c.rejected(r, "已投出再 submit", exit=1, before=before)
    c.note("错误码", r.error)


@scenario("A26")
def a26(c):
    c.write(REC_A_SUB)
    c.write(["status", c.app, "interview", "--expected-revision", 2])
    before = tree(c.data)
    r = c.write(["status", c.app, "offer", "--expected-revision", 2])
    c.rejected(r, "revision 过期", "stale_revision", before=before)
    err = r.err or {}
    c.check("错误带当前 revision 3 和之后的事件", err.get("revision") == 3 and
            [e.get("seq") for e in err.get("events", [])] == [3], {k: err.get(k) for k in ("revision",)})
    c.check("status 仍为 interview", c.show()["status"] == "interview")
    c.note("附带字段名", sorted(err))


@scenario("A27")
def a27(c):
    c.write(REC_A)
    before = tree(c.data)
    r = c.write(["status", c.app, "withdrawn", "--expected-revision", 5])
    c.rejected(r, "revision 比当前大", "stale_revision", before=before)


@scenario("A28")
def a28(c):
    c.write(REC_A)
    before = tree(c.data)
    r = c.write(["status", c.app, "withdrawn"])
    c.rejected(r, "缺 --expected-revision", exit="nonzero", before=before)
    c.note("退出码", r.exit)


def matrix(frm):
    def run(c):
        cells = {}
        for to in STATES:
            app = path_record(c, frm)
            if not c.check(f"走到 {frm}", app is not None):
                continue
            rev = c.rev(app)
            before = tree(c.data)
            r = c.write(["status", app, to, "--expected-revision", rev, "--reason", "状态表核对"])
            if to in ALLOWED[frm]:
                ok = r.exit == 0 and r.app["status"] == to and \
                    r.out["events"][0]["payload"] == {"from": frm, "to": to, "reason": "状态表核对"}
                got = "allow" if ok else f"exit={r.exit} {r.error}"
                c.check(f"{frm}→{to} 允许", ok, got)
            else:
                ok = r.exit == 1 and r.error == "transition" and tree(c.data) == before
                got = "transition" if ok else f"exit={r.exit} error={r.error} wrote={tree(c.data) != before}"
                c.check(f"{frm}→{to} 拒绝（transition，退出 1）", ok, got)
            cells[to] = got
        c.note("矩阵实际结果", cells)
    return run


for n, state in enumerate(STATES, start=29):
    SC[f"A{n:02d}"] = matrix(state)


@scenario("A38")
def a38(c):
    for to in ("interview", "offer", "rejected"):
        app = path_record(c, "no_response")
        before = tree(c.data)
        r = c.write(["status", app, to, "--expected-revision", c.rev(app)])
        c.rejected(r, f"no_response→{to} 不带 reason", "invalid", before=before)
    app = path_record(c, "no_response")
    r = c.write(["status", app, "interview", "--expected-revision", c.rev(app), "--reason", "10月底收到面试邀请"])
    c.accepted(r, "带 reason")
    c.check("reason 原样写进 payload", r.exit == 0 and r.out["events"][0]["payload"]["reason"] == "10月底收到面试邀请")
    app = path_record(c, "no_response")
    r = c.write(["status", app, "interview", "--expected-revision", c.rev(app), "--reason", ""])
    c.note("空字符串 reason", f"exit={r.exit} error={r.error}")


@scenario("A39")
def a39(c):
    c.write(REC_A_SUB)
    before = tree(c.data)
    r = c.write(["status", c.app, "interview", "--expected-revision", 2, "--reason", "面" * 301])
    c.rejected(r, "301 字", "invalid", before=before)
    r = c.write(["status", c.app, "interview", "--expected-revision", 2, "--reason", "面" * 300])
    c.accepted(r, "300 字")


@scenario("A40")
def a40(c):
    c.write(REC_A_SUB)
    before = tree(c.data)
    r = c.write(["status", c.app, "interview", "--expected-revision", 2, "--on", "2099-01-01"])
    c.rejected(r, "将来的 --on", "invalid", before=before)
    r = c.write(["status", c.app, "interview", "--expected-revision", 2, "--at", "2026-11-01T10:00+08:00"])
    c.accepted(r, "--at")
    ev = r.out["events"][0] if r.exit == 0 else {}
    c.check("occurred_at 与 2026-11-01T02:00:00Z 同一时刻",
            re.fullmatch(r"2026-11-01T02:00(:00)?(Z|\+00:00)", ev.get("occurred_at") or "") and ev.get("occurred_on") is None, ev)


@scenario("A41")
def a41(c):
    c.write(REC_A_SUB)
    for to in ("accepted", "drafted"):
        before = tree(c.data)
        r = c.write(["status", c.app, to, "--expected-revision", 2])
        c.rejected(r, f"status {to}", exit="nonzero", before=before)
        c.note(f"status {to}", f"exit={r.exit} error={r.error}")


@scenario("A42")
def a42(c):
    c.write(REC_A)
    ghost = "app_ffffffffffffffffffffffffffffffff"
    before = tree(c.data)
    r = c.write(["status", ghost, "withdrawn", "--expected-revision", 1])
    c.rejected(r, "status 不存在的投递", exit="nonzero", before=before)
    s = c.app_cmd(["show", ghost])
    c.check("show 不存在的投递拒绝", s.exit != 0)
    c.note("不存在的投递", f"status exit={r.exit} error={r.error}; show exit={s.exit} error={s.error}")


def submit_with(c, extra, base=None):
    argv = (base or REC_A_SUB) + extra
    return c.write(argv)


def mat(c, name="resume-1.json"):
    return c.data / "materials" / JOB_A / name


def res(c, name):
    return c.data / "resumes" / JOB_A / name


@scenario("A43")
def a43(c):
    src = {"material": sha(mat(c)), "pdf": sha(res(c, "resume-1.pdf"))}
    r = submit_with(c, ["--material", mat(c), "--sent", res(c, "resume-1.pdf")])
    c.accepted(r, "带材料投出（相符）", warning=False)
    if r.exit != 0:
        return
    a = r.app
    mv = a["material_versions"]
    c.check("一个材料版本", len(mv) == 1, len(mv))
    v = mv[0]
    c.check("version_id 形如 mv_+32 位十六进制", re.fullmatch(r"mv_[0-9a-f]{32}", v["version_id"]), v["version_id"])
    c.check("kind=resume，material_hash、profile_hash", v["kind"] == "resume" and v["material_hash"] == MAT_HASH
            and v["profile_hash"] == PROFILE_HASH, (v["material_hash"], v["profile_hash"]))
    c.check("review_path 指向 review-1-r1.json", (v.get("review_path") or "").endswith("review-1-r1.json"), v.get("review_path"))
    files = {f["role"]: f for f in v["files"]}
    c.check("files 有 source（file_id=material）和 sent", set(files) == {"source", "sent"}
            and files["source"]["file_id"] == "material", [(f["file_id"], f["role"]) for f in v["files"]])
    c.check("发出的 PDF file_id=pdf（设计 §3）", files.get("sent", {}).get("file_id") == "pdf", files.get("sent", {}).get("file_id"))
    for f in v["files"]:
        p = artifact(c, f["path"])
        c.check(f"归档 {f['file_id']} 在 artifacts/<投递>/<版本>/ 下且摘要、大小对",
                p is not None and f"{a['application_id']}/{v['version_id']}" in p.as_posix() and sha(p) == f["sha256"]
                and p.stat().st_size == f["size_bytes"], f["path"])
    c.check("归档摘要等于投出时源文件", files["source"]["sha256"] == src["material"] and files["sent"]["sha256"] == src["pdf"])
    sub_ev = [e for e in a["events"] if e["type"] == "submitted"][0]
    c.check("payload.material_version_ids=[version_id]，sent_file_refs 指向发出文件",
            sub_ev["payload"]["material_version_ids"] == [v["version_id"]]
            and sub_ev["payload"]["sent_file_refs"] == [{"version_id": v["version_id"], "file_id": files["sent"]["file_id"]}],
            sub_ev["payload"])
    c.check("materials_recorded=true", a["submission"]["materials_recorded"] is True)
    for kind in ("job", "match"):
        snap = a["context_snapshot"].get(kind)
        p = artifact(c, snap["path"]) if snap else None
        c.check(f"context_snapshot.{kind} 有 path 和 sha256，摘要等于归档字节", p is not None and sha(p) == snap["sha256"], snap)
    c.check("核对结果写进事件且导出可见（相符）",
            sub_ev["payload"].get("materials_check") == "match" and a["submission"].get("materials_check") == "match",
            (sub_ev["payload"].get("materials_check"), a["submission"].get("materials_check")))
    c.note("review_path 写法", v.get("review_path"))
    c.note("核对结果字段", "payload.materials_check / submission.materials_check")
    snap = a["context_snapshot"]["job"]
    c.note("岗位快照是否逐字节复制", sha(artifact(c, snap["path"])) == sha(c.data / "jobs" / f"{JOB_A}.json"))


@scenario("A44")
def a44(c):
    r = submit_with(c, ["--material", mat(c), "--sent", res(c, "resume-1.pdf"), "--sent", res(c, "resume-1.docx")])
    c.accepted(r, "PDF+Word")
    if r.exit != 0:
        return
    v = r.app["material_versions"][0]
    sent = [f for f in v["files"] if f["role"] == "sent"]
    c.check("一个版本，含 material 和两个发出文件", len(r.app["material_versions"]) == 1 and len(sent) == 2
            and any(f["file_id"] == "material" for f in v["files"]))
    c.check("发出文件 file_id 为 pdf、docx（设计 §3）", sorted(f["file_id"] for f in sent) == ["docx", "pdf"],
            [f["file_id"] for f in sent])
    refs = [e for e in r.app["events"] if e["type"] == "submitted"][0]["payload"]["sent_file_refs"]
    c.check("sent_file_refs 两条", len(refs) == 2)
    c.check("没有核对不符的警告", r.app["submission"].get("materials_check") == "match", r.app["submission"].get("materials_check"))
    c.note("无审核结果时的警告", r.warnings)
    c.check("没有审核结果时 review_path=null", v.get("review_path") is None)


@scenario("A45")
def a45(c):
    c.write(REC_A)
    r = c.write(["submit", c.app, "--expected-revision", 1, "--on", "2026-10-30", "--material", mat(c),
                 "--sent", res(c, "resume-1.docx")])
    c.accepted(r, "submit 带材料")
    if r.exit != 0:
        return
    v = r.app["material_versions"][0]
    sent = [f for f in v["files"] if f["role"] == "sent"]
    c.check("status=applied，一份发出文件，摘要对", r.app["status"] == "applied" and len(sent) == 1
            and sent[0]["sha256"] == sha(res(c, "resume-1.docx")) and sha(artifact(c, sent[0]["path"])) == sent[0]["sha256"])
    c.check("sent_file_refs 的 file_id=docx（设计 §3）", sent[0]["file_id"] == "docx", sent[0]["file_id"])
    c.note("警告", r.warnings)


@scenario("A46")
def a46(c):
    r = submit_with(c, ["--material", mat(c), "--sent", res(c, "resume-1.pdf")])
    c.accepted(r, "投出")
    first = c.export().out["applications"][0]
    arts = tree(c.appdir / "artifacts")
    shutil.copy(INPUTS / "material" / "resume-1.edited.json", mat(c))
    code, _, err = build(c.data)
    c.check("改材料后重新 build 成功", code == 0, err[:200])
    prof = c.data / "profile" / "profile.json"
    data = json.loads(prof.read_text(encoding="utf-8"))
    for skill in data.get("skills", []):
        if skill.get("name") == "Git":
            skill["name"] = "GIT"
    prof.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    c.check("artifacts 下文件和摘要不变", tree(c.appdir / "artifacts") == arts)
    now = c.export().out["applications"][0]
    c.check("导出的 material_versions、context_snapshot 不变",
            now["material_versions"] == first["material_versions"] and now["context_snapshot"] == first["context_snapshot"])
    v = c.app_cmd(["validate"])
    c.check("validate valid=true，退出 0", v.exit == 0 and v.out["valid"] is True, v.stdout[:300])
    c.note("validate 警告", v.out.get("warnings") if v.out else None)


@scenario("A47")
def a47(c):
    r = submit_with(c, ["--material", mat(c), "--sent", res(c, "resume-1.pdf")])
    c.accepted(r, "材料生成后被改", warning=True)
    if r.exit != 0:
        return
    v = r.app["material_versions"][0]
    c.check("归档材料的 material_hash 是改后的", v["material_hash"] == MAT_HASH_EDITED, v["material_hash"])
    c.check("review_path=null", v.get("review_path") is None, v.get("review_path"))
    ev = [e for e in r.app["events"] if e["type"] == "submitted"][0]
    c.check("核对不符写进事件、导出可见", ev["payload"].get("materials_check") == "mismatch"
            and r.app["submission"].get("materials_check") == "mismatch")
    c.check("materials_recorded=true", r.app["submission"]["materials_recorded"] is True)
    c.note("警告原文", r.warnings)


@scenario("A48")
def a48(c):
    r = submit_with(c, ["--material", mat(c), "--sent", res(c, "resume-1.edited.pdf")])
    c.accepted(r, "发出文件摘要不在说明文件里", warning=True)
    if r.exit != 0:
        return
    sent = [f for f in r.app["material_versions"][0]["files"] if f["role"] == "sent"][0]
    c.check("归档的是改过的字节", sent["sha256"] == sha(res(c, "resume-1.edited.pdf")))
    check = r.app["submission"].get("materials_check")
    c.check("核对结果为不符，导出可见", check == "mismatch", check)
    c.note("警告原文", r.warnings)


@scenario("A49")
def a49(c):
    f = c.outside / "resume-1-final.docx"
    r = submit_with(c, ["--material", mat(c), "--sent", f])
    c.accepted(r, "文件不在 resumes/ 下", warning=True)
    if r.exit != 0:
        return
    c.check("警告提到不在 resumes/ 下", any("resumes" in w for w in r.warnings), r.warnings)
    sent = [x for x in r.app["material_versions"][0]["files"] if x["role"] == "sent"][0]
    c.check("归档字节摘要正确", sent["sha256"] == sha(f))
    dump = c.export().stdout
    c.check("导出里没有数据目录外的绝对路径", str(c.outside) not in dump and str(c.outside).replace("\\", "\\\\") not in dump
            and "Users" not in dump)
    c.note("核对结果", r.app["submission"].get("materials_check"))


@scenario("A50")
def a50(c):
    r = submit_with(c, ["--material", mat(c), "--sent", res(c, "resume-1.pdf")])
    c.accepted(r, "没有说明文件", warning=True)
    if r.exit != 0:
        return
    sub = r.app["submission"]
    # 有警告要是关于说明文件的：setup 没有审核结果，"no review" 警告与本场景无关
    c.check("有关于说明文件缺失的警告", any(re.search(r"build|说明文件|note", w, re.I) for w in r.warnings), r.warnings)
    c.check("导出里看得到未核对", sub.get("materials_check") not in (None, "match"), sub)
    c.note("没有说明文件时", f"materials_recorded={sub['materials_recorded']} materials_check={sub.get('materials_check')} "
                           f"archived_files={len(r.app['material_versions'][0]['files']) if r.app['material_versions'] else 0} "
                           f"warnings={r.warnings}")


@scenario("A51")
def a51(c):
    before = tree(c.data)
    r = submit_with(c, ["--material", mat(c, "resume-7.json"), "--sent", res(c, "resume-1.pdf")])
    c.check("材料文件不存在：只警告并记录（冻结期望）", r.exit == 0 and r.warnings, f"exit={r.exit} {r.stderr.strip()[:200]}")
    c.note("材料文件不存在", f"exit={r.exit} wrote={tree(c.data) != before} {r.stderr.strip()[:200]}")


@scenario("A52")
def a52(c):
    r = c.write(REC_A_SUB)
    c.accepted(r, "投出不带材料", warning=True)
    c.check("material_versions=[]，materials_recorded=false",
            r.app["material_versions"] == [] and r.app["submission"]["materials_recorded"] is False)
    c.check("警告是材料未记录", any("材料未记录" in w for w in r.warnings), r.warnings)


@scenario("A53")
def a53(c):
    c.write(REC_A)
    a = c.export().out["applications"][0]
    c.check("submission 未投出的四个字段", {k: a["submission"][k] for k in ("confirmed", "occurred_at", "occurred_on",
            "materials_recorded")} == {"confirmed": False, "occurred_at": None, "occurred_on": None,
                                       "materials_recorded": None}, a["submission"])


@scenario("A54")
def a54(c):
    before = tree(c.data)
    r = submit_with(c, ["--material", mat(c, "resume-9.json"), "--sent", res(c, "resume-1.pdf")])
    if r.exit == 0:
        c.check("若接受：不能记成相符", r.app["submission"].get("materials_check") != "match")
    c.note("无效材料", f"exit={r.exit} error={r.error} wrote={tree(c.data) != before} {r.stderr.strip()[:200]}")


@scenario("A55")
def a55(c):
    before = tree(c.data)
    r = c.write(["record", JOB_B, "--channel", "portal", "--submitted", "--on", "2026-10-28",
                 "--material", mat(c), "--sent", res(c, "resume-1.pdf")])
    if r.exit == 0:
        c.check("若接受：必须有警告", bool(r.warnings))
    c.note("材料岗位不同", f"exit={r.exit} error={r.error} wrote={tree(c.data) != before} {r.stderr.strip()[:200]}")


@scenario("A56")
def a56(c):
    before = tree(c.data)
    r = submit_with(c, ["--sent", res(c, "resume-1.pdf")])
    if r.exit == 0:
        mv = r.app["material_versions"]
        c.check("若接受：看得出材料 JSON 未记录",
                not mv or not any(f["role"] == "source" for f in mv[0]["files"]))
    c.note("只给 --sent", f"exit={r.exit} error={r.error} wrote={tree(c.data) != before} "
                        f"{(r.stderr.strip() or json.dumps(r.app and r.app['material_versions'], ensure_ascii=False))[:240]}")


@scenario("A57")
def a57(c):
    note = res(c, "resume-1.build.json")
    c.check("说明文件 resume-1.build.json 在 PDF 旁", note.is_file())
    if not note.is_file():
        return
    n = json.loads(note.read_text(encoding="utf-8"))
    c.check("material_hash、profile_hash", n.get("material_hash") == MAT_HASH and n.get("profile_hash") == PROFILE_HASH)
    stamp = n.get("built_at") or n.get("generated_at") or ""
    c.check("生成时间带时区", re.search(r"(Z|[+-]\d\d:\d\d)$", stamp), stamp)
    names = {f["name"]: f["sha256"] for f in n.get("files", [])}
    c.check("pdf、docx 的 SHA-256 等于磁盘字节", names.get("resume-1.pdf") == sha(res(c, "resume-1.pdf"))
            and names.get("resume-1.docx") == sha(res(c, "resume-1.docx")), names)
    c.note("说明文件结构", sorted(n))
    time.sleep(1.1)
    code, out, err = build(c.data)
    n2 = json.loads(note.read_text(encoding="utf-8"))
    names2 = {f["name"]: f["sha256"] for f in n2.get("files", [])}
    c.check("重新生成后说明文件更新、摘要仍一致", code == 0 and n2.get("built_at") != stamp
            and names2.get("resume-1.pdf") == sha(res(c, "resume-1.pdf"))
            and names2.get("resume-1.docx") == sha(res(c, "resume-1.docx")))


@scenario("A58")
def a58(c):
    code, out, err = build(c.data, "resume-9.json")
    c.check("无效材料 build 退出非 0", code != 0, code)
    left = sorted(p.name for p in (c.data / "resumes" / JOB_A).glob("resume-9*")) if (c.data / "resumes" / JOB_A).exists() else []
    c.check("没有 resume-9 的说明文件、PDF、Word", not left, left)


@scenario("A59")
def a59(c):
    submit_with(c, ["--material", mat(c), "--sent", res(c, "resume-1.pdf")])
    c.write(["record", JOB_B, "--channel", "email"])
    v = c.app_cmd(["validate"])
    c.check("valid=true，errors=[]，退出 0", v.exit == 0 and v.out["valid"] is True and v.out["errors"] == [], v.stdout[:300])


def archived(c, role="sent"):
    a = c.show()
    f = [x for x in a["material_versions"][0]["files"] if x["role"] == role][0]
    return artifact(c, f["path"])


@scenario("A60")
def a60(c):
    submit_with(c, ["--material", mat(c), "--sent", res(c, "resume-1.pdf")])
    archived(c).unlink()
    v = c.app_cmd(["validate"])
    c.check("valid=false、errors 指出缺文件、退出 1", v.exit == 1 and v.out["valid"] is False and v.out["errors"], v.stdout[:300])


@scenario("A61")
def a61(c):
    submit_with(c, ["--material", mat(c), "--sent", res(c, "resume-1.pdf")])
    p = archived(c)
    p.write_bytes(p.read_bytes() + b"x")
    v = c.app_cmd(["validate"])
    c.check("valid=false、errors 指出摘要不符、退出 1", v.exit == 1 and v.out["valid"] is False and v.out["errors"], v.stdout[:300])


@scenario("A62")
def a62(c):
    submit_with(c, ["--material", mat(c), "--sent", res(c, "resume-1.pdf")])
    o1 = c.appdir / "artifacts" / c.app / "mv_00000000000000000000000000000000.tmp"
    o2 = c.appdir / "artifacts" / "app_00000000000000000000000000000000" / "mv_11111111111111111111111111111111"
    for d in (o1, o2):
        d.mkdir(parents=True)
        (d / "x.pdf").write_bytes(b"orphan")
    v = c.app_cmd(["validate"])
    text = v.stdout
    c.check("两个孤立目录都被列出", o1.name in text and "app_00000000000000000000000000000000" in text, text[:400])
    c.check("validate 不删除它们", (o1 / "x.pdf").exists() and (o2 / "x.pdf").exists())
    c.check("export 不出现它们", "app_00000000000000000000000000000000" not in c.export().stdout and o1.name not in c.export().stdout)
    c.note("孤立目录", f"exit={v.exit} valid={v.out.get('valid')} orphans={v.out.get('orphans')}")


@scenario("A63")
def a63(c):
    c.write(REC_A_SUB)
    con = sqlite3.connect(c.db)
    con.execute("UPDATE applications SET status='offer'")
    con.commit()
    con.close()
    v = c.app_cmd(["validate"])
    c.check("valid=false、退出 1", v.exit == 1 and v.out["valid"] is False and v.out["errors"], v.stdout[:300])
    con = sqlite3.connect(c.db)
    still = con.execute("SELECT status FROM applications").fetchone()[0]
    con.close()
    c.check("validate 不自动修复", still == "offer")


@scenario("A64")
def a64(c):
    c.write(REC_A_SUB)
    r = c.write(["status", c.app, "interview", "--expected-revision", 2, "--reason",
                 "HR电话13912345678，邮箱hr@example.com，链接https://example.com/v25"])
    c.accepted(r, "原因里有联系方式")
    v = c.app_cmd(["validate"])
    c.check("validate valid=true、退出 0", v.exit == 0 and v.out["valid"] is True, v.stdout[:300])
    k = kinds_of(v.out.get("warnings", []))
    c.check("validate 警告点到手机号、邮箱、URL", all(k.values()), v.out.get("warnings"))
    c.note("写入时的警告", r.warnings)


@scenario("A65")
def a65(c):
    submit_with(c, ["--material", mat(c), "--sent", res(c, "resume-1.pdf")])
    a1 = c.app
    c.write(["record", JOB_B, "--channel", "email"])
    a2 = c.app
    c.write(["record", JOB_C, "--channel", "referral", "--historical", "--submitted"])
    a3 = c.app
    e = c.export()
    doc = e.out
    c.check("顶层 schema_version=1、exported_at、applications", doc.get("schema_version") == 1 and doc.get("exported_at")
            and isinstance(doc.get("applications"), list))
    ids = [x["application_id"] for x in doc["applications"]]
    c.check("按 application_id 升序", ids == sorted(ids))
    for x in doc["applications"]:
        missing = [k for k in TOPS if k not in x]
        c.check(f"{x['application_id'][:12]} 字段齐全", not missing, missing)
        c.check(f"{x['application_id'][:12]} 没有 next_followup_at，next_followup_on=null",
                "next_followup_at" not in x and x.get("next_followup_on") is None)
        c.check(f"{x['application_id'][:12]} channel/submission 形状", set(x["channel"]) == {"kind", "platform"}
                and {"confirmed", "occurred_at", "occurred_on", "materials_recorded"} <= set(x["submission"]))
        c.check(f"{x['application_id'][:12]} context_snapshot 是 {{job, match}}", set(x["context_snapshot"]) == {"job", "match"})
        for ev in x["events"]:
            miss = [k for k in EVENT_KEYS if k not in ev]
            c.check(f"{x['application_id'][:12]} 事件 {ev['seq']} 字段齐全、voided_by=null", not miss and ev["voided_by"] is None, miss)
        c.check(f"{x['application_id'][:12]} 事件按 seq 升序", [ev["seq"] for ev in x["events"]] == sorted(ev["seq"] for ev in x["events"]))
        for v in x["material_versions"]:
            c.check("material_versions 每项字段", {"material_hash", "profile_hash", "review_path", "files"} <= set(v))
        for ev in x["events"]:
            if ev["type"] == "submitted":
                c.check("submitted payload 用 material_version_ids", "material_version_ids" in ev["payload"]
                        and "version_ids" not in ev["payload"])
    mr = {i: doc_app(doc, i)["submission"]["materials_recorded"] for i in (a1, a2, a3)}
    c.check("materials_recorded 依次 true / null / false", [mr[a1], mr[a2], mr[a3]] == [True, None, False], mr)
    c.check("补录那条快照两项都是 null", doc_app(doc, a3)["context_snapshot"] == {"job": None, "match": None})
    c.check("UTF-8，中文不转义", "\\u" not in e.stdout and "示例招聘站" in e.stdout)
    c.note("source 的形状", doc_app(doc, a1)["events"][0].get("source"))
    c.note("额外字段", sorted(set(doc_app(doc, a1)) - set(TOPS)) + sorted(set(doc_app(doc, a1)["submission"])))


@scenario("A66")
def a66(c):
    submit_with(c, ["--material", mat(c), "--sent", res(c, "resume-1.pdf")])
    one, two = c.export().stdout, c.export().stdout
    c.check("两次导出除 exported_at 逐字节相同", strip_exported_at(one) == strip_exported_at(two))


@scenario("A67")
def a67(c):
    c.write(REC_A)
    printed = c.export().stdout
    r = c.app_cmd(["export", "--out", "v25.json"])
    f = c.appdir / "exports" / "v25.json"
    c.check("--out 文件名写到 applications/exports/", r.exit == 0 and f.is_file(), r.stderr[:200])
    if f.is_file():
        c.check("内容与打印相同（exported_at 除外）", strip_exported_at(f.read_text(encoding="utf-8")).strip()
                == strip_exported_at(printed).strip())
    for bad in ("sub/v25.json", "../v25.json", "..\\v25.json", str(c.outside / "v25.json")):
        before = tree(c.work)
        r = c.app_cmd(["export", "--out", bad])
        c.check(f"--out {sanitize(bad)} 拒绝、退出 1、不写文件", r.exit == 1 and tree(c.work) == before, f"exit={r.exit} {r.error}")
        c.note(f"--out {sanitize(bad)} 错误码", r.error)
    r = c.app_cmd(["export", "--out", "v25.json"])
    c.note("--out 已存在的文件", f"exit={r.exit} {r.stderr.strip()[:120]}")


@scenario("A68")
def a68(c):
    c.write(REC_A)
    first = c.app
    c.write(["record", JOB_B, "--channel", "email"])
    doc = c.export(first).out
    c.check("只导出指定那一条", [x["application_id"] for x in doc["applications"]] == [first])
    r = c.export("app_ffffffffffffffffffffffffffffffff")
    c.note("导出不存在的 id", f"exit={r.exit} error={r.error} out={r.stdout.strip()[:100]}")


@scenario("A69")
def a69(c):
    submit_with(c, ["--material", mat(c), "--sent", res(c, "resume-1.pdf")])
    s = c.app_cmd(["show", c.app])
    obj = s.out.get("application", s.out) if "application_id" not in s.out else s.out
    c.check("show 与导出中的同一条相同", obj == c.export(c.app).out["applications"][0])
    c.note("show 是否包一层", "否" if "application_id" in s.out else sorted(s.out))


@scenario("A70")
def a70(c):
    c.write(REC_A_SUB)
    c.write(["record", JOB_A, "--channel", "email"])
    c.write(["record", JOB_B, "--channel", "portal"])
    rows = c.app_cmd(["list", "--status", "applied"]).out["applications"]
    c.check("--status applied 1 条", len(rows) == 1)
    rows = c.app_cmd(["list", "--status", "drafted", "--status", "applied"]).out["applications"]
    c.check("两个 --status 3 条", len(rows) == 3)
    rows = c.app_cmd(["list", "--job", JOB_B]).out["applications"]
    c.check("--job JOB_B 1 条", len(rows) == 1 and rows[0]["job_id"] == JOB_B)
    allrows = c.app_cmd(["list"]).out["applications"]
    c.check("每行有 application_id、job_id、status、record_origin",
            all({"application_id", "job_id", "status", "record_origin"} <= set(x) for x in allrows))
    c.note("list 行字段", sorted(allrows[0]))
    c.note("list 顺序", [(x["status"], x["submission"]["occurred_on"]) for x in allrows])


@scenario("A71")
def a71(c):
    submit_with(c, ["--material", mat(c), "--sent", res(c, "resume-1.pdf")])
    before = tree(c.appdir)
    for argv in (["show", c.app], ["list"], ["validate"], ["export"]):
        c.app_cmd(argv)
    c.check("只读命令前后 applications/ 下文件不变", tree(c.appdir) == before)


@scenario("A72")
def a72(c):
    submit_with(c, ["--material", mat(c), "--sent", res(c, "resume-1.pdf")])
    profile = json.loads((c.data / "profile" / "profile.json").read_text(encoding="utf-8"))
    contact = [v for k, v in profile["contact"].items() if v and k != "name"]
    texts = {"show": c.app_cmd(["show", c.app]).stdout, "export": c.export().stdout}
    sent = {f["path"] for v in c.show()["material_versions"] for f in v["files"] if f["role"] == "sent"}
    for p in (c.appdir / "artifacts").rglob("*"):
        if p.is_file() and not any(p.as_posix().endswith(s.split("/")[-1]) and s.split("/")[-2] in p.as_posix() for s in sent):
            texts[p.relative_to(c.appdir).as_posix()] = p.read_text(encoding="utf-8", errors="replace")
    leaks = [(name, x) for name, t in texts.items() for x in contact if x in t]
    c.check("show/export/归档（除发出文件）不含档案联系方式", not leaks, leaks)


@scenario("A73")
def a73(c):
    paths = ["data/applications/applications.sqlite3", "data/applications/applications.sqlite3-journal",
             "data/applications/applications.sqlite3-wal", "data/applications/applications.sqlite3-shm",
             "data/applications/exports/x.json", "data/applications/backups/x.sqlite3",
             "data/applications/artifacts/app_x/mv_x/resume-1.pdf"]
    proc = subprocess.run(["git", "check-ignore", "--no-index"] + paths, cwd=OPTS.repo, capture_output=True, text=True)
    got = set(proc.stdout.split())
    c.check("全部被 git 忽略", got == set(paths), sorted(set(paths) - got))


@scenario("A74")
def a74(c):
    c.write(REC_A_SUB)
    p1 = c.preview(["status", c.app, "interview", "--expected-revision", 2]).out["request_id"]
    p2 = c.preview(["status", c.app, "rejected", "--expected-revision", 2]).out["request_id"]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    procs = []
    for to, rid in (("interview", p1), ("rejected", p2)):
        argv = [sys.executable, "-m", "jobsearch_cn", "application", "status", c.app, to, "--expected-revision", "2",
                "--request-id", rid, "--data-dir", str(c.data)]
        procs.append(subprocess.Popen(argv, cwd=OPTS.repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env))
    results = []
    for proc in procs:
        out, err = proc.communicate(timeout=60)
        results.append((proc.returncode, parse(err.decode("utf-8", "replace"))))
        c.log.append({"argv": ["<parallel status>"], "exit": proc.returncode, "stdout": sanitize(out.decode("utf-8", "replace")),
                      "stderr": sanitize(err.decode("utf-8", "replace"))})
    codes = sorted(code for code, _ in results)
    errors = [e.get("error") for code, e in results if code != 0 and isinstance(e, dict)]
    c.check("恰好一个成功，另一个 stale_revision（或 busy）", codes == [0, 1] and errors and errors[0] in ("stale_revision", "busy"),
            (codes, errors))
    a = c.show()
    c.check("事件 seq 连续 1–3，revision=3", [e["seq"] for e in a["events"]] == [1, 2, 3] and a["revision"] == 3)
    con = sqlite3.connect(c.db)
    n = con.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    con.close()
    c.check("requests 表 2 行", n == 2, n)
    v = c.app_cmd(["validate"])
    c.check("validate 通过", v.exit == 0)
    c.note("落败的一方", errors)


@scenario("A75")
def a75(c):
    c.write(REC_A_SUB)
    rid = c.preview(["status", c.app, "interview", "--expected-revision", 2]).out["request_id"]
    before = tree(c.data)
    locker = subprocess.Popen([sys.executable, "-c",
                               "import sqlite3,sys,time;c=sqlite3.connect(sys.argv[1],isolation_level=None);"
                               "c.execute('BEGIN IMMEDIATE');print('locked',flush=True);time.sleep(8);c.execute('ROLLBACK')",
                               str(c.db)], stdout=subprocess.PIPE, text=True)
    locker.stdout.readline()
    t0 = time.time()
    r = c.commit(["status", c.app, "interview", "--expected-revision", 2], rid)
    took = time.time() - t0
    locker.wait(timeout=30)
    c.check("退出 1、error=busy", r.exit == 1 and r.error == "busy", f"exit={r.exit} {r.error}")
    c.check("约 5 秒后返回（4–7.5 秒）", 4 <= took <= 7.5, round(took, 2))
    after = {k: v for k, v in tree(c.data).items() if not k.endswith("-journal")}
    c.check("锁释放后库不变", after == before)
    c.check("validate 通过", c.app_cmd(["validate"]).exit == 0)
    c.note("等待时间（秒）", round(took, 2))


@scenario("A76")
def a76(c):
    target = c.outside / "elsewhere"
    target.mkdir()
    link = c.appdir
    proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    if not c.check("建出 junction", proc.returncode == 0 and link.exists(), proc.stderr):
        return
    r = c.write(REC_A)
    c.check("拒绝", r.exit != 0, r.exit)
    c.check("链接指向的目录里没有写入", not any(target.iterdir()))
    c.note("链接", f"exit={r.exit} {r.stderr.strip()[:200]}")
    os.rmdir(link)


@scenario("A77")
def a77(c):
    r = c.write(REC_A + ["--actor", "codex"])
    c.check("actor=codex 写进事件", r.exit == 0 and r.out["events"][0]["actor"] == "codex")
    c.check("source.kind=user", r.exit == 0 and (r.out["events"][0].get("source") or {}).get("kind") == "user")
    before = tree(c.data)
    r = c.write(["record", JOB_B, "--channel", "portal", "--actor", "robot"])
    c.rejected(r, "未知 actor", exit="nonzero", before=before)
    c.note("未知 actor", f"exit={r.exit}")


@scenario("A78")
def a78(c):
    r1 = c.write(REC_A_SUB)
    r2 = c.commit(REC_A_SUB, r1.rid)
    c.check("重试返回两条，event_id 相同", r2.exit == 0 and [e["event_id"] for e in r2.out["events"]]
            == [e["event_id"] for e in r1.out["events"]] and len(r2.out["events"]) == 2)
    a = c.show()
    c.check("库中仍两条事件，revision=2", len(a["events"]) == 2 and a["revision"] == 2)


@scenario("A79")
def a79(c):
    r1 = c.write(REC_A)
    c.preview(["status", c.app, "withdrawn", "--expected-revision", 1])
    before = tree(c.data)
    r = c.commit(["status", c.app, "withdrawn", "--expected-revision", 1], r1.rid)
    c.rejected(r, "跨命令复用 request_id", "request_conflict", before=before)


@scenario("A80")
def a80(c):
    r = c.write(["record", JOB_C, "--channel", "portal", "--platform", "示例招聘站", "--historical", "--submitted",
                 "--on", "2026-09-20"])
    c.accepted(r, "补录", warning=True)
    r = c.write(["status", c.app, "no_response", "--expected-revision", 2, "--reason", "不等了", "--on", "2026-10-15"])
    c.accepted(r, "no_response")
    r = c.write(["status", c.app, "interview", "--expected-revision", 3, "--reason", "10月底收到面试邀请", "--on", "2026-10-30"])
    c.accepted(r, "迟到的面试")
    a = c.export().out["applications"][0]
    c.check("status=interview，revision=4，4 条事件", a["status"] == "interview" and a["revision"] == 4
            and [e["type"] for e in a["events"]] == ["created", "submitted", "status_changed", "status_changed"])
    c.check("historical、occurred_on=2026-09-20、快照 null、materials_recorded=false",
            a["record_origin"] == "historical" and a["submission"]["occurred_on"] == "2026-09-20"
            and a["context_snapshot"] == {"job": None, "match": None} and a["submission"]["materials_recorded"] is False)
    c.check("两条 status_changed 的 from/to", [(e["payload"]["from"], e["payload"]["to"]) for e in a["events"][2:]]
            == [("applied", "no_response"), ("no_response", "interview")])


# ------------------------------------------------------------------ main

def main():
    global OPTS
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--typst", required=True)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--only", help="comma-separated scenario ids")
    OPTS = ap.parse_args()
    OPTS.repo = OPTS.repo.resolve()
    OPTS.output = OPTS.output.resolve()
    if HOLDOUT in OPTS.output.parents or OPTS.output == HOLDOUT:
        sys.exit("--output must be outside the frozen holdout")
    OPTS.output.mkdir(parents=True, exist_ok=True)
    SANITIZE.extend([(str(OPTS.output / "work"), "<work>"), (str(OPTS.output), "<output>"),
                     (str(OPTS.repo), "<repo>"), (str(Path(OPTS.typst).resolve()), "<typst>"),
                     (str(Path.home()), "<home>")])

    oracle = subprocess.run([sys.executable, str(HOLDOUT / "verify_oracle.py")], capture_output=True, text=True,
                            encoding="utf-8")
    frozen_ok = oracle.returncode == 0
    scenarios = json.loads((HOLDOUT / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
    wanted = set(OPTS.only.split(",")) if OPTS.only else None
    make_templates()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=OPTS.repo, capture_output=True, text=True).stdout.strip()
    results = []
    for s in scenarios:
        if wanted and s["id"] not in wanted:
            continue
        if s["part"] != "M4-1a":
            results.append({"id": s["id"], "part": s["part"], "title": s["title"], "verdict": "waiting_m4_1b"})
            continue
        t0 = time.time()
        c = Ctx(s["id"], s["setup"])
        try:
            SC[s["id"]](c)
            crash = None
        except Exception as exc:  # a crash is a failed comparison, recorded with the scenario
            crash = f"{type(exc).__name__}: {exc}"
        # pass: no strict check failed. A scenario whose checks all depend on an "impl" outcome may end
        # with no strict check at all; its observations are in impl_observed.
        verdict = "pass" if all(x["ok"] for x in c.checks) and crash is None else "fail"
        results.append({"id": s["id"], "part": s["part"], "title": s["title"], "verdict": verdict,
                        "seconds": round(time.time() - t0, 1), "crash": sanitize(crash) if crash else None,
                        "checks": c.checks, "impl_observed": c.impl})
        logdir = OPTS.output / "logs"
        logdir.mkdir(exist_ok=True)
        (logdir / f"{s['id']}.json").write_text(json.dumps(c.log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(s["id"], verdict, flush=True)
    summary = {
        "tested_head": head,
        "frozen_oracle_ok": frozen_ok,
        "counts": {v: sum(1 for r in results if r["verdict"] == v) for v in ("pass", "fail", "waiting_m4_1b")},
        "failed": [r["id"] for r in results if r["verdict"] == "fail"],
        "results": results,
    }
    (OPTS.output / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary["counts"]), "failed:", summary["failed"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
