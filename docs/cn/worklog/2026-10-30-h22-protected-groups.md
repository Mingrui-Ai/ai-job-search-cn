# 2026-10-30 · H22 复审修正：显式清空不得绕过技能组保护

## 完成

- 接续 #67 的 `3b58b92`，按 Codex B 复审和规划者 2026-10-30 裁定修正跨字段清空。
- 在自己的 `codex/h22-explicit-clear` 分支合入最新 `origin/master@acc7e3c`，无冲突，合并提交 `7303b55`。V13 已先交付 #71 并在 #68 回评。
- 全量检查前再次同步 `origin/master@5085bec`（#71 已合并），无冲突；该次同步只有 V13 工作记录。
- 在逐字段合并与 `_fit_alternatives` 之间增加显式清空保护：技能清空实际生效、但还有必须保留的组时，抛出 `StoreError`，尚未进入磁盘写入。错误列出组索引/成员、组缺清空理由或来源更低的原因，以及两字段分别写理由、组使用足够来源的修正方式。
- `jd-import.md` 和 `job-schema.md` 说明整条岗位记录被拒绝、单独 Schema 通过仍可能保存失败，并强调不能把 Agent 判断改标成用户确认。

## 决策

- 新的显式技能清空成功参与字段合并后，如果来源或理由保护要求保留旧技能组，拒绝该记录的整次写入，不让 `_fit_alternatives` 静默删除组；不保留其他字段的部分更改。
- 只处理 H22 的显式清空入口；H16 普通技能/组一致性处理、同 URL 的新原文替换行为保持原样。
- 检查本次传入的显式技能清空，而不是只看合并结果是否为空：合法的既有空技能遇到普通重导入，仍可按 H16 丢弃不适配的重新解析组；技能清空本身被高来源旧技能挡住时，也不额外报错。
- 错误指出被保护的组、保护原因和正确的同步清空方式。测试仅用合成 JD 和临时数据目录；不改安全白名单、冻结样例或真实数据。

## 验证

- 修复前运行 `tests.test_cn_store_clear.SkillAlternativeClear`：8 个测试方法中出现 **13 个失败子用例**（user 组被 agent 清空、缺独立组理由、按 URL 找回相同原文、CLI 错误路径），均复现“仍返回 updated / 没有抛错”。既有正例与 H16 边界通过。
- 修复后运行 `python -m unittest tests.test_cn_store_clear tests.test_cn_store tests.test_cn_schema`：**100 项通过，9.690 秒**。
- 新增 5 个测试方法，覆盖：
  - 技能源为 rule、组旧来源 rule/agent/user × 新组来源 agent/user；来源足够且分别有理由时清空成功，两个字段分别保留出处，规则重导入不恢复。
  - 组理由缺失、user 的 null 理由、rule 来源的空组 × 三种旧组来源；即使输入 Schema 合法，也拒绝合并。传入记录不被修改，岗位目录文件名与内容字节全部不变；用公司字段的独立修改确认没有部分落盘。
  - 同一原文通过 URL 找回保留旧 id 的岗位时，同样拒绝绕过保护。
  - 技能清空本身因来源不足未生效时，不误报；既有空技能的普通重导入和真正的新原文整条替换仍按旧规则工作，保留状态、id、首次导入时间。
  - CLI：`jd validate` 先通过，`jd save` 沿现有 StoreError → InputError 路径返回退出码 2、stderr 的 `{"error": "..."}`，stdout 为空、文件不变；补充模拟用户对组的确认和理由后再次保存成功。没有修改 CLI 错误契约。
- conda `ai-job-search-cn`、Python 3.12.15，全量 `python -m unittest discover -s tests -t .`：**1256 项，OK (skipped=12)，214.242 秒**。
- `python tools/security_guards.py`、`python tools/lint_skills.py`、`git diff --check` 通过。提交前再次拉取，`origin/master` 仍为 `5085bec`，无需进一步合并；`git status` 只有本次源码、测试和三份 CN 文档，没有 data 文件。

## 遗留

- 实现修正由 Codex B 独立复审；本轮测试是作者回归，不当成独立验收。

## 下一步

- 推送 #67，更新 PR 描述并逐条回评新增修改及验证结果。
