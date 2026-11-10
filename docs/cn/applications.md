# 投递记录（Application v1，M4-1）

记下用户的每一次投递：投了哪个岗位、走的什么渠道、什么时候投的、发出去的是哪份简历，以及后来的进展。记录存在本机的一个 SQLite 数据库里，状态由事件推出，投出时发出的文件复制归档。三个 Agent（Claude Code、Codex、DeepSeek Harness）都按本文件读写。

设计和裁定见 [设计稿](worklog/2026-11-03-m4-1-applications-design.md)（§14 是规划者的裁定），存储的取舍见 [M4-0 存储决策备忘](m4-0-store-decision.md)。

**M4-1a** 做了 `record`、`submit`、`status`、`show`、`list`、`validate`、`export`；**M4-1b** 加了 `reply`、`note`、`followup`（含 `list --due`）、`void`、`backup`，以及第 16 节的 Agent 工作流、入口和命令授权。从导出恢复（import）v1 不做，恢复靠 `backup`（第 15 节）。

**M4-3** 的只读复盘命令是 `python -m jobsearch_cn application retrospective [<投递id> ...] [--data-dir <数据目录>]`。按 [calibration.md](calibration.md) 安全整合投递事件和首次登记投出时的 job/match 快照，说明事实、历史评分和缺失/歧义；不写档案或重新评分。完整解释与权重试算交接只维护在该文档。

## 1. 存放位置

都在数据目录下（默认 `cn\data`，`--data-dir` 或环境变量 `JOBSEARCH_CN_DATA_DIR` 可改）：

| 路径 | 内容 |
| --- | --- |
| `applications/applications.sqlite3` | 唯一的投递数据库。回滚日志 `applications.sqlite3-journal` 只在写入时出现 |
| `applications/artifacts/<投递id>/mv_…/` | 一次投出时归档的材料 JSON 和发出的文件 |
| `applications/artifacts/<投递id>/ctx_…/` | 第一次投出时的岗位记录和评分记录（快照） |
| `applications/exports/` | `export --out` 只写到这里 |
| `applications/backups/<UTC 时间>/` | `backup` 写的备份（第 15 节） |

- `data/` 整个被 `.gitignore` 忽略，数据库、日志、导出、归档都不会被提交。
- 这些目录都必须是真的文件夹：是链接或 junction 时拒绝写入；数据库文件本身是链接时拒绝打开。
- 数据库只放本机磁盘。放进网盘的同步目录，同步程序可能在写入中途复制文件，得到坏的副本。
- 只读命令（`show`、`list`、`validate`、`export`）在还没有数据库时返回"还没有投递记录"，不建空库。

## 2. 一条投递

一条投递是"一个岗位、一个渠道的一次投递尝试"。同一岗位换渠道再投、过一阵再投，是新的一条，有新的 `application_id`。下面是 `show` 和 `export` 里一条投递的格式（虚构数据）：

```json
{
  "application_id": "app_0123456789abcdef0123456789abcdef",
  "job_id": "job_000000000001",
  "record_origin": "current",
  "channel": {"kind": "portal", "platform": "示例招聘站"},
  "created_at": "2026-11-02T06:00:00Z",
  "updated_at": "2026-11-02T06:30:00Z",
  "revision": 2,
  "status": "applied",
  "submission": {"confirmed": true, "occurred_at": null, "occurred_on": "2026-11-02", "materials_recorded": true, "materials_check": "match"},
  "next_followup_on": null,
  "context_snapshot": {
    "job": {"path": "artifacts/app_…/ctx_…/job.json", "sha256": "…"},
    "match": null
  },
  "material_versions": [
    {
      "version_id": "mv_…",
      "kind": "resume",
      "material_path": "materials/job_000000000001/resume-1.json",
      "material_hash": "…",
      "profile_hash": "…",
      "review_path": "materials/job_000000000001/review-1-r2.json",
      "created_at": "2026-11-02T06:30:00Z",
      "files": [
        {"file_id": "material", "role": "source", "path": "artifacts/app_…/mv_…/material.json", "sha256": "…", "size_bytes": 1534},
        {"file_id": "sent-1", "role": "sent", "path": "artifacts/app_…/mv_…/sent-1.pdf", "sha256": "…", "size_bytes": 48211}
      ]
    }
  ],
  "events": ["见第 3 节"]
}
```

