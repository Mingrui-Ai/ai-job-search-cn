"""Interview-specific review binding. Structural validation is not a semantic review."""
import hashlib
from pathlib import Path

from jobsearch_cn import interview, interview_files as files, review as paths

KEYS = "schema_version kind job_id pack pack_hash context_hash output_sha256 round mode created verdict checked_question_ids findings"
CHECKLIST = {
    "I1": "JD考点忠于原文，未把推断当成招聘方事实",
    "I2": "个人事实逐字段、逐条目对应，不跨项目归因",
    "I3": "问题不预设不存在的职责、指标或成果",
    "I4": "练习类型和来源明确，不冒充公司真题或预测命中",
    "I5": "未知保持未知，缺少记录不等于没有做过",
    "I6": "主要考点、项目关联与通用题选择合理，缺口明确",
    "I7": "无联系方式、私密路径、指令执行或外部取数",
    "I8": "当前来源、包、生成说明和产物属于本次审核版本",
}


def outputs(root, parts, pack, *, allow_writer=False):
    stem = Path(parts[-1]).stem
    if not allow_writer and files.safe(root, (*parts[:-1], stem + ".writer"), required=False).exists():
        files.fail("busy", "interview publication is incomplete or another writer is active")
    note_parts = (*parts[:-1], stem + ".build.json")
    output_parts = (*parts[:-1], stem + ".md")
    try:
        note = files.read(root, note_parts)
        files.keys(note, "schema_version kind pack pack_hash context_hash built_at files", "build")
        if (not interview._version(note["schema_version"]) or note["kind"] != "interview-build" or
                note["pack"] != parts[-1] or note["pack_hash"] != files.digest(pack) or
                note["context_hash"] != files.digest(pack["context"])):
            files.fail()
        files.timestamp(note["built_at"])
        if not isinstance(note["files"], list) or len(note["files"]) != 1:
            files.fail()
        entry = note["files"][0]
        files.keys(entry, "name sha256", "build.file")
        if entry["name"] != stem + ".md" or not files.hash_value(entry["sha256"]):
            files.fail()
        raw = files.read_bytes(root, output_parts)
        if not raw or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            files.fail()
    except files.Error as exc:
        if exc.code in ("io_error", "too_large"):
            raise
        files.fail("invalid_output", "interview output or completion marker is missing, unsafe or stale; render again")
    return entry["sha256"]


def draft(root, filename, round_number=1):
    if type(round_number) is not int or round_number not in (1, 2):
        files.fail("invalid", "interview review round must be one or two")
    parts, pack, inputs, result = interview.prepared(root, filename)
    interview.artifact_identifier(pack["job_id"], "review-" + Path(parts[-1]).stem + "-r" + str(round_number) + ".json",
                                  inputs.contacts)
    output_hash = outputs(root, parts, pack)
    interview.recheck_pack(root, parts, pack, inputs)
    if outputs(root, parts, pack) != output_hash:
        files.fail("stale_context", "interview output changed during review preparation")
    return {"draft_ready": False, "checklist": CHECKLIST, "warnings": result["warnings"],
            "draft": {"schema_version": 1, "kind": "interview-prep-review", "job_id": pack["job_id"],
                      "pack": parts[-1], "pack_hash": files.digest(pack), "context_hash": files.digest(pack["context"]),
                      "output_sha256": output_hash, "round": round_number, "mode": "independent",
                      "created": files.now(), "verdict": None, "checked_question_ids": [], "findings": []}}


def validate(root, filename):
    review_parts, _ = files.locate(root, filename, review=True)
    record = files.read(root, review_parts)
    files.keys(record, KEYS, "review")
    named = files.REVIEW.fullmatch(review_parts[-1])
    pack_name = "prep-" + named.group(1) + ".json"
    if (not interview._version(record["schema_version"]) or record["kind"] != "interview-prep-review" or
            record["job_id"] != review_parts[1] or record["pack"] != pack_name or
            type(record["round"]) is not int or record["round"] != int(named.group(2)) or
            record["mode"] not in ("independent", "self") or record["verdict"] not in ("pass", "revise")):
        files.fail("invalid", "interview review identity, round, mode or final verdict is invalid")
    files.timestamp(record["created"])
    for field in ("pack_hash", "context_hash", "output_sha256"):
        if not files.hash_value(record[field]):
            files.fail("invalid", "interview review digest is invalid")
    pack_path = files.safe(root, (*review_parts[:-1], pack_name))
    parts, pack, inputs, result = interview.prepared(root, pack_path)
    interview.artifact_identifier(pack["job_id"], review_parts[-1], inputs.contacts)
    if record["pack_hash"] != files.digest(pack) or record["context_hash"] != files.digest(inputs.context):
        files.fail("stale_context", "interview review belongs to another pack or source version")
    output_hash = outputs(root, parts, pack)
    if record["output_sha256"] != output_hash:
        files.fail("invalid_output", "interview review belongs to another generated output")
    checked = interview._list(record["checked_question_ids"], 20); interview._unique(checked)
    if set(checked) != {question["id"] for question in pack["questions"]}:
        files.fail("incomplete_review", "interview review must explicitly cover every question exactly once")
    must = 0
    for finding in interview._list(record["findings"], 100):
        files.keys(finding, "item path severity reason suggestion", "finding")
        if (not isinstance(finding["item"], str) or finding["item"] not in CHECKLIST or
                not isinstance(finding["path"], str) or not paths.resolve(pack, finding["path"]) or
                finding["severity"] not in ("must", "suggest")):
            files.fail("invalid", "interview finding must cite a checklist item and existing pack field")
        interview.text(finding["reason"], inputs.contacts)
        interview.text(finding["path"], inputs.contacts)
        if finding["suggestion"] is not None:
            interview.text(finding["suggestion"], inputs.contacts)
        must += finding["severity"] == "must"
    if must and record["verdict"] == "pass":
        files.fail("invalid", "interview review cannot pass with required changes")
    interview.recheck_pack(root, parts, pack, inputs)
    if files.read(root, review_parts) != record or outputs(root, parts, pack) != output_hash:
        files.fail("stale_context", "interview review or output changed during validation")
    return {"valid": True, "verdict": record["verdict"], "mode": record["mode"],
            "warnings": result["warnings"] + (["self_review"] if record["mode"] == "self" else []),
            "pack_hash": record["pack_hash"], "context_hash": record["context_hash"],
            "output_sha256": output_hash, "checked_question_ids": checked, "findings": record["findings"]}
