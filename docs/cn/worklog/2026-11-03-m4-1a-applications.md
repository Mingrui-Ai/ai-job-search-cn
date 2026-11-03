# 2026-11-03 · M4-1a 投递记录：存储和状态主线（Claude A，进行中）

分支 `feat/cn-m4-1a-applications`，从 master 90e30e0 开。设计和规划者裁定见 [2026-11-03-m4-1-applications-design.md](2026-11-03-m4-1-applications-design.md)（设计分支 `feat/cn-m4-1-applications-design`，§13 问题、§14 裁定和切法）。

**存档**（2026-11-03，经理说今天收尾，明天继续）

已做：

- 读了 `cli.py` 的结构，确定接入方式（见下）。还没有写代码。

下一步（按顺序，做到一段就提交推送）：

1. **`jobsearch_cn/applications.py`**：不依赖 `cli.py`，可以在进程内调用，测试也直接调它。
   - 常量：数据库版本 1、导出版本 1、渠道、状态、允许的变化表（设计 §4）、`actor`、锁等待 5 秒（`LOCK_TIMEOUT`，测试里改小）、文字上限 300。
   - 异常：`ApplicationError(code, message, **extra)`，对应退出码 1（`invalid`、`transition`、`stale_revision`、`request_conflict`、`busy`、`not_found`）；读不了、数据库版本更新时报 `InputError`，退出码 2。
   - 连接：`sqlite3.connect(path, timeout=LOCK_TIMEOUT, isolation_level=None)`，手动 `BEGIN IMMEDIATE`；`PRAGMA foreign_keys=ON`，并读回核对；`PRAGMA journal_mode=DELETE`；`user_version` 为 0 就建表，比 1 大就拒绝。只读命令和 `--preview` 在库不存在时不连接，sqlite3.connect 会建空文件。
   - 状态不另存一套逻辑：`replay(events)` 重放有效事件得出投影，写事件和 `validate` 用同一个函数。
   - 写入顺序：先查 `requests` 表（同 `request_id`：内容摘要相同就返回原结果，不同报 `request_conflict`）→ 归档文件（`artifacts/<app>/<version>.tmp/` 复制、读回核对 SHA-256、改名）→ `BEGIN IMMEDIATE` → 再查一次 `request_id` 和 `expected_revision` → 写事件、请求、版本、快照，更新投影 → 提交。
   - 预览：`--preview` 和 `--request-id` 必须给一个。预览只算不写，输出新的随机 `request_id`、预计的事件（`event_id`、`recorded_at` 为 null）和新旧状态。
   - 时间：`--at` 必须带时区（3.10 的 `fromisoformat` 不认 `Z`，先替换成 `+00:00`），存成 UTC `…Z`；`--on` 只认 `YYYY-MM-DD`。
   - 归档：材料 JSON 记为 `material`，发出的文件依次记为 `sent-1`、`sent-2`，保留扩展名。材料要能通过 `material.validate`，警告只转给用户。材料的 `job_id` 必须是这条投递的岗位。发出的文件不在 `resumes/<岗位id>/resume-<n>.*` 下时给警告。第一次 `submitted` 时复制 `jobs/<id>.json` 和 `matches/<id>.json` 作为快照；`--historical` 不做快照。
   - 新建投递要求岗位在岗位库里；同一岗位已有未结束的投递时给警告。现在的投递（不是补录）投出时没有材料也只给警告，写进输出和 `validate`。
2. **`cli.py`**：新代码放在文件末尾（`build_parser` 之前）的一整块。用单独一行 `from jobsearch_cn import applications as applications_mod` 导入，不改共用的那行 import；`build_parser` 里只加一行 `_add_application_parser(commands, stored)`。读档案、词表、材料用已有的 `_match_profile`、`_vocabulary`、`_read_material`、`_material_notes`，这几个函数本身不改。命令：record、submit、status、show、list、validate、export。
3. **测试** `tests/test_cn_applications.py`，全部用临时目录和公开虚构数据（`tests/fixtures/cn/material/tech-m3`、`tests/fixtures/cn/jd/boss_intern.txt`）。逐条覆盖设计 §11 里属于 M4-1a 的验收项；`busy` 在进程内把 `LOCK_TIMEOUT` 改小后测；两个子进程拿同一个 revision 测 `stale_revision`。
4. **`docs/cn/applications.md`**：格式、状态表、命令、退出码、并发、隐私，以及 `resume build` 说明文件的格式；README 文档索引加一行。
5. **`resume build` 的说明文件**（裁定 4）：等 #119 合并，合入 master 后再改。打算写成 `resume-<n>.build.json`，内容是 `{schema_version, material, material_hash, profile_hash, built_at, files: {pdf, docx 的 SHA-256}}`。格式写进 applications.md，M3-6 照用。投出时核对：说明文件里的 `material_hash` 等于材料的当前值，发出文件的摘要等于说明文件里记的（Word 手工改过的，摘要对不上只给警告）。
6. 三项检查，开 PR，审核者 Codex B。V25 是 Codex A 的留出样例，开 PR 前由规划者确认已冻结；我不看 holdout clone，也不看 `codex/v*` 分支。