| 字段 | 说明 |
| --- | --- |
| `application_id` | `app_` 加 32 位十六进制，命令随机生成 |
| `job_id` | 岗位库里的岗位 id |
| `record_origin` | `current`：现在发生的投递；`historical`：补录以前的投递（见第 7 节） |
| `channel` | `kind` 是 `portal`（招聘平台）、`company_site`（公司官网）、`email`、`referral`（内推）、`campus`（校招宣讲、双选会）、`offline`、`other`、`unknown` 之一；`platform` 是平台名，可为 null，最多 40 字。投出后是实际投出的渠道。不存链接、账号、Cookie、邮箱地址 |
| `created_at`、`updated_at` | 记录写入和最后一次改动的时间（UTC），不是投递发生的时间 |
| `revision` | 最后一条事件的序号。改一条投递时要带上它（`--expected-revision`），见第 8 节 |
| `status` | 当前状态，见第 4 节 |
| `submission` | `confirmed`：用户说过已经投出；`occurred_at` / `occurred_on`：投出的时刻或日期（见第 5 节）；`materials_recorded`：投出时记没记材料，未投出为 null。为 false 就是"材料未记录"（例如用平台的在线简历投的），可以单独统计；`materials_check`：发出的文件和 build 说明文件的核对结果（第 12 节），`match` / `mismatch` / `unchecked`，没有发出文件或未投出为 null |
| `next_followup_on` | 跟进日期，M4-1b 才能设置，现在总是 null |
| `context_snapshot` | 第一次投出时复制的岗位记录和评分记录，没有时为 null（例如没评过分）。补录的投递不做快照：现在的岗位和评分不能冒充当时的 |
| `material_versions` | 投出时归档的材料，见第 6 节 |
| `events` | 全部事件，按序号排 |

## 3. 事件

每次写入追加一到两条事件，不改旧事件。

```json
{
  "event_id": "evt_…",
  "seq": 2,
  "request_id": "req_…",
  "type": "submitted",
  "occurred_at": null,
  "occurred_on": "2026-11-02",
  "recorded_at": "2026-11-02T06:30:00Z",
  "actor": "claude_code",
  "source": {"kind": "user", "reference": null},
  "payload": {"channel": {"kind": "portal", "platform": "示例招聘站"}, "material_version_ids": ["mv_…"], "sent_file_refs": [{"version_id": "mv_…", "file_id": "sent-1"}], "materials_check": "match"},
  "voided_by": null
}
```

| `type` | 由谁写 | `payload` |
| --- | --- | --- |
| `created` | `record` | `{job_id, record_origin, channel}` |
| `submitted` | `record --submitted` 或 `submit` | `{channel, material_version_ids, sent_file_refs, materials_check}`；没有材料时两个列表都是空的 |
| `status_changed` | `status` | `{from, to, reason}`；`reason` 最多 300 字，可为 null |
| `reply_received` | `reply` | `{summary}`，1–300 字。只记"收到回复"，不改状态 |
| `note_added` | `note` | `{text}`，1–300 字 |
| `followup_scheduled` | `followup --due` | `{due_on}`，`YYYY-MM-DD` |
| `followup_cancelled` | `followup --cancel` | `{}` |
| `event_voided` | `void` | `{target_event_id, reason}`；`reason` 1–300 字，必填（第 14 节） |

- `seq` 从 1 起连续编号；`request_id` 是写入它的那次请求（第 8 节）。
- `actor` 是 `user`、`claude_code`、`codex`、`dsh` 之一，命令的 `--actor` 给，默认 `user`。
- `source.kind` 现在总是 `user`：记录的都是用户说的事。`authorized_api` 留给以后经授权的接口。
- `voided_by`：被 `void` 作废的事件，这里是作废它的那条 `event_voided` 的 `event_id`；没被作废为 null。事件不删，只有这一个字段会在写入以后被填上。
- `note_added`、`followup_*`、`event_voided` 没有发生时间（`occurred_at`、`occurred_on` 都是 null）；`reply_received` 可以带 `--on` 或 `--at`（回复是哪天来的）。

## 4. 状态

| 现在 | 可以变成 |
| --- | --- |
| `drafted`（只起草，还没投） | `applied`（只能用 `submit`）、`withdrawn` |
| `applied` | `interview`、`offer`、`rejected`、`withdrawn`、`no_response` |
| `interview` | `offer`、`rejected`、`withdrawn`、`no_response` |
| `offer` | `hired`、`offer_declined`、`rejected`（对方收回）、`withdrawn` |
| `no_response` | `interview`、`offer`、`rejected`（迟到的回复，必须写 `--reason`） |
| `hired`、`rejected`、`withdrawn`、`offer_declined` | 不能再变 |

