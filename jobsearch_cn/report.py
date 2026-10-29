"""Readable match report and feedback form (M2-6a; docs/cn/match.md, 评分报告).

build() lays saved match records out as one self-contained HTML page: a
ranking table, then for each job its hard conditions, its dimensions, how the
total was worked out, the gaps, and what is still to be confirmed and how.
feedback_csv() is the form the user fills in: one row per job, three blank
columns. Only what the records, the stored jobs and the profile already hold is
shown, and never the profile's contact details. Every string from a JD is
escaped, and there is no script and no external resource. Nothing is written
here; the CLI writes the files.
"""

import csv
import html
import io
from fractions import Fraction

from jobsearch_cn import match, score

VERDICTS = {match.ELIGIBLE: "符合", match.NEEDS_CHECK: "待确认", match.INELIGIBLE: "不符合"}
RESULTS = {match.MATCH: "符合", match.CONFLICT: "冲突", match.UNKNOWN: "未知", match.NOT_APPLICABLE: "不适用"}
CHECKS = {"graduation": "届别", "education": "学历", "days_per_week": "每周到岗", "min_months": "实习时长",
          "location": "地点", "employment_type": "岗位类型", "exclusions": "排除项"}
DIMENSIONS = {"skills": "技能", "direction": "方向", "experience": "经历", "salary": "薪资"}
GRADES = {"strong": "很匹配", "good": "较匹配", "moderate": "一般", "weak": "较弱", "poor": "不匹配",
          score.INELIGIBLE: "不符合硬性条件"}
METHODS = {"rule": "规则", "agent": "Agent"}
FEEDBACK_HEADER = ("岗位id", "岗位", "公司", "等级", "总分", "一句话结论",
                   "你的等级", "认可（认可 / 部分认可 / 不认可）", "原因")

ASK_JD = "先看 JD 原文（规则可能没读出来），原文也没写就问 HR"
FILL_PROFILE = "补上档案（建档工作流），再重新评分"
ASK_AGENT = "让 Agent 按评分工作流补充，再生成报告"
RESCORE = "让 Agent 重新评分（match score），再生成报告"


def entry(record: dict, job, stale: bool) -> dict:
    """One job in the report: its saved match record, the stored job (None if gone) and whether it is stale."""
    return {"record": record, "job": job, "stale": stale}


def order(entries: list) -> list:
    """As match list orders them: by grade, strong first and ineligible last, then by score."""
    def key(item):
        total = item["record"].get("total") or {}
        return score.list_key(total.get("grade"), total.get("score"), item["record"]["job_id"])
    return sorted(entries, key=key)


def _label(table: dict, key) -> str:
    return "—" if key is None else table.get(key, str(key))


def grade_text(grade) -> str:
    return "无" if grade is None else f"{_label(GRADES, grade)}（{grade}）"


def _checks(record: dict) -> list:
    return (record.get("filter") or {}).get("checks") or []


def conclusion(record: dict, stale: bool = False) -> str:
    """One sentence: the filter verdict, the grade and total, the dimensions missing."""
    verdict = (record.get("filter") or {}).get("verdict")
    total = record.get("total") or {}

    def named(result):
        return "、".join(_label(CHECKS, c.get("check")) for c in _checks(record) if c.get("result") == result)

    total_score = "无" if total.get("score") is None else f"{total['score']} 分"
    if verdict == match.INELIGIBLE:
        text = f"不符合硬性条件（冲突：{named(match.CONFLICT)}），各维度加权 {total_score}，仅供参考"
    else:
        unknown = [c for c in _checks(record) if c.get("result") == match.UNKNOWN]
        head = f"待确认 {len(unknown)} 项硬性条件（{named(match.UNKNOWN)}）" if unknown else "符合硬性条件"
        text = f"{head}，{grade_text(total.get('grade'))}，总分 {total_score}"
    if total.get("missing"):
        text += f"；缺{'、'.join(_label(DIMENSIONS, key) for key in total['missing'])}维度"
    return ("已过期，先重新评分。" if stale else "") + text


