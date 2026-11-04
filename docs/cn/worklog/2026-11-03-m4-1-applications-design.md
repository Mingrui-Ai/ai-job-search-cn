# 2026-11-03 · M4-1 投递记录：设计稿（Claude A，待规划者确认）

分支 `feat/cn-m4-1-applications-design`，从 master 90e30e0 开。本文件只写设计，没有代码。规划者确认后，正式规格写进 `docs/cn/applications.md`（三个 Agent 共用），本文件留作设计记录。

**依据**

- [M4-0 存储决策备忘](../m4-0-store-decision.md)（#110）：数据格式草案、并发、备份、查询口径；
- 经理意见书-005 第 3 项：选 A，SQLite，数据库放在 `cn\data\applications\`，照 #110 的建议做；
- [路线图 §6 M4](../roadmap.md#6-m4--v04-投递记录跟进与看板)：M4-1 格式和命令，M4-2 跟进，M4-3 复盘，M4-4 看板，M4-5 两周真实使用。

下文"#110 §x"指备忘的章节。本设计默认沿用 #110 的提案，只写定稿的取舍和 #110 留给 M4-1 定的细节；和 #110 不同的地方单独标出。

## 1. 范围

**M4-1 做**：数据库和表结构；记一次投递（含"只起草、还没投"）；确认投出；改状态；记回复、备注；设置和取消跟进日期（只存日期，提醒和起草是 M4-2）；作废最近一条事件（输错时用）；查看、列表、校验、导出 JSON、备份；Agent 共用的工作流说明和四个入口。

**M4-1 不做**：从导出恢复（import），留给 M4-1b，见裁定 1；任意一条历史事件的更正（#110 的 `event_corrected`），v1 只能作废最近一条，见裁定 6；跟进提醒和消息起草（M4-2）；复盘（M4-3）；看板和漏斗统计（M4-4）；联网、代发、读取招聘平台。

## 2. 存放位置

| 路径（都在数据目录下，默认 `cn\data`） | 内容 |
| --- | --- |
| `applications/applications.sqlite3` | 唯一的投递数据库。`journal_mode=DELETE`，回滚日志 `applications.sqlite3-journal` 只在写事务中出现 |
| `applications/artifacts/<application_id>/<version_id>/` | 投出时冻结的材料：材料 JSON、实际发出的 PDF / Word，以及岗位和评分的快照。只写一次，不覆盖 |
| `applications/exports/` | `export --out` 只能写到这里 |
| `applications/backups/` | `backup` 写到这里 |

- 目录都经 `store.safe_dir` 创建，拒绝符号链接和 junction（#110 §4）。数据库文件本身是链接时拒绝打开。
- 只读命令（show、list、validate、export）在数据库不存在时返回"还没有投递记录"，不建空库（#110 §5.5）。

## 3. 表结构

数据库内的版本记在 `PRAGMA user_version`（初版 1）；打开时版本比程序新就拒绝写入，报"请更新程序"，不猜测兼容（#110 §7）。每个连接执行 `PRAGMA foreign_keys=ON` 并核对确实生效。

```sql
CREATE TABLE applications (
  application_id   TEXT PRIMARY KEY,           -- app_<32 位十六进制>，CLI 随机生成
  job_id           TEXT NOT NULL,              -- 不做外键：岗位在 JSON 文件里
  record_origin    TEXT NOT NULL CHECK (record_origin IN ('current','historical')),
  channel_kind     TEXT NOT NULL,              -- 枚举见 §4
  channel_platform TEXT,                        -- 例如"BOSS直聘"，可空，≤40 字
  status           TEXT NOT NULL,              -- 投影，validate 重放事件核对
  submitted        INTEGER NOT NULL CHECK (submitted IN (0,1)),
  submitted_at     TEXT,                        -- 和 submitted_on 互斥，都可空（日期未知）
  submitted_on     TEXT,
  next_followup_on TEXT,                        -- 投影；只到日期，见 §4
  revision         INTEGER NOT NULL,            -- 最后一条有效事件的 seq
  created_at       TEXT NOT NULL,              -- UTC，CLI 写入
  updated_at       TEXT NOT NULL
);
CREATE INDEX applications_job ON applications(job_id);
CREATE INDEX applications_status ON applications(status);
CREATE INDEX applications_followup ON applications(next_followup_on);

