# 工作记录

按时间倒序记录：做了什么、为什么这样做、验证结果、遗留问题、下一步。每完成一步（通常对应一个 PR），在最上方追加一条。架构决策的完整理由见 [迁移方案](cn-migration-plan.md)，这里只记过程和结果。

---

## 2026-10-27 · V2：M2-3 独立 JD 样例与人工匹配对照

**完成与决策**

- 在 `tests/fixtures/cn/jd-m2-3/` 新增 5 份原创虚构 JD、5 份对应人工期望、逐字段 README、完整 CLI 对照输出、冻结清单与验证摘要。覆盖 AI 产品、新媒体内容运营、UI 设计、测试开发实习和市场管培校招；公司均为“示例……有限公司”，每份至少 2 处易错写法。
- 独立编写期间只依据 Job Schema、匹配契约和 tech/ops 示例档案，不查阅解析/匹配规则源码、既有 JD 测试或执行会话实现。先冻结 JD、逐字出处和 10 组人工匹配判断的 SHA-256，再运行 `jd parse`、`match filter`；实测后没有回填期望值。
- 人工期望按 14 个 Job Schema 语义字段组组织；未知保留 `null` / `[]`，运行元数据单独保存在实际输出中。学历优先、会议星期、回复时效、面试地点、试用期和项目周期均按语义区分，不靠结果倒推期望。
- 初期目录权限受限时在临时隔离检出完成冻结；权限恢复后，在指定工作树 `D:/06_Projects/ai-job-search-cn-codex` 从最新 `origin/master@34d254d` 新建 `codex/v2-m2-3-samples`，逐字节复制冻结文件，重跑全部对照与验收。冻结基线为 `a3986d3`；期间示例档案虽有更新，七项过滤所用字段逐项未变。
- 本次不改代码、现有测试、既有样例或其他 CN 文档；没有将新样例放入 `tests/fixtures/cn/jd/`，也未接入现有自动断言。完整结果见[样例 README](../../tests/fixtures/cn/jd-m2-3/README.md)。

**验证与发现**

- `python tools/lint_skills.py`、`python tools/security_guards.py`、`python tools/check_framework_version.py` 均通过。
- conda `ai-job-search-cn`、Python 3.12.15：`python -m unittest discover -s tests -t . -v` 共 1009 项，1000 项通过、9 项按预期跳过，0 失败、0 错误；测试框架报告耗时 98.462 秒。旧权限下未完成的测试已停止，不计入通过结果。
- 18 份交付文件通过 UTF-8、无 BOM 和字符扫描，统一 LF；除必要换行外无 Unicode Cc/Cf 控制或格式字符。59 个字段出处片段逐字存在于对应 JD，城市和技能各项均在各自出处内；10 个冻结文件哈希全部未变。
- 70 个语义字段组：62 项一致、7 项规则漏读、1 项规则误读。5 份 JD 都漏技能；市场管培标题和“全年13薪”中的薪数漏读；同一行的面试城市北京被误收为工作城市。
- 10 组未经补全的匹配总判断全部一致，但 70 项硬条件状态仅 68 项一致：市场管培标题缺失使 tech/ops 的 `exclusions` 从人工 `match` 变成实际 `unknown`，总判断恰好没有变化。
- 另将冻结人工字段写入独立岗位库，5 份记录均通过 `jd validate`；再跑 10 组匹配，70 项检查状态全部符合人工期望。该重放用于区分解析输入与匹配行为，不改变原始实际结果。

**遗留与下一步**

- 交由规划者逐份核对原文、期望与出处，再由 M2-3 扩充 24 个去重后的缺失技能词，并处理管培标题、同一行工作/面试地点区分、“全年13薪”。已正确的否定、优先、未知及范围下限也需保留。
- 匹配验收不能只核对总判断，还需看各项状态和引用字段/出处。本批为人工编写的虚构样例，不替代 M1-6 的真实 JD 自用验收；校招的实习条件是否应视为“不适用”留待后续契约讨论。

---

## 2026-10-27 · 规划：总体规划、计划整理、分工与审核（规划会话）

**完成**

- 中文首页：根目录 `README.md` 开头改为中文项目介绍，上游英文原文收进折叠块（PR #4）。
- 总体规划 `master-plan.md`（PR #6、#7、#10、#14）：最终目的 O1–O6、M1–M8 的目标与完成标准、待决事项 D1–D6、分工。计划整理为两层：总体规划管目标，`roadmap.md` 是唯一的任务清单，`tasks.md` 并入路线图后删除。
- 分工：用户做决定、合并或授权合并、自用验收；规划者维护计划、审核 PR；执行者（Claude Code）实现；验证者（Codex，独立 worktree）实测工作流、独立编写样例和期望结果。
- 审核并合并 #9、#11、#12、#13、#15、#16、#17。每次审核都在合并到最新 master 的副本上跑全量测试，并独立复核关键结论，结论写在各 PR 的评论里。

