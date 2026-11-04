# V24 · Codex 简历工作流入口实测

结论：本机 Codex CLI 的 `workspace-write` 路径不能独立完成构建，V24 不能判为入口全流程通过。宿主补充构建后，已实测新起草会话、原样交接至新审核会话、修改、旧审核摘要失效和第二轮独立审核。最终为 `revise`：两条措辞建议已解决，D5 版面问题仍需处理，按两轮上限停止。宿主成功不抵消 CLI 沙盒失败。

## 被测范围

- 基线：`90e30e0c0cfaeb74377be7f62adbd1fd94795ead`（#116 合并后）。
- 从新建的 Codex CLI 会话开始，通过根 `AGENTS.md` 的“生成简历”入口进入 `docs/cn/resume-workflow.md`；允许沿正文引用读取材料、评分、审核格式和清单文档，不读取实现源码或既有验收结论。
- 档案：公开的 `tests/fixtures/cn/material/tech-m3/profile`；岗位：公开的 `tests/fixtures/cn/jd/boss_intern.txt`。tech-m3 本身没有岗位文件，采用另一份公开 JD 补足前提，不使用真实用户数据。
- 隔离工作树、临时数据均置于仓库外 `tmp/` 下；支持该参数的业务命令显式传 `--data-dir`，`review validate/show` 使用隔离目录下的绝对文件路径（见 P3-2）。报告中的 `<repo>`、`<review-repo>`、`<data>`、`<typst>`、`<private-log>` 是本机绝对路径的代称。
- 起草与审核使用不同的新会话；审核提示只传工作流规定的路径、轮次、build 输出和选材说明，第二轮补充修改说明及前轮结果路径，不传起草对话或推理。

## 运行环境

Codex CLI 0.166.0；conda `ai-job-search-cn`；工作树为 detached HEAD。CLI 使用 `--sandbox workspace-write`、`approval_policy=never`、`--json` 记录实际事件，继承已配置的认证和模型，不读取或复制密钥。

