# 2026-11-04 · M4-1b 投递记录：其余命令、工作流、入口和授权（Claude A）

分支 `feat/cn-m4-1b-applications`，从 origin/master 39f86c5（#122 M4-1a 已合并）开。这一轮只写计划，不写代码；规划者裁定后再实现。

**任务单**：设计稿 `origin/feat/cn-m4-1-applications-design` 的 `docs/cn/worklog/2026-11-03-m4-1-applications-design.md` §14 的切法。M4-1b 做：

- `reply`、`note`、`followup`（含 §8 的 `list --due [--as-of]` 和 `unset` 一栏）、`void`（只作废最近一条有效事件）、`backup`；
- Agent 用的工作流说明、入口（技能 `cn-application` 等，照 #116 给 cn-resume 加入口的做法）、授权；
- §8 最后一条：`resume-workflow.md` 第 4 节"交给用户"之后加一句链接。

import 不做（§14 裁定 1）。V25 有 30 个 M4-1b 的留出场景，我不看 `origin/codex/v25-m4-1-holdout`、PR #124 和 holdout clone。

## 1. 实现步骤（裁定以后做，每步提交推送）

1. **`jobsearch_cn/applications.py`**
   - 新事件类型 `reply_received`、`note_added`、`followup_scheduled`、`followup_cancelled`、`event_voided`，payload 照设计 §4。
   - `replay` 仍是写入和 `validate` 共用的唯一规则：
     - `reply`、`note`、`void` 只加 `revision`；
     - `followup` 设置或清空 `next_followup_on`；
     - 被作废的事件跳过。
   - 新函数 `reply`、`note`、`followup`、`void`、`list --due`、`backup`，以及核对备份。写入照 M4-1a 的预览、`request_id`、`expected_revision`、事务那一套，不另写。
   - 修第 7 条第 1 点的快照冲突。
2. **`cli.py`**：新命令加在 `application` 那一块里，不碰别的命令组。
3. **测试**：`tests/test_cn_applications.py` 加 M4-1b 的部分，`tests/test_cn_agent_entry.py` 的 `WORKFLOWS` 加 `cn-application`。只用虚构数据。
4. **文档**：
   - `docs/cn/applications.md`：补上新命令、跟进和作废的规则、备份和手工恢复的步骤，再加一节"Agent 工作流"（设计 §11.10：三个 Agent 都指向这一份）；
   - `docs/cn/README.md` 的索引改一行；
   - `resume-workflow.md` 第 4 节加一句链接。
5. **入口**：
   - `.claude/skills/cn-application/SKILL.md`
   - `.dsh/skills/cn-application/SKILL.md`
   - `AGENTS.md` 加"记录投递"一段

   入口都只指向工作流，不写命令。
6. **授权**（经理同意以后才改，见第 3 节）。
7. 三项检查，开 PR，审核者 Codex B。

## 2. 设计没说清的地方：建议和理由

### 2.1 没投出（drafted）或已经结束的投递，能不能 reply、note、followup

建议：

- **`note` 任何状态都能记**，包括 `drafted` 和终结状态。理由：备注是用户自己的话（"二面""HR 说明年再招"），结束以后也有用，而且不改状态。
- **`reply` 要已经投出**：`drafted` 拒绝（`transition`），提示先 `submit`；终结状态可以记，例如被拒以后对方的反馈。理由：没投出就收到回复，说明其实已经投了，应该先把投出记上，时间线才对。
- **`followup`（设置和 `--cancel`）只在已投出、没结束时能用**，也就是 `applied`、`interview`、`offer`；`drafted` 和终结状态拒绝（`transition`）。没设跟进日期时 `--cancel` 拒绝（`invalid`），不写空事件。理由：没投出就没什么可跟进；进入终结状态时跟进日期已经清空（设计 §4），#110 §6 也说终结状态不进入待跟进。
- **`no_response` 按"不等了"处理**：进入时和终结状态一样清空跟进日期，在这个状态下不能设跟进，`list --due` 的两栏都不列它。理由：`no_response` 只在用户说"不等了"时记，再提醒跟进和用户的决定相反；迟到的回复来了，状态变成 `interview` 等，就又能设跟进。M4-1a 里设不了跟进日期，已有的库都是 null，改这条不影响旧数据。

