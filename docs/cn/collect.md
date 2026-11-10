# 通用采集框架和本地收件导入

公开项目只接入用户协议不禁止、免登录、无需绕过防护的来源。接入前逐个核对条款和 robots；框架存在不代表某个来源已获许可或可用。协议禁止的网站适配器、插件和操作说明不在公开项目中提供。来源决定见 [ADR-9](cn-migration-plan.md)。

## 本地个人模块：默认关闭

唯一开关是环境变量 `JOBSEARCH_CN_PERSONAL_MODULE`，值为可信的本机 Python 包目录绝对路径（其中有 `__init__.py`），也可指向该文件。未配置或为空时不搜索、不导入任何个人模块，`collect` 没有个人站点子命令。其他命令无论是否配置都不加载个人模块。

```powershell
# 只对当前 PowerShell 会话生效；路径由用户自己提供
$env:JOBSEARCH_CN_PERSONAL_MODULE = 'D:\local-adapters\my_adapters'
python -m jobsearch_cn collect --help
# 用完关闭
Remove-Item Env:JOBSEARCH_CN_PERSONAL_MODULE
```

只接受本机绝对路径，拒绝 URL、相对路径、UNC 共享和映射网络盘。加载器不联网、不安装包、不改 `sys.path`。模块是用户信任的可执行 Python，具有当前进程权限，不是沙箱；用户自己审查模块代码。模块应只在本机使用，协议风险由用户承担。不要把个人模块或本地配置提交到公开仓库。

包的 `__init__.py` 导出 `ADAPTERS = {"example": example}`（`example` 可用相对导入）。适配器契约列在 `jobsearch_cn/collect.py` 模块说明中：来源枚举、城市规则、分页方式、就绪选择器、链接识别、卡片/详情解析、验证/登录/下线判定等。官网沿用 `SITE = "official"`，自己的岗位 ID 放 `extra.site_job_id`，按完整来源 URL 去重。`OFFLINE_ONLY = True` 的模块会在打开浏览器前拒绝采集。

仓库 `tests/fixtures/collect_personal/` 仅为虚构站点回归样例，不是实际来源。

## 采集命令和边界

配置适配器后运行 `python -m jobsearch_cn collect <适配器名> --query '搜索词' --city '广州' --max 10 --data-dir '<本地数据目录>'`。默认最多 30 个新详情、3 页列表；硬上限 50 个详情、10 页，每次导航或滚动之间随机等待 4–9 秒。`--batch` 可指定批次，已有同名原件不会覆盖；`--city-code` 仅在适配器声明城市代码规则时出现。

浏览器依赖是可选的 `playwright` Python 包，只有采集时才导入；运行环境还需已安装 Google Chrome。不自动下载浏览器。默认启动临时无窗口 Chrome，用完关闭；`--cdp http://127.0.0.1:9222` 可显式连接专用本机 Chrome，只创建并关闭本次标签。仍只读取免登录的公开内容，不读取 Cookie、不自动登录、不点击、不发送、不绕验证。

HTTP 403/429（包括本次标签的列表/数据请求）、验证码、登录墙、结构变化都会停止后续访问。空白的后续列表不视为正常结束，只有明确空态才算；整段加载提示、失败提示和纯标题不能当完整正文。历史收件和岗位库中已知的 URL 不重新打开；适配器可用 `known_job_id_from_url` 识别旧链接，但不得因此放宽实际导航地址。输出为 JSON，退出码：0 完成，2 无法开始，3 遇到限制或写入保护，4 页面结构无法识别。停止前保存的文件保留。

### 结构异常诊断（默认关闭）

所有 `collect` 子命令可加 `--diagnostics`。遇到 `page_changed`（退出 4）时，把触发停止的当次已有页面快照存到 `<数据目录>/collect/diagnostics/<batch>/<时间-随机ID>/`，供离线读取适配器排查。诊断不额外访问、滚动、重载或截图；默认不保存，也不增加输出字段。`done`、`needs_user`（包括 HTTP 403/429、验证码和登录）不保存页面。

目录内 `page.html` 是原样的 UTF-8 页面数据，最多 1,000,000 字节，超限只保留完整字符组成的前缀；`metadata.json` 记录实际 URL、标题、已有 HTTP 状态（未知为 `null`）、`list`/`detail` 阶段、停止原因、时间、原始／保存字节数和 SHA256，以及 `truncated`。不保存页面捕获的网络请求／响应体、Cookie、请求头或浏览器存储；元数据超过 64,000 字节则诊断失败。HTML 是不可信外部数据，只作为文本检查，不执行脚本或访问其中链接。页面文本和链接可能含私人内容，真实诊断文件只留本地，不上传含私人内容的原件。

