# 2026-11-01 · A3 dsh 三工作流实测清单

**完成**

- 从 `origin/master@b536270` 新建 `codex/a3-dsh-checklist`，完成用户操作 dsh 的虚构输入、逐步期望、常见失败与记录模板，见 [a3-dsh-checklist.md](../a3-dsh-checklist.md)。
- 覆盖三个 A2 入口发现、Windows/conda 与权限探针、JD 解析/补全/校验/去重/注入防护、逐节建档确认/来源/材料读取、9 项过滤、五维评分/校验/保存/报告/反馈，以及权重试算/拒绝/确认、两种过期后的重评分。
- 旧清单改为跳转；路线图仅更新 A3 的准备进展，保留未勾选状态。未改技能、CLI、测试或上游文件。

**决策**

- 只准备验收并在隔离目录核对 CLI；不启动 dsh、不使用 Key、不读取真实数据。A3 是否通过由用户实测记录决定。
- 以三个共用工作流为唯一规范，清单仅写输入、观察点和通过标准。旧清单改为指向新版，避免两套验收口径并存。
- 本地权限设置不提交；按用户指示，在 #105 合并后还原本地 `.claude/settings.json` 再合入 master。

**验证**

- conda `ai-job-search-cn`，Python 3.12.15：从清单附录提取虚构原文，在本工作树忽略的 `data/a3-dsh/` 新建独立目录、手工构造与回答表一致的参照档案，执行 55 次 CLI 调用。准备脚本及输出只留本地，不作为 dsh 验收证据。
- 4 份岗位的最终字段、4 个过滤总判断和 36 项状态一致；JD/profile/match 校验、重复导入、guard 警告、报告及反馈表生成均符合预期。A/B/D 技能分 90，C 为 27；首次规则草稿总分 89/87/28/89。明确区分 C 的整个 interview/start 为 null 与对象中的空字段。
- 用虚构的示例经历判断核对 total 报错对象的复制与保存；不将示例经历分设为 dsh 的固定期望。权重试算不改档案/notes/匹配文件，确认后的重算与试算一致，保留 Agent 维度；实际出勤变更产生 profile 过期并清空旧 Agent 补充。
- `lint_skills` 通过（12 skills、12 commands）；文档 UTF-8、相对文件链接及 `git diff --check` 通过。
- #105 合并前，`security_guards` 出现用户已说明的 12 条 `required ask rule missing`。没有还原或提交本地设置，没有修改守卫。
- 全量 `python -m unittest discover -s tests -t .`：1447 项，1434 通过、12 跳过、1 失败，耗时 249.507 秒。唯一失败为 `tests.test_security_guards.RealRepoTests.test_guards_pass_on_this_repo`，原因同上，正是 12 条缺失 ask 规则；无其他失败或错误。#105 在提交前仍未合并，保留此已知例外，不将检查记为全绿。

**合入 #105 后复核**

- 按用户通知，先还原本地 `.claude/settings.json`，再合入 `origin/master@7775738`（包含 #100 和 #105），合并提交为 `0693803`，无冲突。本分支的设置文件与 master 一致。
- conda `ai-job-search-cn` / Python 3.12.15：`lint_skills`、`security_guards` 均通过，原先的 12 条缺失 ask 规则错误已消除。
- 全量 `python -m unittest discover -s tests -t .`：1494 项，1473 通过、21 跳过，0 失败、0 错误，耗时 286.066 秒。
- 在新的隔离目录重跑清单的 55 次 CLI 调用，全部通过；4 个总判断、36 项状态及其他断言仍与清单一致。`git diff --check` 通过，相对最新 master 仍仅有本 PR 的四份文档改动。以上首次验证结果保留为历史记录。

**遗留**

- 用户尚未在 dsh 中执行本轮清单；不能用 CLI 核对代替技能发现、环境继承和交互确认验收。
- DOCX/PDF 的 dsh 提取、UI 中的确认/拒绝和反馈操作均留给用户实测；本次只提供步骤与通过标准。

**下一步**

- 已开 [PR #106](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/106)，交规划者审核；用户按清单执行后，由验证者核对记录，问题交规划者分派。
