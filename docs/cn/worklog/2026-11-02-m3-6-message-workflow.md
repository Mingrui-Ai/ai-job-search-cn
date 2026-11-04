# 2026-11-02 M3-6 沟通草稿接进工作流（Claude C，只写设计）

分支 `feat/cn-m3-6-message-workflow`，从 `origin/master`（aafa58b）开。规划者 cn-fa 派活：本轮目标是一个岗位走完"匹配确认 → 简历起草 → 独立审核 → Word/PDF 输出 → 沟通草稿"，这是最后一段。M3-4（Claude B）和 M3-3c（Claude A）都合并后才写代码，现在只出设计。

依据（只读，用 `git show` 看）：
- `origin/feat/cn-m3-3c-workflow`：`docs/cn/resume-workflow.md`、`.claude/skills/cn-resume/SKILL.md`、`.claude/agents/cn-resume-reviewer.md`、`.dsh/skills/cn-resume/SKILL.md`、`AGENTS.md` 和 `tools/security_guards.py` 的改动；
- `origin/feat/cn-m3-4-templates`：设计稿 `docs/cn/worklog/2026-11-01-m3-4-templates.md`，以及已经写好的 `material template`、`material render`、`messages.py`；
- master：路线图 M3-4 的裁定、`docs/cn/review-checklist.md`、`docs/cn/review-format.md`。

**名字以 M3-4 分支为准**：渲染命令是 `material render`，不是 `message render`。它先做和 `material validate` 一样的检查，通过后把纯文本打到标准输出，不写文件。

## 规划者裁定（cn-fa，2026-11-02）

1. 默认按渠道选一种，看不出来再问：同意。交付时告诉用户选了哪种、为什么选，要别的就说一声。
2. 入口并进 `cn-resume` 和 `resume-workflow.md`（新增"沟通草稿"一节），不另开技能：同意。
3. `material render --output` 在 M3-6 里加，不加进 M3-4（M3-4 范围不再变动，V23 按原设计冻结）。
4. 三种材料都走独立审核，最多 2 轮：同意。用户明确说不审时，按现有的 `mode=self` 记为自审（`review validate` 会给警告），交付时说明。
5. 沟通草稿引用 `notes.md`：第一版不做，规划者记进路线图"待办"；M3-5 验收时经理要写求职动机，再按简介的规则安排。
6. G1–G5 写进 `review-checklist.md`，Review v1 的几处改动也由 M3-6 的 PR 改：同意（#116 合并后才开工，不和 Claude A 同时改）。
- `review draft` 和 `_check_material` 的统一由 Claude B 在 M3-4 合 master 时做；M3-6 在 M3-4 合并后的基础上开工。
- `security_guards.py` 里 `material:*` 那句注释：实现时用 AskUserQuestion 请经理本人同意再改。
- 实现要等 #116（M3-3c）和 M3-4 都合并后再开，不叠在没合并的分支上。

## 设计

### 1. 在流程里的位置，起草哪几种

- **两种入口**：
  1. **接在简历后面**（默认）：简历审核通过、交给用户的时候，问一句"要不要起草沟通的话"，按下面的规则建议起草哪一种。
  2. **单独起草**：用户只要一段打招呼语也可以，不必先做简历。BOSS 直聘这类平台通常先打招呼，对方回复了才发简历，所以单独起草是常见用法，不是例外。前提和简历工作流相同：岗位已入库，档案通过检查，匹配记录没过期（`profile_hash` 从匹配记录抄）。
- **默认只起草一种**，按投递渠道选：
  - 岗位的 `site` 是 `boss`、`shixiseng`、`nowcoder`、`liepin`、`zhaopin`、`51job`、`lagou` 这类平台：打招呼语（`greeting`）；
  - JD 里写了投递邮箱：投递邮件（`email`）；
  - `site` 是 `referral`，或者用户说有人能内推：内推请求（`referral`）。
  - 看不出来时问用户。用户点名要几种就起草几种，一种一个文件。
