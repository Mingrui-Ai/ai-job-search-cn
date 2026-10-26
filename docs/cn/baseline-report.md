# Day 0 基线报告

> 记录日期：2026-10-26　｜　执行环境：Windows 11 家庭中文版 + Git Bash / PowerShell
> 结论：上游 Python 测试在 Windows 上全部通过；4 个丹麦门户 CLI 的 TypeScript 类型检查失败，原因已定位为 **Bun 1.4.4 的依赖提升行为变化**，与 Windows 和本项目改动无关。

## 1. 仓库与基线版本

| 项目 | 值 |
| --- | --- |
| 私有仓库（origin） | https://github.com/Mingrui-Ai/ai-job-search-cn （PRIVATE，默认分支 `master`） |
| 上游（upstream） | https://github.com/MadsLorentzen/ai-job-search （MIT 许可） |
| 基线提交 | 上游 `master` @ `e16acee`（= 发布版 `v1.7.3` 之后 50 个提交） |
| 本地路径 | `D:\06_Projects\ai-job-search-cn` |

额外的安全设置（均为本地 git/gh 配置，不在仓库文件中）：

- `upstream` 的 push 地址设为 `no_push_to_upstream`，任何 `git push upstream` 都会直接失败。
- `gh repo set-default Mingrui-Ai/ai-job-search-cn`：存在 `upstream` remote 时，`gh issue/pr create` 可能默认发到上游**公开**仓库（上游 SETUP.md §2，#389），固定默认仓库后杜绝此风险。

## 2. 工具链

| 工具 | 版本 | 说明 |
| --- | --- | --- |
| Git | 2.45.1.windows.1 | 系统级 `core.autocrlf=true` |
| GitHub CLI | 2.92.0 | 账号 `Mingrui-Ai`，scopes 含 `repo`、`workflow` |
| Python | 3.12.15 | conda 环境 `ai-job-search-cn`（Anaconda base 为 3.9.13，低于要求的 3.10） |
| Python 依赖 | pyyaml 6.0.3、openpyxl 3.1.5 | 与上游 CI 一致 |
| Bun | 1.4.4 | `winget install Oven-sh.Bun` |
| Node.js / npm | 24.14.0 / 11.9.0 | 非必需 |
| Codex CLI | 0.164.0 | |
| Claude Code | 2.1.310 | |
| LaTeX | 未安装 | 按计划第二周做简历导出时再装 |

## 3. 检查结果（改动前的纯上游基线）

