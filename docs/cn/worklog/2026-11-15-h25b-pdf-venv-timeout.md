# 2026-11-15 · H25b：Windows 虚拟环境的 PDF 超时回收

## 完成

- 在未修改的 `master@7287f5c` 上复现：Windows / CPython 3.14.9 虚拟环境运行 `ProcessTree.test_the_child_waits_for_the_job_even_when_the_parent_is_slow`，耗时 4.743 秒，超过原有 4 秒断言。
- 沿 H25b 的既有要求修复 PDF 提取进程树；本项独立于微信签名支持。
- 增加两项真实 venv 与 `profile extract` CLI 的回归，确认后代已启动、超时后无法继续写入，且虚拟环境中独有的 PDF 后端仍能读取；同步建档说明和 H25b 路线图条目。
- 已提交 [PR #176](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/176)。

## 决策

- Windows 的 venv `python.exe` 是重定向启动器，会在 Python 握手代码运行前启动实际解释器；延迟分配 Job Object 时，实际解释器已经不在受控进程树里。
- 参考 [CPython `multiprocessing.popen_spawn_win32`](https://github.com/python/cpython/blob/3.14/Lib/multiprocessing/popen_spawn_win32.py) 的做法：直接启动基础解释器，用 `__PYVENV_LAUNCHER__` 保留虚拟环境。保持 stdin 握手和已有超时要求，只处理 Windows 上当前虚拟环境的 Python 命令。

## 验证

- 新增真实 CLI 回归在修复前失败：隔离 venv 中的合成 PDF 后端启动了一个后代，提取预算已耗尽，该后代仍成功写出完成标记。基线的另一项用例确认仅在 venv 中安装的后端可用。
- Windows / Python 3.14.9：`python -m unittest tests.test_cn_resume_extract tests.test_cn_resume_extract_venv -v`，26 项通过、3 项因缺少可选 PDF 工具跳过。
- Windows / Python 3.13.12：`python -m unittest tests.test_cn_resume_extract.ProcessTree tests.test_cn_resume_extract_venv -v`，7 项全部通过。
- Windows / Python 3.14.9 虚拟环境完整回归：`python -m unittest discover -s tests -t . -v`，2287 项，2258 通过、29 跳过，无失败，耗时 733.788 秒。跳过项主要依赖可选的 Typst、字体或 PDF 工具；原有进程回收的时限断言和两项新增用例均通过。
- `tools/lint_skills.py`、`tools/security_guards.py`、`tools/check_framework_version.py`、`git diff --check` 及改动文件 UTF-8 / 替换字符检查通过。

## 遗留

- Windows 无法建立或分配 Job Object 时，H25b 原有的退路仍只终止直接子进程。

## 下一步

- 等待维护者独立审核；线上验证结果附在 PR 的验证说明中。
