# M4-0 · 投递记录存储决策备忘

状态：**建议稿，待规划者与用户裁定**。2026-11-01，基于 `origin/master@4405cb4`；对应 [路线图 M4](roadmap.md#6-m4--v04-投递记录跟进与看板) 和 [总体规划 D4](master-plan.md#7-待决事项)。本次只写文档、读取代码及公开技术资料，没有创建数据库、实现命令、迁移或读取真实数据。

## 1. 建议与范围

**建议 M4-1 的投递记录使用 SQLite，事件和当前状态在同一个事务中保存；岗位、档案、评分、求职材料继续使用现有 JSON 文件。** 三个 Agent 统一调用 Python CLI，以 JSON 查看、起草变更和导出记录。SQLite 是投递元数据的唯一持久存储，JSON 导出是供查看、比较和交换的快照，不做两边同时写入的第二套存储。

理由是 M4 同时需要“某次投递的状态与事件一致”和“跨岗位查漏斗、待跟进”，还可能有多个会话操作同一个本地数据目录。SQLite 已提供事务、约束与索引；JSON 也能完成任务，但要补齐进程锁、冲突检测、一致性查询及恢复机制。选择依据是这些正确性要求，不是未经测量的岗位数量或性能优势。

建议数据库位于 `<数据目录>/applications/applications.sqlite3`，不可变材料归档位于同目录的 `artifacts/`，导出和备份也留在数据目录内。此工作区的真实数据根固定为用户已有的 **`cn/data`**，各 Agent 通过 `--data-dir` 指向它，不在自己的工作树建立第二份真实库；本文不接触该目录。虚构验收使用另一个明确指定的隔离数据目录。

M4-0 不决定迁移 M1/M2，不实现投递发送，不新增服务、账号、模型 API、ORM 或外部数据库。是否采用建议、M4-1 的字段与命令名，仍需裁定；不改写已经确认的 D4 前半部分。

## 2. 现状：现有 JSON 能做什么

依据 [store.py](../../jobsearch_cn/store.py) 的 `Store`、`MatchStore`、`_write_json` 和 `safe_dir`：

- 岗位保存在 `jobs/<job_id>.json`，评分保存在 `matches/<job_id>.json`；`all()` 扫描文件、读取并排序，无法读取的文件以 warnings 报告；按 URL 找岗位也扫描记录。
- 写入使用同目录临时文件，再 `os.replace` 替换目标，避免正常进程中断时留下半份 JSON。它没有覆盖整个“读取旧值→合并→写回”的进程锁、版本比较或跨文件事务，也没有显式 `fsync`；不能把单文件替换等同于并发更新不丢失或断电持久性保证。
- 两个进程都读到版本 A，各改一处并写回，后写的完整记录可能覆盖先写的变更；这是根据代码路径推导的风险，本次没有做并发实验，也不声称发生过真实丢失。
- 数据目录可由 `--data-dir` 或环境变量选择；子目录拒绝符号链接/junction，减少写到数据根以外的风险。新增投递存储应延续这一边界。
- 岗位的 `new/ranked/skipped/...` 是岗位整理状态，不是投递状态；现有 `MatchStore.save` 覆盖同一岗位的评分，不保存历次评分历史。

[Material v1](material.md) 的 `resume-<n>.json` 记录选择和改写，渲染还要读取档案。现有 [profile_hash](../../jobsearch_cn/score.py) 排除了 contact 和 target.weights，因此**它是匹配语义摘要，不是整份简历或档案的文件版本号**。M4 必须能指出当时实际投出的文件，不能只指向会被覆盖的路径或当前评分。

## 3. JSON 与 SQLite 对比

| 维度 | 每条投递一个 JSON 文件，沿用现有方式 | SQLite，保留 JSON 接口 |
| --- | --- | --- |
| 并发写 | 不同文件可各写各的；同一投递的读改写需跨进程锁和 revision 检查。只给最终替换加锁不够。事件与状态放在一个文件可避免跨文件拆分，但仍有覆盖竞争。 | 同一数据库同时只有一个写事务，可有多个读事务；锁等待和冲突需明确处理。事务内一并追加事件、更新状态和 revision，CLI 仍须防止旧会话覆盖新事实。见 [事务说明](https://www.sqlite.org/lang_transaction.html)。 |
| 漏斗、待跟进查询 | 能实现，但每次扫描、解析、聚合；查询期间文件可能来自不同时间点。另建索引文件又要维护索引与原记录一致。 | 可在读事务的一致视图中关联投递、事件和材料，给状态/跟进日期等建索引。小数据下未必明显更快，本次不做性能承诺。 |
| 三个 Agent 都能读写 | 文本可直接读，但手改文件容易跳过校验、锁和事件记录，正式写入仍应走 CLI。 | Codex、Claude Code、dsh 都执行同一 CLI、接收 JSON，不要求模型读二进制或各写一套 SQL；读写能力取决于统一入口与数据目录，不取决于模型。 |
| 可审阅的 diff | 格式稳定时可直接比较文件；全文件重排会增加噪声。真实数据本就不进 git，不能以公开提交充当审计。 | 数据库文件本身没有有用的文本 diff；需稳定排序的 JSON 导出、变更预览和事件查看。用户比较本地导出，公开 PR 只放原创虚构样例。 |
| 状态与事件一致性 | 整条记录内的事件数组便于重放，但越写越长；若拆成单独事件文件，就要设计发布顺序与恢复。 | 状态投影、事件和材料关联可以同一事务提交；约束拦住重复事件、错引用。数据库不会自动验证业务事实，仍需 CLI 校验。 |
| 迁移成本 | 第一版最少新知识；后续转数据库要处理 ID、事件顺序、旧版本和故障恢复。 | 现在增加连接、表结构、迁移版本、导入导出及备份工作；M4 尚无 CN 投递库，首次接入没有理由搬迁已有 jobs/matches。 |
| 备份与恢复 | 停止写入后复制整套目录容易理解；逐个复制正在变化的文件不保证跨文件一致。 | 可用 [备份 API](https://www.sqlite.org/backup.html) 获得一致的数据库快照；附件还需一同备份。不能把正在写的数据库当普通文件随意复制、替换。 |
| 隐私 | JSON、归档和日志均为明文；容易误贴内容。被 git 忽略不等于加密。 | 普通 SQLite 文件同样不提供这里所需的静态加密；日志文件、导出、备份、附件也含私密信息。二进制不可读不代表隐私保护。 |
| 依赖与许可 | Python 标准库 json/pathlib，无新运行服务；项目继续 MIT。 | 使用标准库 sqlite3，但运行环境必须实际带有可用 SQLite 库；不增加 pip 依赖或服务。Python 按其发行许可，SQLite 核心为 public domain，不应误写成 MIT。详见 §8。 |
| 日常故障定位 | 可单独隔离坏文件，但不能像现有列表一样跳过坏记录后仍宣称漏斗完整。 | 需完整性检查、可解释的锁/版本错误和恢复步骤；单库受损可能影响全部投递，备份与导出是首版交付的一部分。 |

**如果选择继续 JSON**：建议一条投递包含完整事件数组，通过统一 CLI 对整次读改写加进程锁、核对 revision，再替换文件；查询应有一致性策略，坏文件必须让汇总明确标为不完整。这是可行备选，但不能直接照搬当前 `_write_json` 就声称满足 M4 并发要求。若用户优先选择手工编辑与单会话串行使用，可据此缩小 M4-1；本备忘仍推荐 SQLite。

## 4. SQLite 的最小落地边界（提案）

### 写入与冲突

一个 CLI 请求使用自己的短连接。接收并校验 JSON 后，开启显式短写事务，重新核对 `expected_revision`，再提交事件和状态；不要在事务中等待模型、用户确认、网络请求或生成 PDF。建议对需要读后写的请求使用 `BEGIN IMMEDIATE`，锁等待先采用有界超时（例如 5 秒，属提案），超时给结构化错误。旧 revision 冲突时请 Agent 重新读取、展示差异；不能自动覆盖。数据库串行写不等于解决了过时的业务意图。[事务语义](https://www.sqlite.org/lang_transaction.html)、[Python 连接参数](https://docs.python.org/3.10/library/sqlite3.html#sqlite3.connect)

每个变更带稳定 `request_id`，重试同一请求不生成重复事件：先查已提交的 request_id，同内容返回原结果，不同内容报冲突，然后才检查新请求的 revision。唯一约束保护 ID、请求和应用内事件序号。所有连接启用并核对外键支持，值通过参数绑定传递；JSON 正文里的引号和指令只作为数据。[SQLite 外键](https://www.sqlite.org/foreignkeys.html)

M4-1 建议先用回滚日志 `journal_mode=DELETE`，保留同步写保护，短读事务查完即关。它可能阻塞并发读写，应明确报忙而不是无限等待。WAL 作为后续测量后的选项：可以改善读写并行，但仍只有一个写者、产生 `-wal/-shm` 文件，并要求同机访问；不能因三个 Agent 就默认需要 WAL。启用前核对运行库版本及已知问题（官方记录了已修复的 WAL-reset 问题），不要只看 Python 版本。[WAL](https://www.sqlite.org/wal.html)、[原子提交与同步](https://www.sqlite.org/atomiccommit.html)

活动数据库限同一台机器的本地磁盘，不把它放在网络共享或双向云盘同步目录上让多个客户端同时改；将来若确有跨机器并发，应重新评估，不用文件同步冒充数据库复制。[适用范围](https://www.sqlite.org/whentouse.html)、[文件锁与损坏风险](https://www.sqlite.org/howtocorrupt.html)

### 与现有文件的边界

SQLite 事务不能一起提交外面的 PDF、Word、岗位 JSON。建议先把需要的材料复制到新的不可变版本目录，完成刷盘、关闭并核对 SHA-256，再以短事务登记这些引用与投递事件；普通写入失败时不产生引用半份文件的已提交记录。文件和目录持久化的平台差异需纳入故障验收，不能仅凭数据库提交就保证断电后整套附件齐全。事务前崩溃可能留下未登记的孤立附件，列出后由用户清理，不冒充投递成功。

数据库内部外键只连自身的投递、事件、材料表；`job_id` 不宣称对 JSON 文件有数据库外键。新记录时核对岗位，确认记录实际投出时冻结岗位与采用的评分；以后当前 JD 被更正或不存在时，历史记录仍可查看，并报告现状差异。不要联动改岗位 JSON 的 status 来制造“已投递”的第二个来源。

所有路径相对显式数据根；归档文件用生成的 ID 命名，不能从 JD 标题拼出任意路径。检查目录链接、路径越界，数据库文件本身也不能借符号链接或硬链接写到别处。SQLite 文件由连接维护，不套用 `_write_json` 的临时替换来更新一个正在使用的数据库。

## 5. M4-1 数据格式草案

以下是待定的逻辑 JSON 格式，SQLite 表的名称和索引是映射建议，**不是已经存在的 Schema 或可运行命令**。M4-1 正式实现时另写唯一格式/工作流说明，三个 Agent 用薄入口引用它。

### 5.1 一条记录代表一次投递尝试

同一岗位换渠道或再次申请，产生新的 `application_id`；不以公司名、职位名或 `job_id` 唯一约束投递。同一次请求重试复用 request_id；同一个文件重新生成也不能自动算又投了一次。

| 字段 | 草案与约束 |
| --- | --- |
| schema_version | 逻辑导入/导出格式版本，初版为 1；数据库迁移版本另管，不能因换表结构就改历史事件含义。 |
| application_id / job_id | application_id 为 CLI 生成的随机稳定 ID；job_id 指向已保存岗位。新建需存在；历史缺文件显示警告并使用快照，不伪造岗位。 |
| record_origin | current / historical，区分当前正常流程与用户确认的历史补录；后者的材料、日期或上下文缺失必须可见，不能默默降低普通记录的要求。 |
| channel | 对象 `{kind, platform}`。kind 建议 portal / company_site / email / referral / campus / offline / other / unknown；platform 如虚构招聘平台名，可为 null。drafted 时为拟用渠道，投出后取首次有效 submitted 的实际渠道；后来跟进换渠道不改原投递渠道。渠道不保存 Cookie、账号、邮件收件人或带凭据的 URL。 |
| created_at / updated_at | CLI 记录时间，规范化为带时区的 UTC 字符串；updated_at 表示元数据最后变更，不能当作最近一次外部沟通时间。 |
| revision | 应用内已提交事件的最后 seq，初始 created 事件为 1；写请求带 expected_revision。状态和材料引用不能绕过事件直接改。 |
| status | 当前状态，由有效事件重放得到；可在表中存投影以便查询，validate 必须能重算核对。 |
| submission | `{confirmed, occurred_at, occurred_on}`；confirmed 表示用户明确报告实际投出，与日期是否已知分开。只有日期时填 occurred_on，不伪造时刻；两种日期互斥，完全未知都为 null。 |
| next_followup_at | 当前有效的跟进到期时刻，可为 null，从 followup_scheduled / cancelled 等事件投影；不是“见到草稿就自动加十天”。 |
| context_snapshot | 首次确认投出时冻结的岗位与采用的评分的路径、字节摘要；drafted 时可为空。评分原件包含时间、规则版本、当时权重，供 M4-3 使用；没评分则 match 为 null，不事后用最新评分补写历史。快照保存的是记录时持有的证据；历史补录不能把当前 JD/评分冒充投出当天的版本。 |
| material_versions | 该尝试准备过的不可变材料版本列表；submitted / followup_sent 事件明确引用实际使用的版本。没有发送事实的版本不计入投递。 |
| events | 按 seq 升序的事件数组；SQLite 中建议单独表保存，show/export 时合成。 |

只有“生成了材料”“用户同意投递”或“打开了投递页面”均不足以设为 confirmed=true。此阶段只记录用户主动提供的已发生动作及合法来源结果，工具不代发；授权接口的结果由用户或 Agent 提供，本地 CLI 不联网同步。未知用 null，不能从没收到回复推断被拒绝。

### 5.2 时间与事件

| 事件字段 | 草案与约束 |
| --- | --- |
| event_id / seq / request_id | 稳定事件 ID；同一 application 的 seq 连续递增且唯一；request_id 关联一次命令，可包含多个原子提交的事件。去重约束放在请求表，不能把同一请求的第二个事件误判重复。 |
| type | created、materials_frozen、submitted、status_changed、reply_received、followup_scheduled、followup_drafted、followup_sent、followup_cancelled、note_added、event_corrected。payload 按 type 校验，不能任意写 JSON 逃过检查。 |
| occurred_at / occurred_on | 事实发生时间，精确时刻或仅知日期，互斥；未知两者均 null。精确时刻接受明确时区后规范化 UTC，仅日期不当午夜。 |
| recorded_at | CLI 真正写入的 UTC 时刻，必有值。用户今天补录上周投递时两种时间不同，不能覆盖为今天。 |
| actor | 写入者 user / codex / claude_code / dsh。它说明谁记录，不证明谁发送，更不代表已有发送授权。 |
| source | `{kind, reference}`，kind 建议 user / authorized_api；reference 为本地证据引用或 null，保留由谁确认事实。不得记 API Key、Cookie 或登录会话。 |
| payload | submitted 带实际渠道和 material_version_ids；status_changed 带 from/to/reason；followup_scheduled 带 due_at；其它类型由 M4-1 逐项定字段。历史渠道、材料以当次事件为准。 |

事件只追加，不能原地改写或删除。输错时间、渠道、状态用 `event_corrected` 指向原 event_id，携带修订值或明确作废理由；原事件仍保留。更正先预览，重算状态和统计，发现后续 from/to 不再合法则拒绝并让用户解决，不静默修复。这是应用层的可追溯约定，不是防管理员篡改的证明。

状态按有效事件的 seq 推进，occurred 时间用于事实展示和期间统计，不靠字符串时间重排来改变状态。补录较早事件可能影响当前状态时须预览确认；普通 note 或材料重建不改变状态。完整性校验核对事件顺序、引用、投影及摘要；历史档案已更新本来就正常，不要求旧材料通过“与当前 profile_hash 相同”的检查。

**状态建议**：drafted（只准备材料）→ applied（明确已投出）→ interview → offer → hired。rejected、withdrawn、offer_declined、no_response 为终结状态；允许确实发生的跳级，例如 applied 直接 offer。reply_received 记录回复事实，不必新增一个状态。未投出的 drafted 可 withdrawn，但不能无依据变成 rejected/interview。

从 drafted 补录一个已经有结果的申请时，同一事务补 submitted 和结果事件；日期可以未知，但发送事实必须确认。no_response 仅在用户确认标记时产生，不能把到期未跟进自动判成无回复结案；收到新消息后重新开启需显式状态事件和理由。具体允许的 from/to 对和终结状态重开规则，由 M4-1 固定并测试。

### 5.3 材料版本与冻结内容

每个 material_version 建议包含 `material_version_id`、`kind`、`created_at`、可空的 `material_source`（归档的原 Material JSON 路径与 SHA-256）、可空的 `profile_hash`，以及 `files[]`。每个文件含版本内稳定 file_id、role/format、相对归档 path、**实际文件字节的 SHA-256** 和 size_bytes；事件的 sent_file_refs 用 material_version_id + file_id 引用。邮件、打招呼语扩展时用独立 kind；文件名 `resume-2.pdf` 不能替代摘要。

在真实投递记录中，归档的是用户确认实际发送的 PDF、DOCX 或文本；Word 经手工编辑后，摘要应来自编辑后的文件。记录两种生成格式不等于两种都发了，事件还应选择实际发送的文件引用。用户口述历史投递而没有文件时，相关材料列表为空，显示“所用材料未记录”，不冒充完整归档；发送操作的未来自动化需要另有确认流程。

冻结目录不再覆盖。`material_source` 说明怎么起草，profile_hash 说明匹配语义版本，最终文件摘要说明实际字节；三者不能互换。岗位和评分快照也按实际归档字节验摘要；hash 证明文件一致性，不证明发送发生、更不能把摘要当脱敏后的公开数据。

### 5.4 简短导出示意

下面全为虚构数据，尚无材料文件的口述历史投递，因此材料为空、评分快照未知。示意只展示核心字段；完整格式及验证器由 M4-1 定稿，不能直接视作现有命令的输入。

```json
{
  "schema_version": 1,
  "application_id": "app_11111111111141118111111111111111",
  "job_id": "job_000000000001",
  "record_origin": "historical",
  "channel": {"kind": "portal", "platform": "示例招聘站"},
  "created_at": "2026-11-01T01:00:00Z",
  "updated_at": "2026-11-01T01:05:00Z",
  "revision": 2,
  "status": "applied",
  "submission": {"confirmed": true, "occurred_at": null, "occurred_on": "2026-10-31"},
  "next_followup_at": null,
  "context_snapshot": {"job": null, "match": null},
  "material_versions": [],
  "events": [
    {
      "event_id": "evt_11111111111141118111111111111111",
      "seq": 1,
      "request_id": "req_11111111111141118111111111111111",
      "type": "created",
      "occurred_at": "2026-11-01T01:00:00Z",
      "occurred_on": null,
      "recorded_at": "2026-11-01T01:00:00Z",
      "actor": "codex",
      "source": {"kind": "user", "reference": null},
      "payload": {"job_id": "job_000000000001", "record_origin": "historical", "channel": {"kind": "portal", "platform": "示例招聘站"}}
    },
    {
      "event_id": "evt_22222222222242228222222222222222",
      "seq": 2,
      "request_id": "req_22222222222242228222222222222222",
      "type": "submitted",
      "occurred_at": null,
      "occurred_on": "2026-10-31",
      "recorded_at": "2026-11-01T01:05:00Z",
      "actor": "codex",
      "source": {"kind": "user", "reference": null},
      "payload": {"channel": {"kind": "portal", "platform": "示例招聘站"}, "material_version_ids": [], "sent_file_refs": []}
    }
  ]
}
```

示意中的 job 快照为 null，属于“历史上下文缺失”而非正常流程中的完整投递记录。正式命令应区分普通流程（新建需当前岗位，提交事实入库时需归档所持上下文）与经用户确认的历史导入（保留缺失警告）；不能让 Agent 用历史导入绕过普通写入校验。

### 5.5 建议的表与 CLI 边界

| 对象 | 建议存放与用途 |
| --- | --- |
| applications | ID、job_id、渠道和时间字段、revision、当前状态/已发送/跟进投影；对 job_id、status、next_followup_at、提交日期建所需索引。 |
| application_events | 外键 application_id；唯一 (application_id,seq)、event_id；发生时间、记录时间、类型、来源和按类型校验的 payload。JSON payload 可存 TEXT，不依赖 SQLite JSON 扩展来完成核心查询。 |
| mutation_requests | request_id 唯一，关联规范化请求摘要、application_id 及原结果/事件范围，供重试去重。 |
| material_versions / material_files | 外键连接尝试、版本与附件清单；文件在数据根内的不可变目录；发送事件引用必须属于同一尝试。 |
| context_snapshots | 岗位/评分快照清单与文件摘要；是否有缺失单独显示，不能拿当前文件代替。 |

建议 CLI 能力为 `apply record/event/show/list/validate/export/import/backup`，**仅为候选命令名，当前未实现**。变更先输出 JSON 预览（旧/新状态、事件、材料引用、revision），确认所需事实后提交；show/list/report 不触发业务写入。读库不存在时明确返回，不因查看创建空库。导出按 application_id、事件 seq 和稳定键顺序排列，UTF-8，同一状态导出内容一致；全量导出包还需含请求去重索引和附件清单，以便恢复后重试原 request_id 仍能识别。导出文件损坏不影响数据库，导入必须显式校验，不能读到一个 JSON 就自动同步。

## 6. 查询口径：避免漏斗和待跟进失真

这些是拟议验收口径，不照搬上游 `/outcome` 的天数阈值：

- **当前状态分布**与**曾到达阶段的漏斗**分开。前者每次尝试只进当前一栏；后者按有效事件统计 distinct application_id，到过 interview 后被 rejected 的仍计入“曾面试”。另给 distinct job_id，不能把重复申请假装不同岗位。
- “已投递”须有有效 submitted 事实，drafted 不进入分母；“有回复”来自 reply_received 或明确的面试/offer/拒绝结果，不把内部 note、权重修改或自动回执直接当作招聘方有实质回复。
- 按提交期间看转化时，以 submission 的实际时间/日期选队列，结果允许发生在队列之后，并显示统计截止时刻。只知日期的保留日期精度；日期未知的列入“提交时间未知”，不偷偷用 created_at 代替。日期分组默认使用明确的展示时区，例如 Asia/Shanghai。
- **待跟进**：已确认投出、仍开放、有效 next_followup_at 到期；时间未知但已投出的记录仍能有人工设定的跟进计划。未知跟进日期单独列“未设置”，不当作已逾期。终结状态不进入待跟进；重新开启后需显式恢复/新建计划。
- followup_drafted 不代表已发送，不增加已跟进次数，不推迟静默计时。实际 followup_sent、提交和实质回复才更新外部活动时间；updated_at 不能用于判断对方多久没回复。M4-2 再确定默认提醒间隔与起草流程。
- 同一状态查询在一次数据库读事务中得到一致结果；附件丢失、历史缺项、记录无法解析要显示不完整警告，不能静默忽略后输出看似精确的统计。

## 7. 迁移、备份与恢复

**首次接入**只创建投递数据库及其格式版本；不扫描真实数据寻找“应当已经投过”的岗位，也不从 ranked 或材料存在推断已投递。上游 `job_search_tracker.csv` 的日期可能是起草日期，历史导入应单独设计映射预览、未知值和用户确认，不在本次自动接入。

以后若从 JSON 投递库迁入 SQLite：先停止写入并备份，逐条校验 schema/ID/事件/附件；全部写入新数据库的事务，核对条数、投影、导出等价及摘要；成功前不删除原目录。失败回滚，未知版本拒绝打开写入；成功后指定唯一活动后端，旧目录标为只读档案，避免双写。反向导出必须保留事件 ID、来源、时间精度和材料清单，不能只导出当前状态。升级时先读版本再迁移，旧 CLI 遇到新版本明确报错，不猜测兼容。

**数据库与附件一起备份**：优先通过 Python `Connection.backup` 生成数据库快照；要获得整套跨文件的一致备份，首版建议暂停业务写入与附件清理，再备份数据库和它引用的不可变附件、生成摘要清单。备份 API 只保证数据库，不替外部文件提供事务。恢复先在新目录校验数据库、外键、事件投影和附件摘要，确认后停写并切换，保留原副本；不能恢复到正在使用的库上。[Python backup](https://docs.python.org/3.10/library/sqlite3.html#sqlite3.Connection.backup)、[SQLite 备份 API](https://www.sqlite.org/backup.html)

普通文件复制只在干净关闭所有连接后进行；出现崩溃遗留日志时先让 SQLite 恢复或使用备份 API，不能自行删日志。在 WAL 模式下单独复制主文件可能遗漏已提交内容；不要手工拼接不同时间的数据库、`-wal`、`-shm` 或回滚日志。[备份/日志相关故障](https://www.sqlite.org/howtocorrupt.html)

## 8. 隐私、依赖与许可

- 真实投递正文、岗位快照、简历、渠道与事件都只在 `cn/data` 下；报告、导出、附件、备份同样是私密材料。默认汇总不复制联系方式或邮件全文，事件 note 不嵌入密钥/凭据。若以后要外部备份，由用户另定目标与加密方式，本提案不发送数据。
- 当前 [.gitignore](../../.gitignore) 已忽略 `/data/`、`*.db`、`*.sqlite`、`*.sqlite3`；**后面三个通配符并不覆盖所有 `-wal/-shm/-journal` 后缀**。本方案靠整个数据目录隔离这些文件，不把数据库移出根目录后还假定已有保护。正式实现要验证导出、日志及临时文件也在同一私密边界，CI 只用虚构数据库和附件。
- JSON 和普通 SQLite 都是本地明文存储；不把“本地”“二进制”“哈希”或“gitignored”当作加密。磁盘/备份的访问控制由用户环境提供，删除记录也不承诺从历史备份与存储介质上安全擦除。若需内置加密要另作依赖与密钥设计，不能暗中加入扩展。
- Python 标准库提供 [sqlite3](https://docs.python.org/3.10/library/sqlite3.html)，沿用项目 Python 3.10–3.14 兼容范围；不依赖仅新版本才有的 autocommit 参数，不依赖系统 sqlite3 命令行、ORM、JSON1/FTS 扩展。运行前检测模块及实际 SQLite 版本，缺失时给安装/环境说明，不能静默切回另一个存储后端。本机只读探测为 Python 3.12.15 / SQLite 3.53.4，不能据此代表全部 CI 和用户环境。
- 本项目仍按 [MIT](../../LICENSE)；Python 的发行按 [Python 许可说明](https://docs.python.org/3/license.html)，SQLite 核心代码和文档由作者置于 [public domain](https://www.sqlite.org/copyright.html)。本次不再分发 SQLite 二进制、不引入第三方 Python 包；若以后打包解释器、扩展或额外构建材料，应核对具体发行组件并更新第三方清单，不能把 SQLite 核心的说明泛化为所有组件的许可。

## 9. 裁定点与 M4-1 验收建议

请规划者和用户确认：是否采用“只给投递元数据接 SQLite、JSON 作为统一接口与导出”的范围；是否接受 M4-1 首版就包含事件原子写入、稳定材料归档、导出/备份与恢复；历史投递缺材料/日期时是否采用“保留未知并警告”的入口。日志模式、状态词表和候选命令在正式规格中定稿，不在本 PR 宣称实现。

后续实现至少应用虚构样例验证以下结果：

1. 两个进程拿同一 revision 更新，一个成功，另一个明确冲突；重试同一 request_id 只得到原结果，事件、状态、材料引用无半提交。
2. 材料已生成但未投出：仅 drafted，投递/回复漏斗均不增加；用户报告已投出但日期未知：计入已投递，时间分组显示未知。
3. 同岗位两个渠道是两次尝试，按申请和按岗位的计数不同；面试后拒绝仍进入曾面试漏斗；跟进草稿不算已跟进。
4. 当前 JD、档案、评分、源 Word 被更新后，已提交材料的历史文件及摘要不变，M4-3 仍能取得当时评分；缺失附件要能检测。
5. 事务前附件写入中断、写锁超时、数据库/导出损坏、备份恢复中断均有可恢复结果；恢复后的事件数、状态投影、材料摘要和漏斗一致。
6. 三个 Agent 在同一数据根经同一 CLI 完成读取、起草/确认、记录、查询、导出；只读命令不建库、不发送、不写材料到根目录以外。

本备忘的技术资料在 2026-11-01 核对，链接随相关论断列出；没有性能基准或真实用户数据实验。文档准备完成不等于 M4-0 已获批准，也不等于 M4-1 已实现。
