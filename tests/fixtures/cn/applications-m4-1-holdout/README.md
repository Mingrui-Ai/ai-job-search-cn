# V25 · M4-1 投递记录留出样例

本目录是 M4-1（投递记录，Claude A 实现）的独立留出样例：110 个场景，M4-1a 80 个、M4-1b 30 个。所有岗位、公司、档案、联系方式和投递经历都是原创虚构的测试内容，不来自用户或真实岗位。

## 依据

- 设计：`origin/feat/cn-m4-1-applications-design` 上的 `docs/cn/worklog/2026-11-03-m4-1-applications-design.md`，§11 验收，§14 裁定（提交 `7680056`）。
- 规划者 11-03 01:00 两条：`resume build` 写 `<材料名>.build.json`（`material_hash`、`profile_hash`、带时区的生成时间、每个输出文件的 SHA-256），投出时核对；找不到材料或没有说明文件只警告、不拒绝，记"材料未记录"。
- 规划者 cn-a7 11-03 18:20 四条：投出事件的材料版本字段叫 `material_version_ids`；`submission.materials_recorded` 未投出为 null、投出没有材料为 false；`--material`/`--sent` 只随投出记，`--historical` 必须带 `--submitted`，补录岗位不在库里只警告、不做快照，`record` 不带 `--note`，`--on`/`--at` 不能是将来；说明文件和材料对不上只警告、照样记录，核对结果进事件、导出可见。
- 按 §14 的切法分部分：M4-1a 是存储、`record`、`submit`、`status`、`show`、`list`、`validate`、`export` 和 `resume build` 的说明文件；M4-1b 是 `reply`、`note`、`followup`（含 `list --due`）、`void`、`backup`、入口和授权。

## 文件

| 文件 | 内容 |
| --- | --- |
| `scenarios.json` | 全部场景：准备、步骤、每步的期望、整体检查、按实现核对的项；另有约定、占位符、准备方式和状态表 |
| `inputs/jd/` | 3 份虚构 JD。A、B 在准备时存库；C 故意不存库，用来测"岗位不在库里" |
| `inputs/profile/` | 虚构档案（取自已合并的 V22 case-01） |
| `inputs/material/resume-1.json` | 投 {JOB_A} 的材料（V22 case-01 材料，只把 `job_id` 改成 {JOB_A}），能通过 `material validate` |
| `inputs/material/resume-1.edited.json` | 同一材料只改技能顺序，用来造"生成后材料被改过" |
| `inputs/material/resume-9.invalid.json` | 引用档案没有的 `exp-404`，`material validate` 退出 1 |
| `inputs/review/review-1-r1.json` | 对 `resume-1.json` 通过的审核结果（`review validate` 通过） |
| `verify_oracle.py` | 不导入产品代码，检查场景编号、计数、状态表、期望取值、占位符、输入摘要和冻结清单 |
| `oracle-manifest.json` | 除自身外每个冻结文件的 SHA-256 |

## 期望怎么写

- 每步期望写到行为层面：接受还是拒绝（`result`）、退出码类别（`exit`）、错误码（`error`）、有没有警告（`warning`），拒绝的一律不写（库文件、`artifacts/`、`exports/` 都不变）；导出里看得到什么写在 `checks`。
- 设计定了的照写：错误码 `invalid`、`transition`、`stale_revision`、`request_conflict`、`busy`；退出码 0 成功、1 业务拒绝、2 读不了；表名、导出字段名、事件类型名、状态名、渠道枚举。
- 设计没定的写 `impl`（按实现核对），场景的 `impl_check` 说明要核对什么。对照时这些项只记录实际行为，不判通过或失败；但同一场景 `checks` 里的底线（例如"不能悄悄写入""若接受必须有警告"）仍然要满足。
- 写步骤默认两段：先 `--preview` 取 `request_id`，再用同样参数加 `--request-id` 提交，期望指提交那一次。
- 状态表（A29–A37）每个起点对 9 个目标各建一条新投递再试，共 81 格，与设计 §4 逐格一致（`verify_oracle.py` 里独立再写了一遍状态表来对照）。

