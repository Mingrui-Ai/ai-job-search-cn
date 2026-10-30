# Job Schema（岗位记录格式）v1

一条岗位记录就是一段 JSON：规则解析器、Agent（Codex / Claude Code）和本地存储都读写同一种格式。约束由 `jobsearch_cn/schema.py` 执行，用下面的命令校验：

```powershell
python -m jobsearch_cn jd validate job.json
```

输出 `{"valid": true/false, "errors": [...]}`，每条错误的格式是"字段路径: 原因"。退出码：0 有效；1 无效；2 文件读不了、不是 UTF-8 或不是 JSON。文件必须是 UTF-8 编码（带不带 BOM 都可以）。

省略文件名时从标准输入读取。**在 Windows PowerShell 5.1 中请直接传文件路径**：它默认用 ASCII 向外部程序传管道，中文会悄悄变成 `?`，校验结果就没有意义了。确实要用管道时，先执行 `$OutputEncoding = [System.Text.UTF8Encoding]::new()`。Git Bash 和 PowerShell 7 没有这个问题。

## 基本约定

1. **所有字段必须出现。** JD 没写的标量或对象填 `null`，没写的列表填 `[]`。Agent 补全记录时要明确写出"没写"，不能漏掉字段。
2. **不认识的字段直接报错**，拼错的字段名会立刻暴露。
3. **每个从 JD 读出的值都要注明出处**（`evidence`，见下文）。
4. `schema_version` 当前为 `1`。格式有不兼容的变化时递增，并记录在文末。

## 示例

下面的 JD 是虚构的。这个示例由测试 `tests/test_cn_schema.py` 校验，保证文档与代码一致。

```json
{
  "schema_version": 1,
  "id": "job_3f9a1c2b7d4e",
  "source": {
    "type": "paste",
    "site": "boss",
    "url": null,
    "imported_at": "2026-10-27T10:00:00+08:00"
  },
  "title": "AI Agent开发实习生",
  "company": "示例智能科技（广州）有限公司",
  "cities": ["广州"],
  "remote": null,
  "employment_type": "internship",
  "salary": {"min": 200, "max": 300, "unit": "CNY/day", "months": null, "negotiable": false},
  "requirements": {
    "graduation": {"years": [2027], "strict": true},
    "days_per_week": 4,
    "min_months": 3,
    "education": {"min": "bachelor", "preferred": "master"},
    "skills": ["Python", "LangChain", "RAG"],
    "skill_alternatives": []
  },
  "return_offer": true,
  "published_at": null,
  "deadline": null,
  "status": "new",
  "evidence": {
    "title": {"text": "AI Agent开发实习生", "method": "rule"},
    "company": {"text": "示例智能科技（广州）有限公司", "method": "rule"},
    "cities": {"text": "工作地点：广州天河区", "method": "rule"},
    "employment_type": {"text": "实习生", "method": "rule"},
    "salary": {"text": "薪资：200-300元/天", "method": "rule"},
    "requirements.graduation": {"text": "2027届本科及以上在读", "method": "rule"},
    "requirements.days_per_week": {"text": "每周至少到岗4天", "method": "rule"},
    "requirements.min_months": {"text": "实习3个月以上", "method": "rule"},
    "requirements.education": {"text": ["本科及以上", "硕士优先"], "method": "rule"},
    "requirements.skills": {"text": "熟悉Python，了解LangChain、RAG", "method": "agent"},
    "return_offer": {"text": "表现优秀者可转正", "method": "rule"}
  },
  "guard": {"verdict": "clean", "counts": {}},
  "raw_text": "AI Agent开发实习生\n示例智能科技（广州）有限公司 · 广州\n薪资：200-300元/天\n\n岗位职责：\n1. 参与基于大模型的 AI Agent 应用开发与评测；\n2. 负责 RAG 检索链路的搭建与优化。\n\n任职要求：\n1. 2027届本科及以上在读，计算机相关专业，硕士优先；\n2. 熟悉Python，了解LangChain、RAG；\n3. 每周至少到岗4天，实习3个月以上；\n4. 表现优秀者可转正。\n\n工作地点：广州天河区"
}
```

