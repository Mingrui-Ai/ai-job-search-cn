# 工作记录

按时间倒序记录：做了什么、为什么这样做、验证结果、遗留问题、下一步。每完成一步（通常对应一个 PR），在最上方追加一条。架构决策的完整理由见 [迁移方案](cn-migration-plan.md)，这里只记过程和结果。

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