- **和简历对齐**：这个岗位已经有审核通过的简历时，沟通草稿的经历段（`evidence`）只从这份简历列出的经历里选，数字和说法与简历一致。`email` 里写"附件是我的简历"，只在简历已经生成、审核通过时才写。没有简历时（单独起草）不受这条约束，但不写附件。

### 2. 命令链

| 步骤 | 谁做 | 输入 | 输出 |
| --- | --- | --- | --- |
| 0. 读资料 | 起草者 | `jd show`、`match show`、`profile show`、`notes.md`；有简历时，这个岗位最后一份审核通过的 `resume-<n>.json` | — |
| 1. 选模板 | 起草者 | `material template <岗位id> --kind K [--direction D]` | 标准输出：模板的槽位、字数上限、写法提示、选它的理由（JSON） |
| 2. 起草 | 起草者 | 模板、资料 | `data/materials/<岗位id>/<kind>-<n>.json`（Material v1，M3-4 的格式） |
| 3. 检查 | 起草者 | `material validate <材料>` | 错误就改到通过；警告逐条处理，或者记下理由 |
| 4. 渲染 | 起草者 | `material render <材料> --output`（新增，见下） | `data/messages/<岗位id>/<kind>-<n>.txt`；标准输出只给路径、字数和警告 |
| 5. 审核 | 审核者 | 见第 3 节 | `data/materials/<岗位id>/review-<kind>-<n>-r<k>.json` |
| 6. 交给用户 | 起草者 | 见第 5 节 | — |

**新增 `--output`**：`material render` 现在把正文打到标准输出。投递邮件的签名里有手机号和邮箱，打到标准输出就会进 Agent 的上下文；简历工作流的规矩是"回复和文件里都不出现联系方式"，联系方式只由程序从档案取。所以工作流里一律用 `--output`：
- 写 `<数据目录>/messages/<岗位id>/<kind>-<n>.txt`，`n` 和材料文件名里的一样；
- 写法同 `resume build`：先写临时文件再改名，输出位置是链接时拒绝；
- 标准输出给 `{"text": 路径, "chars": 字数, "warnings": [...]}`，不含正文。

不加 `--output` 时仍然打到标准输出，留给用户自己在终端里用。

### 3. 审核：走独立审核，最多 2 轮

**要独立审核。** 理由：
- 沟通的话是招聘方最先读到的；"参与"写成"负责"、团队成果写成个人成果，这类夸大和简历一样会出问题。机器只查数字、技能、字数和禁用词，查不出意思上的升级。
- 文字短，审一轮花的时间少。

做法和简历相同（`resume-workflow.md` 第 2、3 节）：
- Claude Code 派子代理，Codex 和 dsh 另开会话，用户不想另开时才自审（标 `self`）；
- 最多 2 轮，第 2 轮只看改动；
- 简历和沟通草稿一起做时，**各审各的**，一份材料一个审核结果，可以在同一次派活里交给同一个审核者。

**适用的已有条目**：A2、A5、B1–B5、E1、E2、E5、E6、F2、F3。不适用的：C1、C2（关键词覆盖表）和 D（版面）。C4"缺口不藏也不硬补"改由 G4 覆盖。

**新增 G 类"沟通草稿"**：

- **G1** `机器` `material validate` 通过（M3-4 的检查）。涵盖：
  - 槽位齐全、顺序对；
  - 引用都在，用到占位符的段引用了它所属的条目；
  - 没有编造数字和技能；
  - 代入后不超过字数上限；
  - 没有禁用说法，没有手写的联系方式；
  - 承诺的到岗时间、每周天数和档案一致。

  审核者核对结果，不重复查这些。
- **G2** `机器` `material render --output` 成功（没有剩下的占位符），警告逐条处理：改掉，或者写明理由。警告包括套话、打招呼语里的链接、内推请求里的薪资、模板版本变了。
- **G3** `审核` 经历段选的是和这个岗位最相关的一两条；有审核通过的简历时，只从简历列出的经历里选，数字和说法与简历一致。邮件提到附件，必须简历已经生成并通过。
- **G4** `审核` 缺口不写成会，也不编。可以用相邻的经历回应（"做过相近的 X"），但不写"熟悉 Y"。
- **G5** `审核` 语气合乎这种材料：
  - 打招呼语短而直接；
  - 邮件有称呼，标题照模板；
  - 内推请求说清岗位和理由，对方能直接转发，不施压。

  三种都不卑微，不写用户没提过的薪资、加班、到岗承诺。

