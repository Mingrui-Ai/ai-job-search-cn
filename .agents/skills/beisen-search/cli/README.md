# Beisen CLI

从仓库根运行 `bun run .agents/skills/beisen-search/cli/src/cli.ts search --help` 或 `detail --help`。此薄入口调用 `python -m jobsearch_cn beisen-portal`，两者共享全部选项、输出格式与退出码。运行需要当前仓库、Bun 和已激活的 CN Python 环境。读取页面还需已安装 Playwright 和本机 Chrome。租户配置见 [采集说明](../../../../docs/cn/collect.md)，命令示例见 [技能说明](../SKILL.md)。

开发时在本目录运行 `bun install`、`bun run typecheck`、`bun test`。从仓库根运行 `python -m unittest tests.test_cn_beisen_portal tests.test_cn_beisen tests.test_cn_single_link` 可核对合成页面和旧入口。
