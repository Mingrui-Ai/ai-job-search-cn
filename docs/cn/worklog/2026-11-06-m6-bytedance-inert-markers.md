# 2026-11-06 · M6 字节采集忽略不可渲染的安全标记

**完成**

- 收窄 `htmltext.visible(include_nontext=True)`：只允许 `iframe`、`canvas`、`svg`、`object` 豁免正文的非文本标签过滤；`script`、`style`、`template`、`head` 等原有跳过标签仍不可见。
- 字节站点已有祖先遍历因此继续忽略模板等上下文中的验证码、登录占位符；可见的安全标记仍触发停止。
- 新增正常列表及详情含脚本、模板、模板内 iframe 的完整采集回归，并覆盖不可渲染祖先及后续真实标记。

**决策**

- 修复只收窄非文本可见性选项，不改变正文提取、落盘、去重或其他站点规则。
- 先冻结生产与测试补丁及 SHA-256 供独立审核，冻结后不再修改这些文件；必要检查通过后再创建新提交。

**验证**

- conda `ai-job-search-cn`：字节/共享采集定向 85 项通过（1.201 秒）。
- `python tools/lint_skills.py`、`python tools/security_guards.py` 均通过，退出 0；`python -m unittest discover -s tests -t .` 全量 1909 项、28 skipped、0 失败，396.061 秒，退出 0。
- 生产与测试补丁基于 `c173fdd1540633bcab57d6aea0fed06c4b03d030` 冻结，SHA-256 为 `e79fce3c1190096bfd49ccf1e34748012c0639e3854fb7433c6f2cdad74f4a98`。逐文件原字节及 Git LF 哈希、快照与检查日志保存在本机协调目录，不入 git。
- 冻结后的生产与测试文件原字节及补丁哈希复核一致；`git diff --check` 通过，5 个交付文件均为有效 UTF-8，无 U+FFFD 替换字符。测试只用虚构 HTML 和临时目录，没有访问招聘网站或修改真实 JD。

**遗留**

- HTML 可见性仍不计算外部样式表，沿用现有离线 DOM 边界。

**下一步**

- 将冻结内容与最终新提交核对一致，交主规划者独立复核。