## 冻结的具体值

| 占位符 | 值 | 来源 |
| --- | --- | --- |
| {JOB_A} | `job_fa26c5d52ff7` | master `8a072b0` 上 `jd parse --save` 的结果 |
| {JOB_B} | `job_af4d7dd8c3a6` | 同上 |
| {JOB_C} | `job_cb7cb4d6e51d` | 同上（准备时不存库） |
| {MAT_HASH} | `ee15c290…54250` | `review draft` 对 `resume-1.json` 的输出；`verify_oracle.py` 用同一规范化算法复算 |
| {MAT_HASH_EDITED} | `3d974d1c…a4ea9` | 同上，对 `resume-1.edited.json` |
| {PROFILE_HASH} | `670f4cbd…206a2` | 材料里的 `profile_hash`，也等于由档案复算的值 |

PDF/Word 的字节不冻结（每次生成可能不同），期望写成"归档字节的摘要等于投出那一刻源文件的摘要"。

## 场景

**M4-1a（80）**

| 范围 | 场景 |
| --- | --- |
| 存储、版本、链接 | A01 建库与表、`user_version=1`、外键；A02 库版本更高拒绝写入（退出 2）；A03 库不存在时只读命令不建库；A76 `applications/` 是链接时拒绝写 |
| 预览、重试 | A04 预览不写（库不存在也不建）；A05 两步提交；A06 同 request 同内容重试；A07 同 request 不同内容 `request_conflict`；A08 不预览直接写；A78 一次请求两条事件的重试；A79 跨命令复用 request_id |
| record / submit | A09 岗位不在库里；A15 `--material`/`--sent` 不随投出；A16 `--historical` 不带 `--submitted`；A17 `--note`；A21 渠道枚举与平台名 40 字；A22 换渠道给重复警告；A23 之前的已结束不警告；A24 submit；A25 已投出再 submit；A42 投递 id 不存在；A77 `--actor` |
| 时间 | A10 只知日期；A11 带时区时刻存 UTC；A12 日期未知；A13 不带时区、不存在的日期、格式错、将来、`--on`/`--at` 同给；A14 不投出却给日期；A40 status 的发生时间 |
| 补录 | A18 岗位不在库里只警告不快照；A19 岗位在库里；A20 发生日期与记录时间分开；A80 故事一（补录→没回音→迟到的面试） |
| revision | A26 过期；A27 比当前大；A28 缺 `--expected-revision` |
| 状态表 | A29–A37 九个起点 × 九个目标；A38 `no_response` 回头要 reason；A39 reason 300 字；A41 未知状态值 |
| 材料与说明文件 | A43 相符（归档、摘要、`material_version_ids`、`sent_file_refs`、快照、`review_path`）；A44 PDF+Word；A45 submit 带材料；A46 投出后改材料/重新生成/改档案归档不变；A47 `material_hash` 不符；A48 发出文件摘要不在说明文件里；A49 文件不在 `resumes/` 下；A50 没有说明文件；A51 材料文件不存在；A52 投出不带材料；A53 未投出 `materials_recorded=null`；A54 无效材料；A55 材料岗位不同；A56 只给 `--sent`；A57 说明文件内容；A58 生成失败不留说明文件 |
| validate | A59 通过；A60 缺归档文件；A61 归档字节被改；A62 孤立目录；A63 投影与重放不一致 |
| 导出、查看 | A65 导出字段（含三种 `materials_recorded`）；A66 两次导出相同；A67 `--out` 只收文件名；A68 按 id 导出；A69 show 与导出一致；A70 list 过滤；A71 只读命令不改库 |
| 隐私 | A64 事件文字像手机号/邮箱/URL 时 validate 警告；A72 输出不带档案联系方式；A73 `git check-ignore` |
| 并发 | A74 两进程同一 revision；A75 持锁超过 5 秒 `busy` |

