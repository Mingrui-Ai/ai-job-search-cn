# 2026-11-11 · M4-2 本地跟进草稿

## 完成

- 从 PR #160 合并提交建立独立工作树，核对 M4-2 裁定及三份设计文件；本轮只用虚构临时数据。
- 接口检查：复用 `application list --due`；新增 `material template --kind followup --application --expected-revision`，沿用材料与审核命令，不新建命令组。
- 已接齐新 kind 的模板/validate/render/review draft/validate/show、typed event refs/date、上下文末次复核及 txt/build note 识别。首次投递归档正则保留。
- 共享流程写入 applications.md §17；材料、审核格式与 H1–H4 说明补齐，AGENTS/Claude/dsh 原有 CN 入口只补引用。AGENTS 的上游段未变；改动只为新增 CN 路由，未修改 framework_version 或权限。

## 决策

- `followups.py` 统一只读上下文、完整输入摘要与资格；`applications.py` 只增加同一读事务内的事件/投影检查，不改数据库、事件或写入流程。
- 旧三类模板仍必填，followup 为 default 可选扩展；缺失时只回退该 spec，返回实际来源及版本。旧材料/审核不开始依赖投递库或当前资料。
- 新 kind 的五个校验入口共享上下文；render 使用同一内存输入，发布前复核；review 核验真实产物后复核。跨 SQLite/JSON 不承诺原子快照。
- AGENTS 与 Claude/dsh 的现有 CN 入口只补路由；上游主体不改，权限字符串不增加。

## 验证

- 实现与验证进行中；最终完整 SHA、三项正式检查、隐私/UTF-8 及独立审核结果记录在 PR。
- 只读上下文及旧消息回归检查点：76 项、1 跳过，17.701 秒，OK。覆盖资格、事实/投影、日期、完整摘要、隐私扣留及模板来源回退。
- 新 CLI 闭环及旧消息、审核、产物、包边界：154 项、3 跳过，32.050 秒，OK。来源变更覆盖五入口；渲染/审核中插入虚构事件会被末次检查拒绝，旧输出保留；txt/说明缺失或被换会拒绝旧审核。
- 扩展到 application 全套与真实 Windows junction：238 项、3 跳过，57.336 秒，OK。自查确认完整 job 摘要须在 legacy upgrade 填默认值前计算；新增回归。末次消息/context 检查 89 项、1 跳过，23.013 秒，OK，包含用户模板可省略可选 progress、必填槽位 required 必须为 true。
- lint_skills/security_guards 通过；24 份变更通过 UTF-8、BOM/替换字符/控制字符及范围检查，新增内容无机器路径或令牌特征。公开样例中的邮箱均为 example.com 虚构标记。

## 遗留

- M4-5 的真实连续使用验收不随本工程完成；本功能只生成本地草稿，不发送、不更改提醒日期。

## 下一步

- 完成只读 context 与旧模板兼容检查点，接齐材料/产物/审核，运行虚构闭环及正式检查，交规划者独立审核。
