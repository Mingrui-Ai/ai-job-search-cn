# 匹配（match）

用 [个人档案](profile.md) 判断一个已保存的岗位适不适合你。分两步：先做**硬性条件过滤**（本文），再做**可解释评分**（M2-4，尚未实现）。全程离线；结果直接输出，不保存。

## 硬性条件过滤：`match filter`

```text
python -m jobsearch_cn match filter <岗位id> [--profile 档案文件] [--data-dir 数据目录]
```

- 岗位从本地岗位库读取（先用 `jd parse --save` 保存）；档案默认读取 `data/profile/profile.json`，必须能通过 `profile validate` 的结构校验（来源文件是否存在不影响过滤）。
- 退出码：0 已给出结论（无论结论是什么）；1 岗位不存在，或档案无效；2 档案读不了、岗位 id 格式不对。
- 输出不包含联系方式。

### 输出

```json
{
  "job_id": "job_9f4694691d57",
  "title": "后端开发实习生（Go方向）",
  "company": "示例互联网科技（深圳）有限公司",
  "verdict": "eligible",
  "checks": [
    {
      "check": "days_per_week",
      "result": "match",
      "reason": "JD 要求每周到岗 4 天，你可以 4 天",
      "jd": {"requirements.days_per_week": {"value": 4, "evidence": "4天/周"}},
      "profile": {"availability.days_per_week": 4}
    }
  ]
}
```

每一项都同时给出 JD 的值和出处原文（`jd`），以及用到的档案字段（`profile`）；有些结论还带 `note` 补充说明。

| `verdict` | 含义 | 条件 |
| --- | --- | --- |
| `ineligible` | 不符合 | 任何一项是 `conflict` |
| `needs_check` | 待确认 | 没有冲突，但有 `unknown`，需要看原文或问 HR |
| `eligible` | 符合 | 全部是 `match` |

### 各项条件

总原则：**JD 或档案任一方没写，结论是 `unknown`，不是 `conflict`。** 规则读不准时会把字段留空，留空不能让你错过岗位。

| `check` | JD 字段 | 档案字段 | `match` | `conflict` | `unknown` |
| --- | --- | --- | --- | --- | --- |
| `graduation` | `requirements.graduation` | `graduation.year` | 你的届别在列表中；或不在列表中但 JD 只是"优先"（附 `note`） | JD 限定届别（`strict: true`）且你不在其中 | 任一方没写 |
| `education` | `requirements.education.min` | `education[]` 中最高的 `level` | 最高学历不低于最低要求 | 低于最低要求 | JD 没写最低学历（只写"优先"也算没写），或档案没写学历 |
| `days_per_week` | `requirements.days_per_week` | `availability.days_per_week` | 要求天数 ≤ 你能到岗的天数 | 要求天数更多 | 任一方没写 |
| `min_months` | `requirements.min_months` | `availability.months` | 要求月数 ≤ 你能实习的月数 | 要求月数更多 | 任一方没写 |
| `location` | `cities`、`remote` | `availability.cities`、`remote_ok`、`relocate` | 城市有交集（"上海"与"上海市"视为相同）；或 JD 可远程且你接受远程；或你愿意搬家（附 `note`） | 没有交集，你明确不搬家（`relocate: false`），并且 JD 写明不支持远程或你明确不接受远程 | JD 或档案没写城市；或没有交集，但是否搬家没写，或能否远程两边都没有否定（包括两边都没写） |
| `employment_type` | `employment_type` | `target.employment_types` | 岗位类型在你的求职方向中 | 不在其中 | 任一方没写 |
| `exclusions` | `title`、`company`、`cities` | `exclusions` | 没命中排除项 | 标题含排除关键词；公司名含排除的公司；工作城市全部在排除城市中 | 设了排除关键词或公司，但 JD 没写标题或公司 |

说明：

- 排除关键词**只匹配标题**。匹配正文容易误伤，例如正文写"本岗位不是外包"。
- 薪资不在过滤范围内，由评分（M2-4）处理。

### 例子

5 份样例 JD 与 2 份示例档案（`tests/fixtures/cn/`）的 10 组结果，以及每组的人工核对理由，写在 `tests/test_cn_match.py` 的 `SAMPLE_TABLE` 中。