## 字段说明

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `schema_version` | 整数 | 固定为 1 |
| `id` | 字符串 | `job_` 加 12 位小写十六进制，导入时生成 |
| `source` | 对象 | 记录从哪里来 |
| `source.type` | 枚举 | 怎么进来的：`paste` 粘贴、`file` 本地文件、`url` 单个链接、`portal` 门户适配器 |
| `source.site` | 枚举或 null | 原发布平台：`boss` BOSS直聘、`shixiseng` 实习僧、`nowcoder` 牛客、`liepin` 猎聘、`zhaopin` 智联招聘、`51job` 前程无忧、`lagou` 拉勾、`official` 公司官网、`ats` 招聘系统托管页（Moka、飞书招聘等）、`referral` 内推、`other` 其他 |
| `source.url` | 字符串或 null | 原链接；`source.type` 为 `url` 时必填 |
| `source.imported_at` | 时间 | 导入时间，ISO 8601，必须带时区，例如 `2026-10-27T10:00:00+08:00` |
| `title` | 字符串或 null | 岗位名 |
| `company` | 字符串或 null | 公司名 |
| `cities` | 字符串列表 | 工作城市 |
| `remote` | 布尔或 null | 是否可远程 |
| `employment_type` | 枚举或 null | `internship` 实习、`campus` 校招、`experienced` 社招 |
| `salary` | 对象或 null | 薪资；JD 完全没提时为 null |
| `salary.min` | 数字或 null | 下限，按单位换算后的金额，例如 10-15K 的下限是 10000 |
| `salary.max` | 数字或 null | 上限；不能小于下限 |
| `salary.unit` | 枚举或 null | `CNY/hour` `CNY/day` `CNY/month` `CNY/year` |
| `salary.months` | 整数或 null | 一年发几个月，例如 14 薪写 14；只用于 `CNY/month` |
| `salary.negotiable` | 布尔 | 面议为 true，此时金额和单位可以为 null；为 false 时必须给出金额和单位 |
| `requirements` | 对象 | 任职要求 |
| `requirements.graduation` | 对象或 null | 届别要求 |
| `requirements.graduation.years` | 整数列表 | 例如 `[2026, 2027]` |
| `requirements.graduation.strict` | 布尔 | true 表示只招这些届别，false 表示优先 |
| `requirements.days_per_week` | 整数或 null | 每周最少到岗天数，1–7 |
| `requirements.min_months` | 整数或 null | 最短实习月数，1–36 |
| `requirements.education` | 对象或 null | 学历要求；两项都没写时整体填 null |
| `requirements.education.min` | 枚举或 null | 最低学历：`associate` 大专、`bachelor` 本科、`master` 硕士、`phd` 博士；`none` 表示 JD 写明了学历不限（"学历不限""不设最低学历门槛"），和没写（null）不同 |
| `requirements.education.preferred` | 枚举或 null | 优先学历，不能低于最低学历 |
| `requirements.skills` | 字符串列表 | 技能关键词 |
| `requirements.skill_alternatives` | 列表的列表 | "任选其一"的技能组，例如 JD 写"熟悉 Golang 或 Java"时为 `[["Golang", "Java"]]`；没有时为 `[]`。见下文"任选其一的技能" |
| `return_offer` | 布尔或 null | 是否可转正 |
| `published_at` | 日期或 null | 发布日期，`YYYY-MM-DD` |
| `deadline` | 日期或 null | 截止日期，`YYYY-MM-DD` |
| `status` | 枚举 | 岗位池状态：`new` 新导入、`skipped` 跳过、`ranked` 已评分、`expired` 已过期、`unreachable` 链接失效（与上游 `seen_jobs.json` 相同） |
| `evidence` | 对象 | 出处，见下文 |
| `guard` | 对象或 null | 防注入检查的结果，未检查时为 null |
| `guard.verdict` | 枚举 | `clean` 未发现问题，`warn` 有需要人工查看的发现 |
| `guard.counts` | 对象 | 各类发现的数量；只存数量，不存原文摘录 |
| `raw_text` | 字符串 | JD 原文，最长 50000 字；一条记录只放一份 JD。由 `jd parse` 生成时，是经过防注入检查清理后的文本（去掉隐藏和不可见字符、合并多余空白） |

文本字段和列表中的每一项最长 200 字；列表中不能有重复项（比较时忽略大小写和全角/半角差异）。

## 任选其一的技能

JD 让你在几个技能里选一个会就行时（"熟悉 Golang 或 Java""Python、R 至少掌握一门"），这几个技能记成一组，放进 `requirements.skill_alternatives`：

```json
"skills": ["Golang", "Java", "Docker"],
"skill_alternatives": [["Golang", "Java"]]
```

- 每组至少两个技能，组里的技能必须也在 `requirements.skills` 里；
- 一个技能最多属于一组；
- 出处写在 `evidence["requirements.skill_alternatives"]`，证明选择是 JD 给的：用到的每个片段都要含有这一组里至少两个技能，这些片段合起来要把整组连成一个选择。一个片段含有整组（"熟悉 Golang 或 Java"）就够了；JD 分两处写、有共同技能的（"熟悉 Python 或 Java""熟悉 Java 或 Go"，合成一组 `["Python", "Java", "Go"]`），两个片段都写上。只出现在"熟悉 Golang""了解 Docker"这类各自的片段里不算。

