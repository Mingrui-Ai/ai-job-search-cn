---
name: cn-setup
description: >
  Builds or updates the local Chinese candidate profile in data/profile/ (profile.json + notes.md)
  from the user's resume files and follow-up questions, every fact with its source, validated with
  `python -m jobsearch_cn profile validate`. Use instead of the upstream /setup. Triggers on:
  建档, 个人档案, 建立档案, 更新档案, 我的简历信息, cn-setup, cn setup
allowed-tools: Read, Write, Glob, AskUserQuestion, Bash(python -m jobsearch_cn profile:*)
---

# CN Setup

Follow `docs/cn/profile-setup.md` exactly - read it first. It is the single workflow shared with
Codex (ADR-7 in `docs/cn/cn-migration-plan.md`); do not restate or extend it here.

Write only under `data/profile/`. Never run or emulate the upstream /setup: it writes personal
data into tracked files.
