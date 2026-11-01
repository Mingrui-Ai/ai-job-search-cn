# V15 · H21 留出样例的 master 基线

5 份原创虚构 JD 已冻结并完成基线，其中视觉设计、内容运营 2 份为非技术方向。master 对 10 个确定的紧跟数字版本写法全部漏读；C4D 保持完整，PS4/PS5 没有映射为 Photoshop，没有确定的多读项。这是 H21 实现前的基线，不是 H21 验收结论。

## 冻结和执行边界

- 基础代码：`e99470eab14a2e22aa1139c6cf0c9604394cf580`，执行前通过 `git fetch origin master` 确认为当时的 master。
- 冻结提交：`4ac20083798332232abb34ec770d5cc401d0ad4b`；先提交输入与期望，随后才执行本批首次 CLI。执行时 `jobsearch_cn/`、`tools/` 与上述 master 无差异，前后均静默核对。
- 清单：[oracle-manifest.json](oracle-manifest.json)，SHA-256：`009b07fcb5a743fabfd9774a4cddafe95f346dc881ed37bd5a5aa53aaf0d7c5f`。其中 12 个文件（5 份 JD、5 份人工期望、README 和 LF 属性）全部保持冻结哈希；工作目录及 Git 提交里的字节一致。
- Windows，conda `ai-job-search-cn`，Python 3.12.15；2026-10-30 03:26:53–03:27:00 UTC 执行。
- 仅读公开文档、任务、虚构档案以及 V4/V10 产物和黑盒 runner 格式。本任务未读解析源码或 H21 分支；历史接触情况见冻结 README。未使用真实 JD 或个人档案。
- 35 次公开 CLI 调用全部退出 0，stderr 为空；5 份解析均无警告，guard 均为 clean。数据写入独立的忽略目录 `data/v15-check/master-e99470e/`。公开候选输出只含本批虚构内容，命令日志中的工作目录替换为 `<workspace>`。

## 逐份结果

| 样例 | 完全可裁定字段组 | 确定技能命中 | 漏读的基础技能 | 边界结果 |
| --- | --- | --- | --- | --- |
| `web_interface_intern` | 13/14 | 1/4 | HTML、CSS、Vue | JavaScript 正确，没有额外 Java；Top3 不算技能 |
| `service_tools_intern` | 13/14 | 1/4 | Python、Java、Docker | SQL 正确；5G 不算技能 |
| `visual_layout_intern` | 13/14 | 1/3 | Photoshop、Illustrator | C4D 保持完整；4A 不算技能 |
| `console_content_campus` | 13/14 | 1/3 | Excel、PowerPoint | 内容策划正确；PS4/PS5 不算 Photoshop |
| `creative_tools_intern` | 13/13，技能组另列 | 2/2 | 无确定漏读 | Figma、剪映正确；3 种版本写法待裁定 |

- 69 个完全可裁定字段组中 **65 个一致**，4 个差异均在技能组；65 个非技能字段组全部一致。第 5 份的技能组含待裁定写法，不与其余 69 组混算。
- 16 次确定技能出现中 **命中 6、漏读 10、多读 0**。10 个正向版本探针命中 **0/10**；无版本对照及固有数字名称共 **6/6** 命中。
- 小数版本探针为 `Python3.10`、`Docker24.0`、`Illustrator28.0`；斜线并列为 `HTML5/CSS3`、`Excel2021/PowerPoint2019`，顿号并列为 `Python3.10、Java8` 等。
- 固有数字名称 **1/1**、游戏机型号 **2/2**、带明确禁读列表的陷阱 **6/6** 符合期望。PS4/PS5 同处一份样例，报告的是两种型号的覆盖，不代表两次独立实验。
- 5 份均未生成虚假的任选技能组，**5/5** 符合期望。

## 待规划者裁定

| 编号 | 写法 | master 实际输出 | 需要裁定的边界 |
| --- | --- | --- | --- |
| v15-p1 | `Photoshop 2024` | 读出 `Photoshop` | 词条与版本之间有空格，是否纳入 H21 |
| v15-p2 | `Vue2.x` | 未读出相关候选技能 | 含通配字母 x 的版本是否接受 |
| v15-p3 | `Pythonv3.11` | 未读出相关候选技能 | 含 v 前缀的版本是否接受 |

这些输出只记出现与否，不算对错，也不计入确定技能命中或多读。没有发现无法归类的新候选拼写。后续裁定另建文件，不回写冻结期望。

## 过滤与人工字段回放

两份公开虚构档案 tech/ops 对 5 个解析岗位的总结论 **10/10**、7 项硬条件状态 **70/70** 与人工期望相同。方向和技能相关度不属于本批硬过滤，不据此声称评分排序正确。

将冻结的确定字段写成 Agent 来源记录，在另一空数据目录验证并保存，5 份均通过 Schema 校验。该回放再次得到总结论 **10/10**、硬条件状态 **70/70** 一致。第 5 份人工记录只含确定技能，不把未定技能的省略视为最终裁定。输入与期望始终未改。

## 验证与复现

冻结提交前，`lint_skills`、`security_guards` 通过；全量 unittest **1256 项，12 项跳过，0 失败**。两个验证脚本编译通过。基线后复查输入哈希、实际输出、日志、隐私路径和 `git diff --check`；生产代码保持不变。

```powershell
conda run -n ai-job-search-cn python tests/fixtures/cn/jd-h21-holdout/audit_oracle.py
conda run -n ai-job-search-cn python tests/fixtures/cn/jd-h21-holdout/run_baseline.py --label master-e99470e-replay
```

runner 要求当前应用/工具代码与冻结 master 一致，输入已提交、数据与输出目录均未存在；不会覆盖旧结果，也不读取解析源码。只读审计会核对冻结清单、原文出处和人工结论结构。此 runner 用于复现当前基线；H21 的对照由规划者通知后另做。

完整逐字段差异见 [summary.json](actual/master-e99470e/summary.json)，原始解析、人工字段、两套过滤结果保存在同目录的 5 份样例 JSON；调用记录见 [commands.json](actual/master-e99470e/commands.json)。本轮仅本地提交，H21 PR 开出前不推送。
