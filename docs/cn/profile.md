# 个人档案（Profile v1）设计稿

> 状态：**v1 已实现**（2026-10-27）：`jobsearch_cn/profile.py`、`profile validate` / `profile show`，建档流程见 [profile-setup.md](profile-setup.md)。字段先按本稿实现，使用中再调整。

## 1. 已定的方向（2026-10-27）

| 问题 | 决定 |
| --- | --- |
| 格式 | `data/profile/profile.json` 存结构化信息（可校验，供过滤和评分用）；`data/profile/notes.md` 存自由文本（写简历和打招呼语的素材） |
| 与上游 `/setup` 的关系 | 独立的 CN 建档流程 `cn-setup`，只写 `data/profile/`；上游 `/setup` 不改也不用。CN 的匹配和简历流程只读 `data/profile/` |
| 信息来源 | 用户把简历放进 `data/profile/sources/`，Agent 抽取后逐项请用户确认，缺的再问 |

`data/` 已被 git 忽略（ADR-6），档案、简历原件和联系方式都不会进入仓库。

## 2. 目录

```text
data/profile/
├── profile.json     # 结构化档案（本文 §3），profile validate 校验
├── notes.md         # 自由文本（本文 §4）
└── sources/         # 用户提供的原始材料：简历 PDF/DOCX/TXT、成绩单等
```

## 3. profile.json 字段

沿用 Job Schema 的约定：所有键都必须出现，没有的填 `null` 或 `[]`；不认识的键报错；枚举值与 Job Schema 共用，以便直接比较。

```json
{
  "schema_version": 1,
  "contact": {"name": "张三", "phone": "13800000000", "email": "a@example.com", "github": null, "website": null},
  "graduation": {"year": 2027, "month": 6},
  "education": [
    {"level": "master", "school": "某大学", "major": "计算机技术", "start": "2025-09", "end": "2027-06",
     "gpa": "3.7/4.0", "rank": "前10%", "courses": ["机器学习", "分布式系统"], "source": "resume.pdf"}
  ],
  "availability": {
    "start_date": "2026-11-15", "days_per_week": 4, "months": 6,
    "cities": ["广州", "深圳"], "acceptable_cities": ["佛山"], "remote_ok": true, "relocate": false
  },
  "target": {
    "employment_types": ["internship"],
    "roles": ["后端开发", "大模型应用开发"],
    "industries": ["互联网"],
    "salary_min": {"amount": 150, "unit": "CNY/day"},
    "directions": ["tech"],
    "weights": null
  },
  "skills": [
    {"name": "Python", "level": "proficient", "used_in": ["exp-1", "proj-1"], "source": "resume.pdf"},
    {"name": "Go", "level": null, "used_in": ["exp-1"], "source": "resume.pdf"}
  ],
  "experience": [
    {"id": "exp-1", "type": "internship", "name": null, "org": "某科技公司", "role": "后端开发实习生",
     "start": "2026-03", "end": "2026-08", "bullets": ["用 Go 重写订单服务，P99 延迟从 120ms 降到 40ms"],
     "source": "resume.pdf"},
    {"id": "proj-1", "type": "project", "name": "课程问答助手", "org": null, "role": null,
     "start": "2025-10", "end": "2026-01", "bullets": ["用 Python 搭建课程资料问答，覆盖 20 门课程"],
     "source": "resume.pdf"}
  ],
  "awards": [{"name": "全国大学生数学建模竞赛省一等奖", "date": "2025-10", "source": "resume.pdf"}],
  "certificates": [{"name": "CET-6", "detail": "560", "date": "2023-12", "source": "user"}],
  "languages": [{"name": "英语", "level": "CET-6 560", "source": "user"}],
  "exclusions": {"cities": [], "companies": [], "keywords": ["销售", "外包"]}
}
```

