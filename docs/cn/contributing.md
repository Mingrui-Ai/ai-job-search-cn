# 为 AI Job Search CN 贡献

CN 功能、测试和文档的目标仓库是 [Mingrui-Ai/ai-job-search-cn](https://github.com/Mingrui-Ai/ai-job-search-cn)，PR 合入 `master`。根目录 [CONTRIBUTING.md](../../CONTRIBUTING.md) 保留上游模板的贡献政策；其中拒绝国别内容和其他运行时适配的规则适用于上游仓库。通用修复若要回馈上游，再按其政策单独处理。

## 1. 选择贡献范围

先读 [AGENTS.md](../../AGENTS.md)、[路线图](roadmap.md)中对应任务和[架构索引](architecture.md)。任务、验收标准与范围决定由[总体规划](master-plan.md)和路线图管理；已有任务按当前分工推进，新增范围先与维护者对齐。

每个 PR 围绕一个具体问题。说明触发条件、当前行为、预期行为，以及改动服务哪个任务编号。修复应从真实命令路径复现；可以用公开虚构输入复现，个人档案、真实岗位材料和会话记录留在本机。

## 2. 开发环境

基础环境是 Git 和 Python 3.10 及以上。从仓库根目录运行下文命令；`python` 代表你选定的解释器，使用 `python3` 的系统相应替换。已有 Conda 环境可以继续使用，项目不要求特定的环境名称或安装目录。

```powershell
python --version
python -m pip install pyyaml openpyxl==3.1.5
python -m jobsearch_cn --help
```

PyYAML 供技能 lint 使用；`openpyxl==3.1.5` 与 [CI](../../.github/workflows/ci.yml) 的 Excel 集成测试依赖一致。基础 CN 命令本身不依赖这两个包。

Windows 全量回归目前使用基础 Python 3.14，与当前 Windows CI 一致。Windows venv 的 PDF 超时回收修复在 [#176](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/176)，Python 3.13 路径兼容及 CI 扩展在 [#177](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/177)；在修复合并前，使用这些环境遇到对应失败时应先对照 PR 的复现说明。

PDF 读取、Typst 和浏览器采集的可选依赖见[快速开始](../../README.md#快速开始)。修改上游门户 CLI 或 LaTeX 模板时，再按 [SETUP.md](../../SETUP.md) 准备 Bun 或 LaTeX。工具输出、中文源码和文档都使用 UTF-8。

## 3. 开发与工作树

先用 `git remote -v` 确认远端。下面以 `origin` 指向 CN 仓库为例；如果从个人 fork 克隆，应把命令里的 `origin` 换成指向 CN 仓库的远端名。PR 发布时显式选择 CN 仓库，不能依赖 GitHub 为 fork 选择的默认上游。

```powershell
git remote -v
git fetch origin
git worktree list
git worktree add -b docs/cn-topic logs/worktrees/cn-topic origin/master
```

在新工作树里修改、检查和提交。功能分支用 `feat/cn-*`，文档用 `docs/cn-*`，维护用 `chore/*`；分支名按实际主题替换。工作树各有工作目录和本地数据，但共享 Git 对象、分支和 stash。

- 每个工作会话使用自己的工作树，保护其他会话未提交的改动。
- 独立留出样例在单独 clone 中准备，待目标 PR 发布后再推送，避免实现者提前看到验证输入；当前分工见[总体规划 §8](master-plan.md#8-协作方式)。
- 公开虚构样例可以放进 `tests/fixtures/`。临时复现使用该工作树的 `logs/` 或显式数据根；共享真实数据只在用户授权后进行。

例如用已有虚构 JD 检查保存与查询，可指定独立目录：

```powershell
python -m jobsearch_cn jd parse tests/fixtures/cn/jd/boss_intern.txt --site boss --save --data-dir logs/dev-smoke
python -m jobsearch_cn jd list --data-dir logs/dev-smoke
```

## 4. 检查与验证

先运行与问题相关的测试，提交前完成仓库要求的全量检查：

```powershell
python tools/lint_skills.py
python tools/security_guards.py
python -m unittest discover -s tests -t . -v
git diff --check
```

定位 CN 回归时可先运行 `python -m unittest discover -s tests -t . -p "test_cn_*.py" -v`，它不替代提交前全量检查。测试修复时保留基线失败、修复后通过的证据，检查需覆盖实际触发路径。

| 修改范围 | 额外核对 |
| --- | --- |
| CN 命令与字段 | 对应 `tests/test_cn_*.py`、命令的 `--help`、JSON 输出、退出码和既有数据兼容性 |
| 共用工作流或薄入口 | [test_cn_agent_entry.py](../../tests/test_cn_agent_entry.py)、实际涉及的运行时；入口存在与运行时实际验收分开记录 |
| 简历生成或文本读取 | [resume-pdf.md](resume-pdf.md) 的工具链与检查；[CN resume PDF](../../.github/workflows/cn-resume-pdf.yml) 的真实渲染。Word/WPS 页面验收另行记录 |
| 上游门户 CLI | 在所改 CLI 目录运行 `bun test` 和 `bun run typecheck`；CI 使用夹具，不自动访问真实招聘平台 |
| Markdown 文档 | 本地链接与锚点、命令示例、UTF-8 和 U+FFFD 替换字符；涉及上游内容时核对保留范围 |

`tools/check_framework_version.py` 按整份框架文件判断版本变化；现有 CI 只在上游模板仓库运行该步骤。CN 对 `AGENTS.md` 的追加段落按 [AGENTS.md](../../AGENTS.md) 保留上游 `framework_version`，不要为了让整文件比较通过而随意升版；改动上游段落时必须说明原因和同步影响。

本地可选工具缺失造成的跳过、CI 条件跳过、人工验收缺口都要如实写出。全量测试或 PDF 渲染通过，不自动完成真实使用、macOS、新用户或 dsh 验收。

## 5. 提交和审核

1. 同步所改能力的共用文档；实现规则、格式和确认步骤只有一个来源，运行时入口引用它。
2. 按[工作记录格式](worklog.md)在 `docs/cn/worklog/` 新建本项记录，写清行为前后、原因、验证、限制与下一步。只更新路线图中自己对应的任务，整体状态与范围调整由规划者维护。
3. 检查 `git status` 和暂存差异。个人数据、Cookie、密钥及本地模块留在被忽略的目录；CN 建档使用 [profile-setup.md](profile-setup.md)，上游 `/setup` 会改被跟踪的模板文件。
4. 请求审核前在自己的分支合入最新 CN `master`，解决冲突并完成检查。提交信息沿用 Conventional Commits，例如 `docs(cn): clarify contribution workflow`。
5. 在已有授权范围内单独执行推送并核对结果。通过 GitHub 或 `gh pr create --repo Mingrui-Ai/ai-job-search-cn --base master` 建 PR，按[模板](../../.github/pull_request_template.md)写明问题、复现和验证，附当前提交及准确的 CI 结果。
6. 实现类 PR 按[现有审核约定](master-plan.md#8-协作方式)请求非作者审核；规划者的文档 PR 和验证者的测试数据 PR 沿用由规划者核对的安排。审核结论绑定 PR 当前提交；作者推送新提交后需重新核对。合并由获得用户授权的规划者或维护者进行，工作会话等待审核，不自行合并。任务调整与争议交规划者统一裁定。

涉及权限时，遵守 [AGENTS.md](../../AGENTS.md) 的工程底线：修改 `tools/security_guards.py`（包括注释）前先取得用户本人同意；确需增加命令授权时，同时更新 `.claude/settings.json` 和对应守卫白名单，让权限变化可见并受审。修改文件使用编辑工具，遵守当前权限确认，不以脚本绕过。现有授权能覆盖的操作按原授权执行。

来源接入按 [collect.md](collect.md) 和 ADR-9 核对；第三方代码和模板保留原许可及来源记录，参见 [THIRD_PARTY.md](../../THIRD_PARTY.md) 与 [habaneraa 模板来源](../../jobsearch_cn/resume_templates/habaneraa/SOURCE.md)。

## 6. 中断与清理

恢复时先检查自己的 `git status`、分支提交和 PR 最新反馈，再读取本项工作记录；依赖其他分支的任务还要核对其当前提交与合并状态。没有上游跟踪分支时，先确认推送目标，再比较本地与远端提交。

工作树共用 stash，临时保存优先使用自己分支的提交。`git clean -x` 和 `git clean -X` 会删除被忽略的真实数据，不用于本项目。清理只针对自己本轮生成的临时产物，先核对真实路径、链接、Git 状态和占用；工作树中的目录联接先单独处理，再按确认的范围移除工作树。

开发工作记录只用于仓库开发任务。日常导入 JD、生成材料或记录投递，按相应求职流程保存产物，无需额外创建开发记录。