- 表里没有的变化报 `transition`，什么也不写。输错了的状态用 `void` 作废那条事件（第 14 节）。
- 多轮面试不加状态，用 `reply` 或 `note` 记"二面"。
- `no_response` 只在用户说"不等了"时记，不由日期自动判定；没收到回复不等于被拒。
- 进入终结状态或 `no_response` 时，跟进日期清空（第 13 节）。
- 状态存在数据库里方便查询，但它是事件的投影：写入和 `validate` 都用同一个函数（`applications.replay`）从事件重放出来，被作废的事件跳过。

每种事件在哪些状态下能记：

| 命令 | 能记的状态 | 不能记时 |
| --- | --- | --- |
| `note` | 任何状态，包括 `drafted` 和终结状态 | — |
| `reply` | 已投出的：有一条没被作废的 `submitted`，状态可以是终结状态（例如被拒以后的反馈） | 没投出的报 `transition`：`drafted` 先 `submit`；没投就撤回的 `withdrawn`（包括投出被作废以后再撤回的）不能记 |
| `followup` | `applied`、`interview`、`offer` | 其他状态报 `transition`；没有跟进日期时 `--cancel` 报 `invalid` |

"已投出"看事件，不看状态：`drafted` 可以直接变成 `withdrawn`，所以 `withdrawn` 不说明投出过。写入和 `validate` 重放时用同一条规则。

收到的回复改了状态（例如面试邀请），只记一条 `status interview --reason 收到面试邀请`，不再另记 `reply`；`reply` 只记状态不变的回复（例如"HR 说下周给结果"）。

## 5. 时间

- 事情发生的时间只有三种写法：`--at 2026-11-02T14:30+08:00`（知道时刻，必须带时区，存成 UTC 的 `…Z`）、`--on 2026-11-02`（只知道日期）、都不写（不知道）。都不写时两个字段都是 null，**不补成今天，也不补成午夜**。用户说"刚投了"，Agent 问清楚或写今天的日期，并告诉用户写的是哪天。
- 不能是将来：`--on` 不能晚于北京时间的今天，`--at` 不能晚于现在 5 分钟以上。
- `recorded_at`、`created_at`、`updated_at` 是写入的时刻，由命令自己写。
- 列表按北京时间（Asia/Shanghai）排日期。

## 6. 材料和归档

投出时（`record --submitted` 或 `submit`）可以带：

- `--material`：这次投的材料文件：简历 `data/materials/<岗位id>/resume-<n>.json`，或沟通草稿 `greeting-<n>.json`、`email-<n>.json`、`referral-<n>.json`（M3-6）；
- `--sent`：实际发出的文件，一个或几个（PDF、Word，或沟通草稿的 `.txt`）；用户手工改过 Word 再发的，就给改过的那份。

写入前先检查：

- 材料要能通过 `material validate`（对照当前档案；档案改过只给警告），而且必须是这个岗位的材料；
- 发出的文件不在 `resumes/<岗位id>/`（沟通草稿是 `messages/<岗位id>/`）下、或者文件名和材料编号对不上，给警告，照样记录；
- 发出的文件用 `resume build` 或 `material render --output` 的说明文件核对（第 12 节）；对不上、找不到说明文件，都给警告，照样记录；
- 材料旁边有通过了这一版材料的审核结果（`review-<n>-r<轮次>.json`，沟通草稿是 `review-<种类>-<n>-r<轮次>.json`；`material_hash` 相同、`verdict` 为 `pass`）时，记下最后一轮的路径（`review_path`）；没有时给警告。
- 材料版本的 `kind` 现在只有 `resume`（库表的约束），沟通草稿也记为 `resume`，从 `material_path` 看是哪种。

然后把材料 JSON（`material.json`）和发出的文件（`sent-1.pdf`、`sent-2.docx`……，保留扩展名）**复制**进 `artifacts/<投递id>/mv_…/`，记下实际字节的 SHA-256 和大小。以后材料被改、PDF 重新生成、档案更新，归档和摘要都不变。`material_path` 只说明来源，以后不从那里读。

