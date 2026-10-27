# V2 · M2-3 独立 JD 样例与人工期望

固定基线：`origin/master@34d254d72bc70795590918af3ae15db25b93c0dd`。本目录收录 5 份原创虚构 JD，覆盖产品、内容运营、UI 设计、测试开发、市场校招；其中 4 份为非开发方向。只模仿页面排版，未访问招聘页面、未照抄真实招聘内容，JD 中没有真实公司、人名、联系方式或链接。

按 14 个 Job Schema 语义字段组 × 5 份 JD 统计：**62 项一致、7 项规则漏读、1 项规则误读**。10 组 `match filter` 的总判断全部一致，但 70 项硬条件检查中只有 **68 项状态一致**；总判断一致不能掩盖字段和依据的错误。人工字段重放后，70 项检查状态全部符合人工预期。

## 独立性与文件约定

- JD、逐字段真值、出处及十组人工匹配判断先写定，再运行 CLI；没有查阅解析或匹配规则源码、既有 JD 样例、测试断言或执行会话的实现。判断依据只有 Job Schema、匹配契约、两份指定示例档案及本目录 JD 原文。
- [oracle-manifest.json](oracle-manifest.json) 记录首次运行 CLI 前冻结的 10 个文件的 SHA-256、冻结时间、文档及档案版本。人工基准冻结于 `a3986d3`；恢复工作树权限后从最新 `origin/master` 新建分支并复验。期间示例档案有更新，但七项过滤所用字段逐项相同；后续没有按解析输出改写期望。摘要以 Git 中保存的 LF 文本字节为准，核查时读取仓库 blob，避免 Windows 检出时的换行转换影响结果。
- `<名字>.expected.json` 是断言文件，不是可直接 `jd save` 的完整岗位记录。`fields` 的键为 [Job Schema v1](../../../../docs/cn/job-schema.md) 路径，`value` 是独立阅读所得值，`evidence` 为逐字复制的原文片段；`method: agent` 表示验证者独立阅读。未写的语义字段保留 `null` 或 `[]`。列表按集合比较，顺序不影响本轮结论。
- `salary`、`requirements.graduation`、`requirements.education` 按对象分组，内部所有字段都列出。金额、薪数、真假值均按原文，不将“优先”变成硬门槛，不推算日薪/月薪或默认工作天数。
- `id`、导入时间、`source`、`status`、`guard`、`raw_text` 属于运行记录，保留在 `actual/*.json` 的 `parse.stdout.jobs[0]` 中，不伪装成 JD 原文提供的人工事实。`site_argument` 仅说明模拟排版对应的 CLI 参数。
- 每份实测文件保存命令参数、退出码、完整 JSON 输出、stderr、时间和期望文件摘要。`parsed_match` 使用未经补全的解析记录；`oracle_match` 使用独立岗位库，将冻结的语义字段及逐字出处写入同一条记录，保留解析时的运行元数据，先 `jd validate`、再 `jd save`、再过滤。这是额外诊断，不用于更改人工判断。
- 本目录刻意独立于 `tests/fixtures/cn/jd/`；没有改代码、现有测试、既有 JD 或示例档案。本批样例未接入现有自动断言，供规划者审核和 M2-3 后续扩展使用。

## 匹配口径

人工判断先按 [match.md](../../../../docs/cn/match.md) 的七项硬条件填写，完整逐项理由在各期望文件的 `human_match`。技能、期望岗位方向和薪资不在本轮硬过滤范围内；不能因为 tech 缺设计/运营技能就增加冲突，也不能因为 ops 符合内容方向就跳过到岗条件。

| 档案 | 届别 / 最高学历 | 可到岗 / 可实习 | 地点与远程 | 类型与排除词 |
| --- | --- | --- | --- | --- |
| [tech](../profile/tech/profile.json) | 2027 / master | 4天/周 / 6个月 | 深圳、广州；可远程；不搬家 | internship；标题排除“外包”“销售” |
| [ops](../profile/ops/profile.json) | 2027 / bachelor | 3天/周 / 3个月 | 上海；不接受远程；不搬家 | internship、campus；标题排除“电话销售” |