**决策**（用户确认）

- 方向：自用优先、兼顾作品集；以后开源给其他同学；岗位方向可配置、不限专业；不赶时间，按里程碑推进。
- D6：联系方式留在 `profile.json`，命令输出默认隐去。

**审核中发现的问题**

- #12：地点判断在"JD 和档案都没写能否远程"时判成了冲突，违反"没写就判未知"的原则。已修复并补测试。
- #13：README 的路径被转义成了控制字符 0x06、0x07。已修复，并新增测试，在 CN 文档和代码里禁止出现 C0 控制字符。
- V1（Codex 第二轮）：和执行者写的示例档案相比，两处填写约定不清（项目名放哪个字段、只在经历里出现的技能算不算），转为 H7，已在 #17 解决。
- #13、#15、#17 连续在工作记录上和 master 冲突，都由规划者解决（两边条目都保留、按时间倒序）。新增约定：请求审核前先合并最新 master。

**下一步**：见路线图的"看板：下次工作"。

---

## 2026-10-27 · H7：Profile 填写约定（项目名称、技能收录范围）

**完成**

- `experience[]` 新增 `name` 字段：项目、竞赛、科研课题的名称放 `name`，单位放 `org`，身份或职位放 `role`，材料没写的留 `null`，不挪用其他字段。
- 技能收录范围：技能栏里的按原文写等级；只在经历描述里出现的技术也收，`level` 为 `null`，`used_in` 指向那段经历；同一技能只记一条。
- `profile.md`（示例、字段说明、"填写约定"、§8 决策记录）、`profile-setup.md`（起草规则）、`jobsearch_cn/profile.py`（校验 `name`）、两份示例档案同步修改。
- 测试：缺少 `name` 报错；示例档案遵守约定（项目类经历都有 `name`，`role` 里没有"个人项目"之类的类别词，没有等级的技能都指向经历）；来源事实检查覆盖 `name`、`org`、`role`。

**决策**

- 新增 `name`，而不是规定"项目名放 `role`"：每个字段只表达一件事，M3 生成简历时不用猜。
- Profile 还没随任何版本发布，直接加入 v1，不升版本号。已有的本地档案需要给每段经历补上 `name`，`profile validate` 会逐条提示（已用 Codex 的 `data/m1-5` 档案只读验证过提示内容）。

**验证**

- 本地全量测试、`security_guards`、`lint_skills` 通过；变异测试：去掉 `name` 的必填检查后有 9 个测试失败。

**下一步**：M2-3 词表外置（代码部分）。

---

## 2026-10-27 · M1-5：Codex 端实测（第二轮，JD 补全与样例建档通过，PR #15）

**完成与决策**

- 在独立工作树 `D:\06_Projects\ai-job-search-cn-codex`、分支 `codex/m1-5-round2` 执行。会话最初仍绑定原目录；文件系统授权生效后，所有实测命令和写入均显式指定独立工作树。通过 `AGENTS.md` 找到共用的 `jd-import.md`、`profile-setup.md`，使用 `conda run --no-capture-output -n ai-job-search-cn python ...`（Python 3.12.15）。
- 用 `--data-dir data/m1-5` 导入 `tests/fixtures/cn/jd/shixiseng_intern.txt`，平台为 `shixiseng`：首次 `created`，岗位 ID 为 `job_d3e712c997b0`，`guard.verdict` 为 `clean`，无警告。
- 完成 `jd-import.md` 第 3 步：先 `jd show`，将规则留空的 `requirements.education` 补为 `{"min":"bachelor","preferred":null}`，出处为 `{"text":"上海 | 本科","method":"agent"}`；原文片段逐字存在于 `raw_text`。整条记录写到 `data/m1-5/inbox/job_d3e712c997b0.json`，`jd validate` 通过，`jd save --data-dir data/m1-5` 返回 `updated`；`id`、`source`、`status`、`guard`、`raw_text` 均保持不变。
- 再次解析并保存同一 JD 返回 `unchanged`，`jd show` 的记录与补全后的记录完全一致，`jd list` 和本地岗位文件均为 1 条。岗位为上海的数据分析实习生，150–200 元/天、2027 届、每周 5 天、至少 3 个月、本科、可转正；公司、远程条件、发布日期和来源链接仍未知。
- 将 `tests/fixtures/cn/profile/tech/sources/resume.txt` 原样复制到 `data/m1-5/profile/sources/resume.txt`，按该材料提取 `profile.json` 并写 `notes.md`；没有复制示例 `profile.json` 中额外的偏好。档案包含 2 段教育、1 段实习、1 个项目、6 项技能，以及奖项、证书、语言各 1 条；所有条目的 `source` 都为 `resume.txt`，成果照录原文，技能等级只采用明确的“熟练 / 熟悉 / 了解”。
- 本轮按用户指定的脱敏样例及继续执行授权建立测试档案。毕业年月取硕士教育结束年月；材料未写的到岗安排、城市、远程与异地意愿、求职方向、薪资和排除项保留 `null` / `[]`，未写成 `source: user`。Docker、PyTorch 没有具体经历依据，`used_in` 留空；项目角色和证书日期也留空。

