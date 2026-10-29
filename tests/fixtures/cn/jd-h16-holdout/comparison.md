# V8 · H16 留出样例对照

H16 对本批样例没有造成旧字段或过滤状态退步。9 个冻结技能组中，语义一致 **8/9**，原写法集合一致 **7/9**，多读 **0**；漏掉 `Git、SVN 其一即可`，而 SVN 在原基线中也没有被抽取。将冻结人工字段和技能组映射进新契约后，5 份岗位均可校验、保存，10 组技能分、技能项数和缺口均符合契约。剩余差异及是否另开任务，交规划者裁定。

## 版本与独立性

- 被测 PR：[#59](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/59)，head `89f3849d46d5997cd0091fdc1981d065526a6d30`。
- 原基线：`e42f82889ee2b5a2f8926cea7a2e6b4834a78486`；[原基线报告](baseline.md)和 `actual/master/` 原样保留。
- 冻结提交：`0b47cf8`；[清单](oracle-manifest.json)的 LF SHA-256：`be6a17191a51ef055e98626f8b9349cab1825ae9a26476dbe59ae11f41e5cd97`。清单内 13 个文件（包括 README）及两个示例档案的哈希在运行前后均一致。
- 样例为 5 份原创虚构 JD，其中 3 份非技术方向；冻结后才运行原基线，#59 开出后才查看其公开文档和运行其 CLI。没有阅读 H16 解析、评分、存储或校验实现；实现类 PR 审核由 Codex B 负责。
- 新字段按 [规划者裁定](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/59#issuecomment-6491885255)映射为 `requirements.skill_alternatives`，不回改冻结 sidecar。
- 执行时间：2026-10-29 08:36:10–08:36:18 UTC；conda `ai-job-search-cn`，Python 3.12.15；55 次公共 CLI 调用均退出 0、无 stderr。[命令记录](actual/h16-89f3849/commands.json)中的工作区路径用 `<workspace>` 表示。

## 旧字段与过滤

| 指标 | 原 master 基线 | H16 |
| --- | ---: | ---: |
| 14 个字段组 × 5 份 | 66/70 | 66/70 |
| 技能原文词项命中 | 21/24 | 21/24 |
| 漏技能 / 多技能 | 3 / 1 | 3 / 1 |
| 直接解析后过滤总结论 | 10/10 | 10/10 |
| 直接解析后七项检查状态 | 69/70 | 69/70 |
| 人工字段重放后总结论 | 10/10 | 10/10 |
| 人工字段重放后检查状态 | 70/70 | 70/70 |

逐份差异与基线完全相同；不仅是计数相同，具体字段值和 10 组 × 7 项状态也逐项对过。

| 样例 | 字段组一致 | 与人工值的差异 |
| --- | ---: | --- |
| `backend_choices_intern` | 14/14 | 无 |
| `content_tools_campus` | 14/14 | 无 |
| `frontend_tools_intern` | 12/14 | “本科或硕士及以上”最低学历读成 master，人工为 bachelor；漏 HTML、CSS、SVN |
| `research_tools_intern` | 13/14 | 将“统计学或市场营销相关专业”中的统计学多读为技能 |
| `visual_tools_intern` | 13/14 | “大专或本科及以上”最低学历读成 bachelor，人工为 associate |

前端样例 × ops 的学历检查因此为 `conflict`，人工为 `match`；其他冲突使总结论仍为 `ineligible`，不能用总结论一致掩盖这处错误。视觉样例的学历误读未改变这两个档案的检查状态。

## 9 个冻结技能组逐项对照

| 样例 | 冻结原文 | H16 组 | 结论 |
| --- | --- | --- | --- |
| 后端 | 熟悉 Go 或 Golang 或 Java | `[Go, Java]` | 原写法集合不同；Go/Golang 按已有同义词契约合并后语义相同。平面 skills 中仍保留 Go、Golang、Java |
| 后端 | Docker、Kubernetes 任选其一 | `[Docker, Kubernetes]` | 一致 |
| 调研 | Excel 或者 SPSS | `[Excel, SPSS]` | 一致 |
| 调研 | Tableau、Power BI 至少一种 | `[Tableau, Power BI]` | 一致 |
| 视觉 | Photoshop、Illustrator 任一即可 | `[Photoshop, Illustrator]` | 一致 |
| 视觉 | Figma、Sketch 二选一 | `[Figma, Sketch]` | 一致 |
| 内容 | 秀米、剪映 之一 | `[秀米, 剪映]` | 一致 |
| 前端 | Postman、Playwright 至少一项 | `[Postman, Playwright]` | 一致 |
| 前端 | Git、SVN 其一即可 | 无 | 漏完整组；直接解析的 skills 仅有 Git，没有 SVN，原基线也漏 SVN |

8 个实际组的出处均逐字存在，且每个组的所有成员共同出现在同一出处片段。没有把专业、学历、城市、届别的“或”生成为技能组，也没有把明确要求全部掌握的 `Excel/PowerPoint`、`HTML/CSS/JavaScript` 生成为任选组。这里的“不多读组”不等于旧字段解析全对：上述学历错误、技能漏读和专业误入技能仍然存在。

冻结的 10 条 `not_groups` 陷阱也包含“试用期3个月”，校招的实习月数仍为不适用。本批没有“均可”、PS 或 AI 缩写用例，不能据此对这些写法的实际分布下结论。

## 10 组技能评分

保持原 tech/ops 档案，不补 Agent 经历。下表分数都是**技能维度**；“人工字段重放”用冻结的 14 个字段及全部 9 个组，单独校验并写入隔离岗位库。技能算式来自公开契约和示例档案，计算器不导入应用代码；这部分算式是在 H16 字段契约确定后写的，不冒充冻结时已有的评分 oracle。

| 样例 × 档案 | 原基线 | H16 直接解析 | 人工字段重放 | 完整人工输入的算式（×100 后四舍五入） |
| --- | ---: | ---: | ---: | --- |
| 后端 × tech | 45 | 90 | 90 | `(1 + 0.8) / 2` |
| 后端 × ops | 0 | 0 | 0 | `0 / 2` |
| 内容 × tech | 0 | 0 | 0 | `0 / 3` |
| 内容 × ops | 70 | 67 | 67 | `(1 + 1 + 0) / 3` |
| 前端 × tech | 0 | 0 | 0 | `0 / 5` |
| 前端 × ops | 0 | 0 | 0 | `0 / 5` |
| 调研 × tech | 0 | 0 | 0 | `0 / 2` |
| 调研 × ops | 20 | 33 | 50 | `(1 + 0) / 2`；直接解析多算统计学，分母为 3 |
| 视觉 × tech | 0 | 0 | 0 | `0 / 2` |
| 视觉 × ops | 20 | 40 | 40 | `(0.8 + 0) / 2` |

- 后端：Go/Golang 不重复计分；任选组只取最佳成员。tech 不再列 Java、Kubernetes 为缺口。ops 只有两个组缺口，分别引用组的原文。
- 内容：ops 同时会秀米和剪映，只能在这一组得 1，Excel 得 1，PowerPoint 得 0，技能分从 70 降到 67 是契约要求的结果。PowerPoint 仍是唯一技能缺口。
- 前端：直接解析只算 3 项（JavaScript、Postman 或 Playwright、Git），完整输入应为 5 项（HTML、CSS、JavaScript、Postman 或 Playwright、Git 或 SVN）。两个档案都不具备这些技能，因此都得 0；不能用分数一致掩盖分母及缺口的缺失。补全后 5 项、两组缺口均正确。
- 调研：ops 的 SPSS 不再单列缺口，Tableau/Power BI 合为一项缺口；专业误读还使直接解析多出统计学缺口并将技能分压到 33。按冻结人工输入重放得到 50，只有 Tableau/Power BI 一项技能缺口。
- 视觉：ops 的 Illustrator 不再单列缺口，只保留 Figma/Sketch 一组缺口；Photoshop 的 0.8 按最佳成员进入分子。

两条路径的 20 个规则评分输出均通过独立算式、项数、缺失集合、缺口原文检查，且都输出 `rules_version: 2`；这是“评分符合各自输入”，不代表直接解析完全符合人工输入。方向分在 10 组中没有变化；按解析结果的方向计数分别从 tech 4→2（后端）、ops 2→1（内容）、tech 4→3（前端）、data 4→3（调研）、design 4→2（视觉）。人工重放去掉统计学后，调研为 data 2；前端补入的未知词项未增加词表方向计数。

所有规则记录 `complete: false`，经历均为 null，ops 的薪资也为 null；不把它们当作完整推荐或用户认可。仅举总分影响：后端 × tech 由 74/good 变为 95/strong，内容 × ops 由 84/strong 变为 82/strong；两者都仍缺维度。

## 提请规划者裁定

1. 将 `[Go, Java]` 对冻结 `[Go, Golang, Java]` 计为语义一致是否认可。本报告同时保留 7/9 原写法一致和 8/9 语义一致，不修改 oracle。
2. `Git/SVN` 漏组与 HTML/CSS/SVN 漏技能是否另立词表或解析补充任务。完整人工输入下该组可以校验、保存和计分；当前没有证据将其归为分组计分退步。
3. 两处备选学历取错最低值、专业词统计学误入技能均为 V8 原基线已见问题，建议单列后续解析任务；统计学会实际影响技能分和缺口。

## 复现与交付范围

只需提取目标提交的 `jobsearch_cn/` 和 `tools/` 到自己的忽略数据目录，避免整仓库副本中的 `.gitignore` 被安全守卫当成子目录配置。应用和工具文件会在运行前后与 `git archive` 逐字节核对。

```powershell
conda activate ai-job-search-cn
git archive --format=zip --output=data/v8-h16-code.zip 89f3849d46d5997cd0091fdc1981d065526a6d30 jobsearch_cn tools
Expand-Archive -LiteralPath data/v8-h16-code.zip -DestinationPath data/v8-h16-code
python tests/fixtures/cn/jd-h16-holdout/run_comparison.py --code-dir data/v8-h16-code --commit 89f3849d46d5997cd0091fdc1981d065526a6d30 --label h16-repeat-1
python tests/fixtures/cn/jd-h16-holdout/run_comparison.py --verify-only
```

每次必须用新 label；脚本拒绝覆盖已有快照或本地库。`jd validate` 是纯文件校验，不接受 `--data-dir`，其余每次调用都显式指定独立数据目录。脚本不写真实数据、不导入应用模块、不添加回归测试、不修改实现。结果及映射后的完整岗位见 [actual/h16-89f3849/](actual/h16-89f3849/)，汇总见 [summary.json](actual/h16-89f3849/summary.json)。
