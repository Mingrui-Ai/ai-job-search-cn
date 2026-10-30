# 2026-10-30 · M2-6f：去外地面试的偏好（Claude A 会话）

规划者按经理意见书-003 立项，要在 M2-5 第二轮之前合并。分支 `feat/cn-m2-6f-interview-travel` 叠在 `feat/cn-m2-6e-salary`（#93）上开；#93 合并后合入 master，再开 PR。路线图的任务单由 Claude C 在整理路线图的 PR 里补，本项的 PR 只勾这一项。

**隐私**：用户本人愿不愿意去外地面试只写在本机档案里，不写进仓库。

**规则**（规划者 10-30 定）

- 档案：`availability` 加一项，取值愿意、不愿意，或没说（null）；旧档案没有这一项的按"没说"。`profile validate` 校验取值；profile-setup.md 加这个问题（cn-setup 入口只指向 profile-setup.md，不另写）。
- 面试一项（`match._interview`）：JD 只写了到意向城市（`cities` 加 `acceptable_cities`）以外现场面试、没有线上选项时，档案写"不愿意"的，从 `match` 改成 `unknown`，理由写清"你暂时不去外地面试，投之前先问能不能线上面试"；"愿意"或没说的，维持 `match` 加路费提示。能线上面试的、有一个面试地点在意向城市内的、没写地点的，都不受影响。不判冲突：JD 写了面试地点，不等于不能线上面试。
- 规划者 10-30 在消息里同意的两处：
  - `mixed`（有一轮要现场面试）和 `onsite` 一样处理：那一轮在外地时，"不愿意"也判 `unknown`；在意向城市内的仍是 `match`；
  - 档案一个意向城市都没写时不改：判断不了面试地点是不是外地，维持 `match` 和"档案没写意向城市"的提示。
- `RULES_VERSION` 在当时 master 的值上加 1，合并前规划者核对顺序（#90 用了 7，#91 用 8，#93 合并前改成 9）。分支上暂时写 8，开 PR 前改。

**做法**

- 字段名 `availability.interview_travel`：`true` 愿意，`false` 暂时不去，null 没说（规划者同意）。
  - 和 M2-6b、M2-6e 的字段不同，这个键可以不写：`profile._obj`、`_keys` 加了 `optional` 参数，`AVAILABILITY_OPTIONAL` 里的键不写不报 missing，写了也不算 unknown field；
  - 两份示例档案都没有这个键，正好当"旧档案"用；profile.md 的示例写了 `true`。
- `match._interview`：所有面试地点都在意向城市以外、`interview_travel` 为 `false` 时判 `unknown`，理由"JD 写要现场面试，在北京，不在你的意向城市内；你暂时不去外地面试，投之前先问能不能线上面试"（`mixed` 写"有一轮要现场面试"），不附 `note`。检查的 `profile` 一栏多了 `availability.interview_travel`。
- 报告：待确认事项里这一条的"怎么确认"是"问 HR 能不能线上面试"。面试的 `unknown` 和以前一样不进总结论（M2-6c）。
- 文档：match.md 的检查表、说明、未知的理由、`rules_version`；profile.md 的 `availability` 一行、示例、"已定与待定"；profile-setup.md 第 4 步。
- 测试：
  - `test_cn_match.Interview`：四种档案（没有这个键、null、true、false）× 六种 JD（只在外地现场、线上、可选线上、有一个地点在意向城市内、现场没写地点、没写面试形式），只有"false × 只在外地现场"变成 `unknown`，其余结果、理由和提示都和没有这个键时相同；`onsite`、`mixed` 的理由；档案没写意向城市时不变；
  - `test_cn_profile`：不写这个键也有效；`true`、`false`、null 有效；其他值报错；
  - `test_cn_report`：待确认事项提示问 HR 能不能线上面试。

**状态（2026-10-30）**

- 做到哪了：代码、测试、文档已完成，已合入 #93 第一轮审核的修改（`d9286cb`）。全量检查：unittest 1377 项 OK（skipped=11），security_guards、lint_skills 通过。
- 下一步：等 #93 合并，合入 master；`RULES_VERSION` 按规划者通知的值改；路线图勾掉 M2-6f（Claude C 的整理 PR 补上任务单以后）；开 PR，Codex B 审。
