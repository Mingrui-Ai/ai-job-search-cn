# 2026-10-28 · H13：同步上游 12 个提交

## 完成

- 在验证者工作树 `ai-job-search-cn-codex` 从最新 `origin/master`（`79b2f78`）新建 `chore/upstream-sync-1028`，fetch 并合入 `upstream/master`（`83c788d`，2026-10-27）。以下 12 个提交全部保留在合并历史中。
- 唯一文本冲突是 README：中文前缀和上游说明保留，折叠块内完整替换为上游新版 README，包含四个新增 SVG；未手改上游英文正文。
- CN 适配只涉及 `jobsearch_cn/guard.py`、三条中文回归和导入说明；另在 settings/守卫两处同步加入 CN 可执行代码的 Edit 确认规则。上游工具和门户的业务函数保持上游原样。
- `upstream` 的 push URL 仍是 `no_push_to_upstream`，未修改 remote 设置。

## 逐提交影响与处理

| 上游提交 | 影响 | CN 处理方式 |
| --- | --- | --- |
| `eb0fcd7` · README 重设计 | 英文首页改版，新增 hero/letters/route/apply 四个 SVG | 中文顶部逐字保留；上游英文正文完整放入原折叠块，SVG 原样合入；本地图片引用测试通过 |
| `9ca4563` · 可执行文件编辑保护、加载时命令限制 | 新增 tools、.agents、salary_lookup 的 Edit 确认；禁止技能/命令加载时 hooks、动态命令及不安全 Agent 模式 | 接受上游规则；CN 的三条 Bash 授权保留，并在 `.claude/settings.json` 和 `REQUIRED_ASK_RULES` 同步增加 `Edit(jobsearch_cn/**)`，防止已授权模块被静默重写 |
| `bc2c583` · PDF dump 路径约束 | `verify_pdf --dump-text` 只可写 cv/cover_letters 下的 .txt，拒绝符号链接；取消裸 pdftotext 预授权 | 完整接受。AST 对照确认 `_extract_pypdf(path)`、`run_tool(command)` 的签名及函数体完全未变；H11 只调用提取接口、向 stdout 返回文本，不用 dump，不需改 `resume_extract.py` |
| `37e81a6` · specs 的不可信输入边界 | setup、apply 相关方法论、scraper、upskill、邮箱/Notion 等入口增加第三方文本只当数据的说明 | 上游 specs 全部按新版接入；CN 两个薄技能和共用流程保留。本批没有修改上游 AGENTS.md，CN 附加段与原文件保持不变 |
| `67d1b84` · 六门户输出清洗 | CLI 输出去掉隐藏 HTML、控制字符、tag 编码等不可见内容，新增每门户三条回归 | 门户实现和测试原样合入；六门户新增隐藏文本测试合计 18/18 通过，没有访问真实招聘页面 |
| `07a77ac` · 解码不可见字符文本 | posting_guard 新增 `invisible_text`，解码 tag/variation selector 载荷并告警 | 在 CN 侧将解码文字纳入中文句式检查，摘要增加 `invisible_text` 数量/告警；载荷不进入清洗后的 JD 正文、字段或持久化摘录；补中文隐藏指令、无已知句式的隐藏文本、双语去重/正常 emoji 回归 |
| `ae6c5ad` · 隐藏 HTML 的计数及摘录清洗 | 隐藏区内的不可见字符也计数、解码；隐藏块摘录在截断前清洗 | 上游完整接受；CN 复用其 findings，再由上述适配保留新告警。CN 仍使用原有 text 模式，不改变导入来源或引入网页抓取 |
| `d83945f` · Windows 符号链接测试 | 无创建符号链接权限的系统按条件跳过拒绝写入测试 | 上游测试原样合入；不放宽实际 dump 目标检查，不为平台权限修改业务逻辑 |
| `4f2083b` · robots 通配符及 URL 协议 | 用表遍历替换可能指数回溯的正则匹配；仅接受带 host 的 HTTP(S)，curl 首跳和重定向都限制协议 | 工具原样合入；CN 离线核心不新增网络能力；上游 robots 回归纳入全量检查 |
| `2b8803f` · 安装时禁用依赖钩子 | 每次 Bun 安装显式传 `--ignore-scripts`，兼容旧 Bun 的默认依赖钩子行为 | 安装器原样合入；用该安装器在本工作树安装六门户测试依赖，未手动绕过校验或恢复钩子 |
| `0bcfd75` · gitignore/settings/workspaces 加固 | 按 Git 语义读取忽略规则，检查子目录否定项；settings 顶层及 permissions 键白名单；拒绝 workspaces/bunfig.toml | 规则原样接受；CN 根忽略规则与三条授权仍通过，无需放宽白名单；守卫业务函数与上游一致 |
| `83c788d` · 拒绝门户 .npmrc | manifest 同目录的 .npmrc 与 bunfig.toml 同样拒绝，避免 registry/安装行为被重配 | 安装器与安全检查原样接受；六门户 dry-run 与受保护的实际依赖安装均通过 |

