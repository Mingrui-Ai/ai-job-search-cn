# 2026-10-28 · 总体规划 v4：第三个 Agent DeepSeek Harness；简历支持 Word 和 PDF（规划会话）

**完成**

- 总体规划升到 v4：
  - O3、O6、目标用户、典型场景、系统全貌、数据对象都写进第三个 Agent，以及 Word、PDF 两种简历格式；
  - M3、M6、M7、M8 的完成标准相应修改；
  - 新增"并行任务 A：接入 DeepSeek Harness"；
  - D1 改为部分已定，新增 D7；
  - "与原计划的差异"和版本记录同步更新；
  - M1 标为完成。
- 路线图：
  - 新增 §2b 跨里程碑的任务：A1 调研、A2 入口、A3 实测，H11 建档支持 Word 和 PDF 简历；
  - M3-0、M3-2 改成两种格式都输出；M7-3、M8-1 改成三个 Agent；
  - 风险表加上 dsh 还是预览版；看板更新。

**决策**（用户 2026-10-28）

- 加入第三个 Agent：DeepSeek 官方开源的 DeepSeek Harness（`dsh`），接 DeepSeek API，让国内同学更容易用上、也用得起。用户随后明确：dsh 是给国内用户找工作用的运行环境，不参与本项目的开发。
- 简历的输入和输出都支持常用的 Word（.docx）和 PDF。

**规划者的补充**

- dsh 还是开发者预览版，官方说明会有不兼容的变更。接入时固定一个版本；入口只做薄薄一层，逻辑都在共用的工作流说明和 `python -m jobsearch_cn` 命令里；升级前重新实测。
- API Key 只放在 dsh 自己的设置里（设置界面或 `DEEPSEEK_API_KEY`）。`jobsearch_cn` 仍然不调用模型，也不读取、不保存密钥，原则不变。
- 先调研、后接入：公开资料还说不清 dsh 会不会读取 `AGENTS.md`、项目级技能放在哪个目录（第三方教程说是 `.dsh/skills`）。本仓库的 `.agents/skills/` 只能放招聘门户适配器，所以入口的位置要等 A1 确认。
- 排期：A1 现在就做，不影响 M2；A2、A3 排在 M2 完成之后、M3 开工之前，这样 M3 的简历工作流从一开始就按三个 Agent 设计。
- 简历输出用哪种方式生成（DOCX 模板转 PDF，还是 Typst/LaTeX 出 PDF、再另外生成 DOCX），仍然留到 M3-0 做完原型对比再定。输入由 H11 用一个确定性的文本提取命令统一处理，三个 Agent 都能用。

**依据**（2026-10-28 查阅）

- 官方仓库 <https://github.com/deepseek-ai/deepseek-harness>；
- 官方用户指南 `docs/user/guide/index.md`：能运行命令、读写工作区文件，危险操作前请求确认，在 Settings → Models 配置 DeepSeek API Key；
- 关于技能目录的第三方教程，例如 <https://github.com/daoge96/dsh-skills>。

**下一步**：规划者做 A1 的文档部分，写出试用清单；用户有空时安装 dsh 试一次。
