"""Run V22 against unchanged frozen inputs; write observations, never expectations.

Run from the repository root with the configured Typst executable and pypdf.
The output directory must not exist. Temporary data contains only synthetic fixtures.
"""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from unittest import mock
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[4]
FROZEN = ROOT / "tests/fixtures/cn/resume-m3-2b-holdout"
FREEZE = "1d6953ee75bf14fa39b6efd1c956a2f4aba32063"
TARGET = "201475af8135f541730b6f81af3b3afd9f9e615b"
sys.path.insert(0, str(ROOT))

from jobsearch_cn import cli, material, resume_docx, resume_pdf, vocab  # noqa: E402
from pypdf import PdfReader  # noqa: E402


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def compact(text):
    # Preserve every non-whitespace character, including punctuation and digits.
    return re.sub(r"\s+", "", text)


def strings(value):
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [text for item in value for text in strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in strings(item)]
    return []


def delta(expected, actual, path=""):
    if type(expected) is not type(actual):
        return [{"path": path, "expected": expected, "actual": actual}]
    if isinstance(expected, dict):
        result = []
        for key in sorted(expected.keys() | actual.keys()):
            if key not in expected or key not in actual:
                result.append({"path": path + "/" + key,
                               "expected": expected.get(key), "actual": actual.get(key)})
            else:
                result.extend(delta(expected[key], actual[key], path + "/" + key))
        return result
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return [{"path": path, "expected": expected, "actual": actual}]
        return [diff for index, (left, right) in enumerate(zip(expected, actual))
                for diff in delta(left, right, path + "/" + str(index))]
    return [] if expected == actual else [{"path": path, "expected": expected, "actual": actual}]


def section_comparison(expected, actual):
    before = {section["title"]: section for section in expected["sections"]}
    after = {section["title"]: section for section in actual["sections"]}
    return {
        "expected_order": list(before), "actual_order": list(after),
        "missing_sections": sorted(before.keys() - after.keys()),
        "extra_sections": sorted(after.keys() - before.keys()),
        "sections": {title: delta(section, after.get(title), "/sections/" + title)
                     for title, section in before.items()},
        "header_differences": delta({k: v for k, v in expected.items() if k != "sections"},
                                    {k: v for k, v in actual.items() if k != "sections"}),
    }