- `material_hash` 是 `review.material_hash` 算的值，和审核结果里记的是同一个，所以能对上这份材料的审核。`profile_hash` 抄材料里的。
- 第一次投出时（补录的除外）还把 `jobs/<岗位id>.json` 和 `matches/<岗位id>.json` 复制进 `ctx_…/`，供 M4-3 复盘看投出时的岗位和评分。投出被作废、以后再 `submit` 时，沿用第一次的快照，不再复制（第 14 节）。
- 现在的投递投出时没有材料：照样记录，输出警告"材料未记录"，`submission.materials_recorded` 为 false，`validate` 也列出来。平台在线简历、网申表格这类投递就是这样，不能为了凑材料挡住。
- `--material`、`--sent` 只能和投出一起记；只起草（`drafted`）时不记材料。

## 7. 补录以前的投递

`record … --submitted --historical`：用户以前投过、现在才记。可以没有材料、日期未知，岗位不在岗位库里也行（给警告，只记岗位 id）。补录不做岗位和评分快照，也不报"材料未记录"。`--historical` 必须带 `--submitted`。

## 8. 命令

```text
python -m jobsearch_cn application record <岗位id> --channel KIND [--platform 名称] [--submitted [--historical] [--on 日期 | --at 时刻] [--material 材料 --sent 文件 ...]] (--preview | --request-id ID) [--actor A]
python -m jobsearch_cn application submit <投递id> --expected-revision N [--channel KIND] [--platform 名称] [--on | --at] [--material ... --sent ...] (--preview | --request-id ID) [--actor A]
python -m jobsearch_cn application status <投递id> <新状态> --expected-revision N [--reason 文字] [--on | --at] (--preview | --request-id ID) [--actor A]
python -m jobsearch_cn application reply <投递id> --summary 文字 --expected-revision N [--on | --at] (--preview | --request-id ID) [--actor A]
python -m jobsearch_cn application note <投递id> --text 文字 --expected-revision N (--preview | --request-id ID) [--actor A]
python -m jobsearch_cn application followup <投递id> (--due 日期 | --cancel) --expected-revision N (--preview | --request-id ID) [--actor A]
python -m jobsearch_cn application void <投递id> --reason 文字 --expected-revision N (--preview | --request-id ID) [--actor A]
python -m jobsearch_cn application show <投递id>
python -m jobsearch_cn application list [--status S ...] [--job 岗位id] [--due [--as-of 日期]]
python -m jobsearch_cn application validate [--backup 名字]
python -m jobsearch_cn application export [<投递id> ...] [--out 文件名.json]
python -m jobsearch_cn application backup
```

所有命令都接受 `--data-dir`；`record`、`submit` 还接受 `--profile`（检查材料用的档案）。

**先预览，再写入。** 写操作（`record`、`submit`、`status`、`reply`、`note`、`followup`、`void`）必须二选一：

1. `--preview`：只算不写（数据库不存在也不会建），输出要写的事件（`event_id`、`seq`、`recorded_at` 为 null）、新旧状态、要归档的文件和它们的摘要、警告，以及一个新的 `request_id`；
2. 用户看过、同意以后，同样的参数加 `--request-id <预览给的 id>` 再运行一次，才写入。

同一个 `request_id` 重试（例如没看到输出、不知道写没写成）：内容相同就返回第一次的结果，`repeated` 为 true，不重复写；内容不同（参数、材料或发出文件的字节变了）报 `request_conflict`，要重新预览。重试不受日期影响：和"今天"比较的检查（跟进日期不能早于今天）只拦新请求，隔天重试已经写成的请求照样返回第一次的结果。

**输出和退出码**：

- 成功：标准输出 JSON，退出码 0。写操作输出 `{"application": <第 2 节的格式>, "events": [这次写入的事件], "request_id": …, "preview": false, "repeated": …, "warnings": [...]}`；预览输出 `{"application": <现在的样子，新建时为 null>, "events": [...], "request_id": <新的>, "preview": true, "status": {"from", "to"}, "materials": [...], "warnings": [...]}`。
- 拒绝：标准错误输出 `{"error": "<代码>", "message": "…", …}`，退出码 1。

  | 代码 | 什么时候 |
  | --- | --- |
  | `invalid` | 参数不合规则：时间格式、文字太长、材料不对、少了 `--reason` 等；材料检查不通过时附 `errors` |
  | `transition` | 状态表不允许的变化（附 `status` 和 `allowed`） |
  | `stale_revision` | `--expected-revision` 不是当前的（附 `revision` 和这之后的 `events`） |
  | `request_conflict` | `request_id` 已经用于另一个请求 |
  | `busy` | 另一个程序正在写，等了 5 秒还没写完 |
  | `not_found` | 没有这条投递；新建投递时岗位不在岗位库里；没有投递记录时 `backup`；`validate --backup` 的备份不存在 |

