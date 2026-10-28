# 更新记录（CN）

只记录 `jobsearch_cn` 和 CN 文档的版本变化；上游框架的版本见仓库根目录的 `CHANGELOG.md`。过程细节见 [工作记录](worklog.md)。

## v0.1.0（2026-10-27）

首个版本：中文 JD 离线入库。

**新增**

- `jd validate`：按 [Job Schema v1](job-schema.md) 校验岗位记录；每个从 JD 读出的值都必须注明出处，出处片段必须真实出现在原文中。
- `jd parse`：按规则从中文 JD 抽取薪资、届别、每周天数、实习时长、学历、转正、远程、城市、岗位类型、标题、公司、日期和技能，读不准的留空（[说明](jd-parse.md)）。
  - 一次导入多份 JD（一行 `===` 分隔）；
  - 支持 UTF-8、UTF-16 BOM、GBK 输入；拒绝被 PowerShell 5.1 管道损坏的文本；
  - 防注入检查：复用上游 `posting_guard`，补充中文注入句式（G1），只警告不拦截。
- 本地岗位库：`jd save`、`jd list`、`jd show`、`jd status`，`jd parse --save`；按内容指纹和规范化链接去重（G2），重复导入逐字段合并。
- Agent 入口：Codex（`AGENTS.md`）和 Claude Code（`cn-jd-import` 技能）共用 [JD 导入工作流](jd-import.md)。

**修复与验收（2026-10-28）**

- 修复工作地址内重复出现同一城市时 `jd parse` 因重复列表项而中止的问题，保留首次出现顺序与原文出处。
- Codex 样例实测和 5 份用户提供的真实 JD 导入、查询、去重验收已通过；真实简历 `cn-setup` 经用户确认后保存并通过校验。真实材料只保存在本机 `data/`。

**已知限制**

- 规则是保守的，城市和技能只认固定词表，很多字段需要 Agent 或用户补全。
- 只用 JSON 文件存储，SQLite 按需接入（见[总体规划](master-plan.md) D4）。
- 多处实习时长要求、网页元信息及标签等仍可能需要 Agent 按原文核对和补全。
- 需要 Python 3.10 及以上。
