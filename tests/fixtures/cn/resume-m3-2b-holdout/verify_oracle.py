"""Validate V22's manually written profiles, materials and expected flat resumes."""
from collections import Counter
import hashlib
import json
from pathlib import Path

FIX = Path(__file__).resolve().parent
LEVELS = [("expert", "精通"), ("proficient", "熟练"), ("working", "熟悉"),
          (None, "项目中使用"), ("familiar", "了解")]
TYPE_SECTIONS = [("internship", "实习经历"), ("project", "项目经历"), ("research", "科研经历"),
                 ("competition", "竞赛经历"), ("campus", "校园经历"), ("work", "工作经历")]
EDUCATION_LABELS = {"associate": "大专", "bachelor": "本科", "master": "硕士", "phd": "博士"}
EMPLOYMENT_LABELS = {"internship": "实习", "campus": "校招", "experienced": "社招"}


def load(path):
    return json.loads((FIX / path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def profile_hash(profile):
    data = {key: value for key, value in profile.items() if key != "contact"}
    data["target"] = {key: value for key, value in data["target"].items() if key != "weights"}
    text = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dotted(value):
    return value.replace("-", ".")


def period(entry):
    return f"{dotted(entry['start'])} - {dotted(entry['end']) if entry['end'] else '至今'}"


def unique_strings(value):
    found = []

    def visit(item):
        if isinstance(item, str) and item and item not in found:
            found.append(item)
        elif isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, dict):
            for child in item.values():
                visit(child)

    visit(value)
    return found


def expected_flat(profile, material):
    contact = " | ".join(profile["contact"][key] for key in ("phone", "email", "github", "website")
                         if profile["contact"][key] is not None)
    roles = "、".join(profile["target"]["roles"])
    employments = "、".join(EMPLOYMENT_LABELS[item] for item in profile["target"]["employment_types"])
    intent = f"求职意向：{roles}（{employments}） · {dotted(profile['availability']['start_date'])} 起可到岗"
    sections = []
    education = {item["id"]: item for item in profile["education"]}
    if material["education"]:
        entries = []
        for selected in material["education"]:
            item = education[selected["ref"]]
            facts = [part for part in ((f"GPA {item['gpa']}" if item["gpa"] else None), item["rank"]) if part]
            bullets = ["，".join(facts)] if facts else []
            if selected["courses"]:
                bullets.append("主修课程：" + "、".join(selected["courses"]))
            entries.append({"left": item["school"], "middle": f"{item['major']} · {EDUCATION_LABELS[item['level']]}",
                            "right": period(item), "bullets": bullets})
        sections.append({"title": "教育经历", "entries": entries})
    experiences = {item["id"]: item for item in profile["experience"]}
    for kind, title in TYPE_SECTIONS:
        selected = [item for item in material["experience"] if experiences[item["ref"]]["type"] == kind]
        if not selected:
            continue
        entries = []
        for choice in selected:
            item = experiences[choice["ref"]]
            left = item["name"] if kind in ("project", "research", "competition") else item["org"]
            entries.append({"left": left, "middle": item["role"] or "", "right": period(item),
                            "bullets": [bullet["text"] for bullet in choice["bullets"]]})
        sections.append({"title": title, "entries": entries})
    skills = {item["name"]: item for item in profile["skills"]}
    lines = []
    for level, label in LEVELS:
        names = [name for name in material["skills"] if skills[name]["level"] == level]
        if names:
            lines.append({"label": label, "rest": "、".join(names)})
    if lines:
        sections.append({"title": "专业技能", "lines": lines})
    by_id = {item["id"]: item for key in ("awards", "certificates", "languages")
             for item in profile[key]}
    honor_lines = []
    for selected in material["awards"]:
        item = by_id[selected["ref"]]
        honor_lines.append({"label": "", "rest": item["name"] + (f"（{dotted(item['date'])}）" if item["date"] else "")})
    certificate_text = []
    for selected in material["certificates"]:
        item = by_id[selected["ref"]]
        text = item["name"] + (f" {item['detail']}" if item["detail"] else "")
        certificate_text.append(text)
        honor_lines.append({"label": "", "rest": text})
    for selected in material["languages"]:
        item = by_id[selected["ref"]]
        if not any(item["level"] in text for text in certificate_text):
            honor_lines.append({"label": "", "rest": f"{item['name']} {item['level']}"})
    if honor_lines:
        sections.append({"title": "荣誉与证书", "lines": honor_lines})
    return {"name": profile["contact"]["name"], "contact": contact, "intent": intent, "sections": sections}


def frozen_names():
    names = [path.relative_to(FIX).as_posix() for path in FIX.rglob("*") if path.is_file()
             and path.name != "oracle-manifest.json"]
    return sorted(names)


def verify():
    oracle = load("expectations.json")
    assert len(oracle["cases"]) == 3
    assert {case["id"] for case in oracle["cases"]} == {"case-01-tech", "case-02-ops", "case-03-data"}
    all_types, levels = set(), set()
    selected_empty_courses = no_gpa = no_end = null_level = False
    duplicate_language = separate_language = False
    for case in oracle["cases"]:
        profile, material = load(case["profile"]), load(case["material"])
        assert material["schema_version"] == 1 and material["kind"] == "resume"
        assert set(material) == {"schema_version", "kind", "job_id", "profile_hash", "created", "summary",
                                 "education", "experience", "skills", "awards", "certificates", "languages"}
        calculated = expected_flat(profile, material)
        assert calculated == case["expected_resume"], case["id"]
        assert "summary" not in calculated
        strings = unique_strings(calculated)
        assert strings == case["text_layer"]["must_contain"], case["id"]
        assert case["text_layer"]["applies_to"] == ["pdf", "docx"]
        current_hash = profile_hash(profile)
        if case["id"] == "case-03-data":
            assert material["profile_hash"] != current_hash
            assert case["validation"]["warnings"] == [
                "profile_hash: the profile has changed since this material was written; check it still holds"
            ]
        else:
            assert material["profile_hash"] == current_hash
            assert case["validation"] == {"valid": True, "errors": [], "warnings": []}
        all_types.update(item["type"] for item in profile["experience"])
        levels.update(item["level"] for item in profile["skills"])
        selected_empty_courses |= any(not item["courses"] for item in material["education"])
        no_gpa |= any(item["gpa"] is None for item in profile["education"])
        no_end |= any(item["end"] is None for item in [*profile["education"], *profile["experience"]])
        null_level |= any(item["level"] is None for item in profile["skills"])
        certs = [by["name"] + (f" {by['detail']}" if by["detail"] else "")
                 for ref in material["certificates"] for by in profile["certificates"] if by["id"] == ref["ref"]]
        for ref in material["languages"]:
            language = next(item for item in profile["languages"] if item["id"] == ref["ref"])
            duplicate_language |= any(language["level"] in text for text in certs)
            separate_language |= not any(language["level"] in text for text in certs)
    assert all_types == {kind for kind, _ in TYPE_SECTIONS}
    assert levels == {level for level, _ in LEVELS}
    assert all((selected_empty_courses, no_gpa, no_end, null_level, duplicate_language, separate_language))
    invalid = oracle["invalid_case"]
    bad, profile = load(invalid["material"]), load(invalid["profile"])
    assert bad["experience"][0]["bullets"][0]["text"].count("99") == 1
    source = next(item for item in profile["experience"] if item["id"] == "intern-a1")["bullets"][0]
    assert "6 周" in source and "99" not in source
    assert invalid["build"] == "reject_before_flat_json_pdf_or_docx"
    manifest = FIX / "oracle-manifest.json"
    if manifest.exists():
        hashes = load("oracle-manifest.json")["frozen_files_sha256"]
        assert set(hashes) == set(frozen_names())
        for name, expected in hashes.items():
            assert digest(FIX / name) == expected, name
    for name in frozen_names():
        raw = (FIX / name).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), name
        assert b"\r" not in raw, name
        raw.decode("utf-8")
    return {"profiles": 3, "valid_materials": 3, "invalid_materials": 1,
            "experience_types": len(all_types), "skill_levels": len(levels),
            "frozen_files": len(frozen_names())}


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False))
