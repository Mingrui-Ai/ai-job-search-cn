# 2026-10-29 · M3-0：简历生成方式的原型对比（进行中，Claude C）

> 进度记录。前半部分是 2026-10-29 暂停时的进度，后面接 2026-10-30 的工作。对比报告见 [m3-0-resume-prototypes.md](../m3-0-resume-prototypes.md)。用户已选定 H（habaneraa 中文一页），结论在报告 1.1。

## 完成

- 读了路线图 §5 的 M3-0 任务单。
- 摸清本机已有的工具（只查看，没装）：Microsoft Word（Office16）、Edge、`pdftotext`（Git 自带的 mingw 版）、pypdf 6.21；**没有** LaTeX、Typst、LibreOffice、pandoc。
- 字体：Windows 自带 Noto Sans SC、Noto Serif SC（OFL）以及微软雅黑、宋体、黑体、等线。读了各字体 OS/2 表的 `fsType`：Noto 两款是 0（无限制），微软的四款是 8（允许嵌入、可编辑），都可以嵌进 PDF。
- 安装：用 AskUserQuestion 问过用户，**只同意装 Typst 便携版**（不装 TinyTeX、LibreOffice）。已装 Typst 0.15.1 官方 Windows 包到仓库外的 `D:\05_Software\typst-0.15.1\`（下载的压缩包 22.5 MB，解压后 `typst.exe` 52.5 MB；解压即用，不需要管理员权限）；下载文件的 SHA-256 和 GitHub 发布页给出的 digest 一致（`19ce3551…6736`）。`typst fonts` 能看到 Noto Sans SC 等中文字体。
- 原型脚本写好了，**还没运行**：`data/m3-0/scripts/resume.py`（被 git 忽略，不进 `jobsearch_cn/`；本机文件 SHA-256 前 16 位 `3fb1fd3ee35c7117`）。它从示例档案 `tests/fixtures/cn/profile/tech` 生成同一份内容模型，再按三种做法各出一份 Word 和 PDF，输出到 `data/m3-0/out/`：
  - **A**：标准库写 DOCX（zipfile + WordprocessingML，字体微软雅黑），用本机 Word（PowerShell 调 COM 的 `ExportAsFixedFormat`）导出 PDF。脚本只在 Word 里没有其他打开的文档时才退出 Word，不会关掉用户开着的文档；
  - **B**：HTML + CSS，用 Edge 无界面模式打印成 PDF（临时的 `--user-data-dir`，不碰用户的 Edge 配置）；DOCX 用和 A 相同的写法；
  - **C**：Typst 读 JSON 数据编译成 PDF（字体 Noto Sans SC）；DOCX 同 A；
  - 另有 `--long`：把实习和项目各重复三遍的压力测试，看超出一页时各做法的表现。
  - 每种做法都检查：页数和文本层（`tools/verify_pdf.py`）、日期范围是否用 ASCII 连字符、PDF 里嵌入的字体、模型里每一行在 PDF 和 DOCX 里是否都能找到、DOCX 和 PDF 的文字是否一致（DOCX 用 `jobsearch_cn.resume_extract` 提取）、文件大小和耗时。
- LaTeX（ctex）只按资料写进对比表，不出样张（用户没同意装 TinyTeX）。

## 10-29 暂停时的下一步（10-30 都已做完）

1. 运行 `python data/m3-0/scripts/resume.py` 和 `--long`，修脚本里的问题，看各做法的 PDF（用 Read 看页面）和检查结果。
2. 写 `docs/cn/m3-0-resume-prototypes.md`：对比表（中文排版、字体许可、安装成本 Windows/macOS、HR 接受度、校验、和 ADR-4 的关系）、推荐，附录放需要保留的脚本片段。
3. 把样张路径告诉用户，请用户打开看；用户选定后由规划者记进 D1。
4. 开 PR 前先给规划者发消息。

## 10-29 的未决问题（10-30 的结论见报告第 1 节和 4.2 节）

- DOCX 字体选微软雅黑（HR 电脑上通常有），PDF（B、C）选 Noto Sans SC（OFL）。两者字形不同，Word 和 PDF 看起来会略有差别。是否要求两份用同一款字体，等看完样张再提。
- 没有 Word 的电脑（macOS 或只有 WPS）上，做法 A 的 PDF 怎么出：LibreOffice 能替代，但用户没同意装，只能按资料写。
- 示例档案内容少，一页肯定放得下；"能不能放进一页"主要靠 `--long` 压力测试判断。

## 2026-10-30 继续（规划者换成 cn-de）

- 开工检查：工作树干净，没有未推送的提交；脚本的 SHA-256 和上面记的一致。#65 由规划者复审，不等它。
- 脚本先改了三处：求职意向写成"后端开发、大模型应用开发（实习）"（原来"实习"只挂在最后一个方向上）；项目没有角色时留空，不编"项目"二字；DOCX 加 `word/settings.xml`（`compatibilityMode` 15），否则 Word 以兼容模式打开。
- 看 PDF 页面：Read 工具渲染 PDF 要 `pdftoppm`，本机没有。改用 Windows 自带的 `Windows.Data.Pdf` 接口（PowerShell 脚本 `data/m3-0/scripts/render.ps1`）把每页渲染成 PNG，不用装东西。

### 跑出来的问题

1. **A：汉字其实是等线，不是微软雅黑。** PDF 的字体列表里汉字全在 DengXian 里，只有英文和数字是微软雅黑。让 Word 另存一份看它怎么理解：它把 `docDefaults` 里的东亚字体换成了主题字体 `minorEastAsia`（包里没有主题，就用中文版 Office 的默认主题，即等线）。写中文名"微软雅黑"或英文名都一样。把字体也写到 Normal 样式上就好了（中文名、英文名都行），三份字体子集都是微软雅黑。**教训：DOCX 的字体不能只写在 `docDefaults`；生成后要看导出 PDF 的字体列表。**
2. **B：用 Noto Sans SC 时，PDF 文本层有 16 个字是康熙部首。** 例如"大"存成 U+2F24"⼤"、"示"存成 U+2F70"⽰"，页面上一模一样，复制出来或按"示例理工大学"搜索就对不上。原因：本机的 Noto Sans SC 是可变字体（`NotoSansSC-VF.ttf`），Edge 把它嵌成了 81 个 Type 3 字体（矢量字形，没有字体名，PDF 390 KB），反查 cmap 生成 ToUnicode 时，同一个字形先查到了部首的码位。换成微软雅黑就是正常的 CID 字体，没有部首，104 KB。
   - `verify_pdf` 发现不了：它只做 NFC，pypdf 读出的部首原样保留，但它不检查；而 `pdftotext` 会把部首折回正常汉字，用它读反而看不出问题。M3-2 的检查要单独查 U+2E80–U+2FDF。
   - 同一份 PDF 用 `pdftotext -layout` 读，相邻两条要点的字会交错成一行（"G主P修A 课3.6程…"）。换微软雅黑后也没有了。
3. **C：嵌入的字体名叫 `NotoSansSC-Thin`，但页面粗细正常。** 这是字体文件自己的 PostScript 名（name 表 ID 6 就是 `NotoSansSC-Thin`），Typst 0.15 实际按常规和粗体排的。另外 Noto 的"•"和"·"共用一个字形，文本层里列表圆点都记成了"·"；换微软雅黑没有这个问题。第一次编译 6 秒，之后每次约 0.15 秒（原因没查）。
4. **压力测试**：实习和项目放大 3 倍时五份都还是一页，改成 5 倍。5 倍时 A（Word）2 页，B、C 都是 1 页，原因是 A 的行距（1.15 倍单倍行距，雅黑约合 15.2 pt）比 B、C 的 14.5 pt 松。A 的第 2 页开头是一条孤立的项目要点，标题留在第 1 页底部，要加"与下段同页"。
   - **B、C 的 DOCX 就是 A 的那份**：同样的内容，PDF 1 页，DOCX 在 Word 里 2 页。B、C 的 Word 版和 PDF 由两套引擎排版，页数可能不一致，没有 Word（或 LibreOffice）就量不出 DOCX 的页数。
- 本机的 Noto Sans SC 是系统字体：注册在 HKLM，文件和微软雅黑一样由 Windows 组件仓库硬链接，版本 2.04，OFL，`fsType` 0。
- 做法 B、C 各加了一个微软雅黑的变体（`B-edge-yahei`、`C-typst-yahei`），也用来回答"Word 和 PDF 用不用同一款字体"。

### 拉齐三种做法的版式

不拉齐的话，用户比的是我写的三份模板，不是三种做法。

- 统一：A4、页边距 1.5 cm、正文 10 pt、行距 14.5 pt、标题 11.5 pt、姓名 18 pt。Typst 原来的行距（`leading` 0.55em，从大写字母高度量起）太挤，改成每行固定 1em 加 0.45em 行间距；列表圆点放大。
- **Word 的"单倍行距"对雅黑特别松**：按页面量，10 pt 雅黑每行约 17 pt（1.72 em），而字体自己标的是 1.32 em（winAscent + winDescent），中文用户常说的"微软雅黑行距大"就是这个。用倍数怎么调都和 B、C 对不齐，改成**固定值** 14.5 pt（姓名、标题另设）后，A 和 B 的页面几乎一样：压力测试里两者的第 2 页都从"专业技能"开始。
- 分页：三种做法都改成条目不拆开、标题不落在页尾。Word 用"与下段同页"（`keepNext`，一直加到条目的倒数第二条要点），CSS 用 `break-inside: avoid` 和 `break-after: avoid`，Typst 用 `block(breakable: false)` 和 `sticky: true`。
- 压力测试放大到 7 倍，五份都超出一页，分页处都没有拆开条目。
- 耗时（同一台机器，多次运行的范围）：A 4–6 秒，有一次 27 秒（原因没查）；B 约 1 秒；C 约 0.12 秒。跑完后没有残留的 Word、Edge 或 Typst 进程。
- 样张整理到 `data/m3-0/samples/`（被 git 忽略），文件名写明做法；三种做法的 Word 版是同一份。脚本 SHA-256 前 16 位：`resume.py` `a2a3a6724063d3ad`，`render.ps1` `6fb36ceda0f6ab1c`。
- 样张路径和简单对比已发给规划者（我倾向 C）。规划者请用户看样张，并请 Codex A 做 V16（独立核对文本层，只读 `data/m3-0/samples/`）。这批样张从此不再重新生成；各文件的 SHA-256 记在报告附录里。

### 用户的新意见：借用开源简历项目（2026-10-30）

用户看了样张："三种简历肉眼基本没区别……可以找一下 github 上开源自动生成简历的项目融合或者借鉴一下，不需要完全自己搞"。三份看着一样，是因为版式拉齐了，规划者已向用户解释。规划者据此给 M3-0 加了三步：

1. 调研 GitHub 上开源的简历生成项目和模板，重点看对中文友好的，按工具链（Typst、LaTeX、HTML/CSS、DOCX）分类。每个都看许可（本仓库是 MIT：复制进仓库的只能是 MIT、BSD、Apache 这类宽松许可，并保留版权声明；GPL、AGPL 的只能当外部工具调用）、中文排版、Word 版怎么配套、PDF 文本层、输入格式和 `profile.json` 的映射、维护情况、安装成本。
2. 挑 2–3 个，用示例档案各出一份样张（能出 Word 的也出），放在被忽略的目录。下载模板试用可以直接做；装新软件或 Python 包（包括 pip）要先问用户本人。
3. 报告的推荐改成"生成工具 + 借用的模板"，写清我们自己写哪些部分、借用的部分怎么放进仓库、许可声明放在哪。原来三种做法的对比保留，作为选工具链的依据。

新样张放 `data/m3-0/samples-oss/`，不碰 V16 在核对的 `samples/`。

### 调研和第二轮样张（进行中）

- 用 `gh` 查仓库的许可、最近提交和 Issue（网页抓取这会儿不稳定）。Typst Universe 共 1719 个包，用 git tree 接口取全表（目录接口截断在 1000 项），名字里带简历或中文特征的有几十个。
- 许可上要排除的：`OrangeX4/Chinese-Resume-in-Typst`（981 星）没有许可证；`NorthSecond/Auto_Typst_Resume_Template` 是 CC BY-NC；`JOYCEQL/magic-resume` 是 Apache-2.0 外加商业限制条款；`xitanggg/open-resume` 是 AGPL-3.0；`posquit0/Awesome-CV` 是 LPPL。
- 选了三个 MIT 的 Typst 模板出样张，都不用装软件。Typst 用 `--package-cache-path` 把包下到被忽略的 `data/m3-0/oss/packages/`，不写进 AppData：
  - **RenderCV 的 Typst 包**（`@preview/rendercv:0.3.0`）：不用 pip 装它的 Python 命令行，Typst 包可以直接用；6 个主题都是同一套参数换值。样张取 `classic` 和 `moderncv` 两个主题，参数从官方示例读出，只改 A4、中文字体、语言 `zh`、关掉图标和页脚。依赖 `fontawesome`（MIT）。
  - **habaneraa-one-page-resume-zh**：中文模板，宋体正文、黑体标题，`element-spaciness` 一个参数调整体间距。依赖的 `nerd-icons` 是 LGPL-3.0，借用时要去掉。
  - **resume-ng**：中文、高密度，受 hijiangtao/resume 启发，不用图标。`project()` 里字体写死为 `Noto Serif CJK SC`，本机同一款设计叫 `Noto Serif SC`，样张把它的四条设置照抄到主文件，只换字体名。
- 字体用各模板原本的设计：思源黑体、思源宋体和 Noto Sans SC、Noto Serif SC 是同一款字，Windows 自带。联系方式按纯文本放，不用图标字体（图标是私用区字符，会进文本层）。
- 结果（脚本 `data/m3-0/scripts/oss.py`）：四份都是一页，文本层完整，没有部首和私用区字符。
  - resume-ng 的日期范围是数学模式的 en dash，`verify_pdf --ascii-dates` 报了 4 处；项目没有角色时标题后多一个"|"；压力测试里跨页的第一个条目丢了右侧日期（日期用 `place` 放，落在了上一页）。
  - habaneraa 在压力测试里"荣誉与证书"的标题留在第 1 页底，横线和内容在第 2 页。
  - RenderCV 两个主题跨页都正常：条目不拆开，标题跟着内容。
- habaneraa 的一键压页：实习和项目放大 4 倍、5 倍时，二分法分别找到 1.281、1.051，刚好一页，每次编译约 0.1 秒，共试 8 次；放大 7 倍时调到最紧的 0.8 也是 2 页。

### 报告

- 写了 `docs/cn/m3-0-resume-prototypes.md`：第一轮三种做法的对比表和问题、第二轮的候选项目和许可表（包括排除的项目和理由）、三个模板的样张和检查结果、借用时要改的地方、推荐方案的分工和许可声明的放法、M3-2 的检查清单、和 ADR-4 的关系；附录是样张的 SHA-256 和要保留的代码片段。文档索引里加了一行。
- 推荐：PDF 用 Typst 生成，版式借用 RenderCV 的 Typst 包，备选 habaneraa；Word 版仍用标准库写。取舍写明：最看重 Word 版和 PDF 完全一致，就选做法 A。
- 规划者取消了 V16（Codex 限流），样张的文本层由规划者审 PR 时核对。LaTeX 先不出样张。

### 下一步

1. 用户已选定 H，结论已补进报告 1.1。规划者记进 D1，细化 M3-1 以后的任务（包括照片）。
2. 用户想看 LaTeX 版时，先用 AskUserQuestion 问装不装 TinyTeX。

### 用户的选择（2026-10-30）

- 规划者转告：用户选定 **H（habaneraa 中文一页）**，原话（答规划者的第 01 项）："我选择H，符合审美后续方便增加面试者头像。"
- 补进报告 1.1：PDF 用 habaneraa 模板经 Typst 生成，Word 版用标准库写、版式向它靠；借用时去掉 `nerd-icons`（LGPL-3.0），修跨页时标题落在页尾的问题；模板放 `jobsearch_cn/resume_templates/habaneraa/`（规划者同意）；Word 版字体留给 M3-2。
- 照片：查了模板源码，`resume-header` 的 `profile-image` 参数把照片放在页头右上角，按页头高度缩放，不传就不显示。照片放 `data/profile/`，不进 git，生成时由用户决定放不放；Typst 只读得到 `--root` 内的文件，Word 版要另加图片部件。进 M3 的哪一项由规划者定。
- 原来的推荐（RenderCV）改成报告 1.2"选定前的推荐"，保留理由。
