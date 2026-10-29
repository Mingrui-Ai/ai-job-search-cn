# V7 · M2-4a 留出样例：master 基线

5 份原创虚构 JD、2 份公开示例档案。人工期望在运行前冻结，采用 M2-4a 的新契约。本报告只记录收尾前的基线，不能据此声称 M2-4a 已通过。

- 代码：`0e35b4bbb47630f315e5ec89d2635161560bf8b4`（当时最新 master）。
- 冻结提交：`4e47853f00f530c44a45b3cc5c6641262d50a705`；manifest SHA-256：`7d468f60aa423108f5c89f0c21a0503c87c21d18d7f029dc3e3b3a147a6ceb85`。
- 首次运行：2026-10-28T09:46:02.238972+00:00 至 2026-10-28T09:46:07.422845+00:00；Python 3.12.15。
- 正文、期望的 10 个哈希在运行前后及冻结 Git blob 中一致；参考契约与示例档案未改。
- 运行方式：公开 CLI；没有读取解析/匹配源码或 H9/M2-4a 分支，也没有修改期望。

## 汇总

| 项目 | master 基线 |
| --- | --- |
| 字段组 | 65/70 一致；4 组漏读、1 组误读、0 组纯多读 |
| 技能词项 | 12/15 读出；漏读 3 次（PPT 两次、客户沟通一次），多读 0 |
| 规则解析后过滤的总判断 | 9/10 一致 |
| 规则解析后过滤的七项状态 | 56/70 一致 |
| 人工字段回放 | 3/5 记录通过旧 Schema 校验；可运行部分总判断 6/6、状态 40/42 一致 |

14 处状态差异全部对应新契约：10 处应为 not_applicable 的检查仍 unknown，4 处明确学历不限仍 unknown。唯一总判断差异为客户服务校招 / ops，应 eligible，实际 needs_check。该岗位截止日期的额外误读不参与当前硬性过滤。

## 字段组

| 字段 | 一致 / 5 |
| --- | --- |
| `title` | 5/5 |
| `company` | 5/5 |
| `cities` | 5/5 |
| `remote` | 5/5 |
| `employment_type` | 5/5 |
| `salary` | 5/5 |
| `requirements.graduation` | 5/5 |
| `requirements.days_per_week` | 5/5 |
| `requirements.min_months` | 5/5 |
| `requirements.education` | 3/5 |
| `requirements.skills` | 3/5 |
| `return_offer` | 5/5 |
| `published_at` | 5/5 |
| `deadline` | 4/5 |

所有不一致如下；其余 65 组相同。

| 岗位 | 字段 | 人工期望 | 实际 | 类型 |
| --- | --- | --- | --- | --- |
| 供应商协调实习 | `requirements.skills` | `["Excel", "PPT", "商务沟通"]` | `["Excel", "商务沟通"]` | missing |
| 语言应用社招 | `requirements.education` | `{"min": "none", "preferred": null}` | `null` | missing |
| 客户服务校招 | `requirements.education` | `{"min": "none", "preferred": null}` | `null` | missing |
| 客户服务校招 | `requirements.skills` | `["Excel", "PPT", "客户沟通"]` | `["Excel"]` | missing |
| 客户服务校招 | `deadline` | `"2026-12-15"` | `"2026-10-28"` | wrong |

Golang、K8s、NLP 在已读出的技能中保持了正文拼写；两处 PPT 未读出。专业不限正确保持学历未知，本科及以上、优秀者可放宽仍正确识别为本科。客户服务岗位的试用期没有被当作实习月数。

截止日期被读成发布日期（2026-10-28，人工为 2026-12-15）。这是额外发现，单独登记，不把它归因于 none/not_applicable 新契约；待实现分支重跑后由规划者裁定。

## 总判断与七项状态

向量顺序固定为：届别、学历、每周天数、实习月数、地点、岗位类型、排除项。M=match，C=conflict，U=unknown，N=not_applicable。