`eligible`=全部检查符合；`ineligible`=至少一项冲突；`needs_check`=无冲突但有未知。“七项状态一致”只比较各项的 `result`，不表示输入字段、出处或理由逐字相同。

## 1. BOSS 风格 · AI 产品经理实习

[JD 原文](boss_ai_product_intern.txt) · [人工期望及逐字出处](boss_ai_product_intern.expected.json) · [完整 CLI 输出](actual/boss_ai_product_intern.json)

| 字段 | 期望值 | 当前 jd parse 的结果 | 结论 |
| --- | --- | --- | --- |
| `title` | `"AI产品经理实习生"` | `"AI产品经理实习生"` | 一致 |
| `company` | `"示例云舟智能科技有限公司"` | `"示例云舟智能科技有限公司"` | 一致 |
| `cities` | `["广州"]` | `["广州"]` | 一致 |
| `remote` | `false` | `false` | 一致 |
| `employment_type` | `"internship"` | `"internship"` | 一致 |
| `salary` | `{"min":180,"max":220,"unit":"CNY/day","months":null,"negotiable":false}` | `{"min":180,"max":220,"unit":"CNY/day","months":null,"negotiable":false}` | 一致 |
| `requirements.graduation` | `{"years":[2026,2027],"strict":true}` | `{"years":[2026,2027],"strict":true}` | 一致 |
| `requirements.days_per_week` | `4` | `4` | 一致 |
| `requirements.min_months` | `3` | `3` | 一致 |
| `requirements.education` | `{"min":"bachelor","preferred":"master"}` | `{"min":"bachelor","preferred":"master"}` | 一致 |
| `requirements.skills` | `["Axure","Figma","SQL","需求分析","用户访谈","PRD"]` | `["SQL"]` | 规则漏读 |
| `return_offer` | `true` | `true` | 一致 |
| `published_at` | `"2026-10-26"` | `"2026-10-26"` | 一致 |
| `deadline` | `null` | `null` | 一致 |

易错写法：“2026届-2027届”；“硕士及以上学历优先”；“每周五例会”；“3-5个工作日内回复”；“面试地点：北京（也可视频面试）”；“不支持远程”。解读见期望文件的 `traps` 与 `fields.*.note`。

| 档案 | 人工结论与理由（运行前写定） | 实际过滤结论 | 七项状态对照 | 人工字段重放 |
| --- | --- | --- | --- | --- |
| tech | `eligible`：2027届、硕士满足要求；4天/周、6个月足够；广州可接受；实习类型和排除项符合。 | `eligible`（总判断一致） | 7/7 一致 | `eligible`，7/7 一致 |
| ops | `ineligible`：至少4天/周高于ops可3天；广州也不符合地点条件。本科已达到最低学历，硕士优先不构成冲突。 | `ineligible`（总判断一致） | 7/7 一致 | `ineligible`，7/7 一致 |

## 2. 实习僧风格 · 新媒体内容运营实习

[JD 原文](shixiseng_content_ops_intern.txt) · [人工期望及逐字出处](shixiseng_content_ops_intern.expected.json) · [完整 CLI 输出](actual/shixiseng_content_ops_intern.json)

| 字段 | 期望值 | 当前 jd parse 的结果 | 结论 |
| --- | --- | --- | --- |
| `title` | `"新媒体内容运营实习生"` | `"新媒体内容运营实习生"` | 一致 |
| `company` | `"示例青禾文化有限公司"` | `"示例青禾文化有限公司"` | 一致 |
| `cities` | `["上海"]` | `["上海"]` | 一致 |
| `remote` | `false` | `false` | 一致 |
| `employment_type` | `"internship"` | `"internship"` | 一致 |
| `salary` | `{"min":150,"max":180,"unit":"CNY/day","months":null,"negotiable":false}` | `{"min":150,"max":180,"unit":"CNY/day","months":null,"negotiable":false}` | 一致 |
| `requirements.graduation` | `{"years":[2027],"strict":false}` | `{"years":[2027],"strict":false}` | 一致 |
| `requirements.days_per_week` | `3` | `3` | 一致 |
| `requirements.min_months` | `3` | `3` | 一致 |
| `requirements.education` | `{"min":"bachelor","preferred":null}` | `{"min":"bachelor","preferred":null}` | 一致 |
| `requirements.skills` | `["秀米","剪映","Photoshop","Excel","内容策划","文案写作","数据复盘"]` | `[]` | 规则漏读 |
| `return_offer` | `false` | `false` | 一致 |
| `published_at` | `null` | `null` | 一致 |
| `deadline` | `"2026-11-30"` | `"2026-11-30"` | 一致 |

