# 2026-11-05 · M6-3 BOSS 直聘采集器（Claude B）

分支 `feat/cn-m6-3-boss-collect`，从 master 1a10d61 开。

**依据**：经理意见书-007 第 2 条（岗位由工具自己找，首要来源 BOSS 直聘）和规划者的落实；规划者派活（接管本机专用 Chrome，CDP 端口 127.0.0.1:9222，Playwright `connect_over_cdp`，可选依赖）；[M6 调研](2026-11-04-m6-discovery-research.md) 第 3–5 节；M6-4 设计稿（`feat/cn-m6-4-batch-screen` 上的 `2026-11-04-m6-4-batch-screen.md`）第 3 节"收件夹格式"。

## 做了什么

- 命令 `python -m jobsearch_cn collect boss --query … --city … [--max] [--max-pages] [--batch] [--cdp] [--data-dir]`，文档 [collect.md](../collect.md)。
- 新模块四个：
  - `htmltext.py`：标准库的 HTML 读取：DOM 树、CSS 选择器子集（标签、类、id、属性，后代和子代）、近似 innerText；
  - `boss.py`：BOSS 的站点规则，选择器全在 `SELECTORS` 一个常量里，另有城市代码、安全检查页和登录页的地址与标题、岗位 ID 的取法；
  - `collect.py`：一次采集的流程、限速、停止、断点续抓、写收件夹；
  - `browser.py`：Playwright 驱动，唯一导入第三方包的文件，在函数里导入。
- `tests/test_cn_collect.py`（34 个测试）和 `tests/fixtures/cn/boss/` 的虚构样例页面；`tests/test_cn_package.py` 加了 `OPTIONAL_IMPORTS` 例外和三个守护测试。
- ADR-4、ADR-9 各加一条 2026-11-05 的修订说明（见"要裁定的问题"第 1 条）。

## 决定

1. **页面在 Python 里读，不在浏览器里跑脚本**。浏览器只负责导航、滚动、交出渲染后的整页 HTML（`page.content()`）；字段在 `htmltext.py` + `boss.py` 里用标准库读。这样实测和离线测试走同一段代码，样例页面就能测到真实路径；`browser.py` 也不需要 `evaluate`（测试禁止它调用 `evaluate`、`click`、`fill`、`cookies` 等）。代价是 innerText 只是近似：样式表里的隐藏不生效，所以规则要点名具体的容器；职位描述按 `pre-line` 处理换行。
2. **text 的排法照整页复制**（第一行岗位名 + 薪资，第二行空格分隔的标签行，然后"职位描述"、技能标签、正文、"工作地址"、地址、公司简称、公司信息、工商全称），测试里用 `jd parse --site boss` 读样例，岗位名、公司、城市、薪资、届别、每周天数、实习时长、学历都读得出来。招聘者整块（含"刚刚活跃"）、推荐职位、按钮、公司介绍、福利标签在读字段前删掉。
3. **`url` 存去掉查询参数的详情页链接**：`lid`、`securityId`、`sessionId` 每次访问都变，调研也要求不保存临时安全标识；导航时用卡片上的原链接。
4. **断点续抓**看两处：`inbox/boss/` 下所有批次的 JSON（`site_job_id` 或 `url`），和岗位库里 `source.url` 是 BOSS 详情页的记录（M6-4 加了 `source.site_job_id` 以后也认）。读不了的收件夹文件记一条提醒，不算抓过。
5. **列表翻页按滚动加载写**（`PAGINATION = "scroll"`，调研看到的入口是 `/web/geek/jobs`）；地址带页码的旧版写法也留了（`"url"`），实测后定。先读列表、凑够要打开的岗位，再逐个打开详情，列表只加载需要的屏数。
6. **退出码**：0 正常结束；2 没能开始；3 要用户在浏览器里处理（安全检查、验证码、登录页、HTTP 403/429、跳到别的网站、浏览器出错）；4 页面结构认不出（找不到卡片、详情缺岗位名或描述、打开后不是这个岗位、岗位名对不上）。3 和 4 都保留已存的岗位。
7. **上限**：`--max` 默认 30、最多 50；`--max-pages` 默认 3、最多 10；间隔 4–9 秒写死在 `collect.DELAY_RANGE`，不能用参数调小。
8. **只连本机**：`--cdp` 只接受 `http://127.0.0.1|localhost|[::1]:端口`。关闭时只关自己的标签、断开连接，不调用 `browser.close()`。

## 没做的

