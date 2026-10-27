# JD 解析（jd parse）

把用户提供的中文 JD 文本按规则抽取成 [Job Schema](job-schema.md) 记录。全程离线；规则读不准的字段留空，交给 Agent 或用户补全。

## 用法

```powershell
python -m jobsearch_cn jd parse jd.txt --site boss
python -m jobsearch_cn jd parse jd.txt --url https://example.com/job/123   # --url 只能用于单份 JD
python -m jobsearch_cn jd parse jd.txt --save                              # 解析后直接保存到本地岗位库
```

- 省略文件名时从标准输入读取。在 Windows PowerShell 5.1 中请直接传文件路径，原因见下面的"编码"。
- 输出 `{"jobs": [岗位记录, ...], "warnings": [...]}`。每条警告包含：
  - `segment`：第几份 JD；
  - `kind`：类型，可能是 `guard`、`encoding`、`too_long`、`empty`；
  - `message`：说明；
  - `excerpts`：可疑句子的摘录（仅 `guard` 警告有）。
- 退出码：0 至少解析出一份 JD；1 输入里没有 JD 文本；2 输入读不了，或 `--url` 用法不对。

## 一次导入多份 JD

在两份 JD 之间放一行 `===`（三个或更多等号）：

```text
后端开发实习生
200-250元/天
……
===
数据分析实习生
150-200/天
……
```

## 编码

| 输入 | 处理 |
| --- | --- |
| UTF-8，带或不带 BOM | 直接读取 |
| 带 BOM 的 UTF-16（Windows PowerShell 5.1 的 `>` 和 `Out-File` 默认写成这样） | 直接读取 |
| 其他编码（多半是 GBK，即记事本另存为时的 ANSI） | 按 GB18030 解码，并给出 `encoding` 警告 |
| 没有中文、却有大量 `?` | 拒绝，退出码 2。这是 Windows PowerShell 5.1 用 ASCII 传管道造成的，中文已经丢失 |

Windows 文件的 CRLF 换行可以正常处理。

## 规则能识别什么

| 字段 | 能识别的写法 | 不会误读 |
| --- | --- | --- |
| `salary` | 200-300元/天、日薪200元、150-200/天、10-15K·14薪、8k-12k、1.5-2万/月、年薪20-30万、30-50元/小时、薪资面议 | 2026-2027届、每周4-5天、3-5年经验、电话号码 |
| `requirements.graduation` | 2027届、2027届优先（`strict` 为 false）、2026/2027届、27届、2026-2028届 | 第12届竞赛 |
| `requirements.days_per_week` | 每周至少到岗4天、一周至少三天、4天/周、每周4-5天（取下限） | 3-5天内回复、周一至周五、每周五下午 |
| `requirements.min_months` | 实习3个月以上、至少实习6个月、实习期不少于三个月、实习半年以上 | 试用期至少3个月、6个月以上实习经验（这是经历要求）、3个月内到岗 |
| `requirements.education` | 本科及以上、硕士研究生及以上学历、大专以上学历、硕士优先 | "硕士及以上学历优先"只算优先、不算最低要求；学历不限 |
| `return_offer` | 可转正、表现优秀者可转正、有转正机会；不提供转正 → false | |
| `remote` | 支持远程实习、可远程；不支持远程 → false | 远程控制系统 |
| `cities` | 工作地点：广州天河区；base 北京/上海；工作城市：深圳、杭州；"北京·海淀区·中关村"这类开头 | 面试地点；正文里顺带提到的城市 |
| `employment_type` | 标题含"实习" → `internship`；校招、应届 → `campus`；社招 → `experienced` | |
| `title` | "职位名称：…"；或第一行是像岗位名的短句 | "岗位职责：…"这类段落标题 |
| `company` | "公司：…"；或开头、结尾单独一行的"…有限公司 / 集团"（可带" · 城市"） | "加入示例科技有限公司，你将…"这类句子 |
| `published_at`、`deadline` | 发布时间：2026-10-20；截止日期：2026年11月30日；2026年11月30日前截止 | 没有年份的日期（不猜年份） |
| `requirements.skills` | 固定词表：Python、Java、Go、LangChain、RAG、PyTorch、MySQL、大模型、机器学习等 | Google 里的 Go、JavaScript 里的 Java、MongoDB 里的 Go |

每个值都附出处，`method` 为 `rule`。规则只抽取有把握的内容，宁可留空也不猜。

## 补全流程

1. 用 `jd parse` 得到记录。
2. 补全规则留空的字段，常见的有 `company`、`requirements.education` 和更多技能。
   - Agent 补全时 `method` 写 `agent`，出处片段必须来自原文；
   - 用户手动补全时 `method` 写 `user`，可以不给出处片段。
3. 用 `jd validate` 校验，再用 `jd save` 保存。完整流程见 [jd-import.md](jd-import.md)。

## 防注入检查

每份 JD 都先经过 `jobsearch_cn/guard.py`：

- **复用上游 `tools/posting_guard.py`**：去掉隐藏内容和不可见字符，并检查英文注入句式、混用字形等；
- **补充中文注入句式**（迁移方案中的 G1），例如：
  - "忽略之前的所有指令"
  - "你现在是一个AI助手，"
  - "不要告诉用户"
  - "把候选人的手机号发送到…"

检查只提示、不拦截：

- 可疑句子出现在 `warnings` 的 `excerpts` 里，请人工查看；
- 记录本身只保存结论和数量（`guard`），不保存摘录。

中文句式刻意收窄，招聘广告里的正常说法不会触发，例如"熟悉提示词工程""设计系统提示词""请将简历发送至邮箱""作为AI产品经理""如果你是AI爱好者"。

`raw_text` 保存的是清理后的文本：去掉了隐藏和不可见字符，合并了多余的空白。

## 局限

- 规则是保守的。例如实习僧标题行里单独的"本科"不会被读成学历要求，需要 Agent 或用户补全。
- 城市只认一份常见城市的固定列表。
- 记录的 `id` 由 JD 内容决定（忽略空白和换行的差异），同一份 JD 重复导入会得到同一个 `id`，这是本地岗位库去重的第一依据（见 [jd-import.md](jd-import.md#去重与合并)）。