启用后的输出新增 `diagnostics`：`saved` 为完整保存、`truncated` 为 HTML 已截断、`unavailable` 为停止时没有可用快照、`failed` 为无法安全保存、`not_applicable` 为本次没有结构停止。保存成功时含 `directory`、`html`、`metadata` 路径和 `complete: true`。没有快照时不使用前一页代替。诊断不会成为岗位收件，不改变 `saved`、`files`、退出码或原停止原因。

目录不穿过数据目录内的符号链接／junction，每次用新目录，文件原子创建且不覆盖。`metadata.json` 最后发布，作为完整诊断的清单。若中途失败，输出 `complete: false`、错误及已知的 `partial_files`（目录无法安全检查时为 `null`）；部分文件保留供核对，不自动清除，也不继续采集。文件系统不支持原子创建时不降级覆盖。

## 本地 JSON 导入

```powershell
python -m jobsearch_cn jd inbox-import 'D:\downloads\jobsearch-inbox' --site official --data-dir 'D:\local-jobs'
```

省略目录时使用 `~/Downloads/jobsearch-inbox`，默认来源 `official`；其他来源显式用 `--site`。只将符合 [收件格式](screen.md) 的 JSON 移入新批次，无效文件留在原处并列于 `left`；不直接写岗位库。完整复制后原子发布目标，再移除来源；磁盘不足不会留下半份 JSON，原件和并发创建的同名文件均受保护。文件系统不支持硬链接时停止，不降级覆盖。

结果包含 `batch`、`moved`、`files`、`left`、`next`、`next_shell` 和 `next_argv`。`next` 在 Windows 明确供 PowerShell 使用，路径里的空格、美元符号、反引号和单引号均按字面保留；其他系统用 POSIX shell。程序调用优先使用结构化的 `next_argv`。后续 `jd screen` 使用本次真实数据目录，不依赖下一次进程的默认值。

`extra.page == "list"` 的摘要可以新增岗位，但不能覆盖已保存正文；完整详情仍可更新。目录错误按 CLI 的 JSON 错误契约返回，退出 2。没有文件成功移动时退出 1；失败后若因来源删除失败而留下完整副本，会保留批次供人工核对。

## 北森招聘门户（`collect beisen`，M6-3）

北森（`<子域名>.zhiye.com`）的平台条款没有禁止自动采集，robots 允许，列表和详情不登录就能看（来源核查见 [工作记录](worklog/2026-11-10-m6-3-beisen.md)）。适配器在公开项目里，但**只读用户本机白名单里的租户**，不做全网发现；不在名单里的子域名在打开浏览器之前就被拒绝。每加一家，先读这家门户自己的条款（门户页脚的“隐私政策”等），没有禁止自动采集才写进名单，并记下链接和核查日期。名单在数据目录里，不进仓库；仓库只放下面这份虚构示例。

白名单位置固定为 `<数据目录>/collect/beisen.json`（数据目录同 `--data-dir`，默认仓库下的 `data/`，或环境变量 `JOBSEARCH_CN_DATA_DIR`），UTF-8 JSON：

```json
{
  "format": "jobsearch_cn.beisen/1",
  "city_codes": {"韶关": "4402"},
  "tenants": [
    {"subdomain": "example", "portal": "new", "company": "示例科技",
     "channels": ["intern", "campus"], "cities": ["广州"],
     "terms_url": "https://example.zhiye.com/privacy", "terms_checked": "2026-11-09"},
    {"subdomain": "example-legacy", "portal": "legacy", "company": "示例信息",
     "channels": ["campus"], "cities": ["广州", "韶关"],
     "terms_url": "https://example-legacy.zhiye.com/Portal/Apply/PrivacyPolicy", "terms_checked": "2026-11-09",
     "note": "可选：自己的备注"}
  ]
}
```

