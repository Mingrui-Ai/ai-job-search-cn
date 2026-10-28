# A1 · DeepSeek Harness 官方资料调研

调研日期：2026-10-28。仅浏览官方发布页、读取官方仓库；没有安装依赖、构建或运行 dsh，没有使用 API Key，也没有交给 dsh 任何 JD 或个人资料。本报告供规划者形成 ADR-10、执行者设计 A2 薄入口；不代表 A1 用户试用或 A3 工作流验收已经通过。

资料固定在官方 tag `dsh-v0.2.2-alpha.2`，commit **`f3803c96974ad4a94195fb97e5c637e9c2a3afe3`**。下列源码与文档链接均指向这个提交，避免滚动 master 改变结论。版本来源：[官方发布页](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.2-alpha.2)。

## 1. 会不会读取 AGENTS.md

**会，标准 web profile 已包含此能力。** `dsh-base` 默认挂载 `agent-instructions`，配置每条指令链 65,536 字节预算。首次请求先加载用户级指令，再加载项目根到当前工作目录的指令；项目根以 `.git` 为标记。项目默认同时读取 `AGENTS.md`、`CLAUDE.md`，再加 `AGENTS.local.md`、`CLAUDE.local.md`；同组内容去除首尾空白后相同才去重，不是二选一。[默认组合](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/bundle/base/cordis.patch.yml#L303-L307)、[指令加载文档](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/context/agent-instructions/README.md#L28-L73)、[候选文件配置](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/context/agent-instructions/src/config.ts)。

对本仓库的建议：沿用根 `AGENTS.md` 指向 CN 工作流的方式；A2 明确 CN 建档指向 `profile-setup.md`，避免根 `CLAUDE.md` 的上游 `/setup` 指引混入。指令加载有预算，且不会把其中引用的文档全部自动展开；官方明确不解释 `@path` 导入。A3 应检查模型是否继续读取所指文档，而不只确认根文件存在。[加载边界](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/context/agent-instructions/README.md#known-limitations-and-deferred-work)。

## 2. 项目级技能放在哪个目录

**`.dsh/skills/<技能名>/SKILL.md` 是官方支持的项目目录。** 同时支持根目录下的 `<技能名>.md`；不会递归发现任意深度的 `SKILL.md`。默认发现顺序是项目 `.dsh/skills`、项目 `.agents/skills`、自定义目录、用户 dsh 目录、用户 agents 目录。技能需有 YAML `name`、`description`；正文按需读取。[目录、格式和优先级](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/skill/skill-filesystem/README.md#L35-L84)、[发现实现](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/skill/skill-filesystem/src/index.ts)。

建议 A2 在 `.dsh/skills/cn-jd-import/`、`cn-setup/`、`cn-match/` 放薄入口，只引用已有 CN 说明；不复制流程，不往 `.agents/skills/` 加本地工作流。默认 dsh 也会发现已有门户技能，这与本仓库 `/scrape` 的门户契约并不冲突。不要假定 Claude 的 `allowed-tools` 会转成 dsh 预授权：官方技能字段和权限机制分别定义，A3 需单独验收权限行为。

## 3. Windows 能否调用 conda 环境的 Python

**官方支持原生 Windows PowerShell 执行；conda 下的本项目命令仍待实测。** 标准组合在 Windows 启用 `pwsh-sandbox` 和 `tool-pwsh`，禁用对应 Bash 工具。PowerShell 可从配置路径、常见安装目录或 PATH 找到，最后可回退 Windows PowerShell 5.1；每次调用为新的非交互进程，带 `-NoProfile`，并设置 UTF-8 输出。[Windows 组合](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/bundle/base/cordis.patch.yml#L248-L287)、[PowerShell 执行文档](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/shell/pwsh-local/README.md#L28-L61)。

子进程继承清理过的父进程环境，PATH 会保留；Windows 环境变量合并不区分大小写。因此，**源码推断**：在已经激活 `ai-job-search-cn` 的终端启动 dsh，可让其 Python 调用沿用该环境。不能依赖前一次工具调用里的 `conda activate` 持续生效，也不能假定 `-NoProfile` 的新 PowerShell 自动加载 conda 函数。[环境继承实现](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/subprocess/subprocess/src/index.ts#L39-L80)、[Windows 环境合并](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/subprocess/subprocess-local/src/spawn.ts#L34-L54)。

A3 先核对 `python -c "import sys; print(sys.executable)"`，再运行 `python -m jobsearch_cn --version` 和合成样例。若 PATH 指向错误解释器，可显式调用用户确认的环境 Python 绝对路径。Windows 沙箱无法建立时会返回 `SANDBOX_UNAVAILABLE`，不能据静态源码保证这台机器的 ACL、conda 路径和写入权限都能通过。[沙箱及失败行为](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/shell/pwsh-sandbox/README.md#L28-L65)。上述命令是后续验收建议，本次未在 dsh 中执行。

## 4. 能不能读 PDF 和 Word

需要区分模型读取正文、浏览器预览和 Office 技能三种能力：

| 能力 | 官方状态 | 对 CN 建档的含义 |
| --- | --- | --- |
| 模型 `read` 工具 | 只读 UTF-8 文本；PDF 支持仍列为 deferred，图片另用 `read_image` | 不应把 PDF/DOCX 路径直接交给 `read` 后就认为正文已读取 |
| 浏览器文档预览 | Office 可转 PDF；预览是浏览器功能，不向模型请求加入内容 | 用户看得到文档，不等于模型拿到正文 |
| Office 技能 | 提供按需加载的 Office 操作/创作说明，依赖选定 Python 库或 Node/LibreOffice Kit CLI | 能指导工具处理文档，但本次没有安装或验证其依赖和中文提取质量 |

出处：[read 限制](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/fs/tool-fs/README.md#L245-L253)、[read 实现](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/fs/tool-fs/src/read.ts)、[Office 转换服务](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/document/office-to-pdf/README.md#L12-L34)、[预览与模型边界](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/client/ui-sidebar-documentpreview/README.md#L130-L137)、[Office 技能](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/skill/skill-office/README.md#L28-L47)。

建议三个 Agent 都沿用 H11 的 `python -m jobsearch_cn profile extract <文件>`，读取其 UTF-8 JSON 的 `text`。DOCX 由本项目标准库提取；PDF 在 Windows conda 环境安装 pypdf，拒绝已知 xpdf 回退；扫描 PDF 不由 H11 做 OCR。这里的实现依据是本项目 [#35](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/35)，不是 dsh 原生能力声明。

## 5. 权限确认怎么配置

标准组合的预设是 `read-only + ask`、`workspace-write + ask`、`danger-full-access + never`，默认工作区写入模式。会话内可用 `/permission` 查看、用 `/permission workspace-write` 切换；`permission.defaultPreset` 设置影响未来会话，不追溯修改已有会话。需要调整组合时使用 dsh profile 的配置/补丁机制，不把 `.claude/settings.json` 当作它的权限配置。[实际预设表](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/bundle/base/cordis.patch.yml#L237-L276)、[预设、命令和设置](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/interaction/permission-presets/README.md#L28-L69)、[profile 配置机制](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/boot/app-boot/README.md#use-this-package)。

`ask` 是把需要审批的请求交给组合中的人或机器答复者；`never` 是拒绝此类请求，不是把审批自动同意。普通已允许动作无需请求审批，所以 `danger-full-access + never` 仍会无沙箱运行许多动作。批准只针对一次请求，没有内建 `allow-always` 授权存储。Auto 模式是额外集成，不能作为“每次问用户”的保证。[审批服务语义](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/interaction/user-approval/README.md#L28-L57)、[单次授权限制](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/interaction/user-approval/README.md#known-limitations-and-deferred-work)、[Auto 定义](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/interaction/permission-presets/README.md#switching-presets)。

**本仓库建议**：A3 使用 `workspace-write + ask`，由用户确认确需升级的动作；CN 工作流仍明确要求对外发送和 push 前取得授权。不要声称预设自动实现 Claude 的逐命令 allow/ask/deny 白名单。官方提供 `tools/pre-execute` 的 allow/deny/ask 和 `ctx.tools.guard` 扩展点；若将来要机械强制特定 shell 子命令审批，需另做策略实现与测试，不属 A2 薄入口范围。[工具策略扩展点](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/core/tools/README.md#enforce-policy-on-calls)。

## 6. 固定用哪个版本

建议 A2/A3 先固定 **`@deepseek-ai/dsh@0.2.2-alpha.2`**，与本报告源码一致。它是官方预发布版，不称为稳定版或已验收版。官方 CLI manifest 要求 **Node.js >= 24.9.0**。后续用户试用时可采用显式版本的 `npx @deepseek-ai/dsh@0.2.2-alpha.2 web`；本次没有执行该命令，也没有验证 npm 安装结果。[官方版本及提交](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.2-alpha.2)、[CLI 名称、版本和 engines](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/apps/cli/package.json)。

后续升级应另记录版本和源码提交，复核上述六项并重跑 A3，不能把 `npx` 不带版本的滚动安装当作本报告结论的复现。

## 交给后续任务的验收点

- A2：三个 `.dsh/skills/cn-*/SKILL.md` 薄入口指向共用说明；不改门户目录，不复制流程或宣称 Claude 权限通用。
- A1 用户试用 / A3：确认 AGENTS 指引和技能可发现；记录实际 Python 路径、中文输出、工作区、权限预设；用合成 JD 与合成 DOCX/PDF 走导入、建档、匹配。模型调用由用户在 dsh 自行配置，Key 不交给本项目工具。
- 验收前仍未确认：本机 Windows 沙箱和 conda 的组合、完整中文文档读取效果、模型是否遵守薄入口及确认步骤。这些是运行验收项，不能用源码阅读替代。