### 2.2 跟进日期能不能设在过去

建议：不能。`--due` 只收 `YYYY-MM-DD`，不能早于 Asia/Shanghai 的今天，可以是今天。理由：过去的日期一设上就是逾期，多半是输错了（例如 2025 写成 2026）。"本该上周跟进"就写今天，`list --due` 的结果完全一样。不设上限。跟进事件不带 `--on`、`--at`：它是计划，不是发生过的事。

### 2.3 `list --due` 的输出结构和默认日期

建议：

- 输出 `{"as_of": "2026-11-04", "due": [...], "unset": [...]}`。每一项是 `list` 的摘要，再加 `next_followup_on`。`due` 的每一项还有 `days_overdue`，等于 `as_of` 减去跟进日期的天数，当天到期为 0。
- `due`：已投出、状态是 `applied`、`interview`、`offer`、`next_followup_on` ≤ `as_of`；按跟进日期从早到晚排，最早的在前，同一天按 `application_id`。
- `unset`：已投出、状态是那三种、没设跟进日期；按投出日期从早到晚排，等得最久的在前，日期未知的排最后。
- 不带 `--as-of` 时取 Asia/Shanghai 的今天，和 `--on` 不能是将来用同一个"今天"。`--as-of` 可以是任何日期，M4-2 可以拿来问"下周一有哪些到期"。它只能和 `--due` 一起用。
- `--status`、`--job` 可以和 `--due` 一起用，先按它们筛。`drafted` 两栏都不列（设计 §11.7）。
- 普通 `list` 的摘要也加 `next_followup_on`。只是多一个字段，原有字段不变。

### 2.4 void 的边界

建议：

- **作废对象**：最近一条"没被作废、本身也不是 `event_voided`"的事件。连着作废就一条一条往前退，设计 §13.6 说更早的错"先把后面的作废，再重记"。
- **作废事件本身不能作废**。作废错了，就把那条事件重新记一次。理由：作废的作废要处理 `voided_by` 链，重放和 `validate` 都会复杂得多，用户也难看懂。
- **只剩 `created` 时不能作废**（`invalid`）。理由：作废 `created` 等于删掉整条投递，v1 不做删除，库里也没有"没有状态的投递"这种行。记错的整条投递这样处理：
  1. 先作废 `submitted`，回到 `drafted`；
  2. 再 `status withdrawn --reason 记错了`。

  这样它从没算投出过：导出里 `submission.confirmed` 为 false，M4-4 从导出统计时不算投出。
- **作废 `submitted` 以后**：
  - 重放回到 `drafted`：`submission.confirmed` 为 false，`occurred_at`、`occurred_on` 为 null，`materials_recorded`、`materials_check` 为 null。这几项都只看没被作废的 `submitted` 事件，M4-1a 已经是这样。
  - 归档的材料版本照样留在 `material_versions` 里，文件不删，`validate` 照样核对摘要。被作废的那条事件保留它的 `material_version_ids`。以后再 `submit` 会建新的材料版本。文档写明：现在用的材料以有效 `submitted` 事件的 `material_version_ids` 为准。
  - 岗位和评分快照沿用第一次的，见第 7 条第 1 点。
- **其他**：
  - `--reason` 必填，≤300 字；
  - 预览里给出要作废的那条事件；
  - 请求摘要带上目标事件的 id；
  - 作废事件自己占一个 seq，`revision` 照常加 1，所以"作废以后的 revision"和别的写入一样用 `expected_revision` 防并发。

### 2.5 backup

建议：

- **一步执行，不预览、不带 `request_id`**。理由：备份不改任何投递记录，只新建一个目录，执行两次就是两份备份，不需要去重。
- **位置和名字**：`data/applications/backups/<UTC 时间 YYYYMMDDTHHMMSSZ>/`；同一秒有重名的，加 `-2`、`-3`。目录里面：
  - `applications.sqlite3`：`Connection.backup` 的一致快照；
  - `artifacts/`：快照里登记的归档文件，相对路径不变；
  - `manifest.json`。

  先写进 `<名字>.tmp/`，复制的每个文件都读回核对摘要，然后改名。
