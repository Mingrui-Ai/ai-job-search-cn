"""Check V25's frozen scenarios and inputs for internal consistency.

Does not import jobsearch_cn: the oracle must stand on the design alone.
Exit 0 when every check passes; prints a summary as JSON.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

FIX = Path(__file__).resolve().parent
PARTS = {"A": "M4-1a", "B": "M4-1b"}
ERROR_CODES = {"invalid", "transition", "stale_revision", "request_conflict", "busy"}
STATES = ["drafted", "applied", "interview", "offer", "no_response",
          "hired", "rejected", "withdrawn", "offer_declined"]
# 设计 §4 的状态表，在这里独立再写一遍，和 scenarios.json 对照
ALLOWED = {
    "drafted": {"withdrawn"},
    "applied": {"interview", "offer", "rejected", "withdrawn", "no_response"},
    "interview": {"offer", "rejected", "withdrawn", "no_response"},
    "offer": {"hired", "offer_declined", "rejected", "withdrawn"},
    "no_response": {"interview", "offer", "rejected"},
    "hired": set(), "rejected": set(), "withdrawn": set(), "offer_declined": set(),
}
TERMINAL = {"hired", "rejected", "withdrawn", "offer_declined"}


def load(rel):
    return json.loads((FIX / rel).read_text(encoding="utf-8"))


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def profile_hash(profile):
    data = {key: value for key, value in profile.items() if key != "contact"}
    data["target"] = {key: value for key, value in data["target"].items() if key != "weights"}
    return canonical_hash(data)


def check_expect(sid, expect, problems):
    if expect is None:
        return
    if "matrix" in expect:
        return
    if "one_of" in expect:
        for item in expect["one_of"]:
            check_expect(sid, item, problems)
        return
    result = expect.get("result")
    if result not in {"accepted", "rejected", "impl"}:
        problems.append(f"{sid}: result {result!r}")
    if expect.get("exit") not in {0, 1, 2, "impl"}:
        problems.append(f"{sid}: exit {expect.get('exit')!r}")
    error = expect.get("error")
    if error is not None and error != "impl" and error not in ERROR_CODES:
        problems.append(f"{sid}: error code {error!r} not in design")
    if result == "accepted" and (expect.get("exit") != 0 or error is not None):
        problems.append(f"{sid}: accepted must exit 0 without error")
    if result == "rejected":
        if expect.get("writes") is not False:
            problems.append(f"{sid}: rejected step must not write")
        if expect.get("exit") == 0:
            problems.append(f"{sid}: rejected step exits 0")


def main():
    problems = []
    data = load("scenarios.json")
    conv = data["conventions"]
    scenarios = data["scenarios"]

    # 编号、部分、计数
    ids = [s["id"] for s in scenarios]
    if len(set(ids)) != len(ids):
        problems.append("duplicate scenario ids")
    for prefix, part in PARTS.items():
        mine = [s for s in scenarios if s["id"].startswith(prefix)]
        want = [f"{prefix}{n:02d}" for n in range(1, len(mine) + 1)]
        if [s["id"] for s in mine] != want:
            problems.append(f"{part}: ids not consecutive")
        if any(s["part"] != part for s in mine):
            problems.append(f"{part}: wrong part label")
    counts = {"total": len(scenarios), "M4-1a": sum(s["part"] == "M4-1a" for s in scenarios),
              "M4-1b": sum(s["part"] == "M4-1b" for s in scenarios)}
    if counts != data["counts"]:
        problems.append(f"counts {data['counts']} != {counts}")

    # 状态表
    if data["states"] != STATES:
        problems.append("states differ from design")
    if {k: set(v) for k, v in data["transition_table"].items()} != ALLOWED:
        problems.append("transition_table differs from design §4")
    matrix_cells = 0
    for s in scenarios:
        for st in s["steps"]:
            exp = st["expect"] or {}
            if "matrix" not in exp:
                continue
            frm = re.search(r"从 (\w+) 出发", s["title"]).group(1)
            cells = exp["matrix"]
            if set(cells) != set(STATES):
                problems.append(f"{s['id']}: matrix misses targets")
            for to, verdict in cells.items():
                want = "allow" if to in ALLOWED[frm] else "transition"
                if verdict != want:
                    problems.append(f"{s['id']}: {frm}->{to} {verdict} != {want}")
                matrix_cells += 1
            if frm in TERMINAL and any(v == "allow" for v in cells.values()):
                problems.append(f"{s['id']}: terminal state allows a change")

    # 期望取值、模式、准备、占位符
    modes = set(conv["mode"])
    setups = set(data["setups"])
    placeholders = set(conv["placeholders"]) | {"{REV}", "{APP}"}
    used_placeholders = set()
    for s in scenarios:
        setup = s["setup"]
        if setup not in setups and not (setup.startswith("base+path:") and setup[10:] in STATES):
            problems.append(f"{s['id']}: unknown setup {setup}")
        if not s["checks"] and not s["impl_check"]:
            problems.append(f"{s['id']}: no checks")
        for st in s["steps"]:
            if st["mode"] not in modes:
                problems.append(f"{s['id']}: unknown mode {st['mode']}")
            check_expect(s["id"], st["expect"], problems)
            used_placeholders |= set(re.findall(r"\{[A-Z_]+\}", st["cmd"]))
        for text in s["checks"]:
            used_placeholders |= set(re.findall(r"\{[A-Z_]+\}", text))
    for unknown in sorted(used_placeholders - placeholders):
        problems.append(f"undefined placeholder {unknown}")

    # 输入文件与冻结的摘要
    ph = conv["placeholders"]
    job_a = re.search(r"job_[0-9a-f]{12}", ph["{JOB_A}"]).group(0)
    profile = load("inputs/profile/profile.json")
    material = load("inputs/material/resume-1.json")
    edited = load("inputs/material/resume-1.edited.json")
    review = load("inputs/review/review-1-r1.json")
    if material["job_id"] != job_a or edited["job_id"] != job_a or review["job_id"] != job_a:
        problems.append("material/review job_id != {JOB_A}")
    if profile_hash(profile) != ph["{PROFILE_HASH}"] or material["profile_hash"] != ph["{PROFILE_HASH}"]:
        problems.append("profile_hash mismatch")
    if canonical_hash(material) != ph["{MAT_HASH}"] or review["material_hash"] != ph["{MAT_HASH}"]:
        problems.append("material_hash mismatch")
    if canonical_hash(edited) != ph["{MAT_HASH_EDITED}"]:
        problems.append("edited material_hash mismatch")
    if review["verdict"] != "pass" or review["findings"]:
        problems.append("review must be a clean pass")
    if {k: v for k, v in edited.items() if k != "skills"} != {k: v for k, v in material.items() if k != "skills"} \
            or sorted(edited["skills"]) != sorted(material["skills"]):
        problems.append("edited material must differ only in skill order")
    invalid = load("inputs/material/resume-9.invalid.json")
    refs = {item["id"] for item in profile["experience"]}
    if invalid["experience"][0]["ref"] in refs:
        problems.append("invalid material must reference a missing entry")
    contact = [v for v in profile["contact"].values() if v]
    for text in [json.dumps(x, ensure_ascii=False) for x in (material, edited, review)]:
        if any(c in text for c in contact):
            problems.append("contact details leaked into material/review inputs")

    manifest = load("oracle-manifest.json")
    for rel, digest in manifest["frozen_files_sha256"].items():
        path = FIX / rel
        if not path.exists() or sha256_file(path) != digest:
            problems.append(f"manifest mismatch: {rel}")
    listed = set(manifest["frozen_files_sha256"])
    actual = {p.relative_to(FIX).as_posix() for p in FIX.rglob("*") if p.is_file()
              and p.name not in {"oracle-manifest.json"} and "__pycache__" not in p.parts}
    if listed != actual:
        problems.append(f"manifest lists {sorted(listed ^ actual)} differently")

    print(json.dumps({"ok": not problems, "counts": counts, "matrix_cells": matrix_cells,
                      "frozen_files": len(listed), "problems": problems}, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
