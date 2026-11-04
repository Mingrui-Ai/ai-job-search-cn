# 审核结果格式（Review v1，M3-3 第二部分）

"起草 + 审核"工作流（[review-checklist.md](review-checklist.md)）里，审核者对一份材料的意见写成一份 JSON，由 `review validate` 检查格式，用 `review show` 显示给用户看。审核者动笔之前，可以先用 `review draft` 拿到机器初稿。

## 1. 存放位置

和所审的材料放在同一个目录：`data/materials/<岗位id>/review-<n>-r<轮次>.json`。`<n>` 和材料 `resume-<n>.json` 的编号一样，轮次是 1 或 2。打招呼语、投递邮件、内推请求（M3-6）的审核结果是 `review-<种类>-<n>-r<轮次>.json`，例如 `email-1.json` 的第 1 轮是 `review-email-1-r1.json`。`data/` 不提交。

## 2. 字段

例子（虚构）：

```json
{
  "schema_version": 1,
  "kind": "resume-review",
  "job_id": "job_000000000001",
  "material": "resume-1.json",
  "material_hash": "…",
  "round": 1,
  "mode": "independent",
  "created": "2026-11-01T12:00:00+08:00",
  "verdict": "revise",
  "findings": [
    {"item": "B1", "path": "experience[0].bullets[1].text", "severity": "must",
     "reason": "原文是参与，这里写成了负责", "suggestion": "参与订单查询接口的重构"}
  ],
  "coverage": [
    {"requirement": "Python", "status": "covered", "where": ["skills[0]"], "note": null},
    {"requirement": "Docker", "status": "gap", "where": [], "note": "档案里有，材料没写"}
  ]
}
```

| 字段 | 说明 |
| --- | --- |
| `schema_version` | 固定为 `1` |
| `kind` | 简历是 `resume-review`；打招呼语、投递邮件、内推请求分别是 `greeting-review`、`email-review`、`referral-review`，必须和材料的种类对上 |
| `job_id` | 必须和所审材料的 `job_id` 相同 |
| `material` | 所审材料的文件名（只写文件名，例如 `resume-1.json`；材料和审核结果在同一目录） |
| `material_hash` | 所审材料的摘要，`review draft` 会输出。材料后来改过，这份审核结果就不通过，要按当前版本重审 |
| `round` | 第几轮，`1` 或 `2`（最多 2 轮） |
| `mode` | `independent`：另开会话或用子代理审核；`self`：起草者自己的会话自审，只作退路，检查会给警告，交给用户时要说明 |
| `created` | 写审核结果的时间，ISO 8601，要带时区 |
| `verdict` | `pass`（通过）或 `revise`（需修改）。`pass` 不能带 `must` 级的问题 |
| `findings[]` | 问题，没有就写 `[]`，每条见下表 |
| `coverage[]` | 岗位要求的覆盖情况（清单 C2），每条见下表；JD 没列要求时写 `[]`；打招呼语、邮件、内推请求没有覆盖表，一律写 `[]` |

`findings[]` 每条：

