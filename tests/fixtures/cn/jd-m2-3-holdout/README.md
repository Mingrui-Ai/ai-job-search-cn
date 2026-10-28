# V4 · M2-3 留出样例

五份全新原创虚构 JD；不对应真实公司、岗位或个人。期望采用 Job Schema v1 和 match.md 已实现的硬性条件契约。已先冻结并建立 master 基线，再按用户通知完成 PR #26 收尾分支重跑，结果见[收尾前后对照](comparison.md)。下文保留首轮基线记录。

| 文件前缀 | 方向 | 非技术 | 主要覆盖 |
| --- | --- | --- | --- |
| boss_data_analysis_intern | 数据分析 | 否 | 标题单独技能、否定技能、公众号页脚、PowerBI、base 深圳 |
| official_finance_campus | 财务 | 是 | 15-25K·14薪、多城市、Power BI、软届别、否定技能、试用期/周五/回复时间 |
| shixiseng_hr_intern | 人力资源 | 是 | 标题 PPT 与正文 PowerPoint、否定工具/职责、远程与城市交集 |
| boss_business_development_intern | 商务拓展 | 是 | 标题排除与正文否定、PPT、城市任选、到岗区间、最低学历与偏好 |
| ats_backend_intern | 后端 | 否 | 标题单独 Java、技能任选其一、K8s/Kubernetes、否定技能、页脚平台名 |

每份 `*.expected.json` 包含 14 个字段组、逐字出处、易错片段解释，以及 tech / ops 两份示例档案的人工总判断和七项状态理由。`oracle-manifest.json` 保存所有 JD/期望和契约/档案的 SHA-256，及冻结时间、基线代码提交和比较口径。

技能只取正文正向提及，并保留原文写法；比较忽略大小写与空格，不依赖词表，也不把两个不同拼写的同义词自动合并。任选其一的正向技能都保存在当前 Schema 的扁平列表里，不代表全部必需，OR 关系无法表达的限制已逐份注明。页脚平台、否定技能及仅标题出现的技能不收。

校招缺每周天数/实习月数时，本轮仍采用已实现契约的 `unknown`；不使用 M2-4 设计稿的 `not_applicable`。字段组、总判断和七项状态单独计数，不用总体结论掩盖逐项差异。

独立性边界：本轮没有查看解析/匹配源码、现有 JD 测试或执行者收尾分支。当前对话此前的 M1-6 工作曾接触解析器及测试，因此不宣称完全无源码先验。本批人工期望先写定并冻结，再首次执行本批规则；具体记录见 manifest。

## 冻结与 master 基线

人工期望冻结于 2026-10-28 07:32:53 UTC，先提交为 `900828f3485b4a38e1227dfdc11784e6675200e4`，再于 07:36:01–07:36:06 UTC 首次运行本批规则。运行代码为新分支创建时最新的 `origin/master`：`143c48265c2db870c307e29cff71caaf92ddbb67`。运行前后 `jobsearch_cn/` 与该提交没有差异。

冻结 manifest 的 SHA-256 为 `0f3b7a606a82c005f72624b5a09197fd6c3036bca58dc7555a1fb3fbce49db62`。10 个 JD/期望文件与 4 个契约/档案的哈希在运行前后均未变化。冻结文件不因实测结果回填；本目录的 `.gitattributes` 固定 LF，避免 Windows 检出换行转换改变 JD/期望的字节哈希。

原始 CLI 输出、逐字段比较、两份档案的总判断与七项状态均保存在 [actual/master/](actual/master/)；机器可读汇总见 [summary.json](actual/master/summary.json)，复核记录见 [verification.json](verification.json)。所有内容来自本批虚构样例，不含真实求职数据。

| 指标 | master 基线 |
| --- | --- |
| 字段组完全一致 | 65/70（92.9%） |
| 仅漏读 / 仅多读 / 错误或漏读与多读并存的字段组 | 0 / 1 / 4 |
| 人工正向技能命中 | 12/20（60.0%） |
| 漏读 / 多读技能 | 8 / 14 |
| 实际技能中有人工依据的比例 | 12/26（46.2%） |
| 解析结果上的总判断一致 | 10/10 |
| 解析结果上的七项状态一致 | 70/70 |
| 人工字段单独回放的总判断 / 七项状态一致 | 10/10、70/70 |

每份 JD 均有 13/14 个字段组一致；五处差异全部位于 `requirements.skills`。按每个 JD 内的技能集合分别计数，跨 JD 重复出现的技能仍各算一次。PowerBI 与 Power BI 按冻结口径视为相同；PPT/PowerPoint 和 K8s/Kubernetes 不作同义词合并。

| 方向 | 技能命中/期望数 | 漏读 | 多读 | 字段差异分类 |
| --- | --- | --- | --- | --- |
| 数据分析 | 3/4 | 数据清洗 | Tableau、数据分析、Python、公众号 | wrong |
| 财务 | 2/4 | 财务分析、PowerPoint | SQL、Python | wrong |
| 人力资源 | 1/3 | 招聘流程、PowerPoint | 剪映、Photoshop、公众号 | wrong |
| 商务拓展 | 1/4 | 客户访谈、CRM、PPT | SQL | wrong |
| 后端 | 5/5 | 无 | Java、Rust、C++、公众号 | extra |

