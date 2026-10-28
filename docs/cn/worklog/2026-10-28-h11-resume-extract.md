# 2026-10-28 · H11：统一提取 Word 与 PDF 简历

## 完成

- 从最新 origin/master `e7b7fc9` 新建 `feat/cn-h11-resume-extract`；PR #33 合并后快进到 `dda4dcc`，按路线图 §2b H11 实现。
- 新增 `profile extract <文件>`，输出 UTF-8 JSON：`source` 为原文件名，`text` 为纯文本。Claude Code、Codex、DeepSeek Harness 使用同一命令。
- DOCX 仅使用 zipfile 和 ElementTree，读取 word/document.xml；按正文顺序处理段落、表格、分段文本、制表符、换行和内容控件，兼容常见及 Strict 命名空间。
- PDF 通过同一 Python 环境的子进程复用上游文本提取，不生成 dump、临时文件或日志。缺后端、无文字、损坏材料均给出可操作错误；旧版 .doc 和其他格式提示另存为 .docx。
- profile-setup.md 只修改步骤 2 中读取材料的部分，原建档字段约定和步骤 4 问答保持不动。没有增加权限授权，没有修改上游工具或包边界测试。

## 决策

- 遵守现有 CLI 的 JSON 输出契约，纯文本位于 text 字段；不会自动写 TXT，也不会保存档案。
- CN 进程只导入标准库。固定子进程桥接复用上游 `_extract_pypdf` 和 `run_tool`；仅需要文本，不调用会额外读取页数的 pdfinfo。可选依赖只在子进程加载，未放宽 `test_cn_package.py`。
- 子进程禁用字节码写入，参数作为 argv 传递、不经过 shell；不转发可能含材料内容的后端诊断。空文本不作为成功简历，PDF 不做 OCR。
- 测试用 zipfile 现场生成 Word 文档、用标准库构造带 Unicode 文本层的合成 PDF；未使用任何真实简历或个人档案。

## 验证

- 提取与包边界测试共 21 项：20 通过，1 项因本机没有 pdftotext 跳过。合成中文 PDF 用现有 pypdf 6.21.3 实际提取成功。
- 覆盖中文文件名、多个段落、表格（含单元格内容控件）、换行及制表符、UTF-8 输出、旧 DOC/其他格式拒绝、文件不存在、损坏/空文档、PDF 后端均缺失及超时。
- CLI 成功和失败前后比较测试目录的文件集合及字节内容，确认未产生提取文件、日志或修改已存档案。
- lint_skills、security_guards 均通过；全量 1047 项测试，1037 通过、10 跳过（112.017 秒，conda ai-job-search-cn / Python 3.12.15）。文档步骤 2 之外及原字段约定逐字不变，V6/V7 哈希和未推送状态已核对。

## 遗留

- 本机没有 pdftotext，真实 Poppler 回退测试由有该工具的环境执行；没有两种后端的降级错误已实际覆盖。
- 读取的是正文文字及 PDF 文本层，不还原视觉排版，不做 OCR；扫描材料按命令提示交给 Agent 读取。
- PR 待创建，待规划者审核合并。

## 下一步

- 开 PR 前已再次 fetch 并合并最新 master dda4dcc（已是最新）；检查通过后推送本分支并开 PR，路线图补上 PR 号。
- V6 `37b94b0`、V7 `14c6729` 保持不动且不推送，分别等用户通知 H9、M2-4a PR 后跑对照。