- 每天的总量上限（调研建议每天不超过 50 个详情页）：现在只有每次的上限，写在 collect.md 的已知局限里。
- Agent 入口和权限白名单：派活没有要求；把 `Bash(python -m jobsearch_cn collect:*)` 加进白名单要改 `tools/security_guards.py`，须经理本人同意，没有动。
- 路线图 M6-3 那一行还是旧的说法（"至少 2 个合规来源、Job Schema 加门户岗位 ID"），由规划者改；Job Schema 的门户岗位 ID 在 M6-4 做。

## 要裁定的问题

1. **采集代码放进公开的项目主体**：ADR-9 原来写"招聘平台站内自动化……默认关闭、不公开的个人模块，不放进项目主体"，调研也说放进主体要在实施 PR 里明确修改 ADR-9。派活定的命令在 `jobsearch_cn` 里，所以我在 ADR-9 加了 2026-11-05 修订（默认不启用、只读、限速、遇检查即停、不读 Cookie），ADR-4 加了 `browser.py` 的例外。请规划者确认措辞。

## 进展

- 开工时查过：CDP 端口通（Chrome 156），只开着一个标签；zhipin.com 还没有 Cookie，即经理还没登录。先写代码和离线测试，登录后再做小量实测。
- 01:30–02:20 代码、样例、测试、文档写完，提交 dc48198，开草稿 PR #142。全量测试 1805 个通过（跳过 26），`security_guards`、`lint_skills` 通过。
- 和 M6-4 对接：在临时工作树里签出 `feat/cn-m6-4-batch-screen`（PR #141 的 `jd screen`），用本分支的采集流程和虚构样例写出一个 5 个岗位的批次，`jd screen <批次> --check` 结果 ok 5、failed 0、ignored 0。
- 等经理登录期间，后台每分钟查一次 zhipin.com 有没有登录 Cookie（只看名字，不看值）。
- 提交 344b309：滚动加载时，没有详情链接的卡片只提醒一次（不再每屏一条）；卡片选择器加 `.card-area` 备选；collect.md 写明停下以后怎么处理。测试加到 33 个。
- 03:10 上一个会话中断，新会话接手。查过进程：登录监视脚本和上一个会话的全量测试都已经不在（当时在跑的全量测试是 `cn` 工作树的，没有动），端口 9222 的 Chrome 没有动。对接 M6-4 用的临时工作树 `tmp/m63-m64wt` 已删；M6-4 的远端分支从对接以后没有新提交。
- `browser.py` 的真实路径，离线测试和 CI 都跑不到（测试用假标签页，CI 不装 Playwright），所以在一次性的环境里跑了一遍：临时 venv 装 Playwright 1.64.1，单独起一个 headless Chrome 156（临时资料目录、端口 9345、除本机外的域名全部解析失败），本机服务虚构样例，把 `boss.ORIGIN` 指过去，跑真的 `collect boss`。结果：5 个岗位存下，滚动后卡片增加能等到，`text` 和离线读取一字不差；重跑不再打开详情；跳到安全检查页和 HTTP 429 都是退出码 3、已存的保留、不重试；连不上和没装 Playwright 都是退出码 2；每次跑完标签页和跑之前一样，浏览器还在。脚本没有进仓库。
- 经理今晚可能不登录，规划者定不等实测，先交审。**待做：登录后的小量实测**（`--max 3`）：选择器和翻页方式只对着虚构样例测过，样例又是按选择器写的，所以对不对得上真实页面还不知道，可能要改 `boss.py`。本机 `ai-job-search-cn` 环境还没装 Playwright，实测前先装。实测通过后删掉 collect.md 第 8 节第一条。
- 上一个会话 API 断线，新会话接手收尾。合入 master dc77a10（#141 M6-4 `jd screen`、#143 v0.2.0），`cli.py` 的导入冲突两边都留。用 master 上的 `jd screen --check` 读采集流程用虚构样例写出的 5 个岗位的批次：ok 5、failed 0、jobs 5，没有重复和忽略的文件，`unread` 全空，`guard` 全是 clean。这一项写成了测试 `test_jd_screen_check_takes_the_batch`：用 `screen.check` 本身来读，不照抄它的规则，把 `INBOX_FORMAT` 改成 `/2` 时这个测试失败。测试加到 34 个。
- 同时：`collect.py` 改用 `schema.is_site_job_id`，不再自己写一份岗位 ID 的正则；collect.md 第 6 节补上 `jd screen` 的命令和第一次实测后先看 `unread`；代码和文档里引用 M6-4 设计稿的地方改指 screen.md 第 2 节，screen.md 开头指到 collect.md。
