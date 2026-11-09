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

## 本地 JSON 导入

```powershell
python -m jobsearch_cn jd inbox-import 'D:\downloads\jobsearch-inbox' --site official --data-dir 'D:\local-jobs'
```

省略目录时使用 `~/Downloads/jobsearch-inbox`，默认来源 `official`；其他来源显式用 `--site`。只将符合 [收件格式](screen.md) 的 JSON 移入新批次，无效文件留在原处并列于 `left`；不直接写岗位库。完整复制后原子发布目标，再移除来源；磁盘不足不会留下半份 JSON，原件和并发创建的同名文件均受保护。文件系统不支持硬链接时停止，不降级覆盖。

结果包含 `batch`、`moved`、`files`、`left`、`next`、`next_shell` 和 `next_argv`。`next` 在 Windows 明确供 PowerShell 使用，路径里的空格、美元符号、反引号和单引号均按字面保留；其他系统用 POSIX shell。程序调用优先使用结构化的 `next_argv`。后续 `jd screen` 使用本次真实数据目录，不依赖下一次进程的默认值。

`extra.page == "list"` 的摘要可以新增岗位，但不能覆盖已保存正文；完整详情仍可更新。目录错误按 CLI 的 JSON 错误契约返回，退出 2。没有文件成功移动时退出 1；失败后若因来源删除失败而留下完整副本，会保留批次供人工核对。
