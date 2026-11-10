---
name: cn-application
description: >
  Records the user's job applications in the local application database: an application drafted or
  sent (with the resume files sent), status changes, replies, notes, follow-up dates, voiding a
  mistaken entry, the follow-up list and backups, each event write previewed and confirmed by the user
  first; also generates offline dashboards. Triggers on: 记投递, 记一下投递, 我投了, 投了简历, 投递记录, 收到回复, 面试邀请, 跟进, 待跟进,
  作废记录, 记错了, 备份投递记录, 投递复盘, 历史评分对照, 离线投递看板, cn-application
allowed-tools: Read, Bash(python -m jobsearch_cn application:*), Bash(python -m jobsearch_cn jd:*)
---

# CN Application

Follow section 16 of `docs/cn/applications.md` exactly - read it first. It is shared with Codex and DeepSeek Harness (ADR-7); do not restate or extend it here. For retrospectives follow `docs/cn/calibration.md`; weight trials hand off to cn-match.

Every event write uses `--preview` first, shown to the user, then the same arguments with its `--request-id` only after user agreement. Never invent an id; pass `--actor claude_code`. Do not use upstream /outcome or /apply.

Write only the user's own words into summaries, notes and reasons, never their contact details.

For follow-up drafting, query and select under section 17, then hand over to `cn-resume`; this skill does not write materials or dispatch reviews. For offline dashboards follow section 19; report generation does not write events or require their preview parameters.