**审核结果的格式**：沿用 Review v1，以下几处要改（实现时改 `review.py` 和 `review-format.md`，原文是 Claude A 的，改动在 PR 里写明）：
- 文件名是 `review-<kind>-<n>-r<k>.json`；
- `path` 可以是 `segments[i].text`、`subject.text`；
- 这三种材料不要求关键词覆盖表（写 `[]`）；
- `review draft` 对这三种只出标点和空格的警告（E1、E3），不出覆盖表。

**合并时要修的一处衔接**（谁后合并谁修）：master 上的 `review draft` 直接调用 `material.validate`；M3-4 分支上，按种类分派的是 cli 的 `_check_material`。三种沟通材料走到 `review draft` 时，要改成同一个分派。#115 加的 `notes` 参数也要传进 `_check_material`。

### 4. 入口和授权

**建议并进简历工作流，不另开技能。**
- `resume-workflow.md` 加一节"沟通草稿"，写第 1、2、5 节的步骤；审核和停止引用原有的第 2、3 节，只写差别。
- `cn-resume` 技能（`.claude` 和 `.dsh` 两份）的描述和触发词加上"打招呼语、投递邮件、内推、沟通的话"。
- 审核子代理 `cn-resume-reviewer` 的描述从"一份简历材料"改成"一份简历或沟通材料"。
- `AGENTS.md` 的"生成简历"一段改成"生成简历和沟通草稿"，指向同一份文档。

理由：
1. 本轮目标就是一个岗位走完一条线，前提、读的资料、审核方式、停止规则都相同；
2. 少一个入口，Claude Code、Codex、dsh 三处要同步的说明也少一份；
3. 用到的命令都在 `material:*`、`review:*` 底下，M3-3c 已经放进允许列表，不用加新的授权。

另开 `cn-message` 技能的好处只是名字更贴切，代价是两份几乎相同的前提和审核说明。

**授权**：
- `.claude/settings.json` 和 `tools/security_guards.py` 的规则都不用改：`Bash(python -m jobsearch_cn material:*)` 已经允许 `material template`、`material render`。
- 但 `security_guards.py` 里这条规则的注释写的是"material validate … only print"。`--output` 会写 `<数据目录>/messages/` 下的文本文件，这句注释要跟着改。只改注释，不改规则；实现时也要先用 AskUserQuestion 请经理本人同意。
- 审核子代理的 Bash 同样受这份允许列表限制，`material render` 也在列表里，所以工作流里写明：审核者不运行 `material render`（和不运行 `resume build` 同理，它会改文件）。

### 5. 交给用户的东西

- 纯文本：`data/messages/<岗位id>/<kind>-<n>.txt`，UTF-8。
  - 打招呼语是一段；
  - 内推请求一段一行；
  - 邮件第一行是"标题：…"，空一行接正文（M3-4 `render` 现在的格式）。
- 起草者告诉用户文件路径，请用户打开文件复制（Windows 可以直接用记事本打开）。回复里**不贴正文**：邮件的签名有联系方式，三种一律不贴，规矩简单。用户想在对话里看到正文，可以自己运行 `! python -m jobsearch_cn material render <材料>`。
- 同时交代：
  - 字数；
  - 最后一轮审核的摘要（`review show`）；
  - 没采纳的建议和理由；
  - 是不是自审；
  - 邮件要附哪份简历（`resume build` 输出的 PDF 路径），由用户自己附。
- **不自动发送**：不调邮件客户端，不打开招聘网站，不往剪贴板写东西，不联网。

### 5b. 和投递记录的接口（规划者 2026-11-03 追加）

M4-1（投递记录，Claude A）投出时要核对：实际发出的文件，和审核通过的材料是不是同一版。

