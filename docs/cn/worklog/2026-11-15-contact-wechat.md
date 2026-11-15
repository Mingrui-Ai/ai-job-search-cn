# 2026-11-15 · 邮件签名引用档案微信号

## 完成

- 接续 #123 的 `contact.wechat` 待办；维护者已在该 PR 的 2026-11-04 裁定中确认，微信号须先进入档案，沟通材料只能在邮件签名引用。
- 实现可选字段、默认脱敏、签名占位符与真实 CLI 路径的回归用例，全部使用公开虚构档案；更新建档、材料和简历工作流的共享说明。

## 决策

- 沿用 Profile v1；旧档案省略字段仍有效。微信号只取用户确认后的档案值，缺失时不推断。
- 不自动加入已有邮件或 PDF/Word 简历，不改变评分摘要，不增加发送接口或权限。

## 验证

- 实现前在 `7287f5c` 代码上运行新增两个 CLI 用例：`profile validate` 与 `material validate` 均退出 1，报 `contact` 有未知字段。
- 实现后，微信、档案及沟通材料的 123 项定向测试通过；补充已有 200 字符上限的边界用例后，微信及沟通材料的 78 项测试通过。本次新增 12 项用例。
- Windows / Python 3.14.9 虚拟环境运行 `python -m unittest discover -s tests -t . -v`：2297 项，2267 通过、29 跳过、1 失败。跳过项主要需要 Typst、中文字体或 PDF 提取工具；新增 12 项全部通过。
- 唯一失败是 `tests.test_cn_resume_extract.ProcessTree.test_the_child_waits_for_the_job_even_when_the_parent_is_slow`：耗时 4.642 秒，超过原有 4 秒断言。同一虚拟环境在未修改的 `master@7287f5c` 上独立复现（4.633 秒）；直接使用同版本基础解释器时，该用例在主线及本分支均通过。本项未修改进程实现或放宽断言。
- Python 3.13.12 下还遇到 `tests.test_cn_store_links.OlderPython.test_the_reparse_attribute_finds_a_junction` 失败，在同一主线基线复现；Python 3.14.9 下通过。未修改这项既有兼容性测试。
- `tools/lint_skills.py`、`tools/security_guards.py`、`tools/check_framework_version.py`（对 `origin/master`）及 `git diff --check` 通过；改动文件通过 UTF-8 和替换字符扫描。

## 遗留

- 本项不代表真实投递或 M3-5 验收完成。
- Windows 虚拟环境的既有进程超时用例仍需单独排查；本次完整回归不能记为全部通过。

## 下一步

- 提交维护者审核，保留上述完整回归的环境限制；真实投递验收按原路线图推进。
