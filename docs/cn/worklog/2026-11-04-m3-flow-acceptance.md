# 2026-11-04 · M3 整条流程工程验收（第一轮）

## 完成

本轮只验收已合并的简历流程与本地投递记录，不改实现、测试或冻结夹具。M3-6（PR #127）不在本轮范围，不能据本报告宣布 M3-5 或 v0.3.0 完成。

**结论：tech 完成导入 → 匹配 → 起草 → 真 Typst 生成 PDF/Word → 独立审核通过 → 投递预览与本地记录，materials_check=match。data、ops 完成生成及独立审核，但因稀疏夹具造成大块留白而保留 revise。未发现阻断 tech 主流程的 P1；发现 1 项 P2 功能缺口、1 项 P2 验收资料问题和 2 项 P3 验证/环境限制。**

- 验收基线：`origin/master` = `88271be20d281345d14b4c3340d15216981bad78`。
- 独立工作树：`tmp/m3-flow`，分支 `codex/m3-flow-acceptance`；审核使用同基线的独立工作树 `tmp/m3-flow-review`。
- 仅使用已公开的虚构夹具，所有运行数据放在本工作树 `data/<方向>/`，未读取、改动真实用户数据目录。
- 本轮交付物只有本报告；PDF、Word、档案、审核与投递数据库均为临时验收数据，不提交。

### 样本与范围

三份岗位原文均来自 `tests/fixtures/cn/messages-m3-4-holdout/contexts/<方向>/jd.txt`。尽管目录名带 holdout，这些文件在本轮基线上已经公开；本轮没有新增或修改留出样例。

| 方向 | 导入后岗位 id | 虚构岗位 | 最终使用的公开档案 |
| --- | --- | --- | --- |
| tech | `job_b508159d1f40` | 后端检索实习生 | `tests/fixtures/cn/material/tech-m3/profile/` |
| data | `job_b19be0526e50` | 数据清洗实习生 | `tests/fixtures/cn/messages-m3-4-holdout/contexts/data/profile/` |
| ops | `job_19de4d50476e` | 内容运营实习生 | `tests/fixtures/cn/messages-m3-4-holdout/contexts/ops/profile/` |

三个 JD 的公司、岗位均为原创虚构；均在广州、实习、日薪 180–240 元。届别、最低学历、每周到岗要求、持续月数和面试形式没有给出。tech 缺 Rust；data、ops 不增补档案里不存在的内容。

预检时 tech 也用同名 V23 上下文的精简档案跑过导入和规则评分；正式起草前改为复制现有 `material/tech-m3/profile/` 完整公开档案，以便主流程覆盖多条教育、实习、项目、技能和奖证。复制后重新校验、评分；没有修改任何夹具或在旧材料上替换摘要。

## 决策

1. 本次用户已明确授权虚构验收、先预览后提交本地投递记录、推送报告并开 PR。匹配确认采用原有档案权重，不改权重或硬性条件；“已投出”只作为临时数据库的测试设定，未联系招聘方。
2. 规则漏提薪资时按 `jd-import.md` 的补全步骤修正：`salary={"min":180,"max":240,"unit":"CNY/day","months":null,"negotiable":false}`，出处为 `{"text":"日薪：180-240 元。","method":"agent"}`。不改 id、来源、raw_text 或状态。
3. 经历评分由本轮起草上下文判断，并显式标记 `method=agent`：tech 85（检索评测与后端实习同类）；data 70（SQL 字段核对可迁移）；ops 75（运营内容草稿可迁移）。依据均引用 JD 的岗位行与档案经历 id，不冒充规则结果。
4. 简历审核由不继承起草对话的独立 Codex 子上下文完成，按 `resume-workflow.md` 第 2 节读取资料，`mode=independent`。每个上下文使用自己的工作树；审核者不改材料、不重新 build。该方式符合 `review-format.md` 对子代理独立审核的定义，但没有覆盖文档中“用户复制提示词另开会话”的界面交接。
5. tech 优先检索评测，再放后端接口与课程资料问答；保留两段教育、六项技能和奖证，未列低相关 PyTorch。data、ops 各只有一段项目，不为填满页面新增事实。三份简历来自不同虚构候选人，不能代替同一用户针对三个岗位的定制验收。

## 验证

### 环境与命令约定

Windows PowerShell，conda 环境 `ai-job-search-cn`（Python 3.12.15）。实际执行由临时 Python 驱动以该解释器逐条调用 CLI，捕获 UTF-8 stdout、stderr、退出码；临时驱动不提交。表中 `$D=data/<方向>`、`$J` 为上表对应 id，`$M=$D/materials/$J/resume-1.json`、`$R=$D/materials/$J/review-1-r1.json`。所有命令在临时工作树根目录执行。