- `resume build` 会在 PDF 旁边写一个小的说明文件，至少记 `material_hash`、`profile_hash` 和生成时间。格式由 Claude A 在 `docs/cn/applications.md` 里定。
- `material render --output` 写 `.txt` 时，照同样的格式在旁边写一份。
- 开工时以 master 上的格式为准。那时 M4-1a 还没合并的话，先告诉规划者，由规划者协调先后。
- 测试：说明文件的 `material_hash` 等于 `review draft` 给的值；材料改了再渲染，`material_hash` 跟着变。

### 6. 验收

**本项（实现 PR）**，用公开的虚构夹具（M3-4 带来的 `tests/fixtures/cn/material/tech-m3/`，以及 `ops-m3/`）：
- **单元测试**：
  - `material render --output` 写对位置，内容等于 `render` 的结果；拒绝链接；标准输出没有正文和联系方式；
  - `review draft`、`review validate` 能处理三种沟通材料（`segments[i].text` 这类路径、`[]` 的覆盖表、文件名）；
  - `review draft` 和 `material validate` 对同一份沟通材料的结论相同；
  - `test_cn_agent_entry` 跟着技能描述、触发词和 `AGENTS.md` 改。
- **手动走一遍**（在 Claude Code，临时数据目录，tech-m3 夹具）：
  - 从起草打招呼语开始，派审核子代理，渲染，交给用户；
  - 再走一遍"简历通过后起草邮件"，看 G3 和附件那一句；
  - 过程记进工作记录。

**Codex A 的整条流程验收**（M3-4、M3-3c、本项都合并后），在 Codex 里用一个虚构岗位走完五段，看：
1. 每一步的命令和输出与文档一致，没有文档外的步骤；
2. 文件只写在 `data/materials/`、`data/resumes/`、`data/messages/` 下，档案没被改；
3. 每个审核结果都通过 `review validate`，轮数不超过 2，审核是另开的会话（或标了 `self`）；
4. 沟通草稿的经历和数字与通过的简历一致（G3）；
5. 对话记录、材料、审核结果里都没有联系方式，只有 `.txt` 和 PDF/Word 里有；
6. 没有联网，没有自动发送；
7. 交给用户的内容齐全：路径、字数、审核摘要、要附的简历；
8. 记下每段花的时间，供 M3-5 参考。

## 要规划者裁定的问题

1. **默认起草哪一种**：按 `site` 和 JD 里的投递邮箱选一种，看不出来就问。可以吗？还是每次都先问用户？
2. **入口**：并进 `cn-resume` 和 `resume-workflow.md`（建议），还是另开 `cn-message` 技能？
3. **`material render --output`**：由 Claude B 在 M3-4 里加，还是本项实现时加？我倾向于 M3-4 还没合并就请 Claude B 加，这样 V23 的对照也包括它；已经合并了就由本项加。
4. **审核**：三种都走独立审核、最多 2 轮（建议）；还是打招呼语只做机器检查加自审？
5. **沟通草稿能不能引 `notes.md`**：邮件和内推请求常写求职动机（例如 `notes.md` 里"希望做有真实用户的线上服务"）。M3-4 的 `refs` 现在不收 `notes.md`。要不要按简介的规则放开（只限动机、结尾这类槽位，"偏好记录"除外）？这要改 M3-4 的检查，属于 Claude B 的范围。
6. **G 类条目的编号和措辞**：G1–G5 加进 `review-checklist.md` §2，原文是 Claude A 的，由本项的 PR 改，可以吗？

## 进展

- 2026-11-02：开分支，读依据，写设计，发给规划者 cn-fa。规划者裁定（见上），等 #116 和 M3-4 合并后实现。
- 2026-11-03：规划者追加接口要求，写进第 5b 节（a274df2）。

## 存档（2026-11-03 收工，经理叫停）

**做到哪**

- M3-6：只有设计，没写代码。本分支 `feat/cn-m3-6-message-workflow`，a274df2，已推送，工作区干净。
- #119（P3 整理，分支 `fix/cn-m3-p3-cleanup`，5b91525）：已送 Codex B 审核，和 #118 一起排队。送审期间不推送。

