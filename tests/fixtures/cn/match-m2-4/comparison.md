# V5 对照 #48（20 组完整 CLI 回放）

被测提交：`5c1445a7d2fc96263fedc4aadaa75541067aa879`。本报告仅使用仓库中虚构样例；未读取解析、评分源码或 H16 分支。完整输出与 `match list` 原始顺序见 [comparison-results.json](comparison-results.json)，独立负向复核见 [independent-review.json](independent-review.json)。

**结论：按规划者裁定，两份档案的排序验收均通过。** 20/20 过滤结论、140/140 硬性检查状态与人工一致；逐维分数并非全部相等，下文完整披露。

## 输入与冻结

- #48 的 `tests/fixtures/cn/match-m2-4c/agent-judgments.json` 在执行前核验 LF SHA-256：`9d0fe6b0ff5c89055882d4d5b1bda516b0b4ed43189727fa642544faf52c3c21`。20 份经历原样使用，不为贴合 V5 调分。
- V5 manifest 的 16 个冻结人工文件执行前后哈希一致；本报告及实际结果是新增文件，没有覆盖冻结期望。
- 每个 #48 `sample` 的原文先归一 LF，再与 V5 manifest 的 `source_files.*.lf_sha256` 唯一对应；没有用文件名猜测。两份示例档案较冻结源仅新增 `target.directions/weights`，其余字段相同；应用 `profile-overrides.json`（tech=`["tech"]`、ops=`["ops"]`、weights=null）后输入完全等价。
- 使用 #48 的实际 `jd parse --save` 输出，未用人工字段覆盖。10 份解析技能清单与 V5 人工输入一致。同义词只计一次；后端人工对照采用已裁定的技能 **43.333333**、总分 **79**，原冻结文件仍保留初版 51.428571/82。
- 隔离存储采用 `--data-dir data/v5-check/run-03/<tech|ops>`。每组依次执行 `profile validate/show`、`jd parse --save`、`jd show`、`match score --draft`，补冻结经历，`match validate`，复制错误里给出的 JSON total，再 `validate/save/show`。两份完整列表都来自 `match list`。

## 排序验收

