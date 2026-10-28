# 2026-10-28 · H11：拒绝 xpdf 与损坏的 PDF 文本

## 完成

- 按 PR #35 审核意见，在本机显式使用 Git for Windows 的 `mingw64/bin/pdftotext.exe` 复现旧回退测试失败，版本为 xpdf 4.00，标识 Glyph & Cog。
- 回退前读取 pdftotext 的版本输出，只允许识别出的 Poppler；Glyph & Cog/xpdf、未知实现、探测失败均视为无可用回退。pypdf 正常时仍优先使用，不受 xpdf 存在影响。
- 不论后端，对 PDF 文本检查 U+FFFD 和异常控制字符；严重损坏时非零退出，只给直接读取或安装提示，不回传乱码或后端诊断。
- profile-setup.md 的读取材料步骤补充 Windows conda 环境中 `python -m pip install pypdf`，说明 Git 自带 xpdf 不用于中文提取。

## 决策

- 判断大量损坏的阈值为：替换字符和不允许的控制字符合计至少 3 个且占非空白字符至少 2%，或合计至少 20 个。允许制表符、回车、换行、换页；孤立的缺字不直接淘汰整份简历。
- 后端识别有固定模拟版本测试；真实 PDF 集成按实际能力分支：pypdf 或 Poppler 可提取，只有 xpdf 则验证提示错误，没有 Poppler 就跳过其正常提取测试。
- 保持标准库包边界、只读、不落盘、不记日志；全部测试仍是合成材料。

## 验证

- 旧代码在本机 xpdf 路径下复现失败；修复后提取与包边界初轮 25 项，24 通过、1 项 Poppler 测试跳过。
- 新增真实 xpdf-only 环境测试后，提取/包边界 26 项：25 通过、1 跳过。启用 Git xpdf 路径后全量 1052 项通过（1037 通过、15 跳过，142.654 秒），lint_skills、security_guards 通过。

- 向 PATH 前置 mingw64/bin 影响了上游 Bash 定位，使 5 项原本可运行的 Bash 测试额外跳过；已恢复常规 PATH 补跑 reset 两模块，16 项中 14 通过、2 项缺少符号链接权限跳过，补齐该覆盖。旧记录的“没有 pdftotext”指初轮 PATH，磁盘上实际存在 Git xpdf。

## 遗留

- 中文文本语义无法仅靠字符统计完全判断；已明确阻止已知 xpdf 回退，并拒绝可量化的大量损坏。
- PR #35 等规划者复核及 Windows CI。

## 下一步

- 检查后推送 #35；然后只读官方源码和文档完成 A1 调研，不安装/运行 dsh，不使用 API Key。