def docx_text(path):
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as package:
        tree = ET.fromstring(package.read("word/document.xml"))
    paragraphs = []
    for paragraph in tree.findall(".//w:p", ns):
        paragraphs.append("".join("\t" if node.tag.endswith("}tab") else node.text or ""
                                  for node in paragraph.iter()
                                  if node.tag in ("{" + ns["w"] + "}t", "{" + ns["w"] + "}tab")))
    return "\n".join(paragraphs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--typst")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("use a new output directory; prior observations are preserved")
    if FROZEN == output or FROZEN in output.parents:
        parser.error("observations must be outside the frozen directory")
    manifest = load(FROZEN / "oracle-manifest.json")["frozen_files_sha256"]
    for name, digest in manifest.items():
        assert hashlib.sha256((FROZEN / name).read_bytes()).hexdigest() == digest, name
    assert not git("diff", FREEZE, "--", str(FROZEN)), "frozen Git tree changed"
    assert not git("diff", TARGET, "--", "jobsearch_cn", "tests/test*.py", "tools"), "target code changed"
    typst = resume_pdf.find_typst(args.typst)
    oracle = load(FROZEN / "expectations.json")
    output.mkdir(parents=True)
    metadata = {
        "freeze_commit": FREEZE, "target_commit": TARGET,
        "checkout_commit": git("rev-parse", "HEAD").decode().strip(),
        "frozen_files_verified": len(manifest), "frozen_git_tree_unchanged": True,
        "target_code_unchanged": True, "python": sys.version.split()[0],
        "typst": subprocess.check_output([typst, "--version"], text=True).strip(),
        "pdf_reader": "pypdf " + __import__("pypdf").__version__,
        "scope": "Frozen flat content, validation, generated text layers; no new Office UI acceptance",
        "adapter": {"filename": "material.json -> resume-1.json (byte-identical copy)",
                    "job_ids": {case["id"]: "job_00000022000" + str(index)
                                for index, case in enumerate(oracle["cases"], 1)},
                    "reason": "PR #111 approved filename/job-id contract after the freeze; only temporary copies change"},
    }
    all_results = []
    with tempfile.TemporaryDirectory(prefix="v22-comparison-") as temporary:
        data_root = Path(temporary)

        def sanitized(text):
            for path, label in ((typst, "<typst>"), (sys.executable, "<python>"),
                                (str(data_root), "<data>"), (str(ROOT), "<repo>")):
                text = text.replace(path, label).replace(path.replace("\\", "/"), label)
            return text

        def command(name, arguments, folder):
            process = subprocess.run([sys.executable, "-m", "jobsearch_cn", *arguments],
                                     cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            def parsed(text):
                try:
                    # Sanitize after JSON parsing so escaped Windows paths are also removed.
                    value = json.loads(text)
                    def clean(item):
                        if isinstance(item, str):
                            return sanitized(item)
                        if isinstance(item, list):
                            return [clean(child) for child in item]
                        if isinstance(item, dict):
                            return {key: clean(child) for key, child in item.items()}
                        return item
                    return clean(value)
                except ValueError:
                    return sanitized(text)
            record = {"argv": ["python", "-m", "jobsearch_cn", *map(sanitized, arguments)],
                      "exit_code": process.returncode,
                      "stdout": parsed(process.stdout), "stderr": parsed(process.stderr)}
            save(folder / (name + ".json"), record)
            return record

        for case in [*oracle["cases"], {"id": "invalid-material", **oracle["invalid_case"]}]:
            name = case["id"]
            data = data_root / name
            folder = output / name
            shutil.copytree((FROZEN / case["profile"]).parent, data / "profile")
            record = load(FROZEN / case["material"])
            path = data / "materials" / record["job_id"] / "resume-1.json"
            path.parent.mkdir(parents=True)
            shutil.copyfile(FROZEN / case["material"], path)
            initial = {p.relative_to(data).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in data.rglob("*") if p.is_file()}
            profile_result = command("profile-validate", ["profile", "validate", "--data-dir", str(data)], folder)
            assert profile_result["exit_code"] == 0, name
            validation = command("material-validate", ["material", "validate", str(path),
                                 "--data-dir", str(data)], folder)
            build_args = ["resume", "build", str(path), "--data-dir", str(data), "--typst", typst]
            built = command("resume-build-original", build_args, folder)
            result = {"id": name, "validation": validation["stdout"],
                      "original_build_exit_code": built["exit_code"], "build_exit_code": built["exit_code"]}
            if name == "invalid-material":
                trace_out, trace_err = io.StringIO(), io.StringIO()
                with mock.patch.object(material, "render", wraps=material.render) as flat, \
                     mock.patch.object(resume_pdf, "render", wraps=resume_pdf.render) as pdf_render, \
                     mock.patch.object(resume_docx, "write", wraps=resume_docx.write) as word_write, \
                     redirect_stdout(trace_out), redirect_stderr(trace_err):
                    traced_exit = cli.main(build_args)
                result.update({
                    "validation_matches": validation["exit_code"] == 1 and validation["stdout"] == {
                        "valid": False, "errors": [case["validation"]["error"]], "warnings": []},
                    "build_error_matches": built["stderr"].get("errors") == [case["validation"]["error"]],
                    "generated_files": [p.relative_to(data).as_posix() for p in (data / "resumes").rglob("*") if p.is_file()],
                    "trace_exit_code": traced_exit,
                    "render_call_counts": {"flat": flat.call_count, "pdf": pdf_render.call_count, "docx": word_write.call_count},
                })
            else:
                assert validation["exit_code"] == 0, (name, validation)
                original_record = record
                record = {**record, "job_id": metadata["adapter"]["job_ids"][name]}
                path = data / "materials" / record["job_id"] / "resume-1.json"
                save(path, record)
                save(folder / "adapted-material.json", record)
                adapted_validation = command("material-validate-adapted", ["material", "validate", str(path),
                                             "--data-dir", str(data)], folder)
                assert adapted_validation["stdout"] == validation["stdout"] and adapted_validation["exit_code"] == 0
                build_args = ["resume", "build", str(path), "--data-dir", str(data), "--typst", typst]
                built = command("resume-build-adapted", build_args, folder)
                assert built["exit_code"] == 0, (name, built)
                profile = load(data / "profile/profile.json")
                content = material.render(record, profile, vocab.load(data))
                assert content == material.render(original_record, profile, vocab.load(data))
                result["adaptation"] = {"differences": delta(original_record, record),
                                        "flat_content_unchanged": True, "validation_unchanged": True}
                result["build_exit_code"] = built["exit_code"]
                save(folder / "flat.json", content)
                pdf_path = data / "resumes" / record["job_id"] / "resume-1.pdf"
                docx_path = pdf_path.with_suffix(".docx")
                reader = PdfReader(pdf_path)
                texts = {"pdf": "\n".join(page.extract_text() or "" for page in reader.pages),
                         "docx": docx_text(docx_path)}
                layers = {}
                for kind, text in texts.items():
                    (folder / (kind + "-text.txt")).write_text(text + "\n", encoding="utf-8", newline="\n")
                    expected_fields = case["text_layer"]["must_contain"]
                    layers[kind] = {
                        "frozen_field_count": len(expected_fields),
                        "literal_missing": [field for field in expected_fields if field not in text],
                        "whitespace_only_missing": [field for field in expected_fields if compact(field) not in compact(text)],
                        "actual_content_missing": [field for field in strings(content) if compact(field) not in compact(text)],
                    }
                result.update({"validation_matches": validation["stdout"] == case["validation"],
                               "warnings_preserved": built["stdout"]["warnings"] == case["validation"]["warnings"],
                               "problems": built["stdout"]["problems"], "pdf_pages": len(reader.pages),
                               "flat_exact_match": content == case["expected_resume"],
                               "content_comparison": section_comparison(case["expected_resume"], content),
                               "text_layers": layers,
                               "artifacts_sha256": {"pdf": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
                                                    "docx": hashlib.sha256(docx_path.read_bytes()).hexdigest()}})
            result["input_bytes_unchanged"] = all(hashlib.sha256((data / p).read_bytes()).hexdigest() == digest
                                                  for p, digest in initial.items())
            all_results.append(result)
    for name, digest in manifest.items():
        assert hashlib.sha256((FROZEN / name).read_bytes()).hexdigest() == digest, name
    save(output / "results.json", {"metadata": metadata, "cases": all_results})
    print(json.dumps({"cases": len(all_results), "exact_flat_matches": sum(item.get("flat_exact_match", False) for item in all_results),
                      "validation_matches": sum(item["validation_matches"] for item in all_results),
                      "frozen_files_verified": len(manifest)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
