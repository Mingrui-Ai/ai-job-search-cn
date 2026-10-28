# 匹配（match）

用 [个人档案](profile.md) 判断一个已保存的岗位适不适合你。分两步：先做**硬性条件过滤**（本文），再做**可解释评分**（M2-4，设计稿见[下文](#可解释评分m2-4-设计稿)）。全程离线。过滤结果直接输出、不保存；评分结果保存为匹配记录。

## 硬性条件过滤：`match filter`

```text
python -m jobsearch_cn match filter <岗位id> [--profile 档案文件] [--data-dir 数据目录]
```

- 岗位从本地岗位库读取（先用 `jd parse --save` 保存）；档案默认读取 `data/profile/profile.json`，必须能通过 `profile validate` 的结构校验（来源文件是否存在不影响过滤）。
- 退出码：0 已给出结论（无论结论是什么）；1 岗位不存在，或档案无效；2 档案读不了、岗位 id 格式不对。
- 输出不包含联系方式。

### 输出

```json
{
  "job_id": "job_9f4694691d57",
  "title": "后端开发实习生（Go方向）",
  "company": "示例互联网科技（深圳）有限公司",
  "verdict": "eligible",
  "checks": [
    {
      "check": "days_per_week",
      "result": "match",
      "reason": "JD 要求每周到岗 4 天，你可以 4 天",
      "jd": {"requirements.days_per_week": {"value": 4, "evidence": "4天/周"}},
      "profile": {"availability.days_per_week": 4}
    }
  ]
}
```

每一项都同时给出 JD 的值和出处原文（`jd`），以及用到的档案字段（`profile`）；有些结论还带 `note` 补充说明。

| `verdict` | 含义 | 条件 |
| --- | --- | --- |
| `ineligible` | 不符合 | 任何一项是 `conflict` |
| `needs_check` | 待确认 | 没有冲突，但有 `unknown`，需要看原文或问 HR |
| `eligible` | 符合 | 全部是 `match` 或 `not_applicable` |

### 各项条件

总原则：**JD 或档案任一方没写，结论是 `unknown`，不是 `conflict`。** 规则读不准时会把字段留空，留空不能让你错过岗位。

| `check` | JD 字段 | 档案字段 | `match` | `conflict` | `unknown` |
| --- | --- | --- | --- | --- | --- |
| `graduation` | `requirements.graduation` | `graduation.year` | 你的届别在列表中；或不在列表中但 JD 只是"优先"（附 `note`） | JD 限定届别（`strict: true`）且你不在其中 | 任一方没写 |
| `education` | `requirements.education.min` | `education[]` 中最高的 `level` | 最高学历不低于最低要求；或 JD 写明学历不限（`none`），这时不看档案 | 低于最低要求 | JD 没写最低学历（只写"优先"也算没写），或档案没写学历 |
| `days_per_week` | `requirements.days_per_week` | `availability.days_per_week` | 要求天数 ≤ 你能到岗的天数 | 要求天数更多 | 任一方没写（校招、社招岗位没写时是 `not_applicable`，见下） |
| `min_months` | `requirements.min_months` | `availability.months` | 要求月数 ≤ 你能实习的月数 | 要求月数更多 | 任一方没写（同上） |
| `location` | `cities`、`remote` | `availability.cities`、`remote_ok`、`relocate` | 城市有交集（"上海"与"上海市"视为相同）；或 JD 可远程且你接受远程；或你愿意搬家（附 `note`） | 没有交集，你明确不搬家（`relocate: false`），并且 JD 写明不支持远程或你明确不接受远程 | JD 或档案没写城市；或没有交集，但是否搬家没写，或能否远程两边都没有否定（包括两边都没写） |
| `employment_type` | `employment_type` | `target.employment_types` | 岗位类型在你的求职方向中 | 不在其中 | 任一方没写 |
| `exclusions` | `title`、`company`、`cities` | `exclusions` | 没命中排除项 | 标题含排除关键词；公司名含排除的公司；工作城市全部在排除城市中 | 设了排除关键词或公司，但 JD 没写标题或公司 |

说明：

- **不适用**（`not_applicable`）：每周到岗天数和实习时长是实习岗位的条件。校招、社招岗位（`employment_type` 为 `campus`、`experienced`）没写这两项时，`days_per_week`、`min_months` 判 `not_applicable`，引用 JD 的 `employment_type`，和 `match` 一样不影响总结论。写了就照常比较；实习岗位、或岗位类型没写时，没写仍是 `unknown`。
- 地点判 `unknown` 时，理由写明两边各说了什么、缺了什么，例如"北京不在意向城市内；JD 没写能否远程；你接受远程、不考虑异地"。
- 排除关键词**只匹配标题**。匹配正文容易误伤，例如正文写"本岗位不是外包"。
- 薪资不在过滤范围内，由评分（M2-4）处理。

### 例子

5 份样例 JD 与 2 份示例档案（`tests/fixtures/cn/`）的 10 组结果，以及每组的人工核对理由，写在 `tests/test_cn_match.py` 的 `SAMPLE_TABLE` 中。

## 可解释评分（M2-4 设计稿）

> 状态：设计稿（规划者，2026-10-28）。按[路线图 M2-4](roadmap.md) 分三个 PR 实现：M2-4a 契约补充（PR #38）、M2-4b 规则评分与匹配记录（PR #41，`jobsearch_cn/score.py`）已实现，M2-4c Agent 工作流待做。实际做法和本稿不同时，在 PR 里说明，并改写本节。

过滤回答"能不能投"，评分回答"值不值得投、差在哪"。评分分两层：

- **规则部分**由 `match score` 计算，同一输入重复运行，结果完全一致：技能、方向、薪资三个维度，加上硬性条件过滤的结论；
- **语义部分**由 Agent 补充：经历是否对口，以及规则判断不了的方向。`method` 写 `agent`，每条依据都要引用 JD 原文和档案条目。

### 维度

| 维度 | 方法 | 怎么算（0–100） | 为 null（未知）的情形 |
| --- | --- | --- | --- |
| `skills` 技能 | 规则 | JD 的每个技能在档案 `skills[]` 里找同名或同义的技能，按掌握程度记分：精通、熟练记 1，熟悉记 0.8，了解记 0.5；没写程度的，有经历用到（`used_in` 不为空）记 0.8，没有记 0.5；档案里没有记 0。分数 = 得分之和 ÷ JD 技能数 × 100 | JD 没有技能 |
| `direction` 方向 | 规则，Agent 可补 | 把 JD 的技能按词表分组计数（`general` 组不计），数量最多的组（并列都算）就是岗位方向。岗位方向在档案 `target.directions` 里记 100；不在，但有 JD 技能属于你的方向记 50；都不属于记 0 | 档案没写 `target.directions`；JD 没有技能，或技能都在 `general` 组（这时由 Agent 根据标题和职责判断） |
| `experience` 经历 | Agent | 对照 JD 的职责和要求，看档案 `experience[]`：80–100 做过同类工作；60–79 相关，能迁移；40–59 沾边，需要自己说明；0–39 无关。规则会列出有经历依据的 JD 技能（`used_in`）作为提示 | Agent 还没补 |
| `salary` 薪资 | 规则 | 单位相同时比较：JD 薪资上限达到你的最低期望（`target.salary_min`）记 100，达不到记 0 | 面议；单位不同（不换算）；任一方没写 |

- Agent 只能补 `experience`，以及规则给出 null 的 `direction`；不能改 `skills`、`salary` 和规则已经算出的 `direction`。
- 比较技能名时忽略大小写和全角半角，并把词表 `same_as` 里同一组的词视为相同（见下文"契约补充"）。

### 总分、等级和缺口

- **权重**默认为技能 35、方向 30、经历 25、薪资 10，可以在档案 `target.weights` 里改（为 null 时用默认值）。
- **总分**：有分值的维度按权重加权平均，四舍五入取整，为 null 的维度不计入。`complete` 表示是否所有维度都有分值，`missing` 列出缺的维度。
- **等级**沿用上游 `04-job-evaluation.md`：`strong` ≥ 75，`good` 60–74，`moderate` 45–59，`weak` 30–44，`poor` < 30。
- 过滤结论为 `ineligible` 时，等级记为 `ineligible`，各维度的分值照常给出，供参考。为 `needs_check` 时等级照常，同时列出待确认的项。
- **缺口**（`gaps`）包括：
  - JD 要求、档案里没有的技能；
  - 薪资低于期望；
  - 过滤结果里的 `conflict` 和 `unknown` 项。

  每条都附上 JD 出处。

### 匹配记录

每个岗位一条，存为 `<数据目录>/matches/<岗位id>.json`（D4：和岗位库一样用 JSON 文件）。

```json
{
  "schema_version": 1,
  "job_id": "job_9f4694691d57",
  "rules_version": 1,
  "scored_at": "2026-10-28T15:00:00+08:00",
  "job_hash": "…",
  "profile_hash": "…",
  "filter": {"verdict": "eligible", "checks": ["…（match filter 的输出）"]},
  "dimensions": {
    "skills": {"score": 75, "method": "rule", "reason": "JD 要求 4 项技能，你有 3 项",
               "matched": [{"jd": "Go", "profile": "Go", "credit": 0.8}], "missing": ["Kafka"]},
    "direction": {"score": 100, "method": "rule", "reason": "JD 技能以技术方向为主，在你的求职方向中",
                  "jd_groups": {"tech": 4}},
    "experience": {"score": 80, "method": "agent", "reason": "做过订单服务重写，和 JD 的高并发后端开发对口",
                   "evidence": {"jd": ["负责高并发订单系统的开发"], "profile": ["exp-1"]}},
    "salary": {"score": 100, "method": "rule", "reason": "JD 上限 300 元/天，达到你的最低期望 150 元/天"}
  },
  "weights": {"skills": 35, "direction": 30, "experience": 25, "salary": 10},
  "total": {"score": 86, "grade": "strong", "complete": true, "missing": []},
  "gaps": [{"kind": "skill", "item": "Kafka", "jd": "熟悉 Kafka 等消息队列"}]
}
```

- `rules_version`：规则或默认权重改变时加 1。
- `job_hash`、`profile_hash`：评分时岗位记录和档案的摘要，档案的摘要不含 `contact`。岗位或档案改了，`match list` 会把这条标为"过期"，需要重新评分。重新评分时，摘要都没变就保留 Agent 已补的内容，变了就清空 Agent 补充。
- Agent 补充的维度必须有 `reason` 和 `evidence`：`jd` 是 JD 原文片段，必须逐字出现在岗位的 `raw_text` 里；`profile` 是档案条目的 id，必须存在。
- `match validate` 检查结构、取值、分值范围和依据，并按上面的规则从各维度重新算出总分和等级，和记录不一致就报错。Agent 不能直接改总分。
- 实现补充（M2-4b）：
  - `direction`、`experience` 都带 `evidence`，规则给出时为 null；`experience` 还有 `hints`，列出档案里用到 JD 技能的经历 id，供 Agent 参考；
  - 缺口里 `filter` 一类另带 `result`、`reason`；JD 没写的项 `jd` 为 null；
  - 岗位的摘要不含 `status`（改岗位状态不算岗位变了），档案的摘要不含 `contact`；`rules_version` 和现在的不同也算过期；
  - `match validate` 先核对两个摘要，岗位或档案改过就要求重新评分；再重算规则部分（过滤、技能、薪资、规则给出的方向、权重、缺口），和记录不一致即报错；
  - 算分全程用分数运算，四舍五入取整（62.5 记 63），同一输入重复运行只有 `scored_at` 不同。

### 命令

| 命令 | 作用 |
| --- | --- |
| `match score <岗位id> [--save]` | 计算规则部分（含过滤），输出匹配记录；加 `--save` 直接保存 |
| `match validate <文件>` | 校验 Agent 补充后的匹配记录 |
| `match save <文件>` | 校验通过后保存 |
| `match show <岗位id>` | 显示已保存的记录 |
| `match list` | 按等级、总分列出已评分的岗位，标出过期的记录 |

- `match score` 输出匹配记录；加 `--save` 时同时保存，输出不变。岗位和档案都没变时，重新评分保留已保存记录里 Agent 补的经历和方向。
- `match validate` 输出 `{"valid": ..., "errors": [...]}`；`match save` 校验通过后输出 `{"saved": "created" | "updated" | "unchanged", "job_id": ...}`。
- `match list` 输出 `{"matches": [...], "warnings": [...]}`，每行有 `job_id`、`title`、`company`、`grade`、`score`、`complete`、`verdict`、`stale`，按等级（strong → poor → ineligible）、总分从高到低排序。
- 退出码：0 成功；1 岗位或记录不存在、档案无效、记录没通过校验；2 文件读不了、不是 JSON、词表有误。

输出都不含联系方式。两个 Agent 共用的工作流（评分 → 补充 → 校验 → 保存 → 用中文向用户说明结论、依据和缺口）在 M2-4c 写进本文。

### 契约补充（M2-4a）

已实现（PR #38）：

- **不适用**：硬性条件新增结论 `not_applicable`。校招、社招岗位没写每周天数和实习时长时，`days_per_week`、`min_months` 判 `not_applicable`，不影响总结论（见上文"各项条件"）。
- **学历不限**：Job Schema 的 `requirements.education.min` 新增取值 `none`，表示 JD 明确写了"学历不限""不设最低学历门槛"，过滤时判 `match`。`jd parse` 能识别这些写法；"专业不限"不算。
- **同义词**：词表新增 `same_as`，列出同义的词条：`["Go", "Golang"]`、`["JavaScript", "JS"]`、`["Kubernetes", "K8s"]`、`["自然语言处理", "NLP"]`、`["文案写作", "文案撰写"]`、`["PowerPoint", "PPT"]`（"JS""PPT""文案撰写"是新补的词条）。同一组的词必须都是词表里的词条，并且属于同一个分组。比较技能时同一组视为相同（`vocab.Vocabulary.same`）；解析结果仍保留 JD 原文的写法。用户词表可以追加，和已有的组有相同词条时并成一组。写法见 [jd-parse.md](jd-parse.md#技能词表)。
- **档案**：`target` 新增 `directions`（词表分组键的列表，例如 `["data", "product"]`；`general` 不算方向）和 `weights`（null，或四个维度的权重，每项不小于 0）。Profile 还没有随版本发布，直接加入 v1，不升版本号。字段说明见 [profile.md](profile.md#3-profilejson-字段)。
- **建档**：`profile-setup.md` 要求问到"是否接受远程""是否愿意去其他城市"，并说明留空的后果；写了意向城市而这两项为空时，`profile validate` 给出警告。草稿放在 `data/profile/drafts/`。
- **地点的理由**：判 `unknown` 时写明哪一方没写，见上文"各项条件"的说明。
