# V15 · H21 留出样例对照（PR #91）

对照冻结基线 `e99470eab14a2e22aa1139c6cf0c9604394cf580` 与 [#91](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/91) 的最新提交 `eb91a9f3cb54c281485bf9a51ec53170b03c7cc3`。**5 份原创虚构 JD 的 70 个旧字段组、19 个裁定后技能、10 组过滤结论和 70 项旧硬条件状态全部符合人工期望；没有多读、读错、漏读或相对基线的新退步。P1 0 / P2 0 / P3 0。**

冻结的 5 份 JD、5 份人工期望、README 和 LF 属性没有修改。冻结清单 SHA-256 仍为 `009b07fcb5a743fabfd9774a4cddafe95f346dc881ed37bd5a5aa53aaf0d7c5f`。原来单列待裁定的 `Photoshop 2024`、`Vue2.x`、`Pythonv3.11` 按 #91 的规划者裁定写入独立的 [adjudication.json](adjudication.json)，未回写冻结期望。

## 汇总

| 指标 | master 基线 | #91 最新提交 |
| --- | ---: | ---: |
| 旧字段组一致 | 65/69（第 5 份技能组另列） | 70/70 |
| 裁定后技能命中 | 6/16，另有 3 项待裁定 | 19/19 |
| 技能漏读 / 多读 / 读错 | 10 / 0 / 0（不含待裁定项） | 0 / 0 / 0 |
| 正向版本探针 | 0/10，另有 3 项待裁定 | 13/13 |
| 游戏机型号不映射 Photoshop | 2/2 | 2/2 |
| 固有数字名称 C4D 保持完整 | 1/1 | 1/1 |
| 非空旧字段出处逐字存在 | 基线已核对 | 67/67 |
| 原始解析过滤：总结论 / 旧状态 | 10/10、70/70 | 10/10、70/70 |
| 人工字段回放：总结论 / 旧状态 | 10/10、70/70 | 10/10、70/70 |
| 人工记录校验 / 保存 | 5/5、5/5 | 5/5、5/5 |

当前规则新增的面试和到岗日期检查在这 5 份 JD 中均为 `unknown`，另存观察，不混入冻结的 70 项旧硬条件分母，也没有改变 10 组总结论。

## 逐份技能读出

| 样例 | master 基线 | #91 实际 | 结论 |
| --- | --- | --- | --- |
| `web_interface_intern` | JavaScript | HTML、CSS、Vue、JavaScript | `HTML5/CSS3`、`Vue3` 均读出基础技能；不拆 JavaScript，不误读 Top3 |
| `service_tools_intern` | SQL | Python、Java、Docker、SQL | `Python3.10`、`Java8`、`Docker24.0` 均读出；不误读 5G |
| `visual_layout_intern` | C4D | Photoshop、Illustrator、C4D | `Photoshop2024`、`Illustrator28.0` 均读出；C4D 保持完整，不误读 4A |
| `console_content_campus` | 内容策划 | Excel、PowerPoint、内容策划 | `Excel2021/PowerPoint2019` 均读出；PS4、PS5 不映射 Photoshop |
| `creative_tools_intern` | Figma、剪映、Photoshop | Figma、剪映、Photoshop、Vue、Python | 三项原待裁定写法均符合裁定；没有额外拼写或版本号进入技能值 |

技能值仍保留词表原写法，不把版本号并进输出。`Photoshop 2024` 在 master 已读出 Photoshop；本轮新增的裁定效果主要是 `Vue2.x` 和 `Pythonv3.11`，同时确认原行为没有退步。

## #91 裁定的补充黑盒探针

6 个补充合成探针不计入冻结分母，只核对作者按裁定追加的边界：

- `PS 5年以上` 读出 `PS`（与 Photoshop 同义），不当作游戏机型号；
- `Python 3 年以上` 读出 `Python`；
- `PS5` 游戏机不读出 Photoshop；
- `Unity3D` 不在词表，本 PR 不处理，保持不读；
- `PS 5.1` 和 `PS5.x` 都作为 Photoshop 的版本写法读出 `PS`，不当游戏机型号。

6/6 符合裁定。公共 Job Schema 的技能出处是分句级文本，因此报告只能确认出处逐字来自原文，不能从 CLI 声称内部匹配范围是否只到 `Python`；#91 的实现测试负责该更细粒度断言。

## 过滤和旧字段

标题、公司、城市、远程、岗位类型、薪资、届别、每周天数、实习时长、学历、转正、发布日期、截止日均与冻结人工期望一致。唯一相对 master 的字段变化是各样例补齐版本技能；没有非技能字段变化。

两份公开虚构档案只在临时运行副本加入当前 Schema 必需的 `availability.acceptable_cities=[]`，其他原值逐项断言与目标提交公开档案相同。原始解析和人工字段回放都得到 10/10 总结论与 70/70 旧状态；技能相关度不属于本批硬过滤，不以过滤结论代替技能字段验收。

## 证据与复现

- [最新汇总](actual/pr91-eb91a9f-complete/summary.json)、[41 次 CLI 调用记录](actual/pr91-eb91a9f-complete/commands.json)，以及同目录 5 份逐字段结果。运行使用 Windows、conda `ai-job-search-cn`、Python 3.12.15；调用全部退出 0、无 stderr。
- `run_comparison.py` 从目标提交创建不可变 Git 归档，在忽略的数据目录执行；最新归档 SHA-256 为 `5e32ec9248231e1eff6b0e1f74bc9bba7cbca0b9a5bb7244ba25bbbd2c81598a`，运行后逐文件哈希未变。
- 最新裁定映射 SHA-256 为 `62427772ce325dd9885dca92fc8e0634739b664d122f76cd8d0b18f993862589`。冻结输入在运行前后均通过 `audit_oracle.py`，没有使用真实岗位或个人档案。
- 作者推送 `eb91a9f` 前对 `572fe48` 的首轮结果保存在 `actual/pr91-572fe48-complete/`；当时裁定映射的原字节保存在 `adjudication-572fe48.json`，哈希 `bf48afca11ef0e847ef7b9d4615e21e394fc38bcb5ed67fe238d0c87345deb37`。最终结论以 `eb91a9f` 为准。
- 报告分支已合入 `origin/master@c0c05ab`；`lint_skills`、`security_guards`、`git diff --check` 通过，全量 unittest 1358 项、12 项跳过、无失败。

复现命令：

```powershell
conda run -n ai-job-search-cn python tests/fixtures/cn/jd-h21-holdout/run_comparison.py --target eb91a9f3cb54c281485bf9a51ec53170b03c7cc3 --label <全新标签>
```

本报告只验收 V15 冻结范围和四条裁定补充探针，不代替 Codex B 对 #91 实现的独立审核。
