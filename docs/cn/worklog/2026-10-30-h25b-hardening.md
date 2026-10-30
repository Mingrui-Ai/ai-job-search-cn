# 2026-10-30 · H25b：发布前的安全加固（Claude B 会话）

> 状态：**进行中**。分支 `fix/cn-h25b-hardening`，从 master `9b94274` 开出。来源：Codex B 的 V18 安全审查（报告在 Codex B 的工作树里，只读）。规划者安排：P2-1 数据目录里的链接、P2-2 深层 DOCX、P2-3 PDF 超时的进程树、P3-2 守卫加 `/data/`；`RULES_VERSION` 不加。可以拆成两个 PR。

**进展**

- P3-2：改 `tools/security_guards.py` 之前，2026-10-30 用 AskUserQuestion 问了用户本人，用户选"同意，加上 /data/"。`REQUIRED_IGNORE_RULES` 加上 `/data/`。`test_security_guards.py` 新增两项：删掉 `/data/` 时守卫报错；用真实的 `git check-ignore` 核对 `data/` 下的代表路径（jobs、matches、drafts、reports、profile、inbox）都被忽略，`tests/fixtures/cn/` 不被忽略。
- 2026-10-30 暂停：规划者让先改 #79（H20）的审核意见。（已改完，`187259a`）
- P2-1：新增 `store.safe_dir(root, *parts)`。数据根本身可以是链接（`--data-dir` 是用户的选择）；根下面的 `jobs/`、`matches/`、`matches/drafts/`、`reports/` 是符号链接或 junction（`Path.is_junction`）时拒绝，抛 `StoreError`；建好以后再核对解析后的路径仍在数据根里。`Store._write`、`MatchStore.save / write_draft`、`cli._report_dir` 都走它；`match score --save/--draft`、`match save`、`match report` 的 `StoreError` 转成退出码 2 的 `{"error": ...}`，和 `jd save` 一致。同目录的 mkstemp + os.replace 保留。检查和写入之间被换成链接的竞态不覆盖，写在注释里。
- 测试 `test_cn_store_links.py`（链接和目标都在临时目录里；不能建符号链接时用 `_winapi.CreateJunction`）：jobs、matches、drafts、reports 四处链接都拒绝且外面没有文件，`jd parse --save` 走 CLI 得到退出码 2 和结构化错误；真实文件夹、链接的数据根、不存在的数据根照常写。5 个拒绝用例在 master 的代码上都失败。
- jd-import.md 写明子文件夹必须是真实文件夹。全量测试、`security_guards`、`lint_skills` 通过。
- 2026-10-30 再暂停：#79 还有一项（专业名的语境）。
- 开出 PR #85（P2-1、P3-2）。规划者裁定：检查和写入之间被换成链接的竞态记为已知限制，不另立任务，M8-3 发布前的安全复查再看。P2-2、P2-3 在 `fix/cn-h25b-extract` 上另开 PR；两个 PR 都合并后再勾路线图的 H25b。

**第 2 部分**（分支 `fix/cn-h25b-extract`）

- #85 已合并。Codex B 的 P3-1 并进本部分：`Path.is_junction` 从 3.12 才有。`_is_link` 补上 `st_file_attributes` 的 reparse point 检查；`safe_dir` 每建一级先核对解析后的路径，报错前不再在外面建出 `drafts/`。`OlderPython` 两个用例在 #85 的 `store.py` 上都失败。
- P2-2：`_word_text` 改成显式栈，不再递归。用 4 万棵随机文档树和旧实现对比，输出全部一致。`_parse_document` 用 `iterparse` 边读边数，节点超 20 万、深度超 256 就停；`document.xml` 解压后上限 16 MB，既看 ZIP 头，也用 `read(上限 + 1)` 防头部造假；输入文件上限 50 MB。超限报不含原文的 `ExtractionError`。新增 `Budgets`。
- P2-3：新增 `_run_tree`，用 Popen 代替 `subprocess.run`。Windows 用 Job Object（`KILL_ON_JOB_CLOSE`），POSIX 用新会话 + `killpg`；超时后回收管道，最多再等 5 秒。`tools/verify_pdf.py` 没改，权限白名单没动。原有 PDF 测试的 mock 从 `subprocess.run` 改到 `_run_tree`，断言不变。
- `ProcessTree` 用短时合成孙进程回归。对照实测老写法（`subprocess.run`）：0.8 秒超时，2.2 秒才返回，孙进程照样跑完；新写法两点都过。中途有一次对照脚本卡住超过 2 分钟，查下来是我用 stdin 跑 unittest 的方式造成的，不是老代码的行为，已换成独立脚本重测。
- 已知局限：Windows 上 Job Object 建不出来时退回只杀桥接进程；Popen 和 AssignProcessToJobObject 之间有极短的窗口，桥接是 Python，启动远慢于这一步，实际不会抢先启动 pdftotext。
- 文档：profile-setup.md 写明上限。