评分时一组算一项要求，见 [match.md](match.md#维度)。规则怎么读出这些组，见 [jd-parse.md](jd-parse.md#规则能识别什么)；规则没读出、或者读错的，Agent 按原文补或改，`method` 写 `agent`。

## 出处（evidence）

`evidence` 以字段路径为键，例如 `salary`、`requirements.skills`。每一项包含两个键：

- `text`：出处原文片段，可以是字符串，也可以是字符串列表；
- `method`：值是怎么得到的：`rule`（本项目的规则解析器）、`agent`（模型补全）、`user`（用户手动填写）。

校验规则：

1. 下列字段只要有值（不是 null，也不是 `[]`），就必须有对应的出处：`title`、`company`、`cities`、`remote`、`employment_type`、`salary`、`requirements.graduation`、`requirements.days_per_week`、`requirements.min_months`、`requirements.education`、`requirements.skills`、`requirements.skill_alternatives`、`return_offer`、`published_at`、`deadline`。
2. `rule` 和 `agent` 给出的每个片段都必须真实出现在 `raw_text` 中。比较前会统一全角/半角和大小写，并去掉空白和零宽字符，所以复制时多出的换行、空格不影响匹配。
3. 列表字段（`cities`、`requirements.skills`）的每一项都必须出现在自己的出处片段里；`requirements.skill_alternatives` 的每一组都要由出处片段说明是一个选择，规则见上文"任选其一的技能"。
4. `user` 表示值来自用户本人，例如 JD 正文里没有公司名，由用户手动补上。这时 `text` 可以为 null，也不要求出现在原文中。

**明确清空列表（H22）**：列表值为 `[]`，且该字段的出处为 `agent` 或 `user`、`text` 非空时，存储层将它视为有意清空。`text` 写明清空依据，可以是非空字符串或非空字符串列表；Agent 仍须逐字引用支持纠正的原文片段，用户可写本人提供的说明。清空来源的优先级必须不低于旧值（`user` > `agent` > `rule`）；保存后这个带出处的 `[]` 继续受优先级保护，规则重新导入不能恢复旧列表。同级或更高优先级可以再纠正。

普通未知列表仍可为 `[]` 且不带出处；`user` 的 `text: null` 也仍合法，但二者均不表示明确清空。规则来源的空列表不清空旧值。空字符串、仅空白、空出处列表不符合现有校验规则，不能用于清空。此路径适用于可取 `[]` 且独立记录出处的列表字段：`cities`、`requirements.skills`、`requirements.skill_alternatives`。清空技能列表时，也要纠正引用这些技能的组；清空全部组时同样为组字段单独保留清空依据，来源不得低于组的旧来源。显式清空技能后若仍有受来源或理由保护的组，存储层拒绝该记录整次写入，不能用字段一致性处理绕过保护；这属于与旧记录合并时的检查，单独的 Schema 校验通过并不保证能保存。标量或对象 `null` 的合并规则不变，也不允许把要求非空的嵌套列表（如 `requirements.graduation.years`）改成 `[]`。操作步骤见 [JD 导入工作流](jd-import.md#明确清空列表字段h22)。

这样模型就没法凭空编造字段：编出来的值找不到原文出处，校验就过不了。不过这条规则只保证出处真实存在，不保证从出处推出的值一定正确，例如把"10-15K"换算成 10000–15000 是否正确，由解析器自己的测试保证（第 2 步）。

## 与上游 `seen_jobs.json` 的对应

| CN 字段 | 上游字段 | 说明 |
| --- | --- | --- |
| `title` | `title` | |
| `company` | `company` | |
| `source.url` | `url` | |
| `source.imported_at` 的日期部分 | `first_seen` | |
| `published_at` | `posted_date` | |
| `deadline` | `deadline` | |
| `status` | `status` | 词表相同 |
| `cities` | `location` | 上游是单个字符串，用 `/` 连接 |
| `source.site` | `portal` | 上游记录的是门户技能名，例如 `linkedin-search` |
| — | `fit`、`source`、`rank_*` 等 | 由上游 `/scrape`、`/rank` 写入；上游的 `source` 是 cli/websearch，与这里的 `source.type` 含义不同 |

上游的去重键（`tools/job_key.py`）遇到纯中文的公司名和岗位名只能生成哈希键（见迁移方案 G2），CN 侧按内容指纹和规范化链接去重，见 [jd-import.md](jd-import.md#去重与合并)。

## 版本记录

- v1（2026-10-26）：首版。
- v1 新增 `requirements.skill_alternatives`（2026-10-29，H16）。只是加了一个字段，版本号不变：本地岗位库里在这之前保存的记录读出时自动补上 `[]`；自己手写、没有这个字段的记录，`jd validate` 会报"missing"，补上 `"skill_alternatives": []` 即可。
