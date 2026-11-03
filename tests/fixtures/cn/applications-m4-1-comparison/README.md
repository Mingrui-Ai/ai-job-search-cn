# V25 · M4-1a 对照报告（#122）

结论：**M4-1a 的 80 个场景里，65 个通过、15 个不通过。** 455 项严格检查有 440 项通过；15 个不通过的场景各只差一项。按原因分：

- (a) 实现的问题，5 个场景、3 条；
- (b) 按实现核对的点，1 个场景：`--material` 指向不存在的文件时退出 2，规划者倾向已批准；
- (c) 期望本身可能不对，9 个场景：状态表里"变回 drafted"那一列。

M4-1b 的 30 个场景**等 M4-1b**，本轮没有运行。冻结期望没有改。

## 基线与证据

- 冻结提交：`b785a776a77a48f685b9371f4d3371b207047f0e`，原始文件在 [applications-m4-1-holdout](../applications-m4-1-holdout/README.md)。运行器先跑 `verify_oracle.py`，14 个冻结文件的摘要都对得上（`results.json` 的 `frozen_oracle_ok=true`）。
- 被测版本：#122 head `5c574417ad2b475073472cd3c16b2512bf6cfe4d`，在 `tmp/` 下用临时工作树检出（`--detach`），用完已删除。
- 环境：Windows、conda `ai-job-search-cn`、Python 3.12、Typst 0.15.1。只用 V25 的虚构输入，没有读用户数据。
- [完整结果](actual/pr122-5c57441/results.json)：每个场景的每项检查（`checks`）和按实现核对时观察到的行为（`impl_observed`）。[logs/](actual/pr122-5c57441/logs/) 里是每条命令的参数、退出码、stdout 和 stderr。本机路径都替换成 `<work>`、`<repo>`、`<typst>`、`<home>`。

## 运行器

[run_comparison.py](run_comparison.py) 只把产品当子进程调用（`python -m jobsearch_cn ...`，cwd 是被测树）。每个场景用一个新数据目录：先在 `base` 模板里存 {JOB_A}、{JOB_B}，复制档案和材料，评分；`built` 模板再加一次 `resume build`。然后照 `scenarios.json` 的步骤运行，写操作都是先 `--preview`、再带 `--request-id` 提交。"不写"的检查比较的是整个数据目录在操作前后的文件和摘要。冻结目录只读。

运行器本身的三处说明（都不改冻结期望）：

1. A50 的"有警告"一开始只检查"有任何警告"，结果被一条无关的警告（准备时没放审核结果，所以有 "no review" 警告）凑巧满足了。正式运行前已改成"要有关于说明文件的警告"。
2. A67 比较打印出来的导出和 `--out` 写出的文件时，先把换行统一成 LF：Windows 的 stdout 是 CRLF，文件是 LF，内容本身一样。
3. 正式运行后发现 A67 一条错误消息里的路径（JSON 里套着 repr，反斜杠被转义了两次）没被替换。按同样的规则补替换了这一个日志文件，并把这条规则补进运行器。

## 总表

| 场景 | 结果 | 说明 |
| --- | --- | --- |
| A01–A28、A38–A42、A46、A47、A49、A52–A80（不含 A50、A51） | 通过（65） | 其中 A08、A14、A54、A55、A56 等只有按实现核对的项，底线检查都满足，观察结果见 (b) |
| A29–A37 | 不通过（9） | 都只差"X→drafted"一格：期望退出 1、`transition`，实际 argparse 退出 2、没有写入。归 (c)-1 |
| A43、A44、A45 | 不通过（3） | 发出文件的 `file_id` 是 `sent-1`、`sent-2`，设计 §3 写的是 `pdf`、`docx`。归 (a)-3 |
| A48 | 不通过 | 改过名的发出文件没有和说明文件核对，`materials_check=unchecked`，期望 `mismatch`。归 (a)-2 |
| A50 | 不通过 | 没有说明文件时不给警告。归 (a)-1 |
| A51 | 不通过 | `--material` 指向不存在的文件时退出 2。冻结期望是"只警告"，规划者倾向 §5 的退出 2。归 (b)-6 |

状态表 81 格里，72 格与冻结值相同，包括 `drafted→applied` 被 `status` 拒绝（`transition`，退出 1）、`no_response` 往回走必须带 reason、终结状态全部拒绝。不同的 9 格都是目标为 `drafted` 的那一列。

## (a) 看起来是实现的问题

