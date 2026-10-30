# 2026-10-30 · H20：可选学历取较低的一个，专业里的词不算技能（Claude B 会话）

> 状态：**进行中**。分支 `feat/cn-h20-edu-major`，从 `origin/feat/cn-m2-6c-interview` 叠着开（#73 合并后合入 master 再开 PR）。任务单见路线图 §2 H20；V10 是留出样例，PR 开出之前不看 `cn-codex` 和 `codex/v10-*`。

**起因**（V8 对照 #61，`tests/fixtures/cn/jd-h16-holdout/comparison.md`）

- "本科或硕士及以上学历"读成最低 master，应为 bachelor；"大专或本科及以上学历"读成 bachelor，应为 associate；
- "统计学或市场营销相关专业"里的统计学读成技能。

**进展**

- 开分支 `feat/cn-h20-edu-major`。

**#73 待改（规划者 2026-10-30 在 #73 加的要求，和 Codex B 的审核意见一起改）**

- 推断出年份的到岗日期，检查理由里写明是推断的，例如"JD 写'11月1日前到岗'，按发布日期推断为 2026-11-01"，并补测试。
