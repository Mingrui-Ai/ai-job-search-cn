# 2026-11-03 · V23：M3-4 留出样例和 #123 的对照

## 2026-11-04 再复跑结论（Codex A，67508e9）

**对 #123 的 `67508e9a4c06b0b5ae8e2521934b5dd1c57db7b9`：75 个冻结场景按裁定通过 75/75，严格比较通过 72/75；上一轮 33 个扩展探针通过 33/33，本次新增 14 个探针通过 14/14。此次范围内未发现新的 P1、P2、P3，原 a-6 的三个套话警告仍是已批准的不阻塞 P3 待办。** 上轮 P1 n-1、P2 n-2 已修复；Codex B 指出的月数占位符单位问题也已修复。本轮 V23 复跑通过，范围限于下述冻结场景和探针。

### 范围与完整性

- 目标来自本轮派活，读取时 #123 的远端 head 与指定完整 SHA 一致；在独立、干净的 detached 工作树运行，运行器再次核对 SHA 和工作树状态。没有修改被测实现。
- 75 个冻结场景全部重跑，冻结输入、期望、清单和校验脚本保持原样。`verify_oracle.py` 在复跑前、运行器前后及复跑后均通过：30 个冻结文件摘要一致，冻结目录相对 `eef00aeed249d0ecde36797e6c656a70b745640b` 无 diff。
- 原有 40 个辅助探针、上一轮 33 个扩展探针全部重跑，另加 14 个新规则探针，共 87 个探针；探针不计入 75 个冻结场景。旧探针的材料和 33 个扩展探针的期望退出码逐项核对未变，原 40 个辅助探针的退出码向量均与上一轮相同。
- 沿用上轮映射版本 2，未修改映射和严格判定逻辑；映射里的实现说明仍指向它建立时的 `762b9f6`，本次实际被测 SHA 以 `results.json` 和 `adjudication.json` 为准。按裁定汇总仍只豁免三个指定场景缺少套话警告，不扩大豁免。
- 所有场景准备步骤成功，45 个候选稿的内置模板对照一致。47 个带显式期望的探针中，10 个通过且最终文字逐字符合预期，37 个被拒，validate/render 均退出 1、返回相同的错误 JSON，没有输出材料正文。
- 只使用冻结的虚构档案和岗位，每次都用独立临时 `--data-dir`；旧实际输出保持原样。遵守收件箱网关提醒，未读取指定历史测试改动，也未转录旧方法名。

### 结果与问题关闭情况

| 项目 | 通过数／结果 |
| --- | --- |
| 冻结场景严格比较 | 72/75 |
| 冻结场景按既定裁定 | 75/75 |
| 上轮 33 个扩展探针 | 33/33，上轮失败的 5 个全部转为通过 |
| 本次新增探针 | 14/14 |
| 原 40 个辅助探针 | 全部复跑，退出码向量一致 |
| P1 n-1：日期占位符同句写“明天” | `r-date-mixed-placeholder` 被拒，诊断明确指出手写“明天”；新增同句写“随时”的探针也被拒 |
| P2 n-2：“至少／以上” | 原四个阿拉伯数字探针全部被拒；新增四个对应占位符探针也全部被拒 |
| Codex B 的 P2-3：月数占位符接“个半月” | 被拒；新增“个多月”也被拒，诊断均指向 `availability.months` 的精确值 |
| P3 a-6 | 三个既有套话警告仍缺失，按已批准待办保留；没有新增 P3 |

冻结场景各组与上一轮相同：模板选择 30/30、长度边界 13/13、通过对照 6/6、必须拒绝 22/22、仅警告严格 1/4（按裁定 4/4）。a-2、a-3 原探针继续拒绝，a-8 的待确认文字继续通过。

### 新增 14 个探针