Typst 使用已安装的 0.15.1 便携版，通过 `JOBSEARCH_CN_TYPST` 指定；不是 mock。PDF 使用 Noto Serif SC / Noto Sans SC，Word 使用等线。材料时间用本轮真实时刻与 `+08:00` 时区。

### 导入、匹配、起草和构建

| 顺序 | 实际命令（每个方向分别执行） | 结果 |
| --- | --- | --- |
| 1 | `python -m jobsearch_cn profile validate --data-dir $D` | 三份最终档案通过，退出 0 |
| 2 | `python -m jobsearch_cn profile show --data-dir $D`；读取 `$D/profile/notes.md` | 默认隐去联系方式，按原文选条目 |
| 3 | `python -m jobsearch_cn jd parse $D/inbox/jd.txt --save --data-dir $D` | 三条新岗位，退出 0；薪资漏提，见 P2-01 |
| 4 | `python -m jobsearch_cn jd show $J --data-dir $D` | 原文、地点、类型、技能可读；薪资为 null |
| 5 | `python -m jobsearch_cn match score $J --draft --data-dir $D` | 预检规则草稿；未直接拿来起草 |
| 6 | 按上述原文出处写 `$D/inbox/job-corrected.json` | 仅补 salary 与对应 evidence |
| 7 | `python -m jobsearch_cn jd validate $D/inbox/job-corrected.json` | 三份通过，退出 0；一次参数误用见下文 |
| 8 | `python -m jobsearch_cn jd save $D/inbox/job-corrected.json --data-dir $D` | 三份 updated，退出 0 |
| 9 | `python -m jobsearch_cn match score $J --draft --data-dir $D` | 按纠正后的 JD、最终档案重建草稿 |
| 10 | 补 `dimensions.experience` 后执行 `python -m jobsearch_cn match validate $D/matches/drafts/$J.json --data-dir $D` | 首次均退出 1，仅报 total 待更新；按文档原样抄报错给出的 total 后再次执行，均通过 |
| 11 | `python -m jobsearch_cn match save $D/matches/drafts/$J.json --data-dir $D` | 三条匹配记录保存成功，退出 0 |
| 12 | `python -m jobsearch_cn match list --data-dir $D`；`python -m jobsearch_cn match show $J --data-dir $D` | 记录均不过期；结论和缺口见下表 |
| 13 | `python -m jobsearch_cn match report $J --data-dir $D` | 各生成 HTML 与 CSV，退出 0；未把机器生成的反馈表当作用户反馈 |
| 14 | 写 `$M` | 有依据的简介、教育引用、经历要点、技能、奖证；未改档案 |
| 15 | `python -m jobsearch_cn material validate $M --data-dir $D` | 三份 valid=true，errors=[]，warnings=[]，退出 0 |
| 16 | `python -m jobsearch_cn resume build $M --data-dir $D` | 三份均退出 0，PDF + DOCX + build.json；problems=[]，warnings=[] |
| 17 | PDFium 渲染每个 PDF 为页面 PNG；pypdf 读取页数和文本层；打开 PNG 逐页检查 | 三份均 1 页、文本非空；tech 页面正常，data/ops 内容稀疏，见审核结论 |

操作偏差也保留：临时命令封装最初给 `jd validate` 多加了 `--data-dir`，三次退出 2；`jd save` 自带校验通过之后，补跑不带该参数的独立 `jd validate`，三次退出 0。另有三次探查夹具档案时误用 `profile show --profile <文件>`，退出 2；看 `profile show --help` 后改为位置参数 `profile show <文件>`，退出 0。这些是验收者参数误用，不计作实现缺陷，也不掩盖执行顺序偏差。

| 方向 | 技能 / 方向 / 经历 / 薪资 / 地点 | 总分、等级 | 完整性与待确认项 |
| --- | --- | --- | --- |
| tech | 50 / 100 / 85 / 100 / 100 | 81，strong | complete=true；过滤 needs_check；Rust 为缺口，JD 未给硬性要求须确认 |
| data | 80 / 100 / 70 / null / 100 | 85，strong | complete=false，缺 salary 维度；档案未给薪资偏好，JD 与档案到岗信息不足 |
| ops | 80 / 100 / 75 / null / 100 | 86，strong | complete=false，缺 salary 维度；档案未给薪资偏好，JD 硬性要求不足 |

“strong”并不表示硬性条件已确认；三个 `filter.verdict` 都是 `needs_check`。未把这些岗位当成已满足全部条件的真实推荐。

