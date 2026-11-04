# V25 · M4-1 投递记录对照报告（#122 / #126）

## M4-1b 对照（9db3287，2026-11-04）

**B01–B30 全部运行：按裁定通过 30/30，严格比较通过 28/30。新 P1、P2、P3 均为 0。** 严格差别只有 B11 的历史日期准备和 B21 的警告期望，解释如下。#126 上 Codex B 已报的四项 P2 不在本次冻结步骤的失败边界内，本结果不表示它们已经修复，不替代代码审核；#124 不合并。

### 基线与证据

- 被测实现：#126 的 `9db32876cde23bf2db1097b9a3599362cd0cbbeb`，独立干净的 detached 工作树；运行器核对完整 SHA，不修改产品代码。
- 裁定：该 head 的 [M4-1b 计划](https://github.com/Mingrui-Ai/ai-job-search-cn/blob/9db32876cde23bf2db1097b9a3599362cd0cbbeb/docs/cn/worklog/2026-11-04-m4-1b-applications.md) §2、§5，以及 [#126 规划者裁定](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/126#issuecomment-6623727633)。
- 冻结基线仍为 `b785a776a77a48f685b9371f4d3371b207047f0e`。既有 `verify_oracle.py` 在运行前后通过，14 个冻结文件的摘要一致。`scenarios.json`、输入、清单、校验脚本均未改；前两轮 M4-1a 输出和原运行器也未改。
- 新运行器：[run_m4_1b.py](run_m4_1b.py)。复用旧运行器的虚构数据准备、哈希和 CLI 结果包装；B01–B30 的执行和判断单独保存，不改旧 A 场景的实现。
- [汇总](actual/pr126-9db3287/results.json)、[30 个场景的命令／输出／事件和逐项判断](actual/pr126-9db3287/cases/)、[B11 历史日期重放](actual/pr126-9db3287/cases/B11-historical-replay.json)。数据目录、实现目录、解释器和 Typst 的本机路径已替换成标记。
- 环境：Windows、conda `ai-job-search-cn`、Typst 0.15.1。只用冻结虚构数据；每个场景独立数据目录，CLI 显式传 `--data-dir`，不读取真实数据。生成的临时数据库、PDF 和 Word 只留在本机日志目录，不随证据入库。

### 严格结果和按裁定结果

| 场景 | 严格通过 | 按裁定通过 | 说明 |
| --- | --- | --- | --- |
| B01–B10 | 10/10 | 10/10 | 回复、备注、跟进和终结状态；`impl` 项另按已批准计划核对 |
| B11 | 0/1 | 1/1 | 实际日期下不允许新设过去的跟进日期；历史状态另行重放通过 |
| B12–B20 | 9/9 | 9/9 | 默认日期、连续作废、材料保留、revision 和拒绝不写 |
| B21 | 0/1 | 1/1 | 冻结步骤的“无警告”与该场景末尾和已批准规则冲突；实际隐私警告正确 |
| B22–B30 | 8/8 | 8/8 | 重试、备份恢复、入口授权、文档命令和两条故事 |
| 合计 | 28/30 | 30/30 | 460 项严格检查中 456 项通过，4 项差别分布在 B11、B21 |

**B11：原日期不改，区分历史状态和今天的新请求。** 冻结准备要求用产品命令给 I 设置 `2026-11-01`，实际运行日是 `2026-11-04`。按照已经批准的计划 §2.2，这个新请求退出 1、`invalid`，提示不能设过去日期。因此原始输出中 I 没进入 due，而进入 unset；准备、due、unset 三项严格不符。保留这份输出，另建一份虚构数据，仅在 CLI 子进程中将 `applications._today` 设为 `2026-11-01`，依原日期通过产品命令建立全部六条记录，再执行原 `list --due --as-of 2026-11-10`：due 为 I、P，逾期 9、5 天；unset 仅 R；Q、D、X 排除；整库 validate 通过。未改系统时钟、冻结日期或数据库行。汇总只允许这三项由过去日期导致的差别，历史重放及其他检查仍须全部通过。

**B21：冻结期望内部不一致，依已批准的隐私警告规则判定。** 最后一步 `validate` 写了 `warning=false`，同一场景的 `checks` 却明确要求 warnings 点到手机号、邮箱和 URL。计划 §2.7(5) 已批准这些警告。实际退出 0、`valid=true`，三个类别都准确提示；严格结果保留“无警告”检查失败，按裁定通过。不修改这条冻结期望。

### 按实现核对的项目

| 项目 | 实际行为及核对结果 |
| --- | --- |
| B04 回复边界 | drafted 的回复退出 1、`transition`，状态不变；补充核对已投出的 hired、rejected、withdrawn、offer_declined 均可记回复，状态不变 |
| B05、B06 备注 | 已结束记录可加备注；note 无发生时间，`--on`、`--at` 均被 argparse 拒绝且不写 |
| B07 参数互斥 | `--due` 与 `--cancel` 同给或都不给均退出 2；设置、取消的事件类型和 payload 正确 |
| B09 跟进边界 | 过去日期为 `invalid`；补充核对 drafted、no_response 和四个终结状态的设置／取消均为 `transition`、不写 |
| B12 默认日期 | 空库退出 0，as_of 为北京时间当天，due、unset 为空；额外 note 说明尚无记录，不建库 |
| B13、B15–B20 作废 | revision 照常增加；连续作废跳过作废事件，第二次作废 submitted；created 不能作废；归档和材料版本保留，validate 无孤立文件错误；record --submitted 的普通投出可作废 |
| B22 请求冲突 | 同 id 同内容返回原事件、不增事件；复用 id 改内容时提交为 `request_conflict`。该冻结模式先做预览，但预览因旧 revision 返回 stale_revision 后，仍按模式定义执行携带原 id 的故意冲突提交；两次拒绝都不写 |
| B23–B25 备份 | backup 一步执行；manifest 和数据库、附件摘要相符；源库和原归档不变；复制到新目录后 export 与原库相同（仅忽略 exported_at），validate 通过；无库时为 not_found，不建空备份 |
| B26–B28 入口和授权 | 三个入口指向同一工作流；预览、用户同意、request_id、actor 和不走上游流程写在共用说明；11 项入口测试、lint_skills、security_guards 通过；文档中每个 application 子命令 --help 退出 0，简历交付段有工作流链接 |

所有正常写操作均先预览再提交，预览逐次核对整个数据目录未变。B22 的同请求重试及故意复用旧请求按冻结模式执行；backup 按已批准例外直接运行。拒绝操作及冻结只读步骤也检查整个数据目录不变。

### 与 Codex B 四项 P2 的对应

依 [Codex B 审核（9db3287）](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/126#issuecomment-6623854046) 保留原编号，不重复列为新问题：

| 已有编号 | 对应领域 | 本轮证据的范围 |
| --- | --- | --- |
| P2-1 | B23、B25 备份与恢复 | 正常归档路径通过；冻结输入没有 Windows 异常路径，不覆盖该缺陷 |
| P2-2 | B04 回复状态 | 测 drafted 和已投出的终结记录；没有“从未投出便撤回”的组合，不覆盖该缺陷 |
| P2-3 | B22 重试 | 冻结步骤是 note 的同日重试；没有 followup 跨日重试，不覆盖该缺陷 |
| P2-4 | B23、B25 备份 | 正常无锁备份通过；没有打开源连接后再持独占锁，不覆盖该缺陷 |

**新问题：P1=0、P2=0、P3=0。** B11、B21 按既有批准规则解释，无需新增范围裁定；本轮通过数不能用于关闭上述四项 P2。

### 复跑和检查

```powershell
conda run --no-capture-output -n ai-job-search-cn python tests/fixtures/cn/applications-m4-1-holdout/verify_oracle.py
conda run --no-capture-output -n ai-job-search-cn python tests/fixtures/cn/applications-m4-1-comparison/run_m4_1b.py --repo <固定head的工作树> --typst <typst.exe> --output <全新输出目录>
```

运行器退出 0 仅表示完成取证，判定以 results.json 为准；B11 的实际日期与历史时钟写在证据中。只将 results.json 和 cases/ 作为公开证据，保留 work/ 和 templates/ 在本机。

- 报告分支合入最新 master `5585f24cc80c7d3428f8ee95ce21428aa1443278`，合并提交 `45f150c`；被测工作树仍固定为上面的 #126 SHA，没有把 master 合进去改变被测对象。
- 报告分支全量测试 1713 项，跳过 26 项，其余通过，零失败／错误，434.720 秒。被测 head 的 M4-1b 事件测试 19 项、入口测试 11 项均通过；不把报告分支全量测试数当作被测 head 的测试数。
- 两个工作树的 lint_skills、security_guards 均通过；冻结与交付文件完整性检查见[本轮工作记录](../../../../docs/cn/worklog/2026-11-04-v25-m4-1b-comparison.md)。
- [证据复核摘要](actual/pr126-9db3287/verification.json)：33 份 JSON 可解析，37 个交付文本通过编码与本机信息扫描；记录的步骤和期望与冻结文件一致，124 项预览只读检查、21 项拒绝或只读步骤的数据不变检查通过；`git diff --check` 通过。

## M4-1a 历史对照记录

最新复跑见[复跑（52d84d0）](#复跑52d84d0)：按规划者裁定 **80 个通过、0 个不通过**；冻结期望的严格比较为 **67 个通过、13 个不通过**，剩余 13 个都是已批准的差别。

第一次对照（5c57441）的结论：**M4-1a 的 80 个场景里，65 个通过、15 个不通过。** 455 项严格检查有 440 项通过；15 个不通过的场景各只差一项。按原因分：

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

## 复跑（52d84d0）

2026-11-04，由 Codex A 复跑。被测提交为 #122 的 `52d84d0310c7f537ed3492c278cd177fa21a0163`；仍使用冻结提交 `b785a776a77a48f685b9371f4d3371b207047f0e` 的全部 80 个 M4-1a 场景。冻结文件和原运行器都没有修改，第一次的 `actual/pr122-5c57441/` 原样保留。

### 结果与证据

| 口径 | 通过 | 不通过 | 说明 |
| --- | --- | --- | --- |
| 冻结期望的严格比较 | 67 | 13 | 455 项检查中 442 项通过；每个不通过的场景只差一项 |
| 按规划者裁定验收 | 80 | 0 | 剩余 13 个场景的差别全部已批准，逐项见下文；不回填严格结果 |
| M4-1b | — | — | B01–B30 共 30 个场景仍为“等 M4-1b”，没有运行 |

- [完整严格结果](actual/pr122-52d84d0/results.json)与 [80 份命令日志](actual/pr122-52d84d0/logs/)独立存放。
- [裁定补充检查](actual/pr122-52d84d0/ruling-checks.json)：A43、A47、A48、A49、A50 共 5 个场景、20 项检查全部通过；这些检查不计入原来的 80 个场景或 455 项检查。
- 补充检查分别调用 `application export` 和 `application validate`，核对 `materials_check`、退出 0、`valid=true`、`errors=[]`、相应警告，并比较整个数据目录的文件与摘要，确认只读命令没有写入。A47/A48 的 `mismatch`、A50 的 `unchecked` 都有对应警告；A43/A49 的 `match` 没有这类警告。
- 环境仍为 Windows、conda `ai-job-search-cn`、Python 3.12.15、Typst 0.15.1；只用虚构输入。本机路径替换为占位符，未提交运行时数据目录。

### 和第一次相比变了什么

| 场景 | 第一次（5c57441） | 本次（52d84d0） |
| --- | --- | --- |
| A48 | 改名且改过字节的发出文件记成 `unchecked`，严格比较不通过 | 按材料对应的说明文件核对，事件和导出记成 `mismatch`，保留改过的归档字节并给警告，严格比较通过；`validate` 也警告 |
| A50 | 找不到说明文件时虽记 `unchecked`，却没有说明文件警告，严格比较不通过 | 明确提示没有说明文件，材料和发出文件照样归档，仍记 `unchecked`，严格比较通过；`validate` 也警告 |
| A49 | 发出文件在 `resumes/` 外，核对结果为 `unchecked`；场景通过 | 通过 `--material` 找到说明文件，字节一致所以为 `match`；目录/文件名警告仍有，场景仍通过 |
| A47 | 材料生成后被改，仍可记录为 `mismatch`；场景通过 | 原场景仍通过；新增补充核对确认 `validate` 将 `mismatch` 列为警告，保持 `valid=true` |
| 其余场景 | 既有结果 | 严格通过/不通过没有变化，未出现回归 |

严格结果从 65/15 变为 67/13，只增加 A48、A50 两个通过场景；检查数从 440/455 变为 442/455。按已批准的口径看，第一次还剩 A48/A50 两个实现问题，本次两个均已解决。A74 的并发落败方仍是 `stale_revision`；A75 约 5.76 秒返回 `busy`，保持通过。

### 已批准的差别，逐条核对

依据：[规划者 cn-e3 在 #122 的裁定](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/122#issuecomment-6608059349)，以及收件箱 11-04 00:20 关于 `validate` 也警告 `mismatch` 的补充。

| 场景 | 本次实际行为 | 验收归属 |
| --- | --- | --- |
| A43 | 发出的 PDF `file_id=sent-1`，归档字节和引用都正确 | 已批准的差别；通过 |
| A44 | 两份发出文件 `file_id=sent-1`、`sent-2`，两条引用正确 | 已批准的差别；通过 |
| A45 | `submit` 发出的 Word `file_id=sent-1`，字节摘要正确 | 已批准的差别；通过 |
| A29–A37 | 九个起点执行 `status <id> drafted` 均被 argparse 拒绝，退出 2；逐格都是 `wrote=False`，其余 72 格严格相符 | 已批准的差别；九个场景均通过 |
| A51 | `--material` 指向不存在的文件，退出 2，`wrote=False` | 已批准的差别；通过 |

原报告“按实现核对”的 12 处逐项更新如下；前 11 处本轮适用，按已批准的实现口径通过，第 12 处仍等待。

| # | 本次核对 | 裁定后的结论 |
| --- | --- | --- |
| 1 | argparse 拒绝退出 2，业务拒绝退出 1；`invalid`、`transition`、`not_found` 的既有区分不变 | 已批准；通过 |
| 2 | A08 缺少预览/请求参数时退出 2、不写；合法自拟请求 id 可提交；A06 重试仍 `repeated=true` | 已批准；通过；“先预览”的 Agent 流程留给 M4-1b |
| 3 | A02 高版本库拒绝读写；A03 空库的 list/validate/export 可读且不建库，show 为 `not_found`；A42/A68 不存在的 id 为 `not_found` | 已批准；通过 |
| 4 | A14 不投出却给日期，退出 1、`invalid`；A05 创建事件的发生时间仍为 null | 已批准；通过 |
| 5 | A09 当前流程找不到岗位为 `not_found`；A19 补录已有岗位仍不做快照、不警告 | 已批准；通过 |
| 6 | A50 缺说明文件只警告并记录为 `unchecked`；A51 路径不存在退出 2、不写 | 已批准；通过；A50 的警告缺失已修复 |
| 7 | A54 无效材料、A55 岗位不同都退出 1、`invalid`、不写；A56 只给 `--sent` 接受并给缺材料警告 | 已批准；通过 |
| 8 | A43/A47 的事件与导出核对字段、相对审核路径、A57 的说明文件键均保持原行为；岗位快照仍逐字节复制 | 已批准；通过 |
| 9 | A62 孤立目录列入 `orphans`，退出 0、`valid=true`；A64 写入和 validate 均给隐私警告；补充检查确认 `mismatch`/`unchecked` 警告 | 已批准及补充裁定；通过 |
| 10 | A70 列表字段与排序、A69 show 外层结构、A67 导出同名覆盖均不变，四种路径写法仍拒绝 | 已批准；通过 |
| 11 | A76 junction 拒绝且目标目录无写入；A77 未知 actor 仍被 argparse 拒绝、退出 2 | 已批准；通过 |
| 12 | B01–B30 没有运行 | 等 M4-1b，不计为通过 |

### 新问题分类

- (a) 新的实现问题：0；A48、A50 已修复，无新增复现项。
- (b) 新的“按实现核对”分歧：0；A51 是此前已批准差别。
- (c) 新的期望分歧：0；A29–A37 是此前已批准差别。

### 本次复跑命令

在 holdout clone 根目录运行；输出目录必须是新的，位于冻结目录之外：

```powershell
git worktree add --detach <tmp>\v25-pr122b 52d84d0310c7f537ed3492c278cd177fa21a0163
conda run --no-capture-output -n ai-job-search-cn python tests/fixtures/cn/applications-m4-1-comparison/run_comparison.py `
  --repo <tmp>\v25-pr122b --typst <typst路径> --output <tmp>\v25-run-52d84d0
conda run --no-capture-output -n ai-job-search-cn python tests/fixtures/cn/applications-m4-1-comparison/check_rulings.py `
  --repo <tmp>\v25-pr122b --run <tmp>\v25-run-52d84d0
conda run --no-capture-output -n ai-job-search-cn python tests/fixtures/cn/applications-m4-1-holdout/verify_oracle.py
```

`check_rulings.py` 仅使用已完成复跑的数据调用只读命令，补充文件单独保存为 `ruling-checks.json`；不会改严格判定或冻结文件。

## 第一次对照的运行方法

在 holdout clone 的根目录运行（`--output` 必须是一个不在冻结目录里的新目录）：

```powershell
git -C <holdout clone> worktree add --detach <tmp>\v25-pr122 5c574417ad2b475073472cd3c16b2512bf6cfe4d
conda run --no-capture-output -n ai-job-search-cn python tests/fixtures/cn/applications-m4-1-comparison/run_comparison.py `
  --repo <tmp>\v25-pr122 --typst <typst路径> --output <tmp>\v25-run
```

整套约 4 分钟，`--only A43,A48` 可以只跑几个场景。运行器正常跑完就退出 0，**退出 0 不等于全部通过**，判断看 `results.json` 的 `counts`、`failed` 和每个场景的 `checks`。它不接入常规 unittest 自动发现。