def pending(record: dict, job, profile: dict) -> list:
    """What is still open, as (item, why, how to settle it): unknown hard conditions, then null dimensions."""
    items = []
    for check in _checks(record):
        if check.get("result") != match.UNKNOWN:
            continue
        reason = check.get("reason") or ""
        how = ([ASK_JD] if "JD 没写" in reason else []) + ([FILL_PROFILE] if "档案没写" in reason else [])
        items.append((_label(CHECKS, check.get("check")), reason, "；".join(how) or "对照理由核对 JD 原文和档案"))
    dimensions = record.get("dimensions") or {}
    for key in (record.get("total") or {}).get("missing") or []:
        reason = (dimensions.get(key) or {}).get("reason") or ""
        items.append((f"{_label(DIMENSIONS, key)}维度", reason, _settle(key, job, profile)))
    return items


def _settle(key: str, job, profile: dict) -> str:
    target = profile.get("target") or {}
    if key == "experience":
        return ASK_AGENT if profile.get("experience") else FILL_PROFILE
    if key == "direction":
        return ASK_AGENT if target.get("directions") else FILL_PROFILE
    if key == "skills":
        return ASK_JD
    if key == "salary" and job is not None:
        offered = job.get("salary") or {}
        if offered.get("max") is None and offered.get("min") is None:
            return "问 HR 薪资范围" if offered.get("negotiable") else ASK_JD
        if not target.get("salary_min"):
            return FILL_PROFILE
        return "档案的最低期望薪资改用 JD 的单位（例如实习按天），再重新评分"
    return "对照理由核对 JD 原文和档案"


def working(record: dict):
    """How the total comes about: rows of (dimension, score, weight, product or None), the sum and the divisor."""
    dimensions, rows = record.get("dimensions") or {}, []
    numerator = denominator = Fraction(0)
    for key, weight in (record.get("weights") or {}).items():
        value = (dimensions.get(key) or {}).get("score")
        if value is None:
            rows.append((key, None, weight, None))
            continue
        weight_value = Fraction(str(weight))
        numerator += weight_value * value
        denominator += weight_value
        rows.append((key, value, weight, weight_value * value))
    return rows, numerator, denominator


def feedback_csv(entries: list) -> str:
    """The feedback form as text, UTF-8 with a BOM and CRLF rows, so Excel and WPS open it without mojibake."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(FEEDBACK_HEADER)
    for item in entries:
        record, job = item["record"], item["job"] or {}
        total = record.get("total") or {}
        writer.writerow([_cell(value) for value in (
            record["job_id"], job.get("title"), job.get("company"), grade_text(total.get("grade")),
            total.get("score"), conclusion(record, item["stale"]), "", "", "")])
    return "﻿" + buffer.getvalue()


def _cell(value) -> str:
    """Every cell, so no text - least of all the JD's - is read as a formula when the sheet is opened."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


# ---------------------------------------------------------------- HTML

_STYLE = """
:root { --ink: #1f2328; --muted: #59636e; --line: #d1d9e0; --soft: #f6f8fa;
        --ok: #1a7f37; --warn: #9a6700; --bad: #cf222e; }
body { margin: 0 auto; max-width: 1100px; padding: 24px 16px 64px; color: var(--ink); background: #fff;
       font: 15px/1.6 "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif; }
h1 { font-size: 24px; margin: 0 0 4px; }
h2 { font-size: 20px; margin: 40px 0 4px; padding-top: 16px; border-top: 2px solid var(--line); }
h3 { font-size: 16px; margin: 20px 0 6px; }
p.meta, .muted { color: var(--muted); }
table { border-collapse: collapse; width: 100%; margin: 6px 0; }
th, td { border: 1px solid var(--line); padding: 6px 8px; text-align: left; vertical-align: top; }
th { background: var(--soft); white-space: nowrap; }
td.num { text-align: right; white-space: nowrap; }
.match, .eligible { color: var(--ok); } .unknown, .needs_check { color: var(--warn); }
.conflict, .ineligible { color: var(--bad); } .not_applicable { color: var(--muted); }
.stale { color: var(--bad); font-weight: bold; }
.notice { background: #fff8c5; border: 1px solid #d4a72c; padding: 8px 12px; margin: 12px 0; }
q { quotes: "「" "」"; } ul { margin: 4px 0; padding-left: 20px; }
@media print { h2 { break-before: page; } }
"""


def _legend() -> str:
    """The grade bands from score.GRADES, named as in GRADES: 很匹配（strong）≥ 75，较匹配（good）60–74，…"""
    bands, ceiling = [], None
    for name, floor in score.GRADES:
        if ceiling is None:
            bands.append(f"{grade_text(name)}≥ {floor}")
        elif floor == 0:
            bands.append(f"{grade_text(name)}< {ceiling + 1}")
        else:
            bands.append(f"{grade_text(name)}{floor}–{ceiling}")
        ceiling = floor - 1
    return "，".join(bands) + f"；有硬性条件冲突的记为{grade_text(score.INELIGIBLE)}"