### 输出与独立核对

六个生成文件均存在；另用标准库检查 DOCX ZIP CRC 与每个 XML，三份都通过。`hashlib.sha256` 独立重算六个文件，均与对应 build.json 的 files 一致。最终档案 `profile.json`、`notes.md` 与所选公开夹具逐字节相同。

| 方向 | 输出 | 字节数 | SHA-256 |
| --- | --- | --- | --- |
| tech | PDF | 71040 | `254268879b9aa20e5fa097922b098dc6397ccc6e903700c032b288013049dcf3` |
| tech | DOCX | 2845 | `811828471f745a4d472580ba7a5e17c49457d81eae80eff93c963338cfee2c65` |
| data | PDF | 39011 | `b00da4f55c7cda3e7cff1111b1b2ac4d17f5a4e029415581718bdbb19e3338b0` |
| data | DOCX | 2315 | `ee52f9b099ac89309fc864389d1b9687cdeefdc37d58dcaca74abeb230b713b1` |
| ops | PDF | 40081 | `5a88331fa08ba36a17eaa0d6924f57617a0f8fc87f069ebe90a46201ab6985c1` |
| ops | DOCX | 2350 | `fc8e16f0f2d3296c3477d153d01ee4f28d8ac7615ac76aa56e76925eee019d9a` |

三份 PDF 均使用 `spaciness=1.5`，没有缩字号或二次压缩内容。输出路径均为 `$D/resumes/$J/resume-1.{pdf,docx,build.json}`。

附加尝试：PowerShell 启动独立不可见 Word 实例，调用 `Documents.Open(path, false, true, false)` 准备只读打开，再 `ComputeStatistics(2)` 和 `ExportAsFixedFormat(...,17)`。打开调用数分钟未返回，无页数或导出文件；中止该命令并按进程 id、名称、启动时间核对后，只终止本次启动的 Word 实例。没有改写 DOCX。该尝试不算原生 Word 页面验收通过，见 P3-02；机器文本校验与 ZIP/XML 通过不能替代用户在 Word/WPS 里实际查看。

### 可复核的起草输入

以下为实际进入 material validate / resume build 的三份材料（只含公开虚构夹具的引用和改写，不含联系方式）。日期和摘要保留本轮原值。

**tech**

```json
{
  "schema_version": 1,
  "kind": "resume",
  "job_id": "job_b508159d1f40",
  "profile_hash": "3b5cbef9bab820661299a6d82715f9c382679bb7e1adedee69e3a2671ec9e093",
  "created": "2026-11-04T17:47:15+08:00",
  "summary": {
    "text": "具备后端开发实习经历，使用Python编写检索评测脚本，并搭建过课程资料问答项目",
    "refs": [
      "exp-1",
      "proj-1"
    ]
  },
  "education": [
    {
      "ref": "edu-1",
      "courses": [
        "机器学习",
        "分布式系统",
        "数据库系统"
      ]
    },
    {
      "ref": "edu-2",
      "courses": []
    }
  ],
  "experience": [
    {
      "ref": "exp-1",
      "bullets": [
        {
          "text": "为内部RAG问答服务编写检索评测脚本（Python），覆盖300条测试问题",
          "refs": [
            "exp-1"
          ]
        },
        {
          "text": "使用Go重构订单查询接口，P99延迟从120ms降至45ms",
          "refs": [
            "exp-1"
          ]
        }
      ]
    },
    {
      "ref": "proj-1",
      "bullets": [
        {
          "text": "基于LangChain和MySQL搭建课程资料问答，支持20门课程的资料检索",
          "refs": [
            "proj-1"
          ]
        }
      ]
    }
  ],
  "skills": [
    "Python",
    "Go",
    "MySQL",
    "LangChain",
    "RAG",
    "Docker"
  ],
  "awards": [
    {
      "ref": "award-1"
    }
  ],
  "certificates": [
    {
      "ref": "cert-1"
    }
  ],
  "languages": [
    {
      "ref": "lang-1"
    }
  ]
}
```

**data**

```json
{
  "schema_version": 1,
  "kind": "resume",
  "job_id": "job_b19be0526e50",
  "profile_hash": "04e64fbae4c0a66ba20b3b127dccac1ff74b0a8f793fe1474561b1c2857d8c39",
  "created": "2026-11-04T17:47:23+08:00",
  "summary": {
    "text": "使用SQL核对数据字段，参与表格核对项目",
    "refs": [
      "proj-v23"
    ]
  },
  "education": [
    {
      "ref": "edu-v23",
      "courses": []
    }
  ],
  "experience": [
    {
      "ref": "proj-v23",
      "bullets": [
        {
          "text": "用SQL核对了6类数据字段",
          "refs": [
            "proj-v23"
          ]
        }
      ]
    }
  ],
  "skills": [
    "SQL"
  ],
  "awards": [],
  "certificates": [],
  "languages": []
}
```