易错写法：“2027届优先，其他届别也可投递。”；“每周五例会”；“3-5个工作日内回复”；“非外包岗位”；“不提供转正机会”。解读见期望文件的 `traps` 与 `fields.*.note`。

| 档案 | 人工结论与理由（运行前写定） | 实际过滤结论 | 七项状态对照 | 人工字段重放 |
| --- | --- | --- | --- | --- |
| tech | `ineligible`：上海不在tech可接受城市中，且JD不支持远程、tech不搬家；正文“非外包”不触发标题排除。 | `ineligible`（总判断一致） | 7/7 一致 | `ineligible`，7/7 一致 |
| ops | `eligible`：2027届、本科、3天/周、3个月、上海及实习类型均符合；无排除项命中。 | `eligible`（总判断一致） | 7/7 一致 | `eligible`，7/7 一致 |

## 3. Moka / 飞书招聘页风格 · UI 设计实习

[JD 原文](ats_ui_design_intern.txt) · [人工期望及逐字出处](ats_ui_design_intern.expected.json) · [完整 CLI 输出](actual/ats_ui_design_intern.json)

| 字段 | 期望值 | 当前 jd parse 的结果 | 结论 |
| --- | --- | --- | --- |
| `title` | `"UI设计实习生"` | `"UI设计实习生"` | 一致 |
| `company` | `"示例映格数字科技有限公司"` | `"示例映格数字科技有限公司"` | 一致 |
| `cities` | `["杭州"]` | `["杭州"]` | 一致 |
| `remote` | `true` | `true` | 一致 |
| `employment_type` | `"internship"` | `"internship"` | 一致 |
| `salary` | `{"min":null,"max":null,"unit":null,"months":null,"negotiable":true}` | `{"min":null,"max":null,"unit":null,"months":null,"negotiable":true}` | 一致 |
| `requirements.graduation` | `null` | `null` | 一致 |
| `requirements.days_per_week` | `null` | `null` | 一致 |
| `requirements.min_months` | `null` | `null` | 一致 |
| `requirements.education` | `{"min":null,"preferred":"master"}` | `{"min":null,"preferred":"master"}` | 一致 |
| `requirements.skills` | `["Figma","Sketch","Photoshop","交互设计","视觉设计","设计规范"]` | `[]` | 规则漏读 |
| `return_offer` | `null` | `null` | 一致 |
| `published_at` | `null` | `null` | 一致 |
| `deadline` | `null` | `null` | 一致 |

易错写法：“第十二届设计周”；“硕士及以上学历优先，不设最低学历门槛。”；“每周五例会”；“项目周期6个月，具体实习时长另行协商。”；“面试地点：北京，也可视频面试。”。解读见期望文件的 `traps` 与 `fields.*.note`。

| 档案 | 人工结论与理由（运行前写定） | 实际过滤结论 | 七项状态对照 | 人工字段重放 |
| --- | --- | --- | --- | --- |
| tech | `needs_check`：届别、最低学历、到岗天数、最短实习时长均未知；杭州岗位可远程且tech接受，因此无地点冲突。 | `needs_check`（总判断一致） | 7/7 一致 | `needs_check`，7/7 一致 |
| ops | `ineligible`：杭州不符合地点条件，ops明确不搬家且不接受远程；另有四项未知。“硕士优先”不应淘汰本科。 | `ineligible`（总判断一致） | 7/7 一致 | `ineligible`，7/7 一致 |

## 4. 牛客风格 · 测试开发实习