def _e(value) -> str:
    return html.escape("" if value is None else str(value))


def _value(value) -> str:
    if value is None or value == []:
        return "没写"
    if value is True or value is False:
        return "是" if value else "否"
    if isinstance(value, list):
        return "、".join(_value(item) for item in value)
    if isinstance(value, dict):
        if "level" in value or "school" in value:  # an education entry
            return " ".join(str(value[key]) for key in ("level", "school", "major") if value.get(key))
        return "；".join(f"{key}：{_value(item)}" for key, item in value.items() if item not in (None, [], "")) or "没写"
    return str(value)


def _quotes(snippets) -> str:
    if not snippets:
        return ""
    snippets = [snippets] if isinstance(snippets, str) else snippets
    return "<br>".join(f"<q>{_e(text)}</q>" for text in snippets)


def _experience_names(profile: dict) -> dict:
    names = {}
    for item in profile.get("experience") or []:
        if isinstance(item, dict) and item.get("id"):
            parts = [item.get(field) for field in ("name", "org", "role") if item.get(field)]
            names[item["id"]] = f"{item['id']}（{' '.join(parts)}）" if parts else item["id"]
    return names


def build(entries: list, profile: dict, generated_at: str, vocabulary) -> str:
    """The report page for entries already in order(); the vocabulary names the direction groups."""
    names = _experience_names(profile)
    stale = [item for item in entries if item["stale"]]
    out = [
        "<!doctype html>", '<html lang="zh-CN">', "<head>", '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>岗位评分报告</title>", f"<style>{_STYLE}</style>", "</head>", "<body>",
        "<h1>岗位评分报告</h1>",
        f'<p class="meta">生成于 {_e(generated_at)} · 共 {len(entries)} 个岗位 · 只读取已保存的匹配记录</p>',
    ]
    if stale:
        out.append(f'<p class="notice">有 {len(stale)} 条记录已过期（岗位或档案在评分后改过，或评分规则更新了），'
                   f"下面的结论可能不准：{RESCORE}。</p>")
    out += [
        f"<p>等级按总分划分：{_e(_legend())}。"
        "看完后在同目录的 <code>feedback.csv</code> 里填写“你的等级”“认可”“原因”三列，"
        "保存时保持 CSV（UTF-8）格式，然后告诉 Agent。</p>",
        "<h2 id=\"ranking\">排序</h2>",
        "<table><tr><th>#</th><th>岗位</th><th>公司</th><th>硬性条件</th><th>等级</th><th>总分</th>"
        "<th>完整</th><th>过期</th></tr>",
    ]
    for rank, item in enumerate(entries, 1):
        record, job = item["record"], item["job"] or {}
        total, verdict = record.get("total") or {}, (record.get("filter") or {}).get("verdict")
        expired = '<td class="stale">过期</td>' if item["stale"] else "<td></td>"
        out.append(
            f"<tr><td class=\"num\">{rank}</td>"
            f"<td><a href=\"#{_e(record['job_id'])}\">{_e(job.get('title') or record['job_id'])}</a></td>"
            f"<td>{_e(job.get('company') or '')}</td>"
            f"<td class=\"{_e(verdict)}\">{_e(_label(VERDICTS, verdict))}</td>"
            f"<td>{_e(grade_text(total.get('grade')))}</td>"
            f"<td class=\"num\">{_e('—' if total.get('score') is None else total['score'])}</td>"
            f"<td>{'是' if total.get('complete') else '否'}</td>{expired}</tr>")
    out.append("</table>")
    for item in entries:
        out += _job_section(item, profile, names, vocabulary)
    out += ["</body>", "</html>", ""]
    return "\n".join(out)