还没定的问题：

- 说明文件的名字（`resume-<n>.build.json`）和字段，要和 M3-6 的 `material render --output` 用同一套，写好后告诉规划者，由他转告 Claude C。
- 现在的投递投出时没有材料：我打算只给警告（BOSS 直聘等平台可能用的是在线简历，没有文件），设计里没有单独裁定。实现时照这个做，PR 里请规划者确认。

规划者裁定（cn-fa，2026-11-03，收尾时）：

1. **说明文件**：一次 build 写一个，放在输出旁边，文件名是材料文件名去掉 `.json` 再加 `.build.json`（例如 `resume-1.build.json`）。字段至少有 `material_hash`、`profile_hash`、生成时间（带时区），以及这次 build 输出的每个文件名和它的字节 SHA-256。投出时用这些摘要核对发出的文件是不是这次 build 的文件。格式写进 `applications.md`，M3-6 的 `.txt` 照这个格式。上面第 5 步照此执行。
2. **投出时没有材料**：只给警告，不报错。记录里写明"材料未记录"（导出时有一个可以单独统计的字段），让 M4-3、M4-4 能单独统计。平台在线简历这类投递要能如实记下，不能为了凑材料挡住。

**进展**（2026-11-03，规划者 cn-a7 正式派活后）

- 合入 origin/master 45e699d。
- 第 1–3 步：`jobsearch_cn/applications.py`、`cli.py` 末尾的 `application` 命令组、`tests/test_cn_applications.py`（43 项）已写好。
- 实现时定下的几处（写进 applications.md，PR 里请规划者确认）：
  - `submitted` 事件的 payload 用 `material_version_ids`（#110 §5.4 的写法；设计 §4 写的是 `version_ids`，设计 §7 说导出字段名照 #110）。
  - "材料未记录"在导出里是 `submission.materials_recorded`：未投出为 null，投出时没有材料为 false。
  - `--material`、`--sent` 只能和投出一起记（`record --submitted` 或 `submit`）；只起草时不记材料。
  - `--historical` 必须带 `--submitted`；补录的岗位可以不在岗位库里（给警告），不做快照。
  - 不带 `--note`：备注事件是 M4-1b 的 `note`。
  - `--on`、`--at` 不能是将来（`--on` 按 Asia/Shanghai 的今天，`--at` 容 5 分钟）。
  - 第一次写入时建表也在同一个事务里，写入失败时连表一起回滚。
- 自查发现：`submit`、`status` 成功后用同一个 `request_id` 重试，会先撞上 `stale_revision`（revision 已经变了）。改成先查请求表、再查 revision，加了测试。
- 第 4 步：`docs/cn/applications.md` 写好，README 文档索引和常用命令各加一行。第 12 节先写了 `resume build` 说明文件的格式，供 M3-6 照用；实现等 #119。

下一步：

1. 等 #119 合并（2026-11-03 查过，还是 OPEN，head 5b91525）。合并后合入 master，按 applications.md 第 12 节改 `cmd_resume_build` 写说明文件，`submit` / `record --submitted` 读发出文件旁边的说明文件核对，加测试。
2. 三项检查，开 PR，审核者 Codex B；开 PR 前请规划者确认 V25 已冻结。
- 全量测试第一次在并发测试上失败一次：输的那个进程先读到 revision 2 的投递，读事件时对方已经写进第 3 条，重放报成了 `invalid`。改成只用读投递那一刻的事件做预检，真正的判定留给写事务里的 `stale_revision`；加了一个确定复现这个时序的测试，并发测试连跑 8 次都通过。

规划者裁定（cn-a7，2026-11-03，对 18:11 回报）：

