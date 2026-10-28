# V7 · M2-4a 留出样例对照

5 份原创虚构 JD、10 组人工过滤判断在运行前冻结。本报告重跑用户指定的已合并 M2-4a，不含 H12 修复。

- 本次代码：`a337796d4d7a8bf81b469a768342cb60efede63e`（master，M2-4a PR #38 的合并提交）。
- 基线代码：`0e35b4bbb47630f315e5ec89d2635161560bf8b4`；冻结提交：`4e47853f00f530c44a45b3cc5c6641262d50a705`。
- manifest SHA-256：`7d468f60aa423108f5c89f0c21a0503c87c21d18d7f029dc3e3b3a147a6ceb85`。
- 完整运行：2026-10-28T12:11:04.217372+00:00 至 2026-10-28T12:11:10.045575+00:00；Python 3.12.15。
- 独立工作树固定到上述代码；公开 CLI 解析、校验、保存、过滤，使用隔离 data 目录。JD、人工期望、manifest 和旧基线输出均未修改。

## 汇总

| 项目 | 原 master 基线 | M2-4a | 变化 |
| --- | --- | --- | --- |
| 字段组一致 | 65/70 | 68/70 | +3；剩 1 组漏读、1 组误读 |
| 总判断一致 | 9/10 | 10/10 | +1 |
| 七项检查状态一致 | 56/70 | 70/70 | +14 |
| 技能词项 | 12/15 | 14/15 | 补读 2 次 PPT；仍漏客户沟通，多读 0 |
| 人工字段记录通过校验 | 3/5 | 5/5 | none 不再被 Schema 拒绝 |
| 人工字段回放 | 总判断 6/6、状态 40/42 | 总判断 10/10、状态 70/70 | 可回放范围扩大，分母不同 |

结果与规划者告知的 68/70、10/10、70/70 一致。数字由原始 CLI 输出独立复计，不以规划者数字作为生成输入，也没有按结果回填期望。

## 字段组及剩余差异

| 字段 | 原基线 / 5 | M2-4a / 5 |
| --- | --- | --- |
| `title` | 5/5 | 5/5 |
| `company` | 5/5 | 5/5 |
| `cities` | 5/5 | 5/5 |
| `remote` | 5/5 | 5/5 |
| `employment_type` | 5/5 | 5/5 |
| `salary` | 5/5 | 5/5 |
| `requirements.graduation` | 5/5 | 5/5 |
| `requirements.days_per_week` | 5/5 | 5/5 |
| `requirements.min_months` | 5/5 | 5/5 |
| `requirements.education` | 3/5 | 5/5 |
| `requirements.skills` | 3/5 | 4/5 |
| `return_offer` | 5/5 | 5/5 |
| `published_at` | 5/5 | 5/5 |
| `deadline` | 4/5 | 4/5 |

| 样例方向 | 原基线 / 14 | M2-4a / 14 |
| --- | --- | --- |
| 内容编辑实习 | 14/14 | 14/14 |
| 供应商协调实习 | 13/14 | 14/14 |
| 语言应用社招 | 13/14 | 14/14 |
| 后端开发校招 | 14/14 | 14/14 |
| 客户服务校招 | 11/14 | 12/14 |

仅剩以下两组不一致；都属于客户服务校招样例，均是旧基线已有差距。

| 字段 | 人工期望 | M2-4a 实际 |
| --- | --- | --- |
| `requirements.skills` | `["Excel", "PPT", "客户沟通"]` | `["Excel", "PPT"]` |
| `deadline` | `"2026-12-15"` | `"2026-10-28"` |

这两项已由用户转入 H12 PR #40：截止日期不跨行、market 增加客户沟通。它们不参与当前七项硬性过滤，因此没有影响本次 10/10 总判断与 70/70 状态。本报告没有用 H12 重跑后覆盖 M2-4a 的输出，也不据此声称两处修复已在 V7 验证。

## 总判断与七项状态

向量顺序：届别、学历、每周天数、实习月数、地点、岗位类型、排除项。M=match，C=conflict，U=unknown，N=not_applicable。