CREATE TABLE events (
  application_id TEXT NOT NULL REFERENCES applications(application_id),
  seq            INTEGER NOT NULL,
  event_id       TEXT NOT NULL UNIQUE,
  request_id     TEXT NOT NULL,
  type           TEXT NOT NULL,                 -- 枚举见 §4
  occurred_at    TEXT,                          -- 和 occurred_on 互斥，都可空
  occurred_on    TEXT,
  recorded_at    TEXT NOT NULL,
  actor          TEXT NOT NULL CHECK (actor IN ('user','claude_code','codex','dsh')),
  source_kind    TEXT NOT NULL CHECK (source_kind IN ('user','authorized_api')),
  payload        TEXT NOT NULL,                 -- JSON，按 type 校验；不用 JSON1 扩展查询
  voided_by      TEXT,                          -- 被作废时，作废它的事件 event_id
  PRIMARY KEY (application_id, seq)
);

CREATE TABLE requests (                          -- 重试去重（#110 §4）
  request_id     TEXT PRIMARY KEY,
  request_hash   TEXT NOT NULL,                  -- 规范化请求内容的 SHA-256
  application_id TEXT NOT NULL REFERENCES applications(application_id),
  first_seq      INTEGER NOT NULL,
  last_seq       INTEGER NOT NULL
);

CREATE TABLE material_versions (
  version_id      TEXT PRIMARY KEY,              -- mv_<32 位十六进制>
  application_id  TEXT NOT NULL REFERENCES applications(application_id),
  kind            TEXT NOT NULL CHECK (kind IN ('resume')),   -- M3-4 的沟通材料以后加
  material_path   TEXT,                          -- 原材料相对数据目录的路径，只作来源说明
  material_hash   TEXT,                          -- review.material_hash，和审核结果里的同一个值
  profile_hash    TEXT,                          -- 抄材料里的
  review_path     TEXT,                          -- 对这个 material_hash 通过的最后一轮审核结果，没有为 null
  created_at      TEXT NOT NULL
);

CREATE TABLE material_files (
  version_id TEXT NOT NULL REFERENCES material_versions(version_id),
  file_id    TEXT NOT NULL,                      -- 版本内编号：material、pdf、docx
  role       TEXT NOT NULL,                      -- source（材料 JSON）或 sent（发出的文件）
  path       TEXT NOT NULL,                      -- artifacts 下的相对路径
  sha256     TEXT NOT NULL,                      -- 归档文件实际字节的摘要
  size_bytes INTEGER NOT NULL,
  PRIMARY KEY (version_id, file_id)
);