| 字段 | 说明 |
| --- | --- |
| `contact` | 写简历用。只存在本地；除简历外，任何输出（日志、报告、Agent 汇总）都不应复制它 |
| `graduation` | 毕业年月。与 JD 的 `requirements.graduation.years` 比较 |
| `education[]` | `level` 取值同 Job Schema：`associate` / `bachelor` / `master` / `phd`。最高学历用于和 JD 的 `requirements.education.min` 比较 |
| `availability` | 可到岗日期、每周天数、可实习月数、意向城市、是否接受远程、是否愿意去其他城市。分别对应 JD 的 `days_per_week`、`min_months`、`cities`、`remote`。意向城市分两档：`cities` 是首选城市，`acceptable_cities` 是可以接受、但不是首选的城市（M2-6b），两者不能重复；硬性条件里两档都算意向城市，评分的地点维度首选记 100、可以接受记 60。`relocate` 指是否愿意去这两档以外的城市。写了意向城市时，`remote_ok`、`relocate` 也要写：留空的话，意向城市以外的岗位地点都会判"未知"，`profile validate` 会给出警告 |
| `target` | 求职方向。`employment_types` 取值同 Job Schema；`salary_min.unit` 取值同 Job Schema 的薪资单位。`directions` 是想做的方向，取[技能词表](jd-parse.md#技能词表)的分组键，例如 `["data", "product"]`；可以用自己词表里新增的分组，`general`（通用办公软件）不算方向；`profile validate` 会对照词表检查。`weights` 是评分五个维度的权重，为 null 时用默认值（技能 30、方向 25、经历 25、薪资 10、地点 10）；要改就写全五项，例如 `{"skills": 40, "direction": 20, "experience": 20, "salary": 10, "location": 10}`，每项不小于 0，至少一项大于 0。评分方法见 [match.md](match.md#可解释评分m2-4-设计稿) |
| `skills[]` | `level`：`familiar`（了解）、`working`（熟悉）、`proficient`（熟练）、`expert`（精通）。`used_in` 指向用到它的经历或项目的 `id`，写简历时据此给出事实依据。收录范围见下方"填写约定" |
| `experience[]` | 实习、项目、科研、竞赛、校园经历都放这里，用 `type` 区分：`internship` / `project` / `research` / `competition` / `campus` / `work`。`name`、`org`、`role` 的分工见下方"填写约定" |

**填写约定**（2026-10-27 起，H7；两个 Agent 对同一份简历必须填得一样）：

- **经历的三个名称字段各管一件事**，材料里没有的留 `null`，不要挪用别的字段：
  - `name`：项目、竞赛、科研课题本身的名称，例如"课程问答助手""全国大学生数学建模竞赛"。实习和工作通常为 `null`；
  - `org`：所在单位，例如公司、实验室、学生会部门。个人项目为 `null`；
  - `role`：你在其中的身份或职位，例如"后端开发实习生""副部长""队长"。材料没写就为 `null`，不要把"个人项目"之类的类别词填进来（类别由 `type` 表示）。
- **技能两处都收**：
  - 简历技能栏里的技能，`level` 按原文的"了解 / 熟悉 / 熟练 / 精通"填写；
  - 只出现在经历描述里的技术（例如只在实习描述中提到的 RAG）也收，`level` 留 `null`，`used_in` 指向出现它的经历；
  - 同一技能两处都出现时只记一条：`level` 取技能栏的写法，`used_in` 列出所有出现它的经历。
  - 技能栏里有、但没有任何经历用到的技能，`used_in` 为 `[]`。
| `awards[]`、`certificates[]`、`languages[]` | 奖项、证书、语言 |
| `exclusions` | 硬性排除：不去的城市、不考虑的公司、标题或正文中出现即排除的关键词 |

**来源（`source`）**：经历、技能、教育、奖项等条目都带 `source`，取值是 `sources/` 下的文件名，或者 `user`（用户口述）。这与 JD 的出处规则对应：简历里没有、用户也没说过的内容不能出现在档案里。写简历时只能用档案里有的事实。

**校验规则**（`profile validate`）：

- 日期格式为 `YYYY-MM` 或 `YYYY-MM-DD`，开始不晚于结束；
- 枚举值合法；`used_in` 指向的 `id` 必须存在；`id` 不能重复；
- `source` 是 `user`，或者是 `sources/` 下确实存在的文件；
- 每周天数 1–7，月数 1–24，毕业年份在合理范围内。

## 4. notes.md

自由文本，没有固定格式，校验只检查它存在且是 UTF-8。建议的小节：

- 一句话自我介绍
- 优势和代表性成果（每条都应能在 `profile.json` 的经历里找到）
- 求职方向与动机
- 工作方式和偏好的团队氛围
- 不考虑的情况（硬性的写进 `exclusions`，这里写原因和软性偏好）

## 5. 建档流程 `cn-setup`

和 JD 导入一样，流程只写在一份文档（`docs/cn/profile-setup.md`）里，Claude Code 技能和 `AGENTS.md` 都只指向它。

1. 请用户把简历等材料放进 `data/profile/sources/`；
2. Agent 读取材料，起草 `profile.json` 和 `notes.md`，每条带 `source`；
3. 逐节展示给用户确认；材料里没有的（到岗时间、意向城市、每周天数、排除项等）直接问；
4. `profile validate` 通过后保存；
5. 以后可以重复运行：只提出新增或有变化的内容，不覆盖用户已经确认过的值。

## 6. 与 JD 的硬性条件对照（v0.2 第 2 项预告）

| JD 字段 | 档案字段 | 不符合的情形 |
| --- | --- | --- |
| `requirements.graduation`（`strict: true`） | `graduation.year` | 届别不在列表中 |
| `requirements.education.min` | `education[]` 中的最高 `level` | 低于最低学历 |
| `requirements.days_per_week` | `availability.days_per_week` | JD 要求的天数多于可到岗天数 |
| `requirements.min_months` | `availability.months` | JD 要求的月数多于可实习月数 |
| `cities` + `remote` | `availability.cities`、`acceptable_cities`、`remote_ok`、`relocate` | 城市不在首选和可以接受的城市中，也不能远程或去其他城市 |
| `employment_type` | `target.employment_types` | 不在求职方向中 |
| 标题、公司、正文 | `exclusions` | 命中排除项 |

JD 字段为 `null` 时结论是"未知"，不判为不符合。

## 7. 隐私护栏

- 新增测试，检查上游 `/setup` 会写入的文件（`CLAUDE.md`、`job-application-assistant/01–08`、`cv/main_example.tex`）仍是占位符，防止有人误跑上游 `/setup` 后把个人信息提交上去；
- 新增测试，检查 `data/profile/` 被 git 忽略；
- CN 命令输出档案时默认隐去 `contact`，需要时显式加参数。

## 8. 已定与待定

- 字段与四档技能等级按本稿实现，使用中再调整（2026-10-27）。
- `experience[].name` 与上方"填写约定"（H7，2026-10-27）：M1-5 第二轮发现两个 Agent 对同一份简历的填法不同（项目名称一个放 `org`、一个放 `role`；只在经历里出现的技能一个收、一个不收），M3 生成简历前必须统一。新增 `name` 而不是规定"项目名放 `role`"，是为了让每个字段只表达一件事。Profile 尚未随任何版本发布，所以直接加入 v1，不升版本号；已有的本地档案需要为每段经历补上 `"name": null` 或项目名称，`profile validate` 会逐条提示。
- `exclusions.keywords` 暂定只匹配岗位标题（正文容易误伤，例如"非外包岗位"），在 v0.2 硬性过滤中实现，可再讨论。
- `target.directions` 和 `target.weights`（M2-4a，2026-10-28）：供 M2-4 评分的"方向"维度和加权总分使用。和 `experience[].name` 一样直接加入 v1，不升版本号；已有的本地档案需要在 `target` 里补上 `"directions": []`（或自己的方向）和 `"weights": null`，`profile validate` 会提示。
- `availability.acceptable_cities` 和 `target.weights.location`（M2-6b，2026-10-29）：供评分的"地点"维度使用。同样直接加入 v1，不升版本号；已有的本地档案需要在 `availability` 里补上 `"acceptable_cities": []`（或可以接受的城市），自己写过 `weights` 的还要补上 `"location"`（写 0 就和以前算法一样），`profile validate` 会提示。`relocate` 的含义随之收窄为"愿意去首选和可以接受的城市以外的地方"。