| 字段 | 说明 |
| --- | --- |
| `item` | 清单编号，`A1`–`A5`、`B1`–`B6`、`C1`–`C6`、`D1`–`D6`、`E1`–`E6`、`F1`–`F4`、`G1`–`G8`（G 类只用于沟通草稿） |
| `path` | 问题在材料里的位置，例如 `summary.text`、`experience[0].bullets[1].text`、`skills[2]`，沟通草稿是 `segments[3].text`、`subject.text`；必须能在材料里找到。下标只认 ASCII 数字，`skills[１]`（全角）这类写法按找不到的位置报告。关于整份材料的问题（例如 D1 页数）写 `null` |
| `severity` | `must` 是必改，`suggest` 是建议；界线见 [review-checklist.md §4.3](review-checklist.md#43-审核者读什么输出什么) |
| `reason` | 理由，不超过 300 字 |
| `suggestion` | 可以直接替换的新文字，没有就写 `null` |

`coverage[]` 每条：

| 字段 | 说明 |
| --- | --- |
| `requirement` | 岗位的一项要求：技能、学历专业、经验，或者 JD 里反复出现的业务词 |
| `status` | `covered` 已覆盖，`synonym` 同义可改，`gap` 缺口 |
| `where` | 材料里覆盖它的位置；`covered`、`synonym` 至少一处，`gap` 必须是 `[]` |
| `note` | 说明；不写说明时为 `null` |

所有字段都要写，不能多写。

## 3. 命令

```
python -m jobsearch_cn review draft <材料文件> [--profile <档案>] [--data-dir <目录>]
python -m jobsearch_cn review validate <审核结果> [--material <材料文件>]
python -m jobsearch_cn review show <审核结果> [--material <材料文件>]
```

**`review draft`**：材料要先通过 `material validate`，否则退出码 1。只打印，不写文件。它只用材料检查的错误，不输出那里的警告（例如档案改过、`profile_hash` 和现在的不同），这些看 `material validate` 的输出。输出：

- `material_hash`：写进审核结果的摘要；
- `job_found`：岗位库里有没有这个岗位；
- `coverage`：JD 解析出的每项技能要求一行，可以直接作为审核结果 `coverage` 的初稿。打招呼语、邮件、内推请求是 `[]`，`style` 只查全角标点和中英文之间的空格（E1、E3），不查要点结尾的句号。

  - 材料的技能一节或改写的文字里用了 JD 的写法（只差大小写也算；JD 对同一项技能用了几种写法，例如职责写 Go、要求写 Golang，用哪一种都算）：`covered`；
  - 只用了别的写法（例如 JD 写 Golang，材料写 Go）：`synonym`，`note` 写明两种写法；
  - 都没用：`gap`。`note` 只写机器能看出的情况：
    - 档案的技能列表里有："档案里有，材料没写"；
    - 技能列表里没有，但材料引用的某个条目的原文里有（经历要点、项目名等）："技能列表未列，所引条目原文里有，材料没写"；
    - 两处都没有："技能列表未列，需核对经历原文"。材料没引用的条目里可能有这项技能，机器不下"档案里没有"的结论，由审核者核对后决定是缺口还是没写上。

  **任选其一**：JD 的 `requirements.skill_alternatives` 里的一组（"熟悉 Golang 或 Java"）合成一行，`requirement` 写"Golang 或 Java"，排在组里第一项技能出现的位置；组里的技能不再单列，和评分的算法一样（[match.md](match.md#任选其一的技能h16)）。组里有一项 `covered`，这一行就是 `covered`，`where` 列出覆盖的位置；都没有时，有一项 `synonym` 就是 `synonym`；都没用就是 `gap`，`note` 取组里最有用的那条，前面写上是哪项技能，例如"Java：档案里有，材料没写"（"需核对经历原文"不写技能名）。

  学历、经验、业务词机器不列，由审核者补上（清单 C1）。岗位库里没有这个岗位时为 `[]`。
- `style`：清单 E1、E3 的警告，包括要点结尾有句号、中文里夹着半角逗号分号冒号、中文和英文或数字之间有空格。只是警告，不影响 `material validate` 和退出码。

**`review validate`**：检查格式，并核对审的是材料的当前版本。不写 `--material` 时，读审核结果同一目录下 `material` 字段写的文件，只取文件名。输出和其他校验命令一样：`{"valid": …, "errors": […], "warnings": […]}`。不通过时退出码 1，文件读不了时退出码 2。

**`review show`**：先做同样的检查，不通过就输出错误，退出码 1；通过就把审核结果显示成 Markdown，包括结论、审核方式、问题（必改在前）和覆盖表。审核者写的文字（覆盖表的要求和说明，问题的理由和建议改法，以及标题里的材料文件名和岗位 id）原样显示，里面的换行一律写成 `<br>`，所以不会拆断所在的列表项、标题或表格行；表格单元格里的竖线和反斜杠还会转义。不另存文件。

## 4. 不通过的情况

- 字段缺失、多余或类型不对，枚举值不在列表里；
- `job_id` 和材料的不同，或者 `material_hash` 和材料的当前版本不同；
- `round` 不是 1 或 2；
- `item` 不是清单编号，`path` 或 `where` 里的位置在材料里找不到；
- `verdict` 是 `pass` 却有 `must` 级的问题；
- 状态为 `gap` 的行列了位置，或者 `covered`、`synonym` 的行没列位置；
- `reason`、`requirement` 为空或超过 300 字。

**警告**只在没有错误时给出：`verdict` 是 `revise` 但没有 `must` 级的问题；`mode` 是 `self`。
