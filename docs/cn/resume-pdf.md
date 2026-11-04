# 生成简历：PDF（Typst）和 Word 版

M3-2。`jobsearch_cn` 用外部程序 [Typst](https://github.com/typst/typst) 把简历编译成一页 PDF，同时用标准库写出一份内容相同的 Word 版（.docx）。Typst 不是 Python 依赖，用 subprocess 调用（ADR-4）。模板放在仓库里，生成时不联网。

`resume sample` 用固定的虚构内容试生成 PDF，验证 Typst 和字体装好了；`resume build` 从一份检查过的简历材料（[material.md](material.md)）生成 PDF 和 Word 版。

## 安装 Typst（便携版，不要管理员权限）

1. 到 [Typst 的发布页](https://github.com/typst/typst/releases)下载压缩包（已测试的版本是 0.15.1，至少要 0.13）：

   | 系统 | 压缩包 |
   | --- | --- |
   | Windows | `typst-x86_64-pc-windows-msvc.zip` |
   | macOS（Apple 芯片） | `typst-aarch64-apple-darwin.tar.xz` |
   | macOS（Intel） | `typst-x86_64-apple-darwin.tar.xz` |
   | Linux | `typst-x86_64-unknown-linux-musl.tar.xz` |

2. 解压到任意目录，里面的 `typst`（Windows 上是 `typst.exe`）就是整个程序。
3. 用下面三种办法之一告诉 `jobsearch_cn`，前面的优先：

   ```text
   python -m jobsearch_cn resume sample --typst D:\tools\typst\typst.exe    # 1. 命令行参数
   set JOBSEARCH_CN_TYPST=D:\tools\typst\typst.exe                          # 2. 环境变量（macOS、Linux 用 export）
   # 3. 把解压目录加进 PATH，命令里写 typst 就能找到
   ```

只测试过 Windows 11。macOS 和 Linux 的步骤是按 Typst 的发布包写的，还没有实际跑过。

## 字体

按顺序找第一款装了的字体，`typst fonts` 能列出这台电脑上有哪些：

| 用途 | 依次找 |
| --- | --- |
| 正文 | Noto Serif SC → Noto Serif CJK SC → Source Han Serif SC → 微软雅黑 |
| 标题 | Noto Sans SC → Noto Sans CJK SC → Source Han Sans SC → 微软雅黑 |

Windows 11 自带 Noto Serif SC 和 Noto Sans SC。一款都没有时，命令会报错，而不是生成满页方框的 PDF。

## 验证

```text
python -m jobsearch_cn resume sample
```

用固定的虚构内容（`jobsearch_cn/resume_templates/sample.json`，含一段个人简介）生成 `<数据目录>/resumes/sample.pdf` 并检查，输出 JSON：

| 字段 | 含义 |
| --- | --- |
| `pdf` | 生成的文件 |
| `spaciness` | 用的间距参数 |
| `fonts` | 用的字体 |
| `problems` | 检查发现的问题；空列表表示都通过 |

有问题时退出码是 1。检查读文本层要装 `pypdf` 或 Poppler 的 `pdftotext`，两个都没有时，`problems` 里会写明。

## 从材料生成：`resume build`

```text
python -m jobsearch_cn resume build data/materials/<岗位id>/resume-1.json [--profile <档案>] [--typst <路径>] [--data-dir <目录>]
```

1. 先像 `material validate` 一样检查材料（档案要先通过 `profile validate`；简介引了 `notes.md` 时，读档案同目录的 `notes.md`）。不通过时退出码 1，错误写在标准错误里，什么也不写。
2. 按材料引用的条目从档案取出姓名、学校、日期等，排成简历内容（规则见 [material.md 第 5 节](material.md#5-渲染成简历)）。
3. 写 `<数据目录>/resumes/<岗位id>/resume-<n>.pdf` 和 `resume-<n>.docx`，`n` 和材料文件名里的一样，所以材料文件必须叫 `resume-<n>.json`。重新生成会替换旧文件；先写临时文件再改名，中途失败时旧文件还在。输出位置是链接时拒绝，不通过链接写到别处。PDF 放不进一页时报错，两份都不写。建不了文件夹、写不了文件时（权限不够、磁盘满、沙盒不让写系统临时目录），标准错误输出 `{"error": …}`，退出码 1：只写出错的文件名和系统给的原因，不带 traceback 和本机路径（V24 P3-1）。这时不写说明文件。
4. 检查两份：PDF 照"检查什么"一节；Word 版要能读出内容里的每个字段，而且除了项目符号"•"和标签后的"："，没有内容以外的文字。个人简介的标题和正文也是字段，两份都要有。最后把两份全文按顺序直接对照：只允许空白（换行、制表符、空格）不同，以及 PDF 在每个有副标题的条目里多一个" · "（模板用它隔开名称和副标题，Word 版用制表位）；别的不同都算问题，报出从哪里开始不同。

输出 JSON：

| 字段 | 含义 |
| --- | --- |
| `pdf`、`docx` | 生成的两个文件 |
| `spaciness`、`fonts` | PDF 用的间距参数和字体 |
| `font` | Word 版用的字体 |
| `problems` | 两份检查发现的问题；有问题时退出码 1 |
| `warnings` | 材料检查的警告（档案改过、熟练技能没列等）；档案里没有姓名时也写在这里。不影响退出码 |

## Word 版

- 内容和 PDF 是同一份，版式仿照模板：姓名、联系方式、求职意向，每节一个标题，条目左边是名称和职位、右边是日期，下面是要点。个人简介是标题下的一段正文，没有项目符号。
- **只保证 PDF 是一页。** Word 按自己的字体和排版换行，同样的内容可能排到第二页。投递时优先发 PDF；对方要 Word 版时，打开看一眼，超出就删内容，或者在 Word 里稍微调小字号或边距。
- 字体用**等线**。PDF 用的 Noto 字体不是每台电脑都有，等线是 Office 2016 起在 Windows 和 Mac 上都自带的中文字体，对方用哪种 Office 打开，看到的都是同一款字体。
- 只用标准库写（.docx 是几个 XML 文件打成的 zip），不加依赖。用 Word 打开虚构的示例内容试过，一页；WPS 还没有试过。

## 个人简介的版面

材料有简介时（M3-2c），它是抬头之下、教育经历之前的第一节，标题"个人简介"，正文一段，不加项目符号；`summary` 为 `null` 时没有这一节，其余版面不变。PDF 正文 11pt：最松的间距（1.5）下一行约 44 个汉字，最紧（0.8）约 49 个；Word 版 10.5pt，一行约 48 个。所以简介超过 88 个汉字宽（字母、数字、半角标点算半个）时，`material validate` 会警告，见 [material.md 第 4 节](material.md#4-material-validate)。

## 超出一页时

模板的 `element-spaciness` 一个参数同时调页边距、行距和段距。先用最松的 1.5 编译，放不下就在 0.8–1.5 之间二分查找能放进一页的最松的值，最多编译 8 次。调到 0.8 还放不下，就报错要求删内容，不生成文件。

## 检查什么

- `tools/verify_pdf.py`：页数是 1、文本层读得出来、日期范围用 ASCII 连字符。
- 文本层没有康熙部首和部首补充（U+2E80–U+2FDF）：它们看着像"大""用"，但搜索和 ATS 对不上。
- 文本层没有私用区字符（U+E000–U+F8FF 和两个补充平面）：这是图标字体。
- 没有 Type 3 字体。
- 内容里的每个字段都能在文本层里逐字找到（忽略空白）。

部首和私用区是直接读 PDF 字体的 ToUnicode 映射查的，只用标准库。`pdftotext` 会把部首折回正常汉字，所以不能靠它查；`pypdf` 能读出原样，但它是可选依赖。

## CI 上的真实渲染

工作流 `.github/workflows/cn-resume-pdf.yml` 的任务 "Resume PDF real render (Linux)" 在 Ubuntu 上跑 `tests/test_cn_resume_pdf.py`，真的编译 PDF 再检查，而不是跳过：

1. 下载固定版本的 Typst 0.15.1（`typst-x86_64-unknown-linux-musl.tar.xz`），以及 [notofonts/noto-cjk](https://github.com/notofonts/noto-cjk) 在固定提交 `9b0f143`（标签 Serif2.003）上的 `NotoSansSC-VF.ttf` 和 `NotoSerifSC-VF.ttf`。
2. 用 `sha256sum --check --strict` 核对三个文件的 SHA-256。任何一个不符，任务就在这一步失败，不解压，也不设置后面要用的环境变量。
3. 只用下载的字体（`TYPST_FONT_PATHS`、`TYPST_IGNORE_SYSTEM_FONTS=true`），装 `pypdf==6.21.3`，设 `JOBSEARCH_CN_REQUIRE_TYPST=1` 后跑测试。

`JOBSEARCH_CN_REQUIRE_TYPST=1` 的意思是缺 Typst 或字体时测试失败，不再跳过。本机不设这个变量，没装 Typst 时测试照旧跳过。

换版本时，摘要不要从下载下来的文件里算，要从独立来源核对：

- Typst：GitHub API `repos/typst/typst/releases/tags/v<版本>` 里那个资产的 `digest` 字段（`sha256:...`）。
- 字体：仓库在新提交上那个文件的 git blob id（`git ls-tree <提交> <路径>`）。用下载的文件跑 `git hash-object` 算出的 id 和它一致，才用 `sha256sum` 算新的摘要。

## 模板

模板借自 [habaneraa/typst-resume-one-page](https://github.com/habaneraa/typst-resume-one-page)（MIT），放在 `jobsearch_cn/resume_templates/habaneraa/`，来源和改动见那里的 `SOURCE.md`。所有第三方组件见 [THIRD_PARTY.md](../../THIRD_PARTY.md)。
