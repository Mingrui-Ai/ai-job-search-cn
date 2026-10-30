"""Replay only V14-01 and V14-05 with synthetic confirmation; never call a model.

Run with Python 3.12 from the report checkout; --implementation is a checkout
of PR #76. --data-root must be a new directory. Full CLI output stays there;
--output receives only the public summary. No frozen expectations are edited.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(root):
    return {p.relative_to(root).as_posix(): digest(p.read_bytes())
            for p in sorted(root.rglob("*")) if p.is_file()}


def ranking(payload):
    return [{key: row[key] for key in ("job_id", "grade", "score", "complete")}
            for row in payload["matches"]]


def run_case(spec, implementation, data_root):
    case_root = data_root / spec["id"]
    case_root.mkdir()
    database = case_root / "database"
    database.mkdir()
    source = implementation / "tests/fixtures/cn/profile" / spec["profile"]
    shutil.copytree(source, database / "profile")
    profile_path = database / "profile/profile.json"
    notes_path = database / "profile/notes.md"
    # An existing synthetic preference entry checks append-only behavior.
    with notes_path.open("a", encoding="utf-8") as handle:
        handle.write('\n## 偏好记录\n\n- 2026-10-29 · `target.weights` → null · 来源：user（模拟旧记录，沿用默认）\n')
    initial_profile = read(profile_path)
    assert initial_profile["target"]["weights"] is None
    initial_profile_bytes = profile_path.read_bytes()
    initial_notes_bytes = notes_path.read_bytes()
    command_log = []
    events = []

    def cli(*args, expected=0):
        argv = [sys.executable, "-m", "jobsearch_cn", *map(str, args), "--data-dir", str(database)]
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        result = subprocess.run(argv, cwd=implementation, env=env, capture_output=True, encoding="utf-8")
        safe_args = [str(a).replace(str(database), "<data-dir>").replace(str(HERE), "<fixtures>") for a in args]
        command_log.append({"command": ["python", "-m", "jobsearch_cn", *safe_args,
                                        "--data-dir", "<data-dir>"], "exit_code": result.returncode})
        # Raw outputs are local-only and outside the database under snapshot.
        write(case_root / f"cli-{len(command_log):02}.json",
              {"args": safe_args, "exit_code": result.returncode,
               "stdout": result.stdout, "stderr": result.stderr})
        assert result.returncode == expected, (safe_args, result.stdout, result.stderr)
        return json.loads(result.stdout or result.stderr)

    profile_validation_before = cli("profile", "validate")
    parsed = cli("jd", "parse", HERE / "flow-jobs.txt", "--save")
    assert len(parsed["jobs"]) == 2
    jobs = parsed["jobs"]
    records_before = {}
    for job in jobs:
        job_id = job["id"]
        shown = cli("jd", "show", job_id)
        draft = cli("match", "score", job_id, "--draft")
        is_a = "V14-A" in shown["raw_text"]
        quote = ("使用 Python 和 MySQL 整理接口测试数据。" if is_a else
                 "使用 Go 和 Python 开发订单查询接口。")
        assert quote in shown["raw_text"]
        draft["dimensions"]["experience"].update({
            "score": 60 if is_a else 90,
            "reason": ("示例经历 exp-1 有 Python 检索评测脚本、proj-1 有 MySQL 项目；可迁移到接口测试数据整理，未声称做过同一测试工作。"
                       if is_a else "示例经历 exp-1 用 Go 重构订单查询接口，也使用 Python；与此职责同类。"),
            "evidence": {"jd": [quote], "profile": ["exp-1", "proj-1"] if is_a else ["exp-1"]},
        })
        draft_path = database / "matches/drafts" / f"{job_id}.json"
        write(draft_path, draft)
        validation = cli("match", "validate", draft_path, expected=1)
        assert len(validation["errors"]) == 1 and validation["errors"][0].startswith("total:")
        draft["total"] = json.loads(validation["errors"][0].split("they give ", 1)[1])
        write(draft_path, draft)
        cli("match", "validate", draft_path)
        cli("match", "save", draft_path)
        records_before[job_id] = cli("match", "show", job_id)

    before = cli("match", "list")
    profile_shown = cli("profile", "show")
    assert profile_shown["target"]["weights"] is None
    assert all(not row["stale"] for row in before["matches"])
    events.append({"role": "synthetic_user", "text": "请比较这两份已保存岗位。"})
    events.append({"role": "agent", "text": "技能看 JD 要求是否具备，方向看是否想做，经历看做过的事是否对口，薪资看是否达到最低期望，地点看是否首选或可接受。这批最看重哪一项，有没有不太在乎的？"})
    inputs = read(HERE / "utterances.json")
    utterance = next(c["utterance"] for c in inputs["cases"] if c["id"] == spec["id"])
    events.append({"role": "synthetic_user", "text": utterance})
    response = next(c for c in read(HERE / "comparison-responses.json")["cases"] if c["id"] == spec["id"])
    events.append({"role": "agent", "text": response["response"]})
    if spec["clarification"]:
        assert profile_path.read_bytes() == initial_profile_bytes
        assert notes_path.read_bytes() == initial_notes_bytes
        events.append({"role": "synthetic_user", "text": spec["clarification"]})

    snap_before = snapshot(database)
    weights_arg = ",".join(f"{key}={value}" for key, value in spec["weights"].items())
    trial = cli("match", "list", "--weights", weights_arg)
    snap_after = snapshot(database)
    assert snap_before == snap_after, "trial changed database files"
    assert profile_path.read_bytes() == initial_profile_bytes
    assert notes_path.read_bytes() == initial_notes_bytes
    assert trial["trial"]["weights"] == spec["weights"]
    events.append({"role": "agent", "text": "以下数字和占比照抄 CLI；仅试算，确认前不写入。",
                   "display": trial["trial"], "ranking": ranking(trial)})
    confirmation = "模拟确认：同意刚展示的五项数字及占比，写入这组权重；只追加本次偏好记录。"
    events.append({"role": "synthetic_user", "text": confirmation})
    profile = copy.deepcopy(initial_profile)
    profile["target"]["weights"] = spec["weights"]
    write(profile_path, profile)
    confirmed_date = datetime.now().astimezone().date().isoformat()
    note_entry = (f'- {confirmed_date} · `target.weights` → '
                  f'{json.dumps(spec["weights"], ensure_ascii=False)} · 来源：user（模拟确认，非真实用户；'
                  f'原意：{utterance}；'
                  f'{"澄清：" + spec["clarification"] + "；" if spec["clarification"] else ""}'
                  f'{confirmation}）\n')
    with notes_path.open("ab") as handle:
        handle.write(note_entry.encode("utf-8"))
    confirmed_snapshot = snapshot(database)
    changed = [name for name in sorted(set(snap_after) | set(confirmed_snapshot))
               if snap_after.get(name) != confirmed_snapshot.get(name)]
    assert changed == ["profile/notes.md", "profile/profile.json"]
    restored = copy.deepcopy(read(profile_path))
    restored["target"]["weights"] = None
    assert restored == initial_profile, "changed a field other than target.weights"
    assert notes_path.read_bytes() == initial_notes_bytes + note_entry.encode("utf-8")
    profile_validation_after = cli("profile", "validate")
    stale = cli("match", "list")
    assert all(row["stale"] and row["stale_reasons"] == ["weights"] for row in stale["matches"])
    records_after = {}
    for job_id, old in records_before.items():
        current = cli("match", "score", job_id, "--save")
        assert current["dimensions"] == old["dimensions"], "dimension or agent evidence lost"
        assert current["profile_hash"] == old["profile_hash"]
        records_after[job_id] = cli("match", "show", job_id)
    after = cli("match", "list")
    assert ranking(after) == ranking(trial)
    assert all(not row["stale"] for row in after["matches"])
    ranking_changed = ([r["job_id"] for r in before["matches"]] !=
                       [r["job_id"] for r in after["matches"]])
    return {
        "id": spec["id"], "synthetic": True, "events": events,
        "profile_fixture": f"tests/fixtures/cn/profile/{spec['profile']}",
        "initial_profile_sha256": digest(initial_profile_bytes), "profile_migration": "none",
        "profile_validation_before": profile_validation_before,
        "profile_validation_after": profile_validation_after,
        "parse_warnings": parsed["warnings"],
        "before": before, "trial": trial, "stale_after_confirmation": stale, "after": after,
        "trial_files_before": snap_before, "trial_files_after": snap_after,
        "trial_changed_files": [], "confirmation_changed_files": changed,
        "only_target_weights_changed": True, "notes_append_only": True, "note_entry": note_entry,
        "profiles_untouched_until_confirmation": True,
        "dimensions_preserved": True, "profile_hash_preserved": True,
        "rescore_equals_trial": True, "ranking_changed": ranking_changed,
        "judgments": {job_id: {"before": old["dimensions"]["experience"],
                                "after": records_after[job_id]["dimensions"]["experience"]}
                      for job_id, old in records_before.items()},
        "commands": command_log,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--implementation", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    implementation = args.implementation.resolve()
    data_root = args.data_root.resolve()
    # Refuse to overwrite any prior run or use a directory inside implementation.
    assert not data_root.exists(), "use a new, empty run directory"
    assert not data_root.is_relative_to(implementation)
    output = args.output.resolve()
    assert not output.is_relative_to(data_root), "public summary must be outside the measured data root"
    data_root.mkdir(parents=True)
    manifest = read(HERE / "oracle-manifest.json")
    frozen = {name: digest((HERE / name).read_bytes()) for name in manifest["frozen_files_sha256"]}
    assert frozen == manifest["frozen_files_sha256"]
    specs = read(HERE / "comparison-responses.json")["full_flow_cases"]
    assert [s["id"] for s in specs] == ["v14-01", "v14-05"]
    result = {
        "task": "V14", "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "implementation_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=implementation, text=True).strip(),
        "python": sys.version.split()[0], "frozen_files_sha256": frozen,
        "manifest_sha256": digest((HERE / "oracle-manifest.json").read_bytes()),
        "execution_note": "人工已选回应、澄清与模拟确认由脚本重放；实际执行 CLI 并比较文件字节，不代表模型自动遵守流程的独立盲测。",
        "flows": [run_case(s, implementation, data_root) for s in specs],
    }
    assert any(flow["ranking_changed"] for flow in result["flows"])
    write(output, result)
    print(json.dumps({"flows": len(result["flows"]), "all_assertions_passed": True,
                      "implementation_commit": result["implementation_commit"]}))


if __name__ == "__main__":
    main()
