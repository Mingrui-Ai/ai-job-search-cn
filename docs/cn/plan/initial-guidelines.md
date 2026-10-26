# AI Job Search CN：从零启动到可用版本的完整开发方案

基于 [MadsLorentzen/ai-job-search](https://github.com/MadsLorentzen/ai-job-search?utm_source=chatgpt.com) 的中国互联网求职 Agent 二次开发计划

我建议你把这个项目正式定位为：

AI Job Search CN —— 面向中国互联网招聘市场的多 Agent 智能求职系统。

目标不是简单制作一个招聘网站爬虫，而是让 AI 帮助求职者完成从岗位发现、职位分析、简历定制、招聘沟通到面试准备、求职进度管理的一整套流程。

这份方案以你当前使用的 Windows + Codex CLI + GitHub 为主要开发环境，优先面向 AI Agent、AI 应用开发、Java 后端等互联网技术岗位。

推荐项目目标

## 4 周形成完整 MVP

第 1 周

项目跑通 + 中文职位解析

第 2 周

人岗匹配 + 简历生成

第 3～4 周

多 Agent + 管理界面 + 测试

这是开发节奏建议，不是完成时间保证。按每天约 2～3 小时的有效开发时间规划，可根据实际进度调整。

## 一、项目启动前，先确定开发策略

### 1. 不建议推倒原仓库重写

我已经检查了原仓库当前的核心结构。它并不是单纯的一组爬虫，而是以 Claude Code 工作流为中心，结合 Skills、TypeScript CLI、Python 工具和简历模板形成的 Agent 项目。

其中有不少值得直接保留的工程能力：

| 原仓库已有能力                   | 二次开发处理方式           |
| -------------------------------- | -------------------------- |
| `AGENTS.md` 跨 Agent 使用说明    | 保留，增加中国本地化规则   |
| `/setup` 求职档案建立            | 改为中国高校求职者档案     |
| `/scrape` 岗位收集与去重         | 复用，增加国内数据接入     |
| `/rank` 岗位匹配排序             | 重新设计实习与校招评分     |
| `/apply` 简历生成、双 Agent 审核 | 保留核心逻辑，增加中文简历 |
| `/interview` 面试准备            | 增加国内技术面试与项目拷打 |
| `tools/posting_guard.py`         | 保留，强化外部招聘数据安全 |
| `.github/workflows/ci.yml`       | 保留，扩展中文化测试       |

仓库还提供了 `/add-portal` 命令，可以通过标准化 CLI 扩展招聘信息来源。

因此，最省时间的技术路线是：

在原仓库上增量改造，先运行现有代码，再新增中国本地化模块，最后将改造成熟的能力整合进原有工作流。

### 2. 明确 MVP 范围

第一版不要追求全自动化，先让以下五项能力真正可用。

| 第一版功能                     | 是否必须 |
| ------------------------------ | -------- |
| 粘贴中文 JD 并解析成结构化岗位 | 必须     |
| 建立个人技能及项目档案         | 必须     |
| AI 进行岗位匹配并解释评分      | 必须     |
| 根据 JD 生成中文定制简历       | 必须     |
| 记录岗位、投递与面试状态       | 必须     |
| BOSS 直聘自动抓取              | 暂不做   |
| 自动登录招聘网站、批量投递     | 暂不做   |
| 微信小程序、多用户 SaaS        | 暂不做   |

这样安排还有一个重要原因：BOSS 直聘和实习僧的用户协议对未经许可的第三方工具访问、爬虫及批量检索存在明确限制。因此，第一版使用用户主动提供的 JD、授权接口和允许访问的企业官方招聘信息，更容易做出稳定、合规、能公开展示的产品。

![img](https://www.google.com/s2/favicons?domain=https://www.zhipin.com&sz=32)

zhipin.com

+1



## 二、第 0 天：把项目部署到你自己的电脑上

这一阶段的目标只有一个：建立一个可安全修改的本地仓库，确保原项目的基础测试通过。

### 第一步：准备开发环境

根据原仓库当前的 README，主要依赖如下。

| 工具         | 用途                         | 建议           |
| ------------ | ---------------------------- | -------------- |
| Git          | 版本管理、合并原项目更新     | 必需           |
| GitHub CLI   | 创建、管理 GitHub 仓库       | 推荐           |
| Python 3.10+ | 原项目 Python 工具及测试     | 必需           |
| Bun          | 运行 TypeScript 招聘网站 CLI | 必需           |
| Codex CLI    | 主要 Agent 开发工具          | 使用你现有环境 |
| VS Code      | 查看代码、调试               | 推荐           |
| MiKTeX       | 生成 PDF 简历                | 第二周再安装   |
| SQLite       | 本地岗位与投递数据存储       | 第二阶段使用   |

打开 Windows PowerShell，先检查环境。

```
git --version
gh --version
python --version
bun --version
codex --version
```

缺少 Git、GitHub CLI、Bun 时，可使用 Windows 包管理器：

```
winget install Git.Git
winget install GitHub.cli
winget install Oven-sh.Bun
```

Python 缺失则单独安装官方 Python 3.10 或更新版本。

安装完成后重新打开终端，确认以上版本命令都能正常执行。

### 第二步：克隆原仓库，而不是直接 Fork

这里有个非常重要的细节。

原项目的 `CLAUDE.md` 会保存求职者的个人信息，而且属于 Git 跟踪文件。GitHub 公共仓库的 Fork 仍然是公开仓库，不能直接改为私有 Fork。

![img](https://www.google.com/s2/favicons?domain=https://docs.github.com&sz=32)

GitHub Docs



因此，我建议先创建一个独立的私有仓库。

在 PowerShell 中执行：

```
# 进入你的项目目录
cd D:\06_projects

# 克隆原仓库
git clone https://github.com/MadsLorentzen/ai-job-search.git ai-job-search-cn

# 进入项目
cd ai-job-search-cn

# 将原仓库保留为 upstream
git remote rename origin upstream
```

然后使用 GitHub CLI 登录：

```
gh auth login
```

创建私人项目，并上传原始代码：

```
gh repo create ai-job-search-cn --private --source=. --remote=origin --push
```

检查结果：

```
git remote -v
git status
```

正常情况下：

- `origin` 指向你新创建的私有仓库。
- `upstream` 指向原作者仓库。
- 本地工作区是干净的。

这个结构可以让你在开发自己的功能时，继续获取原项目的更新。

原作者仓库（upstream）

MadsLorentzen/ai-job-search

本地开发仓库

D:\06_projects\ai-job-search-cn

个人私有仓库（origin）

ai-job-search-cn

### 第三步：安装原项目依赖，验证项目健康状态

在项目根目录执行：

```
# 查看安装操作
python tools\install_portal_clis.py --dry-run

# 安装原项目中各招聘网站 CLI 的依赖
python tools\install_portal_clis.py

# 安装测试所需的 Python 依赖
python -m pip install pyyaml openpyxl==3.1.5
```

然后运行：

```
# Skill 和配置检查
python tools\lint_skills.py

# 安全配置检查
python tools\security_guards.py

# Python 测试
python -m unittest discover -s tests -t . -v
```

如果这些检查通过，说明原项目的基础结构在你的环境中具备可运行条件。

再检查一个 TypeScript CLI：

```
Push-Location .agents\skills\linkedin-search\cli

bun run typecheck

Pop-Location
```

此时不需要真的请求 LinkedIn 招聘接口，更不需要运行批量抓取。

第 0 天的验收标准： 仓库已建立、依赖安装完成、主要测试通过，并把任何 Windows 兼容性问题记录下来。暂不做业务修改。

## 三、总体技术架构设计

原项目是以 Agent 的 Markdown 工作流为中心的。我建议保留这种组织方式，但逐步加入更明确的业务模块，防止所有功能都依赖大模型临时解释文本。

### 推荐的目标架构

交互层

初期 Codex CLI / 后期 Web UI

Agent 工作流编排层

职位分析 Agent

匹配评分 Agent

简历优化 Agent

面试辅导 Agent

业务工具层

岗位导入与解析

结构化评分器

简历导出工具

求职进度管理

数据层

SQLite / 本地文件

外部接口层

模型 API / 授权数据源

### 推荐技术栈

| 模块         | 技术选择                   | 原因                     |
| ------------ | -------------------------- | ------------------------ |
| Agent 开发   | Codex + 现有 Skills        | 最大程度复用原项目       |
| 招聘数据适配 | TypeScript + Bun           | 与原项目保持一致         |
| 业务数据处理 | Python                     | 已经有现成 Python 工具   |
| 大模型调用   | 可配置模型 Provider        | 便于切换模型和比较成本   |
| 数据库       | SQLite                     | 单机开发，无需单独部署   |
| 简历导出     | 原有 LaTeX，后续加入 DOCX  | 复用现有能力             |
| 前端         | React + TypeScript         | 后期形成可展示的求职看板 |
| 测试         | Python unittest + Bun test | 沿用原仓库测试体系       |

关键建议：第一阶段不要同时重写 Agent 框架、数据接入、后端、前端。 否则很容易出现每个模块都完成一点，却没有一条完整工作流能真正使用的情况。

## 四、第一周：必须完成的开发任务

我建议将第一周聚焦在一条最短业务闭环：

中文 JD → 结构化解析 → 岗位保存 → 在 Codex 中查询

这一周不需要训练模型，也不需要接入 BOSS 直聘。

### 任务 1：先制定中国招聘岗位的数据标准

以后无论数据来自手动粘贴、授权 API 还是企业官网，都应该转成同一个 Job Schema。

例如：

```
{
  "id": "job_example_001",
  "source": "manual",
  "source_url": null,
  "title": "AI Agent开发实习生",
  "company": "示例科技公司",
  "location": "广州",
  "employment_type": "internship",
  "salary": {
    "min": 200,
    "max": 300,
    "unit": "CNY/day"
  },
  "requirements": {
    "graduation_years": null,
    "days_per_week": 4,
    "minimum_months": 3,
    "skills": [
      "Python",
      "LangChain",
      "RAG"
    ]
  },
  "published_at": null,
  "description": "原始JD内容",
  "application_status": "saved"
}
```

这只是建议的标准化模型。实际工程中，应该另设解析置信度、字段证据和原始数据来源，不能将模型猜测的毕业年份、薪资、公司等内容当作已确认事实。

还需要正确处理中文招聘中的特殊情况，比如 `150-250元/天`、`10-15K·14薪`、`2027届优先`、`每周4天`、`可转正` 等。

### 任务 2：开发 JD 导入 Skill

建议新增：

```
.agents/skills/cn-jd-import/
├── SKILL.md
└── cli/
    ├── package.json
    ├── src/
    │   ├── cli.ts
    │   ├── parser.ts
    │   └── schema.ts
    └── tests/
```

第一版支持三个操作：

| 操作       | 作用                               |
| ---------- | ---------------------------------- |
| `import`   | 从用户指定的 TXT 文件导入 JD       |
| `parse`    | 提取岗位、薪资、技术要求、实习条件 |
| `validate` | 检查字段、原文依据和数据完整性     |

这里的 `cn-jd-import` 是本地导入工具，不需要伪装成招聘网站 CLI。等到岗位都可以存储后，再通过独立适配器对接原项目的 `/scrape`。

### 任务 3：岗位数据持久化

第一周先使用 JSON 文件保存开发样例即可，随后切换 SQLite。

建议至少包含以下实体：

- `candidate_profiles`：求职者档案
- `jobs`：标准化岗位
- `job_sources`：数据来源与导入记录
- `job_matches`：匹配结果与评分版本
- `applications`：投递、面试、Offer 状态

对于同一岗位反复导入的情况，应该根据可信的外部岗位 ID、来源 URL 或规范化内容指纹进行去重，避免一家公司同一个岗位重复出现多次。

### 第一周的逐日安排

第一周开发检查表

0/7 完成

Day 1 · 环境与代码审计

克隆仓库、检查依赖、记录现有工作流

Day 2 · 制定 Job Schema

字段定义、JSON Schema、中文薪资与实习条件规则

Day 3 · 实现 JD 导入

TXT 输入、字段解析、结构化输出

Day 4 · 数据保存与去重

本地持久化、唯一标识、异常处理

Day 5 · Codex Skill 集成

通过自然语言触发 JD 导入与查询

Day 6 · 测试与修复

解析测试、缺失字段、乱码、恶意文本测试

Day 7 · 版本验收

文档整理、演示、提交 v0.1.0

第一周结束时，最重要的验收是：给系统一段中文 JD，它能输出符合 Schema 的 JSON，并保存为一个可再次查询的岗位。

## 五、第二周：建立真正有价值的 AI 求职能力

第二周重点不是招聘网站，而是判断某个岗位是否适合求职者，以及如何提高申请质量。

### 核心一：个人档案系统

原项目的 `/setup` 能建立候选人档案。建议将中国高校求职所需字段补充进去：

| 信息类型 | 示例字段                          |
| -------- | --------------------------------- |
| 教育背景 | 学校、专业、学历、预计毕业年份    |
| 技术能力 | Python、Java、MySQL、Agent 框架等 |
| 项目经验 | 项目名称、承担任务、真实技术实现  |
| 实习条件 | 可到岗时间、每周天数、持续月份    |
| 求职目标 | Agent 开发、AI 应用、后端等       |
| 地理偏好 | 城市、远程/线下、通勤约束         |

个人档案要与岗位信息分开存储。正式使用时，还应避免将真实身份证号、手机号、家庭住址等信息自动传入不必要的外部模型请求。

### 核心二：混合式岗位匹配

不建议只把 JD 和简历一起丢给大模型，让它直接给出一个 85 分。

更合理的方案是：

硬性规则过滤 + 技术关键词匹配 + LLM 语义评价 + 可解释评分。

例如，岗位要求每周 5 天，而用户只能到岗 3 天，应该直接标记为条件冲突，而不是通过技术技能高分把结果拉回来。

匹配结果还应明确给出：

- 满足的岗位要求及其简历证据
- 缺少的技能及对应 JD 原文
- 需要用户确认的条件
- 可执行的简历改进建议
- 评分所使用的规则与模型版本

### 核心三：中文简历生成与审核

你可以直接复用原项目的 Drafter–Reviewer 思路。

Resume Drafter Agent

根据 JD 调整已有项目经历的表达方式

Resume Reviewer Agent

核验真实性、关键词、可读性和格式

人工确认与 PDF/DOCX 输出

用户确认最终内容后再生成文件

第二周验收目标：对 10 份测试岗位能够给出稳定、可解释的匹配结果，并针对至少 3 个岗位生成不同的中文简历版本。

## 六、第三周：接入中国招聘信息与多 Agent 协作

到了第三周，再考虑实际的数据来源和完整 Agent 编排。

### 1. 数据来源优先级

建议采用：

用户主动导入 → 授权接口 → 允许访问的企业招聘官网 → 其他通过合规审核的来源。

对于 BOSS 直聘、实习僧等平台，可以先支持用户主动复制职位描述，或者由用户导入其有权使用的文件。

在后续增加自动化数据源前，需要单独检查平台协议、`robots.txt`、接口授权范围以及个人信息处理方式，不能因为技术上可抓取，就将其直接注册为可用 Adapter。

### 2. 多 Agent 不宜过早复杂化

起步时，我推荐四个核心 Agent：

| Agent           | 职责                 | 输出            |
| --------------- | -------------------- | --------------- |
| Job Analyst     | 识别并整理职位信息   | 标准化 Job JSON |
| Match Evaluator | 匹配个人技能与岗位   | 评分和证据      |
| Resume Writer   | 生成岗位专属简历     | 简历草稿        |
| Resume Reviewer | 检查真实性和表达问题 | 审核报告        |

面试辅导、招聘聊天助手可以作为后续独立 Skill 接入。

每个 Agent 都应该使用明确定义的输入输出结构，而不是只用自由文本互相传递。

同时记录每一步的 Token 消耗、耗时、失败原因和重试次数。

第三周验收：至少有一条岗位导入、匹配评价、简历生成、审核的可追溯完整工作流。

## 七、第四周：做成可以展示的产品

前三周先确保核心能力正确，第四周再做界面。

我建议前端保留四个最主要页面。

![AI Job Search Dashboard by Pickolab Studio on Dribbble](https://images.openai.com/static-rsc-4/lT2zOKOL00iOiT3VD1tnMZtadJJN4hd9Yn2mQEa2XO7l1pflYHFM181qV6hWu9tqEm7deD2OaAqePCicTYFoLFNTswJYfzm47CFdKmPVdTFC8iQuwiaEmM9x7Hd3gp7svGb7J5bvim7l8zRb_Hpi9TRHdLbU-SvQZ3CGOwqaOp0?purpose=inline)

岗位中心

岗位导入、筛选、收藏、匹配排序

![HireAI – AI Recruitment Platform - Case Study | GroveTech | GroveTech Solutions](https://images.openai.com/static-rsc-4/RHgoAV875mL7CzlvRw8qvl-I0FLQmAO5U5rtNzhFRSMn7mwne7k1OPTX5B5E21K6vVzDVeWD8GHgvdOBl0UcZa6FJuYLFWstCv-clYJGIOyhDqChKMcAG7-VQZ0rfw-VXqb6U_sYK-1t9eKcfYFJ_eX-vMRDRdr6FCKXxpMHz30?purpose=inline)

AI 匹配分析

技能匹配、条件冲突、改进建议

![FlowCV: Details, Pricing, Features, & Integration in 2026](https://images.openai.com/static-rsc-4/2NRImDMwHO6JgUWoiMHZMTwlLkBXo7mO195lunrLklC2qq8KLL2PMdQ1YmNmcvurL3TX8CqKeEjCjBkrGPv9tJcqdZ-Uwli7IrKhKxGric5eHrkJX100WLyOZ6_fKPKlq626LSrGcMQR9JoWV03p9O4SCQ8AcIMThkvDI7R9UX8?purpose=inline)

智能简历

简历管理、JD 定制、导出文件

![PopResume - AI Resume Builder | Create Professional Resumes in Minutes](https://images.openai.com/static-rsc-4/yk9iv7uUwBTJdB-rEnUw-_bzTcQ18w9j_u7HkLBiqIqCyZ31IZfyJo7_nRmJdfQAq2YelEQYwCmCui_xN1wayOFd6TEO6f-7BCe7DLNLv1YkW0IdmZD6xC4gisX-68uCo0Ht2kLZBjp36ThDLNbK5qhqrGYV_qhC3m2sykAo56M?purpose=inline)

求职看板

已收藏、已投递、面试中、Offer

以上为同类界面风格参考，不是原仓库的实际截图。

如果你到第四周还没有把后端工作流跑通，宁可暂时不做完整 Web 前端，也不要牺牲核心功能的正确性。

## 八、项目开发时需要坚持的工程规范

我建议从第一个提交开始，就把以下事项当成正式项目要求：

| 规范         | 实际要求                               |
| ------------ | -------------------------------------- |
| 数据真实性   | 不得凭空生成职位、薪资、项目经历       |
| 人工确认     | 不自动投递、不自动发送招聘消息         |
| 数据安全     | 简历和个人联系方式默认本地保存         |
| 外部数据安全 | JD 视为不可信输入，不能当作 Agent 指令 |
| 可测试性     | 中文解析、匹配规则、数据去重都有测试   |
| 稳定性       | 单个平台访问失败不能使全流程崩溃       |
| 成本控制     | 缓存结果，避免对同一个 JD 重复调用模型 |
| 代码维护     | 保留上游更新渠道，定期检查变更         |

尤其注意：原仓库已经有安全防护机制和 CI，新增工具权限时不要为了省事把 Codex 或 Claude Code 的执行权限全部放开。

如果未来将真实求职者数据上传到服务端或调用外部模型 API，还需要设计告知、授权、数据最小化、删除以及第三方数据处理机制，符合《个人信息保护法》等要求。

![img](https://www.google.com/s2/favicons?domain=https://www.cac.gov.cn&sz=32)

cac.gov.cn



## 九、怎么使用 Codex 正式开工？

这里最关键的是，不要第一条指令就让 Codex：

> 把整个项目改造成中国版，支持所有国内招聘网站，帮我实现全自动投递。

这种一次性范围过大的任务，很容易让 Agent 大量修改原有文件，造成不可控的回归问题。

建议先新建独立分支：

```
git switch -c feat/cn-foundation

codex
```

然后将下面这份指令发送给 Codex，作为项目的第一个正式开发任务。

Codex 第一阶段开发指令

 复制指令

这段指令限定了开发范围，要求 Codex 先审计原项目，再进行第一步最小实现。

建议首次执行时使用正常的审批模式，重点检查新依赖、权限变更和涉及外部网络请求的操作。

## 十、四周里程碑与最终验收

| 时间    | 建议版本 | 交付结果                                |
| ------- | -------- | --------------------------------------- |
| 第 1 周 | `v0.1.0` | 中文 JD 导入、解析、保存与基础测试      |
| 第 2 周 | `v0.2.0` | 求职档案、人岗匹配、中文简历生成        |
| 第 3 周 | `v0.3.0` | 多 Agent 协作、可追溯流程、合规来源接入 |
| 第 4 周 | `v0.4.0` | 求职看板、完整演示、回归测试与文档      |

最终 MVP 应该能够完成这样一个演示场景：

用户提供一段中国互联网公司的 AI Agent 实习 JD，系统解析职位要求，根据个人项目经历判断匹配度，解释技能差距，生成符合事实的中文简历，交由 Reviewer 检查，并让用户将该岗位加入求职看板。

整个过程应该能够复现，并能展示每次模型调用的成本及结果质量。

这是一个足够完整、适合作为 AI Agent 实习作品集展示的项目。

## 十一、今天真正需要做什么？

虽然上面的路线有四周，但今天只需要完成三件事情：建立私有仓库、跑通现有基础测试、让 Codex 完成第一轮代码审计并写出开发计划。

先不修改招聘网站，不安装复杂的前端框架，也不购买额外的 API 服务。

这样做最大的好处是：你可以先获得一个稳定的项目基线，每一步都有可检查的开发成果。

我建议将第一次正式提交命名为：

```
chore: initialize AI Job Search CN development baseline
```

等基线确认后，再开始 `feat: add Chinese JD import and normalization`。

只要第一条“中文岗位输入 → 结构化输出”的流程成功运行，后面的岗位匹配、简历定制和多 Agent 系统就都有了可靠的开发基础。