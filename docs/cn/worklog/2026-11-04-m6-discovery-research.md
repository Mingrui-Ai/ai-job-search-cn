# 2026-11-04 · M6 岗位发现技术调研

## 完成

完成 Windows 已登录浏览器接管、国内招聘采集项目、BOSS 页面读取边界及 M6 最小方案调研。按派活要求保留 **2026-11-04** 文件名，收尾跨至北京时间 11-05；下文 GitHub 提交日期为 UTC，维护状态以本轮查询到的默认分支提交和许可证文件为准。

**推荐：M6-3 首先用 Microsoft 官方 Playwright Extension + Playwright MCP 的 `--extension` 模式，接管用户现有 Chrome 的指定标签页，按关键词和城市低频读 DOM。** 它直接复用登录态，Codex 与 Claude Code 都可通过本地 MCP 使用；无需先自建扩展。独立 Chrome 用户目录 + CDP 是需要稳定脚本接口时的备选。Playwright CRX 适合录制和定位原型，Codex 自带 Chrome 读取是可用时的快捷入口，都不作为唯一依赖。M6-4 独立接收本地文件，继续推进。

本轮仅新增本报告；没有安装浏览器扩展、开启调试端口、登录招聘站、编写或运行采集代码，也没有访问真实数据目录。公开页面探查不等于登录态验收；尚不能承诺 BOSS 在目标账号上可稳定采集。

### 1. Windows 浏览器接管：选择与操作

| 路线 | 能否复用当前普通 Chrome 登录态 | 用户要做什么 | 优点 | 限制与推荐用途 |
| --- | --- | --- | --- | --- |
| Chrome 调试端口 + Playwright `connect_over_cdp` | **不能给未开端口的现有进程补参数**；Chrome 136 起默认数据目录也不接受此方式 | 创建独立数据目录，用专用快捷方式启动；在新窗口人工登录一次，以后复用 | 官方库、跨语言、适合确定性采集；不依赖 Agent 专属浏览器插件 | 专用目录不继承日常 Chrome 登录态；端口权限覆盖整个该浏览器；推荐作脚本化备选 |
| Playwright CRX（ruifigueira） | 可以，通过扩展附着现有标签页 | 在实际登录的 Chrome profile 安装扩展，点击图标选中页面；录制或运行受支持步骤 | 不开 TCP 端口，能直接录制页面动作和定位器 | 商店版主要是 recorder/player；不是给 Python 暴露完整 Playwright 服务；自定义采集、可靠落盘仍需扩展开发。维护较慢 |
| **Microsoft Playwright Extension + MCP** | **可以，官方文档明确支持默认 profile 和既有会话** | 安装官方扩展；本地配置 MCP `--extension`；连接时选择 BOSS 标签页并确认 | 同时适配 Codex / Claude Code；无需迁移 Cookie；能先交付小批发现流程 | 仍需扩展与本地 Node/MCP 宿主；按版本核对能力；连接确认不能假设永远只需一次 |
| Codex / ChatGPT 桌面端 Chrome 扩展 | 可以，必须选 `@Chrome` 对应连接 | 桌面端设置中安装/连接 Chrome 扩展，使用正确 profile，并授权目标站 | 操作步骤少，可直接读取页面和保存结果 | 产品能力及宿主可用性相关；本会话宿主不可用；不是所有 Codex CLI 天生都有的能力 |
| Codex 内置 `@Browser` | 默认**不共享**日常 Chrome profile | 在独立内置浏览器另行人工登录 | 共享可视界面，适合公开页面或已有内置浏览器会话 | 与“接管当前已登录 Chrome”不是同一个连接；不作为该目标首选 |

#### 1.1 CDP：不要按旧教程重启默认 profile