**ops**

```json
{
  "schema_version": 1,
  "kind": "resume",
  "job_id": "job_19de4d50476e",
  "profile_hash": "497c5b9dcf76f81860eb8e2466f2ffe474f152a148f7f43a6dd24e7565f40d74",
  "created": "2026-11-04T17:47:27+08:00",
  "summary": {
    "text": "围绕新媒体运营整理内容草稿",
    "refs": [
      "proj-v23"
    ]
  },
  "education": [
    {
      "ref": "edu-v23",
      "courses": []
    }
  ],
  "experience": [
    {
      "ref": "proj-v23",
      "bullets": [
        {
          "text": "围绕新媒体运营整理了12份内容草稿",
          "refs": [
            "proj-v23"
          ]
        }
      ]
    }
  ],
  "skills": [
    "新媒体运营"
  ],
  "awards": [],
  "certificates": [],
  "languages": []
}
```

### 独立审核与投递记录

审核者在独立工作树分别执行以下命令（每组 6 条核心命令，共 18 条，均退出 0）：

```powershell
python -m jobsearch_cn profile show --data-dir $D
python -m jobsearch_cn jd show $J --data-dir $D
python -m jobsearch_cn match show $J --data-dir $D
python -m jobsearch_cn material validate $M --data-dir $D
python -m jobsearch_cn review draft $M --data-dir $D
# 审核者独立写 $R，再校验；review validate 不带 --data-dir
python -m jobsearch_cn review validate $R
```

审核者独立读取 notes.md、材料和 build 输出，实际查看三张页面。机器 coverage 初稿补充了学历、经验和岗位业务方向；未把 JD 没写的门槛当成已确认资格。另有一次附加文本提取因 conda 多行参数失败，改用单行包装后成功；不影响上述核心命令结果。

| 方向 | round / mode / verdict | 问题 | 关键词与事实结论 |
| --- | --- | --- | --- |
| tech | 1 / independent / pass | 0 must；2 suggest（E4） | Python、后端与检索经历有依据；Rust 为真实缺口，不补写 |
| data | 1 / independent / revise | 1 must（D5） | SQL 字段核对有依据；完整“数据清洗”经验仍是缺口，没有夸成清洗项目 |
| ops | 1 / independent / revise | 1 must（D5）；1 suggest（E4） | 只覆盖新媒体内容草稿整理，不扩展为发布、账号管理或增长成果 |

原始审核 JSON 从审核工作树原样复制到对应 `$D/materials/$J/review-1-r1.json`，起草者没有改审核结论；在起草工作树再次运行 `review validate $R` 和 `review show $R`，三份均退出 0。**review validate 通过只表示审核记录合法，不把 data/ops 的 revise 变成 pass。**

tech 的两条建议：把“为内部RAG问答服务编写……”改成“编写内部RAG问答服务的……”；把“基于LangChain和MySQL搭建……”改成“使用LangChain和MySQL搭建……”。两条均属 E4，原文已准确易懂，本轮保留业务对象、技术背景在前的写法，不采纳、不改材料，所以无需第二轮。ops 同类建议为把“围绕新媒体运营整理了12份内容草稿”改为“整理新媒体运营内容草稿，共12份”；保留为未采纳建议。

data/ops 的 D5 必改项保留：唯一项目已完整列出，没有更多经过确认的事实可补；不为消除留白扩写无依据内容、不用无修改的第二轮制造“通过”。本轮未给这两份记投递，正式验收前需补足资料。三组均仅审 1 轮，没有超过 2 轮上限。

tech 投递先执行 `application list --job $J --data-dir $D`（无记录），再预览：

```powershell
python -m jobsearch_cn application record $J --channel other --platform 公开夹具工程验收 --submitted --on 2026-11-04 --material $M --sent $D/resumes/$J/resume-1.pdf --sent $D/resumes/$J/resume-1.docx --actor codex --preview --data-dir $D
```

预览退出 0：`status={"from":null,"to":"applied"}`，两条事件为 `created`、`submitted`，`materials_check=match`，`warnings=[]`；列出材料 JSON、PDF、Word 的 SHA-256 与大小。预览前后对数据目录的文件清单检查没有新增文件，也未建投递数据库。预览 request_id 为 `req_57375887c6440fcb3630a34471a81a9f`。