- 读不了：文件不存在、不是 JSON、不是投递数据库、数据库版本比程序新（"请更新程序"，什么也不读不写），标准错误输出 `{"error": …}`，退出码 2。
- `validate` 输出 `{"valid", "errors", "warnings", "orphans"}`，不通过时退出码 1。
- `list` 按投出时间倒序，没投出的在最后；每行带岗位库里的 `title`、`company`，以及 `next_followup_on`。`list --due` 见第 13 节。
- `void` 的预览和写入输出还多一项 `voids`：要作废（或已作废）的那条事件。
- `backup` 不预览，输出 `{"backup": 名字, "path", "manifest", "warnings"}`（第 15 节）。
- `export` 顶层是 `{"schema_version": 1, "exported_at": …, "applications": [...]}`，按 `application_id` 排序，键顺序固定；同样的记录导出两次，除了 `exported_at` 逐字节相同。导出不带归档文件的内容，只带清单。`--out` 只收文件名（字母、数字、`.`、`_`、`-`，以 `.json` 结尾），写到 `applications/exports/`，不接受路径。

## 9. 几个 Agent 同时写

- 每条命令一个短连接，写入用 `BEGIN IMMEDIATE`，锁最多等 5 秒，超时报 `busy`，不无限等。`backup` 也一样（第 15 节）。
- 改已有投递时，事务里再读一次 `revision`，和 `--expected-revision` 不同就报 `stale_revision`，把别人新写的事件带回来。Agent 要重新读、告诉用户发生了什么，不能自动覆盖。
- 事务里不等用户、不生成 PDF、不联网。归档文件在事务**之前**写好：先写进 `….tmp/`，每个文件读回核对摘要，再改名成正式目录，然后开事务登记。事务没成功时删掉这次写的归档；进程在中途被杀掉留下的目录，`validate` 列在 `orphans` 里，数据库里没有它，不算投递，用户同意后再删。
- 第一次写入时建表也在同一个事务里，失败时一起回滚。
- 新建投递时，同一岗位已经有没结束的投递，给警告（可能记重了），不拦：换渠道再投是允许的。

## 10. 检查（`validate`）

- SQLite 自己的完整性检查和外键检查；
- 每条投递：id 和字段的格式，事件从 1 连续编号，每条事件的 payload 字段齐全、取值合法，没有发生时间的事件确实没写时间，重放得到的状态、投出时间、跟进日期、渠道、`revision` 和表里存的一致；补录的必须已投出；
- 作废：每条 `event_voided` 指向本投递里更早的一条事件，那条事件当时是最近一条能作废的（不是 `created`，也不是作废事件），它的 `voided_by` 就是这条作废；一条事件最多被作废一次；
- 事件引用的材料版本和发出文件都登记了；归档文件都在，字节的 SHA-256 和大小没变；现在的投递投出了，就要有快照记录；
- 归档路径（`material_files.path`、`snapshots.path`）只能是 `artifacts/` 下的普通路径：只用 `/` 分隔，每一段只有字母、数字、`_`、`-` 和夹在中间的 `.`，不是 Windows 的设备名（`NUL` 等）。反斜杠、盘符、`..`、绝对路径、结尾的点、冒号都不行，在哪个系统上都一样判。文件按解析后的真实位置也要在 `artifacts/` 里，中间经过链接或目录联接（junction）走到外面的算错误，不跟随。`backup` 和 `validate --backup` 用同一条规则（第 15 节）；
- 请求表里每个 `request_id` 对应的事件确实是它写的；
- 警告：投出时材料未记录的投递；`materials_check` 为 `mismatch` 或 `unchecked` 的投递（第 12 节）；原因、平台名、回复摘要、备注、作废原因里像手机号、邮箱、链接的文字；
- `orphans`：`artifacts/` 下没有登记的文件和目录，以及 `backups/` 下没做完的 `<名字>.tmp/`（第 15 节）。
- `validate --backup <名字>` 改为检查一份备份，见第 15 节。

## 11. 隐私