Chrome 官方于 2025-03-17 公告：**从 Chrome 136 起**，`--remote-debugging-port` 和 `--remote-debugging-pipe` 对默认数据目录不再生效，需配合指向非默认目录的 `--user-data-dir`。只加 `--profile-directory="Profile 1"` 仍在默认数据根目录内，不能解决问题；换成 pipe 也不能解决。Chrome for Testing 是官方建议的自动化浏览器，但同样不会自动继承普通 Chrome 的登录态。[Chrome 公告](https://developer.chrome.com/blog/remote-debugging-port)

可行的一次性设置如下，**这是交给实现阶段/用户的操作说明，本轮未执行**：

1. 确认 Chrome 可执行文件的位置。以下用通常的系统安装路径；若不存在，从 Chrome 快捷方式确认真实路径，不猜用户目录。
2. 建立专用的非默认用户目录，普通浏览器继续原样使用。不要复制 Cookie、`Login Data` 或整个日常 profile，也不要关掉 Chrome 加密保护。
3. 用下面的方式打开可见窗口，由用户亲自登录 BOSS。以后从同一快捷方式启动并复用这个目录；若该专用目录已被一个未启用调试的 Chrome 使用，先正常退出**该专用实例**再启动，不强制结束全部 Chrome。

```powershell
$m6Chrome = Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'
$m6Profile = Join-Path $env:LOCALAPPDATA 'AIJobSearchCN\ChromeDiscovery'
if (-not (Test-Path -LiteralPath $m6Chrome)) { throw '请先确认 Chrome 安装路径' }
& $m6Chrome '--remote-debugging-address=127.0.0.1' '--remote-debugging-port=9222' "--user-data-dir=$m6Profile"
```

4. 用 `Get-NetTCPConnection -LocalPort 9222 -State Listen` 核实只监听回环地址；若端口已被其他程序占用，停止并换一个已确认空闲的本地端口。`http://127.0.0.1:9222/json/version` 可用于本地连通性检查，不把返回的调试连接信息写进公开日志。
5. 在核心包之外的采集环境安装固定版本 Playwright。连接入口是 `playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")`，从 `browser.contexts` 找已有上下文，按主机和用户选定标签定位页面。不要通过 `new_context()` 误建一个未登录会话。只 attach 时不必额外下载 Playwright 自带 Chromium。
6. 用完只断开采集连接，保留用户页面；专用 Chrome 退出后调试端口消失。不要绑定 `0.0.0.0`、做端口转发或加 `--remote-allow-origins=*`。端口本身不提供业务级认证，专用 profile 只放求职站。

Playwright 的 CDP 连接只支持 Chromium 系浏览器；官方也明确其功能完整度低于 Playwright 自有协议。因此应在目标 Chrome/Playwright 固定版本上实测页面定位、导航、断开，不承诺所有高级能力都可用。[Playwright Python API](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp)

**新版 Chrome 的额外官方选项**：Chrome 144+ 已提供 `chrome://inspect/#remote-debugging` 下的用户启用入口，Chrome DevTools MCP 可用 `--autoConnect` 请求接入当前实例，连接时出现用户授权。这是另一套受支持的连接流程，不能等同于“Chrome 136 的默认目录限制消失了”，也不能假设启用它就有 `localhost:9222` 可供 Python 连接。它会扩大到当前 profile 的调试访问范围；若评估，关闭默认使用统计和 CrUX 查询（`--no-usage-statistics`、`--no-performance-crux`），只做页面读取。暂不作为 MVP 的额外依赖。[Chrome 官方 auto-connect 指南](https://developer.chrome.com/docs/devtools/agents/use-cases/auto-connect)

#### 1.2 CRX 与官方 Playwright Extension 不要混淆

[Playwright CRX](https://github.com/ruifigueira/playwright-crx/blob/3425f33e1e114e6a2a25333d3543a84fc36bd2f5/README.md) 用 `chrome.debugger` 实现 Playwright 连接传输，页面需要显式 attach。商店扩展能录制及回放动作；界面显示 Python/Java/C#，并不表示它真的在扩展里执行这些语言，player 使用内部步骤格式。库可以用于编写新的 MV3 扩展，但普通 Node/Python 文件系统不能直接当作浏览器扩展文件系统使用；落盘要另外设计下载或本地桥接。故不建议为了第一批岗位先 fork 一个完整 CRX 项目。

首选的 **Microsoft 官方扩展**是另一个产品：[安装与连接说明](https://github.com/microsoft/playwright/blob/1af60d94ac714d4007828bafa02b0f1cbd8646b9/packages/extension/README.md)、[Chrome 商店](https://chromewebstore.google.com/detail/playwright-extension/mmlmfjhmonkocbjadbfplnigmagldckm)。执行步骤：

1. 用户在已登录 BOSS 的 Chrome profile 安装这个扩展；保留默认连接确认。
2. 实现者准备一个本地 MCP 配置，程序为 `npx`（Windows 配置需要时用 `npx.cmd`），参数是 `@playwright/mcp@<已验证版本>`、`--extension`。依赖版本在实现 PR 固定；这里的尖括号是待选择版本，不是可直接执行的命令。两个 Agent 的配置留在用户本机，不写浏览器令牌。
3. 用户在连接页选择 BOSS 标签页并确认。官方当前文档支持每个客户端独立标签组；只使用本任务组，不与其他 Agent 争用同一页。
4. 工具进入站内搜索控件，输入关键词、选择城市，核对筛选状态，逐条打开列表里的详情；把可见岗位文本交给本地文件写入环节。无需用户自己搜岗位或复制 JD。
5. 保留断开按钮与停止开关。MCP/扩展故障时先报告并结束该次采集；不要自动切到其他账号、代理或更强权限的连接。

扩展需要较强浏览器调试权限，不能因为不开放 TCP 端口就称其“只读”。只读是我们施加的动作限制。选择标签页、域名白名单、禁止发送/上传/打招呼和本地审计仍然必要。MCP 默认自动化浏览器模式不等于 `--extension` 模式。[Playwright MCP](https://github.com/microsoft/playwright-mcp/blob/176c8ea1832d5d0b36963af38191ac0088abdac6/README.md)

#### 1.3 Codex 自带读取：能力存在，本会话连接未就绪

官方当前文档区分了两个入口：内置 Browser 用独立 profile；桌面端浏览器扩展可以让 Codex 在用户常用 Chrome 的已登录页面工作。安装路径是桌面端 **Settings → Computer Use → Chrome → Install**，返回后应显示 **Manage**，再在本地 Codex 会话中选 `@Chrome`。站点授权只给目标主机；账号和组织配置可能限制可用性。[Browser extension](https://learn.chatgpt.com/docs/chrome-extension)；[Browser](https://learn.chatgpt.com/docs/browser)

本会话实际调用浏览器清单，返回 **browser access host unavailable**；Windows 原生连接也返回管道不存在。因此本轮没有接管 Chrome、没有读取用户标签或 Cookie。可在实现现场按官方故障排查检查桌面端、扩展与 profile，再开新会话验证；不能把当前有工具名称当作已具备工作连接。纯 CLI 或另一 Agent 需要另外配置 MCP，不能依赖这个桌面端能力。

浏览器里读到的文本可能进入用户所用 Agent 的模型上下文，受该产品数据控制约束；“文件存在本机”不代表“模型处理完全离线”。MVP 只给 Agent 岗位区域，排除个人资料、聊天、联系人和调试凭据。若未来要求 JD 也不进模型，应选独立的确定性 Playwright 读取进程，模型只看聚合统计；Python 核心仍不接模型 API。

### 2. 开源项目核对

以下均未安装、未对招聘平台运行。**“有近期提交”不是“目标账号验证可用”**；表中可用性结论来自所链接的 README/源码检查。许可证以查到的文件为准，只有 MIT/BSD/Apache 代码可进入借用候选；借用时仍要逐文件核查、保留版权/NOTICE，并检查依赖。GPL 只参考设计，不复制/改写其实现；无许可证、仅徽章或非商业条款均不进入借用清单。

#### 2.1 国内站点项目

| 项目与核查版本 | 许可证 | 维护证据 | 方法、覆盖与当前判断 |
| --- | --- | --- | --- |
| [lastsunday/job-hunting](https://github.com/lastsunday/job-hunting/tree/045f891354edc09e5b05be5b9aa955811ae90f8a) | [MIT](https://github.com/lastsunday/job-hunting/blob/045f891354edc09e5b05be5b9aa955811ae90f8a/LICENSE)，扩展目录也有 MIT | 默认 `dev` 分支最后提交 2026-10-09；仓库最近推送 11-02，未归档 | Chrome/Edge 扩展，覆盖 BOSS、51job、智联、猎聘、拉勾等。解析页面响应、观察 DOM 变化并存浏览记录；代码也会主动请求补充信息，频率比本方案激进。**最值得读的平台字段映射参考**，不能原样运行代替只读低频发现；非独立自动搜索收集器，当前站点有效性未实测 |
| [tenltrist/job-hunt](https://github.com/tenltrist/job-hunt/tree/3ebbe8f21d01b06ca5f665e38eb14edda7d3c684) | [MIT](https://github.com/tenltrist/job-hunt/blob/3ebbe8f21d01b06ca5f665e38eb14edda7d3c684/LICENSE) | 2026-09-14，未归档 | Node 22+ MCP：实习僧 HTML + DDG 搜索聚合；BOSS、牛客主要是搜索引擎发现，**没有专用平台 API**。作者同日记录实习僧 403/字体编码导致字段不能可靠提取；DDG 返回结果不代表仍在招。适合借鉴来源失败的明确表达，不能充当现成 BOSS 采集器 |
| [Bynlk/JobHunter](https://github.com/Bynlk/JobHunter/tree/4b5a69010a98b3d80b408fd983c1c2dfa60788e4) | [MIT](https://github.com/Bynlk/JobHunter/blob/4b5a69010a98b3d80b408fd983c1c2dfa60788e4/LICENSE) | 2026-05-07，未归档 | Playwright、Flask、SQLite，实习僧、国家就业平台及公司接口；实习僧代码包含字体映射。README 承认大量公司官网通用采集基本无效，并使用 stealth。**不整体采用**；仅借鉴来源分层/入库结构，反检测、字体解码和接口探测不移植，作者数量声明不作本项目验收证据 |
| [chadqiu/newcoder-crawler](https://github.com/chadqiu/newcoder-crawler/tree/7076bded80c162c4598f309fae6994ab2902c11e) | [Apache-2.0](https://github.com/chadqiu/newcoder-crawler/blob/7076bded80c162c4598f309fae6994ab2902c11e/LICENSE) | 2023-02-04，未归档但多年无默认分支更新 | Python requests 按关键词抓牛客讨论帖、增量保存 MySQL，含邮件提醒/Nacos/分类模型。抓的是帖子和内推线索，**不等于完整招聘岗位**；只能作旧设计参考，邮件发送和历史数据不导入，当前可用性未知 |
| [IcingTomato/BOSS_ZHIPIN-Spider](https://github.com/IcingTomato/BOSS_ZHIPIN-Spider/tree/a4ecda2bbb5eda85edade2e2f28030914574bf17) | [GPL-3.0](https://github.com/IcingTomato/BOSS_ZHIPIN-Spider/blob/a4ecda2bbb5eda85edade2e2f28030914574bf17/LICENSE)：**只参考思路** | 2023-05-23，未归档，多年无更新 | pyppeteer 按城市读取并导出 CSV/XLSX；作者仅声称在 2023-05-23 可用，不能外推到现在；不借代码 |
| [zhansan379/boss-crawler-skill](https://github.com/zhansan379/boss-crawler-skill/tree/122e6f632c97ab48103ff0eeef8ce976f482f28e) | README 标 MIT，但该提交树未找到 LICENSE，GitHub `/license` 返回 404：**暂不借代码** | 2026-09-05，未归档 | 声称 CDP/会话复用、BOSS 采集匹配和自动投递；包含自配模型 API、登录状态保存及抗风控策略，与本仓库边界不一致。只能作调查线索，不能因首页徽章认定已完成许可核验 |
| [loks666/get_jobs](https://github.com/loks666/get_jobs/tree/36bf5f986fad93374d77b99205c7684f8450874a) | 当前 [PolyForm Noncommercial 1.0.0](https://github.com/loks666/get_jobs/blob/36bf5f986fad93374d77b99205c7684f8450874a/LICENSE)：**不符合本任务许可白名单** | 2026-11-03，未归档，近期活跃 | Java Playwright 浏览器自动投递/管理系统；当前平台目录含 BOSS、51job、猎聘、智联。老 fork/介绍提到拉勾，不能据此认定主线当前支持。执行范围包含发送和投递，不作为只读采集基础；不要把网上旧 MIT/GPL 介绍当当前许可 |
| [tangke7/job-crawler](https://github.com/tangke7/job-crawler/tree/007ca8c59c3ebe9231f674600c8c71cc7505ce55) | 未找到许可证文件，`/license` 404：**不借代码** | 2026-03-30，未归档 | FastAPI/Vue 配置式爬虫，BOSS 代码使用 httpx + BeautifulSoup；目录有智联、51job、拉勾适配及 anti-crawl。有文件不等于已可用，无本轮运行证据，不进入推荐实现 |

猎聘/智联/拉勾优先参考第一项各自适配文件；实习僧应专门验证“屏幕可见但 DOM 是字体编码”的情况；牛客需区分招聘详情、社区内推帖与公司官网入口。**本轮没有发现可直接承诺在全部这些平台持续工作的宽松许可成品。** 后续每加一个来源独立验收，不以多站 README 清单一次性开通。

#### 2.2 通用工具与借用建议

| 项目 | 许可及固定核查点 | 维护情况与适用性 |
| --- | --- | --- |
| [Microsoft Playwright](https://github.com/microsoft/playwright/tree/1af60d94ac714d4007828bafa02b0f1cbd8646b9) / [Playwright MCP](https://github.com/microsoft/playwright-mcp/tree/176c8ea1832d5d0b36963af38191ac0088abdac6) | 均核对 LICENSE：Apache-2.0 | 默认分支分别为 2026-11-04 / 11-03，未归档。首选浏览器基础；现成的 CDP、定位、等待、扩展连接，平台解析仍需自己维护 |
| [ruifigueira/playwright-crx](https://github.com/ruifigueira/playwright-crx/tree/3425f33e1e114e6a2a25333d3543a84fc36bd2f5) | [Apache-2.0](https://github.com/ruifigueira/playwright-crx/blob/3425f33e1e114e6a2a25333d3543a84fc36bd2f5/LICENSE) | 默认分支 2025-09-03，package.json 为 0.15.0，未归档但一年多未更新；不能从内嵌 Playwright 文档假定兼容最新版本。用于录制/原型，不优先维护 fork |
| [remorses/playwriter](https://github.com/remorses/playwriter/tree/04342b0a8fc42c95702687191425f7b3cd7dc13a) | [MIT](https://github.com/remorses/playwriter/blob/04342b0a8fc42c95702687191425f7b3cd7dc13a/LICENSE) | 2026-11-03，未归档。Chrome 扩展 + 本地 CLI/MCP，支持在现有页面执行 Playwright，README 有 Node `connectViaExtension`；是 CRX recorder 之外的备选。独立维护者项目，Windows 与断连行为未实测；不使用其远程控制/公开中继功能 |
| [speedyapply/JobSpy](https://github.com/speedyapply/JobSpy/tree/68b88d6909a2342ad75fbb945c4204a3a7ed6665) | [MIT](https://github.com/speedyapply/JobSpy/blob/68b88d6909a2342ad75fbb945c4204a3a7ed6665/LICENSE) | 2026-10-27，未归档。统一多个海外求职站到 DataFrame，各站有专用采集逻辑；列出的 LinkedIn/Indeed/Glassdoor 等**不含 BOSS、实习僧、牛客、猎聘、智联、拉勾**。不能一换城市就变成国内站适配；不采用其代理绕封策略 |
| [g1879/DrissionPage](https://github.com/g1879/DrissionPage/tree/7761b855300a2dc4efc32c000be8150b60d21b97) | 当前 [LICENSE](https://github.com/g1879/DrissionPage/blob/7761b855300a2dc4efc32c000be8150b60d21b97/LICENSE) 有非盈利/商业授权限制，GitHub 为 NOASSERTION | 2026-10-27，未归档。虽是常见浏览器方案，**本次核查版本不是无条件 BSD 借用候选**。不能沿用旧文章的许可证结论；本方案不引入 |

### 3. BOSS 页面结构与证据边界

#### 3.1 本轮实际看到了什么

浏览器宿主不可用后，仅通过网页文本工具做了少量公开读取，没有登录：

| 探查对象 | 实际结果 | 能证明什么 |
| --- | --- | --- |
| [robots.txt](https://www.zhipin.com/robots.txt) | 工具报告不可访问 | 本轮无法重新核实 robots；不能把失败当作允许 |
| [2019-01-28 协议地址](https://www.zhipin.com/web/common/protocol/protocol-2019-01-28.html) | 文本工具返回 404 | 不能宣称已读取当前生效协议；旧地址可能失效或不可由该工具访问 |
| [搜索应用入口](https://www.zhipin.com/web/geek/jobs) | 仅得到一个输入控件，未得到职位列表 | 原始 HTML/搜索工具不能代替浏览器渲染后的列表 |
| 一个搜索引擎收录的 `/zhaopin/<分类标识>/` 公开聚合页 | 有岗位标题链接、薪资、城市区县、经验、学历、公司和截断描述 | 可作为字段存在的公开文本证据；这种 SEO 聚合页可能混入其他城市或推荐职位，不等于当前登录搜索结果 |
| 从上述列表点开**一个** `/job_detail/<不透明标识>.html` 链接 | 跳转到 `/web/passport/zp/security.html`，标题为“请稍候” | 访问安全检查已经出现；**立即停止 BOSS 探查，没有刷新、求解、登录或重试** |

公开报告不保存真实岗位名称、公司、岗位标识、验证参数或正文，因而这里只记录路径形态和字段结构；没有把公开聚合页转换成待投岗位样本。详情跳转发生在网页文本工具端，不等于用户 Chrome/账号已经被限制，也不能说已看到了某种具体 CAPTCHA。

#### 3.2 采集契约应覆盖的字段

下表区分公开聚合页已见字段与详情仍待现场核验的字段；选择器仅是定位线索，**没有把开源代码中的旧 CSS 当作本轮实测结果**。

| 字段 | 列表可见内容 / 详情需求 | 保存与验证要点 |
| --- | --- | --- |
| 职位名称 | 公开聚合页有职位标题；登录列表与详情标题需核对 | 原样保存，不用搜索关键词代替；详情打开后验证所选职位匹配 |
| 公司 | 公开页有简称、行业/规模等标签；详情公司信息需核验 | 简称和工商全称分清，没显示全称就未知；不要额外抓企业/HR 个人信息 |
| 城市 | 公开页可有城市、区、商圈；详情可能有工作地址 | 搜索城市只是筛选条件，不能补写成岗位事实；岗位多城市和面试地址分开 |
| 薪资 | 公开页有区间和薪数；日薪、月薪、面议等需保留原文 | 不在采集阶段换算；单位/周期缺失即未知，由现有规则解析 |
| 要求 | 列表经验/学历；完整技能、届别、实习天数/时长、远程条件通常要看详情 | 列表是摘要；详情没有写的保持 `null`，不从公司标签推断 |
| 职位描述 | 公开聚合页文字明显截断；本轮详情未读到 | 必须从已加载详情的职位描述区域提取并核对是否完整；列表摘要不能伪装成完整 JD |
| 链接 / 平台标识 | 列表标题的实际 `href`；详情路径通常有不透明标识 | 跟随页面真实链接，不构造/枚举 ID；保留合法来源 URL，平台 ID 按不透明字符串处理，不解码 |
| 采集状态 | 新增、重复、摘要、完整、受限、失效、解析失败等本地状态 | “登录/验证/空壳”不等于“没有岗位”；截断、失效和缺失分别表达 |

可参考的已核查源码是 [job-hunting 的 BOSS 适配](https://github.com/lastsunday/job-hunting/blob/045f891354edc09e5b05be5b9aa955811ae90f8a/apps/extension/entrypoints/content/plantforms/boss/index.js)：使用 `.card-area`、`.job-card-body`、`.job-card-left` 等节点并解析响应。实现时先做一次现场结构检查，优先可访问名称、详情区标题和实际链接；封装选择器，发现定位不唯一、字段不匹配或页面结构变更就停止，避免用空值继续整批运行。

#### 3.3 前端 JSON：有第三方证据，没有本轮登录态证据

上述 MIT 项目有响应 JSON 的解析和补充请求代码，说明存在/曾存在前端结构化响应路径。但本轮没有已登录浏览器的 Network 数据，**不能确认当前账号会返回哪些字段，也不记录未经现场观察的接口路径、参数或响应样本**。不从开源项目照抄内部 URL，更不逆向签名、加密参数或复用认证头。

MVP 以渲染后 DOM 为唯一必需来源。若后续在已授权、已登录浏览器中，用户正常点击列表/详情时确实看到相应 JSON，只被动观察此次页面本来发出的响应，记录字段名与可见页面的对应关系；不重放请求、不扩大页数/字段范围，不保存 Cookie、令牌、请求头或完整 HAR。没有响应权限就继续 DOM，不为了 JSON 放宽调试权限。

#### 3.4 公开反自动化说法及其含义

- 仓库现有 [ADR-9](../cn-migration-plan.md) 已记录 BOSS 协议对插件、第三方工具和拟人程序的限制。搜索索引中的 [2019-09-30 协议](https://www.zhipin.com/web/common/protocol/protocol-2019-09-30.html) 也可见有关爬虫/拟人程序获取信息的条款；**这不是对当前协议全文的重新核验**。用户同意操作自己的账号不等于平台授权，低频和只读也不能保证符合条款。
- 公开项目普遍记录验证码、登录失效、访问受限等问题，但没有找到可以作为承诺的官方“每分钟安全次数”。本轮单详情已触发安全页；应将安全页/验证码、HTTP 403/429、异常跳转、登录页、空列表异常都作为停止信号，不当作自动重试理由。
- 账号限制或封禁是需用户了解的剩余风险；限速只能降低请求压力，不能承诺不受限。不改变浏览器指纹，不装 stealth，不用代理轮换/多账号，不解决验证码。人处理验证后，只有明确恢复指令才重新确认页面并继续；受限反复出现则结束该次任务。

## 决策

### 4. 最小可行版本：采集到短名单

```text
用户给关键词 + 城市 + 本次上限
  → 本地浏览器连接（官方扩展优先；CDP 专用目录备选）
  → BOSS 搜索列表 → 按实际链接逐条读取详情
  → data/inbox/<run_id>/：岗位文本 + 来源清单 + 进度
  → 现有 jd parse --save（“JD import”在当前 CLI 的真实入口）
  → M6-4 批量硬条件过滤 + 规则评分
  → 少量候选补充有依据的经历/方向评分
  → 本地短名单和失败/待确认清单
```

| 模块 | 责任与输出 | 边界 |
| --- | --- | --- |
| 连接/动作控制 | 校验浏览器、profile、标签组、目标域名；搜索控件操作、单页串行；统一限额、停止、人工恢复 | 浏览器层在核心包外；不得自动登录或触碰发送、简历、收藏/关注、聊天等写操作 |
| 来源适配 | 从**实际卡片链接**发现岗位、读取完整详情，附提取版本与证据位置；列表、详情做一致性检查 | 首先只做 BOSS；每个平台独立适配，站外和 JD 正文链接不访问 |
| 本地收件箱 | 一岗一份 UTF-8 文本，来源/采集时间单独清单；每条原子写入、去重与断点 | 不保存全站 HTML、浏览器 profile、Cookie 或 HAR；只把岗位可见区域写入正文 |
| 导入桥接 | 逐条调用现有 `jd parse --site boss --url <页面来源> --save --data-dir <指定目录>`，收集返回岗位 ID 与 action | 文件路径通过参数传入，不用 PowerShell 中文管道；多岗位不能共用一个 `--url` |
| M6-4 批处理 | 对本次保存/更新 ID 运行 `match filter`、`match score --save`；逐条失败不丢整批；必要时按共用工作流补证据 | 保持标准库、离线、确定性；批处理命令名称由 M6-4 定，本报告不假装它已存在 |
| 短名单 | 明确硬条件结论、分数是否完整、未知项、来源和采集日期；生成本地报告 | 只统计本次批次；不把未评分、过期、详情失败或硬冲突项混进可投推荐，不凑数量 |

现有 [JD 导入工作流](../jd-import.md) 要求元信息不混入正文，且当前 Job Schema 尚无门户岗位 ID。建议收件箱先采用如下**待与 M6-4 对齐的旁路清单契约**，不直接给现有 Job Schema 塞字段：

- `run_id`、`site`、`query`、`requested_city`、`captured_at`（有时区）、`collector_version`；
- 每条 `text_file`（只允许本批目录内相对路径）、`source_url`（真实岗位页面链接，去掉已确认的跟踪/认证参数）、`portal_job_id`（只能从已见链接/页面取，缺失为 `null`）、`content_hash`；
- `completeness`（`list_only` / `detail_complete`）、`state`（`captured` / `duplicate` / `needs_human` / `unreachable` / `failed`）、`reason`；
- 导入后回填 `local_job_id` 和 `created` / `updated` / `unchanged`，保存运行计数与当前停止位置。

原始带参数链接如含临时安全标识仅在当前浏览器导航中使用，不存日志；不能确认哪些参数可去除时，将 URL 处理问题列为待核验，不臆造可访问的规范链接。收件箱文本应保留标题、公司、城市、薪资和描述等**页面原文**，无抓取时间前缀、无 AI 改写。跨批去重先沿用现有 store 的内容指纹与规范化 URL；门户 ID 第一优先级是后续 Schema 变更，不能本轮宣称已有。

**批次运行规则建议**（工程初值，不是平台允许量）：单账号、单浏览器、单任务、串行；完成一次页面加载后至少等 8–15 秒才做下一次导航/翻页；首轮最多 10 个详情、最多 2 页列表，短批验证后可设每次最多 30 个详情、每日最多 50 个。计数跨重启持久化；已访问详情、失败尝试也计入导航预算。任何验证/风控信号立即停止且不自动重试，达到上限即交付已有结果，不能为了凑够数量继续访问。不要把 `slow_mo` 当作完整限速器，它只减慢 Playwright 动作。

**断点与质量**：每条完成就写进度；恢复时以来源 URL/平台 ID 和内容指纹避重，不重新打开已完成详情。详情为空、加载不全或身份不匹配标为失败/摘要，保留到待重查清单；不覆盖已有完整 JD，也不因此生成低质量评分。真实零结果、暂时空壳、登录失效、验证、下架分别计数。JD 必经 `guard.py`；警告不成为执行页面指令的理由。

**评分衔接**：按 [match 工作流](../match.md) 使用当前已确认权重；流程未问过偏好时只在整批前问一次，同一会话已有选择则沿用。不因搜索城市而自动改档案或推断远程。规则评分的经历维度可能为空，先标明“不完整初筛”；仅对少量候选按既有流程补经历/方向证据。新导入、原文更新或规则/档案变更的记录重新评分，不能复用过期分数。经理提出的“远程未写明按不符合”需等相应档案/评分变更落地后使用，不在采集器偷偷加一套规则。

### 5. 一次性设置与实施边界

用户只需：安装并连接选定扩展，在自己的浏览器里保持登录，连接时选定标签，给出关键词、城市和批次上限。之后发现列表、打开详情、保存、导入和初筛都由工具完成；只有验证码、登录失效等平台要求出现时交还用户。选择 CDP 备选则多一次专用 profile 人工登录，后续用固定快捷方式启动。

**与旧 ADR 的关系必须写清**：规划者本轮已经把已登录浏览器发现提前，优先级和“不得使用登录内容”的旧路线描述以本轮授权为准，不能再把“请用户手工收集”当交付。但这并不自动更改 [ADR-4/ADR-9](../cn-migration-plan.md) 的公开代码边界。建议：

1. M6-4 的通用导入/过滤/报告留在公开核心包，继续通过离线守卫。
2. BOSS 站内浏览器工作流按 ADR-9 放在默认关闭的个人 Agent 工作流或私有模块；不作为已核准公共门户塞入 `.agents/skills/`，不让上游 `/scrape` 自动调用。
3. 如规划者要把登录态 BOSS 采集代码公开纳入主体，需在实施 PR 明确修改 ADR-9、说明来源授权/协议核查和权限范围；本报告不默许这项架构扩大，也不修改权限白名单。

推荐顺序：官方扩展连接验收 → BOSS 10 条以内小批 DOM 验收 → 对接 M6-4 → 把断点/限额固定下来 → 再单独验证猎聘、智联、拉勾、实习僧、牛客。不能把“先支持六个平台”作为拿到第一批短名单的前置条件。

## 验证

- 阅读了本机协调提醒、经理意见书第 2 条及规划者决定；这些非公开文件没有复制进仓库。
- 已读取 Chrome、Playwright、OpenAI 官方资料；通过 GitHub API 核对所列项目的默认分支 SHA、提交日期、归档状态和许可证内容；未以 stars、搜索摘要或 README 徽章代替许可核验。
- 已核对公开列表字段与详情安全跳转；登录态 DOM、真实账号频率阈值和前端 JSON 均未实测，没有运行任何第三方爬虫。
- 已核对当前 `jd parse`、store 去重、评分工作流与 ADR 边界；M6-4 新批处理和门户 ID 字段只作为待对接设计。
- 提交前已同步 `origin/master`（`c9d1202`），在 conda 环境 `ai-job-search-cn` 运行：`python tools/lint_skills.py` 通过（14 skills、12 commands）；`python tools/security_guards.py` 通过；`python -m unittest discover -s tests -t .` 通过（1765 项，跳过 27 项，350.207 秒）。这些验证仓库基线，不代表浏览器或招聘源可用性测试。
- 文档 UTF-8 检查无 U+FFFD，内部相对链接均存在；提交范围仅本报告，无 `data/` 文件。

## 遗留

- 本地浏览器宿主尚未连通；目标 Windows Chrome 版本、扩展版本及真实登录标签均待实施现场确认。
- 当前 BOSS 协议和 robots 未重新核实；公开文本安全跳转后没有继续访问。此报告给出技术路线，不宣称平台授予采集许可或保证账号不会受限。
- 没有登录态 Network 证据，内部接口目录留空。完整详情字段、页面变体、字体编码、正常零结果与受限页面的区分都需一次小规模现场验收。
- **请规划者在 PR 审阅中裁定**：采用“官方 Playwright Extension + MCP”为首选、CDP 专用 profile 为备选；BOSS 读取仍放个人/私有工作流；与 M6-4 对齐收件箱清单、部分失败以及不完整评分的短名单语义。

## 下一步

M6-3 实现者按本报告准备连接与只读流程；独立验收者在用户亲自登录后验证以下完成条件：

1. 用户只给关键词和城市，工具自行找到列表和详情，并在指定本地收件箱留下可追溯文本；无需用户找岗位链接或复制正文。
2. 小批每条都有正确标题/公司/地点/薪资/链接，正文完整性与页面一致；缺失不编造。重复运行不重复入库，更新不覆盖用户已确认信息的规则以 store 契约为准。
3. 页面中出现验证/登录/受限、字段结构异常或上限耗尽时，后续导航立即停止，已有文件与断点可恢复；不为测试故意触发真实站点风控，停止逻辑先用本地模拟页验证。
4. 没有消息、投递、上传或个人资料读取；日志与输出没有 Cookie/令牌/验证参数；浏览器连接结束后用户会话仍可用。
5. M6-4 对同一批完成逐条导入、去重、硬条件过滤和评分，报告分别列出可推荐、待确认、硬冲突及读取/导入失败；人工抽查至少 3 条的来源和评分依据。

本轮交付到研究 PR 为止，由规划者审阅和合并，不替实现者提前声称 M6-3 或 M6-4 已完成。
