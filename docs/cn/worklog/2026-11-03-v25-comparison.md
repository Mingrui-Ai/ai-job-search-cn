# 2026-11-03 · V25：M4-1a 冻结样例对照（#122）

**完成**

- 推送冻结分支 `codex/v25-m4-1-holdout`（`b785a77`）。冻结文件没有改。
- 写了[对照运行器和报告](../../../tests/fixtures/cn/applications-m4-1-comparison/README.md)，对 #122 head `5c57441` 跑了 V25 里 M4-1a 的 80 个场景。#122 在 `tmp/` 下的临时工作树里检出（`--detach`），用完已删除。M4-1b 的 30 个场景等 M4-1b。
- 解释差别时读了 #122 的 `docs/cn/applications.md` 和 `jobsearch_cn/applications.py`，没有改产品代码。

**结果**

- 65 个通过，15 个不通过；455 项严格检查有 440 项通过，每个不通过的场景只差一项。冻结样例自检通过（14 个文件摘要相符）。
- (a) 3 条：没有说明文件时不给警告（P2，A50）；改过名的发出文件不和说明文件核对，记成 `unchecked` 而不是 `mismatch`（P3，A48）；发出文件的 `file_id` 是 `sent-N`，不是设计 §3 的 `pdf`/`docx`（P3，A43–A45，请规划者批准或改回）。
- (b) 12 处都有着落，第 12 处等 M4-1b。`--material` 指向不存在的文件时退出 2，记为规划者倾向已批准（A51）。
- (c) 1 条：状态表"→ drafted"一列被 argparse 拒绝（退出 2，不写），冻结期望是 `transition`/退出 1（A29–A37）。建议认可实际行为。

**决策**

- 状态表和 A51 的严格结果照冻结期望记为不通过，在报告里分类说明，不改冻结文件。
- 运行器改过三处（A50 收紧"有警告"的判断、A67 统一换行、补了一条路径替换规则），都在报告里写明，不影响冻结期望。

**验证**

- 运行器正常跑完，`results.json` 和 80 份命令日志里没有本机路径和档案联系方式。
- `python tools/lint_skills.py`、`python tools/security_guards.py`、`python -m unittest discover -s tests -t .`（1599 项通过、25 项跳过）和 `git diff --check` 都通过。`origin/master` 仍是 `8a072b0`，不用合入。

**下一步**

- 开 PR 交规划者审核和裁定 (a)(c)；不自行合并。M4-1b 的 PR 开出后再跑 B01–B30。
