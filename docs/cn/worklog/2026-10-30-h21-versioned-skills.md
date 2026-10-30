# 2026-10-30 · H21：带版本号的技能写法（进行中，Claude C）

任务单见[路线图 §2 H21](../roadmap.md)。分支 `feat/cn-h21-versioned-skills`，从 `origin/master` 的 `9b94274` 开出。H20（Claude B）也改 `jd_parser.py`，谁后合并谁合 master。V15 是本项的留出样例（Codex A 本地），PR 开出前不看 `cn-codex` 和 `codex/v15-*`。

## 进度

- 开工：读了任务单和规划者 10-30 的裁定。
- 看了现有写法：英文词条两侧不能紧挨字母或数字（`_skill_pattern`），所以 `HTML5`、`Vue3`、`Pythonv3.11` 读不出；带空格的 `Python 3.10`、`Photoshop 2024` 现在已能读到词条。词表 150 个词条，91 个英文；短词条里要防误读的有 `C4D`（本身带数字）、`PS`（`PS4`、`PS5` 是游戏机）、`Go`、`JS`、`K8s` 等。
- 暂停：规划者插了 H25a（隐私修复），先做那一项，做完回来。
