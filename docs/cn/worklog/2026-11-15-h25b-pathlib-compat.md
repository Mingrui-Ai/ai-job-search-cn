# 2026-11-15 · H25b：旧版 pathlib 的路径检测回归

## 完成

- 在 `master@7287f5c`、Windows / Python 3.13.12 下复现 `OlderPython.test_the_reparse_attribute_finds_a_junction` 失败：删除 `Path.is_junction` 后，父类 `PathBase` 的同名方法仍存在，测试在模拟旧版 API 的断言处提前失败。
- 模拟时遍历整个继承链，移除每处定义，并为每处注册恢复操作，使测试能实际走到文件属性的 junction 检测。
- Windows CI 扩展为 Python 3.13 / 3.14 两项，覆盖此次实际失败的版本。
- 已提交 [PR #177](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/177)。

## 决策

- 保留缺少 API、拒绝 junction 和目录外没有写入的原有断言；本项只改测试，不改变存储实现或安全边界。
- 不把 `PathBase` 私有类名写成固定依赖：按 `Path.__mro__` 查找实际定义，兼容没有该 API、只有一处定义和有继承定义的版本。
- 修改上游 `.github/workflows/ci.yml` 的原因是现有 3.13 测试只在 Linux 上运行，相关 junction 用例会跳过；Windows 3.14 单项不能发现此次回归。采用现有矩阵格式，保留原有 Windows 3.14 检查名，不改变分支保护。

## 验证

- 修复前，原有用例在 Python 3.13.12 下失败，耗时 0.067 秒；实际继承链在 `pathlib._local.Path` 和 `pathlib._abc.PathBase` 两处定义了该方法。
- Windows / Python 3.13.12 和 3.14.9 各运行 `tests.test_cn_store_links`：10 项均通过；3.13 的两处方法定义在测试后均恢复。
- 反向验证：临时把 `store._REPARSE_POINT` 置为 0，原有用例如期失败，说明仍在核对文件属性检测；失败后，两处方法同样恢复。未改磁盘上的存储实现。
- Python 3.13.12 基础解释器完整回归：`python -m unittest discover -s tests -t . -v`，2285 项，2256 通过、29 跳过，无失败，耗时 478.625 秒。测试依赖从项目虚拟环境加载；PDF venv 问题另见 PR #176。
- Windows CI 矩阵与原有 3.14 检查名已核对；`tests.test_workflow_hardening` 的 3 项测试通过。
- `tools/lint_skills.py`、`tools/security_guards.py`、`tools/check_framework_version.py`、`git diff --check` 及改动文件 UTF-8 / 替换字符检查通过。

## 遗留

- Windows 虚拟环境中的 PDF 进程回收问题单独由 PR #176 处理。

## 下一步

- 等待维护者独立审核；线上验证结果附在 PR 的验证说明中。