使用方式依据 [OpenAI 官方非交互模式文档](https://learn.chatgpt.com/docs/non-interactive-mode)：`codex exec` 可从标准输入读取提示，`--json` 保留命令事件，`-o` 保存最终交接文字。这里检验本机实际行为，不将 CLI 参数视为已经验证的安全保证。

## 实测记录

业务命令、机器结果及命令耗时见 [commands.json](validation/v24-codex-resume/commands.json)，会话用时见 [sessions.json](validation/v24-codex-resume/sessions.json)。命令耗时来自 Codex 原始日志的 CommandExecution.duration；宿主命令由计时包装器记录。会话用时包括模型处理、文件读取和服务重试，不能当成 CLI 执行耗时。原始对话/推理未放入仓库。

交接原文（只替换本机路径）、原文件 SHA-256 和前后文件比较见 [evidence.json](validation/v24-codex-resume/evidence.json)。同目录保留公开虚构材料的两版和两轮审核快照，供审核者用 `review validate <review-rN.json> --material <material-rN.json>` 重验。快照文件改了名称，所以需要显式 `--material`；`material_hash` 是 CLI 对内容计算的摘要，与原文件字节 SHA-256 不同。

会话启动形式为 `codex exec --sandbox workspace-write -C <repo> -c 'approval_policy="never"' --json -o <final-file> -`，从标准输入传提示；恢复起草用 `codex exec resume <thread-id>`，两轮审核分别新建会话，在 `<review-repo>` 下执行，仅额外授权该岗位材料目录。两次传给审核会话的标准输入都直接读取原起草会话的最终输出文件，未改写交接或传入起草历史。PDF 临时预览由宿主用 `pypdfium2.PdfDocument(pdf)[0].render(scale=1.5)` 生成 PNG，再由各会话的看图工具查看；此临时渲染未单独计时，也未测 Word 页面。

| 步骤 | 实际行为与结果 | 命令耗时（秒） |
| --- | --- | --- |
| 入口与前提 | 新会话读取入口、流程及引用文档；中文文档第一次用 PowerShell 默认编码出现乱码，之后自行改用 UTF-8 重读 | 单独保留会话总用时 |
| 导入 | `jd parse <data>/inbox/boss_intern.txt --site boss --save --data-dir <data>`，保存公开虚构岗位 | 0.571 |
| 档案 | `profile validate` / `profile show`，校验通过，读取使用默认联系信息脱敏 | 0.588 / 0.600 |
| 匹配 | `match score <id> --draft`；按文档补经历，首次校验提示总分需重算，照错误给出的对象更新后校验、保存 | 初稿 0.346；两次校验 0.342 / 0.338；保存 0.338 |
| 匹配回读 | `match show` / `match list`，81 分、strong、完整、不过期；未改档案权重 | 0.362 / 0.578 |
| 材料 | 写 `resume-1.json`，含有依据的简介、教育、实习、课程项目、技能与荣誉；`material validate` 通过、无警告 | 0.472 |
| CLI build | 默认临时目录和材料目录内 TEMP/TMP 两次均 WinError 5；没有 PDF/DOCX，按文档提前停止 | 0.613 / 0.611 |
| 宿主对照 | 当前宿主的既有完整权限环境中，对同一份材料原样 build 成功，problems/warnings 均空 | 1.234 |
| 页面与交接 | 宿主将实际 PDF 渲染为 PNG；宿主和起草会话各自查看后，起草会话打印完整交接文字。原样传给另一个新审核会话 | 原起草 418.609；恢复起草只读交接 81.375 |
| 修改 | 原起草会话采纳 E4 两条建议，仅改两处要点；material validate 通过、无警告；D5 如实保留 | 校验 0.581；会话 295.297 |
| 第二次构建 | 宿主对修订材料 build 成功，problems/warnings 均空；PDF 1 页，渲染新 PNG；原起草会话再次看图 | 1.156 |
| 旧审核失效 | 原起草会话用正确签名运行 review validate，退出 1，明确报 material_hash 变化；未修改历史审核 | 0.305 |
| 第二轮交接 | 原起草会话打印前轮路径、逐条处理、真实 build 输出及限制，原样传入另一个新审核会话 | 起草交接会话 89.703 |
| 第二轮审核 | 新上下文只核对改动与上一轮问题；D5 一条 must、无剩余 suggest，verdict=revise；材料和审核校验均通过 | 材料 0.057；审核 0.349；会话 299.266 |
| 交付说明 | 原起草会话运行 review validate/show，确认 PDF/Word 存在，给出独立审核结论、缺口、D5 未解决和宿主构建限制；只读、没有第三轮 | validate 0.287；show 0.276；会话 103.985 |

第一轮独立审核已写文件：`mode=independent`、`verdict=revise`，D5 一条必改、E4 两条建议，覆盖表 13 行。审核期间原有 11 个数据/产物文件的 SHA-256 全部不变，只增加 `review-1-r1.json`。写完后的 CLI 服务限流令该轮进程退出码为 1；恢复同一会话后仍因派活参数要求与接口冲突而未完成校验，宿主使用明确材料快照路径校验通过（0.250 秒）。

第二轮审核期间原有 13 个文件全部不变，只增加 `review-1-r2.json`。审核者确实通过看图工具查看最新 PNG，没有只凭文本假称检查 D5。第一轮和第二轮的 `material_hash` 分别为 `ec339680…44d8f4`、`71cb50d1…fffa72`；旧审核的失效没有通过重写摘要规避。两轮公开快照用各自的 `--material` 回验均通过。

## 问题与限制

**P2-1（运行环境/入口可用性）**：Windows 上 Python 的 `TemporaryDirectory` 已创建后，复制模板时无法在里面创建 `build/`，随后清理该临时目录也报 WinError 5。改到材料目录内的 TEMP/TMP 仍复现；同一数据、代码与 Typst 在当前宿主成功。能确认的是本机 CLI 沙盒路径受阻，尚不能仅凭此证明是业务代码缺陷或所有 Windows 环境都失败。没有放宽子会话权限、改 ACL 或改代码；该 CLI 路径按文档提前停止的行为符合说明。

**P3-1（错误呈现）**：上述失败返回 Python traceback，而非项目通常使用的 JSON 错误，日志含本机临时路径。没有输出成功 JSON或假称生成文件。公开证据只保留已脱敏的错误类型、阶段和结果，不公开原始绝对路径。

**P3-2（派活与接口不一致）**：本次任务和交接提示要求所有业务命令显式加 `--data-dir`，但 `review validate`、`review show` 没有这个参数，实际报 `unrecognized arguments`。`review-format.md` 第 3 节列出的签名是正确的：这两条命令读审核文件及同目录材料，或显式 `--material`，不访问岗位库/档案目录。因此后续明确将其作为例外，使用临时数据下的绝对文件路径。此项归因于测试约束过宽及交接未纠正约束，不把文档已有的正确签名误报为 CLI 缺陷。

**P3-3（D5 版面与处理边界，待裁定）**：独立审核把意向行末尾“起可到岗”独占一行及页底约四分之一留白列为 D5 必改。没有重叠或裁切，但 `build` 的空 problems 无法替代视觉审核。求职意向由档案渲染，当前材料没有该字段；不能为改善版面改候选人的意向，也不能编造经历填空。工程优先级 P3 与审核清单的 `must` 是不同维度：后者决定审核仍需修改，不代表工程事故严重度。请规划者裁定留白阈值和材料不可修的问题如何交付；截至查询时，意向换行已有待合并的 #119，本报告仍按 #116 基线评价，不假定它已修复。

环境观察：恢复起草时 CLI 提示用户配置项 `disable_response_storage` 已不识别，本轮未修改用户配置；第一轮审核遇到服务 token 速率限制后自动重试。这些与材料校验或产品逻辑失败分开记录。

**P3-4（交付说明遗漏）**：原起草会话的实际最终交付已说明 Word 页面未查看，但没有复述第 4 节的“投递优先用 PDF，Word 版可能排到第二页”。原文保留在 evidence.json，没有事后润色成完全遵循文档。验证者补充：正式交付时仍应提醒用户优先使用 PDF，并自行打开 Word 核对分页。

## 演练交付结果

实际交付文字已保存于 evidence.json 的 `draft-delivery` 项；当时确认生成的 PDF、DOCX 和第 2 轮审核文件存在。两条 E4 建议都已采纳，没有未采纳建议；D5 已看而未通过，Word 未看。保留的缺口是 Redis、Kubernetes、核心业务系统经历、Go 高并发服务及 MySQL/Redis 存储设计优化；到岗日期、面试安排属于 JD 待确认项。

最终 `review validate/show` 成功表示格式及版本正确，不代表 `verdict=pass`。原起草会话交付后 14 个文件摘要全部不变；档案源文件全程不变，进入审核后未改岗位或匹配记录，未修改代码/模板/权限、未投递或外发简历。临时 PDF/Word 按任务要求清理，报告中的路径只是历史命令证据，不是当前可下载的交付文件。

## 检查与清理

基线和提交前同步均为 `origin/master@90e30e0`。conda `ai-job-search-cn` 中：`python tools/lint_skills.py` 通过（13 个技能），`python tools/security_guards.py` 通过；`JOBSEARCH_CN_REQUIRE_TYPST=1`、已配置真实 Typst 时运行 `python -m unittest discover -s tests -t .`，1588 项，1574 通过、14 跳过，零失败/错误，309.675 秒。公开 JSON、两版材料仅两处预期差异、审核快照回验、路径/联系方式/密钥标记及 U+FFFD 扫描均通过。

两个隔离工作树及其中的数据、生成物已用 `git worktree remove` 删除，并回查工作树列表和目录不存在。保留脱敏报告证据和本地忽略的运行日志。

清理例外：CLI 第一次失败留下的 `<system-temp>/jobsearch-cn-resume-4uokvui7` 仍存在。已只读确认它是本轮的普通目录；自动审批先后拒绝有范围检查的删除命令和明确 `-LiteralPath` 的删除命令，仅返回 `blocked by policy`，没有具体原因。删除命令没有执行，未以其他工具绕过；该单个系统临时目录需由用户或获授权的环境清理。
