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
| [plan/kickoff-guide-v0.1.md](plan/kickoff-guide-v0.1.md) | 原始文件《AI_Job_Search_CN_项目启动指导_v0.1.md》（存档） |
| [plan/initial-guidelines.md](plan/initial-guidelines.md) | 原始文件《初步guidelines.md》（存档） |

`plan/` 下的两份原始计划原样存档、不再修改。之后的计划分两层：目的、里程碑和待决事项写在 `master-plan.md`，任务和进度写在 `roadmap.md`；架构决策写在 `cn-migration-plan.md`。

## 开发环境（Windows）

```powershell
conda activate ai-job-search-cn          # Python 3.12；Anaconda base 是 3.9，版本不够
cd D:\06_Projects\ai-job-search-cn
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

- `origin` = 私有仓库 `Mingrui-Ai/ai-job-search-cn`；`upstream` = 上游，只拉取（push 已禁用）。
- `gh` 的默认仓库已固定为私有仓库，`gh issue/pr create` 不会误发到上游公开仓库。
- 功能开发在 `feat/cn-*` 分支进行，合并回 `master`。提交信息沿用上游的 Conventional Commits，例如 `feat(cn): add Chinese JD import`。
- 推送 `master` 和开 PR 都会触发 CI。
- 个人数据已被 `.gitignore` 忽略：`data/`（含个人档案 `data/profile/`）、`logs/`、`documents/` 下的个人文件、求职记录。提交前用 `git status` 确认。
- 上游 `/setup` 会把个人信息写进被 git 跟踪的 `CLAUDE.md` 等文件，不要用它；CN 建档用 [profile-setup.md](profile-setup.md)。

### 多个 Agent 并行工作

两个 Agent 在同一个目录里工作会互相干扰：一方切换分支或提交，另一方的文件和验证结果随之改变（M1-5 实测中发生过）。所以每个 Agent 用自己的 `git worktree`：同一个仓库、共享提交历史，但各有一个工作目录。

| 目录 | 使用者 |
| --- | --- |
| `D:\06_Projects\ai-job-search-cn` | Claude Code（执行：功能开发） |
| `D:\06_Projects\ai-job-search-cn-codex` | Codex（实测、验证） |
| `D:\06_Projects\ai-job-search-cn-plan` | 规划 |

```powershell
git worktree list                                                    # 查看所有工作目录
git worktree add -b <新分支> ../ai-job-search-cn-<名字> origin/master  # 新建
git worktree remove ../ai-job-search-cn-<名字>                       # 删除（目录里不能有未提交的改动）
```

- 一个分支同一时间只能在一个目录里签出。要查看别人正在用的分支，用 `git switch --detach origin/<分支>`。
- 各目录的 `data/`、`logs/` 是分开的（都被 git 忽略）。要用同一份数据，设置环境变量 `JOBSEARCH_CN_DATA_DIR` 或加 `--data-dir`。
- conda 环境 `ai-job-search-cn` 各目录共用。