def _job_section(item: dict, profile: dict, names: dict, vocabulary) -> list:
    record, job = item["record"], item["job"]
    shown = job or {}
    total = record.get("total") or {}
    out = [f"<section id=\"{_e(record['job_id'])}\">",
           f"<h2>{_e(shown.get('title') or record['job_id'])}</h2>",
           f"<p class=\"meta\">{_e(shown.get('company') or '')} · {_e(record['job_id'])} · "
           f"评分于 {_e(record.get('scored_at'))}</p>"]
    if job is None:
        out.append('<p class="notice">岗位库里已经没有这个岗位，只能显示匹配记录里保存的内容。</p>')
    if item["stale"]:
        out.append(f'<p class="notice stale">这条记录已过期：{RESCORE}。</p>')
    out.append(f"<p><strong>结论：</strong>{_e(conclusion(record))}</p>")

    out += ["<h3>硬性条件</h3>",
            "<table><tr><th>条件</th><th>结论</th><th>理由</th><th>JD 原文</th><th>档案</th></tr>"]
    for check in _checks(record):
        result = check.get("result")
        reason = _e(check.get("reason")) + (f"<br><span class=\"muted\">{_e(check['note'])}</span>"
                                            if check.get("note") else "")
        jd = "<br>".join(_quotes(field.get("evidence")) or f"{_e(path)}：{_e(_value(field.get('value')))}"
                         for path, field in (check.get("jd") or {}).items())
        mine = "<br>".join(f"{_e(path)}：{_e(_value(value))}" for path, value in (check.get("profile") or {}).items())
        out.append(f"<tr><td>{_e(_label(CHECKS, check.get('check')))}</td>"
                   f"<td class=\"{_e(result)}\">{_e(_label(RESULTS, result))}</td>"
                   f"<td>{reason}</td><td>{jd}</td><td>{mine}</td></tr>")
    out.append("</table>")

    weights = record.get("weights") or {}
    out.append("<h3>各维度</h3>")
    if job is None:
        out.append('<p class="notice">岗位已删除，规则给出的维度列不出 JD 原文。</p>')
    elif item["stale"]:
        out.append('<p class="notice stale">依据栏里技能、薪资、方向的 JD 原文取自现在的岗位库，'
                   "这条记录已过期，依据可能已变，请先重新评分。</p>")
    out.append("<table><tr><th>维度</th><th>分数</th><th>权重</th><th>给出方</th><th>理由</th><th>依据</th></tr>")
    for key, dimension in (record.get("dimensions") or {}).items():
        dimension = dimension or {}
        value = dimension.get("score")
        out.append(f"<tr><td>{_e(_label(DIMENSIONS, key))}</td>"
                   f"<td class=\"num\">{_e('—' if value is None else value)}</td>"
                   f"<td class=\"num\">{_e(_decimal(weights[key]) if key in weights else '—')}</td>"
                   f"<td>{_e(_label(METHODS, dimension.get('method')) if value is not None else '—')}</td>"
                   f"<td>{_e(dimension.get('reason'))}</td>"
                   f"<td>{_grounds(key, dimension, names, job, vocabulary)}</td></tr>")
    out.append("</table>")

    rows, numerator, denominator = working(record)
    out += ["<h3>总分怎么算</h3>",
            "<p class=\"muted\">有分数的维度按权重加权平均，四舍五入取整；没有分数的维度不计入，也不计入分母。</p>",
            "<table><tr><th>维度</th><th>分数</th><th>权重</th><th>分数 × 权重</th></tr>"]
    for key, value, weight, product in rows:
        out.append(f"<tr><td>{_e(_label(DIMENSIONS, key))}</td>"
                   f"<td class=\"num\">{_e('—' if value is None else value)}</td>"
                   f"<td class=\"num\">{_e(_decimal(weight))}</td>"
                   f"<td class=\"num\">{_e('不计入' if product is None else _decimal(product))}</td></tr>")
    out.append("</table>")
    if denominator:
        exact = _decimal(numerator / denominator)
        cut = "；“…”表示后面还有位数，只截断显示、不进位" if exact.endswith("…") else ""
        out.append(f"<p>合计 {_e(_decimal(numerator))} ÷ 权重之和 {_e(_decimal(denominator))} = {_e(exact)}。"
                   f"总分由这个精确值直接四舍五入为 <strong>{_e(total.get('score'))}</strong>，"
                   f"{_e(grade_text(total.get('grade')))}（中途不先取小数{cut}）。</p>")
    else:
        out.append(f"<p>合计 {_e(_decimal(numerator))} ÷ 已评分维度的权重之和 0：已评分维度的权重之和为 0，算不出总分。"
                   "请补上权重大于 0 的维度（例如让 Agent 补经历），或在档案里调整权重（target.weights）。</p>")

    out.append("<h3>缺口</h3>")
    gaps = record.get("gaps") or []
    if gaps:
        out.append("<ul>" + "".join(f"<li>{_gap(gap)}</li>" for gap in gaps) + "</ul>")
    else:
        out.append("<p>没有列出的缺口。</p>")

    out.append("<h3>待确认</h3>")
    open_items = pending(record, job, profile)
    if open_items:
        out.append("<table><tr><th>事项</th><th>现在的情况</th><th>怎么确认</th></tr>")
        out += [f"<tr><td>{_e(what)}</td><td>{_e(why)}</td><td>{_e(how)}</td></tr>" for what, why, how in open_items]
        out.append("</table>")
    else:
        out.append("<p>没有待确认的事项。</p>")
    out.append("</section>")
    return out


