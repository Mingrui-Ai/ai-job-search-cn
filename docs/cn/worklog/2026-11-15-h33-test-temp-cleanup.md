# 2026-11-15 · H33：回归测试临时文件清理

## 完成

- 在 `master@7287f5c` 的原有测试中复现两种残留：Windows 只读 Git 对象文件删除失败，及岗位键审计使用 `delete=False` 创建 JSON 后未注册删除。
- 框架版本、上游更新、上游分流和安全守卫的四个测试基类改用 `tempfile.TemporaryDirectory()`，创建后立即通过 `addCleanup(directory.cleanup)` 注册清理，随后取目录路径。跨引用测试随继承关系得到相同修复。
- 岗位键审计的两个临时文件入口在创建文件后、序列化之前注册 `Path.unlink` 清理；文件仍在启动 CLI 前关闭，兼容 Windows 文件共享规则。
- 原有 CLI、Git 历史构造和业务断言保持原样。
- 已提交 [PR #178](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/178)。

## 决策

- 原来的 `shutil.rmtree(..., ignore_errors=True)` 在 Windows 上不能删除 Git 创建的只读对象文件，且会吞掉错误，因此测试通过不代表目录已清理。
- 采用项目已有的 `TemporaryDirectory` 用法。标准库会为可恢复的权限错误重设权限并重试；没有启用 `ignore_cleanup_errors`，其他清理错误仍由 unittest 报告。
- 安全守卫的残留由 `TrackedNodeModulesTests` 暂存文件时产生，即使没有 commit，`git add` 也会写只读对象。修复落在该类使用的 `GuardRepoFixture` 中。
- JSON 临时文件保留 `delete=False`，由 unittest 在测试结束时统一删除；注册点先于 `json.dump`，序列化或后续断言失败时同样执行。
- 修改五个上游测试文件是为了修复本机完整回归暴露的临时产物残留。改动集中在文件创建和清理注册，不新增共享抽象、第三方依赖或跨版本分支，不修改工具实现与 CI 配置。

## 验证

- 修复前，Windows / Python 3.14.9：三个上游相关模块的 36 项测试通过（56.102 秒），残留 31 个目录和 393 个只读文件；跨引用模块的 4 项通过（11.749 秒），残留 4 个目录；`TrackedNodeModulesTests.test_tracked_node_modules_file_fails` 通过（0.548 秒），残留 1 个目录。Git 残留共 36 个目录。
- `tests.test_job_key` 的 32 项原有测试通过（3.503 秒），残留 9 个 JSON 文件。各次复现使用空的专用 `TEMP` / `TMP`，测试退出后检查该目录内容。
- 修复后：Windows / Python 3.13.12 与 3.14.9 各运行上述四个模块的 40 项测试，分别耗时 66.528、68.508 秒，均通过，专用临时目录均为空。
- 安全守卫和岗位键审计两个模块：Windows / Python 3.13.12 与 3.14.9 各 111 项通过，分别耗时 36.844、40.408 秒，专用临时目录均为空。与前四个模块合计，各版本分组验证 151 项。
- 两个 Python 版本各对四个基类做两种失败实验：真实创建含只读对象文件的 Git 仓库后，让测试断言失败，或让 `setUp` 报错；另对两个 JSON 入口分别让后续断言失败、让序列化抛出 TypeError。共 24 次实验保留预期失败，均无额外清理错误，临时产物全部删除。
- Windows / Python 3.14.9 基础解释器完整回归：`python -m unittest discover -s tests -t . -v`，2285 项，2256 通过、29 跳过，无失败，耗时 583.846 秒。测试依赖从项目已有虚拟环境加载；退出后，专用 `TEMP` / `TMP` 内文件和目录均为 0。
- `tools/lint_skills.py`、`tools/security_guards.py`、`tools/check_framework_version.py`、`git diff --check` 及七个改动文件的 UTF-8 / 替换字符检查通过。

## 遗留

- 本项处理测试自身创建的临时产物，不更改求职数据存储或用户目录的删除行为。

## 下一步

- 等待维护者独立审核；线上验证结果附在 PR 的验证说明中。
