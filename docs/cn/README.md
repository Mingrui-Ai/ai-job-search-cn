# AI Job Search CN 文档

面向中国互联网招聘市场的多 Agent 求职系统，基于上游 [MadsLorentzen/ai-job-search](https://github.com/MadsLorentzen/ai-job-search) 增量开发。MVP 闭环为：**导入中文 JD → 结构化提取 → 个人档案匹配 → 中文简历生成与审核 → 岗位状态保存**。

本项目是本地工具：不托管服务、不提供模型 API，用户使用自己的 Codex 或 Claude Code（自带订阅或 API Key）；工具同时兼容这两个 Agent；个人档案只存在本地。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [worklog.md](worklog.md) | 工作记录：每一步做了什么、验证结果、遗留问题（按时间倒序） |
| [roadmap.md](roadmap.md) | 完整计划书：目标、阶段与里程碑、每步交付与验收、风险 |
| [cn-migration-plan.md](cn-migration-plan.md) | D1 审计结论、架构决策（ADR）、第一周任务、待决事项、上游同步流程 |
| [job-schema.md](job-schema.md) | 岗位记录格式（Job Schema v1）：字段说明、出处规则、与上游字段的对应 |
| [jd-parse.md](jd-parse.md) | `jd parse`：用法、编码处理、各字段能识别的写法、补全流程、防注入检查 |
| [baseline-report.md](baseline-report.md) | Day 0 环境、测试基线、已知问题与 Windows 兼容性记录 |
| [plan/kickoff-guide-v0.1.md](plan/kickoff-guide-v0.1.md) | 原始文件《AI_Job_Search_CN_项目启动指导_v0.1.md》（存档） |
| [plan/initial-guidelines.md](plan/initial-guidelines.md) | 原始文件《初步guidelines.md》（存档） |

两份计划文档原样存档、不再修改；之后的计划调整写进 `cn-migration-plan.md`。

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
```

## 仓库与分支约定

- `origin` = 私有仓库 `Mingrui-Ai/ai-job-search-cn`；`upstream` = 上游，只拉取（push 已禁用）。
- `gh` 的默认仓库已固定为私有仓库，`gh issue/pr create` 不会误发到上游公开仓库。
- 功能开发在 `feat/cn-*` 分支进行，合并回 `master`。提交信息沿用上游的 Conventional Commits，例如 `feat(cn): add Chinese JD import`。
- 推送 `master` 和开 PR 都会触发 CI。
- 个人数据已被 `.gitignore` 忽略：`data/`（含个人档案 `data/profile/`）、`logs/`、`documents/` 下的个人文件、求职记录。提交前用 `git status` 确认。
- 上游 `/setup` 会把个人信息写进被 git 跟踪的 `CLAUDE.md` 等文件，CN 档案方案落地前先不要用它。
