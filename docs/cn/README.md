# AI Job Search CN 文档

面向中国互联网招聘市场的多 Agent 求职系统，基于上游 [ai-job-search-dev/ai-job-search](https://github.com/ai-job-search-dev/ai-job-search) 增量开发。MVP 闭环为：**导入中文 JD → 结构化提取 → 个人档案匹配 → 中文简历生成与审核 → 岗位状态保存**。

本项目是本地工具：不托管服务、不提供模型 API，用户使用自己的 Codex 或 Claude Code（自带订阅或 API Key）；工具同时兼容这两个 Agent；个人档案在本地保存。Agent 读取的内容如何发送给模型服务，取决于所选 Agent 和模型配置。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [roadmap.md](roadmap.md) | 路线图：唯一的任务清单和进度表，按里程碑拆分的任务、负责人、验收标准，随每个 PR 更新 |
| [master-plan.md](master-plan.md) | 总体规划：最终目的、设计原则、系统全貌、M1–M8 的目标与完成标准、待决事项、分工 |
| [worklog.md](worklog.md) | 工作记录：每一步做了什么、验证结果、遗留问题。2026-10-28 起每条一个文件，放在 [worklog/](worklog/) |
| [CHANGELOG.md](CHANGELOG.md) | 版本更新记录（CN） |
| [cn-migration-plan.md](cn-migration-plan.md) | 上游审计结论、架构决策（ADR）、目录结构、上游同步流程 |
| [architecture.md](architecture.md) | 当前实现与代码索引：命令组、本地数据、校验职责和可选依赖 |
| [contributing.md](contributing.md) | CN 贡献指南：环境、工作树、隔离复现、检查、PR、审核与恢复 |
| [job-schema.md](job-schema.md) | 岗位记录格式（Job Schema v1）：字段说明、出处规则、与上游字段的对应 |
| [jd-import.md](jd-import.md) | JD 导入工作流（Codex 与 Claude Code 共用）：解析、补全、校验、保存、去重、查询 |
| [collect.md](collect.md) | 北森本机白名单采集、单链接读取、通用收件导入，以及默认关闭的本地个人模块入口 |
| [profile.md](profile.md) | 个人档案格式（Profile v1）：字段、来源规则、与 JD 硬性条件的对照 |
| [profile-setup.md](profile-setup.md) | 建档工作流 cn-setup（Codex 与 Claude Code 共用） |
| [material.md](material.md) | 求职材料格式：简历引用与检查；打招呼语、邮件、内推及跟进正文 followup 的格式、模板、来源绑定和 `material template/validate/render`；跟进共享流程在 applications.md 第 17 节 |
| [review-checklist.md](review-checklist.md) | 中文简历审核清单（A–F，每条有编号）和"起草 + 审核"工作流设计（M3-3） |
| [review-format.md](review-format.md) | 审核结果格式（M3-3）：`review draft` 机器初稿（技能覆盖、标点和空格警告）、`review validate`、`review show` |
| [resume-workflow.md](resume-workflow.md) | 生成简历工作流 cn-resume（三个 Agent 共用，M3-3）：起草材料、生成 PDF 和 Word、独立审核（最多 2 轮）、交给用户 |
| [applications.md](applications.md) | 投递记录：SQLite 数据库、事件和状态表、先预览再写入、投出时归档材料；第 16 节是 Agent 工作流 cn-application，第 17 节为本地跟进草稿，第 19 节为 `application report` 离线看板（三个 Agent 共用） |
| [match.md](match.md) | 匹配：评分工作流 cn-match（三个 Agent 共用）；`match filter` 硬性条件过滤（符合 / 冲突 / 未知 及依据）；可解释评分 `match score / validate / save / show / list` 和匹配记录 |
| [calibration.md](calibration.md) | 投递复盘（M4-3）：只读 `application retrospective`、历史评分质量、记录事实与假设分开、权重试算交接 cn-match |
| [interview.md](interview.md) | 面试准备包（M5-1）：独立 `interview` 五动作、事实引用、原创题库、Markdown 与审核；Codex 的 AGENTS 指引和 Claude Code 的 cn-interview 共用第 2 节，#169 收尾与 #171 薄入口已独立审核合并，整体及真实使用未验收 |
| [screen.md](screen.md) | 批量初筛 `jd screen`（M6-4）：收件夹批次的格式（给采集程序）、去重、按规则评分、短名单的输出和 Agent 工作流 |
| [jd-parse.md](jd-parse.md) | `jd parse`：用法、编码处理、各字段能识别的写法、补全流程、防注入检查 |
| [baseline-report.md](baseline-report.md) | Day 0 环境、测试基线、已知问题与 Windows 兼容性记录 |
| [oss-privacy-review.md](oss-privacy-review.md) | 开源前隐私审查（2026-10-28）：公开范围、各类扫描结果和处理结论、转为公开前的操作 |
| [resume-pdf.md](resume-pdf.md) | 生成简历：安装 Typst（便携版）、字体、`resume sample`、压成一页和检查；`resume build` 从材料生成 PDF 和 Word 版 |
| [m2-5-round2-checklist.md](m2-5-round2-checklist.md) | M2-5 第二轮的操作清单：用 cn-setup 补档案的哪几项（薪资分档、可以接受的城市、去外地面试），以及重新导入、重新评分、调权重、出报告的顺序和命令 |
| [m3-5-checklist.md](m3-5-checklist.md) | M3-5 真实验收操作清单：备份、经理选择三个岗位、简历与沟通草稿、独立审核、Word/WPS 和 PDF 实看、真实投递与记录 |
| [m3-0-resume-prototypes.md](m3-0-resume-prototypes.md) | M3-0 简历生成方式的原型对比（2026-10-30）：三种同时出 Word 和 PDF 的做法、开源简历模板的调研和许可、推荐方案和 M3-2 的检查清单 |
| [plan/kickoff-guide-v0.1.md](plan/kickoff-guide-v0.1.md) | 原始文件《AI_Job_Search_CN_项目启动指导_v0.1.md》（存档） |
| [plan/initial-guidelines.md](plan/initial-guidelines.md) | 原始文件《初步guidelines.md》（存档） |

`plan/` 下的两份原始计划原样存档、不再修改。之后的计划分两层：目的、里程碑和待决事项写在 `master-plan.md`，任务和进度写在 `roadmap.md`；架构决策写在 `cn-migration-plan.md`。

## 开发环境（Windows）

Python、开发检查依赖与当前 Windows 环境限制统一见[贡献指南 §2](contributing.md#2-开发环境)。基础 CLI 和按需功能依赖见[快速开始](../../README.md#快速开始)。在选定 Python 环境的终端中，从自己的仓库工作目录启动 Agent。

## 常用命令

提交前检查与隔离复现见[贡献指南](contributing.md#4-检查与验证)。以下是 CN 能力的命令入口，具体操作按上面的共用流程执行。

```powershell
# CN CLI
python -m jobsearch_cn --version
python -m jobsearch_cn jd parse jd.txt --site boss   # 从 JD 文本抽取岗位记录（多份用一行 === 分隔）
python -m jobsearch_cn jd validate job.json          # 按 job-schema.md 校验一条岗位记录
python -m jobsearch_cn jd parse jd.txt --save        # 解析并保存到本地岗位库 data/jobs/（自动去重）
python -m jobsearch_cn jd screen data/inbox/boss/<批次>  # 批量初筛：导入一个收件夹批次、按规则评分、给出短名单（docs/cn/screen.md）
python -m jobsearch_cn jd list                       # 列出岗位库；jd show <id>、jd status <id> <状态>
python -m jobsearch_cn match filter <id>             # 用个人档案过滤一个已保存的岗位（硬性条件）
python -m jobsearch_cn match report                  # 把已保存的评分生成可读的报告（HTML）和反馈表（CSV），写到 data/reports/
python -m jobsearch_cn resume sample                 # 用固定的虚构内容生成一页 PDF，验证 Typst 和字体（docs/cn/resume-pdf.md）
python -m jobsearch_cn material validate resume-1.json   # 对照个人档案检查一份简历材料（docs/cn/material.md）
python -m jobsearch_cn material template <id> --kind greeting   # 打招呼语、邮件、内推请求：按方向选模板（material.md 第 7 节）
python -m jobsearch_cn material render greeting-1.json   # 检查通过后输出可以直接复制的文字；只生成，不发送
python -m jobsearch_cn resume build resume-1.json    # 生成一页 PDF 及同内容 Word 版，写到 data/resumes/<岗位id>/
python -m jobsearch_cn application list              # 投递记录；先 --preview 再带 --request-id 写入（docs/cn/applications.md）
python -m jobsearch_cn application report            # 新建离线投递看板 HTML；只写报告文件，不写事件
python -m jobsearch_cn profile validate              # 校验 data/profile/ 下的个人档案；profile show 查看（隐去联系方式）
```

## 仓库与分支约定

CN PR 的目标是 `Mingrui-Ai/ai-job-search-cn` 的 `master`。远端名和 `gh` 默认仓库由每个 clone 的配置决定，先核对再推送；设置和分支示例见[贡献指南 §3](contributing.md#3-开发与工作树)，提交与审核见[§5](contributing.md#5-提交和审核)。

### 多个 Agent 并行工作

每个会话使用自己的工作树，Git 对象和分支共享，工作目录及默认数据根分开。创建命令、独立留出样例与复现数据的处理方式见[贡献指南 §3](contributing.md#3-开发与工作树)。

### 多会话协作

分工与裁定按[总体规划 §8](master-plan.md#8-协作方式)，具体任务按[路线图](roadmap.md)。[贡献指南 §5](contributing.md#5-提交和审核)保留当前提交审核、独立推送、权限修改和公开内容的要求；运行时和本机联络方式由当前任务安排决定。

### 中断后恢复

按[贡献指南 §6](contributing.md#6-中断与清理)核对工作树、提交、PR 反馈与本项工作记录后继续。共享 stash、忽略目录和其他会话的文件都需保留各自边界。
