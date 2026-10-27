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
    "cities": ["广州", "深圳"], "remote_ok": true, "relocate": false
  },
  "target": {
    "employment_types": ["internship"],
    "roles": ["后端开发", "大模型应用开发"],
    "industries": ["互联网"],
    "salary_min": {"amount": 150, "unit": "CNY/day"}
  },
  "skills": [
    {"name": "Python", "level": "proficient", "used_in": ["exp-1"], "source": "resume.pdf"}
  ],
  "experience": [
    {"id": "exp-1", "type": "internship", "org": "某科技公司", "role": "后端开发实习生",
     "start": "2026-03", "end": "2026-08", "bullets": ["用 Go 重写订单服务，P99 延迟从 120ms 降到 40ms"],
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
| `availability` | 可到岗日期、每周天数、可实习月数、意向城市、是否接受远程、是否愿意搬到其他城市。分别对应 JD 的 `days_per_week`、`min_months`、`cities`、`remote` |
| `target` | 求职方向。`employment_types` 取值同 Job Schema；`salary_min.unit` 取值同 Job Schema 的薪资单位 |
| `skills[]` | `level`：`familiar`（了解）、`working`（熟悉）、`proficient`（熟练）、`expert`（精通）。`used_in` 指向用到它的经历或项目的 `id`，写简历时据此给出事实依据 |
| `experience[]` | 实习、项目、科研、竞赛、校园经历都放这里，用 `type` 区分：`internship` / `project` / `research` / `competition` / `campus` / `work` |
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
| `cities` + `remote` | `availability.cities`、`remote_ok`、`relocate` | 城市不在意向中，也不能远程或搬家 |
| `employment_type` | `target.employment_types` | 不在求职方向中 |
| 标题、公司、正文 | `exclusions` | 命中排除项 |

JD 字段为 `null` 时结论是"未知"，不判为不符合。

## 7. 隐私护栏

- 新增测试，检查上游 `/setup` 会写入的文件（`CLAUDE.md`、`job-application-assistant/01–08`、`cv/main_example.tex`）仍是占位符，防止有人误跑上游 `/setup` 后把个人信息提交上去；
- 新增测试，检查 `data/profile/` 被 git 忽略；
- CN 命令输出档案时默认隐去 `contact`，需要时显式加参数。

## 8. 已定与待定

- 字段与四档技能等级按本稿实现，使用中再调整（2026-10-27）。
- `exclusions.keywords` 暂定只匹配岗位标题（正文容易误伤，例如"非外包岗位"），在 v0.2 硬性过滤中实现，可再讨论。
