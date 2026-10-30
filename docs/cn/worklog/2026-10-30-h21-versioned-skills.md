# 2026-10-30 · H21：带版本号的技能写法（进行中，Claude C）

任务单见[路线图 §2 H21](../roadmap.md)。分支 `feat/cn-h21-versioned-skills`，从 `origin/master` 的 `9b94274` 开出。H20（Claude B）也改 `jd_parser.py`，谁后合并谁合 master。V15 是本项的留出样例（Codex A 本地），PR 开出前不看 `cn-codex` 和 `codex/v15-*`。

## 进度

- 开工：读了任务单和规划者 10-30 的裁定。
- 看了现有写法：英文词条两侧不能紧挨字母或数字（`_skill_pattern`），所以 `HTML5`、`Vue3`、`Pythonv3.11` 读不出；带空格的 `Python 3.10`、`Photoshop 2024` 现在已能读到词条。词表 150 个词条，91 个英文；短词条里要防误读的有 `C4D`（本身带数字）、`PS`（`PS4`、`PS5` 是游戏机）、`Go`、`JS`、`K8s` 等。
- 暂停：规划者插了 H25a（隐私修复），先做那一项，做完回来。
- H25a（#86）做完并已合并，回到 H21。合了 master（`4463572`，含 H20 #79、H27 #82、H25a #86），没有冲突。

## 做法（已提交 `94afcfd`）

- `jd_parser._skill_pattern()`：英文词条后面可以跟一个版本号，紧贴或隔空格都行：数字和小数点，前面可以有 `v`，末尾可以有 `.x`（`HTML5`、`Vue2.x`、`Python 3.10`、`Pythonv3.11`、`Photoshop 2024`）。版本号算进匹配范围，所以"Python 3.10 或 Java 8"仍认作任选其一的组。版本号后面不能紧跟字母，所以 `C4D` 不会被拆开；可以跟 `+`（`Java8+`）。
- `PS` 后面隔不隔空格跟一位数字（`PS4`、`PS 5`）是游戏机，整个不读；跟年份（`PS2024`）仍算 Photoshop。
- 探针（`/tmp/h21probe.py`，不入库）：上面这些写法都按预期读出或不读；"有 3 年以上 Python 开发经验"、句末的"Python3." 不受影响。
- `RULES_VERSION` 6 → 7（`score.py` 注释、`test_cn_score.py`、`match.md` 的版本说明都已同步）。

## 下一步

1. `jd-parse.md` 的技能规则写上版本号的读法；
2. 解析器测试：读出和不误读的种子用例、版本号写法的出处和 schema 校验；
3. 跑全量测试，确认 V2、V4、V6、V7、V8 的对照测试不退步；
4. 路线图勾上 H25a（#86 已合并）；合 master，开 PR，告诉规划者。

## 存档（2026-10-30 傍晚，会话可能被压缩或重开）

- **已完成并推送**：解析改动 `94afcfd`；`RULES_VERSION` 7 和 `match.md` 版本说明 `4930909`；`jd-parse.md` 规则说明 `ae02720`；解析器测试 `3e24ca8`（种子用例加了读出和不误读两组，新测试类 `VersionedSkills` 查出处和 schema 校验；换回 master 的解析器，8 处失败）。已合 master `4463572`。
- **进行中**：全量测试在后台跑，结果未知。新会话先重跑：`D:/05_Software/Anaconda3/envs/ai-job-search-cn/python.exe -X utf8 -m unittest discover -s tests -t .`，再跑 `tools/security_guards.py`、`tools/lint_skills.py`，重点看 V2、V4、V6、V7、V8 的对照测试有没有退步。
- **下一步**：
  1. 路线图勾上 H25a（#86 已合并），H21 的条目写实际做法；
  2. 合最新 master：冲突两边保留；`RULES_VERSION` 在合并时的 master 基础上加 1，现在是 7，master 上是 6；
  3. 开 PR，告诉规划者（消息写短）。V15 是留出样例，PR 开出前不看 `cn-codex` 和 `codex/v15-*`。
- **未决，在 PR 里请规划者确认**：
  - "PS 5"（PS 和数字之间有空格）也当游戏机，不读。旧代码会把它读成 Photoshop；
  - 词条后面隔一个空格的数字都并进匹配范围，例如"Python 3 年以上"里的 3。读出的技能不变，只是出处片段的范围包括这个数字；
  - "Unity3D"这类"数字加字母"的写法仍读不出。词表里本来也没有 Unity。
- 全量测试通过：1338 个，跳过 11 个，含 V2、V4、V6、V7、V8 的对照测试；`security_guards`、`lint_skills` OK。路线图已勾 H25a，H21 写了实际做法。下一步：合 master，开 PR。

## 收尾（2026-10-30）

- 已和最新 master 同步（master 上 `RULES_VERSION` 为 6，本分支 7）。路线图勾上 H21。
- 三项检查：全量测试 1339 个通过、跳过 11 个；`security_guards` OK；`lint_skills` OK。开 PR，发给规划者。

## 规划者裁定后（#91）

- 数字后面跟时间、数量单位的不当版本号，也不当游戏机型号："Python 3 年以上"只匹配 Python，"Python3年以上"也读出 Python，"PS 5年以上"算 Photoshop。补了读出和不误读的种子用例，`VersionedSkills` 加了匹配范围的测试。`Unity3D` 不处理。
- `RULES_VERSION` 仍是 7；#90 先合并的话合 master 后改成 8。
