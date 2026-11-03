# 投递记录（Application v1，M4-1）

记下用户的每一次投递：投了哪个岗位、走的什么渠道、什么时候投的、发出去的是哪份简历，以及后来的进展。记录存在本机的一个 SQLite 数据库里，状态由事件推出，投出时发出的文件复制归档。三个 Agent（Claude Code、Codex、DeepSeek Harness）都按本文件读写。

设计和裁定见 [设计稿](worklog/2026-11-03-m4-1-applications-design.md)（§14 是规划者的裁定），存储的取舍见 [M4-0 存储决策备忘](m4-0-store-decision.md)。

**M4-1a（本文件现在覆盖的部分）**：`record`、`submit`、`status`、`show`、`list`、`validate`、`export`。**M4-1b 再加**：`reply`、`note`、`followup`（含 `list --due`）、`void`、`backup`，以及工作流、Agent 入口和命令授权。M4-1b 合并之前，Agent 不会自己调用这些命令。

## 1. 存放位置

都在数据目录下（默认 `cn\data`，`--data-dir` 或环境变量 `JOBSEARCH_CN_DATA_DIR` 可改）：

| 路径 | 内容 |
| --- | --- |
| `applications/applications.sqlite3` | 唯一的投递数据库。回滚日志 `applications.sqlite3-journal` 只在写入时出现 |
| `applications/artifacts/<投递id>/mv_…/` | 一次投出时归档的材料 JSON 和发出的文件 |
| `applications/artifacts/<投递id>/ctx_…/` | 第一次投出时的岗位记录和评分记录（快照） |
| `applications/exports/` | `export --out` 只写到这里 |

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

- `seq` 从 1 起连续编号；`request_id` 是写入它的那次请求（第 8 节）。
- `actor` 是 `user`、`claude_code`、`codex`、`dsh` 之一，命令的 `--actor` 给，默认 `user`。
- `source.kind` 现在总是 `user`：记录的都是用户说的事。`authorized_api` 留给以后经授权的接口。
- `voided_by` 留给 M4-1b 的 `void`，现在总是 null。

## 4. 状态

| 现在 | 可以变成 |
| --- | --- |
| `drafted`（只起草，还没投） | `applied`（只能用 `submit`）、`withdrawn` |
| `applied` | `interview`、`offer`、`rejected`、`withdrawn`、`no_response` |
| `interview` | `offer`、`rejected`、`withdrawn`、`no_response` |
| `offer` | `hired`、`offer_declined`、`rejected`（对方收回）、`withdrawn` |
| `no_response` | `interview`、`offer`、`rejected`（迟到的回复，必须写 `--reason`） |
| `hired`、`rejected`、`withdrawn`、`offer_declined` | 不能再变 |

- 表里没有的变化报 `transition`，什么也不写。输错了的状态，到 M4-1b 用 `void` 作废那条事件。
- 多轮面试不加状态，M4-1b 用 `reply` 或 `note` 记"二面"。
- `no_response` 只在用户说"不等了"时记，不由日期自动判定；没收到回复不等于被拒。
- 状态存在数据库里方便查询，但它是事件的投影：写入和 `validate` 都用同一个函数（`applications.replay`）从事件重放出来。

## 5. 时间

- 事情发生的时间只有三种写法：`--at 2026-11-02T14:30+08:00`（知道时刻，必须带时区，存成 UTC 的 `…Z`）、`--on 2026-11-02`（只知道日期）、都不写（不知道）。都不写时两个字段都是 null，**不补成今天，也不补成午夜**。用户说"刚投了"，Agent 问清楚或写今天的日期，并告诉用户写的是哪天。
- 不能是将来：`--on` 不能晚于北京时间的今天，`--at` 不能晚于现在 5 分钟以上。
- `recorded_at`、`created_at`、`updated_at` 是写入的时刻，由命令自己写。
- 列表按北京时间（Asia/Shanghai）排日期。

## 6. 材料和归档

投出时（`record --submitted` 或 `submit`）可以带：

- `--material`：这次投的简历的材料文件（`data/materials/<岗位id>/resume-<n>.json`）；
- `--sent`：实际发出的文件，一个或几个（PDF、Word）；用户手工改过 Word 再发的，就给改过的那份。

写入前先检查：