**(a)-1 · P2 · 没有说明文件时不给警告（A50）。** 规划者 11-03 01:00 裁定：投出时找不到材料或没有说明文件，只给警告。实现把 `materials_check` 记成 `unchecked`，导出里看得到，但不给警告，用户和 Agent 都收不到提示。原因：`jobsearch_cn/applications.py` 的 `_build_check` 找不到 `build_note_path(sent_file)` 时直接 `return "unchecked"`，没有往 `warnings` 里加一条（说明文件读不出来时有警告）。复现：

```powershell
# 数据目录里已存岗位 {JOB_A}、档案、materials/{JOB_A}/resume-1.json，并 resume build 过
Remove-Item <数据目录>\resumes\{JOB_A}\resume-1.build.json
python -m jobsearch_cn application record {JOB_A} --channel portal --submitted --on 2026-10-28 `
  --material <数据目录>\materials\{JOB_A}\resume-1.json --sent <数据目录>\resumes\{JOB_A}\resume-1.pdf `
  --preview --data-dir <数据目录>
# warnings 里只有 "no review beside it passed..."，没有提到说明文件；预览里 submitted 事件的 payload.materials_check = unchecked，提交后 submission.materials_check 也是 unchecked
```

A49（发出文件在 `resumes/` 外）也是 `unchecked`，那里有"不在 resumes/ 下"的警告，没有单独的说明文件警告，冻结期望只要求前者。

**(a)-2 · P3 · 改过名的发出文件不和说明文件核对（A48）。** cn-a7 第 4 条：发出文件的摘要不在说明文件里时，只警告、照样记录，核对结果记进事件。A48 把 `resume-1.pdf` 改了几个字节，另存为同一目录下的 `resume-1.edited.pdf` 再发出，旁边就是 `resume-1.build.json`，`--material` 也是 `resume-1.json`。实现按发出文件自己的名字找说明文件（`build_note_path`：名字不是 `resume-<n>.<扩展名>` 时找 `resume-1.edited.build.json`），找不到，结果是 `unchecked`，只有一条文件名警告。所以手工改过、另存成新名字的文件（正是这条裁定要抓的情形）记不成 `mismatch`。复现：在 A50 的准备上不删说明文件，复制 `resume-1.pdf` 为 `resume-1.edited.pdf` 并在末尾追加字节，`--sent` 指向它。建议：名字对不上时退回到 `--material` 编号对应的说明文件。

**(a)-3 · P3 · 发出文件的 `file_id` 与设计 §3 不同（A43–A45）。** 设计 §3 的 `material_files.file_id` 是"版本内编号：material、pdf、docx"；实现是 `material`、`sent-1`、`sent-2`……（`applications.md` §2、§6 已这样写）。这样做的好处是同一种格式发出两个文件时不冲突，`sent_file_refs` 也能对应上。它不影响归档和摘要：A43–A45 的其余检查全部通过。请规划者批准这个改名（批准后转为已批准的差别），或者要求改回设计的命名。

## (b) 按实现核对的点，实现是怎么做的

上次列的 12 处，逐条：