- `subdomain`：门户地址 `https://<子域名>.zhiye.com` 里的子域名；`portal`：`new` 新版（单页应用，列表 `/{频道}/jobs`）或 `legacy` 旧版（服务端渲染，列表 `/search`、详情 `/zpdetail/<数字>`）；`company`：写进岗位正文的公司名。
- `channels`：`campus` 校招、`intern` 实习、`social` 社招，写这家门户实际有的；`cities`：城市名。常用城市的四位代码已内置（行政区划代码前四位，广州 4401），其他城市在 `city_codes` 里补。
- `terms_url`、`terms_checked`：这家门户条款的链接和读条款的日期（不能晚于当天）。

```powershell
python -m jobsearch_cn collect beisen --tenant example --data-dir 'D:\local-jobs'
# 只读一个频道；只搜一个词；不按关键词读全部
python -m jobsearch_cn collect beisen --tenant example --channel intern --query 'Agent'
python -m jobsearch_cn collect beisen --tenant example --all
```

一次运行读一家租户：白名单里的每个频道 × 每个城市 × 档案 `target.search_keywords` 的每个关键词各是一组搜索（档案没有关键词、或用 `--all` 时每个频道和城市读全部），按这个顺序读，组与组之间按岗位 ID 去重。所有组合计最多 5 次列表加载（`--max-pages`）、30 个详情页（`--max`），用完就停，结果的 `searches` 列出每组读了几次、怎么结束的（`not_run` 是额度用完没轮到，下次可用 `--channel`、`--query` 分开跑）。翻页和打开详情之间随机等 4–9 秒。

- 新版门户的岗位卡片没有链接，岗位 ID 来自页面自己发出的列表请求的响应：浏览器只被动记下与当前门户同源（协议、主机和端口相同）的响应，不自己构造或发送请求，也不读取其他租户的响应。响应里每条岗位的 `Id` 是详情页地址用的 UUID（`JobAdId` 是门户内部的数字编号，不用），`Count` 是整个结果的总数（`Total` 总是 0），每次加载 20 条，向下滚动加载后面的；页面在第一批底部就显示“没有更多了~”，所以以 `Count` 为准。详情页从页面上读。门户没有按地址里的关键词搜索时（页面发出的列表请求里缺少关键词或不是这个词）停下并说明，改用 `--all`；响应不是可识别的 JSON，或不是上面这种格式，也会停下。
- 旧版门户按 `r`（频道）、`c`（城市代码）、`k`（关键词）、`PageIndex`（页码）读列表。详情页只读岗位本身的区域（页面侧栏的搜索表单不算）：标题去掉后面的“(未申请)”，“工作地点：”“工作性质：”“薪资范围：”“发布时间：”这些标签取紧跟的值，“工作职责”“任职资格”等标题下的文字是正文。
- 没有结果只认门户自己明确的标志：新版要列表响应说 0 条（`Count` 为 0、没有岗位）且页面显示“暂时没有符合条件的职位~”空态框；旧版要页面写着“共0条记录”或显示“没有搜索到相关应聘职位”。认不出岗位、响应和页面对不上、或写着有 N 条却一条也读不出，都按“页面结构变了”停下，不当作没有结果。空态框和“共 0 个”可能在列表响应到达之前就出现，所以新版的空结果要等到就绪等待结束后再判断，这一组会多等十几秒。
- 旧版另一个已核空态模板：`.positionlist-smallblue` 主模块内 `.joblist > table.jobsTable` 的同一空态行，须有可见 `span.noResult` 和确切文字“没有搜索到相应职位”。主表有链接、未知行、可见非零计数、多个不一致主表或混合可见列表模板时仍停止；侧栏职位不算搜索结果。该模板目前只支持明确空态，不支持非空卡片或详情。可见性沿用 hidden／隐藏内联样式检查，不计算外部 CSS。
- 停止：HTTP 403/429、验证码、跳到登录页、接口报错，或页面显示还有更多但连续两次加载都没有新岗位，都会停下这家租户，结果里写明原因；已存的不受影响。
- 岗位 ID 是 `beisen.<子域名>.<门户的岗位 ID>`，写进收件文件的 `site_job_id`（见 [job-schema.md](job-schema.md)），是重跑时去重的第一依据。正文第一行是岗位名（去掉末尾的 `(J12345)` 编号，编号另记在 `extra.job_code`），后面是“招聘频道”“工作地点”“工作性质”“薪资”（“面议”照写）“发布时间”“公司名称”和职责、要求原文；页面没给的就不写，导入后保持 `null`。收件夹是 `<数据目录>/inbox/ats/<批次>/`，之后照常 `jd screen`。