- 材料要能通过 `material validate`（对照当前档案；档案改过只给警告），而且必须是这个岗位的材料；
- 发出的文件不在 `resumes/<岗位id>/` 下、或者文件名和材料编号对不上，给警告，照样记录；
- 发出的文件用 `resume build` 的说明文件核对（第 12 节）；对不上、找不到说明文件，都给警告，照样记录；
- 材料旁边有通过了这一版材料的审核结果（`review-<n>-r<轮次>.json`，`material_hash` 相同、`verdict` 为 `pass`）时，记下最后一轮的路径（`review_path`）；没有时给警告。

然后把材料 JSON（`material.json`）和发出的文件（`sent-1.pdf`、`sent-2.docx`……，保留扩展名）**复制**进 `artifacts/<投递id>/mv_…/`，记下实际字节的 SHA-256 和大小。以后材料被改、PDF 重新生成、档案更新，归档和摘要都不变。`material_path` 只说明来源，以后不从那里读。

- `material_hash` 是 `review.material_hash` 算的值，和审核结果里记的是同一个，所以能对上这份材料的审核。`profile_hash` 抄材料里的。
- 第一次投出时（补录的除外）还把 `jobs/<岗位id>.json` 和 `matches/<岗位id>.json` 复制进 `ctx_…/`，供 M4-3 复盘看投出时的岗位和评分。
- 现在的投递投出时没有材料：照样记录，输出警告"材料未记录"，`submission.materials_recorded` 为 false，`validate` 也列出来。平台在线简历、网申表格这类投递就是这样，不能为了凑材料挡住。
- `--material`、`--sent` 只能和投出一起记；只起草（`drafted`）时不记材料。

## 7. 补录以前的投递

`record … --submitted --historical`：用户以前投过、现在才记。可以没有材料、日期未知，岗位不在岗位库里也行（给警告，只记岗位 id）。补录不做岗位和评分快照，也不报"材料未记录"。`--historical` 必须带 `--submitted`。

## 8. 命令

```text
python -m jobsearch_cn application record <岗位id> --channel KIND [--platform 名称] [--submitted [--historical] [--on 日期 | --at 时刻] [--material 材料 --sent 文件 ...]] (--preview | --request-id ID) [--actor A]
python -m jobsearch_cn application submit <投递id> --expected-revision N [--channel KIND] [--platform 名称] [--on | --at] [--material ... --sent ...] (--preview | --request-id ID) [--actor A]
python -m jobsearch_cn application status <投递id> <新状态> --expected-revision N [--reason 文字] [--on | --at] (--preview | --request-id ID) [--actor A]
python -m jobsearch_cn application show <投递id>
python -m jobsearch_cn application list [--status S ...] [--job 岗位id]
python -m jobsearch_cn application validate
python -m jobsearch_cn application export [<投递id> ...] [--out 文件名.json]
```

所有命令都接受 `--data-dir`；`record`、`submit` 还接受 `--profile`（检查材料用的档案）。

**先预览，再写入。** 写操作必须二选一：

1. `--preview`：只算不写（数据库不存在也不会建），输出要写的事件（`event_id`、`seq`、`recorded_at` 为 null）、新旧状态、要归档的文件和它们的摘要、警告，以及一个新的 `request_id`；
2. 用户看过、同意以后，同样的参数加 `--request-id <预览给的 id>` 再运行一次，才写入。

同一个 `request_id` 重试（例如没看到输出、不知道写没写成）：内容相同就返回第一次的结果，`repeated` 为 true，不重复写；内容不同（参数、材料或发出文件的字节变了）报 `request_conflict`，要重新预览。

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
  | `not_found` | 没有这条投递；或新建投递时岗位不在岗位库里 |

- 读不了：文件不存在、不是 JSON、不是投递数据库、数据库版本比程序新（"请更新程序"，什么也不读不写），标准错误输出 `{"error": …}`，退出码 2。
- `validate` 输出 `{"valid", "errors", "warnings", "orphans"}`，不通过时退出码 1。
- `list` 按投出时间倒序，没投出的在最后；每行带岗位库里的 `title`、`company`。
- `export` 顶层是 `{"schema_version": 1, "exported_at": …, "applications": [...]}`，按 `application_id` 排序，键顺序固定；同样的记录导出两次，除了 `exported_at` 逐字节相同。导出不带归档文件的内容，只带清单。`--out` 只收文件名（字母、数字、`.`、`_`、`-`，以 `.json` 结尾），写到 `applications/exports/`，不接受路径。

