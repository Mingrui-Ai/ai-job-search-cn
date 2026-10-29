# AI Job Search CN 文档

面向中国互联网招聘市场的多 Agent 求职系统，基于上游 [ai-job-search-dev/ai-job-search](https://github.com/ai-job-search-dev/ai-job-search) 增量开发。MVP 闭环为：**导入中文 JD → 结构化提取 → 个人档案匹配 → 中文简历生成与审核 → 岗位状态保存**。

本项目是本地工具：不托管服务、不提供模型 API，用户使用自己的 Codex 或 Claude Code（自带订阅或 API Key）；工具同时兼容这两个 Agent；个人档案只存在本地。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [roadmap.md](roadmap.md) | 路线图：唯一的任务清单和进度表，按里程碑拆分的任务、负责人、验收标准，随每个 PR 更新 |
| [master-plan.md](master-plan.md) | 总体规划：最终目的、设计原则、系统全貌、M1–M8 的目标与完成标准、待决事项、分工 |
| [worklog.md](worklog.md) | 工作记录：每一步做了什么、验证结果、遗留问题。2026-10-28 起每条一个文件，放在 [worklog/](worklog/) |
| [CHANGELOG.md](CHANGELOG.md) | 版本更新记录（CN） |
| [cn-migration-plan.md](cn-migration-plan.md) | 上游审计结论、架构决策（ADR-1 至 ADR-9）、目录结构、上游同步流程 |
| [job-schema.md](job-schema.md) | 岗位记录格式（Job Schema v1）：字段说明、出处规则、与上游字段的对应 |
| [jd-import.md](jd-import.md) | JD 导入工作流（Codex 与 Claude Code 共用）：解析、补全、校验、保存、去重、查询 |
| [profile.md](profile.md) | 个人档案格式（Profile v1）：字段、来源规则、与 JD 硬性条件的对照 |
| [profile-setup.md](profile-setup.md) | 建档工作流 cn-setup（Codex 与 Claude Code 共用） |
| [match.md](match.md) | 匹配：评分工作流 cn-match（三个 Agent 共用）；`match filter` 硬性条件过滤（符合 / 冲突 / 未知 及依据）；可解释评分 `match score / validate / save / show / list` 和匹配记录 |
| [jd-parse.md](jd-parse.md) | `jd parse`：用法、编码处理、各字段能识别的写法、补全流程、防注入检查 |
| [baseline-report.md](baseline-report.md) | Day 0 环境、测试基线、已知问题与 Windows 兼容性记录 |
| [oss-privacy-review.md](oss-privacy-review.md) | 开源前隐私审查（2026-10-28）：公开范围、各类扫描结果和处理结论、转为公开前的操作 |
| [plan/kickoff-guide-v0.1.md](plan/kickoff-guide-v0.1.md) | 原始文件《AI_Job_Search_CN_项目启动指导_v0.1.md》（存档） |
| [plan/initial-guidelines.md](plan/initial-guidelines.md) | 原始文件《初步guidelines.md》（存档） |

`plan/` 下的两份原始计划原样存档、不再修改。之后的计划分两层：目的、里程碑和待决事项写在 `master-plan.md`，任务和进度写在 `roadmap.md`；架构决策写在 `cn-migration-plan.md`。

## 开发环境（Windows）

```powershell
conda activate ai-job-search-cn          # Python 3.12；Anaconda base 是 3.9，版本不够
cd D:\06_Projects\ai-job-search\cn
codex                                    # 或 claude；要从已激活环境的终端启动
```

- 用 `python`，不要用 `python3`：本机的 `python3` 是微软商店占位程序。
- Bun 通过 winget 安装；如果提示找不到 `bun`，重开终端即可。
- LaTeX 第二周再装。

## 常用命令

```powershell
# 提交前检查（与 CI 一致）
python tools\lint_skills.py
python tools\security_guards.py
python -m unittest discover -s tests -t .

# 只跑 CN 测试
python -m unittest discover -s tests -t . -p "test_cn_*.py" -v

# CN CLI
python -m jobsearch_cn --version
python -m jobsearch_cn jd parse jd.txt --site boss   # 从 JD 文本抽取岗位记录（多份用一行 === 分隔）
python -m jobsearch_cn jd validate job.json          # 按 job-schema.md 校验一条岗位记录
python -m jobsearch_cn jd parse jd.txt --save        # 解析并保存到本地岗位库 data/jobs/（自动去重）
python -m jobsearch_cn jd list                       # 列出岗位库；jd show <id>、jd status <id> <状态>
python -m jobsearch_cn match filter <id>             # 用个人档案过滤一个已保存的岗位（硬性条件）
python -m jobsearch_cn profile validate              # 校验 data/profile/ 下的个人档案；profile show 查看（隐去联系方式）
```

## 仓库与分支约定

- `origin` = 本仓库 `Mingrui-Ai/ai-job-search-cn`；`upstream` = 上游，只拉取（push 已禁用）。
- `gh` 的默认仓库已固定为本仓库，`gh issue/pr create` 不会误发到上游仓库。
- 功能开发在 `feat/cn-*` 分支进行，合并回 `master`。提交信息沿用上游的 Conventional Commits，例如 `feat(cn): add Chinese JD import`。
- 推送 `master` 和开 PR 都会触发 CI。
- 个人数据已被 `.gitignore` 忽略：`data/`（含个人档案 `data/profile/`）、`logs/`、`documents/` 下的个人文件、求职记录。提交前用 `git status` 确认。
- 上游 `/setup` 会把个人信息写进被 git 跟踪的 `CLAUDE.md` 等文件，不要用它；CN 建档用 [profile-setup.md](profile-setup.md)。

### 多个 Agent 并行工作

两个 Agent 在同一个目录里工作会互相干扰：一方切换分支或提交，另一方的文件和验证结果随之改变（M1-5 实测中发生过）。所以每个 Agent 用自己的 `git worktree`：同一个仓库、共享提交历史，但各有一个工作目录。2026-10-29 起，这些目录都放在 `D:\06_Projects\ai-job-search\` 下：

| 目录 | 使用者 |
| --- | --- |
| `cn` | Claude A（执行：主线功能开发） |
| `cn-b` | Claude B（第二执行者） |
| `cn-c` | Claude C（第三执行者） |
| `cn-codex` | Codex（实测、验证） |
| `cn-plan` | 规划 |

```powershell
git worktree list                                         # 查看所有工作目录
git worktree add -b <新分支> ../cn-<名字> origin/master     # 新建
git worktree remove ../cn-<名字>                           # 删除（目录里不能有未提交的改动）
```

- 一个分支同一时间只能在一个目录里签出。要查看别人正在用的分支，用 `git switch --detach origin/<分支>`。
- 各目录的 `data/`、`logs/` 是分开的（都被 git 忽略）。要用同一份数据，设置环境变量 `JOBSEARCH_CN_DATA_DIR` 或加 `--data-dir`。
- conda 环境 `ai-job-search-cn` 各目录共用。

### 多会话协作

2026-10-29 起，本仓库同时有一个规划会话和几个工作会话：几个 Claude Code 执行者，加上 Codex 验证者。分工见[总体规划 §8](master-plan.md#8-协作方式)，任务和进度见[路线图](roadmap.md)。

- **派活**：规划者先把任务单写进路线图，再直接通知各会话。Claude Code 会话之间用 SendMessage。Codex 的任务写在规划者维护的本机收件箱文件里（在仓库外，不入 git），再用 `codex queue` 通知它。用户不必转贴任务。
- **回报**：Claude Code 会话在开 PR、推送新提交或需要裁定时，发消息给规划者；Codex 写在 PR 评论里。规划者用一个监视脚本跟踪 PR 的事件和 Codex 每一轮的结束。
- **裁定只有一个出口**：验证者的复核意见写在 PR 评论里，由规划者裁定，再通知作者要改什么。工作会话之间不互相派活。
- **交给 Codex 的事**：需要第二个模型的工作，即留出样例、规则改动的独立复核、Codex 入口的实测、真实数据验收。实现交给 Claude Code 会话。
- **留出样例**：要检验的 PR 开出之前不推送。执行者在那之前不看验证者的工作树和分支。
- **公开仓库**：提交、PR 文字和评论推送后立即公开。不写真实岗位、档案内容、本机用户名和密钥；用户的真实数据只在本机的 `data/` 下。
- **操作约定**：
  - `git push` 单独执行，看完整输出；
  - 改 `tools/security_guards.py`（哪怕只是注释）之前，先征得用户本人同意；
  - 改代码用编辑工具，不用脚本绕过确认；
  - 请求审核前合入最新 master，跑全量测试、`security_guards`、`lint_skills`；
  - 路线图只改自己那一项（见路线图的"更新规则"）。
