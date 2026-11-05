# 2026-11-05 · M6 BOSS 剪藏：纯英文标题保护

## 完成

- 独立复审 `0a18900` 确认原四类状态提示已修复，但纯“Job description”仍作为描述更新完整岗位；按规划者裁定继续处理同一个 P2。
- 在实质描述检查中剔除常见英文标题及可选修饰前缀，覆盖 description／details／responsibilities／requirements／qualifications／duties／skills／overview／summary 及 job／position／role／required 等组合。
- 判定前 NFKC 归一全角格式；存储原文仍完全保留。没有提高长度门槛，未改 `screen`、`store`、Schema 或权限配置。
- 新增 20 种英文标题格式，每种覆盖纯标题和标题加加载提示，共 40 个变体；与前序组合共 114 个占位样例。

## 决策

- 标题剔除仅影响“是否有实质描述”的判断。`Job description: Write SQL`、`Requirements: Java`、真实职责中谈需求或岗位描述仍保留，原文大小写和全角字符不变。
- 单纯标题与只有状态提示都不能刷新已保存岗位，继续由独立审核者复核精确最终提交。

## 验证

- 新回归在 `0a18900` 上共 34 个失败，真实 `jd screen` 复现英文纯标题 `updated=1`。
- 修复后：`tests.test_cn_boss_clip` 与 `tests.test_cn_screen.ListSummary` 共 37 项通过，9.548 秒；114 个占位变体拒绝，短职责和原文保存对照通过。
- `lint_skills`、`security_guards` 通过；全量 unittest 1856 项，28 skipped，396.499 秒，退出 0。运行代码和测试在全量期间未改。
- `git diff --check`、改动文件 U+FFFD 检查通过；日志在 `logs/boss-placeholder-resume/english-headings-*`。

## 遗留

- 词法不能识别任意未知标题或提示。真实 BOSS 选择器、自动发现验收及既有 P3 仍在对应任务。

## 下一步

- 本地提交后交 `framework_finish` 独立增量复审，不 push 或外发。
