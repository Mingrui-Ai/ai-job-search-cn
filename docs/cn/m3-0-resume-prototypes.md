# M3-0 · 简历生成方式的原型对比

2026-10-29 至 10-30，Claude C。只用示例档案 `tests/fixtures/cn/profile/tech`。生成的 Word、PDF 和原型脚本都放在被 git 忽略的 `data/m3-0/` 下，不提交。

本机原有 Word（Office 16）、Edge、pypdf 6.21 和 Git 自带的 `pdftotext`。按用户同意，只另装了 Typst 0.15.1 便携版（`D:\05_Software\typst-0.15.1\`）。第二轮借用的开源模板由 Typst 下载到 `data/m3-0/oss/packages/`。

结论由用户选定，规划者记进 D1。过程记录见[工作记录](worklog/2026-10-29-m3-0-prototypes.md)。

## 1. 结论

**推荐：PDF 用 Typst 生成，版式借用 RenderCV 的 Typst 包；Word 版仍由我们用标准库生成，版式向它靠。**

- **Typst**（第一轮的做法 C）：
  - 文本层正确，中英文间距和中文标点挤压处理得最好；
  - 一次编译约 0.1 秒，自动压进一页可以反复试；
  - Windows、macOS 上都只是一个可执行文件，不要管理员权限；用命令行调用，不碰 Word 和浏览器。
- **RenderCV**：
  - MIT 许可，1.79 万星，最近一次推送在 2026-10-30；
  - 同一个包换参数就有 6 个主题，以后换样式不用改代码；
  - 跨页表现最稳；
  - 只用它的 Typst 包，不装它的 Python 命令行（那个要 Python 3.12 以上和 pydantic、Jinja2 等第三方库）。
- **备选 habaneraa**：中文味最足，还有"调一个参数压满一页"的设计。用户更喜欢它的样子就借它，但要去掉它依赖的 LGPL 图标包，并修跨页时章节标题孤立在页尾的问题。
- **取舍**：B、C 和 LaTeX 的 Word 版和 PDF 由两套引擎排版，页数可能不同；没有 Word 或 LibreOffice 时，量不出 Word 版的页数。**如果最看重"Word 版和 PDF 完全一致"，就选做法 A**（标准库写 DOCX，用 Word 导出 PDF）：两者是同一次排版。代价是只能在装了 Word 的 Windows 上生成，每次 4–6 秒，开源的 Typst 模板也用不上。
- **不推荐 B**（Edge 打印）：文本层对不对取决于字体，用系统自带的 Noto Sans SC 时有 16 个字成了康熙部首。
- **不推荐 LaTeX**：安装大、编译慢，长处 Typst 都有。两个流行的中文 LaTeX 模板还附带不能再分发的 Adobe 中文字体。

## 2. 第一轮：三种同时出 Word 和 PDF 的做法

| 做法 | Word 版 | PDF | 样张（`data/m3-0/samples/`） |
| --- | --- | --- | --- |
| A | 标准库写 DOCX | 本机 Word 导出（PowerShell 调 COM） | `A-Word导出-微软雅黑.pdf` |
| B | 同 A | HTML + CSS，Edge 无界面模式打印 | `B-Edge打印-微软雅黑.pdf`；反例 `B-Edge打印-NotoSansSC-文本层有康熙部首.pdf` |
| C | 同 A | Typst 读 JSON 编译 | `C-Typst-微软雅黑.pdf`、`C-Typst-NotoSansSC.pdf` |
| LaTeX（ctex） | 同 A | XeLaTeX | 没出样张：用户没同意装 TinyTeX |

- 三种做法的 Word 版是同一份：`Word版-三种做法共用同一份.docx`。
- 版式统一为 A4、边距 1.5 cm、正文 10 pt、行距 14.5 pt、标题 11.5 pt、姓名 18 pt。不拉齐的话，比的是三份模板，不是三种做法。用户看了觉得"肉眼基本没区别"，原因就在这里。
- 压力测试把实习和项目各放大 7 倍（放大 3 倍、5 倍时都还在一页内），样张在 `压力测试-实习和项目放大7倍/`。

### 2.1 对比表

LaTeX 一列只按资料写，没有实测。

| | A：Word 导出 | B：Edge 打印 | C：Typst | LaTeX（资料） |
| --- | --- | --- | --- | --- |
| 中文排版 | Word 自动在中英文之间加空隙；标点不挤压 | 不加空隙，标点不挤压 | 自动加空隙，相邻中文标点挤压，最接近专业排版 | ctex 成熟 |
| 字体与许可 | 微软雅黑随 Windows 授权，`fsType` 8 允许嵌入；macOS 默认没有 | 雅黑正常；Noto Sans SC（OFL）是可变字体，被嵌成 Type 3 | 雅黑、Noto 都正常嵌入 | ctex 在 Windows 上默认用系统的宋体、黑体，其他系统默认用 Fandol（随 TeX 发行） |
| 页数和压页 | 要让 Word 排一次才知道页数，每次 4–6 秒 | 每次约 1 秒 | 每次约 0.12 秒；理论上也能在 Typst 里用 `measure` 一次算好（没试） | 每次数秒 |
| 跨页 | 都能做到条目不拆开、标题不落页尾：Word 用 `keepNext`，CSS 用 `break-inside`，Typst 用 `breakable: false` 和 `sticky` | 同左 | 同左 | 同左 |
| 安装：Windows | 要 Microsoft Word（付费），本机已有 | Edge 系统自带 | 官方压缩包 22.5 MB，解压后 52.5 MB，不要管理员权限 | TinyTeX 23–164 MB，另加 ctex 等宏包（估计几十 MB），装在用户目录 |
| 安装：macOS | 没有 COM：要么写 AppleScript 驱动 Word for Mac，要么装 LibreOffice（约 300 MB 以上，估计），都没测 | 要装 Chrome 或 Edge | 官方有 Apple 芯片版（14.4 MB）和 Intel 版（15.6 MB），也可以 `brew install typst` | TinyTeX 或 MacTeX |
| Word 版 | 就是排出 PDF 的那份，页数和样子一致 | 另外生成，由 Word 或 WPS 自己排版；页数要靠 Word 或 LibreOffice 量 | 同 B | 同 B |
| PDF 文本层 | 正确 | 用 Noto 时 16 个字成了康熙部首；用雅黑正确 | 正确 | — |
| 和 ADR-4 | `subprocess` 调 PowerShell 和 COM | `subprocess` 调 Edge；浏览器可能有后台联网（没抓包） | `subprocess` 调 Typst；不导入 `@preview` 包就完全离线 | `subprocess` 调 XeLaTeX |

耗时是同一台机器上多次运行的范围：A 有一次用了 27 秒，C 第一次运行用了 6 秒，原因都没查。

### 2.2 实测中发现的问题

1. **Word 把汉字换成了等线。** 东亚字体只写在 `docDefaults` 时，Word 打开后换成了主题字体 `minorEastAsia`。包里没有主题，就用中文版 Office 的默认主题，也就是等线。用 Word 另存一份就能看到这个替换。字体写成中文名"微软雅黑"或英文名都一样，写到 Normal 样式上才好。肉眼几乎看不出来，要看导出 PDF 的字体列表。
2. **Word 的"单倍行距"对微软雅黑特别松。** 按页面量，10 pt 雅黑每行约 17 pt（1.72 em），而字体自己标的是 1.32 em。按倍数调怎么也和别的做法对不齐，改成固定值 14.5 pt 才行。
3. **Edge 加可变字体，文本层出错。** 本机的 Noto Sans SC 是可变字体（`NotoSansSC-VF.ttf`），Edge 把它嵌成了 81 个 Type 3 字体：没有字体名，PDF 有 390 KB（用雅黑是 104 KB）。生成 ToUnicode 时，同一个字形先对上了部首的码位，例如"大"存成 U+2F24"⼤"，"示"存成 U+2F70"⽰"。页面上一模一样，复制出来，或者按"示例理工大学"搜索，就对不上。
   - `tools/verify_pdf.py` 查不出这个问题：它只做 NFC，pypdf 读出的部首原样保留，但它不检查。改用 `pdftotext` 读也看不出，因为它会把部首折回正常汉字。
   - 同一份 PDF 用 `pdftotext -layout` 读，相邻两条要点的字会交错成一行。
4. **Typst 加 Noto 的两个小问题。** 嵌入的字体名显示为 `NotoSansSC-Thin`，这是字体文件里的 PostScript 名，实际粗细正常。另外"•"和"·"在 Noto 里共用一个字形，文本层里的列表圆点都记成了"·"。换成雅黑就没有这两个问题。
5. **B、C 的 Word 版和 PDF 页数可能不同。** 拉齐行距之前，放大 5 倍的内容 PDF 是 1 页，同一份 DOCX 在 Word 里是 2 页。
6. **分页。** 压力测试里，最初 Word 版的一条项目要点被分到第 2 页，标题留在第 1 页底。三种做法加上上面那几条设置后，都在条目之间分页。

## 3. 第二轮：借用开源简历模板

用户看完第一轮的样张："三种简历肉眼基本没区别……我感觉可以找一下 github 上开源自动生成简历的项目融合或者借鉴一下，不需要完全自己搞"。这一轮比的是样子。

### 3.1 调研方法

2026-10-30 用 `gh` 查各仓库的许可证、星数、最近推送和 Issue，按"typst 简历""中文简历 latex""json resume theme"等关键词搜索。Typst 官方包仓库 Typst Universe 共 1719 个包，用 git tree 接口取全表（目录接口最多只返回 1000 项），名字里带简历或中文特征的有几十个。逐个看了其中 15 个的 `typst.toml`，重点几个看了 README 和源码。

许可按规划者的要求判断：本仓库是 MIT，复制进来的模板或代码只能是 MIT、BSD、Apache 这类宽松许可，并保留原作者的版权声明；GPL、AGPL 的只能当外部工具调用。

### 3.2 候选项目

星数和最近推送日期（GitHub 的 `pushed_at`）是 2026-10-30 查的。

| 项目 | 工具链 | 许可 | 星数 / 最近推送 | 中文 | 处理 |
| --- | --- | --- | --- | --- | --- |
| [RenderCV](https://github.com/rendercv/rendercv)（Typst 包 `@preview/rendercv:0.3.0`） | Typst；另有 Python 命令行（YAML 转 Typst） | MIT | 17864 / 2026-10-30 | 没有中文专门设计；字体、语言都能设 | 出样张 R1、R2 |
| [habaneraa-one-page-resume-zh](https://github.com/habaneraa/typst-resume-one-page) | Typst | MIT；依赖的 `nerd-icons` 是 LGPL-3.0 | 42 / 2026-08-11 | 中文专门设计 | 出样张 H |
| [resume-ng](https://github.com/fky2015/resume-ng-typst) | Typst | MIT | 110 / 2024-10-07 | 中文；仿 hijiangtao/resume | 出样张 N |
| [golixp-resume-zh-cn](https://github.com/golixp/typst-resume-zh-cn) | Typst | MIT | 7 / 2026-05-16 | 中文专门设计 | 没出样张：图标是布局的一部分，用户少 |
| [chicv](https://github.com/skyzh/chicv) | Typst | CC0-1.0（Typst Universe 上标 MIT） | 729 / 2025-04-06 | 英文为主；中文分支 chicv-cn 没有许可证 | 没出样张 |
| [brilliant-CV](https://github.com/yunanwg/brilliant-CV) | Typst | Apache-2.0 | 846 / 2026-10-29 | 自述支持多语言，中文效果没核实 | 没出样张 |
| [modern-cv](https://github.com/ptsouchlos/modern-cv) | Typst | MIT（GitHub 显示 NOASSERTION，文件内容是 MIT） | 635 / 2026-09-01 | 仿 Awesome-CV，英文为主 | 没出样张 |
| [Chinese-Resume-in-Typst](https://github.com/OrangeX4/Chinese-Resume-in-Typst) | Typst | **没有许可证** | 981 / 2025-03-18 | 中文 | **排除**：没有许可就不能复制 |
| [Auto_Typst_Resume_Template](https://github.com/NorthSecond/Auto_Typst_Resume_Template) | Typst | **CC BY-NC 4.0** | 201 / 2026-09-27 | 中英双语 | **排除**：禁止商用，和 MIT 不兼容 |
| [billryan/resume](https://github.com/billryan/resume) | XeLaTeX | MIT；中文分支附带的 Adobe 中文字体不在许可内 | 11541 / 2024-03-15 | 中文分支 `zh_CN` | 只调研：要装 TeX；字体不能复制 |
| [hijiangtao/resume](https://github.com/hijiangtao/resume) | XeLaTeX | MIT；同样附带 Adobe 中文字体 | 3729 / 2024-09-04 | 中文 | 只调研 |
| [Awesome-CV](https://github.com/posquit0/Awesome-CV) | XeLaTeX | **LPPL-1.3c** | 28835 / 2026-10-21 | 英文为主 | **排除**：不在宽松许可清单内 |
| [resumed](https://github.com/rbardini/resumed) + JSON Resume 主题（如 [even](https://github.com/rbardini/jsonresume-theme-even)） | Node.js，HTML 主题，浏览器打印 | MIT | 551 / 2026-10-19 | 没查中文效果 | 只调研：要 npm 安装；浏览器打印有第一轮 B 的文本层风险 |
| [Reactive Resume](https://github.com/reactive-resume/reactive-resume) | Web 应用，要自建服务 | MIT | 45083 / 2026-10-29 | 没查 | 不采用：不是本地命令行工具 |
| [OpenResume](https://github.com/xitanggg/open-resume) | Web 应用 | **AGPL-3.0** | 8957 / 2024-10-29 | — | **排除** |
| [Magic Resume](https://github.com/JOYCEQL/magic-resume) | Web 应用 | **Apache-2.0 加商业限制条款** | 11282 / 2026-10-29 | 中文 | **排除**：附加条款限制商用 |
| [visiky/resume](https://github.com/visiky/resume) | Web 应用 | MIT | 3213 / 2023-08-30 | 中文 | 不采用：Web 应用，2023-08 之后没有推送 |

Word：这次没有找到可借用的开源中文 Word 简历模板。Python 生成 DOCX 的库有 python-docx（MIT）、docxtpl（LGPL-2.1），都是第三方库，和 ADR-4 冲突。Word 版继续用我们的标准库写法。

### 3.3 样张

第二轮样张放在 `data/m3-0/samples-oss/`，脚本是 `data/m3-0/scripts/oss.py`。

| 样张 | 模板 | 字体 | 说明 |
| --- | --- | --- | --- |
| `R1-RenderCV-classic主题-NotoSansSC.pdf` | RenderCV `classic` 主题 | Noto Sans SC | 参数取官方示例，只改 A4、字体、语言 `zh`、关图标和页脚 |
| `R2-RenderCV-moderncv主题-NotoSansSC.pdf` | RenderCV `moderncv` 主题 | Noto Sans SC | 左侧日期栏，和上游英文简历的 moderncv 风格同源 |
| `H-habaneraa-中文一页-NotoSerifSC.pdf` | habaneraa | Noto Serif SC 正文，Noto Sans SC 标题 | 间距参数自动取到上限 1.5，示例内容仍只占约 70% 页面 |
| `N-resume-ng-中文高密度-NotoSerifSC.pdf` | resume-ng | Noto Serif SC | 页边距 1 cm，黑白、紧凑 |
| `一键压页演示-实习和项目放大5倍/H-habaneraa-自动调间距到1.051.pdf` | habaneraa | 同 H | 内容超过一页时，脚本自动把间距调到 1.051，刚好一页 |
| `压力测试-实习和项目放大7倍/` | 以上四份 | — | 看跨页表现 |

- **字体**：用各模板原本设计的字体。模板要的思源黑体、思源宋体，和 Windows 自带的 Noto Sans SC、Noto Serif SC 是同一款字，所以没有下载字体。
- **联系方式**：按纯文本排，没有用图标字体。图标是私用区字符，会进入 PDF 文本层；habaneraa 的图标包又是 LGPL。
- **下载**：三个模板都没有装软件。Typst 用 `--package-cache-path` 把包下载到被忽略的目录，没有写进 AppData。
- **Word 版**：三个模板都不能出 Word。

### 3.4 检查结果

- 四份都是一页。文本层里每个字段都逐字找得到，没有康熙部首，没有私用区字符。
- **resume-ng**：`verify_pdf` 的 ASCII 日期检查报了 4 处，它的日期范围用的是数学模式的 en dash（`$dash.en$`）。
- **压力测试**：
  - RenderCV 两个主题都在条目之间分页，章节标题跟着内容；
  - habaneraa 把"荣誉与证书"的标题留在了第 1 页底，横线和内容在第 2 页；
  - resume-ng 第 2 页的第一个条目丢了右侧的日期：日期用 `place` 放，落到了上一页。
- **一键压页**（habaneraa 的 `element-spaciness`，脚本在 0.8–1.5 之间二分查找）：
  - 实习和项目放大 4 倍时找到 1.281，放大 5 倍时找到 1.051，都刚好一页；每次编译约 0.1 秒，共试 8 次；
  - 放大 7 倍时调到最紧的 0.8 也是 2 页，这时只能删内容。
  - RenderCV 没有单一的间距参数，但可以照这个办法同时缩放它的几个间距参数。

### 3.5 借用时要改的地方

MIT 许可允许修改，改动要写进随附的说明（见 4.2）。

- **RenderCV**：
  - `lib.typ` 第一行导入 `@preview/fontawesome`（MIT）。我们不用图标，可以去掉这个导入，把 `fa-icon` 换成空函数；要保留图标，就把 fontawesome 包也一起放进仓库。
  - `moderncv` 主题里，技能、荣誉这类纯文本小节没有对齐到正文栏，要调。
- **habaneraa**：
  - 去掉 `nerd-icons`（LGPL-3.0）的导入和页头的图标调用，联系方式改成纯文本；
  - 章节标题要和后面的内容连在一起（Typst 的 `sticky`），避免孤立在页尾；
  - 默认字体名是"Noto Sans CJK SC""Source Han Sans SC"，本机没有这两个名字，要通过参数改成本机的字体。
- **resume-ng**：
  - 日期范围的 en dash 改成 ASCII 连字符（`resume-date`），否则过不了 ATS 日期检查；
  - 没有角色时标题后面多一个"|"：`array-to-str` 要先去掉空字段；
  - 跨页丢日期：`resume-item` 用 `place` 放日期，要改成 `grid` 或 `h(1fr)`；
  - `project()` 里字体写死为"Noto Serif CJK SC"，要改成参数。

## 4. 推荐方案：哪些借，哪些自己写

### 4.1 分工

**借用**：选定模板的 Typst 文件（RenderCV 是一个 28 KB 的 `lib.typ`），放进仓库，按 3.5 做少量修改。

**自己写**：

1. 从档案生成简历内容：选哪些经历和要点，每一条都带档案条目 id，供 M3-1 的 `material validate` 追溯；
2. 把内容转成 JSON，再写几十行的 Typst 主文件调用模板函数。数据从 JSON 读，不在 Python 里拼 Typst 标记，所以不用处理转义；
3. 用 `subprocess` 调 Typst 编译，自动压进一页：按 3.4 的办法二分查找间距，还放不下就提示删内容；
4. 检查，见第 5 节；
5. 用标准库写 DOCX：字号、颜色、标题样式向选定的模板靠，固定值行距，字体写在样式上；
6. 本机有 Word 时，可选地用 Word 量 Word 版的页数。

### 4.2 放在哪里，许可声明放在哪里

- **位置**：建议作为包数据放在 `jobsearch_cn/` 下，例如 `jobsearch_cn/resume_templates/rendercv/`，和 `skills.json` 一样随包走。Typst 文件不是 Python 代码，不违反 ADR-4。上游的 `templates/` 是 `/add-template` 管理的用户模板，带占位符，和这里的用法不同，不建议混放。最终由规划者定。
- **许可**：每个借来的包保留原 `LICENSE` 文件，同目录加一份说明，写清来源网址、版本、版权人和本地改动。仓库层面再列一张第三方组件清单（放在 README 的"许可证"一节，或单独一个文档）。
- **离线**：模板改成相对路径导入，不在运行时用 `@preview/...`，否则 Typst 会联网下载。
- **字体**：PDF 会嵌入字体，HR 那边不用装。Word 版的字体还要定：微软雅黑 HR 的 Windows 电脑上都有；Noto Sans SC 和模板设计一致，本机的 Windows 自带，但旧版 Windows 上不一定有。这在 M3-2 里定。

## 5. M3-2 的检查清单

- **PDF**：
  - 用 `tools/verify_pdf.py` 查页数为 1、文本层、日期用 ASCII 连字符；
  - 文本层里没有康熙部首和部首补充区字符（U+2E80–U+2FDF）。要用 pypdf 读，`pdftotext` 会把它们折回正常汉字；
  - 没有私用区字符（U+E000–U+F8FF），也就是没有图标字体；
  - 字体列表里没有 Type 3，字体族是预期的那几个。字体可能放在表单 XObject 里，要递归找；
  - 内容里的每个字段都能在文本层里逐字找到（忽略空白）。
- **Word 版**：
  - `jobsearch_cn.resume_extract` 读出的文字里有每个字段；
  - 包结构里有 `settings.xml`（`compatibilityMode` 15），字体写在样式上；
  - 本机有 Word 时，可选地导出一次 PDF，查页数和字体。
- **Word 版和 PDF 一致**：按字段比，不比全文。列表圆点在不同引擎里不一样：Edge 把圆点画成图形，Typst 加 Noto 时会把圆点记成"·"。

## 6. 和 ADR-4 的关系

- `jobsearch_cn` 仍只用标准库：DOCX 用 `zipfile` 加 XML 字符串写，内容转 JSON，用 `subprocess` 调 Typst，和 `resume_extract` 调 `pdftotext` 一样。Typst 的路径从配置或 PATH 找；找不到就报清楚的错误，并说明怎么装。
- 运行时不联网：模板放在仓库里，用相对路径导入。
- 测试：
  - DOCX 写法和数据转换用纯 Python 测；
  - 要调 Typst 的集成测试，照现有 `pdftotext` 测试的写法，用 `skipUnless(装了 Typst)`；
  - CI 要跑这些测试时，可以在工作流里下载固定版本的 Typst 并核对 SHA-256。这是 CI 的事，不影响运行时离线。

## 7. 遗留问题

- 本机没有 WPS 和 LibreOffice，Word 版在 WPS 里的样子和页数没测；macOS 上什么都没测，表里 macOS 的内容都按资料写。
- Noto Sans SC、Noto Serif SC 在本机是系统字体：注册在 HKLM，文件和微软雅黑一样由 Windows 组件仓库硬链接。旧版 Windows 上不一定有，那样的电脑生成 PDF 要改用微软雅黑。
- 示例档案内容少；压力测试是把同一段经历重复多次，不是真实简历。
- LaTeX 没出样张。用户想看的话，再用 AskUserQuestion 问装不装 TinyTeX。
- 用户选定模板后，把结论补进本报告和 D1。

## 附录 A：样张和脚本的 SHA-256

前 16 位，文件大小单位是字节。

第一轮，`data/m3-0/samples/`：

| SHA-256 | 大小 | 文件 |
| --- | --- | --- |
| `0b4c6579d433dbfc` | 100719 | `A-Word导出-微软雅黑.pdf` |
| `e324489efca2ae06` | 399626 | `B-Edge打印-NotoSansSC-文本层有康熙部首.pdf` |
| `a3a09a459f515810` | 106960 | `B-Edge打印-微软雅黑.pdf` |
| `c79410d783145922` | 49741 | `C-Typst-NotoSansSC.pdf` |
| `895774956670ea19` | 95483 | `C-Typst-微软雅黑.pdf` |
| `105167cce07eeb1e` | 3224 | `Word版-三种做法共用同一份.docx` |
| `86d8c828aa8a5fe6` | 110399 | `压力测试-实习和项目放大7倍/A-Word导出-微软雅黑.pdf` |
| `087fb96ccc3e7426` | 415900 | `压力测试-实习和项目放大7倍/B-Edge打印-NotoSansSC-文本层有康熙部首.pdf` |
| `a3d1096c4032acb4` | 122689 | `压力测试-实习和项目放大7倍/B-Edge打印-微软雅黑.pdf` |
| `db530d7256fe5449` | 68232 | `压力测试-实习和项目放大7倍/C-Typst-NotoSansSC.pdf` |
| `8d9c34b0e6763ae0` | 113974 | `压力测试-实习和项目放大7倍/C-Typst-微软雅黑.pdf` |
| `5e0abecd4cce9878` | 3326 | `压力测试-实习和项目放大7倍/Word版-三种做法共用同一份.docx` |

第二轮，`data/m3-0/samples-oss/`：

| SHA-256 | 大小 | 文件 |
| --- | --- | --- |
| `23c896abc7f75d03` | 52445 | `R1-RenderCV-classic主题-NotoSansSC.pdf` |
| `387f951cfca61278` | 53686 | `R2-RenderCV-moderncv主题-NotoSansSC.pdf` |
| `67dd4ee51f8b2c77` | 69223 | `H-habaneraa-中文一页-NotoSerifSC.pdf` |
| `04c20a772fde430b` | 63981 | `N-resume-ng-中文高密度-NotoSerifSC.pdf` |
| `41c9e3de736e93de` | 77256 | `一键压页演示-实习和项目放大5倍/H-habaneraa-自动调间距到1.051.pdf` |
| `a1ce899908b782d7` | 69960 | `压力测试-实习和项目放大7倍/R1-RenderCV-classic主题-NotoSansSC.pdf` |
| `cb3dffe662ae4dbd` | 71081 | `压力测试-实习和项目放大7倍/R2-RenderCV-moderncv主题-NotoSansSC.pdf` |
| `735fa8d547224990` | 81969 | `压力测试-实习和项目放大7倍/H-habaneraa-中文一页-NotoSerifSC.pdf` |
| `15610280d9b457e7` | 82157 | `压力测试-实习和项目放大7倍/N-resume-ng-中文高密度-NotoSerifSC.pdf` |

脚本（都在 `data/m3-0/scripts/`）：`resume.py` `a2a3a6724063d3ad`，`render.ps1` `6fb36ceda0f6ab1c`，`oss.py` `33e2befc063c5756`。Word 导出的 PDF 带时间戳，Typst 也会写入生成日期，所以重新运行后哈希会变。

## 附录 B：要保留的代码片段

原型脚本不进 `jobsearch_cn/`。下面是 M3-2 用得上的部分。

**DOCX 的字体、兼容模式和行距。** 字体除了写在 `docDefaults`，还要写在 Normal 样式上；行距用固定值：

```xml
<!-- word/styles.xml -->
<w:docDefaults>
  <w:rPrDefault><w:rPr>
    <w:rFonts w:ascii="Microsoft YaHei" w:hAnsi="Microsoft YaHei" w:eastAsia="微软雅黑" w:cs="Microsoft YaHei"/>
    <w:sz w:val="20"/><w:szCs w:val="20"/><w:lang w:val="en-US" w:eastAsia="zh-CN"/>
  </w:rPr></w:rPrDefault>
  <w:pPrDefault><w:pPr><w:spacing w:line="290" w:lineRule="exact"/></w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal">
  <w:name w:val="Normal"/>
  <w:rPr><w:rFonts w:ascii="Microsoft YaHei" w:hAnsi="Microsoft YaHei" w:eastAsia="微软雅黑" w:cs="Microsoft YaHei"/></w:rPr>