从输入和输出对照可确认，标题单独出现的词、明确否定的技能、页脚公众号仍会进入技能列表，若干正文正向技能未被识别。此结论只描述本批黑盒输出，不推断源码中的具体成因。后端的两个任选技能与两种 Kubernetes 写法均命中；Schema 的扁平技能列表仍不能表达 OR 条件。

非技能字段在本批中全部一致，包括月薪区间与 14 薪、多工作城市、base 深圳、否定远程、学历最低要求与偏好、届别软偏好，以及校招正文里容易误当实习条件的时间表达。不能据此推广为所有写法均已覆盖。

## 总判断与七项状态

下表同时是冻结人工期望和 master 实际状态；所有单元格相同。`M` = `match`，`C` = `conflict`，`U` = `unknown`。逐项人工理由、规则输出及出处保存在 expected 与 actual 文件里。

| 方向 | 档案 | 届别 | 学历 | 每周天数 | 实习月数 | 地点 | 类型 | 排除项 | 总判断 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 数据分析 | tech | M | M | M | M | M | M | M | eligible |
| 数据分析 | ops | M | M | C | C | C | M | M | ineligible |
| 财务 | tech | M | M | U | U | M | C | M | ineligible |
| 财务 | ops | M | M | U | U | M | M | M | needs_check |
| 人力资源 | tech | M | M | M | M | M | M | M | eligible |
| 人力资源 | ops | M | M | M | M | M | M | M | eligible |
| 商务拓展 | tech | M | M | M | M | M | M | C | ineligible |
| 商务拓展 | ops | M | M | M | M | M | M | M | eligible |
| 后端 | tech | C | M | M | M | M | M | M | ineligible |
| 后端 | ops | C | C | C | C | C | M | M | ineligible |

技能不参与当前七项硬性过滤，所以总判断 10/10、状态 70/70 不代表技能提取正确，也不等于岗位适合度评分。另将冻结人工字段写入独立临时存储并验证后回放 `match filter`，结果也是 10/10、70/70；该回放没有覆盖或修正解析器首次输出。

## 复核方法

使用 conda 环境 `ai-job-search-cn`（Python 3.12.15），仅通过公开 CLI 运行；无需阅读解析器、匹配器或既有 JD 测试源码。运行前先复核 manifest 中的文件哈希，代码检出基线提交，fixture 保持本分支的冻结版本。契约/档案哈希记录的是冻结时工作副本字节；如其他平台发生换行转换，应先检查这一差异，不修改 manifest。

以下 PowerShell 示例会在一个新的、被 git 忽略的临时目录重跑五份 JD 和十组过滤。它不覆盖已保存的首轮基线。将输出按 manifest 的比较口径与 `*.expected.json` 对照，分别统计 14 个字段组、总判断和七项状态。

```powershell
conda activate ai-job-search-cn
$env:PYTHONIOENCODING = 'utf-8'
$fixtureDir = 'tests/fixtures/cn/jd-m2-3-holdout'
$runDir = Join-Path 'data/v4-recheck' ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $runDir | Out-Null
$utf8 = [System.Text.UTF8Encoding]::new($false)
Get-ChildItem "$fixtureDir/*.expected.json" | ForEach-Object {
    $oracle = Get-Content $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $stem = [IO.Path]::GetFileNameWithoutExtension($oracle.fixture)
    $jd = Join-Path $fixtureDir $oracle.fixture
    $parsed = python -m jobsearch_cn jd parse $jd --site $oracle.site_argument --save --data-dir $runDir
    if ($LASTEXITCODE -ne 0) { throw "parse failed: $stem" }
    $parsedText = $parsed -join "`n"
    [IO.File]::WriteAllText((Join-Path $runDir "$stem.parse.json"), $parsedText, $utf8)
    $jobId = ($parsedText | ConvertFrom-Json).jobs[0].id
    foreach ($profileName in 'tech', 'ops') {
        $profile = "tests/fixtures/cn/profile/$profileName/profile.json"
        $filtered = python -m jobsearch_cn match filter $jobId --profile $profile --data-dir $runDir
        if ($LASTEXITCODE -ne 0) { throw "filter failed: $stem / $profileName" }
        [IO.File]::WriteAllText((Join-Path $runDir "$stem.$profileName.match.json"), ($filtered -join "`n"), $utf8)
    }
}
```

人工字段回放另外使用新的存储：复制解析记录，将 14 个字段替换成冻结 `fields.*.value`，相应出处取冻结 `fields.*.evidence`、标记 `method: agent`；未知字段删除该字段的出处。随后依次执行 `jd validate`、`jd save --data-dir <独立目录>`、两份档案的 `match filter --data-dir <独立目录>`。保留此结果与原始解析结果的区别，不修改期望。

提交前检查：`python tools/lint_skills.py`、`python tools/security_guards.py` 均通过；`python -m unittest discover -s tests -t .` 通过，1021 项、9 项跳过。新增内容仅为虚构夹具、基线结果、报告及局部换行设置，没有修改应用代码或现有 JD 测试。

## 后续边界

首轮冻结与 master 基线完成时没有推送、开 PR。用户随后通知 PR #26 已开出，并授权重跑、推送和开 PR；现已完成 `9939502` 对照，新增快照位于 `actual/wrapup-9939502/`，原始基线未覆盖。剩余多读、漏读列在对照报告中，由规划者按路线图处置，冻结期望未回填。