- **为什么也复制附件**：#110 §7 说数据库要和它引用的不可变附件一起备份。只有清单的话，`artifacts/` 丢了就恢复不了。附件不会被改，先做数据库快照、再复制快照里登记过的附件，即使同时有人在写也一致：之后新写的附件不在这份快照里。简历文件不大，每次全量复制，不做增量。如果规划者认为只要清单（设计 §5 的原话是"附件清单和摘要写在旁边"），就只写 `manifest.json`，文档写明备份不含附件。
- **清单格式**：

  ```json
  {"schema_version": 1, "kind": "applications-backup", "created_at": "…Z",
   "database": {"name": "applications.sqlite3", "sha256": "…", "size_bytes": 0, "user_version": 1},
   "counts": {"applications": 0, "events": 0},
   "artifacts": [{"path": "artifacts/app_…/mv_…/sent-1.pdf", "sha256": "…", "size_bytes": 0}],
   "source_valid": true}
  ```

  `source_valid` 是备份时对原库跑 `validate` 的结论。原库不通过也照样备份（留住现状，方便排查），输出里给警告。
- **核对已有备份**：建议用 `application validate --backup <名字>`，只读。它检查：
  - 清单在、数据库文件的摘要对；
  - 数据库能打开、`user_version` 是 1；
  - 再对备份目录跑和 `validate` 一样的检查（外键、事件、重放、附件摘要）。

  理由：备份目录和 `applications/` 的布局一样，可以直接复用 `validate`，不另写一套规则。
- **恢复不做成命令**（import 不做）。文档写手工步骤：
  1. 停止所有 Agent 的写入；
  2. 用 `validate --backup` 核对备份；
  3. 把现在的 `applications.sqlite3` 和 `artifacts/` 移到别处保留；
  4. 把备份里的复制进来；
  5. 跑 `validate`。

  这和 #110 §7 一致："不能恢复到正在使用的库上，保留原副本"。
- **什么时候备份**：Agent 只在用户要求时执行，或者在建议用户手工恢复之前提醒先备份，不自动定期备份。

### 2.6 入口和授权分别是哪些文件

**三个 Agent** 是 Claude Code、Codex 和 DeepSeek Harness（dsh），入口三个文件，都指向 `docs/cn/applications.md` 的"Agent 工作流"一节：

- `.claude/skills/cn-application/SKILL.md`
- `.dsh/skills/cn-application/SKILL.md`
- `AGENTS.md` 的"记录投递"一段（Codex 用）

**设计 §1 写"四个入口"**，是照 M3-3 数的。M3-3 的第四个是审核子代理 `cn-resume-reviewer`，投递记录没有独立审核，所以只有三个。另外两处不算入口：`docs/cn/README.md` 的文档索引，和 `resume-workflow.md` 第 4 节的链接。

**技能用到的命令组**：`application` 和 `jd`（用 `jd list`、`jd show` 找岗位 id）。Claude Code 技能的 `allowed-tools` 是：

```text
Read, Bash(python -m jobsearch_cn application:*), Bash(python -m jobsearch_cn jd:*)
```

`test_the_skill_grants_only_its_workflow_groups` 要求技能授权的命令组正好是工作流里用到的那些，所以 applications.md 的"Agent 工作流"一节要写出 `python -m jobsearch_cn jd list` 和 `jd show`（现在全文只出现 `application`）。不要 `Write`：写文件都由命令自己做。

授权要改的地方见第 3 节。

### 2.7 实现时看到的其他问题

1. **作废 `submitted` 以后再 `submit` 会失败**。`snapshots` 表的主键是 `(application_id, kind)`，现在的 `submit` 对现在的投递总要写快照，第二次插入撞主键，整个事务回滚。建议：已有快照就不再写，沿用第一次的，文档写明。另一个办法是改主键，那要迁移表结构（`user_version` 2），不值得。
2. **一次回复如果改了状态，只记 `status --reason`**，不再另记一条 `reply`。例如收到面试邀请：`status interview --reason 收到面试邀请`。只记"收到回复但状态不变"时才用 `reply`（例如"HR 说下周给结果"）。这样用户一次只确认一个预览。写进工作流。
3. **"先预览"只能靠工作流保证**。授权 `application:*` 也包括写命令；Agent 自己编一个 `request_id` 也能直接提交（#122 的裁定：接受，由 M4-1b 的技能保证）。工作流和三个入口都要写死：
   - 写入前必须先 `--preview`，把要写的内容给用户看；
   - 用户同意后，才带预览给的 `request_id` 提交；
   - `--actor` 写 Agent 自己的名字（`claude_code`、`codex`、`dsh`）。