- 记录、归档、导出都只在数据目录下，本机明文存储，不加密。
- 原因、平台名只写用户说的话，Agent 不往里写联系方式、邮件全文、链接；写了 `validate` 和写入时都给警告。
- `show`、`list`、`export` 不带档案的联系方式；归档的材料 JSON 本来就只引用档案条目，不含联系方式。发出的 PDF、Word 里有联系方式，它们只在 `artifacts/` 里，导出只带摘要。

## 12. `resume build` 的说明文件（M4-1a 第二部分）

规划者 2026-11-03 裁定：`resume build` 每生成一次，在输出旁边写一个说明文件，记下这次用的是哪一版材料、生成了哪些文件。M3-6 的 `material render --output` 写 `.txt` 时用同样的格式。

- 位置和名字：`data/resumes/<岗位id>/resume-<n>.build.json`，即材料文件名去掉 `.json` 再加 `.build.json`。每次 build 覆盖上一次的。
- 沟通草稿（M3-6）：`material render --output` 在 `data/messages/<岗位id>/<种类>-<n>.build.json` 写同样格式的说明文件，`kind` 是 `message-build`，`files` 只有它写的 `<种类>-<n>.txt`。下面说的核对对它一样适用。
- 格式：

  ```json
  {
    "schema_version": 1,
    "kind": "resume-build",
    "material": "resume-1.json",
    "material_hash": "…",
    "profile_hash": "…",
    "built_at": "2026-11-03T10:00:00+08:00",
    "files": [
      {"name": "resume-1.pdf", "sha256": "…"},
      {"name": "resume-1.docx", "sha256": "…"}
    ]
  }
  ```

  `material_hash` 是 `review.material_hash`，`profile_hash` 是当前档案的 `score.profile_hash`，`built_at` 带时区，`files` 列出这次输出的每个文件名和字节 SHA-256。
- 投出时用哪个说明文件核对：
  - 给了 `--material`：用这份材料的说明文件核对所有发出的文件。说明文件在 `resumes/<岗位id>/` 下（沟通草稿在 `messages/<岗位id>/` 下），名字是材料文件名去掉 `.json` 再加 `.build.json`，就是 `resume build`（沟通草稿是 `material render --output`）写的那个。发出的文件改了名字（例如另存为"姓名-岗位.pdf"）也照样核对。
  - 没给 `--material`：按每个发出文件自己的名字找它旁边的说明文件。`resume-<n>.<扩展名>` 找 `resume-<n>.build.json`（`greeting-<n>.txt` 找 `greeting-<n>.build.json`，邮件、内推同理），别的名字找去掉扩展名再加 `.build.json` 的那个。
- 核对的内容：发出文件的摘要要在说明文件的 `files` 里；给了 `--material` 时，说明文件里的 `material_hash` 还要等于材料的当前值。对不上只给警告（手工改过的 Word 就是这样），照样记录用户说发出的文件。
- 核对结果记进 `submitted` 事件的 `materials_check`（导出的 `submission.materials_check` 里也有）：
  - 都对得上为 `match`；
  - 有一处对不上为 `mismatch`，改过内容的文件就是这样；
  - 没有对不上、但找不到说明文件或说明文件读不了为 `unchecked`；
  - 没有发出文件为 null。

  `mismatch` 和 `unchecked` 都给警告，照样记录；`validate` 也把这两种投递列在警告里，不算错误。发出的文件和 build 出来、审过的那份对不上，比没法核对更要提醒。
- 上述是记录用户实际发出文件的归档口径，保留改名与手工修改文件的警告行为。交付前的 `review validate/show` 使用同一说明格式，但要求当前完整产物及逐文件名摘要一致，缺失或不符为错误；具体操作只维护在 [简历与沟通草稿工作流](resume-workflow.md)。
- 说明文件只列这次 build 实际写出的文件。一个文件都没写出来（例如 PDF 生成失败）时不写说明文件，也不覆盖原来那份：原来的文件和原来的说明文件还对得上。build 失败时的退出码和输出照旧。
- `resume build` 的输出里多一项 `build_note`，是说明文件的路径；没写说明文件时为 null。

## 13. 跟进（`followup` 和 `list --due`）