## 9. 几个 Agent 同时写

- 每条命令一个短连接，写入用 `BEGIN IMMEDIATE`，锁最多等 5 秒，超时报 `busy`，不无限等。
- 改已有投递时，事务里再读一次 `revision`，和 `--expected-revision` 不同就报 `stale_revision`，把别人新写的事件带回来。Agent 要重新读、告诉用户发生了什么，不能自动覆盖。
- 事务里不等用户、不生成 PDF、不联网。归档文件在事务**之前**写好：先写进 `….tmp/`，每个文件读回核对摘要，再改名成正式目录，然后开事务登记。事务没成功时删掉这次写的归档；进程在中途被杀掉留下的目录，`validate` 列在 `orphans` 里，数据库里没有它，不算投递，用户同意后再删。
- 第一次写入时建表也在同一个事务里，失败时一起回滚。
- 新建投递时，同一岗位已经有没结束的投递，给警告（可能记重了），不拦：换渠道再投是允许的。

## 10. 检查（`validate`）

- SQLite 自己的完整性检查和外键检查；
- 每条投递：id 和字段的格式，事件从 1 连续编号，每条事件的 payload 字段齐全、取值合法，重放得到的状态、投出时间、渠道、`revision` 和表里存的一致；补录的必须已投出；
- 事件引用的材料版本和发出文件都登记了；归档文件都在，字节的 SHA-256 和大小没变；现在的投递投出了，就要有快照记录；
- 请求表里每个 `request_id` 对应的事件确实是它写的；
- 警告：投出时材料未记录的投递；`materials_check` 为 `unchecked` 的投递（第 12 节）；原因、平台名里像手机号、邮箱、链接的文字；
- `orphans`：`artifacts/` 下没有登记的文件和目录。

## 11. 隐私

- 记录、归档、导出都只在数据目录下，本机明文存储，不加密。
- 原因、平台名只写用户说的话，Agent 不往里写联系方式、邮件全文、链接；写了 `validate` 和写入时都给警告。
- `show`、`list`、`export` 不带档案的联系方式；归档的材料 JSON 本来就只引用档案条目，不含联系方式。发出的 PDF、Word 里有联系方式，它们只在 `artifacts/` 里，导出只带摘要。

## 12. `resume build` 的说明文件（M4-1a 第二部分）

规划者 2026-11-03 裁定：`resume build` 每生成一次，在输出旁边写一个说明文件，记下这次用的是哪一版材料、生成了哪些文件。M3-6 的 `material render --output` 写 `.txt` 时用同样的格式。

- 位置和名字：`data/resumes/<岗位id>/resume-<n>.build.json`，即材料文件名去掉 `.json` 再加 `.build.json`。每次 build 覆盖上一次的。
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
  - 给了 `--material`：用这份材料的说明文件核对所有发出的文件。说明文件在 `resumes/<岗位id>/` 下，名字是材料文件名去掉 `.json` 再加 `.build.json`，就是 `resume build` 写的那个。发出的文件改了名字（例如另存为"姓名-岗位.pdf"）也照样核对。
  - 没给 `--material`：按每个发出文件自己的名字找它旁边的说明文件。`resume-<n>.<扩展名>` 找 `resume-<n>.build.json`，别的名字找去掉扩展名再加 `.build.json` 的那个。
- 核对的内容：发出文件的摘要要在说明文件的 `files` 里；给了 `--material` 时，说明文件里的 `material_hash` 还要等于材料的当前值。对不上只给警告（手工改过的 Word 就是这样），照样记录用户说发出的文件。
- 核对结果记进 `submitted` 事件的 `materials_check`（导出的 `submission.materials_check` 里也有）：
  - 都对得上为 `match`；
  - 有一处对不上为 `mismatch`，改过内容的文件就是这样；
  - 没有对不上、但找不到说明文件或说明文件读不了为 `unchecked`；
  - 没有发出文件为 null。

  `unchecked` 也给警告，照样记录，`validate` 也列出来。
- 说明文件只列这次 build 实际写出的文件。一个文件都没写出来（例如 PDF 生成失败）时不写说明文件，也不覆盖原来那份：原来的文件和原来的说明文件还对得上。build 失败时的退出码和输出照旧。
- `resume build` 的输出里多一项 `build_note`，是说明文件的路径；没写说明文件时为 null。