| 岗位 / 档案 | 人工总判断 | master 总判断 | 人工七项 | master 七项 |
| --- | --- | --- | --- | --- |
| 内容编辑实习 / tech | needs_check | needs_check | M M U M M M M | M M U M M M M |
| 内容编辑实习 / ops | needs_check | needs_check | M M U M M M M | M M U M M M M |
| 供应商协调实习 / tech | eligible | eligible | M M M M M M M | M M M M M M M |
| 供应商协调实习 / ops | ineligible | ineligible | M M C M C M M | M M C M C M M |
| 语言应用社招 / tech | ineligible | ineligible | U M N N M C M | U U U U M C M |
| 语言应用社招 / ops | ineligible | ineligible | U M N N C C M | U U U U C C M |
| 后端开发校招 / tech | ineligible | ineligible | M U M N M C M | M U M U M C M |
| 后端开发校招 / ops | needs_check | needs_check | M U M N M M M | M U M U M M M |
| 客户服务校招 / tech | ineligible | ineligible | M M N N C C M | M U U U C C M |
| 客户服务校招 / ops | eligible | needs_check | M M N N M M M | M U U U M M M |

| 检查项 | 一致 / 10 |
| --- | --- |
| `graduation` | 10/10 |
| `education` | 6/10 |
| `days_per_week` | 6/10 |
| `min_months` | 4/10 |
| `location` | 10/10 |
| `employment_type` | 10/10 |
| `exclusions` | 10/10 |

实习未写每周天数仍为 unknown，校招显式要求的每周实习 3 天仍正常比较；这两处边界目前与人工期望一致。

## 人工字段回放与旧 Schema 限制

将人工字段覆盖到独立记录并用 CLI 校验；校验成功才保存和过滤。2 份包含 `education.min: "none"` 的记录被当前 master 拒绝，因此没有回放这 4 组匹配，不能把它们计成通过或过滤失败。原始解析记录的 10 组主基线全部运行。

- 语言应用社招：`"requirements.education.min: must be one of associate, bachelor, master, phd or null"`
- 客户服务校招：`"requirements.education.min: must be one of associate, bachelor, master, phd or null"`

| 可回放岗位 / 档案 | master 总判断 | master 七项 |
| --- | --- | --- |
| 内容编辑实习 / tech | needs_check | M M U M M M M |
| 内容编辑实习 / ops | needs_check | M M U M M M M |
| 供应商协调实习 / tech | eligible | M M M M M M M |
| 供应商协调实习 / ops | ineligible | M M C M C M M |
| 后端开发校招 / tech | ineligible | M U M U M C M |
| 后端开发校招 / ops | needs_check | M U M U M M M |

可回放部分仅后端校招的月数两项有差异（unknown 对 not_applicable），其余 40 项一致。

## 复现与验证

在隔离数据目录中，按每份 expected.json 的 site_argument 执行以下公开命令，并分别以 tech/ops profile.json 调用过滤。不要用个人岗位库。

```text
python -m jobsearch_cn jd parse <fixture.txt> --site <site_argument> --save --data-dir <isolated-dir>
python -m jobsearch_cn jd validate <isolated-dir>/jobs/<job_id>.json
python -m jobsearch_cn match filter <job_id> --profile tests/fixtures/cn/profile/<tech|ops>/profile.json --data-dir <isolated-dir>
```

- 原始 CLI 输出、字段/检查对照：[actual/master/](actual/master/)；计数：[summary.json](actual/master/summary.json)。
- [verification.json](verification.json)记录独立复计、冻结时间顺序、Git blob 和原始输出哈希。
- 提交前 lint_skills、security_guards 通过；全量 1028 项（1019 通过、9 跳过，145.933 秒）。这不是将 V7 接入现有测试后的通过率；新契约差距由本报告单独保存。
- 仅本目录 .txt/.json/.md 强制 LF，以避免 Windows 检出换行破坏冻结与报告字节哈希。

## 后续

本分支保持本地，不推送、不打开 PR。M2-4a PR 开出并收到通知后，用其代码重跑同一批冻结样例和档案，比较字段组、总判断、七项状态及前后变化，再开 PR。V6 仍等待 H9；V5 #29 保持不动。