| # | 问题 | 实现（场景） |
| --- | --- | --- |
| 1 | 拒绝的退出码 | 被 argparse 拦的都是退出 2：未知选项 `--note`（A17）、`--on`/`--at` 同给（A13）、缺 `--expected-revision`（A28）、枚举外的 `--channel wechat`（A21）、`status accepted`/`drafted`（A41）、`--actor robot`（A77）、不带 `--preview` 也不带 `--request-id`（A08）。业务检查拦的都是退出 1：时间格式错、将来、太长、`--historical` 不带 `--submitted`、`--material` 不随投出、`no_response` 不带 reason（包括空字符串）都报 `invalid`；`submit` 已投出的报 `transition`（A25）；找不到投递或岗位报 `not_found`（设计的错误码表里没有，`applications.md` §8 新加） |
| 2 | 预览 | `--preview` 和 `--request-id` 必须二选一，都不给时 argparse 退出 2、不写（A08）。自己编一个格式合法的 `req_…` 也能直接提交、退出 0（A08）：命令没法知道 id 是不是预览给的，"先预览"靠 Agent 遵守。预览阶段就做参数和状态检查（A13、A21 在预览时就被拒）。重试时输出 `repeated=true`（A06） |
| 3 | 只读命令 | 库不存在时：`list` 退出 0，返回 `{"applications": [], "note": "no application records yet"}`；`validate` 退出 0，`valid=true`，带一条警告；`export` 退出 0，返回空列表；`show` 退出 1、`not_found`；都不建库（A03）。库版本更高时写和读都退出 2，"nothing was read or written"（A02）。不存在的投递 id：`status`/`show`/`export` 都是退出 1、`not_found`（A42、A68） |
| 4 | `record` 不投出却给日期 | 拒绝，退出 1、`invalid`，提示加 `--submitted` 或以后用 `submit` 记（A14）。`created` 事件的 `occurred_at`/`occurred_on` 都是 null（A05） |
| 5 | 岗位不在库里 | 当前流程退出 1、`not_found`（A09）。补录时岗位在库里也不做快照，不给警告（A19），与 `applications.md` §7 一致 |
| 6 | 材料缺失 | 没有说明文件：材料和发出文件照样归档，`materials_recorded=true`，`materials_check=unchecked`（A50；但没有警告，见 (a)-1）。`--material` 指向不存在的文件：退出 2，`cannot read …: not a file`，什么也不写（A51）。规划者说明 01:00 那条裁定说的是没给材料，不是路径写错，倾向 §5 的退出 2：**规划者倾向已批准**。冻结期望按 01:00 裁定写成"只警告"，所以 A51 在严格比较里记为不通过，冻结文件不改 |
| 7 | 拦还是警告 | 材料通不过 `material validate`：退出 1、`invalid`，附 `errors`，不写（A54）。材料 `job_id` 和投递岗位不同：退出 1、`invalid`（A55）。只给 `--sent`：接受，建一个 `material_path`/`material_hash`/`profile_hash` 都为 null、只有 `sent-1` 的版本，警告 "no material file recorded"（A56） |
| 8 | 字段名 | 核对结果是 `submitted` 事件 `payload.materials_check` 和导出 `submission.materials_check`，取值 `match`/`mismatch`/`unchecked`/null（A43、A47）。`review_path` 是相对数据目录的路径 `materials/<岗位id>/review-1-r1.json`（A43）。说明文件的键：`schema_version`、`kind`（`resume-build`）、`material`、`material_hash`、`profile_hash`、`built_at`、`files[{name, sha256}]`（A57）。岗位快照是逐字节复制（A43） |
| 9 | validate | 孤立目录放在单独的 `orphans` 字段里，不算错误：`valid=true`，退出 0（A62）。写入时也给隐私警告：A64 的 reason 写入时手机号、邮箱、链接各一条，`validate` 再报一次 |
| 10 | list、show、export | `list` 投出的按投出时间倒序在前，没投出的在后（A70）；每行有 `application_id`、`channel`、`company`、`job_id`、`record_origin`、`revision`、`status`、`submission`、`title`、`updated_at`。`show` 包一层 `{"application": …}`，里面那层与导出相同（A69）。`export --out` 遇到已存在的文件直接覆盖，退出 0（A67）；带路径的四种都是退出 1、`invalid` |
| 11 | 链接、actor | `applications/` 是 junction 时退出 2，链接指向的目录里什么也没写（A76）。未知 actor 被 argparse 拦，退出 2（A77） |
| 12 | M4-1b 那些点 | **等 M4-1b**（B01–B30 本轮没跑） |

另外观察到：两个进程拿同一个 revision 并发写时，输的一方报 `stale_revision`（A74）；另一连接持写锁时等了 5.77 秒后报 `busy`（A75）。

## (c) 期望本身可能不对

**(c)-1 · 状态表里的"→ drafted"一列（A29–A37）。** 冻结期望对每个起点都要求 `status <id> drafted` 退出 1、`transition`。设计 §4 的表里，`drafted` 从来不是可以变成的状态。实现干脆不把它列进 `status` 的可选值，argparse 先拒绝，退出 2，什么也不写。结果都是"拒绝、不写"；冻结期望把错误码和退出码定得比设计更死，`transition` 是我从"其余都拒绝（transition）"推出来的。建议规划者认可这一列的实际行为，不要求实现改。这 9 个场景在严格比较里仍记为不通过，冻结文件不改。

## 复跑

在 holdout clone 的根目录运行（`--output` 必须是一个不在冻结目录里的新目录）：

```powershell
git -C <holdout clone> worktree add --detach <tmp>\v25-pr122 5c574417ad2b475073472cd3c16b2512bf6cfe4d
conda run --no-capture-output -n ai-job-search-cn python tests/fixtures/cn/applications-m4-1-comparison/run_comparison.py `
  --repo <tmp>\v25-pr122 --typst <typst路径> --output <tmp>\v25-run
```

整套约 4 分钟，`--only A43,A48` 可以只跑几个场景。运行器正常跑完就退出 0，**退出 0 不等于全部通过**，判断看 `results.json` 的 `counts`、`failed` 和每个场景的 `checks`。它不接入常规 unittest 自动发现。