**下一步**

1. 等 #119 的审核：有 P1、P2 就修，P3 不修；修完跑三项检查，推送一次，回报规划者。
2. M3-6 开工的条件：#116 已合并；还要等 M3-4（Claude B）合并。开工时从最新的 master 另开实现分支，或者把本分支合入 master 后接着做。
3. 开工时先看 master 上有没有 `docs/cn/applications.md` 的说明文件格式（M4-1a）。没有就先告诉规划者。

**还没定的**

- 无待裁定的问题。`notes.md` 用于沟通草稿，第一版不做，规划者记在路线图待办里。

## 实现计划（2026-11-04，Claude C，未写代码）

基线：本分支已合入 origin/master（a08cade，含 M3-4 #123、M4-1a）。现状要点：`review.KINDS` 只有 `resume-review`；`review draft` 遇到沟通材料直接报错（cli.py `cmd_review_draft`，注释写"由 M3-6 定"）；`resume build` 的说明文件由 cli.py 里写 `resume-<n>.build.json` 的函数生成，格式见 `applications.md` 第 12 节。

### 步骤（每步一个提交，跑三项检查后再进下一步）

1. **`material render --output`**（`cli.py`、`material`/`messages` 渲染不动）
   - 写 `<数据目录>/messages/<岗位id>/<kind>-<n>.txt`，临时文件再改名，目标或其上级是链接时拒绝（复用 `resume build` 的写法）。
   - 旁边写 `<kind>-<n>.build.json`，字段照 `applications.md` §12（`material_hash`、`profile_hash`、生成时间、`files` 的摘要），抽出 `resume build` 现有的写说明文件函数共用，不复制一份。
   - 标准输出 `{"text", "chars", "warnings", "build"}`，无正文。不加 `--output` 行为不变。
   - 检查 `applications.py` 的投出核对能找到 `messages/` 下的说明文件（§12 "别的名字找去掉扩展名加 .build.json"已覆盖，补测试即可；`--material` 分支现在只找 `resumes/`，见问题 2）。
2. **Review v1 扩到三种沟通材料**（`review.py`、`cli.py`、`docs/cn/review-format.md`）
   - `KINDS` 加 `greeting-review`、`email-review`、`referral-review`（或保留单一 kind、按材料种类判断，见问题 1）；文件名 `review-<kind>-<n>-r<k>.json`；`path` 收 `segments[i].text`、`subject.text`；`coverage` 必须是 `[]`；G1–G5 进条目表。
   - `cmd_review_draft` 去掉对沟通材料的拒绝，走同一个 `_check_material`；对沟通材料只出 E1/E3 警告，不出覆盖表。
3. **审核清单**（`docs/cn/review-checklist.md`）
   - 加 G 类 G1–G5（措辞照设计第 3 节），写明适用/不适用的旧条目。
   - #123 留下的审核项并进 G 类（暂定 G6–G8，见问题 3）：手写的学校、学历、公司、岗位名、姓名；`evidence` 段不引档案条目；手写链接；规则认不出的中文数字到岗说法。这些是机器拦不住的，标 `审核`。
4. **工作流文档和入口**（`docs/cn/resume-workflow.md` 新增"沟通草稿"一节；`.claude/skills/cn-resume/SKILL.md`、`.dsh/skills/cn-resume/SKILL.md` 描述和触发词；`.claude/agents/cn-resume-reviewer.md`；`AGENTS.md`）
   - 写入 #120 裁定 1、4、5：Codex 沙盒里 build/render 的说明；D5 留白与材料改不了的必改项怎么处理；交付提醒优先附 PDF。
   - 审核者不运行 `material render`、`resume build`。
   - 顺带改 #116 P3：审核子代理说明和相关测试名把"工具层保证"说过了头的地方，改成与实际一致的说法（只改措辞和测试名，不改行为）。