[JD 原文](nowcoder_test_dev_intern.txt) · [人工期望及逐字出处](nowcoder_test_dev_intern.expected.json) · [完整 CLI 输出](actual/nowcoder_test_dev_intern.json)

| 字段 | 期望值 | 当前 jd parse 的结果 | 结论 |
| --- | --- | --- | --- |
| `title` | `"测试开发实习生（Web自动化）"` | `"测试开发实习生（Web自动化）"` | 一致 |
| `company` | `"示例澄石软件有限公司"` | `"示例澄石软件有限公司"` | 一致 |
| `cities` | `["深圳"]` | `["深圳","北京"]` | 规则误读 |
| `remote` | `false` | `false` | 一致 |
| `employment_type` | `"internship"` | `"internship"` | 一致 |
| `salary` | `{"min":25,"max":35,"unit":"CNY/hour","months":null,"negotiable":false}` | `{"min":25,"max":35,"unit":"CNY/hour","months":null,"negotiable":false}` | 一致 |
| `requirements.graduation` | `{"years":[2027],"strict":true}` | `{"years":[2027],"strict":true}` | 一致 |
| `requirements.days_per_week` | `4` | `4` | 一致 |
| `requirements.min_months` | `4` | `4` | 一致 |
| `requirements.education` | `{"min":"bachelor","preferred":null}` | `{"min":"bachelor","preferred":null}` | 一致 |
| `requirements.skills` | `["TypeScript","Playwright","Postman","Git","接口测试","自动化测试"]` | `["TypeScript","Git"]` | 规则漏读 |
| `return_offer` | `false` | `false` | 一致 |
| `published_at` | `null` | `null` | 一致 |
| `deadline` | `"2026-12-15"` | `"2026-12-15"` | 一致 |

易错写法：“每周4-5天”；“每周四、五各安排一次缺陷复盘。”；“3-5个工作日内回复”；“工作地点：深圳南山区；面试地点：北京。”；“非外包”；“25～35元/小时”。解读见期望文件的 `traps` 与 `fields.*.note`。

| 档案 | 人工结论与理由（运行前写定） | 实际过滤结论 | 七项状态对照 | 人工字段重放 |
| --- | --- | --- | --- | --- |
| tech | `eligible`：2027届、硕士、4天/周、6个月、深圳及实习类型均符合；最低天数取4，不取5。 | `eligible`（总判断一致） | 7/7 一致 | `eligible`，7/7 一致 |
| ops | `ineligible`：到岗3天少于4天、可实习3个月少于4个月，深圳也不符合地点条件。 | `ineligible`（总判断一致） | 7/7 一致 | `ineligible`，7/7 一致 |

地点误读被最终结论掩盖：解析器为 `cities` 给出的出处是“工作地点：深圳南山区；面试地点：北京。”，把面试城市一起收入。tech仍因深圳命中而通过地点检查，ops对两个城市都不接受，故这两份档案的总判断没有变化；不能据此认为城市字段正确。

## 5. 公司官网风格 · 市场管培校招

[JD 原文](official_marketing_campus.txt) · [人工期望及逐字出处](official_marketing_campus.expected.json) · [完整 CLI 输出](actual/official_marketing_campus.json)

| 字段 | 期望值 | 当前 jd parse 的结果 | 结论 |
| --- | --- | --- | --- |
| `title` | `"市场管培生"` | `null` | 规则漏读 |
| `company` | `"示例远帆品牌管理有限公司"` | `"示例远帆品牌管理有限公司"` | 一致 |
| `cities` | `["上海"]` | `["上海"]` | 一致 |
| `remote` | `false` | `false` | 一致 |
| `employment_type` | `"campus"` | `"campus"` | 一致 |
| `salary` | `{"min":8000,"max":10000,"unit":"CNY/month","months":13,"negotiable":false}` | `{"min":8000,"max":10000,"unit":"CNY/month","months":null,"negotiable":false}` | 规则漏读 |
| `requirements.graduation` | `{"years":[2027],"strict":true}` | `{"years":[2027],"strict":true}` | 一致 |
| `requirements.days_per_week` | `null` | `null` | 一致 |
| `requirements.min_months` | `null` | `null` | 一致 |
| `requirements.education` | `{"min":"bachelor","preferred":null}` | `{"min":"bachelor","preferred":null}` | 一致 |
| `requirements.skills` | `["Excel","PowerPoint","市场调研","活动策划","商务沟通"]` | `[]` | 规则漏读 |
| `return_offer` | `null` | `null` | 一致 |
| `published_at` | `"2026-10-27"` | `"2026-10-27"` | 一致 |
| `deadline` | `"2026-11-20"` | `"2026-11-20"` | 一致 |