def _grounds(key: str, dimension: dict, names: dict, job, vocabulary) -> str:
    """What a dimension rests on: the JD text from the stored job for the rule dimensions, the agent's evidence."""
    parts = []

    def skill(name):
        quote = _jd_quote(job, "requirements.skills", name)
        return _e(name) + (" " + _quotes(quote) if quote else "")

    if dimension.get("matched"):
        parts.append("有：" + "；".join(f"{skill(hit['jd'])}（档案：{_e(hit['profile'])}，计 {_e(hit['credit'])}）"
                                       for hit in dimension["matched"]))
    if dimension.get("missing"):
        parts.append("缺：" + "；".join(skill(name) for name in dimension["missing"]))
    if key == "salary":
        quote = _jd_quote(job, "salary")
        if quote:
            parts.append("JD：" + _quotes(quote))
    if dimension.get("jd_groups"):
        counted = score.direction_skills(job, vocabulary) if job and job.get("requirements") else {}
        for group, count in dimension["jd_groups"].items():
            label = vocabulary.groups.get(group, {}).get("label", group)
            listed = "、".join(counted.get(group) or [])
            parts.append(_e(f"{label}（{group}）{count} 项" + (f"：{listed}" if listed else "")))
        if job and {group: len(found) for group, found in counted.items()} != dimension["jd_groups"]:
            parts.append("词表或岗位在评分后改过，上面列的技能可能和评分时不同，请先重新评分")
    evidence = dimension.get("evidence")
    if isinstance(evidence, dict):
        if evidence.get("jd"):
            parts.append("JD：" + _quotes(evidence["jd"]))
        if evidence.get("profile"):
            parts.append("经历：" + _e("、".join(names.get(ref, ref) for ref in evidence["profile"])))
    elif dimension.get("score") is None and dimension.get("hints"):
        parts.append("可参考：" + _e("；".join(
            f"{hint['jd']} → {'、'.join(names.get(ref, ref) for ref in hint['profile'])}" for hint in dimension["hints"])))
    return "<br>".join(parts) or "—"


def _jd_quote(job, path: str, term: str = None):
    """The stored job's evidence for a field (and a term in it), as score quotes it for gaps; None if there is none."""
    if not job or not isinstance(job.get("evidence"), dict):
        return None
    return score._quote(job, path, term)


def _decimal(value, places: int = 6) -> str:
    """A number written out exactly, or cut (never rounded) after `places` decimals and marked …, so the digits
    shown never cross the .5 that rounding the total depends on: 71.498575… stays below 71.5."""
    value = value if isinstance(value, Fraction) else Fraction(str(value))
    sign, value = ("-", -value) if value < 0 else ("", value)
    cut = value.numerator * 10 ** places // value.denominator
    whole, decimals = divmod(cut, 10 ** places)
    digits = f"{decimals:0{places}d}".rstrip("0")
    exact = cut * value.denominator == value.numerator * 10 ** places
    return f"{sign}{whole}" + (f".{digits}" if digits else "") + ("" if exact else "…")


def _gap(gap: dict) -> str:
    kind = gap.get("kind")
    if kind == "skill":
        text = f"缺技能：{_e(gap.get('item'))}"
    elif kind == "salary":
        text = f"薪资：{_e(gap.get('item'))}"
    elif kind == "filter":
        text = (f"{_e(_label(CHECKS, gap.get('item')))}（{_e(_label(RESULTS, gap.get('result')))}）："
                f"{_e(gap.get('reason'))}")
    else:
        text = _e(gap.get("item"))
    quote = _quotes(gap.get("jd"))
    return text + (f"<br>JD：{quote}" if quote else "")