5. **`tools/security_guards.py` 注释**："material … only print"改成说明 `render --output` 会写 `data/messages/`。只改注释，不改规则——**需经理本人同意，请规划者去问**；未获同意前这一步不做，其余照常。
6. **手动走一遍**（临时数据目录，tech-m3 夹具）：单独起草打招呼语 → 子代理审核 → render --output → 交付；再走"简历通过后起草邮件"看 G3 和附件句。记进本文件。

### 测试

- 新增/扩充 `tests/test_cn_messages.py`（不动现有带 `m34_` 前缀的测试名）、`tests/test_cn_review.py`、`tests/test_cn_applications.py`、`tests/test_cn_agent_entry.py`：
  - `--output` 写对位置、内容等于不带 `--output` 的输出；链接拒绝；标准输出无正文、无手机号邮箱；
  - 说明文件 `material_hash` 等于 `review draft` 给的值；改材料再渲染，hash 变；投出核对能用上它；
  - `review draft`/`validate` 接受三种沟通材料，`coverage` 非空报错，路径 `segments[i].text` 合法、越界报错，文件名规则；
  - `review draft` 与 `material validate` 对同一份沟通材料结论一致；
  - 入口测试跟着描述、触发词、`AGENTS.md` 改。
- 只用公开虚构夹具；不读留出样例。

### 要规划者裁定的问题

1. **审核结果的 `kind`**：三个新值（`greeting-review` 等），还是保留 `resume-review` 改名为通用的 `material-review`（会动已有审核文件的兼容）？我建议加三个新值，旧值不变。
2. **投出核对找沟通草稿的说明文件**：`applications` 给了 `--material` 时现在只去 `resumes/<岗位id>/` 找。沟通材料的说明文件在 `messages/<岗位id>/`。由本项改 `applications.py` 按材料种类找（Claude A 的代码，PR 里写明），还是交回 Claude A？我建议本项改，改动小。
3. **#123 的四项编号**：并进 G 类续编 G6–G8（建议），还是归进已有的 A3/C 类？
4. **security_guards 注释**：请规划者代问经理是否同意只改那一句注释。
5. **#116 P3 的范围**：我按"审核子代理说明 + 对应测试名"理解；如果规划者手上有具体条目清单，请发我，免得改多或改少。

## 规划者裁定（计划 d9cc2db，2026-11-04）

1. 审核结果 `kind` 新加 `greeting-review`、`email-review`、`referral-review`，旧值不动。
2. `applications.py` 投出时到 `messages/` 找说明文件由 M3-6 改，但要等 #126（M4-1b）合并后在新 master 上做，放最后一步。
3. #123 那四项编 G6–G8。
4. 经理本人 2026-11-04 同意 `security_guards.py` 只改那一句注释，不改规则。
5. #116 P3 范围：审核子代理说明和对应测试名，按工具层实际保证改措辞。

## 实现进展（2026-11-04）

