# 2026-10-29 · V3 合并后匹配工作流实测

**完成**

- #48 合并为 `51ac2fc`、#29 合并为 `59e49be` 后，在 `master@59e49be3c1612e94d3369a2d86bf0240b87a986e` 按 `docs/cn/match.md` 实测。
- 使用 tech/ops 示例档案、4 份已有虚构 JD，以及 1 份不含技能关键词的原创虚构 JD，完成 63 次 CLI 调用。
- 覆盖两条路径：先批量保存规则部分再补草稿；规则方向为 null 时由 Agent 补方向。另检查档案变更后的 stale、旧草稿拒绝和重评。
- 本次仅增加工作记录和 V3 进度，未改代码、评分规则或冻结文件；V8 留在独立的本地分支。

**决策**

- 所有操作在独立目录 `data/v3-check/tech`、`ops`、`direction`，只用样例；不读取真实岗位或档案，不访问 JD 链接。
- 查看档案只用 `profile show`，输出已确认不含样例联系方式；JSON 用 UTF-8 文件写入，不通过 PowerShell 的 `>` 转存。
- 总分一律复制 `match validate` 报错里的 JSON 对象，不手算。评分理由是本轮工作流输入，不作为新的独立排序 oracle。

**验证**

环境为 Windows、conda `ai-job-search-cn`、Python 3.12.15。每个数据目录先复制相应示例档案及其示例来源，再运行 `profile validate/show`。下面的 `<D>` 为对应隔离目录，每条命令都显式传入：

```text
python -m jobsearch_cn profile validate --data-dir <D>
python -m jobsearch_cn profile show --data-dir <D>
python -m jobsearch_cn jd parse <样例.txt> --save --data-dir <D>
python -m jobsearch_cn jd list --data-dir <D>
python -m jobsearch_cn jd show <id> --data-dir <D>
python -m jobsearch_cn match score <id> --save --data-dir <D>
python -m jobsearch_cn match score <id> --draft --data-dir <D>
python -m jobsearch_cn match validate <D>/matches/drafts/<id>.json --data-dir <D>
python -m jobsearch_cn match save <D>/matches/drafts/<id>.json --data-dir <D>
python -m jobsearch_cn match show <id> --data-dir <D>
python -m jobsearch_cn match list --data-dir <D>
```

在草稿内补经历后，首次 validate 只报 total 不一致；复制应填对象后再 validate，全部通过并保存。规则部分、hints 和缺口未改。

| 档案 | 样例（相对 tests/fixtures/cn） | 经历分 | 过滤 | 总分/等级 | 未知维度 |
| --- | --- | --- | --- | --- | --- |
| tech | jd/boss_intern.txt | 85 | eligible | 76/strong | 无 |
| tech | jd/official_site.txt | 45 | needs_check | 49/moderate | salary |
| ops | jd-m2-3/shixiseng_content_ops_intern.txt | 85 | eligible | 77/strong | salary |
| ops | jd-m2-3/official_marketing_campus.txt | 70 | eligible | 44/weak | salary |

`match list` 给出的顺序与上表各档案顺序相同，初始均非 stale。草稿与 score 输出相等，重复 score --draft 保留已保存的 Agent 经历。

**第 6 步，面向用户的说明实测：**

- tech 后端符合硬性条件。Go 后端接口经历与“使用 Go 语言编写高并发服务”相关，引用 `exp-1`、`proj-1`；规则缺口是 Redis、Java、Kubernetes。二选一仍是 H16 待处理局限，不能把它解释成档案一定缺少可投资格。
- tech 算法岗位待确认届别：JD 没写、示例档案为 2027 届，可向 HR 确认。经历只支持 RAG 应用与检索评测，不能宣称做过推荐、强化学习或多模态研究；薪资面议，因此总分不含薪资。
- ops 内容运营优先于市场管培；分别引用 `exp-1`、`campus-1` 的运营/校园活动经历。市场管培只有相关活动经验，预算跟进没有直接证明。两份都缺最低期望薪资，所以 salary 为 null、complete=false；只展示本批两个可投候选，不凑三项。

**规则方向为 null 的路径：**

另用以下原创虚构文本，保存到独立 `direction` 目录；它不是 V8 留出题目：

```text
社区运营实习生
示例伙伴服务有限公司
工作地点：上海
薪资：180-220元/天
仅招2027届
本科及以上学历
每周至少到岗3天
至少实习3个月
不支持远程办公
岗位职责：协助社区活动的报名登记和现场接待。
```

规则没有识别出技能，skills、direction 均为 null。按标题补方向 100（method=agent，引用“社区运营实习生”，profile 证据为空列表），经历补 60（引用“协助社区活动的报名登记和现场接待”与 `campus-1`，说明校园活动经验可迁移但无直接接待证明）。校验、保存成功，total 为 82/strong，missing 为 skills、salary。向用户明确：这不是已经证明技能匹配 82 分；缺技能要求和期望薪资，总分只基于方向和相关经历，应先补充信息再决策。

**档案变化和重评：**

- tech/ops 隔离档案的四项权重临时改为 1；各自 2 条已保存记录全部 stale。
- 旧草稿 validate 返回退出码 1，并提示 `the job or the profile changed since scoring`。
- 重新 `score --draft` 后，旧 Agent 经历分清空为 null，等待根据新输入补充；未将旧记录冒充当前评分。
- 实测完成后恢复隔离档案原值。原示例档案未改。

提交前全量 1181 项，`OK (skipped=12)`；`lint_skills`、`security_guards` 通过。原始 CLI 输出仅留本地 `data/v3-check/results.json`。

**遗留**

- 本次未发现工作流阻塞问题。H16/H17/H18 的规则局限维持已知任务，不在 V3 修改。
- V8 已冻结并完成基线，但 H16 PR 尚未开出，仍不得推送。

**下一步**

- 规划者审核 V3 记录；M2-5 由用户进行真实数据验收。
- H16 PR 开出后，在 V8 分支继续留出对照，之后再公开测试数据 PR。
