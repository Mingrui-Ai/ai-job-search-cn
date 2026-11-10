# 2026-11-11 · M5-1 面试准备包实现

## 完成

- 新增独立 interview 五动作、原创五方向练习配置、严格包/来源/审核绑定，以及 JSON/Markdown 输出。
- 个人事实逐字段引用，未知保持 null；安全来源目录不输出 contact、来源文件名或路径。实际 Profile v1 source 为字符串，派生为 user/source_file，不冒充独立核验。
- 同包排他 writer、暂存 fsync、旧 build 失效、先 Markdown 后提交标记，审核核对正式字节；异常只清本轮安全对象。
- application 底层按内容拒绝 interview-prep；保留 followup 原错误、旧未知材料和 --sent 事实合同。未改 DB、评分、RULES_VERSION、权限白名单。
- 新增单源 interview.md、索引和 M5-1 进度记录。没有改上游文件；运行时入口候选仅在协调区。

## 决策

- 只做本地单岗位练习包，不提供完整第一人称回答、模拟面试、外部题库或额外产物格式。
- 完整源对象规范摘要，输出按字节摘要；相同题库内容切换 builtin/local 仍过期。机器 JSON 保留安全原文，Markdown 使用文字围栏。
- 生成协议不承诺两文件整体事务或旧产物回滚。来源最终重查不承诺跨文件快照或 A→B→A 历史检测。
- 独立审核由规划者安排，作者不自审或合并。用户当前只用 Codex，不启动 Claude 作权限匹配器验证。

## 验证

- 公开虚构定向 `tests.test_cn_interview`、`tests.test_cn_interview_publish` 共 58 项，4 项因 Windows 无符号链接创建权限跳过，其余通过；Windows junction 拒绝测试实际通过。包含两次 replace 前后失败、fsync 失败、硬终止、并发 writer、上下文改变及最终字节复查。
- `lint_skills`（14 skills / 12 commands）和 `security_guards` 静态检查通过；16 个改动文件 UTF-8/替换字符/控制字符、Python AST/JSON 检查通过。完整提交 SHA 的正式三门禁及原始日志在协调区 `interview-implementation/` 交付报告中记录；不将这些结果宣称为运行时权限实测。
- 第一轮 42 项发现两处测试辅助/夹具问题（误用 unittest fail 名称、源时间字段名与异常类），已更正；不将失败轮次计作通过。

## 遗留

- 经理意见书 018 的五动作精确权限与运行时薄入口尚未批准；因此 M5-1 不标全部完成，不宣称三运行时已齐备。
- 本地工程结果不能替代独立验收、真实面试使用及 M5-4 效果验证。

## 下一步

- 完成定向、正式门禁、UTF-8/范围检查，提供可审查提交和原始日志，由规划者派独立审核。
