# V6 · H9 留出样例对照

本轮运行 PR #34（`feat/cn-h9-boss-paste`）的 head **`19292e9b6642b0fb7761b8772a7b32e30e16122a`**，时间 2026-10-28T11:07:08.069740+00:00 至 2026-10-28T11:07:13.263579+00:00。基线为 master `737c1f00ebb1c50a5fac0bedb977cb4c58ba472a`，冻结提交 `4d5084a52f7c78ff5febd31c9be448b6a3c52ace`。

5 份原创虚构 JD、人工字段和匹配期望均保持冻结原样。使用独立工作树运行公开 CLI，未读取 H9 的解析源码；冻结的 tech/ops 档案也未改变。这里只比较输出，不按结果回填期望。

## 汇总

| 指标 | 基线 | H9 head |
| --- | --- | --- |
| 字段严格一致 | 50/70 | 61/70 |
| 按 H9 口径留空 | 0/2 | 2/2 |
| 严格一致加按口径留空 | 50/70 | 63/70 |
| 字段漏读 / 误读 / 纯多读 | 16 / 4 / 0 | 7 / 0 / 0 |
| 技能读出 / 漏读 / 多读 | 9/15 / 6 / 11 | 15/15 / 0 / 0 |
| 原始解析后总判断对人工真值 | 4/10 | 2/10 |
| 原始解析后七项状态对人工真值 | 46/70 | 54/70 |
| 双时长样例对冻结的留空后预期 | 1/4；24/28 | 4/4；28/28 |
| 人工字段回放 | 10/10；70/70 | 10/10；70/70 |

严格一致数上升 11 项；两处双时长不再误取 3 个月，而是按 H9 要求留空。技能漏读和多读清零。总判断与人工真值的一致数下降 2 项，发生在测试开发/tech、招聘协调/tech：原来的 eligible 因月数留空变成 needs_check，符合冻结的留空后预期。不能把这两项称为匹配规则退步，也不能把留空算作读出了人工真值 4 个月。

## 字段组及剩余差距

| 字段组 | 基线一致 / 5 | H9 一致 / 5 |
| --- | --- | --- |
| `title` | 2 | 5 |
| `company` | 2 | 4 |
| `cities` | 3 | 3 |
| `remote` | 5 | 5 |
| `employment_type` | 5 | 5 |
| `salary` | 5 | 5 |
| `requirements.graduation` | 5 | 5 |
| `requirements.days_per_week` | 5 | 5 |
| `requirements.min_months` | 0 | 2 |
| `requirements.education` | 2 | 2 |
| `requirements.skills` | 1 | 5 |
| `return_offer` | 5 | 5 |
| `published_at` | 5 | 5 |
| `deadline` | 5 | 5 |

| 样例 | 字段 | 人工真值 | 基线实际 | H9 实际 | 分类 |
| --- | --- | --- | --- | --- | --- |
| 招聘协调 | `requirements.min_months` | `4` | `3` | `null` | policy_blank |
| 会务整页 | `company` | `"示例帆橙会务社"` | `null` | `null` | missing |
| 会务整页 | `requirements.min_months` | `3` | `null` | `null` | missing |
| 会务整页 | `requirements.education` | `{"min": "bachelor", "preferred": null}` | `null` | `null` | missing |
| 财务标签 | `cities` | `["上海"]` | `[]` | `[]` | missing |
| 财务标签 | `requirements.education` | `{"min": "bachelor", "preferred": null}` | `null` | `null` | missing |
| 前端标签 | `cities` | `["广州"]` | `[]` | `[]` | missing |
| 前端标签 | `requirements.education` | `{"min": "bachelor", "preferred": null}` | `null` | `null` | missing |
| 测试开发 | `requirements.min_months` | `4` | `3` | `null` | policy_blank |

剩余 7 组漏读集中在粘贴标签：前端、财务的城市及学历各两组；整页会务的公司、实习月数、学历三组。标题 3/3 已识别，标签样例公司及月数各 2/3 已识别。无新增字段误读或多读；这 7 项需规划者按 H9 验收口径裁定。

## 总判断和七项状态

顺序：届别、学历、每周天数、月数、地点、类型、排除项。M=match，U=unknown，C=conflict。

| 样例/档案 | 人工总判断 | 基线总判断 | H9 总判断 | 人工七项 | 基线七项 | H9 七项 |
| --- | --- | --- | --- | --- | --- | --- |
| 招聘协调/tech | eligible | eligible | needs_check | M M M M M M M | M M M M M M M | M M M U M M M |
| 招聘协调/ops | ineligible | eligible | needs_check | M M M C M M M | M M M M M M M | M M M U M M M |
| 会务整页/tech | eligible | needs_check | needs_check | M M M M M M M | M U M U M M U | M U M U M M M |
| 会务整页/ops | eligible | needs_check | needs_check | M M M M M M M | M U M U M M U | M U M U M M M |
| 财务标签/tech | ineligible | needs_check | needs_check | M M M M C M M | M U M U U M U | M U M M U M M |
| 财务标签/ops | eligible | needs_check | needs_check | M M M M M M M | M U M U U M U | M U M M U M M |
| 前端标签/tech | eligible | needs_check | needs_check | M M M M M M M | M U M U U M U | M U M M U M M |
| 前端标签/ops | ineligible | ineligible | ineligible | M M C C C M M | M U C U U M U | M U C C U M M |
| 测试开发/tech | eligible | eligible | needs_check | M M M M M M M | M M M M M M M | M M M U M M M |
| 测试开发/ops | ineligible | ineligible | ineligible | M M C C C M M | M M C M C M M | M M C U C M M |

| 检查项 | 基线一致 / 10 | H9 一致 / 10 |
| --- | --- | --- |
| `graduation` | 10 | 10 |
| `education` | 4 | 4 |
| `days_per_week` | 10 | 10 |
| `min_months` | 2 | 4 |
| `location` | 6 | 6 |
| `employment_type` | 10 | 10 |
| `exclusions` | 4 | 10 |

## 留空策略单列

两个多时长字段的人工作业真值仍为 4，规则期望为 null。H9 的 4 组下游结果全部符合冻结的 policy_blank_match；人工字段补全后，10 组总判断和 70 项状态全部正确。

| 样例/档案 | 留空后预期 | H9 实际 | 七项一致 |
| --- | --- | --- | --- |
| 招聘协调/tech | needs_check | needs_check | 7/7 |
| 招聘协调/ops | needs_check | needs_check | 7/7 |
| 测试开发/tech | needs_check | needs_check | 7/7 |
| 测试开发/ops | ineligible | ineligible | 7/7 |

## 复现和更新

原始输出见 [actual/h9-19292e9/](actual/h9-19292e9/)，基线见 [master-baseline.md](master-baseline.md)。冻结文件/Git blob 哈希与原始输出复计见 [comparison-verification.json](comparison-verification.json)。

每份用独立数据目录执行 jd parse --save、jd validate；分别以冻结 tech/ops 档案执行 match filter。再将人工字段另存到另一隔离岗位库，validate/save/filter 回放。未访问 JD 里的占位链接。

PR #34 如有新 head，新增对应 actual/h9-<head>/ 输出并更新本报告，保留已有运行记录，不覆盖旧结果或修改人工期望。
