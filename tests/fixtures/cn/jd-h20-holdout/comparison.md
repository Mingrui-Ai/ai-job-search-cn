# V10 · H20 留出样例对照（PR #79）

对照冻结基线 `c6055cc7aee16ce0ca956e948c3c654e1ae40334` 与 [#79](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/79) 的 `1a64eacaf6bb1f0f73449a1c368d1770a3fb2a47`。**本批 H20 的目标项通过：4 处备选学历误读、4 处专业词多读均修正，“最低本科＋优先硕士”及正向技能控制例不变；未发现新增回退。** 旧字段整体为 67/70，剩余 3 处漏读属于冻结基线已有问题，按两项存量 P2 单列，不算 #79 新增缺陷。

这不是 #79 的合并建议。[Codex B 的独立实现审核](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/79#issuecomment-6516586031)另报两项 P2：博士研究生备选学历误降、专业基础知识和专业版表达里的技能误删。这些句式不在 V10 的冻结样例里，不混入本批分母，也不能因 V10 通过而忽略。

5 份原创虚构 JD（4 份非技术、1 份技术）和人工期望在 `6263566` 冻结，旧基线在 `7723a5d` 保存。冻结清单 LF SHA-256 仍为 `4c0a3dc79bd98532124b7c12c29bc3a4601cf800e7adbddf504cde3c88ec99c2`，12 个清单内输入均未变；冻结清单、原基线及旧运行入口也原样保留。本轮没有使用真实岗位或个人数据。

## 汇总与口径

| 指标 | 冻结 master 基线 | #79 原始解析 | #79 人工字段回放 |
| --- | ---: | ---: | ---: |
| 原有 14 字段组 × 5 份一致 | 61/70 | 67/70 | 按冻结人工值输入 |
| 本轮仅漏读 / 仅多读 / 读错的字段组 | 见基线明细 | 3 / 0 / 0 | — |
| 最低与优先学历对象一致 | 1/5 | 5/5 | 5/5 |
| 技能原文词项命中 | 10/12 | 10/12 | 按冻结人工值输入 |
| 技能漏读 / 多读 | 2 / 4 | 2 / 0 | — |
| 原有七项硬条件状态一致 | 66/70 | 70/70 | 70/70 |
| 总结论一致 | 8/10 | 10/10 | 10/10 |
| 人工记录校验 / 保存 | 5/5、5/5 | — | 5/5、5/5 |
| 非空旧字段组出处逐字存在 | 本轮不重计 | 60/60 | 使用冻结引文 |

“字段组”沿用冻结的 14 项，不拆分学历对象的 min/preferred 来抬高分母。技能按 NFKC、大小写和空白归一后比较集合，专业词多读和正向技能漏读分别计数。4 个学历对象和4 个技能集合的输出发生变化；其中两组技能仍缺“统计分析”，所以完全一致的字段只增加 6 组。其余 62 个旧字段组与基线相同，包含仍未修复的薪资漏读。

新版本比冻结时多了面试和到岗日期两项检查。本批 5 份 JD 的 `interview`、`requirements.start` 都为 null；10 组原始过滤及 10 组人工回放中，两项均为 unknown，按现行 M2-6c 契约不单独降低总结论。它们另存观察结果，不混入原有 70 项硬条件分母，也不回填冻结期望。

## 逐份学历与技能

| 样例 | 冻结最低 / 优先学历 | 旧解析 → #79 | #79 技能 | 字段一致及结论 |
| --- | --- | --- | --- | --- |
| `data_platform_intern` | bachelor / master | 保持 bachelor / master | Python、SQL | 13/14 → 14/14；去掉只在专业段出现的统计学，逗号后的 Python/SQL 保留 |
| `market_planning_campus` | bachelor / null | null → bachelor / null | 统计学、SPSS、Excel | 12/14 → 13/14；“硕士或本科均可”取本科，能力段再次出现的统计学保留；仍漏月薪 |
| `operations_analysis_intern` | bachelor / null | master / null → bachelor / null | Python、Excel | 12/14 → 13/14；去掉专业统计学，保留同句 Python/Excel；仍漏正向统计分析 |
| `service_quality_intern` | associate / null | bachelor / null → associate / null | Excel、客户沟通 | 12/14 → 14/14；“大专/本科及以上”取大专；专业段后的技能要求保留 |
| `statistics_research_intern` | bachelor / null | master / null → bachelor / null | Excel | 12/14 → 13/14；“本科或硕士在读，两个层次均可”取本科；仍漏能力段统计分析 |

学历顺序反转、斜线、或、最低加优先四类写法均有原文样例；不会把“本科及以上，硕士优先”错误降成两个备选学历。专业里的“统计学”从 4 份不要求该项能力的 JD 中移除，市场策划的“具备统计学基础”仍被保留，没有因为另一个专业句出现同词而全部删除。

除上述差异，岗位标题、公司、城市、工作方式、岗位类型、届别、每周天数、实习时长、发布日期和截止日均按冻结对照保持。“每周五”未变成每周 5 天，“试用期3个月”未变成实习时长；薪资除下述存量漏读外没有新增变化。

## 过滤影响

| 样例 × 档案 | 旧学历检查 → #79 | 旧总结论 → #79 | 冻结人工期望 |
| --- | --- | --- | --- |
| 问卷研究 × ops | conflict → match | ineligible → eligible | eligible |
| 市场策划 × ops | unknown → match | needs_check → eligible | eligible |
| 市场策划 × tech | unknown → match | ineligible → ineligible | ineligible，其他硬条件仍冲突 |
| 经营分析 × ops | conflict → match | ineligible → ineligible | ineligible，地点仍冲突 |

其余 6 组的原有状态及总结论都不变。服务质量从本科修正到大专，对两个本科及以上的示例档案不会改变总结论，仍须通过字段级对照验证，不能以总结论无变化代替学历验收。

5 条人工岗位记录仅覆盖冻结的 14 个字段及其原文出处，在另一独立库中校验、保存并用两份档案过滤。5/5 校验与保存、10/10 总结论、70/70 原有状态通过；没有修改 JD 原文、冻结期望或档案原有偏好。

## 剩余问题（均为存量，非 #79 新增）

### P2-1 · 明确能力要求中的“统计分析”仍漏读（2 处）

- `statistics_research_intern.txt`：“能力要求：熟悉统计分析方法，能用Excel整理调研表。”冻结技能为统计分析、Excel，#79 只有 Excel。
- `operations_analysis_intern.txt`：“统计学或经济学相关专业，熟悉Python、Excel，能使用统计分析方法解释问卷数据。”冻结技能为 Python、Excel、统计分析，#79 只有 Python、Excel。

这两处漏读在原始基线已经存在。H20 正确移除了专业“统计学”，但没有补出能力“统计分析”；不能把移除多读的词当成满足全部技能，也不能从冻结期望中删除漏掉的词。建议规划者另排技能识别问题；可能影响后续技能匹配，本轮没有用完整评分量化其影响。

### P2-2 · 明确的月薪区间仍为 null（1 处）

`market_planning_campus.txt`：“薪资：9000-11000元/月。”冻结值为 `min=9000, max=11000, unit=CNY/month, months=null, negotiable=false`，原基线与 #79 均为 null。学历已修复不代表薪资信息完整；这项可能影响薪资比较，建议规划者另排解析修复。

两项共 3 处漏读，没有剩余多读或读错；本批未发现 P1、P3 或 #79 新增的 P2。不依据此小批样例对 #79 全部新语法、旧岗位重新导入或既有技能列表清空行为作覆盖承诺，也不代替实现审核。

规划者已在 [#79 裁定](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/79#issuecomment-6516562307)同意版本号维持 5、作者声明的额外识别口径以及重导入时沿用 H22 的明确清空规则。本报告不扩张这些已定范围，存量漏读留给规划者另行安排。

## 证据、运行与验证

- [冻结基线](actual/master-c6055cc/summary.json)、[本轮汇总](actual/pr79-1a64eac/summary.json)、[35 次 CLI 调用记录](actual/pr79-1a64eac/commands.json)。同目录每份 JSON 保存 parse/filter、逐字段 expected/actual、原文出处和人工回放。
- 公共 CLI 于 **2026-10-30 06:30:45–06:30:55 UTC** 运行，Python 3.12.15；35 次调用全部退出 0，无 stderr。目标检出位于本验证者仓库外的独立 worktree，运行前后目标 HEAD、应用/工具字节及跟踪文件状态未变。没有将实现分支合入本报告 PR。
- tech/ops 档案从清单指定的旧提交读取并核对 LF 哈希；只在临时副本加入 M2-6b 必需的 `availability.acceptable_cities=[]`。逐项断言其他值完全相同，并且适配结果等于 #79 的公开示例档案。不会改冻结来源文件或拿新偏好替换旧偏好。
- 对照入口为 [run_comparison.py](run_comparison.py)，拒绝覆盖已有结果。先在仓库外检出目标提交，再运行：`python tests/fixtures/cn/jd-h20-holdout/run_comparison.py --target 1a64eacaf6bb1f0f73449a1c368d1770a3fb2a47 --source <目标检出目录> --label <全新结果名>`。使用 conda `ai-job-search-cn`；所有读写库命令显式指定独立 data-dir。
- 独立性沿用冻结 README：期望先于运行写定，未读取 H20 实现来编写。本轮按公共 CLI 输出对照；此前隐私扫描只在机器内部匹配代码字符串，未向验证会话展示解析实现。
- 两边的 lint、安全守卫通过；报告分支全量 1300 项、#79 原提交全量 1301 项，均 OK（12 skipped）。已合入最新 `origin/master@264a279`，`git diff --check` 通过；细节见[工作记录](../../../../docs/cn/worklog/2026-10-30-v10-h20-comparison.md)。
