# 第三方组件清单

这份清单列的是 `jobsearch_cn`（CN 版工具）用到的第三方组件。本仓库是 MIT 许可；上游项目的说明见 [README](README.md) 的"致谢与许可"。

## 放进了仓库的

| 组件 | 版本 | 许可 | 位置 | 改动 |
| --- | --- | --- | --- | --- |
| [habaneraa/typst-resume-one-page](https://github.com/habaneraa/typst-resume-one-page)（简历模板） | 提交 `98aea62` | MIT | `jobsearch_cn/resume_templates/habaneraa/` | 见同目录的 [SOURCE.md](jobsearch_cn/resume_templates/habaneraa/SOURCE.md) |

## 没放进仓库、由用户自己装的

运行时调用，不随仓库发布，也不是 Python 依赖（ADR-4）。

| 组件 | 用途 | 许可 | 必需吗 |
| --- | --- | --- | --- |
| [Typst](https://github.com/typst/typst) | 把简历编译成 PDF，安装方法见 [resume-pdf.md](docs/cn/resume-pdf.md) | Apache-2.0 | 生成 PDF 时必需 |
| [pypdf](https://github.com/py-pdf/pypdf) | 读 PDF 的文本层 | BSD-3-Clause | 和 Poppler 二选一 |
| [Poppler](https://poppler.freedesktop.org/) 的 `pdftotext` | 读 PDF 的文本层 | GPL | 和 pypdf 二选一 |

## 字体

字体不放进仓库。生成 PDF 时，用到的字形会嵌入 PDF，HR 那边不用装。

| 字体 | 来源 | 许可 | 用在哪里 |
| --- | --- | --- | --- |
| Noto Serif SC、Noto Sans SC（或同一设计的 Source Han、Noto CJK） | 操作系统自带或用户安装 | OFL-1.1 | 正文、标题 |
| 微软雅黑 | Windows 自带 | 微软的字体许可，`fsType` 允许嵌入 | 没有上面几款时的备选 |
| New Computer Modern | Typst 程序自带 | 见 Typst 的 [typst-assets](https://github.com/typst/typst-assets) | 列表圆点（上游模板的设计） |

## 特意没有用的

- `@preview/nerd-icons`（上游模板依赖的图标包）是 LGPL-3.0，已从模板里去掉，联系方式改成纯文本。