**M4-1b（30）**

| 范围 | 场景 |
| --- | --- |
| reply / note | B01 回复不改状态；B02 300 字；B03 时间；B04 未投出或已结束记回复；B05 备注；B06 已结束加备注 |
| followup | B07 设置/取消/参数互斥；B08 只到天；B09 过去日期；B10 终结清空跟进；B11 `list --due --as-of`（到期、`unset`、排除未投出和已结束）；B12 不带 `--as-of` |
| void | B13 作废最近一条状态事件；B14 误记拒信后重新改状态；B15 作废 submit；B16 作废跟进；B17 连续作废；B18 只有 created；B19 revision 与 reason；B20 作废 record 写的投出 |
| 其它 | B21 回复/备注里的联系方式；B22 重试与冲突；B23–B25 backup 与恢复后校验；B26–B28 入口、授权、文档命令；B29 故事三（输错作废再重记）；B30 故事二（换渠道再投，只跟进一条） |

## 设计没说清、按实现核对的地方

1. 拒绝的退出码：参数被 argparse 拦（未知选项、选项互斥、缺必填、枚举外的值）时是 2，被业务检查拦时是 1；设计没说哪些参数走哪条路（A13、A17、A21、A28、A41、B07、B19）。
2. 不带 `--preview` 也不带 `--request-id` 的调用怎么处理，自拟的 request_id 能否提交（A08）；预览阶段是否就做状态和参数检查。
3. 库不存在时只读命令的退出码和输出形状；库版本更高时只读命令能否读（A02、A03）；不存在的投递 id 的退出码（A42、A68）。
4. `record` 不带 `--submitted` 却给 `--on`/`--at`：拒绝还是忽略（A14）；`created` 事件的发生时间填什么（A05）。
5. 当前流程岗位不在库里的退出码和错误码（A09）；补录时岗位在库里要不要做快照（A19）。
6. 没有说明文件时文件是否仍归档、`materials_recorded` 是 true 还是 false（A50）；材料文件不存在与设计 §5"文件不存在退出 2"的冲突，以 01:00 裁定为准期望警告（A51）。
7. 材料通不过 `material validate`、材料 `job_id` 与投递岗位不同、只给 `--sent`：拦还是警告（A54–A56）。
8. 核对结果在事件和导出里的字段名；`review_path` 的写法；说明文件除两个摘要外的结构（A43、A47、A57）。
9. 孤立目录算 error 还是 warning（A62）；写入时是否也给隐私警告（A64）。
10. `list` 的"按最近提交时间倒序"指什么、每行字段（A70）；`show` 是否包一层（A69）；`export --out` 覆盖已存在文件（A67）。
11. 链接时的退出码（A76）；未知 actor 的退出码（A77）。
12. M4-1b：未投出/已结束时能否 reply、note、followup（B04、B06、B09）；过去的跟进日期；`list --due` 的输出结构和默认日期（B11、B12）；作废"作废事件"、只有 created 时作废、作废投出后材料版本怎么显示（B15、B17、B18）；backup 是否两步、清单格式（B23、B24）；入口个数（§1 写四个、§11 写三个 Agent）和授权写在哪（B26、B27）。

## 独立性

从 `origin/master@8a072b0` 开分支，只读了设计稿与裁定、`docs/cn/m4-0-store-decision.md`、master 上已合并的材料/审核/简历文档和 V22 文件；没有读取或获取 M4-1a 实现分支、`docs/cn/applications.md` 或任何 PR 的 diff。冻结前只在 master 上跑了准备步骤（存岗位、校验材料、评分、生成 PDF/Word、校验审核结果）确认输入可用，没有运行任何 `application` 命令。实现 PR 开出前本分支只在独立 clone 里，不推送。

## 复跑

```powershell
conda run --no-capture-output -n ai-job-search-cn python tests/fixtures/cn/applications-m4-1-holdout/verify_oracle.py
```

对照运行器在 M4-1a 的 PR 开出后另写，不改这里的任何文件。
