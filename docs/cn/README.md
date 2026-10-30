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
| [cn-migration-plan.md](cn-migration-plan.md) | 上游审计结论、架构决策（ADR）、目录结构、上游同步流程 |
| [job-schema.md](job-schema.md) | 岗位记录格式（Job Schema v1）：字段说明、出处规则、与上游字段的对应 |
| [jd-import.md](jd-import.md) | JD 导入工作流（Codex 与 Claude Code 共用）：解析、补全、校验、保存、去重、查询 |
| [profile.md](profile.md) | 个人档案格式（Profile v1）：字段、来源规则、与 JD 硬性条件的对照 |
| [profile-setup.md](profile-setup.md) | 建档工作流 cn-setup（Codex 与 Claude Code 共用） |
| [match.md](match.md) | 匹配：评分工作流 cn-match（三个 Agent 共用）；`match filter` 硬性条件过滤（符合 / 冲突 / 未知 及依据）；可解释评分 `match score / validate / save / show / list` 和匹配记录 |
| [jd-parse.md](jd-parse.md) | `jd parse`：用法、编码处理、各字段能识别的写法、补全流程、防注入检查 |
| [baseline-report.md](baseline-report.md) | Day 0 环境、测试基线、已知问题与 Windows 兼容性记录 |
| [oss-privacy-review.md](oss-privacy-review.md) | 开源前隐私审查（2026-10-28）：公开范围、各类扫描结果和处理结论、转为公开前的操作 |
| [resume-pdf.md](resume-pdf.md) | 生成 PDF 简历：安装 Typst（便携版）、字体、`resume sample`、压成一页和检查 |
| [m3-0-resume-prototypes.md](m3-0-resume-prototypes.md) | M3-0 简历生成方式的原型对比（2026-10-30）：三种同时出 Word 和 PDF 的做法、开源简历模板的调研和许可、推荐方案和 M3-2 的检查清单 |
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
python -m jobsearch_cn match report                  # 把已保存的评分生成可读的报告（HTML）和反馈表（CSV），写到 data/reports/
python -m jobsearch_cn resume sample                 # 用固定的虚构内容生成一页 PDF，验证 Typst 和字体（docs/cn/resume-pdf.md）
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
| `cn-codex` | Codex A（实测、验证） |
| `cn-codex-b` | Codex B（审核 PR） |
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

2026-10-29 起，本仓库同时有一个规划会话和几个工作会话：Claude Code 执行者 A、B、C，Codex A 验证者，Codex B 审核者。分工见[总体规划 §8](master-plan.md#8-协作方式)，任务和进度见[路线图](roadmap.md)。

- **派活**：规划者先把任务单写进路线图，再直接通知各会话。Claude Code 会话之间用 SendMessage。Codex 的任务写在规划者维护的本机收件箱文件里（在仓库外，不入 git，Codex A、B 各一个），再用 `codex queue` 通知它。用户不必转贴任务。
- **回报**：Claude Code 会话在开 PR、推送新提交或需要裁定时，发消息给规划者；Codex 写在 PR 评论里。规划者用一个监视脚本跟踪 PR 的事件和两个 Codex 每一轮的结束。
- **审核和合并**：实现类的 PR 开出后，规划者通知 Codex B 审核。Codex B 在自己的工作树里试合并最新 master、跑检查，在 PR 评论里写结论和按 P1–P3 分级的问题。要改的地方由规划者转告作者；Codex B 建议合并、CI 通过后，由规划者合并。规划者自己的文档 PR 和 Codex A 的测试数据 PR 不经过 Codex B。
- **裁定只有一个出口**：审核者和验证者的意见都写在 PR 评论里，范围和口径由规划者裁定，再通知作者要改什么。工作会话之间不互相派活。
- **交给 Codex 的事**：需要第二个模型的工作，即留出样例、规则改动的独立复核、Codex 入口的实测、真实数据验收。实现交给 Claude Code 会话。
- **留出样例**：要检验的 PR 开出之前不推送。执行者在那之前不看验证者的工作树和分支。
- **公开仓库**：提交、PR 文字和评论推送后立即公开。不写真实岗位、档案内容、本机用户名和密钥；用户的真实数据只在本机的 `data/` 下。
- **操作约定**：
  - `git push` 单独执行，看完整输出；
  - 改 `tools/security_guards.py`（哪怕只是注释）之前，先征得用户本人同意；
  - 改代码用编辑工具，不用脚本绕过确认；
  - 请求审核前合入最新 master，跑全量测试、`security_guards`、`lint_skills`；
  - 路线图只改自己那一项（见路线图的"更新规则"）。

### 中断后恢复

会话随时可能中断：额度用完、网络断开、窗口被关掉。master 有分支保护，没做完的改动只会留在各自的分支和工作树里，不会进入 master。下面几条让中断的影响尽量小。

- **随做随记，不留收尾**：开工时就在 `docs/cn/worklog/` 建好这一项的工作记录，有了决定、遇到问题就写一句；PR 描述也随时更新。这样中断以后，新会话读分支上的记录就能接着做，不需要专门收工。
- **新会话开工先查**（新开或恢复都一样）：
  1. `git status`、`git log --oneline @{u}..`（有没有没推送的提交），以及有没有进行到一半的合并（`git status` 会提示）；
  2. 自己的 PR 现在是什么状态、有没有新的审核意见：`gh pr view <号> --comments`；
  3. 叠在别的分支上的工作（例如在 H16 的分支上做 M2-6b）：基础分支有没有新提交，合并了没有；
  4. 读自己分支上的工作记录草稿，接着做。拿不准时发消息问规划者。
- **危险操作**：
  - 任何工作树里都不运行 `git clean -x` 或 `-X`。它会删掉被 git 忽略的 `data/`，里面有用户的真实档案和岗位，只有这一份；
  - 不用裸的 `git stash` / `git stash pop`：所有工作树共用一个 stash 栈，可能弹出别人的改动。要暂存，就用临时提交；
  - 不在别人的工作树里切分支、改文件、重置，也不删除别人的工作树。
- **规划者中断时**：工作会话照常做手上的任务；PR 开了就等审核，不自己合并；需要裁定的问题写在 PR 评论里，等规划者回来或者新规划者接手。规划者的交接手册和现场记录在本机的协调目录里（不入 git），新规划者从那里接手。
- **审核者或验证者中断时**（例如 Codex 的 API 出故障）：规划者暂停给它们排消息，审核由规划者代做，或者请一个没参与的 Claude 会话交叉审；没做完的任务原样留在收件箱里。恢复或新开会话后，规划者把这段时间合并了什么、哪些任务已经由别人做完，合成一条消息告诉它（2026-10-29 Codex B 中断时就是这样接上的）。
