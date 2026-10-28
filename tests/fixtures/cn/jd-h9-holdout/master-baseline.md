# V6 · master 基线

代码提交 `737c1f00ebb1c50a5fac0bedb977cb4c58ba472a`；输入冻结提交 `4d5084a52f7c78ff5febd31c9be448b6a3c52ace`。首次运行时间 2026-10-28T08:55:26.201626+00:00 至 2026-10-28T08:55:32.820452+00:00。

本报告只记录当前master，不代表H9分支验收。冻结期望未回填，未读取解析源码或H9分支。

三份BOSS版式均漏读标题、公司和实习月数，且漏读标签学历；其中两份只在标签写城市，也漏读城市。双时长样例均误取平台3个月，招聘协调对ops因此从人工ineligible误判为eligible。人工字段单独回放全部符合期望，表明这些匹配差异来自解析输入的信息缺失或错误，不能据此说过滤规则本身错误。

| 指标 | 数值 |
| --- | --- |
| 字段组严格符合人工真值 | 50/70 |
| 按口径留空（单独计数） | 0 |
| 真值符合 + 按口径留空 | 50/70 |
| 仅漏读 / 仅多读 / 错误或漏多并存 | 16 / 0 / 4 |
| 两个不同时长字段遵循H9留空策略 | 0/2 |
| 解析结果的总判断 / 七项状态符合人工真值 | 4/10、46/70 |
| 人工字段回放的总判断 / 七项状态 | 10/10、70/70 |
| 双时长样例的解析结果符合预先写定的留空后判断 / 状态 | 1/4、24/28 |
| 正向技能命中 / 漏读 / 多读 | 9/15、6、11 |

严格真值与H9策略是两个口径：双时长字段输出null为“按口径留空”，不计误读；输出4是人工真值一致，但仍需单列未按H9留空；输出3为误读。下游unknown必须保留，不能冒充满足条件。

## 逐份字段差异

| 样例 | 一致 | 按口径留空 | 漏读 | 多读 | 错误 |
| --- | --- | --- | --- | --- | --- |
| 招聘/双时长 | 12 | 0 | 0 | 0 | 2 |
| 会务整页 | 9 | 0 | 5 | 0 | 0 |
| 财务标签 | 8 | 0 | 6 | 0 | 0 |
| 前端标签 | 9 | 0 | 5 | 0 | 0 |
| 测试/双时长 | 12 | 0 | 0 | 0 | 2 |

| 样例 | 字段 | 人工真值 | 规则输出 | 分类 |
| --- | --- | --- | --- | --- |
| 招聘/双时长 | requirements.min_months | 4 | 3 | wrong |
| 招聘/双时长 | requirements.skills | ["Excel","PowerPoint","招聘流程"] | ["Excel","SQL","Python","剪映","小红书","抖音","公众号"] | wrong |
| 会务整页 | title | "会务协调实习生" | null | missing |
| 会务整页 | company | "示例帆橙会务社" | null | missing |
| 会务整页 | requirements.min_months | 3 | null | missing |
| 会务整页 | requirements.education | {"min":"bachelor","preferred":null} | null | missing |
| 会务整页 | requirements.skills | ["Excel","活动策划","商务沟通"] | ["Excel","活动策划"] | missing |
| 财务标签 | title | "财务助理实习生（费用核对）-【上海】" | null | missing |
| 财务标签 | company | "示例杉汀商行" | null | missing |
| 财务标签 | cities | ["上海"] | [] | missing |
| 财务标签 | requirements.min_months | 3 | null | missing |
| 财务标签 | requirements.education | {"min":"bachelor","preferred":null} | null | missing |
| 财务标签 | requirements.skills | ["Excel","PowerPoint","财务分析"] | ["Excel"] | missing |
| 前端标签 | title | "前端开发实习生（应用界面）-【广州】" | null | missing |
| 前端标签 | company | "示例棠原工作室" | null | missing |
| 前端标签 | cities | ["广州"] | [] | missing |
| 前端标签 | requirements.min_months | 6 | null | missing |
| 前端标签 | requirements.education | {"min":"bachelor","preferred":null} | null | missing |
| 测试/双时长 | requirements.min_months | 4 | 3 | wrong |
| 测试/双时长 | requirements.skills | ["Python","Postman","Git"] | ["Python","Git","Java","C++","Photoshop","小红书","公众号"] | wrong |

## 总判断与七项检查

顺序固定为届别、学历、天数、月数、地点、类型、排除项。M=match，C=conflict，U=unknown。人工列按真实岗位要求，未用平台介绍替代岗位月数。

| 样例 | 档案 | 人工总判断 | 实际总判断 | 人工七项 | 实际七项 |
| --- | --- | --- | --- | --- | --- |
| 招聘/双时长 | tech | eligible | eligible | M M M M M M M | M M M M M M M |
| 招聘/双时长 | ops | ineligible | eligible | M M M C M M M | M M M M M M M |
| 会务整页 | tech | eligible | needs_check | M M M M M M M | M U M U M M U |
| 会务整页 | ops | eligible | needs_check | M M M M M M M | M U M U M M U |
| 财务标签 | tech | ineligible | needs_check | M M M M C M M | M U M U U M U |
| 财务标签 | ops | eligible | needs_check | M M M M M M M | M U M U U M U |
| 前端标签 | tech | eligible | needs_check | M M M M M M M | M U M U U M U |
| 前端标签 | ops | ineligible | ineligible | M M C C C M M | M U C U U M U |
| 测试/双时长 | tech | eligible | eligible | M M M M M M M | M M M M M M M |
| 测试/双时长 | ops | ineligible | ineligible | M M C C C M M | M M C M C M M |

## 时长策略与隔离回放

| 样例 | 人工月数 | 规则月数 | H9规则期望 | 遵循策略 |
| --- | --- | --- | --- | --- |
| 招聘/双时长 | 4 | 3 | null | 否 |
| 测试/双时长 | 4 | 3 | null | 否 |

预先冻结的policy_blank_match表示其他字段正确且月数留空时的理想下游结果；4个总判断、28项状态的辅助对照不替换主指标10/70。原始parse记录另存，人工字段只写入独立临时存储回放，两个存储互不覆盖。

## 验证与下一步

- 10个JD/期望及契约/档案哈希运行前后不变；69处逐字出处已核对。所有本批parse/filter/validate成功。
- lint_skills、security_guards通过；全量1023项测试，9项跳过，其余通过（215.237秒）。
- [机器汇总](actual/master/summary.json)保留全部字段差异和检查状态；同目录逐份JSON保留CLI输出。输出快照哈希另存于verification.json。
- 此阶段不推送、不开PR。H9 PR开出后，绑定其提交重跑同一冻结输入，另存结果并写前后对照，再开数据PR。V5不修改。
