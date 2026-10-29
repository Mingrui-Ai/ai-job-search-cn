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