- `followup <投递id> --due YYYY-MM-DD`：设跟进日期，只到天。日期可以是北京时间的今天或以后，不能是过去（多半是输错了）；"本该上周跟进"就写今天。这条只拦新请求：今天写成的请求，明天用同一个 `request_id` 重试，照样返回第一次的结果（第 8 节）。`--cancel` 取消，没设时报 `invalid`。
- 只用于 `applied`、`interview`、`offer`（第 4 节）。进入终结状态或 `no_response` 时跟进日期清空：`no_response` 是用户说不等了，不再提醒；迟到的回复来了、状态变了，可以再设。
- `list --due [--as-of 日期]` 输出 `{"as_of", "due", "unset"}`，每项是 `list` 的一行：
  - `due`：状态是那三种、`next_followup_on` 不晚于 `as_of` 的。多一项 `days_overdue`，当天到期为 0。按跟进日期从早到晚排，同一天按 `application_id`。
  - `unset`：状态是那三种、没设跟进日期的，不算逾期。按投出日期从早到晚排，等得最久的在前，日期未知的排最后。
  - `drafted`、终结状态和 `no_response` 都不列。
  - 不带 `--as-of` 时按北京时间的今天。`--as-of` 可以是任何一天，只能和 `--due` 一起用。`--status`、`--job` 先筛一遍。
- 到期提醒和跟进消息的起草是 M4-2，这里只存日期。

## 14. 作废（`void`）

- 作废最近一条"没被作废、本身也不是作废"的事件。连着作废就一条一条往前退；更早的错，先把后面的作废，再重记。
- 作废事件本身不能作废：作废错了，把那条事件重新记一次。
- 不能作废 `created`，只剩它时报 `invalid`，因为作废它等于删掉整条投递。记错的整条投递这样处理：
  - 现在的投递：先作废 `submitted`（回到 `drafted`），再 `status withdrawn --reason 记错了`。这样它从没算投出过。
  - 补录的投递本来就是"已投出"，它的 `submitted` 不能单独作废（报 `invalid`），直接 `status withdrawn --reason 记错了`。
- 什么都不删：被作废的事件留着，`voided_by` 指向作废它的事件；状态由其余事件重放得出。`revision` 照常加 1。
- 作废 `submitted` 以后：
  - 回到 `drafted`：`submission.confirmed` 为 false，投出时间、`materials_recorded`、`materials_check` 为 null。它们只看没被作废的 `submitted`。
  - 归档的材料版本还在 `material_versions` 里，文件不删，`validate` 照样核对。以后再 `submit` 会建新的材料版本；现在用的是有效 `submitted` 事件的 `material_version_ids` 指的那份。
  - 岗位和评分快照沿用第一次的。
- `--reason` 必填。预览的 `voids` 给出要作废的那条事件，给用户看清楚再提交。

## 15. 备份和恢复

`backup` 一步执行，不预览：它不改任何记录。写到 `applications/backups/<UTC 时间 YYYYMMDDTHHMMSSZ>/`，同一秒已经有的加 `-2`、`-3`。里面有：

