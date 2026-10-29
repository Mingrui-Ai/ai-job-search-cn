# V8 · master 基线

冻结提交 `0b47cf8`；冻结 manifest 的 LF SHA-256 为 `be6a17191a51ef055e98626f8b9349cab1825ae9a26476dbe59ae11f41e5cd97`。被测代码为冻结时的 `origin/master@e42f82889ee2b5a2f8926cea7a2e6b4834a78486`；运行前确认 `jobsearch_cn/`、`tools/` 与该提交无差异。

正式基线于 2026-10-29 06:50:02–06:50:10 UTC 执行，晚于冻结。此前一次回放脚本在给不支持该参数的 `jd validate` 传 `--data-dir` 时停止；仅修正调用脚本，改用新数据目录重跑，输入期望没有改动。

使用 `data/v8-check/master-02` 隔离数据。每份执行 `jd parse --save`，tech/ops 分别执行 `match filter` 与 `match score`；此外用冻结人工字段和出处构成单独记录，经 `jd validate/save` 后在另一个存储回放过滤。未补 Agent 经历，不将规则总分当作完整评分。

完整输出见 [actual/master](actual/master)，汇总见 [summary.json](actual/master/summary.json)。

| 指标 | 结果 |
| --- | --- |
| 14 个字段组 | 66/70 一致 |
| 正向技能命中 | 21/24；漏 3，多 1 |
| 原始解析上的过滤结论 | 10/10 一致 |
| 原始解析上的七项检查 | 69/70 一致 |
| 人工字段回放过滤结论 / 七项检查 | 10/10、70/70 |
| 冻结任选技能组 | 9；当前 master 不支持该字段 |

| 样例 | 字段一致 | tech / ops 技能规则分 | 与人工字段的差异 |
| --- | --- | --- | --- |
| backend_choices_intern | 14/14 | 45 / 0 | 无；Go/Golang 已去重，但任选组尚不表达 |
| content_tools_campus | 14/14 | 0 / 70 | 无；斜线且明确都要的工具按两个技能保留 |
| frontend_tools_intern | 12/14 | 0 / 0 | 最低学历把“本科或硕士及以上”读为硕士；漏 HTML、CSS、SVN |
| research_tools_intern | 13/14 | 0 / 20 | 从专业要求多读“统计学” |
| visual_tools_intern | 13/14 | 0 / 20 | 最低学历把“大专或本科及以上”读为本科 |

七项检查唯一差异为 frontend/ops 的学历：人工最低本科，ops 本科应 match；解析成硕士后为 conflict。该组已有天数、月数和地点冲突，所以总结论仍为 ineligible。visual 的两份档案都高于两个学历门槛，过滤状态未变。

这些是冻结前后独立留下的基线差异，不修改期望。专业名称多读以及学历“或”的解释留给规划者裁定；缺失词记录为词表覆盖差距。H16 对照时要区分原有问题与新增退步，不把基线缺陷写成 H16 新引入。

H16 PR 尚未开出，因此没有读取其代码，没有填写实现字段名或报告其结果；本分支保持本地。后续只新增对照，不修改 `oracle-manifest.json` 所列文件。