| 命令 | 结果 |
| --- | --- |
| `python tools/install_portal_clis.py --dry-run` / 实装 | 6/6 个门户 CLI 依赖安装成功 |
| `python tools/lint_skills.py` | OK（9 skills、12 commands、settings.json） |
| `python tools/security_guards.py` | OK |
| `python tools/check_framework_version.py` | OK |
| `python -m unittest discover -s tests -t . -v` | **836 个测试通过，9 个跳过，0 失败**（约 90 秒） |
| 各 CLI `bun test` | 6/6 通过，共 495 个测试 |
| 各 CLI `bun run typecheck` | 2/6 通过：`freehire-search`、`linkedin-search` 通过；`jobbank`、`jobdanmark`、`jobindex`、`jobnet` 共 137 个 TS 错误（见 §4.1） |
| GitHub Actions 首次运行 | [run 40314476175](https://github.com/Mingrui-Ai/ai-job-search-cn/actions/runs/40314476175)：除上述 4 个 CLI typecheck job 外全部通过（含 Python 3.10–3.14、Windows、LaTeX 两条编译线） |

9 个跳过的测试都在预期之内：

- 7 个是"仅限上游模板"的占位符守卫（`test_placeholder_integrity` 5 个、`test_setup_command` 2 个），fork 会通过 `/setup` 个性化这些文件，所以跳过。
- 2 个需要创建文件系统符号链接（`test_reset_documents`），Windows 需开发者模式或管理员权限。

本次框架改动之后再次运行：lint、security_guards 均 OK，单元测试 842 个（新增 6 个 `tests/test_cn_package.py`）全部通过。

原始日志保存在本地 `logs/baseline/`（已被 `.gitignore` 忽略，不入库）。

## 4. 已知问题

### 4.1 Bun 1.4.4 导致 4 个门户 CLI 类型检查失败（上游问题）

**现象**：`bun run typecheck` 报 `Property 'status' does not exist on type 'Response'`、`'URL' refers to a value, but is being used as a type` 等，均为 fetch 相关全局类型缺失。

**根因**（已复现确认）：

1. 依赖链 `@bunli/core` → `@opentui/core@0.1.97` → `jimp@1.6.0` → `image-q@4.0.0`，其中 `image-q` 精确锁定 `@types/node@16.9.1`。
2. Bun 1.4.4 把 `@types/node@16.9.1` 提升到 `node_modules` 顶层，`bun-types` 随之读到缺少 fetch 类型的旧版 Node 类型。
3. 上游 `.gitignore` 忽略 `bun.lock`，CI 的 `setup-bun` 也不锁 Bun 版本，所以依赖解析随 Bun 版本浮动。

**证据**：同一提交 `e16acee`，上游 10-21 的 CI 用 Bun 1.4.3 全绿（[run 39549824836](https://github.com/MadsLorentzen/ai-job-search/actions/runs/39549824836)）；本仓库 10-26 用 Bun 1.4.4（10-22 发布）失败。在临时目录用 `bun@1.4.3` 重装 `jobbank-search`，顶层 `@types/node` 变为 26.6.5，typecheck 0 错误。

**影响**：只影响丹麦门户 CLI 的类型检查，运行时测试全部通过；不影响 CN 开发。

**处理选项**（尚未执行，待决定）：

- 等上游修复后合并（最省事，CI 暂时保持这 4 个红灯）；
- 向上游报告（会以你的 GitHub 身份公开发 issue，需要你确认）；
- 在本 fork 的 CI 中临时把 `oven-sh/setup-bun` 固定为 `bun-version: 1.4.3`（会改动上游 workflow 文件）。

### 4.2 Windows 兼容性记录

| 问题 | 影响 | 处理 |
| --- | --- | --- |
| `python3` 指向微软商店占位程序（执行后退出码 49、无输出） | 上游工作流说明统一写 `python3 tools/...`，并附 Windows 提示改用 `python` | 本机一律用 `python`（conda 环境）。也可在"设置 → 应用 → 应用执行别名"中关闭 `python3.exe` 别名 |
| 默认 `python` 是 Anaconda base 3.9.13 | 低于 3.10，上游部分工具无法运行 | 先 `conda activate ai-job-search-cn`；Claude Code / Codex 继承启动它们的终端的 PATH，所以要从已激活的终端启动 |
| winget 安装 Bun 后只有新终端能找到 `bun` | 旧终端报 `bun: command not found` | 重开终端 |
| 中文 Windows 控制台默认 cp936（GBK） | Python 打印中文到管道时乱码，cp1252 环境下直接 `UnicodeEncodeError` | CN CLI 强制 UTF-8 输出（`jobsearch_cn/__main__.py`，由测试守护）；也可在用户环境变量中设置 `PYTHONUTF8=1` |
| 创建符号链接需要特权 | 2 个测试跳过 | 预期行为，无需处理 |
| `core.autocrlf=true` | 未观察到问题 | 不加 `.gitattributes`，避免全仓库换行重写 |

### 4.3 私有仓库的 GitHub Actions 额度

每次推送 `master` 或每个 PR 都会触发完整 CI：17 个 job，计费约 26 分钟（Linux 20 分钟 + Windows 3 分钟 × 2 倍）。GitHub Free 的私有仓库每月 2000 分钟，约够 75 次运行。`upstream-watch.yml` 每周一自动运行一次，在本仓库维护一个名为 "Upstream sync watch" 的 issue，报告上游新提交。

## 5. 复现步骤

```powershell
conda activate ai-job-search-cn
cd D:\06_Projects\ai-job-search-cn
python tools\install_portal_clis.py --dry-run
python tools\install_portal_clis.py
python tools\lint_skills.py
python tools\security_guards.py
python tools\check_framework_version.py
python -m unittest discover -s tests -t . -v
Push-Location .agents\skills\linkedin-search\cli; bun run typecheck; bun test; Pop-Location
```