易错写法：“试用期3个月”；“每周五例会”；“3-5个工作日内回复”；“非外包；本岗位不承担销售指标。”。解读见期望文件的 `traps` 与 `fields.*.note`。

| 档案 | 人工结论与理由（运行前写定） | 实际过滤结论 | 七项状态对照 | 人工字段重放 |
| --- | --- | --- | --- | --- |
| tech | `ineligible`：校招类型和上海地点均冲突；到岗天数、最短实习时长未知；人工确认标题未命中排除词。 | `ineligible`（总判断一致） | 6/7 一致；`exclusions`：人工 `match`，实际 `unknown` | `ineligible`，7/7 一致 |
| ops | `needs_check`：已知届别、学历、上海地点和校招类型均符合；按现行七项契约，到岗天数和最短实习时长仍是unknown，故needs_check。试用期不是实习时长。 | `needs_check`（总判断一致） | 6/7 一致；`exclusions`：人工 `match`，实际 `unknown` | `needs_check`，7/7 一致 |

标题漏读使 `exclusions` 缺少标题证据，tech、ops都从人工的 `match` 变成实际的 `unknown`。tech已有地点/类型冲突，ops已有两项未知，因此总判断恰好未变；人工字段重放恢复了两项 `exclusions: match`。校招的到岗/实习时长是否应视为“不适用”属于后续匹配契约问题，本轮遵循现有文档，不把它登记为解析错误。

## 复现

在本分支根目录激活 `ai-job-search-cn` 后运行。以下代码仅把 CLI 的 JSON 输出交给 PowerShell 读取，不把 JD 正文经管道传给 Python；每次使用新的临时岗位库，避免此前人工补全影响比较。

```powershell
conda activate ai-job-search-cn
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$fixtureDir = 'tests/fixtures/cn/jd-m2-3'
$runData = Join-Path $env:TEMP ('cn-v2-replay-' + [guid]::NewGuid().ToString('N'))
foreach ($expectedFile in Get-ChildItem -LiteralPath $fixtureDir -Filter '*.expected.json') {
    $expected = Get-Content -Raw -Encoding UTF8 $expectedFile.FullName | ConvertFrom-Json
    $jdPath = Join-Path $fixtureDir $expected.fixture
    $parsed = python -m jobsearch_cn jd parse $jdPath --site $expected.site_argument --save --data-dir $runData | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'jd parse failed' }
    $parsed.jobs[0] | ConvertTo-Json -Depth 30
    foreach ($profileName in @('tech', 'ops')) {
        $profilePath = "tests/fixtures/cn/profile/$profileName/profile.json"
        python -m jobsearch_cn match filter $parsed.jobs[0].id --profile $profilePath --data-dir $runData
        if ($LASTEXITCODE -ne 0) { throw 'match filter failed' }
    }
}
```

人工字段重放：从该次 `parse.stdout.jobs[0]` 复制完整记录，将期望文件 `fields` 下每个路径的 `value` 写入；对应非空字段的 `evidence.<路径>` 写为 `{"text": <原片段列表>, "method": "agent"}`，空字段移除原规则出处。保持 `id/source/status/guard/raw_text` 原样，另存 UTF-8 JSON；按 [JD 导入工作流](../../../../docs/cn/jd-import.md) 先 `jd validate`、再向另一新 `--data-dir` 执行 `jd save`，对相同两份档案运行 `match filter`。本轮五份重放记录全部通过 Job Schema 校验。

## 验证记录