CREATE TABLE snapshots (                         -- 投出时的岗位和评分（#110 §5.1 context_snapshot）
  application_id TEXT NOT NULL REFERENCES applications(application_id),
  kind           TEXT NOT NULL CHECK (kind IN ('job','match')),
  path           TEXT,                           -- artifacts 下；当时没有评分时为 null
  sha256         TEXT,
  PRIMARY KEY (application_id, kind)
);
```

**材料版本怎么认**（规划者要求"用 material_hash"）：

- `material_hash` 用 `review.material_hash`（材料 JSON 的规范化 SHA-256），和审核结果里记的是同一个值，所以能找到这份材料对应的审核。
- 材料文件会被原地修改（简历工作流第 1 节第 3 步），`resumes/` 下的 PDF 重新生成会被覆盖，只记路径和摘要以后就找不回当时的文件。所以投出时把材料 JSON 和实际发出的文件**复制**进 `artifacts/`，记实际字节的 SHA-256（#110 §5.3）。`material_path` 只说明来源，不作为以后读取的位置。
- 投出时核对：材料能通过 `material validate`（档案改过只给警告，不拦）；发出的文件在 `resumes/<岗位id>/` 下，文件名编号和材料一致（`resume-<n>.json` 对 `resume-<n>.pdf`）。PDF 是不是用当前这版材料生成的，现在没有办法核对，见裁定 4。
- 用户手工改过 Word 再发出的，归档的是改过的那份（#110 §5.3），由 `--sent` 指定文件；不在 `resumes/` 下时给警告，不拦。

## 4. 事件、状态和时间

**事件类型**（v1）：

| type | 谁触发 | payload |
| --- | --- | --- |
| `created` | `record` | `{job_id, record_origin, channel}` |
| `submitted` | `record --submitted` 或 `submit` | `{channel, version_ids, sent_file_refs}`；`sent_file_refs` 是 `[{version_id, file_id}]` |
| `status_changed` | `status` | `{from, to, reason}`，`reason` ≤300 字，可空 |
| `reply_received` | `reply` | `{summary}`，≤300 字；只记"收到回复"这件事，不改状态 |
| `note_added` | `note` | `{text}`，≤300 字 |
| `followup_scheduled` | `followup` | `{due_on}` |
| `followup_cancelled` | `followup --cancel` | `{}` |
| `event_voided` | `void` | `{target_event_id, reason}`，只能作废最近一条有效事件（裁定 6） |

M4-2 要加的 `followup_drafted`、`followup_sent` 留给 M4-2 定，表结构不用改（`type` 不设 CHECK，由程序校验，加新类型不迁移表）。

**渠道** `channel_kind`：`portal`（招聘平台）、`company_site`（公司官网）、`email`、`referral`（内推）、`campus`（校招宣讲、双选会）、`offline`、`other`、`unknown`。`platform` 是平台名，可空。不存 URL、账号、Cookie、邮箱地址（#110 §5.1）。

**状态**和允许的变化（照 #110 §5.2，这里定死）：

| 现在 | 可以变成 |
| --- | --- |
| `drafted` | `applied`（只能经 `submit`）、`withdrawn` |
| `applied` | `interview`、`offer`、`rejected`、`withdrawn`、`no_response` |
| `interview` | `offer`、`rejected`、`withdrawn`、`no_response` |
| `offer` | `hired`、`offer_declined`、`rejected`（对方收回）、`withdrawn` |
| `no_response` | `interview`、`offer`、`rejected`（迟到的回复；`reason` 必填） |
| `hired`、`rejected`、`withdrawn`、`offer_declined` | 不能再变；输错了用 `void` 作废那条状态事件 |

- 多轮面试不加状态，用 `reply` 或 `note` 记"二面"。
- `no_response` 只在用户说"不等了"时记，不由到期自动判定（#110 §5.2）。
- 进入终结状态时，`next_followup_on` 清空。

**时间**：

- 事实发生时间 `occurred_at`（带时区的时刻，存 UTC）或 `occurred_on`（只知道日期，`YYYY-MM-DD`），两者互斥，都不知道时都为 null；`recorded_at` 是写入时刻，必有。补录上周的投递，两个时间不同（#110 §5.2）。
- 命令行只接受 `--on 2026-11-02`（日期）或 `--at 2026-11-02T14:30+08:00`（必须带时区），不写时为未知。不把"今天"当默认值：用户说"刚投了"，由 Agent 问清或写今天的日期并告诉用户。
- 跟进日期只到天（`due_on`）。显示和按天分组用 Asia/Shanghai。

**投影**：`status`、`submitted*`、`next_followup_on`、`revision` 由有效事件（`voided_by` 为空）按 seq 重放得到，写事件时在同一事务里更新；`validate` 重放核对。

## 5. 命令

命令组 `application`（裁定 2）。写操作都分两步：先 `--preview`，输出要写的事件、新旧状态和一个 `request_id`，不写任何东西；Agent 给用户看、用户确认后，带同一个 `--request-id` 再运行一次才写入（#110 §5.5 的"先预览再提交"）。同一个 `request_id` 重试，内容相同就返回原结果，不同就报冲突。

| 命令 | 作用 |
| --- | --- |
| `application record <岗位id> --channel KIND [--platform 名称] [--submitted [--on 日期 \| --at 时刻]] [--material 材料文件 --sent 文件 ...] [--historical] [--note 文字]` | 新建一次投递。不带 `--submitted` 是 `drafted`；带了是 `applied`，同一事务写 `created` 和 `submitted` |
| `application submit <投递id> --expected-revision N [--on \| --at] [--material ... --sent ...]` | `drafted` 确认投出 |
| `application status <投递id> <新状态> --expected-revision N [--reason 文字] [--on \| --at]` | 改状态，按 §4 的表检查 |
| `application reply <投递id> --summary 文字 --expected-revision N [--on \| --at]` | 记收到回复 |
| `application note <投递id> --text 文字 --expected-revision N` | 备注 |
| `application followup <投递id> (--due 日期 \| --cancel) --expected-revision N` | 设置或取消跟进日期 |
| `application void <投递id> --reason 文字 --expected-revision N` | 作废最近一条有效事件 |
| `application show <投递id>` | 一条投递的完整内容，格式同导出 |
| `application list [--status S ...] [--job 岗位id] [--due [--as-of 日期]]` | 列表，按最近提交时间倒序；`--due` 见 §8 |
| `application validate` | 整库检查：外键、事件连续、投影重放一致、归档文件存在且摘要对、`artifacts/` 下有没有没登记的孤立文件 |
| `application export [<投递id> ...] [--out 文件名]` | 导出 JSON（§7）；不写 `--out` 时打印 |
| `application backup` | 用 `Connection.backup` 在 `backups/` 写一份数据库快照，附件清单和摘要写在旁边 |

公共参数：`--data-dir`（和其他命令一样）、`--actor`（默认 `user`；Agent 写自己的名字），都写进事件。

**输出和退出码**（和现有命令一致）：

- 成功：标准输出 JSON，退出码 0。写操作输出 `{"application": <导出格式的这条投递>, "events": [新写入的事件], "request_id": …, "preview": true|false}`。
- 业务上拒绝（参数不合规则、状态不允许、revision 过期、request_id 内容冲突、数据库忙）：标准错误输出 `{"error": "<代码>", "message": "…", …}`，退出码 1。代码有 `invalid`、`transition`、`stale_revision`（附当前 revision 和这之后的事件）、`request_conflict`、`busy`。
- 读不了（文件不存在、不是 JSON、数据库版本比程序新、没有 sqlite3 模块）：退出码 2，和 `InputError` 一样。
- `validate` 照校验命令的惯例：`{"valid": …, "errors": […], "warnings": […]}`，不通过退出码 1。

## 6. 几个 Agent 同时写

照 #110 §4：

- 每条命令一个短连接；写操作 `BEGIN IMMEDIATE`，锁等待 5 秒，超时报 `busy`，不无限等。
- 事务内重新读 `revision`，和 `--expected-revision` 不同就报 `stale_revision`，把对方新写的事件带回去，让 Agent 重新读、告诉用户，不自动覆盖。
- 事务里不等用户、不生成 PDF、不联网。归档文件在事务**之前**写好：先写到 `artifacts/<application_id>/<version_id>.tmp/`，核对摘要后改名为正式目录，再开事务登记。事务失败时留下的目录由 `validate` 列为孤立文件，用户确认后清理，不当作已投递。
- 新建投递没有 revision 可比；同一岗位已有未结束的投递时给警告（可能重复记了），不拦：同一岗位换渠道再投是允许的（#110 §5.1）。
- `journal_mode=DELETE`，不开 WAL（#110 §4）。数据库只放本机磁盘；放在云盘同步目录里的风险写进说明。

## 7. 导出格式

导出是 #110 §5.4 的格式，字段名照它，加上 v1 定下的几处：

- `next_followup_at` 改名 `next_followup_on`，只到日期；
- `material_versions[]` 每项带 `material_hash`、`profile_hash`、`review_path` 和 `files[]`；
- `context_snapshot` 为 `{"job": {path, sha256} | null, "match": {path, sha256} | null}`；
- 事件带 `voided_by`。

顶层是 `{"schema_version": 1, "exported_at": …, "applications": [...]}`。按 `application_id`、事件 seq 排序，键顺序固定，UTF-8，同样的数据导出两次逐字节相同（`exported_at` 除外）。导出不带附件内容，只带清单。导入（M4-1b）读的是同一个格式。

## 8. 给后面几步的接口（只定接口，不做）

- **M4-2 跟进提醒**：`application list --due [--as-of 日期]` 返回已投出、没结束、`next_followup_on` ≤ 那天的投递；另列 `unset`：已投出、没结束、没设跟进日期的，不算逾期（#110 §6）。跟进消息的起草和 `followup_drafted`、`followup_sent` 两种事件由 M4-2 加。
- **M4-3 复盘**：从导出的 `context_snapshot.match` 读投出时的评分原件（含当时的权重和规则版本），和后来的状态比对。
- **M4-4 看板**：读 `application export` 的全量 JSON 自己算。当前状态分布和"曾到达"漏斗分开、按投递和按岗位分开计数、日期未知单列，口径照 #110 §6，由 M4-4 实现和测试。
- **简历工作流**：`resume-workflow.md` 第 4 节"交给用户"之后加一句：用户投出后，按投递记录工作流记一次。只加链接。

## 9. 隐私

- 数据库、附件、导出、备份都只在数据目录下；`--out` 只收文件名，写到 `applications/exports/`，不接受路径。
- `.gitignore` 已忽略 `/data/`；测试再核对 `data/applications/` 下的 `-journal`、`-wal`、`-shm`、`exports/`、`backups/` 都被忽略。
- 事件文字（原因、回复摘要、备注）只存用户说的话，Agent 不往里写联系方式、邮件全文、链接；文档写明，`validate` 对其中像手机号、邮箱、URL 的内容给警告。
- `show`、`list`、`export` 不带档案的联系方式，归档的材料 JSON 本来也不含联系方式（材料只引用档案）。
- 本地明文存储，不是加密（#110 §8）。

## 10. 测试和示例

- 全部用公开虚构数据：档案和材料用 `tests/fixtures/cn/material/tech-m3`，岗位用 `tests/fixtures/cn/jd/` 下的虚构 JD，数据库建在临时目录。新的固定样例放 `tests/fixtures/cn/applications/`，全部虚构。
- 不读 `cn\data`；测试里的数据目录都显式指定。
- CI 的 Python 3.10–3.14 都跑；运行时检查 `sqlite3` 模块和 SQLite 版本，缺失时报清楚。

## 11. 验收标准（审核者 Codex B）

1. 表结构、版本、外键：新库建出 §3 的表，`user_version` 为 1；外键生效；版本更高的库拒绝写入，退出码 2。
2. 状态：§4 表里每一对允许的变化能写入，其余都拒绝（`transition`）；终结状态不能再变；`void` 只能作废最近一条，作废后投影回到之前。
3. 预览和重试：`--preview` 不写任何东西，数据库不存在时也不建库；同一个 `request_id` 重试内容相同返回原结果、不重复写，内容不同报 `request_conflict`。
4. 并发：两个进程拿同一个 revision 写，一个成功，另一个报 `stale_revision`；另一进程持有写锁超过 5 秒时报 `busy`。事件、投影、请求表都没有写了一半的情况。
5. 材料：投出时材料 JSON 和发出的文件被复制、摘要对；之后改材料、重新生成 PDF、改档案，归档和摘要不变；删掉一个归档文件，`validate` 报出来。归档写到一半中断，`validate` 列出孤立目录，数据库里没有它。
6. 时间：只知道日期、知道时刻、都不知道三种都能记，导出时保持原样，不补成午夜或今天；不带时区的 `--at` 拒绝。
7. 只起草不投：只有 `drafted`，`list --due` 不列；同一岗位两个渠道是两条投递。
8. 导出：同一状态导出两次内容相同（`exported_at` 除外）；`--out` 带路径时拒绝。
9. 隐私：`git check-ignore` 覆盖 §9 列的文件；导出和 show 里没有档案的联系方式。
10. 入口：三个 Agent 的入口指向同一份 `docs/cn/applications.md`；`test_cn_agent_entry` 覆盖新技能；文档里的每条命令都存在。
11. 只读命令（show、list、validate、export）不建库、不写文件（export 带 `--out` 除外）。

另外建议照前几个功能的做法，由 Codex A 做留出样例（V 项）：几段虚构的投递经历（补录、换渠道、迟到回复、输错作废），PR 开出前冻结。

## 12. 实现拆分（建议）

| 部分 | 内容 | 预计 |
| --- | --- | --- |
| M4-1a | 数据库、事件和状态、`record`/`submit`/`status`/`reply`/`note`/`followup`/`void`、`show`/`list`/`validate`/`export`、归档、并发、测试 | 主体 |
| M4-1b | `backup`、`import`（从导出恢复到新库）、工作流文档和四个入口、`security_guards` 授权 | 小 |

也可以合成一个 PR；分开的话 a 先合并，b 再接入口。

## 13. 要裁定的问题

1. **范围**：import（从导出恢复）放 M4-1b 还是 v1 不做？我的建议：M4-1b 做，因为"备份能恢复"是 #110 §9 的验收项。
2. **命令组名**：用 `application`，不用 #110 写的 `apply`。理由：`apply` 和上游 `/apply`（起草 + 审核求职材料）重名，读起来也像"代为投递"。
3. **归档材料**：投出时复制材料 JSON 和发出的文件（建议，#110 §5.3），还是只记路径和摘要？只记的话，材料原地改过、PDF 重新生成以后就找不回当时投的是什么。
4. **PDF 和材料版本对不对得上**：现在 `resume build` 不记录它用的是哪一版材料，归档时没法核对"这份 PDF 就是这个 material_hash 生成的"。可选：(a) `resume build` 在 PDF 旁写一个小的说明文件，记 `material_hash`，M4-1 投出时核对（要改 `resume build`，是 Claude C 的代码，小改动）；(b) 不核对，只记用户指定的文件和摘要，文档写明。我建议 (a)，单独一个小 PR，在 M4-1a 之前或一起做。
5. **先预览再提交**：写操作必须先 `--preview` 拿 `request_id`，再带着它提交（建议），还是允许一步写入？一步写入少一次调用，但用户没看过就写进去了，重试也没法去重。
6. **输错了怎么改**：v1 只能作废最近一条有效事件（`void`），更早的错要先把后面的作废，再重记。#110 的 `event_corrected`（指向任意一条事件、带改正值）要逐条重算后续状态是否还合法，复杂得多，建议等真实使用里确实需要再做。
7. **补录历史投递**：v1 支持 `--historical`（建议）。M4-5 要连续两周记真实投递，开始前经理多半已经投过一些；补录的允许没有材料、日期未知，导出和列表里标出来，不要求当时的岗位和评分快照。
8. **入口和授权**：技能名 `cn-application`，授权 `Bash(python -m jobsearch_cn application:*)`，要改 `tools/security_guards.py`，届时用 AskUserQuestion 请经理本人同意。

## 14. 规划者裁定（cn-fa，2026-11-03）

1. import：v1 不做，记进路线图待办；恢复先靠 `backup` 的数据库副本。M4-1b 只剩 backup、入口和授权。
2. 命令组叫 `application`：同意。
3. 投出时把材料 JSON 和实际发出的文件复制进 `artifacts/`，记字节 SHA-256：同意。
4. 选 (a)：`resume build` 在 PDF 旁写说明文件，至少记 `material_hash`，再加 `profile_hash` 和生成时间，投出时核对。由 Claude A 在 M4-1a 里改，等 #119（也改 `resume build` 和 `cli.py`）合并后再动；格式写进 `applications.md`。M3-6 的 `material render --output` 会照同样的格式写一份。
5. 先预览、再带 `request_id` 提交：同意。
6. v1 只能作废最近一条事件，`event_corrected` 等真实使用里需要再做：同意。
7. 支持补录历史投递（`--historical`，可以没有材料、日期未知）：同意。
8. 技能 `cn-application`、授权 `application:*`：同意，放在 M4-1b；改 `security_guards.py` 前用 AskUserQuestion 请经理本人同意。

实现要求：M4-1a 的 PR 带正式文档 `docs/cn/applications.md`，工作记录只留过程；`cli.py` 里 `application` 命令组的代码放在独立的一块，不改别的命令组；只用公开虚构数据；审核者 Codex B；Codex A 做留出样例 V25，PR 开出前冻结，Claude A 不看 holdout clone 和 `codex/v*` 分支。

**切法（Claude A 定）**：

- M4-1a：存储、`record`、`submit`、`status`、`show`、`list`、`validate`、`export`、`resume build` 的说明文件，以及 `applications.md`。
- M4-1b：`reply`、`note`、`followup`（含 `list --due`）、`void`、`backup`，工作流、入口和授权。

M4-1a 只建状态主线，审核集中在存储、并发、归档和状态表；M4-1b 的几种事件只追加记录，不碰归档。入口和授权要到 M4-1b 才有，所以 M4-1a 合并以后 Agent 还不会用它，在那之前缺 `void` 不会让真实记录出错。