</w:style>

<!-- word/settings.xml：没有它，Word 以兼容模式打开 -->
<w:compat>
  <w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/>
</w:compat>
```

条目标题和除最后一条以外的要点都加 `<w:keepNext/>`，这样条目不会被分到两页。

**用 Word 导出 PDF**（PowerShell，参数是 DOCX 和 PDF 的绝对路径）。只在这个 Word 实例里没有其他文档时才退出，不关用户开着的文档：

```powershell
$ErrorActionPreference = 'Stop'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
  $doc = $word.Documents.Open($args[0], $false, $true)   # ConfirmConversions, ReadOnly
  $doc.ExportAsFixedFormat($args[1], 17)                  # wdExportFormatPDF
  $doc.Close($false)
} finally {
  if ($word.Documents.Count -eq 0) { $word.Quit() }
  [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($word)
}
```

**调用 Typst，二分查找间距压进一页**（以 habaneraa 为例，模板从 `sys.inputs` 读间距）：

```python
def compile_typ(folder, inputs=None):
    command = [TYPST, "compile", "--package-cache-path", PACKAGES, folder / "main.typ", folder / "resume.pdf"]
    for key, value in (inputs or {}).items():
        command[2:2] = ["--input", f"{key}={value}"]
    subprocess.run(command, check=True, capture_output=True, timeout=120)
    return page_count(folder / "resume.pdf")


def fit_spaciness(folder, low=0.8, high=1.5):
    if compile_typ(folder, {"spaciness": high}) == 1:
        return high
    if compile_typ(folder, {"spaciness": low}) > 1:
        return None  # 最紧也放不下：要删内容
    for _ in range(6):
        middle = round((low + high) / 2, 3)
        low, high = (middle, high) if compile_typ(folder, {"spaciness": middle}) == 1 else (low, middle)
    return low
```

**文本层检查**：

```python
def radicals(text):  # 康熙部首、部首补充：看着像"大""用""工"，码位不同，搜索对不上
    return sorted({ch for ch in text if 0x2E80 <= ord(ch) <= 0x2FDF})


def private_use(text):  # 图标字体
    return sorted({ch for ch in text if 0xE000 <= ord(ch) <= 0xF8FF})


def pdf_fonts(pdf):  # Chromium 把整页画在表单 XObject 里，字体要递归找
    names = set()

    def walk(resources, depth=0):
        resources = resources.get_object() if resources is not None else {}
        for ref in (resources.get("/Font") or {}).values():
            names.add(str(ref.get_object().get("/BaseFont")))
        for ref in (resources.get("/XObject") or {}).values():
            xobject = ref.get_object()
            if xobject.get("/Subtype") == "/Form" and depth < 5:
                walk(xobject.get("/Resources"), depth + 1)

    for page in PdfReader(str(pdf)).pages:
        walk(page.get("/Resources"))
    return sorted(names)
```

**不装 poppler 也能看 PDF 页面。** 用 Windows 自带的 `Windows.Data.Pdf` 把页面渲染成 PNG（`render.ps1` 的核心几行；`Await` 是把 WinRT 异步操作转成 .NET Task 的辅助函数）：

```powershell
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($pdfPath)) ([Windows.Storage.StorageFile])
$doc = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
$page = $doc.GetPage(0)
$options = New-Object Windows.Data.Pdf.PdfPageRenderOptions
$options.DestinationWidth = 1240   # A4 宽 1240 像素，约 150 dpi
AwaitAction ($page.RenderToStreamAsync($stream, $options))
```
