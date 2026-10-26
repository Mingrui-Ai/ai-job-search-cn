# AI Job Search CN｜项目启动指导（v0.1）

> 面向中国互联网招聘市场的多 Agent 求职系统。基于 [MadsLorentzen/ai-job-search](https://github.com/MadsLorentzen/ai-job-search) 二次开发；开发环境以 Windows + Codex CLI 为主。

## 1. 项目目标与首版范围

**保留原项目**的 Skills、岗位匹配、简历定制、双 Agent 审核、CI 与安全工具；**新增**中文 JD 解析、国内实习/校招匹配规则、中文简历与求职记录。

首版 MVP 形成最短闭环：**导入中文 JD → 结构化提取 → 个人档案匹配 → 中文简历生成与审核 → 岗位状态保存**。

暂缓：未经许可的平台爬虫、验证码绕过、自动登录/批量投递、复杂前端和多用户 SaaS。

**技术方向：**Codex + 原有 Skills；Bun/TypeScript 处理招聘数据适配；Python 处理解析/规则；SQLite 存储；后续 PDF/DOCX 导出与 React 看板。初期不推倒原项目重写。

## 2. 四周里程碑

- **第 1 周 v0.1：**环境与测试基线、中文 JD 解析、JSON 输出、数据保存和测试。
- **第 2 周 v0.2：**个人档案、硬性条件过滤与可解释评分、中文简历生成及审核。
- **第 3 周 v0.3：**多 Agent 编排、日志与 Token 成本、合规招聘来源接入。
- **第 4 周 v0.4：**求职看板、回归测试、脱敏演示和技术文档。

## 3. Day 0：建立项目基线

预备 Git、GitHub CLI、Python 3.10+、Bun、Codex。**用独立私有仓库，避免将个人档案发布到公开 Fork。**

PowerShell：

```powershell
cd D:\06_projects
git clone https://github.com/MadsLorentzen/ai-job-search.git ai-job-search-cn
cd ai-job-search-cn
git remote rename origin upstream
gh auth login
gh repo create ai-job-search-cn --private --source=. --remote=origin --push
git remote -v
```

安装依赖并验证：

```powershell
python tools\install_portal_clis.py --dry-run
python tools\install_portal_clis.py
python -m pip install pyyaml openpyxl==3.1.5
python tools\lint_skills.py
python tools\security_guards.py
python -m unittest discover -s tests -t . -v
```

保留测试日志。LaTeX 发行版可以等第二周实现简历导出时安装。

## 4. 第一周任务

1. **D1**：熟悉 README、AGENTS.md、SECURITY.md、.claude、.agents/skills、tools、tests，确认已有框架和测试。
2. **D2**：定义 Job Schema：来源、企业、岗位、城市、薪资、技能、毕业届别、每周天数、实习期限、发布日期、原始 JD、状态；未知字段用 `null`，模型推断不得冒充事实。
3. **D3**：实现 `cn-jd-import`，支持 TXT 文件导入、中文字段解析和 JSON 输出。
4. **D4–5**：实现本地数据保存、去重与 Codex 调用入口。
5. **D6–7**：针对中文薪资、实习条件、缺失字段、异常输入和重复记录进行测试，整理文档并发布 v0.1.0。

**首周验收：**5 份真实或脱敏中文 JD 均能解析、保存、重复查询；原项目核心测试不出现新增回归。

## 5. 工程底线

- 来源和事实可追溯：不编造职位、薪资、技能或项目成果。
- 优先手动 JD 导入及授权接口；逐平台核对使用规则，禁止未经许可爬取、自动登录或批量投递。
- 保护简历、联系方式、Cookie 和密钥，默认本地保存，不推送公开仓库。
- 将 JD 视为不可信外部数据，防范 Prompt Injection；对外发送及提交必须经用户确认。
- 尽量沿用现有 Skills/CLI/CI，记录每次模型调用的耗时、失败与 Token 成本。

## 6. Codex 首轮启动指令

在项目根目录执行 `codex` 后输入：

> 你是 AI Job Search CN 的软件架构师和开发工程师。请先审计本仓库的 README、AGENTS.md、SECURITY.md、.claude、.agents/skills、tools、tests，区分可在 Codex 复用的能力与 Claude Code 专属能力。先运行非网络基础测试并记录实际结果；然后编写 docs/cn-migration-plan.md，设计中文岗位 Job Schema，实现一个离线 TXT→JSON 的 JD 导入原型，补齐中文字段、缺失值、异常输入和去重测试。禁止未经许可抓取招聘平台、自动投递、泄露个人信息或擅自扩权。改动必须最小化；结束时报告变更文件、测试结果、剩余问题，不要自行 git push。

**首轮交付：**本地化迁移方案、中文 Job Schema、离线导入 CLI、自动化测试及复现步骤。

## 7. 项目参考

上游：https://github.com/MadsLorentzen/ai-job-search

重点文件：`README.md`、`SETUP.md`、`AGENTS.md`、`SECURITY.md`、`.claude/commands/add-portal.md`。