依据本轮派活及该 head 的 [material.md 7.4](https://github.com/Mingrui-Ai/ai-job-search-cn/blob/67508e9a4c06b0b5ae8e2521934b5dd1c57db7b9/docs/cn/material.md#74-检查)，tech 虚构档案为最早 `2026-12-07`、每周 4 天、3 个月；均引用 `availability`。

| 写法 | 数量 | validate/render 实际退出码 | 判定 |
| --- | --- | --- | --- |
| 日期占位符搭配“起”“以后”“最早” | 3 | 0 / 0，无警告 | 通过，代入后的文字正确 |
| 日期占位符搭配“最晚”“之前”“左右”“或更早” | 4 | 1 / 1 | 正确拒绝 |
| 同句日期占位符加“或随时入职” | 1 | 1 / 1 | 正确拒绝 |
| 月数占位符接“个半月”“个多月” | 2 | 1 / 1 | 正确拒绝 |
| 天数／月数占位符搭配“至少／以上” | 4 | 1 / 1 | 正确拒绝 |

### 证据、检查与后续

- [严格结果](../../../tests/fixtures/cn/messages-m3-4-comparison/actual/pr123-67508e9/results.json)、[按裁定汇总](../../../tests/fixtures/cn/messages-m3-4-comparison/actual/pr123-67508e9/adjudication.json)、[75 个逐场景记录](../../../tests/fixtures/cn/messages-m3-4-comparison/actual/pr123-67508e9/cases/)、[87 个探针及命令输出](../../../tests/fixtures/cn/messages-m3-4-comparison/actual/pr123-67508e9/probes.json)、[输出复核摘要](../../../tests/fixtures/cn/messages-m3-4-comparison/actual/pr123-67508e9/verification.json)。
- 复跑命令仍用下方的 `run_comparison.py --impl <被测工作树> --output <新目录>`；当前 `LOCKED_HEAD` 已设为本轮完整 SHA。随后运行 `summarize_rerun.py <新目录>`，分别给出原 33 个和新增 14 个探针的结果。
- 报告分支已包含最新 `origin/master@39f86c57b5542704579b730a77d092642f86a72e`，再次合入时无变化。两个工作树的 `lint_skills`、`security_guards` 均通过；被测 head 的 `tests.test_cn_messages` 共 60 项通过。
- conda `ai-job-search-cn`：报告分支全量测试 `python -m unittest discover -s tests -t .` 共 1653 项，跳过 26 项，其余通过，零失败／错误，337.511 秒。被测 head 运行的是上述 60 项沟通材料测试，不把报告分支测试数算作被测 head 的全量测试数。
- 80 个新 JSON 均可解析，84 个交付文本通过 UTF-8、无 BOM、U+FFFD、本机用户名、盘符路径及密钥模式扫描；`git diff --check` 通过，无 `data/` 文件进入提交。冻结目录及前两轮实际输出无 diff。
- 无新增需裁定问题；原 a-6 保持待办。交由规划者审核 #125 和安排 #123 后续，本次不替代代码审核或 M3 完整流程验收。另见[本轮工作记录](2026-11-04-v23-67508e9-rerun.md)。

---

## 2026-11-04 上一轮复跑结论（Codex A，762b9f6）

**对 #123 的 `762b9f62e95e78915bcb9cd6669d0ec13de26549`：75 个冻结场景按裁定通过 75/75，严格比较通过 72/75；扩展探针发现新 P1、P2 各一项，不能据此宣布 V23 整体验收通过。** 严格比较剩余 3 项都是规划者已列入待办的 a-6 套话警告。新增的 33 个裁定探针通过 28 个、失败 5 个，失败集中在下面两项新问题；探针不混进 75 的分母。

### 依据、范围与证据

- 按 #123 的 [V23 裁定](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/123#issuecomment-6608844037)、[代审裁定](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/123#issuecomment-6609267907)、[11-04 新裁定](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/123#issuecomment-6622522832) 判定：到岗时间只认 `{availability.start_date}`；天数、月数严格等于对应字段，至少、以上和区间不通过；a-8 一起复查。c-1 签名拆段、c-2 不考核错误引用片段，以及 b-1 至 b-8 已获确认。
- 冻结提交 `eef00aeed249d0ecde36797e6c656a70b745640b` 的目录没有任何 diff；`verify_oracle.py` 在复跑前后通过，30 个冻结文件摘要一致。没有修改输入、期望、冻结清单或产品代码。
- 被测实现用独立、干净的 detached 工作树；运行器校验完整 head，拒绝脏工作树。报告分支已合入 `origin/master` 的 `39f86c57b5542704579b730a77d092642f86a72e`。没有读取网关提醒列出的历史测试改动，也不转录相关旧方法名。
- 全部 75 个场景和原有 40 个探针重跑；另加 33 个裁定探针，共 73 个探针。每次使用冻结的虚构档案和独立的临时 `--data-dir`，清除数据目录环境变量，未接触真实数据。
- 新结果：[results.json](../../../tests/fixtures/cn/messages-m3-4-comparison/actual/pr123-762b9f6/results.json)、[逐场景记录](../../../tests/fixtures/cn/messages-m3-4-comparison/actual/pr123-762b9f6/cases/)、[probes.json](../../../tests/fixtures/cn/messages-m3-4-comparison/actual/pr123-762b9f6/probes.json)、[按裁定汇总](../../../tests/fixtures/cn/messages-m3-4-comparison/actual/pr123-762b9f6/adjudication.json)。首次 `pr123-2c84d96/` 输出保持原样。
- 映射版本升为 2，只为新增诊断文字补充同一错误类别：微信号、代入后残留花括号、逐字段到岗检查。接口、正文适配和冻结判断不变；本次映射副本随输出保存。按裁定的汇总仅豁免三个指定场景的套话警告缺失，其他结论、类别、渲染和内置模板对照仍核对。

### 冻结场景结果

| 组 | 场景数 | 严格通过 | 按裁定通过 |
| --- | --- | --- | --- |
| 模板选择 | 30 | 30 | 30 |
| 长度边界 | 13 | 13 | 13 |
| 通过对照 | 6 | 6 | 6 |
| 必须拒绝 | 22 | 22 | 22 |
| 仅警告 | 4 | 1 | 4 |
| 合计 | 75 | 72 | 75 |

首次失败的 23 个全部复跑，20 个转为严格通过；剩下 `warn-cliche-greeting`、`warn-cliche-email`、`warn-referral-salary-and-cliche` 仅缺套话警告，属于已裁定不阻塞的 a-6（P3）。所有场景准备步骤成功；所有成功渲染的文字符合冻结文本的既定适配；45 个候选稿的内置模板对照均未发现除槽位之外的错误差别。

### 原问题与指定探针

| 项目 | 复跑结果 |
| --- | --- |
| a-1（原 P2） | design、market、finance、hr、general 的 15 个显式选择全部回退 default，输出模板和理由正确；未知方向仍退出 2 |
| a-2（原 P1） | `x1-unknown-availability-cited`、`x1-tomorrow-cited` 均从 validate/render 退出 0 改为 1，错误明确指向到岗日期 |
| a-3（原 P1） | `x2-months-from-date`、`x2-days-from-date` 均改为退出 1，分别指向 `availability.months`、`availability.days_per_week`；5 天、6 个月两个控制探针继续拒绝 |
| a-4（原 P2） | 冻结微信号场景命中联系方式类别，无数字微信号的 `x7` 也拒绝 |
| a-5（原 P2） | 家庭住址、病史两个场景均拒绝并命中敏感个人信息 |
| a-6（P3 待办） | 三个套话场景仍缺警告；内推薪资警告保留，按裁定不阻塞 |
| a-7（原 P3） | 替换值中残留花括号被拒；冻结记法控制探针 `x3`、`x4` 也拒绝 |
| a-8（原 P3） | 冻结的“到岗安排尚待确认”通过；`x6` 及新增有引用／无引用两个控制探针均通过且原样渲染 |
| b-1 至 b-8、c-1 | 原探针结论保留；占位符、模板方向、长度、job 引用、revision、notes 和拿错材料的退出码未回退；正文邮箱仍须拆入签名 |

新增探针还确认：纯日期占位符和相等的阿拉伯数字／对应占位符能通过；手写相同或更晚日期、下周、尽快、随时不能通过；少于档案的天数／月数、不同字段占位符、3–4 天与 3–6 个月区间被拒；中文五天、两天、三个月、半年被拒；三项未知值无论手写数字还是用占位符都不能形成承诺。

### 新问题（建议优先级，交规划者）

**P1 · n-1：同句的到岗日期占位符使手写“明天”绕过检查。**

- 探针 `r-date-mixed-placeholder`：虚构 tech 档案最早到岗日期 `2026-12-07`，正文 `可于{availability.start_date}或明天到岗。`，引用 `availability`。validate 退出 0、无警告；render 退出 0，输出 `可于2026年12月7日或明天到岗。`。
- 对照：只有 `{availability.start_date}` 时通过；只有“明天”时拒绝。这里不是规则不认识的中文数字说法，而是已认识的时间被同句占位符豁免；违反 11-04“手写日期、随时、尽快、下周等一律不通过”的裁定，且会放出早于档案的承诺。
- 位置：[`messages.py:439`](https://github.com/Mingrui-Ai/ai-job-search-cn/blob/762b9f62e95e78915bcb9cd6669d0ec13de26549/jobsearch_cn/messages.py#L439)。判断同句只要含 `{availability.start_date}`，就跳过所有其余时间表达的拒绝。应继续检查占位符以外的时间表达。

**P2 · n-2：数值相等时，“至少／以上”仍被当作严格相等放行。**

- 虚构 tech 档案每周 4 天、3 个月，四个探针均引用 `availability`，validate/render 都退出 0、无警告，正文原样输出：

| 探针 | 正文 |
| --- | --- |
| `r-days-at-least-equal` | 每周可以至少到岗4天。 |
| `r-days-above-equal` | 每周可以到岗4天以上。 |
| `r-months-at-least-equal` | 可以至少实习3个月。 |
| `r-months-above-equal` | 可以连续实习3个月以上。 |

- 今天的裁定明确拒绝“至少”“区间”“以上”，这四条不符合。对照的无修饰等值通过、少值拒绝、不同端点的区间拒绝，说明只比较数值仍不足以满足裁定。
- 位置：[`messages.py:54`](https://github.com/Mingrui-Ai/ai-job-search-cn/blob/762b9f62e95e78915bcb9cd6669d0ec13de26549/jobsearch_cn/messages.py#L54)、[`messages.py:522`](https://github.com/Mingrui-Ai/ai-job-search-cn/blob/762b9f62e95e78915bcb9cd6669d0ec13de26549/jobsearch_cn/messages.py#L522)。提取并比较数值，未拒绝范围修饰语。没有新增 P3；原 a-6 仍是已批准待办。

### 复现与验证

从报告分支根目录，以不存在的新输出目录运行：

```powershell
conda run --no-capture-output -n ai-job-search-cn python tests/fixtures/cn/messages-m3-4-holdout/verify_oracle.py
conda run --no-capture-output -n ai-job-search-cn python tests/fixtures/cn/messages-m3-4-comparison/run_comparison.py --impl <762b9f6工作树> --output logs/v23-rerun
conda run --no-capture-output -n ai-job-search-cn python tests/fixtures/cn/messages-m3-4-comparison/summarize_rerun.py logs/v23-rerun
```

运行器退出 0 只表示执行完成。`results.json` 保留严格判断，`adjudication.json` 单独列出三个已裁定的 a-6 豁免及新增探针的五个失败；`probes.json` 保存输入、准备检查、命令及 stdout/stderr。冻结文件不会因汇总而改变。

- conda `ai-job-search-cn`：冻结校验、`lint_skills`、`security_guards` 通过；被测 head 的 `tests.test_cn_messages` 55 项通过。
- 报告分支全量测试：`python -m unittest discover -s tests -t .` 共 1653 项，跳过 26 项，其余通过，零失败／错误，380.094 秒。被测 head 只重跑了上述 55 项沟通材料测试，没有把报告分支测试数冒充被测 head 的全量测试数。
- 79 个新 JSON 均可解析，84 个交付文本通过 UTF-8、U+FFFD、本机用户名和盘符路径检查；`git diff --check` 通过，没有 `data/` 文件进入提交。
- 遗留／下一步：由规划者处理新 P1 n-1、P2 n-2；修复后重跑相同探针。当前只交付验证证据和报告，不改 #123 实现、不自行合并。另见[本轮工作记录](2026-11-04-v23-rerun.md)。

---

## 首次对照记录（2026-11-03/04，保留原结论）

结论：**75 个场景 52 个通过、23 个不通过，路线图 M3-4 的验收项"V23 对照通过"现在不满足。** 不通过的 23 个都有写明的原因：6 条看起来是实现的问题（a）；另有 2 条实现问题是同一规则换个写法才暴露的，不计入 75。8 条已批准的差别（b）都符合裁定，没有造成不通过。2 条期望本身可能要调整（c），没有造成不通过。没有改冻结文件，也没有改产品代码。

本来是 Codex A 的活，Codex 服务 11-03 17:20 起断流，由 Claude 会话按规划者 cn-e3 的派活接手。

## 基线与证据

- 冻结提交：`eef00ae`，文件在 [messages-m3-4-holdout](../../../tests/fixtures/cn/messages-m3-4-holdout/README.md)。`verify_oracle.py` 在运行器开头和全部跑完后各核对一次，30 个文件的摘要相符；冻结目录相对 `eef00ae` 没有改动。
- 被测版本：#123 head `2c84d966c673550fae95ba6bdc46ba6606145f61`，用独立的临时工作树，运行器锁定这个提交并确认工作树干净；用完已删除。按规划者要求，只看 PR head 上的文件和 PR 描述、评论，没有打开 `e51c8c4`、`131b1e6` 的改动，也没有读 `tests/test_cn_messages.py`。
- 环境：Windows、conda `ai-job-search-cn`。只用冻结目录里的虚构数据，每个场景一个新的临时 `--data-dir`，运行器去掉了数据目录环境变量，没有读真实数据目录。
- 实际输出：[results.json](../../../tests/fixtures/cn/messages-m3-4-comparison/actual/pr123-2c84d96/results.json)（汇总）、[cases/](../../../tests/fixtures/cn/messages-m3-4-comparison/actual/pr123-2c84d96/cases/)（每个场景的适配后材料、命令、退出码、stdout、stderr、判定）、[probes.json](../../../tests/fixtures/cn/messages-m3-4-comparison/actual/pr123-2c84d96/probes.json)（75 个以外的探针）。路径换成了 `<repo>`、`<data>`、`<python>`。
- 映射：[comparison-mapping.json](../../../tests/fixtures/cn/messages-m3-4-comparison/comparison-mapping.json)；运行器：[run_comparison.py](../../../tests/fixtures/cn/messages-m3-4-comparison/run_comparison.py)。

## 结果

| 组 | 场景数 | 通过 | 不通过 |
| --- | --- | --- | --- |
| 模板选择 `select-*` | 30 | 15 | 15 |
| 长度边界 `length-*` | 13 | 13 | 0 |
| 通过对照 `valid-*` | 6 | 5 | 1 |
| 必须拒绝 `reject-*` | 22 | 18 | 4 |
| 仅警告 `warn-*` | 4 | 1 | 3 |
| 合计 | 75 | 52 | 23 |

按冻结期望分：通过类 45 个，29 个符合；拒绝类 26 个，22 个符合；仅警告类 4 个，1 个符合。

判定依据：结论（通过、拒绝、警告）、必须报告的问题类别、作用字段（标题还是正文）、代入后的字数，以及被拒绝的稿件 `material render` 也退出 1 且不输出正文。全部 75 个场景的临时档案和岗位都通过了校验（`profile validate`、`jd save` 退出 0），不存在"因为输入不合格才被拒绝"的情况。

## 接口适配

都只动格式，不动用户看到的文字和判断。通过的稿件，render 的输出和冻结文本逐字比较，全部相同（有两处规定的例外：段间换行、日期写法，见下）。

| 冻结记法 | 适配成 | 说明 |
| --- | --- | --- |
| `requested_direction` | `material template <岗位id> --kind … --direction …` | 冻结说明把它定义为模板选择请求，所以用显式参数 |
| `{{job_title}}` 等，来源指针 | `{job.title}` 等白名单占位符，`refs` 补上占位符要求的 `job`、`availability` | 规划者 11-02 裁定 1 |
| 没有来源的 `{{x}}`，包括岗位名里的 | `{x}` | PR 的语法；用冻结记法另跑了探针 `x3`、`x4`，结论相同 |
| 一整段 `body` | 用户模板：方向、revision、上限同内置，只留 `body`（邮件另有 `signature`） | 内置模板要求多个槽位，一段文字放不进去；用户模板是 material.md 7.2 公布的做法 |
| `valid-supported-fact-slot` 的 `/experience/0/bullets/0` | 把原文直接写进正文，引 `proj-v23` | 白名单没有 bullets（探针 `b1-placeholder-not-on-the-list`）；最终文字不变 |
| 到岗日期 `2026-12-07` | 代入后是 `2026年12月7日` | material.md 7.1 的写法；冻结期望没有固定这个格式 |
| 邮件正文里的 `{{contact_email}}` | 拆到 `signature` 段，两个场景 | 见 (c)-1 |

**单槽位模板有没有掩盖规则**：另把 45 个候选稿放到内置模板上跑一遍作对照，除槽位错误外，其余错误和单槽位模板的结果 45 个全部相同。

## (a) 看起来是实现的问题

优先级是我的建议，由规划者定。a-1、a-4、a-5、a-6、a-7、a-8 这 6 条对应 75 个场景里的 23 个不通过；a-2、a-3 是探针发现的，不计入 75，但都是冻结规则明文要求的。

**a-1 · `--direction` 指定没有模板的方向时退出 2，没有回退 default（15 个场景，建议 P2）。**

- 场景：`select-{design,market,finance,hr,general}-{greeting,email,referral}`。
- 复现：`python -m jobsearch_cn material template job_000000002305 --kind email --direction design --data-dir <data>`
- 实际：退出 2，`no template for direction 'design' (there are: data, default, ops, product, tech)`。
- 依据：规划者 cn-83 裁定这五个键回退 default；冻结说明写明"不能报'该方向不支持'后退出"。设计稿第 3 节第 4 步也写"这个方向没有模板文件，就用 default"。退出 2 只记在工作记录"和设计稿不同的地方"，#123 的规划者评论没有裁定这一条，所以归 (a)。
- 补充：不给 `--direction`、档案写 design、market、finance、hr 时能正确回退（探针 `b2-implicit-fallback-*`），问题只在 `messages.py:160` 这条显式路径。`general` 档案校验不收，只能从 `--direction` 进来。完全不存在的方向（如 `nosuch`）退出 2 是合理的，修的时候可以分开。

**a-2 · 写了到岗日期之类的承诺，只要引了 `availability` 就放行（探针，建议 P1）。**

- 探针 `x1-unknown-availability-cited`：data 档案三项到岗信息全是 null，正文"您好，我随时可以到岗。"，`refs: ["availability"]`，退出 0，render 输出原文。
- 探针 `x1-tomorrow-cited`：tech 档案最早 2026-12-07，"您好，我明天即可到岗。"，同样退出 0。
- 依据：冻结规则"缺失值不能变成'随时到岗'，不能承诺比档案更早或更长"。冻结的 `reject-availability-unknown`、`reject-availability-earlier-date` 能通过，只是因为冻结输入 `refs` 为空；多引一项就绕过去了。
- 位置：`messages.py:351` 只查"引了没有"；material.md 7.4 写"写的数要和档案一致，由上一条的数字检查保证"，没有数字的承诺不受任何检查。

**a-3 · 到岗日期里的数字可以冒充天数和月数（探针，建议 P1）。**

- 探针 `x2-months-from-date`：档案 3 个月，"您好，我可以连续实习 12 个月。"，引 `availability`，退出 0；12 来自日期 `2026-12-07` 的月份。
- 探针 `x2-days-from-date`：档案每周 4 天，"您好，我每周可以到岗 7 天，烦请告知申请方式。"，退出 0；7 来自日期的 `07`。
- 对照：写 5 天、6 个月（日期里没有的数）都被拒绝（`x2-control-*`）。
- 位置：`messages.py:264` 把三个字段连成一段原文，`messages.py:332` 把其中所有数字算作已知，没有区分字段。

**a-4 · 手写微信号查不出来（1 个场景，建议 P2）。**

- 场景：`reject-literal-wechat`，"您好，微信号：v23_fake_only，方便时烦请告知申请方式。"
- 实际：退出 1，但错误是 `the number '23' is not in what it cites`，来自微信号里碰巧的数字，不是联系方式规则，所以按"未命中必须的类别"判不通过。
- 复现根因：探针 `x7-wechat-without-digits`，微信号换成 `fake_only_handle`，退出 0，render 输出原文。
- 位置：`messages.py:43-44` 只有手机号和邮箱两个正则，material.md 7.4 也只写了这两种；冻结规则写的是"电话、邮箱或微信"。

**a-5 · 敏感信息词表缺家庭住址和病史（2 个场景，建议 P2）。**

- 场景：`reject-sensitive-home-address`（"我的家庭住址是示例市虚构路测试小区甲栋"）、`reject-sensitive-health`（"我的病史是测试用虚构疾病"）。
- 实际：都退出 0，render 输出原文。
- 位置：`banned.json` 敏感一组没有"住址""地址"；健康只收了"健康状况"（`banned.json:20`）。工作记录写了把"健康"收窄，这条没有经过规划者裁定；收窄本身有道理，但"病史""疾病"这类词也要收。

**a-6 · 常见套话没有警告（3 个场景，建议 P3）。**

- 场景：`warn-cliche-greeting`（"吃苦耐劳，抗压能力强"）、`warn-cliche-email`（"良好的团队合作精神和沟通能力，希望贵司给我机会"）、`warn-referral-salary-and-cliche`（薪资警告有，套话警告没有）。
- 实际：前两个退出 0、没有警告；第三个只有薪资警告。
- 位置：`banned.json:55` 这一组只收了"在吗""急求"等开头语。按冻结规则这是警告，不挡发送，所以优先级低。`warn-cliche-email` 那句靠词表不一定抓得全，要收哪些词可以由规划者定。

**a-7 · 替换值里残留的占位符没有被发现（1 个场景，建议 P3）。**

- 场景：`reject-unfilled-after-substitution`，岗位名是"示例{unfilled_title}岗位"，正文 `您好，想了解{job.title}的申请方式。`
- 实际：退出 0，render 输出"您好，想了解示例{unfilled_title}岗位的申请方式。"，用冻结的 `{{ }}` 记法也一样（探针 `x3`）。
- 位置：`messages.py:324` 只检查 Agent 写的文字；material.md 7.4 明写"占位符代入的值不查"。这条规定没有经过裁定。岗位名带花括号很少见，但一旦出现，发出去的就是带占位符的消息。

**a-8 · "到岗安排尚待确认"被当成到岗承诺（1 个场景，建议 P3）。**

- 场景：`valid-unknown-availability-omitted`，"您好，我做过数据字段核对，希望了解岗位安排。到岗安排尚待确认。"，`refs: ["proj-v23"]`。
- 实际：退出 1，`commits to a start date, days a week or a length of stay without citing 'availability'`。
- 依据：冻结规则把"到岗信息未知时保留待确认"列为通过对照。
- 位置：`messages.py:46` 的 `_COMMITMENT` 碰到"到岗"两个字就算承诺。绕过办法是多引 `availability`，这时能通过（探针 `x6`）。但这和 a-2 是同一处：引了就什么都不查。

## (b) 已批准的差别

V23 冻结之后定的规则，按已批准对待。下面都实跑确认过，都符合裁定，没有造成不通过。

**规划者 11-02 对设计四问的裁定**

- **b-1 占位符由渲染代入。** 实现：材料里写 `{edu-1.school}`、`{job.title}` 等白名单占位符，`material render` 从档案和岗位库代入一轮，学历代入成"本科"，日期代入成"2026年12月7日"；不在白名单的报错。实跑内置 tech 模板，render 输出"您好，我是示例留出测试大学软件工程专业的本科生，想应聘贵司的后端检索实习生。用 Python 整理了 8 项检索校验记录。可以2026年12月7日起到岗，每周4天。方便的话我把简历发给您。"探针 `b1-*`。
- **b-2 第一版 tech、data、product、ops 加 default。** 实现：`message_templates/` 下正好这五个文件，加一个 `banned.json`。对这五个键的 15 个选择场景全部通过，不给 `--direction` 时也选对（`b2-implicit-*`）。这条裁定没有说 `--direction design` 要报错，见 a-1。
- **b-3 长度按代入后的字数算，用户只能改小。** 实现：各段代入后的字数相加，段间换行不算；用户模板写的上限和硬上限取小。13 个长度场景全部通过，包括 150 字、302 字节的混合文本（确认不按字节算）。实跑：改成 9999 后 151 字仍拒绝，标题改成 200 后 41 字仍拒绝，改成 100 后 100 字通过、101 字拒绝（`b3-*`）。
- **b-4 起草流程归 M3-6。** 实现：`material` 只有 `validate`、`template`、`render`，`--output` 报参数错误退出 2（`b4-no-draft-command`）。本轮没有验证起草流程。

**规划者 11-03 在 #123 的裁定**

- **b-5 `job` 只算数字的依据，技能只认档案。** 实现：`_source` 里 `job` 的原文只有岗位名和公司名；技能依据跳过 `job`。实跑：岗位名含 Rust 且引 `job`，写"我熟练使用 Rust"仍拒绝；JD 要求 Rust 且引 `job`，仍拒绝；岗位名含 2027，引 `job` 可以写 2027，不引则拒绝；JD 薪资 180 引 `job` 也不能用（`b5-*`）。
- **b-6 模板编号 `<方向>/<kind>@<revision>`。** 实现：`material template` 输出如 `tech/greeting@1`。把用户模板的 revision 改成 2，按 `@1` 写的材料通过并警告"the template is now tech/greeting@2"；方向或种类不符报错（`b6-*`）。
- **b-7 沟通材料引用 notes.md 报错。** 实现：`material validate` 和 `material render` 都退出 1，错误相同：`a message does not cite notes.md; only a CV's summary does`（`b7-cites-notes`）。
- **b-8 拿错材料退出 2。** 实现：`resume build`（文件名合规时走到种类检查，否则先被文件名检查拒绝）、`review draft` 拿到沟通材料，`material render` 拿到简历，都退出 2，并说明该用哪个命令（`b8-*`）。

## (c) 期望本身可能不对

- **c-1 冻结的 `valid-contact-from-profile` 把邮箱占位符放在邮件正文，实现只允许放在 `signature` 段。** 正文原样放进 `body` 时退出 1（探针 `x5-contact-email-in-body`）；拆到 `signature` 段后通过，只多一个段间空行，计为通过。`reject-mixed-contact-reference-and-literal` 也做了同样的拆分，仍因手写邮箱被拒绝。"只能写在签名段"是 11-01 批准的设计稿里的规则，不在这次列出的 (b) 里，所以单列：如果这条规则成立，冻结用例的写法就过时了，意图（"经档案代入，不是手写"）不变。请规划者确认。
- **c-2 期望里的"问题片段"比实现公布的粒度细。** `results.json` 里 22 个符合期望的拒绝场景有 12 个标为没有引到冻结的 `offending_text`。其中 2 个（`reject-unfilled-*`）只是记法不同，错误里引的是适配后的 `{unfilled_role}`；其余 10 个确实没有引到：联系方式 4 个（错误不引原文）、到岗 4 个（同上）、`reject-sensitive-marital`（报"未婚"，冻结是"未婚未育"）、`reject-sensitive-birthday`（报"出生""生日"，冻结是日期）。冻结说明第 3 节的比较项只有结论、类别和作用字段，所以没有算不通过。请规划者确认片段只作说明，不作判定。另外，错误信息不引原文，对 Agent 定位问题没那么方便，可以以后顺手改。

## 复跑

从仓库根目录运行，`--impl` 是 #123 head 的工作树，`--output` 是一个不存在的目录，不能在冻结目录里：

```powershell
conda run --no-capture-output -n ai-job-search-cn python tests/fixtures/cn/messages-m3-4-holdout/verify_oracle.py
conda run --no-capture-output -n ai-job-search-cn python tests/fixtures/cn/messages-m3-4-comparison/run_comparison.py --impl <#123 工作树> --output logs/v23-new-run
```

运行器锁定 `2c84d96`。它退出 0 只表示跑完了，**不等于场景通过**，判定看 `results.json`。#123 改了以后要改 `LOCKED_HEAD` 再跑，结果放到新目录，不覆盖这一份。它不生成期望文件，不接入 unittest 自动发现。

## 验证

- 本分支：`lint_skills`、`security_guards` 通过；conda `ai-job-search-cn` 全量测试 1494 项通过，跳过 20 项，零失败，235.893 秒。这是分支基线 `507e499` 加上本次文件的结果，本分支没有合入最新 master，也没有跑 #123 上的全量测试（PR 自己记的是 1641 项通过）。
- 运行器跑过两次（试跑后加了 3 个探针），75 个场景的结论两次相同。
- 75 个场景：准备步骤全部退出 0；通过的稿件最终文字全部和冻结文本相符；内置模板对照全部一致。
- 交付文件查过 U+FFFD、本机用户名和路径，都没有。

## 遗留

- a-1 到 a-8 待规划者定优先级，转给 Claude B 或裁定改期望。不能写"V23 通过"。#123 修改后，用同一运行器对新 head 再跑。
- c-1、c-2 待规划者确认。不改冻结文件，确认结果记在冻结目录以外。
- 没做的：没有跑内置模板文案的人工质量评估（冻结说明不要求），没有覆盖完整岗位流程（M3-3 第三部分、M3-4、M3-6 合并后另走）。

## 下一步

规划者审这份 PR，裁定上面各条。本 PR 只加对照材料，不改产品代码，不自行合并。
