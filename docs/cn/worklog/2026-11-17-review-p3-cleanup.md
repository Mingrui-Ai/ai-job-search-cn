# 2026-11-17 · 审核留下的 P3 收尾（#176、#177、#178、#180、#181）

## 完成

- **工作流固定 SHA 的检查覆盖全部工作流（#180 P3-2）。** 原有检查在 `tests/test_upstream_triage.py`，只读 `upstream-watch.yml`。`tests/test_workflow_hardening.py` 新增三项测试，对 `.github/workflows/*.yml` 里的每个 `uses:` 检查：
  - 外部 Action 必须是 `owner/repo@<40 位小写十六进制>`（允许 `owner/repo/子路径@…`）；标签、分支、短 SHA、大写、缺版本、表达式都不通过。
  - 本仓库内的引用（`./` 开头）没有版本可固定，放行。
  - `docker://` 镜像必须带 `@sha256:<64 位十六进制>` 摘要。目前三个工作流里没有这种引用，规则先定下来。
  - 读法按行，不依赖 PyYAML：认 `- uses:`、`uses:`、带引号的键和值，去掉行尾注释。另外核对“读到的引用数”等于文件里（去掉注释后）`uses` 这个词出现的次数，数目对不上就失败，这样读不懂的写法（例如花括号的流式写法）不会悄悄漏检。
  - 现在三个工作流共 19 处引用，全部通过。原有的那项检查保留不动。
- **旧版 pathlib 的模拟（#177 P3-1）。** `tests/test_cn_store_links.py` 的辅助函数改为遍历 `type(self.root).__mro__`，前提断言改为 `hasattr(self.root, "is_junction")` 为假。每一处移除仍然各自注册恢复。
- **安全守卫测试的临时目录（#178 P3-1）。** `GitignorePatternBehaviorTests.setUp` 换成 `TemporaryDirectory` 创建后立即 `addCleanup(directory.cleanup)`，与 #178 的写法相同。只改这三行，断言和守卫调用的行没有变化。
- **同样的旧写法一并换掉。** `tests/test_cn_inbox.py`（两处）、`tests/test_fetch_page.py`、`tests/test_lint_skills.py`、`tests/test_posting_guard.py` 的 `setUp` 是完全相同的两行（`mkdtemp()` 加忽略错误的 `rmtree`），换成同一写法。
- **路线图。** H34 从第 2 节开头挪到 H33 之后，内容没改（#180 P3-1）；“审核留下的 P3”一节补上今天各 PR 留下、这次没处理的条目，并标注这次处理掉的四条。

## 决策

- 新检查放在 `tests/test_workflow_hardening.py`：它已经遍历全部工作流，并且说明里写的就是“固定 zizmor 检查的设置”。
- 没有引入 YAML 解析库。按行读有读漏的可能，所以加了数目核对；代价是以后如果在工作流的脚本或名称里写到 `uses` 这个词，测试会失败并要求调整读法，宁可这样也不漏检。
- `container:` 键下的镜像（CI 里的 `texlive/texlive:latest`、`debian:bookworm`）不是 `uses:` 引用，这次没有纳入，现状不变；是否固定摘要见遗留。
- pathlib 模拟的恢复顺序不用特别处理：每个类的定义是各自独立的属性，恢复彼此不依赖。
- 没换的临时文件写法：`tests/test_cn_messages.py` 两处 `mkdtemp()` 配的是不忽略错误的 `rmtree`，清理错误会上报；`tests/test_cn_resume_build.py`、`tests/test_cn_screen.py` 各一处忽略错误的 `rmtree` 是用例内部重置目录，不是清理；`tests/test_job_key.py` 两处 `delete=False` 已由 #178 注册删除。

## 验证

环境：Windows 11，Python 3.12.15。

- **变异（仓库外的临时副本，工作树里的工作流没有改）。** 把测试文件和三个工作流复制出去，各改一处后在副本里运行 `tests.test_workflow_hardening`：
  - 不改：6 项通过。
  - `ci.yml` 的 dependency-review-action 改成 `@v7`：失败，报出文件、第 141 行和引用。
  - `cn-resume-pdf.yml` 的 setup-python 改成 `@main`：失败，第 45 行。
  - `upstream-watch.yml` 的 checkout 改成 7 位短 SHA：失败，第 49 行。
  - `ci.yml` 的 setup-bun 改成带引号的键和值、版本 `@v2`：失败，第 257 行。
  - 同一处改成花括号流式写法：失败在数目核对（读到 14 处，文件里 15 处）。
- **pathlib 探针。** 在实例继承链的 `WindowsPath`、`PureWindowsPath`、`PurePath` 上分别临时注入 `is_junction`，再让用例在三种情况下运行：原样、关掉文件属性检测、被测代码抛异常。
  - 新写法：12 次运行全部符合预期（原样通过；关掉检测后失败，说明用例确实走了文件属性检测；抛异常时报错）。
  - 改动前的写法：注入在 `WindowsPath` 或 `PureWindowsPath` 上并关掉检测时仍然通过，与审核描述一致。
  - 24 次运行后每个类上的定义都按对象身份恢复，进程结束时与开始时一致。