- `applications.sqlite3`：用 SQLite 的备份接口（`Connection.backup`）做的一致快照。别人正在写时最多等 5 秒，从开始备份算起（打开数据库也算在内），不管锁是开始前就有、还是复制途中才来；超时报 `busy`，删掉这次的 `.tmp/`，原库不动。
- `artifacts/…`：快照里登记的归档文件，相对路径不变。数据库要和它引用的附件一起备份（[#110 §7](m4-0-store-decision.md)），只有清单的话附件丢了就恢复不了。只复制路径合第 10 节规则、真实位置在 `artifacts/` 里的文件；不合规则的不复制，给警告，`source_valid` 为 false，备份目录以外什么也不写。
- `manifest.json`：

  ```json
  {"schema_version": 1, "kind": "applications-backup", "created_at": "2026-11-04T08:30:00Z",
   "database": {"name": "applications.sqlite3", "sha256": "…", "size_bytes": 0, "user_version": 1},
   "counts": {"applications": 0, "events": 0},
   "artifacts": [{"path": "artifacts/app_…/mv_…/sent-1.pdf", "sha256": "…", "size_bytes": 0}],
   "source_valid": true}
  ```

  `source_valid` 是对这份快照跑 `validate` 的结论。不通过也照样备份，留住现状，输出里给警告。

其他规则：

- 先写进 `<名字>.tmp/`，复制的文件读回核对摘要，写好清单再改名。进程中途被杀留下的 `.tmp/`，由 `validate` 列在 `orphans` 里，用户同意后再删。
- 没有投递记录时报 `not_found`，什么也不写。
- `validate --backup <名字>` 只读核对一份备份：清单在；数据库文件和清单记的摘要一样；再对备份目录跑和 `validate` 一样的检查；清单列的每个附件路径也合第 10 节的规则，文件都在，摘要和大小对。

恢复没有命令，手工做：

1. 停止所有 Agent 的写入；
2. 跑 `validate --backup <名字>`，要通过；
3. 把现在的 `applications.sqlite3` 和 `artifacts/` 移到别处保留，不删；
4. 把备份里的 `applications.sqlite3` 和 `artifacts/` 复制进 `applications/`；
5. 跑 `validate`。

不要恢复到正在使用的库上，也不要把不同时间的数据库和日志文件拼在一起（#110 §7）。Agent 只在用户要求时备份，不自动定期备份。备份和数据库一样是明文的私密材料，在 `data/` 下，不进 git。

## 16. Agent 工作流（`cn-application`）

Claude Code 和 DeepSeek Harness 的 `cn-application` 技能、Codex 的 `AGENTS.md` 都按这一节做。

用户要复盘投递、对比历史评分和已记录面试结果，或根据结果讨论偏好时，转 [calibration.md 的复盘工作流](calibration.md#1-agent-工作流)。`retrospective` 是只读命令，无需写入预览；需要调权时由该工作流显式交接 `cn-match`，不扩大 `cn-application` 的命令授权。

**规则**

1. 只记用户说的事。不替用户投递，不联系招聘方，不联网查进展。
2. **先预览，用户同意后再写**：
   - 每次写入先带 `--preview` 运行，把要写的事件、新旧状态、警告（作废时还有 `voids`）用中文讲给用户听；
   - 用户明确同意后，用同样的参数加预览给的 `--request-id` 再运行一次；
   - 不自己编 `request_id`，不跳过预览。
3. `--actor` 写自己：Claude Code 写 `claude_code`，Codex 写 `codex`，DeepSeek Harness 写 `dsh`。
4. 不用上游的 `/outcome`、`/apply` 记投递：它们写的是上游自己的 `job_search_tracker.csv` 和 `documents/applications/`，和这里的记录不通。
5. 回复摘要、备注、原因只写用户说的话，不写联系方式、邮件全文、链接。
6. 时间问清楚（第 5 节）。用户说"刚投了"，写今天的日期，并告诉用户写的是哪天。

**步骤**

1. **找岗位和已有的投递**：
   - 岗位 id 用 `python -m jobsearch_cn jd list`、`python -m jobsearch_cn jd show <岗位id>` 找；
   - 已有的投递和它的 `revision` 用 `python -m jobsearch_cn application list --job <岗位id>`、`python -m jobsearch_cn application show <投递id>` 看。
   - 现在的投递，岗位要先导入岗位库（`cn-jd-import`）；以前投的可以补录（第 7 节）。
2. **记投递**：`python -m jobsearch_cn application record` 新建；已起草的投出了用 `python -m jobsearch_cn application submit`。有简历文件就带 `--material` 和 `--sent`（第 6 节）；发的是沟通草稿（打招呼语、邮件、内推请求）时，带它的材料和 `data/messages/<岗位id>/` 下的 `.txt`。用平台在线简历投的没有文件，照样记，并告诉用户"材料未记录"。
3. **记进展**：
   - 状态变了用 `python -m jobsearch_cn application status`，对方说了什么写进 `--reason`；
   - 状态没变的回复用 `python -m jobsearch_cn application reply`（第 4 节）；
   - 备注用 `python -m jobsearch_cn application note`；
   - 跟进日期用 `python -m jobsearch_cn application followup`。
4. **输错了**：`python -m jobsearch_cn application void` 作废最近一条（第 14 节）。
5. **别人刚写过**：报 `stale_revision` 时，重新 `show`，把新写的事件告诉用户，再重新预览。报 `busy` 时稍后再试。
6. **待跟进**：`python -m jobsearch_cn application list --due`，把 `due` 和 `unset` 讲给用户。跟进消息的起草是 M4-2，现在不做。
7. **核对和备份**：
   - 用户问记录对不对时跑 `python -m jobsearch_cn application validate`；
   - 用户要备份时跑 `python -m jobsearch_cn application backup`；
   - 用户要导出时跑 `python -m jobsearch_cn application export`；
   - 手工恢复前先备份并核对（第 15 节）。
8. **每次写完**：告诉用户记了什么。警告要照实说：材料未记录、`mismatch`、`unchecked`、像联系方式的文字。