4. **和上游技能撞车**。上游 `/outcome`（"记录投递结果"）写的是上游自己的 `job_search_tracker.csv` 和 `documents/applications/`，`/interview`、`/html-report` 读的也是那张表，触发词和"记投递""收到回复"重叠。建议：
   - `cn-application` 的触发词用中文（记投递、投了、投递记录、收到回复、跟进、作废记录、备份投递记录）；
   - 工作流和 dsh 入口写明"不要用上游的 `/outcome`、`/apply` 记投递"，和 cn-resume 入口写明不用上游 `/setup` 是一个做法。
5. **`validate` 要加的检查**：
   - 每种新事件的 payload 字段；
   - 作废的对应关系：目标在同一条投递里，目标的 `voided_by` 等于作废事件的 id；
   - 一条事件只被作废一次；
   - 不能作废 `created` 和 `event_voided`；
   - 被作废的事件在作废时是最近一条可作废的事件。

   回复摘要、备注、作废原因也查像手机号、邮箱、链接的文字，和原因、平台名一样只警告。
6. **时间**：`reply` 可以带 `--on`、`--at`（回复是哪天来的），规则和 `status` 一样，不能是将来；`note`、`followup`、`void` 不带。
7. **备份目录里中断留下的 `<名字>.tmp/`**，由 `validate` 列在 `orphans` 里，和 `artifacts/` 下的孤立目录一样，用户同意后再删。

## 3. 授权要改的地方（经理同意之前不改 `tools/security_guards.py`）

规划者正在请经理本人同意，结果在派实现时告诉我。同意以后改这四处，写法照 #116 的 material、resume、review：

1. `tools/security_guards.py` 的 `ALLOWED_PERMISSIONS`：加 `"Bash(python -m jobsearch_cn application:*)"`，前面加一段 CN fork 注释，写批准日期和命令做什么。注释大意：
   - 写命令只在用户看过预览、同意以后，写 `<数据目录>/applications/` 下的数据库和归档；
   - `backup` 写 `applications/backups/`；
   - 不联网。
2. `tools/security_guards.py` 的 `ALLOWED_SKILL_TOOLS`：加同一行，行尾注释 `# CN fork: .claude/skills/cn-application`。
3. `.claude/settings.json` 的 `permissions.allow`：加同一行。
4. `.claude/skills/cn-application/SKILL.md` 的 `allowed-tools`：见 2.6。

`jd:*` 已经在两个清单和 `settings.json` 里了，不用加。`tests/test_cn_agent_entry.py` 的 `test_the_skill_grant_is_in_both_allowlists` 会核对这四处一致。

## 4. 请规划者裁定

1. 2.1：`note` 任何状态都能记；`reply` 要已投出；`followup` 只在 `applied`、`interview`、`offer`。`no_response` 按"不等了"处理：清空跟进日期，不进 `due` 和 `unset`。
2. 2.2：跟进日期不能早于今天（Asia/Shanghai）。
3. 2.3：`list --due` 的输出结构，默认取 Asia/Shanghai 的今天。
4. 2.4：作废的边界：
   - 作废事件和 `created` 都不能作废；
   - 作废 `submitted` 后，材料版本保留、快照沿用。
5. 2.5：`backup` 一步执行、复制附件、`validate --backup` 核对、恢复只写手工步骤。如果只要清单、不复制附件，请注明。
6. 2.6：三个入口，技能授权 `application` 和 `jd` 两个命令组。
7. 2.7：
   - 快照沿用（第 1 点）；
   - 改状态的回复只记 `status`（第 2 点）；
   - 上游技能的触发词（第 4 点）。