| 方向 / 档案 | 人工总判断 | 原基线 | M2-4a | 人工七项 | 原基线七项 | M2-4a 七项 |
| --- | --- | --- | --- | --- | --- | --- |
| 内容编辑实习 / tech | needs_check | needs_check | needs_check | M M U M M M M | M M U M M M M | M M U M M M M |
| 内容编辑实习 / ops | needs_check | needs_check | needs_check | M M U M M M M | M M U M M M M | M M U M M M M |
| 供应商协调实习 / tech | eligible | eligible | eligible | M M M M M M M | M M M M M M M | M M M M M M M |
| 供应商协调实习 / ops | ineligible | ineligible | ineligible | M M C M C M M | M M C M C M M | M M C M C M M |
| 语言应用社招 / tech | ineligible | ineligible | ineligible | U M N N M C M | U U U U M C M | U M N N M C M |
| 语言应用社招 / ops | ineligible | ineligible | ineligible | U M N N C C M | U U U U C C M | U M N N C C M |
| 后端开发校招 / tech | ineligible | ineligible | ineligible | M U M N M C M | M U M U M C M | M U M N M C M |
| 后端开发校招 / ops | needs_check | needs_check | needs_check | M U M N M M M | M U M U M M M | M U M N M M M |
| 客户服务校招 / tech | ineligible | ineligible | ineligible | M M N N C C M | M U U U C C M | M M N N C C M |
| 客户服务校招 / ops | eligible | needs_check | eligible | M M N N M M M | M U U U M M M | M M N N M M M |

| 检查项 | 原基线 / 10 | M2-4a / 10 |
| --- | --- | --- |
| `graduation` | 10/10 | 10/10 |
| `education` | 6/10 | 10/10 |
| `days_per_week` | 6/10 | 10/10 |
| `min_months` | 4/10 | 10/10 |
| `location` | 10/10 | 10/10 |
| `employment_type` | 10/10 | 10/10 |
| `exclusions` | 10/10 | 10/10 |

4 项明确学历不限由 unknown 变 match；10 项未写明的校招/社招实习条件由 unknown 变 not_applicable。客户服务校招 / ops 的总判断由 needs_check 变 eligible。实习缺失天数仍 unknown，校招明确要求的每周实习 3 天仍正常比较，专业不限仍不是学历不限。

## 档案版本与独立性

初次尝试直接使用冻结旧档案时，M2-4a 校验报告缺少 target.directions 和 target.weights，未形成任何完整样例输出。没有修改冻结档案或绕过校验；完整对照采用 a337796 自带的 tech/ops 示例档案。两份档案仅新增 target.directions（分别为 tech、ops）和 target.weights=null，移除这两个新增字段后与冻结档案逐值完全一致；七项硬性过滤所用字段均未变。运行档案的来源提交及哈希见审计文件。

正文、人工期望和冻结 manifest 仍与冻结 Git blob 逐字节一致。冻结时的参考文档与旧档案在隔离输入目录核对原哈希（必要时恢复 Windows CRLF），没有覆盖运行代码的文档或档案。

独立性仅描述编写与冻结阶段：此前源码先验已在 manifest 披露；冻结后本 Agent 承担 H11/H12 并阅读、修改了解析实现，本次不再声称从未看过源码。人工期望保持冻结，重跑仅通过公开 CLI；另用独立计数脚本从原始输出核对字段和状态。

## 复现和审计

在独立工作树签出上述完整代码提交，取冻结提交的 5 份 txt、expected.json、manifest，配合该代码提交的两份示例档案。所有命令使用隔离 data 目录：

```text
python -m jobsearch_cn jd parse <fixture.txt> --site <site_argument> --save --data-dir <isolated-dir>
python -m jobsearch_cn jd validate <isolated-dir>/jobs/<job_id>.json
python -m jobsearch_cn match filter <job_id> --profile <a337796 的 tech/ops profile.json> --data-dir <isolated-dir>
```

技能比较按冻结口径忽略大小写、全半角和空白，不合并同义词；其余字段按原 manifest 比较。人工字段回放在另一个数据目录，先校验通过才保存和过滤。

- [原基线](baseline.md)与[原始基线输出](actual/master/)保持不变。
- [本次完整 CLI 输出](actual/m2-4a-a337796/)与[汇总](actual/m2-4a-a337796/summary.json)。
- [对照审计](comparison-verification.json)：代码、冻结材料、运行档案、原始输出及报告哈希，独立复计结果和前后计数。
- 本分支仅提交验证产物及文档；全量检查结果见本次工作记录。H12 的 V6 检验仍由规划者运行。