[规划者裁定](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/48#issuecomment-6489267165)：R 为 `rankings.json` 各行 `recommended_top_k=true` 的数量；k=min(3,R)。前 k 与人工推荐集合交集至少 min(2,k)，且前 k 无人工 ineligible/poor。

| 档案 | R / k | 实际前 k | 交集 / 要求 | 人工禁入数 | 结果 |
| --- | --- | --- | --- | --- | --- |
| tech | 3 / 3 | 后端实习、测试开发实习、算法实习 | 3 / 2 | 0 | 通过 |
| ops | 2 / 2 | 内容运营实习、市场管培校招 | 2 / 2 | 0 | 通过 |

ops 的第 3 名 UI 设计仍为 ineligible，不是推荐。tech 的算法实习是 needs_check，届别需确认。

## 逐组差异

四维按技能 / 方向 / 经历 / 薪资排列；— 为 null。Δ总分 = 实际 − 人工；每张表严格按实际 `match list` 顺序。技能输出取整数，V5 保留 6 位，5 组技能差异属于展示取整：tech 后端 43 对 43.333333、tech 算法 8 对 8.333333、tech 大模型校招 39 对 38.75、ops 内容 51 对 51.428571、ops UI 13 对 13.333333。方向、薪资及技能得分信用/分母一致；总分使用规则内部的精确分数，不能拿显示整数重新算。

### tech

| 实际序 / 人工序 | 岗位 | 人工四维 | 实际四维 | 人工总分/等级 | 实际总分/等级 | Δ总分 | 过滤（两边一致） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 / 1 | 后端实习 (`boss_backend`) | 43.333333 / 100 / 95 / 100 | 43 / 100 / 85 / 100 | 79/strong | 76/strong | -3 | eligible |
| 2 / 2 | 测试开发实习 (`test_dev`) | 0 / 100 / 65 / — | 0 / 100 / 60 / — | 51/moderate | 50/moderate | -1 | eligible |
| 3 / 3 | 算法实习 (`official_algorithm`) | 8.333333 / 100 / 45 / — | 8 / 100 / 45 / — | 49/moderate | 49/moderate | +0 | needs_check |
| 4 / 4 | AI 产品实习 (`ai_product`) | 0 / 0 / 45 / 100 | 0 / 0 / 45 / 100 | 21/poor | 21/poor | +0 | eligible |
| 5 / 5 | UI 设计实习 (`ui_design`) | 0 / 0 / 15 / — | 0 / 0 / 5 / — | 4/poor | 1/poor | -3 | needs_check |
| 6 / 6 | 大模型应用校招 (`campus_llm`) | 38.75 / 100 / 85 / — | 39 / 100 / 80 / — | 72/ineligible | 71/ineligible | -1 | ineligible |
| 7 / 7 | 数据分析实习 (`data_intern`) | 25 / 100 / 45 / 100 | 25 / 100 / 50 / 100 | 60/ineligible | 61/ineligible | +1 | ineligible |
| 8 / 8 | Java 社招 (`experienced_java`) | 0 / 100 / 65 / — | 0 / 100 / 40 / — | 51/ineligible | 44/ineligible | -7 | ineligible |
| 9 / 9 | 内容运营实习 (`content_ops`) | 0 / 0 / 5 / 100 | 0 / 0 / 5 / 100 | 11/ineligible | 11/ineligible | +0 | ineligible |
| 10 / 10 | 市场管培校招 (`marketing_campus`) | 0 / 0 / 15 / — | 0 / 0 / 5 / — | 4/ineligible | 1/ineligible | -3 | ineligible |

- **后端实习**：同属后端服务开发；#48 对高并发及未证明的工具能力更保守（经历 85 对 95）。
- **测试开发实习**：都认定接口/评测经历可迁移；#48 取相关档下沿 60，V5 为 65。
- **算法实习**：经历均为 45；RAG 应用不能冒充算法研究。
- **AI 产品实习**：均为 45，只认应用开发与产品工作沾边。
- **UI 设计实习**：均在无关档；#48 为 5，V5 为 15。
- **大模型应用校招**：均在同类工作档；#48 为 80，V5 为 85。
- **数据分析实习**：均在沾边档；#48 为 50，V5 为 45。
- **Java 社招**：跨档差异：#48 强调 Java 工具链和年限不足取 40；V5 认可后端迁移取 65。两者均因硬性条件排除。
- **内容运营实习**：经历均为 5，未把技术经历算作运营经历。
- **市场管培校招**：均在无关档；#48 为 5，V5 为 15。

### ops

| 实际序 / 人工序 | 岗位 | 人工四维 | 实际四维 | 人工总分/等级 | 实际总分/等级 | Δ总分 | 过滤（两边一致） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 / 1 | 内容运营实习 (`content_ops`) | 51.428571 / 100 / 95 / — | 51 / 100 / 85 / — | 80/strong | 77/strong | -3 | eligible |
| 2 / 2 | 市场管培校招 (`marketing_campus`) | 20 / 50 / 75 / — | 20 / 50 / 70 / — | 45/moderate | 44/weak | -1 | eligible |
| 3 / 3 | UI 设计实习 (`ui_design`) | 13.333333 / 0 / 50 / — | 13 / 0 / 35 / — | 19/ineligible | 15/ineligible | -4 | ineligible |
| 4 / 5 | AI 产品实习 (`ai_product`) | 0 / 0 / 45 / — | 0 / 0 / 20 / — | 13/ineligible | 6/ineligible | -7 | ineligible |
| 5 / 4 | 数据分析实习 (`data_intern`) | 0 / 0 / 45 / — | 0 / 0 / 20 / — | 13/ineligible | 6/ineligible | -7 | ineligible |
| 6 / 9 | 测试开发实习 (`test_dev`) | 0 / 0 / 5 / — | 0 / 0 / 5 / — | 1/ineligible | 1/ineligible | +0 | ineligible |
| 7 / 6 | 后端实习 (`boss_backend`) | 0 / 0 / 10 / — | 0 / 0 / 5 / — | 3/ineligible | 1/ineligible | -2 | ineligible |
| 8 / 8 | 大模型应用校招 (`campus_llm`) | 0 / 0 / 5 / — | 0 / 0 / 5 / — | 1/ineligible | 1/ineligible | +0 | ineligible |
| 9 / 10 | Java 社招 (`experienced_java`) | 0 / 0 / 0 / — | 0 / 0 / 5 / — | 0/ineligible | 1/ineligible | +1 | ineligible |
| 10 / 7 | 算法实习 (`official_algorithm`) | 0 / 0 / 5 / — | 0 / 0 / 5 / — | 1/ineligible | 1/ineligible | +0 | ineligible |

- **内容运营实习**：均在同类工作档；#48 为 85，V5 为 95。
- **市场管培校招**：均在相关档；70 对 75 使总分跨过 45 分边界（weak 对 moderate），仍是第 2 个可投候选。
- **UI 设计实习**：跨档差异：#48 认为海报经验距 UI 工作较远取 35；V5 视为沾边取 50。均为 ineligible。
- **AI 产品实习**：跨档差异：#48 无需求/原型经历取 20；V5 认可用户接触和活动经验沾边取 45。均为 ineligible。
- **数据分析实习**：跨档差异：#48 无清洗/可视化经历取 20；V5 认可运营数据接触沾边取 45。均为 ineligible。
- **测试开发实习**：经历均为 5。
- **后端实习**：均在无关档；#48 为 5，V5 为 10。
- **大模型应用校招**：经历均为 5。
- **Java 社招**：均在无关档；#48 为 5，V5 为 0。
- **算法实习**：经历均为 5。

经历维度共 14/20 组有分差，最大绝对差 25；均保留两方理由与引用，不把分差回填到 oracle。tech 全部 10 个位置一致；ops 第 4 名以后受分差与同分顺序影响，表中逐项列出，不影响 k=2 的验收。

## 缺口与说明边界

- 20 组技能缺口在同义归一后都一致；ops 后端原冻结缺口同时列 Go/Golang，实际仅列 Go，符合已裁定的去重口径。
- 硬性缺口项目和状态全部一致；人工 `hard_condition` 与实际 `filter` 是标签名称差别。
- V5 另列 4 条经历型缺口（tech 算法、tech 大模型校招、tech Java 社招、ops Java 社招）。实际 `gaps` 只包含契约规定的技能、薪资和过滤项，经历限制留在经历理由/向用户说明中；不将其误报为规则漏项。
- 二选一技能目前仍把 Java 列为后端缺口，已立项 H16；大模型与 RAG/LangChain 不合并；未知理由的具体化已立项 H17。这些不在 V5 对照过程中改规则。

## 独立复核（#48）

- `match score --draft`：20 份草稿为 UTF-8 无 BOM，与命令返回对象相同，未保存前不出现在 `match list`；已保存的 Agent 经历在重新评分时保留。
- `total` 错误给出可直接解析的 JSON 对象；20 组复制后 validate/save 成功。另将有效总分加 1，校验拒绝；复制应填对象后通过，validate 自身没有写正式记录。
- **P2 修复通过**：`evidence.profile` 的元素分别写成对象、数组、数字、空串；另外将整个字段分别设为这四种值。8 种输入 × validate/save = 16 次，全部 valid=false、退出码 1、无 stderr/异常堆栈、正式记录未创建。
- **P1：未发现。P2：指定问题已修复，未发现新增阻塞。P3：无新增阻塞。** 最新 head 已补齐规划者要求的三处文档：第 6 步不拿 ineligible 凑推荐；路线图写明 k 的裁定；CI 恢复与 8 项必需检查。对最新 head 重新执行了全部 20 组及 16 次负向检查。

## 原文哈希对应

| V5 oracle | #48 sample（相对 tests/fixtures/cn） | 原文 LF SHA-256 |
| --- | --- | --- |
| `boss_backend` | `jd/boss_intern.txt` | `843d58dc2bb6a9411cf6c34401e9f02706ecd3e1453862235045b3f40ddd01ef` |
| `data_intern` | `jd/shixiseng_intern.txt` | `bec80b7da184393bfc7a19e93cc64c349bffb9da4784f158fc145d19f0e5f61b` |
| `campus_llm` | `jd/nowcoder_campus.txt` | `b8f57126b426c461c125883591287a305053052faaf7c4e475fc87da5af71de7` |
| `official_algorithm` | `jd/official_site.txt` | `512e03dad9f0ca45677737c0f6da268ab7f520cf636b281ce1a71d2b1c2a5c10` |
| `experienced_java` | `jd/experienced_hire.txt` | `f042d11eedeb8a8ca737b07f6b7ab0db08364e5b9f301f60931183bea1327ead` |
| `ai_product` | `jd-m2-3/boss_ai_product_intern.txt` | `72d442027042c88f29d5e614bfc3f1a13284f2a0d9695605e412599387fa483e` |
| `content_ops` | `jd-m2-3/shixiseng_content_ops_intern.txt` | `55d515034b676fc55aea04dc99666f4f7928bd4e879ff959298670f369843ee3` |
| `ui_design` | `jd-m2-3/ats_ui_design_intern.txt` | `6cd4eeff1f3374a6e345a0ea9bebbcba3ff9db3f302089797937b9d39e32dd59` |
| `test_dev` | `jd-m2-3/nowcoder_test_dev_intern.txt` | `22717a1c11cf8670f5c4117aa65727a04da45751c9921c0c9287e5710c24b7e8` |
| `marketing_campus` | `jd-m2-3/official_marketing_campus.txt` | `db3403da4334ea27ab50e784e218257ccd565cdb3ae5cdcc28b57de948b34964` |

复现数据在 JSON 中保留 20 份完整记录（四维分数/理由/出处、总分、缺口、过滤七项）、两份原始 match list、每组首次总分错误及保存结果。记录只引用样例经历 id，不含档案联系方式。

## Checks

`5c1445a`: Windows / conda `ai-job-search-cn`, Python 3.12.15; 1181 tests, OK (skipped=12). lint_skills and security_guards passed. GitHub CI completed successfully on this head.