## 决策

- 上游文件以上游为准。`tools/security_guards.py` 相对上游只保留既有 CN allow/skill-allow 常量扩展，并增加一条收紧权限的 CN required-ask 常量；未改检查函数或为 CN 绕过新规则。
- `.claude/settings.json` 保留 CN 的 `jd`、`profile`、`match` 三条授权，同时接受上游新增 ask 和删除裸 pdftotext 的修改；没有增加新的 allow 权限。
- `AGENTS.md`、CN 两个薄入口和原有个人数据忽略配置没有丢失；上游 specs 的版本标记跟随上游，不改写成 CN 副本。
- CN 原先只扫描可见清洗文本，且摘要漏计新 `invisible_text`，会把部分隐藏载荷错误地存成 clean。这是上游新增 findings 带来的兼容缺口，已通过 CN 适配修正，而非修改 posting_guard。
- 未运行上游 `/setup`，未使用真实 JD/简历、账号或 Key。依赖、锁文件和验证临时数据均保持在忽略目录，不随 PR 提交。
- Claude B 正在另改 README 的“开发中”说明；本 PR 不提前改那一段。后合并的一方负责基于最新 master 解冲突，并保留中文最新内容及完整上游折叠正文。

## 验证

- 环境：Windows，conda `ai-job-search-cn`，Python 3.12.15；门户定向测试使用 Bun 1.4.4。
- 新 CN 隐藏载荷回归在适配前复现中文指令漏检、新告警漏计；适配后通过。包含中文防注入、JD/CLI 验收、H11、入口、离线边界和 README 图片的定向 73 项：71 通过、2 跳过。
- H11 单独复核 17 项：15 通过、2 跳过；真实子进程提取合成中文 PDF、段落/表格和只读检查通过。两项跳过分别需要本机 Poppler fallback 和 xpdf 可执行程序；无后端、损坏文本、版本检测及桥接行为仍有测试。
- 全量 `python -m unittest discover -s tests -t .`：1134 项，1122 通过、12 跳过，130.877 秒；`lint_skills.py`、`security_guards.py` 均通过。
- 六门户各运行 `bun test tests/hidden-text.test.ts --timeout 30000`，合计 18 项全通过；使用 mock/本地服务数据，不访问招聘平台。安装器 dry-run 与 `--ignore-scripts` 的实际依赖安装均成功。
- AST 对比确认两个 PDF 桥接函数的签名与完整实现未变；README 中文前缀、AGENTS 内容保持，英文折叠正文与上游逐字相同。
- 最终审计通过：本批 52 个无需 CN 合并处理的上游文件与 `upstream/master` 逐字一致；安全守卫所有函数/类的 AST 与上游一致，常量和 settings 的差异仅为既有三条 CN 授权及新增 CN Edit 保护。上游推送仍禁用，无未解决冲突。
- CN 改动的 `git diff --check` 通过。暂存的上游 SVG 原本有三处空白行尾空格（apply.svg/letters.svg 第 28 行、route.svg 第 24 行），`git diff --cached --check` 会报告它们；按上游文件原样保留原则未做格式清理。
- 提交前再次 `git fetch origin`，`origin/master` 仍为 `79b2f78`，没有新增主线改动。

## 遗留

- 本地检查不等于独立审核；CN 适配由规划者复核。GitHub CI 受账号额度限制期间，不宣称远端 CI 已通过。
- 本次同步没有处理 #41 中另行报告的非法经历引用问题，不改执行者评分分支或 #29。

## 下一步

- 再次同步最新 origin/master 后推送本分支、开 H13 PR，PR 描述逐条列出以上 12 个提交的影响和处理；由规划者审核、用户合并。