**验证**

- `python -m jobsearch_cn profile validate --data-dir data/m1-5`：`{"valid":true,"errors":[],"warnings":[]}`；`profile show --data-dir data/m1-5` 的非空联系方式全部为 `***`；复制后的简历与夹具逐字节一致。
- 初次业务操作基于 `eec5123`；检查前将测试分支快进到 `origin/master@ee3a0ec`（合入 M2-2），在该版本重新校验已保存的 JD、档案，均通过。
- `python tools/lint_skills.py`：通过（11 skills、12 commands）；`python tools/security_guards.py`：通过；按 `CONTRIBUTING.md` 补跑 `python tools/check_framework_version.py`，通过。
- `python -m unittest discover -s tests -t .`：共 1005 项，996 项通过、9 项按预期跳过，0 失败、0 错误，耗时 100.573 秒。
- `git check-ignore -v` 确认岗位、补全 JSON、档案、笔记、简历原件及日志都位于已忽略的 `data/`、`logs/` 下。本 PR 只提交 CN 工作记录和路线图；详细 CLI 输出、检查结果和运行元数据留在本机 `logs/m1-5-round2/`。

**ADR-7 的两个问题**

1. Codex 能否通过 `AGENTS.md` 找到工作流：**能**。本轮从同一入口完成了 JD 补全、保存、去重及样例建档、校验，两个工作流共用原有文档，无需新增门户技能。
2. Claude Code 是否读取 `AGENTS.md`：沿用[第一轮执行者记录（PR #13）](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/13)的观察：当时的 Claude Code 会话未自动读取，需主动打开；其业务入口为 `cn-jd-import`、`cn-setup` 两个薄技能。本轮核对了薄技能指向共用文档，**没有重新启动 Claude Code 验证其自动加载行为**。

**遗留与下一步**

- M1-5 的第二轮样例业务验收通过，路线图标记完成。本轮没有验证真实个人档案的逐节确认和偏好问答，不能替代 M2-1 的真实简历自用验收。
- M1-6 仍由用户导入至少 5 份真实 JD 后验收；M1-7 的发布 tag 等其通过后再处理。第一轮历史记录仍见 PR #13。

---

## 2026-10-27 · Codex CI 复验：本地全量与远端检查通过

**完成与决策**

- 环境权限恢复后，确认系统临时目录可正常创建、写入和清理，并在 conda 环境 `ai-job-search-cn`（Python 3.12.15）重跑三项提交前检查。
- 测试从 `eec5123` 开始，结束时 HEAD 为 `3a274af`。已核对两者只修改了 `docs/cn/roadmap.md`、`docs/cn/worklog.md`，代码、测试和 CI 配置均未变化；另行核实最新提交的远端 CI。

**验证**

- `python tools/lint_skills.py`：通过（11 skills、12 commands）。
- `python tools/security_guards.py`：通过。
- `python -m unittest discover -s tests -t . -v`：973 项，964 项通过、9 项按预期跳过，0 失败、0 错误；测试耗时约 96.5 秒。
- 最新提交 `3a274aff2e57819048c9cef8e783e1102756d292` 的 [GitHub CI（run 40476465895）](https://github.com/Mingrui-Ai/ai-job-search-cn/actions/runs/40476465895)：`completed / success`。
- 完整本地日志和运行元数据位于已忽略的 `logs/ci-codex-2026-10-27/full-access/`。

**执行者核对**：`gh run view 40476465895` 为 `success`，对应提交 `3a274af`（分支 `docs/cn-m1-5`）；`logs/ci-codex-2026-10-27/full-access/python-tests.log` 结尾为 `Ran 973 tests … OK (skipped=9)`。第一轮记录中"全量测试受沙箱阻断"的问题已解决。本条由 Codex 在原工作目录写入、未提交，执行者核对后提交；之后 Codex 改用独立的 worktree `ai-job-search-cn-codex`。

**遗留与下一步**

- 本次 CI 验证已完成，保持待合并状态。
- M1-5 的第二轮业务验收（JD 字段补全、建档流程）仍按下一条记录单独跟进，不能由 CI 通过代替。

---

## 2026-10-27 · M1-5：Codex 端实测（第一轮，部分完成）

**Codex 的记录**（由 Codex 写入，执行者整理）

- Codex 读取了 `AGENTS.md`、CN 开发说明和共用的 `jd-import.md`，使用 conda 环境 `ai-job-search-cn`（Python 3.12.15）。
- 用脱敏样例 `shixiseng_intern.txt` 实际执行解析、保存、查询、校验和重复导入：首次 `created`，重复导入 `unchanged`，岗位库仍为 1 条，校验通过。数据在已忽略的 `data/ci-codex-2026-10-27/`。
- `lint_skills`、`security_guards` 通过；`tests.test_cn_agent_entry`、`tests.test_cn_package` 共 11 项通过。
- 全量测试在 Codex 沙箱中因临时目录 `PermissionError` / `WinError 5` 无法运行（把 `TEMP`/`TMP` 改到仓库内仍然如此），日志在已忽略的 `logs/ci-codex-2026-10-27/`。GitHub CLI 受代理限制，Codex 无法查看远端 CI。

**执行者核对**

- `data/ci-codex-2026-10-27/jobs/job_d3e712c997b0.json` 用 `jd validate` 复核有效，`id` 与 Claude Code 实测同一样例时一致（同一份 JD 得到同一指纹）。
- 记录中没有任何 `method: agent` 的出处，学历仍为 null：Codex **没有执行第 3 步"补全"**。
- 建档工作流（`profile-setup.md`）本轮没有测试。
- 全量测试受阻是 Codex 沙箱的限制，不是代码问题：同期 GitHub Actions 上 PR #9、#11、#12 的全量测试（Python 3.10–3.14、Windows）均通过；执行者本地全量测试也通过。

**ADR-7 的两个问题**

1. Codex 能否通过 `AGENTS.md` 找到工作流：**能**。它从 `AGENTS.md` 找到并按 `jd-import.md` 执行了导入。
2. Claude Code 是否读取 `AGENTS.md`：**不会自动读取**。Claude Code 会话开始时只自动加载根目录的 `CLAUDE.md`（上游的求职顾问模板），本会话中 `AGENTS.md` 的内容是靠手动打开才看到的。因此 Claude Code 端依赖技能入口（`cn-jd-import`、`cn-setup`），这正是 ADR-7 的设计；开发约定写在 `AGENTS.md` 里，Claude Code 不会自动遵守，要靠开发会话主动读取。

**发现的问题**

- **两个 Agent 共用一个工作目录会互相干扰。** Codex 测试期间，Claude Code 在同一目录里切换分支、提交，Codex 的验证结果因此对应不上最终提交；Codex 写的工作记录也落在了别的功能分支的工作区里，未提交（已由执行者移到本条）。以后并行工作时，每个 Agent 各用一个 `git worktree`，或一个跑的时候另一个不动仓库。
- Codex 沙箱里跑不了用到临时目录的测试，Codex 端只能跑不依赖临时目录的子集；全量结果以 GitHub Actions 为准。

**遗留**（M1-5 尚未完成）

- 第二轮 Codex 实测：JD 导入要走完第 3 步补全（期望学历补全为本科，出处"上海 | 本科"）；建档流程用 `tests/fixtures/cn/profile/tech/sources/resume.txt` 走一遍，`profile validate` 通过。
- 建议第二轮在独立的 worktree 中进行。

---

## 2026-10-27 · M2-2：硬性条件过滤（`match filter`）；H6

**完成**

- H6（PR #11）：两份示例档案的联系方式改为假数据（13800000000、@example.com），测试固定这一点，并确认 `profile show` 默认不输出任何联系方式；CHANGELOG 中 SQLite 改为"按需接入（总体规划 D4）"。
- `jobsearch_cn/match.py`：按 profile.md §6 的 7 项条件（届别、学历、每周天数、实习月数、地点、岗位类型、排除项）逐项给出 `match` / `conflict` / `unknown`，每项附 JD 的值和出处原文、所用的档案字段；总结论 `ineligible` / `needs_check` / `eligible`。
- `python -m jobsearch_cn match filter <岗位id> [--profile] [--data-dir]`：从岗位库读岗位、从 `data/profile/` 读档案，结果只输出、不保存，不含联系方式。
- `docs/cn/match.md`：过滤规则表（每项三种结论的条件）和输出格式。
- 授权 `Bash(python -m jobsearch_cn match:*)` 登记在 `settings.json`、`ALLOWED_PERMISSIONS`、`ALLOWED_SKILL_TOOLS` 三处。

**决策（实现细节，待规划者确认）**

- 届别 `strict: false` 不符时结论为 `match`，附 `note` 提示，不影响总结论。
- 地点：任务单之外，沿用 profile.md §6 的"愿意搬家"：没有交集但 `relocate: true` 时为 `match`（附 `note`）。只有 `relocate` 为 false，且 JD 不支持远程或档案不接受远程时才判 `conflict`，其余判 `unknown`。比较城市时"上海"与"上海市"视为相同。
- **审核修正**（规划者，PR #12）：初版在 JD 和档案都没写能否远程时判成了 `conflict`，违反"没写判未知"；已按上一条改正并补测试。规划者确认了其余 5 处细节。
- 排除项：关键词只匹配标题；另外按 §6 检查排除的公司（公司名包含即命中）和排除的城市（JD 的工作城市全部在排除名单中才算）。
- 档案只做结构校验，来源文件是否存在不影响过滤结果。

**验证**

- 每项条件的三种结论都有单元测试；5 份样例 JD × 2 份示例档案的 10 组结果写成期望表（`tests/test_cn_match.py` 的 `SAMPLE_TABLE`），逐组对照 JD 原文人工核对，理由写在表上方的注释里。
- 变异测试（14 项，每项都有测试失败）：9 处"没写判未知"分别改成判冲突；去掉 `strict` 判断；地点冲突条件的 4 种错误写法（恢复初版的 bug、只看是否搬家、忽略是否搬家、远程没写也算不能远程）。
- 本地全量测试、`security_guards`、`lint_skills` 通过。

**发现的问题**

- 样例里只有一份 JD 写明了远程与否，地点项常是 `unknown`；实习僧样例标题行的"本科"规则不读，学历项为 `unknown`。这正是"宁可未知、不误判"的预期，但说明 Agent 补全（jd-import 第 3 步）对过滤结果影响很大。

**下一步**：路线图已勾掉 M2-2；之后 M2-3 词表外置或 M2-4 评分，按规划者安排。

---

## 2026-10-27 · v0.2 第 1 项：个人档案（Profile v1）与 cn-setup

**完成**

- 设计稿 `docs/cn/profile.md`，与用户确认三个方向：JSON + Markdown 两个文件；独立的 CN 建档流程、不用上游 `/setup`；从简历文件抽取再问答补全。字段按设计稿实现，使用中再调整。
- `jobsearch_cn/profile.py`：Profile v1 校验。沿用 Job Schema 的约定（所有键必须出现、未知键报错），学历、岗位类型、薪资单位与 JD 记录共用取值；每条事实必须带 `source`（`sources/` 下的文件名或 `user`），`used_in` 必须指向存在的经历，经历 `id` 不能重复，技能名比较时忽略大小写和全角/半角。
- CLI：`profile validate`（同时检查来源文件是否存在、`notes.md` 是否为 UTF-8）和 `profile show`（默认隐去联系方式，`--contact` 才显示）。
- `docs/cn/profile-setup.md`：共用的建档工作流；Claude Code 入口 `.claude/skills/cn-setup`，Codex 入口在 `AGENTS.md`；授权 `Bash(python -m jobsearch_cn profile:*)` 同样登记三处。
- 隐私护栏：`tests/test_cn_profile.py` 检查上游 `/setup` 会改写的 5 个模板文件仍保留占位符（上游 CI 的同类检查只在上游仓库运行），并检查 `data/profile/` 被 git 忽略。
- `tests/test_cn_agent_entry.py` 改为同时覆盖两个工作流。

**决策**

- `exclusions.keywords` 暂定只匹配标题，在硬性过滤中实现。
- 档案的来源规则比 JD 宽：用户本人是权威来源，所以只要求标明出处、来源文件存在，不要求逐字匹配原文。

**验证**

- 本地 Python 3.12：967 个测试全部通过（跳过 9 个），其中 CN 131 个；`security_guards`、`lint_skills` 通过。
- 变异测试：关掉"来源文件必须存在""used_in 必须指向存在的经历""隐去联系方式"，每次都有测试失败。
- 校验器在第一次运行时就发现了设计稿示例里的错误（`used_in` 指向不存在的 `proj-1`），已修正文档。

**遗留问题**

- cn-setup 还没用真实简历实际走过一遍。
- Codex 端（两个工作流）待实测。

**下一步**：v0.2 第 2 项，硬性条件过滤（`match` 命令，按 profile.md §6 的对照表），JD 字段为 null 时判为"未知"。

---

## 2026-10-27 · 第 4 步：v0.1 验收测试与发布准备

**完成**

- `tests/test_cn_acceptance.py`：通过真实 CLI 逐条对应 v0.1 验收清单：
  - 5 份脱敏样例一次粘贴，解析、保存得到 5 个 `created`；倒序再导入全部 `unchanged`；`list`、`show`、`validate` 都对得上；
  - 混合粘贴（正常 JD + 空段 + 超长 JD）只保留正常的那份，超长的给出 `too_long` 警告；只有超长 JD 时退出码 1 且不保存；
  - 几乎什么都没写的 JD 仍生成有效记录（所有字段为 null 或 `[]`），可以保存；
  - 带中文注入句式的 JD：`warnings` 给出摘录，记录里 `guard.verdict` 为 `warn` 且只有计数；除 `raw_text` 外，记录中任何地方都不出现注入内容；
  - `jd save` 收到非 JSON、空 `jobs` 或非记录内容时拒绝，不写入任何东西。
- 版本号改为 `0.1.0`；新增 `docs/cn/CHANGELOG.md`。

**决策**

- `v0.1.0` 的 tag 等 PR #3、#5 合并且 Codex 端实测之后再打，保证 tag 对应的版本满足"两个 Agent 都能完成导入与查询"。
- 注入内容保留在 `raw_text` 中：它是原文的一部分，已被标记；去掉它会让出处校验和去重失真。

**验证**

- 本地 Python 3.12：947 个测试全部通过（跳过 9 个），其中 CN 111 个；`security_guards`、`lint_skills` 通过。

**遗留问题**

- Codex 端实测（用户稍后进行）。
- 工作区 `README.md` 的中文首页改动仍未提交，其中版本写的是 `0.1.0.dev0`，发布时需要同步。

**下一步**：Codex 实测 → 合并 PR #3、#5 → 打 `v0.1.0` → 进入 v0.2（个人档案、硬性条件过滤、可解释评分、中文简历）。

---

## 2026-10-27 · 第 3 步：本地岗位库、去重（G2）与两个 Agent 的入口

**完成**

- `jobsearch_cn/store.py`：每条记录一个 `data/jobs/<id>.json`，原子写入；`--data-dir` 或环境变量 `JOBSEARCH_CN_DATA_DIR` 可换位置。
- 去重：先比内容指纹（`id`），再比规范化后的来源链接（忽略 http/https、大小写、默认端口、末尾斜杠、`utm_*`/`ka`/`spm` 等跟踪参数和参数顺序）。
- 合并规则：同一份 JD 逐字段合并，新值覆盖、空值不抹掉旧值，用户填写的值只被用户值覆盖；同一链接的 JD 改过文字时用新内容替换，保留原 `id`、状态和首次导入时间；状态只由 `jd status` 修改。
- CLI：`jd save`（接受单条记录或 `jd parse` 的输出，任何一条无效就一条都不存）、`jd list [--status]`、`jd show`、`jd status`；`jd parse --save` 一步完成解析和保存，避开 PowerShell 5.1 管道问题。
- `docs/cn/jd-import.md`：两个 Agent 共用的唯一工作流（解析、补全、校验、保存、查询、去重说明）。
- Claude Code：`.claude/skills/cn-jd-import/SKILL.md`，只是指向该文档的薄入口；授权 `Bash(python -m jobsearch_cn jd:*)`，同时登记在 `.claude/settings.json`、`ALLOWED_PERMISSIONS` 和 `ALLOWED_SKILL_TOOLS`。
- Codex：`AGENTS.md` CN 段落加一行指向同一文档；顺带删掉"posting_guard 只识别英文"这条已过时的提醒。
- `tests/test_cn_store.py`（去重、合并、链接规范化、文件安全、CLI）和 `tests/test_cn_agent_entry.py`（两端入口指向同一文档、文档里的每条命令都存在、授权在三处一致）。

**决策**

- 去重顺序与原计划不同：原计划是"可信岗位 ID > URL > 内容指纹"。Schema v1 没有门户岗位 ID 字段，这一级等 v0.3 再加；内容指纹排在 URL 前，因为它表示原文完全相同，合并最安全。
- SQLite 推迟到 v0.2：JSON 文件对现在的规模足够，也方便用户直接查看；等匹配筛选需要查询时再接到同一套接口后面。
- 只授权 `jd` 命令组，不授权整个 `python -m jobsearch_cn`。

**验证**

- 本地 Python 3.12：941 个测试全部通过（跳过 9 个），其中 CN 105 个；`security_guards`、`lint_skills` 通过。
- 变异测试：分别关掉"用户值不被覆盖""按链接去重""空值不抹掉旧值"，每次都有测试失败。
- 端到端（Claude Code 按 jd-import.md 实际执行）：解析并保存实习僧样例 → Agent 补全学历（出处"上海 | 本科"）→ `validate` 通过、`save` 得到 `updated` → 重新解析得到 `unchanged`，补全仍在 → 改用原文没有的出处"本科及以上"时被 `validate` 拒绝。

**发现的问题**

- Git Bash 的 `/tmp/...` 路径 Windows 版 Python 读不到；Agent 在 Windows 上调用 CLI 时应使用 Windows 路径或仓库内的相对路径（工作流已统一用 `data/inbox/`）。
- 本步进行中，工作区的 `README.md` 出现了与本步无关的未提交改动（中文首页），没有放进本 PR。

**遗留问题**

- ADR-7 的 Codex 端还没实测：Codex 能否按 `AGENTS.md` 找到并完成这个工作流。
- Claude Code 是否会读 `AGENTS.md` 已不影响本工作流（它走技能入口），但仍待确认。

**下一步**：第 4 步，测试补强与 `v0.1.0`，先做 Codex 端实测。

---

## 2026-10-27 · 第 2 步：规则解析 `jd parse` 与中文防注入（G1）

**完成**

- `jobsearch_cn/jd_parser.py`：按规则从中文 JD 抽取 Job Schema 记录，覆盖薪资（日薪/月薪/K·N薪/万/年薪/时薪/面议）、届别及强弱、每周天数、实习时长、学历、转正、远程、城市、岗位类型、标题、公司、发布/截止日期、技能词表。每个值都带出处，`method` 为 `rule`；读不准就留空。
- `jobsearch_cn/guard.py`：先复用上游 `tools/posting_guard.py`（隐藏内容、不可见字符、英文注入句式），再补充收窄后的中文注入句式（G1）。只警告不拦截；记录里只存结论和计数，摘录只出现在 `warnings`。
- `python -m jobsearch_cn jd parse [文件] [--site …] [--url …]`：一行 `===` 分隔多份 JD；退出码 0/1/2；编码支持 UTF-8（含 BOM）、UTF-16 BOM，其他按 GB18030 解码并警告；输入几乎全是 `?` 时拒绝（PowerShell 5.1 ASCII 管道问题）。
- `tests/fixtures/cn/jd/`：5 份脱敏样例 JD（BOSS 实习、实习僧、牛客校招、公司官网、社招）。
- `docs/cn/jd-parse.md`：用法、编码、各字段能识别和刻意不识别的写法、补全流程、防注入说明。
- `tests/test_cn_package.py`：允许导入的上游工具改为显式白名单（目前只有 `posting_guard`），并沿导入链检查这些脚本同样不联网。

**决策**

- G1 采用待决事项中的方案一：在 CN 侧封装，不改上游文件；稳定后再考虑回馈上游。
- 记录 `id` 由规范化后的 JD 内容决定（忽略空白和换行差异），为第 3 步去重准备。
- `raw_text` 存清理后的文本；"优先"类学历不算最低要求；不猜年份、不把经历要求读成实习时长。

**验证**

- 本地（conda 环境 `ai-job-search-cn`，Python 3.12.15）：914 个测试全部通过（跳过 9 个），其中 CN 78 个（第 1 步 49 + 第 2 步 29）；`security_guards`、`lint_skills` 通过。
- 冒烟：`jd parse tests/fixtures/cn/jd/boss_intern.txt --site boss` 输出的记录能通过 `jd validate`。

**发现的问题**

- 默认 PATH 上的 `python` 是 Anaconda base 的 3.9.13，项目要求 3.10+，在那里跑测试会大面积误报失败。本地一律用 `conda activate ai-job-search-cn`；项目用 `unittest`，不需要 pytest。

**遗留问题**

- 城市只认固定列表；实习僧标题行里单独的"本科"等需要 Agent 或用户补全。
- 4 个丹麦门户的 CI 红灯仍在等上游修复。

**下一步**：第 3 步，本地存储与去重（G2）及两个 Agent 的入口（D4–5），见 [路线图](roadmap.md)。

---

## 2026-10-26 · 第 1 步：Job Schema 与校验（[PR #1](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/1)）

**完成**

- `jobsearch_cn/schema.py`：岗位记录格式 v1 及其校验，只用标准库。所有字段必须出现（没写的填 null，列表填 `[]`），不认识的字段报错，枚举、取值范围、日期、薪资前后一致都会检查。
- **出处规则**（核心）：每个从 JD 读出的值都要注明出处。
  - 规则解析器或 Agent 给出的片段必须真实出现在原文中；
  - 列表字段（城市、技能）的每一项都必须出现在出处片段里；
  - 比较前统一全角/半角和大小写，去掉空白和零宽字符。

  因此模型没法凭空编造字段。
- `python -m jobsearch_cn jd validate`：输出 JSON，退出码 0 有效、1 无效、2 输入读不了；只接受 UTF-8，带不带 BOM 都可以。命令行逻辑移到 `jobsearch_cn/cli.py`。
- `docs/cn/job-schema.md`：字段说明、出处规则、与上游 `seen_jobs.json` 的对应关系。测试会校验文档里的示例，并要求每个字段名和取值都出现在文档中，防止文档与代码脱节。
- 另一个提交：ADR-9（数据来源与自动化路线）和本工作记录。

**决策**

- 采用"所有字段必须出现"，不采用"缺省即未知"：Agent 补全时必须明确写出"没写"，漏字段会被发现。
- 届别、学历、薪资各用一个小对象，共享一条出处；列表字段从不为 null。
- `status` 沿用上游 `seen_jobs.json` 的词表，以后并入上游岗位池不用转换。

**验证**

- 本地：885 个测试全部通过（上游 836 + CN 49）；lint、安全检查通过。
- 变异测试：分别关掉"值必须有出处""出处必须在原文中""列表项必须在出处中"和"复制差异折叠"四条规则，每次都有对应的测试失败。
- 冒烟测试：文档示例通过文件路径和标准输入校验，退出码都是 0；改成非法状态后退出码 1，并给出明确的错误。
- CI（[run 40333450292](https://github.com/Mingrui-Ai/ai-job-search-cn/actions/runs/40333450292)）：Python 3.10–3.14 和 Windows 全部通过，新测试在 Python 3.10 和 Windows 上都实际跑过；只有 4 个已知的丹麦门户红灯。

**发现的问题**

- Windows PowerShell 5.1 向外部程序传管道默认用 US-ASCII，中文会悄悄变成 `?`（实测 `'广州' | python` 收到 `b'??'`）。文档已改为推荐直接传文件路径，并记入基线报告 §4.2。
- 中文 Windows 上把 Python 输出重定向到文件，得到的是 GBK 编码；CLI 会拒绝这类文件（退出码 2），不会误读。
- 写代码时，正则里的 Unicode 转义一度被写成了真实的零宽字符，已改回转义写法，并扫描了所有新文件。以后涉及特殊字符一律用 `chr()` 构造。

**遗留问题**

- 第 2 步的 `jd parse` 要专门处理 PowerShell 5.1 管道的问题：优先用文件输入，并考虑在输入几乎全是 `?` 时直接报错。
- 4 个丹麦门户的 CI 红灯仍在等上游修复。

**下一步**：第 2 步，规则抽取（`jd parse`）和中文注入检测（G1），支持一次粘贴多份 JD。

---

## 2026-10-26 · Day 0–1：建仓、基线、审计与方向决策

**完成**

- 建立私有仓库 [Mingrui-Ai/ai-job-search-cn](https://github.com/Mingrui-Ai/ai-job-search-cn)，基线为上游 `master@e16acee`（v1.7.3 之后 50 个提交）。`upstream` 只能拉取（push 已禁用）；`gh` 的默认仓库固定为私有仓库，避免 issue/PR 误发到上游公开仓库。
- 环境：conda 环境 `ai-job-search-cn`（Python 3.12.15），Bun 1.4.4，6 个门户 CLI 的依赖。
- 基线测试：上游 836 个测试在 Windows 上全部通过，9 个跳过属预期。4 个丹麦门户 CLI 的类型检查失败，原因是 Bun 1.4.4 的依赖提升变化（用 Bun 1.4.3 重装后 0 错误），与本项目无关。详见 [基线报告](baseline-report.md)。
- 审计上游代码，写出 [迁移方案](cn-migration-plan.md)。发现两个本地化缺口：
  - `posting_guard` 只识别英文注入句式（G1，P0）；
  - `job_key` 对中文公司名、岗位名退化为哈希键（G2）。
- 搭建 `jobsearch_cn/` 骨架和边界测试：只用标准库、离线、UTF-8 输出。CI 中 Python 3.10–3.14 和 Windows 全部通过。

**决策**（理由见迁移方案 ADR-6～9）

- 工具同时兼容 Codex 和 Claude Code。
- 项目不提供模型 API，用户自带。
- 个人档案只存本地 `data/profile/`。
- 数据来源分三层：粘贴导入 → 单个公开链接 → 核实过的公司官网和招聘系统。
- 最终目标是高度自动化。招聘平台站内自动化违反其用户协议，是否使用由用户决定，放在核心流程之后，并设护栏。
- 协作方式：每一步在 `feat/cn-*` 分支实现并开 PR，合并到 `master` 前由用户确认。

**robots.txt 实测**（`tools/robots_check.py`；只是第一道门槛，还要看用户协议）

| 网站 | 结果 |
| --- | --- |
| BOSS直聘 | 搜索页本身允许，但带搜索条件（`?query=`、`?city=`、`?salary=` 等）的 URL 全部禁止；点名封禁 `Jobuispider` |
| 智联招聘 | 禁止 |
| 前程无忧、拉勾、腾讯校招、美团校招 | 返回的不是 robots.txt，无法确认，按禁止处理 |
| 实习僧 | robots.txt 为空文件 |
| 牛客、猎聘、字节跳动校招、Moka | 测试的路径允许 |
| 阿里、百度、京东校招、飞书招聘 | 未发布 robots.txt |

**遗留问题**

- CI 中 4 个丹麦门户的类型检查红灯，等上游修复。
- 待定：中文简历格式（第 2 周）；G1 的修复位置（第 2 步按"CN 侧封装"实现）。

**下一步**：第 1 步，Job Schema 与校验。
