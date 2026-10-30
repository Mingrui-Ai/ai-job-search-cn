# 生成 PDF 简历：Typst 和字体

M3-2 第一部分。`jobsearch_cn` 用外部程序 [Typst](https://github.com/typst/typst) 把简历编译成一页 PDF。Typst 不是 Python 依赖，用 subprocess 调用（ADR-4）。模板放在仓库里，生成时不联网。

现在只能用固定的虚构内容试生成。接上简历材料和 Word 版是第二部分，等 M3-1 合并后再做。

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

用固定的虚构内容生成 `<数据目录>/resumes/sample.pdf` 并检查，输出 JSON：

| 字段 | 含义 |
| --- | --- |
| `pdf` | 生成的文件 |
| `spaciness` | 用的间距参数 |
| `fonts` | 用的字体 |
| `problems` | 检查发现的问题；空列表表示都通过 |

有问题时退出码是 1。检查读文本层要装 `pypdf` 或 Poppler 的 `pdftotext`，两个都没有时，`problems` 里会写明。

## 超出一页时

模板的 `element-spaciness` 一个参数同时调页边距、行距和段距。先用最松的 1.5 编译，放不下就在 0.8–1.5 之间二分查找能放进一页的最松的值，最多编译 8 次。调到 0.8 还放不下，就报错要求删内容，不生成文件。

## 检查什么

- `tools/verify_pdf.py`：页数是 1、文本层读得出来、日期范围用 ASCII 连字符。
- 文本层没有康熙部首和部首补充（U+2E80–U+2FDF）：它们看着像"大""用"，但搜索和 ATS 对不上。
- 文本层没有私用区字符（U+E000–U+F8FF 和两个补充平面）：这是图标字体。
- 没有 Type 3 字体。
- 内容里的每个字段都能在文本层里逐字找到（忽略空白）。

部首和私用区是直接读 PDF 字体的 ToUnicode 映射查的，只用标准库。`pdftotext` 会把部首折回正常汉字，所以不能靠它查；`pypdf` 能读出原样，但它是可选依赖。

## 模板

模板借自 [habaneraa/typst-resume-one-page](https://github.com/habaneraa/typst-resume-one-page)（MIT），放在 `jobsearch_cn/resume_templates/habaneraa/`，来源和改动见那里的 `SOURCE.md`。所有第三方组件见 [THIRD_PARTY.md](../../THIRD_PARTY.md)。