把上述事件、状态及核对结果说明后，按本次用户明确授权，用完全相同参数将 `--preview` 换为 `--request-id req_57375887c6440fcb3630a34471a81a9f` 写入。退出 0，实际结果：

```json
{
  "application_id": "app_e657c232da4d8a20bbcba3c7a5aadb5d",
  "revision": 2,
  "status": "applied",
  "submission": {
    "confirmed": true,
    "occurred_at": null,
    "occurred_on": "2026-11-04",
    "materials_recorded": true,
    "materials_check": "match"
  },
  "event_types": ["created", "submitted"],
  "review_path": "materials/job_b508159d1f40/review-1-r1.json"
}
```

`review_path` 在实际结果的 `material_versions[0]` 内，上面仅为摘录，非改写 Application Schema。确认来源是虚构验收任务，不是真实发出的申请。

随后执行（`$A` 为上面的 application_id）：

```powershell
python -m jobsearch_cn application show $A --data-dir $D
python -m jobsearch_cn application validate --data-dir $D
python -m jobsearch_cn application list --job $J --data-dir $D
python -m jobsearch_cn application export $A --out m3-flow.json --data-dir $D
# 原 record 命令、相同 request_id 再执行一次
python -m jobsearch_cn application list --job $J --data-dir $D
```

全部退出 0。`application validate` 为 `valid=true, errors=[], warnings=[], orphans=[]`；导出结果仍为 `materials_check=match`。相同请求重试返回 `repeated=true`，列表仍只有同一条投递、revision=2。

独立按归档记录逐个读取材料、sent-1.pdf、sent-2.docx，以及首次投出的 job.json / match.json 快照：五个文件存在，SHA-256 都与记录一致，三份材料文件的大小也一致；PDF/Word 摘要就是前文输出表中的 tech 两行。审核 material_hash、build material_hash 与投递 material_versions[0].material_hash 均为 `a614cc74fae80269339180dee08ea1ca8e71237511dfc6db2b8b5125c2d011b6`。

### 提交前检查

- `python tools/lint_skills.py`：通过，14 skills / 12 commands。
- `python tools/security_guards.py`：通过。
- `python -m unittest discover -s tests -t .`：退出 0，`Ran 1740 tests in 378.563s`，`OK (skipped=14)`。本轮三个 resume build 均实际使用 Typst，不是跳过的渲染测试。
- 请求审核前重新 fetch，`origin/master` 仍为验收基线；本报告以该基线提交。本轮无实现改动，不存在验证本轮自写实现的情况。
- 提交范围仅本报告；临时输入、驱动、日志、材料和二进制产物不入 git。交付后移除本轮两个临时工作树。

## 遗留

优先级：P1 为阻断主流程或事实/数据完整性风险；P2 为有绕行办法的功能缺口或会影响正式验收判断的问题；P3 为文档、操作或环境可用性问题。以下仅报告，不在本 PR 修实现。

| 编号 | 分级 | 发现、证据与影响 | 本轮处理 / 建议 |
| --- | --- | --- | --- |
| P2-01 | P2 | 三份 JD 的 `日薪：180-240 元。` 被解析为 salary=null；未补全时匹配理由写“JD 没写薪资”，与原文不符 | 用 agent 原文证据补全，jd validate/save 后恢复；后续补规则或明确此写法需人工补全 |
| P2-02 | P2（验收资料） | data/ops 各只有一段项目，PDF 下半页大块留白；独立审核按 D5 判 must。不是崩溃，也不代表可交付的三份简历已完成 | 不补造经历；本轮保留 revise，正式 M3-5 需更完整且经用户确认的档案和三个真实目标岗位 |
| P3-01 | P3 | Codex 文档要求用户复制提示词另开会话，review-format 又允许独立子代理；本轮用隔离子上下文完成，未覆盖手动会话交接 | 正式验收选定并记录实际入口；不把此轮替代路径算作手动交接已验 |
| P3-02 | P3（环境） | 额外 Word COM 只读打开没有返回，未取得原生页数或页面；未定位为 DOCX 实现缺陷 | 本轮只确认 DOCX 生成、CRC/XML 可读及构建时文字一致；Word/WPS 原生打开留给 M3-5 |

## 下一步

1. 规划者审核本报告及问题分级，决定需要先修哪些问题。
2. PR #127 合并后做第二轮：补 M3-6 沟通草稿，重点核对邮件 G3（和简历一致）及“简历见附件”；再串一次审核和 materials_check。
3. M3-5 仍需真实用户档案、三个目标岗位、三份有针对性且可追溯的简历，用户本人打开确认，并至少用一份真实投递。本轮没有满足或模拟替代该真实投递门槛。
