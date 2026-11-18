# 北森列表和详情

每次选择已核实的 `https://<tenant>.zhiye.com` 企业门户。`collect/beisen.json` 定义租户、条款核对日期、门户版本、频道和城市。已验证的页面结构及日期见 [北森原始验证记录](../../../docs/cn/worklog/2026-11-10-m6-3-beisen-live.md)。

| 页面 | 参数与解析依据 |
| --- | --- |
| 新版 `/{channel}/jobs` | `LocId` 包含白名单城市代码和名称，`KeyWords` 为可选关键词。页面自身的同源 `/api/Jobad/GetJobAdPageList` 响应中，`Data[].Id` 是详情 UUID，`Count` 是总数。按页面可见的卡片标题和岗位编号核对，再取城市标签和发布日期。 |
| 旧版 `/search` | `r` 为社招 1、校招 2、实习 3，`c` 为城市代码，`k` 为可选关键词。逐行读取 `table.listtable` 中指向 `/zpdetail/<数字>` 的岗位、城市和日期。 |
| 新版 `/{channel}/detail?jobAdId=<UUID>` | 读取可见岗位名、标签、发布时间和 `STDutyContainer-editor` 的职责与要求。 |
| 旧版 `/zpdetail/<数字>` | 读取岗位自己的 `positiondetail` 区块、字段和正文。链接没有频道，`channel_source=argument` 表示用户选择的频道，`whitelist_single` 表示唯一的白名单频道。 |

`search` 结果保留 `id/title/company/location/date/url`。`company` 来自本机白名单，`id` 与 CN 收件共用 `beisen.<tenant>.<原始岗位号>`。`detail` 接受该 ID 或规范 URL，返回同一组字段及 `description`、`salary`、公司和频道来源。缺失的事实为 `null`。任何页面内链接均不作为下一步读取目标。

列表和详情均使用 `JobSearchCN/1` 读取同源 `/robots.txt`，按实际目标 URL 检查许可及等候时间。模块禁止额外文档导航，不拼接 API 请求，冻结页面并关闭浏览器后才采信结果。验证码、403、429、登录、跳转、读取失败或结构变化终止当前命令。多页滚动及批次收件由用户单独运行既有 `collect beisen` 命令。
