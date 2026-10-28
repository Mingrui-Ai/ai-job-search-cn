# 更新记录（CN）

只记录 `jobsearch_cn` 和 CN 文档的版本变化；上游框架的版本见仓库根目录的 `CHANGELOG.md`。过程细节见 [工作记录](worklog.md)。

## v0.1.0（2026-10-28）

首个版本：中文 JD 离线入库。按用户决定，tag 打在通过真实 JD 验收的那一版代码上，所以已经带有 v0.2 的预览功能（见下文）。

**新增**

- `jd validate`：按 [Job Schema v1](job-schema.md) 校验岗位记录；每个从 JD 读出的值都必须注明出处，出处片段必须真实出现在原文中。
- `jd parse`：按规则从中文 JD 抽取薪资、届别、每周天数、实习时长、学历、转正、远程、城市、岗位类型、标题、公司、日期和技能，读不准的留空（[说明](jd-parse.md)）。
  - 一次导入多份 JD（一行 `===` 分隔）；
  - 支持 UTF-8、UTF-16 BOM、GBK 输入；拒绝被 PowerShell 5.1 管道损坏的文本；
  - 防注入检查：复用上游 `posting_guard`，补充中文注入句式（G1），只警告不拦截。
- 本地岗位库：`jd save`、`jd list`、`jd show`、`jd status`，`jd parse --save`；按内容指纹和规范化链接去重（G2），重复导入逐字段合并。
- Agent 入口：Codex（`AGENTS.md`）和 Claude Code（`cn-jd-import` 技能）共用 [JD 导入工作流](jd-import.md)。

**v0.2 预览（还在开发，格式可能变）**

- 个人档案 Profile v1 与建档流程 `cn-setup`：`profile validate`、`profile show`（默认隐去联系方式）。
- 硬性条件过滤 `match filter`：逐项给出"符合 / 冲突 / 未知"，附 JD 出处。
- 技能词表移到 `jobsearch_cn/skills.json`，按求职方向分组；用户可以在 `data/config/skills.json` 追加词条。

**修复与验收（2026-10-28）**

- 修复：工作地址里重复出现同一城市时，`jd parse` 会因为列表里有重复项而中止。现在按首次出现的顺序去重，保留原文出处。
- Codex 的样例实测通过；5 份用户提供的真实 JD 的导入、查询、去重验收也通过。用户用真实简历走完了 `cn-setup`，档案确认后保存，通过校验。真实材料只保存在本机 `data/`。

**已知限制**

- 规则是保守的，城市和技能只认固定词表，很多字段需要 Agent 或用户补全。
- BOSS 直聘的粘贴文本：开头有链接、日期这类元数据行时读不出标题；标签行里的公司和单独的"N个月"读不出来；一份 JD 写了几个不同的实习时长时，可能读到较宽松的那个。以上都要 Agent 按原文补全（H9）。
- 重新导入同一份 JD 时，规则读出的值会覆盖 Agent 补全的值，导入后要再核对一遍（H10）。
- 只用 JSON 文件存储，SQLite 按需接入（见[总体规划](master-plan.md) D4）。
- 需要 Python 3.10 及以上。