1. 字段名用 `material_version_ids`，和 #110 的导出字段一致；设计 §4 的 `version_ids` 是笔误。
2. `submission.materials_recorded`：未投出为 null，投出时没有材料为 false。同意。
3. 实现时自定的四条（`--material`/`--sent` 只随投出记；`--historical` 必须带 `--submitted`、岗位不在库里只警告；`record` 不带 `--note`；`--on`/`--at` 不能是将来）都同意。
4. 说明文件和材料对不上：只警告、照样记录；核对结果记进事件（`materials_check`），导出里看得到。
5. V25 留出样例由另一个会话准备；开 PR 等规划者通知。

**进展**（2026-11-03，新会话接手第 5 步）

- 合入 origin/master（#119 已合并）。master 上 `_material_notes(args, record)` 改了签名，`application` 的材料检查跟着改。
- `resume build` 在输出旁边写 `resume-<n>.build.json`（applications.md 第 12 节），输出里多 `build_note`；只列这次实际写出的文件。
- `submit`、`record --submitted` 读发出文件旁边的说明文件核对，结果写进 `submitted` 事件的 `materials_check`（`match`/`mismatch`/`unchecked`/null），导出 `submission.materials_check`；`validate` 检查这个字段的取值。`materials_check` 也算进请求摘要。
- 测试：resume build 的说明文件内容；对得上、文件摘要不对、material_hash 不对、没有说明文件、没有发出文件。

规划者裁定（cn-e3，2026-11-03）：说明文件只列这次实际写出的文件；一个都没写出来时不写说明文件、不覆盖原来那份，退出码和输出照旧。已实现并加测试（`test_a_failed_build_keeps_the_earlier_build_note`）。说明文件格式由规划者转告 Claude C。

已开 PR #122（审核者 Codex B，V25 由独立会话对照）。

规划者裁定（cn-e3，2026-11-03，#122 评论；V25 对照结果见 #124：80 个场景，65 个通过）：

- 要改：
  - A50（P2）：`materials_check` 为 `unchecked` 时也要给警告（命令输出里有，`validate` 也报），照样记录。
  - A48（同一段代码）：给了 `--material` 时，用材料对应的说明文件（材料文件名去掉 `.json` 加 `.build.json`）核对所有发出的文件；没给材料时才按发出文件的名字找。改过内容的文件这时是 `mismatch`，不再是 `unchecked`。
- 批准为已批准的差别，不改：
  - A43–A45：发出文件的 `file_id` 用 `sent-1`、`sent-2`。
  - A29–A37：`status <id> drafted` 被 argparse 拒绝（退出 2，什么也不写）。
  - V25 标"按实现核对"的 12 处。

**进展**（2026-11-04，按上面的裁定改）

- `prepare_materials` 先读完所有发出的文件，再一起核对：
  - 给了材料：用 `resumes/<岗位id>/<材料名去掉 .json>.build.json`（`material_note_path`）核对全部发出文件，并比 `material_hash`；
  - 没给材料：按发出文件的名字找旁边的说明文件（`build_note_path`），同一个说明文件对应的几个文件一起核对；
  - 汇总：有 `mismatch` 就是 `mismatch`，否则有 `unchecked` 就是 `unchecked`，都对得上才是 `match`。
- 找不到说明文件时给警告（`… no resume build note … to check against; recorded unchecked …`）；读不了的说明文件照旧给警告。`validate` 对 `unchecked` 的投递给警告（`<投递id>: materials_check unchecked …`）。
- 测试：
  - 改名后的文件用材料的说明文件核对，内容一样为 `match`，改过内容为 `mismatch`；
  - 没给材料时按名字找，改名的文件为 `unchecked`；
  - 找不到说明文件和说明文件读不了这两种 `unchecked`，命令输出和 `validate` 都有警告；
  - 没有发出文件时为 null，不给这类警告。
- `test_a_clean_database_is_valid` 先写一份说明文件，干净的库仍然没有警告；`build_note` 从 `Materials` 挪到 `Data`，两组测试共用。
- applications.md 第 6、10、12 节同步改。

规划者裁定（cn-e3，2026-11-04）：`validate` 把 `materials_check` 为 `mismatch` 的投递也列出来，和 `unchecked` 一样算警告、不算错误。理由：发出的文件和 build 出来、审过的那份对不上，比没法核对更要提醒。

- 已实现：`validate` 对 `mismatch` 给警告（`<投递id>: materials_check mismatch …`），`valid` 仍为 true。
- 加了测试：`test_validate_lists_a_mismatch_as_a_warning_not_an_error`。
- applications.md 第 10、12 节同步改。

下一步：V25 重跑受影响的场景、更新 #124；代审只看改动的部分。
