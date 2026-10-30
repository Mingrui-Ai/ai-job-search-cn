# 2026-10-29 · M3-0：简历生成方式的原型对比（进行中，Claude C）

> 进度记录（WIP）。规划者 2026-10-29 要求暂停保存进度，本条写明做到哪、下一步和未决问题。完成后改写成正式记录。

## 完成

- 读了路线图 §5 的 M3-0 任务单。
- 摸清本机已有的工具（只查看，没装）：Microsoft Word（Office16）、Edge、`pdftotext`（Git 自带的 mingw 版）、pypdf 6.21；**没有** LaTeX、Typst、LibreOffice、pandoc。
- 字体：Windows 自带 Noto Sans SC、Noto Serif SC（OFL）以及微软雅黑、宋体、黑体、等线。读了各字体 OS/2 表的 `fsType`：Noto 两款是 0（无限制），微软的四款是 8（允许嵌入、可编辑），都可以嵌进 PDF。
- 安装：用 AskUserQuestion 问过用户，**只同意装 Typst 便携版**（不装 TinyTeX、LibreOffice）。已装 Typst 0.15.1 官方 Windows 包到仓库外的 `D:\05_Software\typst-0.15.1\`（21 MB，解压即用，不需要管理员权限）；下载文件的 SHA-256 和 GitHub 发布页给出的 digest 一致（`19ce3551…6736`）。`typst fonts` 能看到 Noto Sans SC 等中文字体。
- 原型脚本写好了，**还没运行**：`data/m3-0/scripts/resume.py`（被 git 忽略，不进 `jobsearch_cn/`；本机文件 SHA-256 前 16 位 `3fb1fd3ee35c7117`）。它从示例档案 `tests/fixtures/cn/profile/tech` 生成同一份内容模型，再按三种做法各出一份 Word 和 PDF，输出到 `data/m3-0/out/`：
  - **A**：标准库写 DOCX（zipfile + WordprocessingML，字体微软雅黑），用本机 Word（PowerShell 调 COM 的 `ExportAsFixedFormat`）导出 PDF。脚本只在 Word 里没有其他打开的文档时才退出 Word，不会关掉用户开着的文档；
  - **B**：HTML + CSS，用 Edge 无界面模式打印成 PDF（临时的 `--user-data-dir`，不碰用户的 Edge 配置）；DOCX 用和 A 相同的写法；
  - **C**：Typst 读 JSON 数据编译成 PDF（字体 Noto Sans SC）；DOCX 同 A；
  - 另有 `--long`：把实习和项目各重复三遍的压力测试，看超出一页时各做法的表现。
  - 每种做法都检查：页数和文本层（`tools/verify_pdf.py`）、日期范围是否用 ASCII 连字符、PDF 里嵌入的字体、模型里每一行在 PDF 和 DOCX 里是否都能找到、DOCX 和 PDF 的文字是否一致（DOCX 用 `jobsearch_cn.resume_extract` 提取）、文件大小和耗时。
- LaTeX（ctex）只按资料写进对比表，不出样张（用户没同意装 TinyTeX）。

## 下一步

1. 运行 `python data/m3-0/scripts/resume.py` 和 `--long`，修脚本里的问题，看各做法的 PDF（用 Read 看页面）和检查结果。
2. 写 `docs/cn/m3-0-resume-prototypes.md`：对比表（中文排版、字体许可、安装成本 Windows/macOS、HR 接受度、校验、和 ADR-4 的关系）、推荐，附录放需要保留的脚本片段。
3. 把样张路径告诉用户，请用户打开看；用户选定后由规划者记进 D1。
4. 开 PR 前先给规划者发消息。

## 未决问题

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
3. **C：嵌入的字体名叫 `NotoSansSC-Thin`，但页面粗细正常。** 这是字体文件自己的 PostScript 名（name 表 ID 6 就是 `NotoSansSC-Thin`），Typst 0.15 实际按常规和粗体排的。另外 Noto 的"•"和"·"共用一个字形，文本层里列表圆点都记成了"·"；换微软雅黑没有这个问题。第一次编译 6 秒（建系统字体缓存），之后每次约 0.15 秒。
4. **压力测试**：实习和项目放大 3 倍时五份都还是一页，改成 5 倍。5 倍时 A（Word）2 页，B、C 都是 1 页，原因是 A 的行距（1.15 倍单倍行距，雅黑约合 15.2 pt）比 B、C 的 14.5 pt 松。A 的第 2 页开头是一条孤立的项目要点，标题留在第 1 页底部，要加"与下段同页"。
   - **B、C 的 DOCX 就是 A 的那份**：同样的内容，PDF 1 页，DOCX 在 Word 里 2 页。B、C 的 Word 版和 PDF 由两套引擎排版，页数可能不一致，没有 Word（或 LibreOffice）就量不出 DOCX 的页数。
- 本机的 Noto Sans SC 是系统字体：注册在 HKLM，文件和微软雅黑一样由 Windows 组件仓库硬链接，版本 2.04，OFL，`fsType` 0。
- 做法 B、C 各加了一个微软雅黑的变体（`B-edge-yahei`、`C-typst-yahei`），也用来回答"Word 和 PDF 用不用同一款字体"。