- **临时目录。** 把 `TEMP` / `TMP` 指到空的专用目录：`tests.test_security_guards` 79 项通过，遗留 0；加上另外四个改过的模块共 186 项通过，遗留 0。
- 改过的三个主要测试模块（`tests.test_workflow_hardening` 6 项、`tests.test_cn_store_links` 10 项、`tests.test_security_guards` 79 项）各跑 3 遍，9 次全部通过。
- `tools/lint_skills.py`、`tools/security_guards.py`、`git diff --check` 通过；新增中文文本没有替换字符或成串问号。
- 完整回归：`python -m unittest discover -s tests -t .`，2315 项，2272 通过、43 跳过，无失败，耗时 709.7 秒（本工作记录是在这次运行期间加入的，只是文档）。

## 遗留

- CI 里 LaTeX 任务的容器镜像用的是标签（`texlive/texlive:latest`、`debian:bookworm`），没有固定摘要，也没有测试约束。固定摘要会让镜像不再自动更新，是否这样做需要单独决定。
- 新检查按行读工作流，不是 YAML 解析；多行的 `uses` 值之类的写法靠数目核对兜住，不是逐一识别。
- 本地复合 Action（`.github/actions/*/action.yml`）里的 `uses:` 不在读取范围内；仓库现在没有这类文件（#183 P3-2）。
- 流式写法前面同一行有带引号的 `#` 时（例如 `- {name: "a # b", uses: …}`），去注释会把后面的 `uses` 一起去掉，逐行核对发现不了（#183 P3-2）。
- pathlib 探针只在 Python 3.12 上运行；3.13、3.14 上的行为依靠 CI。
- 这次没处理的 P3 见路线图“审核留下的 P3”一节。

## 审核后修改（#183 独立审核 193abe9：P2 一条、P3 五条）

- **P2-1：`.yaml` 工作流也受检查。** 原来的列表只取 `*.yml`，GitHub 同样执行 `*.yaml`。“列出工作流文件”和三项检查（固定 SHA、`persist-credentials`、`matrix.tool` 不进脚本）改成对一组文件调用的函数，列表同时取两种扩展名；真实目录和用例自己的临时目录走同一套函数。新用例在临时目录里写一个含 `uses: actions/checkout@v7` 的 `extra.yaml`，断言它被列出并被三项检查分别报出；另一个用例写固定完整 SHA 的 `extra.yaml`，断言通过。仓库的工作流目录里没有放测试文件。
- **P3-1：数目核对失败时指出行。** 原来比较整个文件里 `uses` 一词的次数和读到的引用数，失败信息只有 `15 != 16 : ci.yml`。改成逐行比较：一行里（去掉注释后）`uses` 出现的次数多于这一行被读到的引用数，就报出文件名和行号。判定范围与原来相同，步骤名或脚本里只是提到这个词也照样报，只会多报、不会漏过。固定 SHA 的失败信息现在也是“文件:行号: 原因: 引用”的列表。
- **P3-5。** `tests/test_cn_store_links.py` 的注释改成实际的继承链（Windows、Python 3.12 上是 `WindowsPath`、`Path`、`PureWindowsPath`、`PurePath`，打印核对过）；`tests/test_posting_guard.py` 去掉不再使用的 `import shutil`（文件里没有别处用到）。
- **P3-3：这次改到的上游测试文件。** `tests/test_fetch_page.py`、`tests/test_lint_skills.py`、`tests/test_posting_guard.py`、`tests/test_workflow_hardening.py` 来自上游，主干历史里它们只有上游作者的提交，这个 PR 是本仓库第一次修改。前三个只换了 `setUp` 里临时目录的建立和清理（`test_posting_guard.py` 另去掉随之不用的一行导入）：原来忽略错误的 `rmtree` 会吞掉清理错误，换成 `TemporaryDirectory` 后清理失败会上报；断言和被测调用没有变化。`test_workflow_hardening.py` 是守卫扩展：它本来就遍历全部工作流，新检查接在同一处，没有另放到 `tests/test_cn_*.py`。以后同步上游时这四个文件可能需要手工合并。
- **P3-4：路线图补全。** 补上 #176 评论里的未验项、#178 的备注和 `container:` 镜像没有固定摘要这条遗留，另记 #183 自己的各条。
- **P3-2：只记录，不实现。** 见“遗留”里标了 #183 P3-2 的两条和路线图。
- **验证。** 新用例先在只取 `*.yml` 的代码上运行，2 项失败；改读取范围后 `tests.test_workflow_hardening` 9 项通过。在仓库外的副本里重做审核的复现（每次复制测试文件和三个工作流，再加一个文件，运行真实的测试模块）：改动前的测试文件加 `extra.yaml`（`@v7`）仍然通过，复现了问题；改动后同一文件失败并报出 `extra.yaml:7`；固定完整 SHA 并设 `persist-credentials: false` 的 `extra.yaml` 通过；固定了 SHA 但保留凭据、把 `matrix.tool` 写进脚本、步骤名里带 `uses` 一词的各自失败并报出行号；`extra.txt` 不算工作流。第一轮的五种变异重跑后仍全部失败。改动的三个测试模块各跑 3 遍，`tools/lint_skills.py`、`tools/security_guards.py`、`git diff --check` 在提交前通过。完整回归在提交后分片运行，结果随 PR 说明给出。

## 下一步

- 等待对返工提交的独立审核。
