# 2026-10-30 · H25b：发布前的安全加固（Claude B 会话）

> 状态：**进行中**。分支 `fix/cn-h25b-hardening`，从 master `9b94274` 开出。来源：Codex B 的 V18 安全审查（报告在 Codex B 的工作树里，只读）。规划者安排：P2-1 数据目录里的链接、P2-2 深层 DOCX、P2-3 PDF 超时的进程树、P3-2 守卫加 `/data/`；`RULES_VERSION` 不加。可以拆成两个 PR。

**进展**

- P3-2：改 `tools/security_guards.py` 之前，2026-10-30 用 AskUserQuestion 问了用户本人，用户选"同意，加上 /data/"。`REQUIRED_IGNORE_RULES` 加上 `/data/`。`test_security_guards.py` 新增两项：删掉 `/data/` 时守卫报错；用真实的 `git check-ignore` 核对 `data/` 下的代表路径（jobs、matches、drafts、reports、profile、inbox）都被忽略，`tests/fixtures/cn/` 不被忽略。
- 2026-10-30 暂停：规划者让先改 #79（H20）的审核意见。
