"""Read-only integrity checks for V23; never import the M3-4 implementation."""

import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re


FIX = Path(__file__).resolve().parent
SLOT = re.compile(r"\{\{([a-z_]+)\}\}")
LIMITS = {"greeting_body": 150, "email_subject": 40,
          "email_body": 600, "referral_body": 300}


def load(path):
    return json.loads((FIX / path).read_text(encoding="utf-8"))


def pointer(record, path):
    value = record
    for part in path.strip("/").split("/"):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def replace_pointer(record, path, value):
    parts = path.strip("/").split("/")
    parent = record
    for part in parts[:-1]:
        parent = parent[int(part)] if isinstance(parent, list) else parent[part]
    key = int(parts[-1]) if isinstance(parent, list) else parts[-1]
    assert key in parent if isinstance(parent, dict) else key < len(parent)
    parent[key] = value


def render(case, contexts):
    records = copy.deepcopy(contexts[case["context"]])
    for patch in case["overrides"]:
        replace_pointer(records[patch["record"]], patch["pointer"], patch["value"])
    values = {key: pointer(records[ref["record"]], ref["pointer"])
              for key, ref in case["slots"].items()}
    # One substitution pass only: a placeholder in a value remains observable.
    def field(text):
        if text is None:
            return None
        return SLOT.sub(lambda match: str(values[match[1]])
                        if match[1] in values else match[0], text)
    return {key: field(case[key]) for key in ("subject", "body")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pre-freeze", action="store_true",
                        help="Check corpus consistency before creating its manifest")
    args = parser.parse_args()
    inputs, oracle = load("inputs.json"), load("expectations.json")
    assert oracle["length_limits"] == LIMITS
    actual_paths = set()
    for path in sorted(FIX.rglob("*")):
        if path.is_dir():
            assert not path.is_symlink()
            continue
        assert not path.is_symlink()
        relative = path.relative_to(FIX).as_posix()
        actual_paths.add(relative)
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        assert not raw.startswith(b"\xef\xbb\xbf"), relative
        assert "\ufffd" not in text and "\r" not in text, relative
        if path.suffix == ".json":
            json.loads(text)

    if not args.pre_freeze:
        manifest = load("oracle-manifest.json")
        hashes = manifest["frozen_files_sha256"]
        assert set(hashes) == actual_paths - {"oracle-manifest.json"}
        for relative, digest in hashes.items():
            assert hashlib.sha256((FIX / relative).read_bytes()).hexdigest() == digest, relative

    cases, expected = inputs["cases"], oracle["cases"]
    assert len({case["id"] for case in cases}) == len(cases)
    assert [case["id"] for case in cases] == [case["id"] for case in expected]
    contexts = {}
    for directory in sorted((FIX / "contexts").iterdir()):
        profile = load(f"contexts/{directory.name}/profile/profile.json")
        job = load(f"contexts/{directory.name}/job.json")
        contexts[directory.name] = {"profile": profile, "job": job}
        assert profile["contact"]["email"].endswith("@example.invalid")
        assert profile["contact"]["phone"] == "00000000000"
        assert profile["contact"]["name"].startswith("示例候选")
        assert job["company"].startswith("示例留出")
        assert job["source"]["url"] is None
        assert (directory / "jd.txt").read_text(encoding="utf-8").rstrip("\n") == job["raw_text"]
        for evidence in job["evidence"].values():
            assert evidence["text"] in job["raw_text"]
        for entry in profile["education"] + profile["skills"] + profile["experience"]:
            assert (directory / "profile/sources" / entry["source"]).is_file()

    selection_pairs = set()
    boundary_pairs = set()
    for case, want in zip(cases, expected):
        assert case["context"] in contexts
        assert case["kind"] in {"greeting", "email", "referral"}
        assert want["outcome"] in {"accept", "reject", "warn"}
        assert bool(want["required_error_categories"]) == (want["outcome"] == "reject")
        assert bool(want["required_warning_categories"]) == (want["outcome"] == "warn")
        if case["operation"] == "select_template":
            selection_pairs.add((want["template_family"], case["kind"]))
            assert want["outcome"] == "accept"
            continue
        profile_ids = {entry["id"] for entry in contexts[case["context"]]["profile"]["experience"]}
        assert set(case["refs"]) <= profile_ids
        rendered = render(case, contexts)
        for field, length in want.get("rendered_codepoints", {}).items():
            assert len(rendered[field]) == length, case["id"]
        for field, length in want.get("rendered_utf8_bytes", {}).items():
            assert len(rendered[field].encode("utf-8")) == length, case["id"]
        if "focus_field" in case:
            focus = case["focus_field"]
            field = "subject" if focus.endswith("_subject") else "body"
            length = len(rendered[field])
            boundary_pairs.add((focus, length - LIMITS[focus]))
            assert len(case[field]) == want["template_before_substitution_codepoints"]
            assert want["outcome"] == ("reject" if length > LIMITS[focus] else "accept")
        if "unfilled_placeholder" in want["required_error_categories"]:
            assert any(SLOT.search(value or "") for value in rendered.values())
        if case["kind"] != "email":
            assert case["subject"] is None

    assert boundary_pairs == {(key, offset) for key in LIMITS for offset in (-1, 0, 1)}
    if not args.pre_freeze:
        assert selection_pairs == {(direction, kind) for direction in oracle["template_families"]
                                   for kind in ("greeting", "email", "referral")}
        assert len(oracle["template_families"]) == 5
    summary = {"contexts": len(contexts), "cases": len(cases),
               "outcomes": dict(Counter(case["outcome"] for case in expected)),
               "selection_cases": len(selection_pairs), "boundary_cases": len(boundary_pairs),
               "frozen_files": len(actual_paths) - ("oracle-manifest.json" in actual_paths),
               "manifest_checked": not args.pre_freeze}
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