Python 3.12.15，代码基线 `34d254d72bc70795590918af3ae15db25b93c0dd`。本轮完整摘要见 [verification.json](verification.json)。

| 检查 | 结果 |
| --- | --- |
| `python tools/lint_skills.py` | exit=0；lint_skills: OK (11 skills, 12 commands, settings.json) |
| `python tools/security_guards.py` | exit=0；security_guards: OK (permissions allowlist, hooks allowlist, gitignore rules, package manifests, no tracked node_modules, skill/command allowed-tools, agent tools) |
| `python tools/check_framework_version.py` | exit=0；Comparing HEAD against base commit: HEAD; Framework Version Check: OK |
| `python -m unittest discover -s tests -t . -v` | exit=0；Ran 1009 tests in 98.462s; OK (skipped=9) |
| 五份人工字段重放记录 `jd validate` | 5/5 有效，出处均为原文逐字片段 |
| 人工字段出处 | 59 个片段逐字存在于相应 JD；所有城市、技能项在其各自出处中出现 |
| 冻结完整性 | 10/10 JD/期望文件 SHA-256 未变；契约文档和两份档案的匹配条件未变；完整档案版本变化另记摘要 |
| 编码与隐私 | UTF-8、无 BOM、LF 换行；除必要 LF 外无 Unicode Cc/Cf 控制或格式字符；五份 JD 无真实公司、人物、电话、邮箱、链接 |

执行位置：最终交付和验收均在用户指定的 `D:/06_Projects/ai-job-search-cn-codex`、分支 `codex/v2-m2-3-samples`。初期会话无该目录写权限，先在临时隔离检出中独立编写并冻结期望；权限恢复后逐字节复制冻结文件，停止旧权限下未完成的测试，在正式工作树重新执行全部验收。

## M2-3 规则扩充建议

下面仅根据原文与 CLI 的输入输出提出需求，未查看或修改实现。

| 类别 | 应补的词或语义 | 本轮依据 |
| --- | --- | --- |
| 产品 | Axure、Figma、PRD、需求分析、用户访谈 | 产品样例只读到SQL；5项漏读 |
| 内容运营 | 秀米、剪映、Photoshop、Excel、内容策划、文案写作、数据复盘 | 内容样例技能全部漏读 |
| UI 设计 | Figma、Sketch、Photoshop、交互设计、视觉设计、设计规范 | UI样例技能全部漏读 |
| 测试开发 | Playwright、Postman、接口测试、自动化测试 | 已读到TypeScript、Git，另4项漏读 |
| 市场 / 管培 | Excel、PowerPoint、市场调研、活动策划、商务沟通；标题“市场管培生” | 技能全部漏读；独立首行的岗位名未识别，导致排除检查unknown |
| 地点上下文 | 同一行内区分“工作地点”与“面试地点”，不能把整行城市都当工作城市 | 技术样例错误收入北京；产品/UI样例的分行面试地点处理正确 |
| 薪资组成 | 识别“8-10K/月，全年13薪”中的年发薪月数，保留月薪单位 | 月薪金额正确，salary.months漏掉13 |

技能共30个样例条目，仅识别3个（SQL、TypeScript、Git），漏27个条目，去重后是24个待补关键词。重复的Figma、Photoshop、Excel横跨方向，应共享词条；本轮没有覆盖别名、大小写、否定技能或“任选其一”的识别，不能据此宣称这些形式也已验证。

继续保留本轮已正确识别的边界：`2026届-2027届`、学历“优先”与最低学历分离、“每周五例会”不变成5天、“3-5个工作日内回复”不变成到岗天数、项目周期/试用期不变成最短实习期、`第十二届`不变毕业年、`非外包`不触发标题排除、否定远程/转正、4-5天取下限、波浪号小时薪资。扩词后既要消除8处差异，也要核对这些已正确的null和否定值不被破坏。

匹配验收应同时核对总判断、七项检查状态和每项引用的JD值/出处。本轮总判断10/10一致，仍掩盖1处错误工作城市和2处由标题漏读引起的检查状态差异；不应只用总判断做M2-3验收。