- 第 1 步 `material render --output`：写 `messages/<岗位id>/<种类>-<n>.txt` 和 `<种类>-<n>.build.json`（`kind` 为 `message-build`，和 `resume build` 共用写说明文件的函数）；文件名必须是 `<种类>-<n>.json` 且种类对上。
- 第 2 步 Review v1：三个新 kind 且必须和材料种类对上；沟通草稿 `coverage` 必须是 `[]`；`review draft` 对沟通草稿只出 E1/E3 风格警告（不查要点句号）；条目 A1–G8；`review show` 对沟通草稿写"沟通草稿没有覆盖表"。
- 第 3 步清单 G1–G8；D5 加页底留白的口径（#120 裁定 4）。
- 第 4 步 `resume-workflow.md` 新增第 5 节"沟通草稿"，Codex 沙盒 WinError 5 的处理（#120 裁定 1），材料改不了的必改项（裁定 4），交付提醒优先 PDF（裁定 5）；`cn-resume` 两份入口、审核子代理、`AGENTS.md`；#116 P3：子代理说明不再说"只读、不能写文件"，改成"没有 Edit/Write/联网工具，Bash 能跑允许列表里会写文件的命令，靠说明约束"，测试名改为 `test_the_agent_has_no_edit_write_or_web_tools`。
- 第 5 步 `security_guards.py` 注释（批准日期写在注释里），规则未改。
- 第 6 步手动走一遍（Claude Code，临时数据目录，tech-m3 公开夹具）：`material validate` → `material render --output`（标准输出只有路径、124 字、无警告）→ 派 `cn-resume-reviewer` 子代理审第 1 轮，约 3 分 20 秒，结论 `pass`，一条 E3 建议；子代理按第 5 节给出文件名 `review-greeting-1-r1.json`，`review validate` 通过。发现 `review show` 对沟通草稿写"没有列出"，已改。没走"简历通过后起草邮件"那一遍（要真实 Typst build），G3 和附件句只在文档和清单里覆盖，留给 Codex A 的整条流程验收。子代理提到夹具数据目录里没有匹配记录，这是我没拷，不影响沟通草稿。
- 已做（见本节最后）：#126 合并后改 `applications.py` 的 `--material` 查找（`messages/`）和 `applications.md` §12 的说明。
- Codex B 审 0faf0ed 的 P2-1：沟通草稿改完以后，第 5 节沿用第 3 节"重新 `resume build`"，它只收简历（退出码 2），`.txt` 和说明文件停在旧版，第 2 轮审核结果却能通过 `review validate`。改法（规划者转告）：
  - 第 3 节"重新生成"处注明沟通草稿是 `material render --output`；第 5 节加第 6 步"修改"：重新 `material validate`、`material render --output`，新输出交给下一轮。
  - 第 5 节审核一步加一条：审核者先打开 render 输出里的说明文件，`material_hash` 要等于 `review draft` 给的；不等就不写审核结果，请起草者重新渲染再派这一轮，不算一轮。不打开 `.txt`（邮件签名有联系方式）。清单 G2、审核子代理同步。
  - `cn-resume` 两份入口和 `AGENTS.md` 各加一句：材料改过以后，重新运行生成文件的命令（简历 `resume build`，沟通草稿 `material render --output`）。
  - 测试：入口文字（第 5 节"修改"一步的命令、审核一步和子代理提到说明文件、三处入口都写了两个命令）；改材料后 `resume build` 退出码 2、文件不变，重新渲染后说明文件、`.txt` 和第 2 轮审核结果是同一版。
  - 没加机器检查：`review validate` 不读 `messages/`，也不收 `--data-dir`，要加就得改命令。简历有同样的缺口（改了材料忘了 `resume build`，第 2 轮照样通过），这次没动，回报时问规划者。
- 规划者裁定（2026-11-04，P2-1 之后）：1. 审核者先核对说明文件那条保留；2. 机器检查不加，记进路线图待办（已记）；3. 简历也加审核者那条核对，本 PR 做。
  - 第 3 条：第 2 节第 2 步加"先核对 `resume-<n>.build.json` 的 `material_hash` 等于 `review draft` 给的，不等不写结果、不算一轮"；清单 D 类开头、审核子代理、入口测试同步；`test_cn_resume_build` 加改材料后重新 build 的测试（假 Typst）。
- `applications.py` 投出核对接上沟通草稿（#126 合并后）：
  - 给了 `--material` 且是沟通草稿时，到 `messages/<岗位id>/` 找 `<种类>-<n>.build.json`（`message-build`）；没给时按发出文件的名字找旁边的（`greeting-<n>.txt` 找 `greeting-<n>.build.json`），原来就能找到。
  - 顺带改的三处，不改就会让沟通草稿投出时给假警告或被拒：投递命令检查材料改用 `material validate` 那个分派函数（原来直接调简历的检查，沟通草稿通不过）；审核结果按 `review-<种类>-<n>-r<k>.json` 找；发出文件应在 `messages/<岗位id>/` 下。简历的警告原文不变。
  - `applications.md` 第 6、12、16 节写明。四个变异（找错目录、审核结果名、检查函数、警告用词）各被新测试抓到。
  - 没做、回报时问规划者：材料版本 `kind` 库表只允许 `resume`，沟通草稿也记成 `resume`（改要迁移库表）；邮件带简历附件时 `--material` 只能给一份，另一份发出的文件会报 mismatch。
