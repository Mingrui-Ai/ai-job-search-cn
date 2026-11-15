# 2026-11-15 · M3-2b照片简历的原生Word样例检查

## 完成

补充 [PR #174](https://github.com/Mingrui-Ai/ai-job-search-cn/pull/174) 的 Word 原生页面证据。受检实现为 `72bad8c27ccabc610a59e56c94130f4777d60a0c`，Git tree 为 `74433c53104eaa8deea63c7d5774fe6208218f27`；生成期间工作树无产品改动。本次变更只更新页面验收记录与文档入口。

五份虚构样例均由真实 `profile validate`、`material validate`、`resume build` 生成，再由 Microsoft Word 打开同一份 DOCX、重新分页并导出 PDF。每份另建编辑副本，在姓名末尾添加 `[EDITED]`，保存、关闭、重新打开，再导出页面。五份原稿和五份编辑副本均可正常打开，Word 均报告一页。

## 决策

使用 Windows 11 已安装的 Microsoft Word `16.0.20527.20196`，新建隐藏实例，只操作虚构样例，关闭本次实例。PowerShell 5.1 的 COM 参数绑定由本地验证脚本适配；没有给产品新增 Word 自动化、权限或依赖。

PDF 使用 Typst `0.15.1 (9dfd3a08)` 和本机 Noto Sans SC / Noto Serif SC，DOCX 使用等线。Typst Windows 便携包按发布页 SHA-256 `19ce3551153c2fe7ee9fa2f95208310c8f4d3209fedb699e0333faf8913f6736` 校验。本轮使用本机字体，没有把它表述成 Linux CI 固定字体环境。Word 分页由 Word 本身完成；PyMuPDF 用于最终 PDF 的页面渲染、位置与颜色辅助检查，pypdf `6.21.3` 用于文字与页数复查。

## 验证

输入来自公开虚构的 [tech-m3](../../../tests/fixtures/cn/material/tech-m3/) 档案和材料，图片来自 [PNG 测试夹具](../../../tests/test_cn_resume_photo.py) 的非对称四色图案。先固定输入及期望的尺寸、颜色、方向，再构建；输入清单 SHA-256 为 `973c8b66906b499fdabcc05dc0f5488dbb79cf2ffebef2637722f7f0a0a34566`。

| 样例 | 图片及内容 | Typst 间距 | PDF / Word / 编辑副本页数 |
| --- | --- | --- | --- |
| no-photo | 材料不选图，档案登记的图片故意不存在 | 1.5 | 1 / 1 / 1 |
| portrait-rgba | 400×600 RGBA，约21.33×32 mm，右下角半透明 | 1.5 | 1 / 1 / 1 |
| landscape-rgb | 800×400 RGB，25×12.5 mm | 1.5 | 1 / 1 / 1 |
| square-long-header | 320×320 RGBA，25×25 mm；长姓名、四项联系方式和五个求职方向 | 1.5 | 1 / 1 / 1 |
| portrait-dense | 400×600 RGBA；实习经历增加12条明确标记为虚构的排版条目 | 0.865 | 1 / 1 / 1 |

五份 Typst 页面、五份 Word 原稿导出页面、五份编辑副本导出页面，共15页全部渲染并逐页查看。文字可读且完整，照片四角颜色与非对称线方向正确，RGBA 在白色页面上的透明效果保留，图片完整等比显示；长抬头正常换行，未见与照片重叠、正文裁切或页外内容。

辅助检查也全部通过：Word 统计页数与导出 PDF 页数一致；全文按顺序与原 DOCX 对照，只忽略空白和既定的 Typst 条目副标题分隔差异；编辑副本只增加预期姓名标记。四份有图样例各含一张可见图片，实际尺寸与预期之差小于0.06 mm，图片与文字边界没有相交，四角颜色抽样吻合。这些检查没有新增产品级的 PDF 图片逐像素证明。

Word 检查结束后，重新核对全部输入、五组原始 PDF/DOCX/build note 的 SHA-256；字节未变，五组 `build_notes.check_outputs` 仍无问题。编辑副本单独存放，未覆盖原始产物，也未当作经过原生成说明核验的材料。

首次全量运行2307项，出现22条失败记录、16项跳过。失败来自本轮验证环境：测试子进程重设 `PYTHONPATH` 后找不到父进程可见的 pypdf；仓库内的 `TEMP` 又触发抓取测试禁止向仓库写入外部内容的守卫。依赖改放本轮独立的 `PYTHONUSERBASE`，`TEMP/TMP` 改为仓库外专用临时目录；产品、测试断言及守卫保持不变。涉及的18个测试定向复跑全部通过。

最终在 Windows 11 / Python 3.14.9 上重新完成仓库三检查：`python tools/lint_skills.py`、`python tools/security_guards.py` 和 `python -m unittest discover -s tests -t .` 均退出0。全量2307项，2291通过、16项按环境跳过，用时637.702秒；设置 `JOBSEARCH_CN_REQUIRE_TYPST=1`，真实 Typst 渲染实际执行。运行前冻结1591个 Git 路径的文件，结束后逐一核对未变；之后只回填本条记录的检查结果。三份文档的90个本地文件/目录引用目标均存在，UTF-8 替换字符与 diff 空白检查通过。

## 遗留

结论仅适用于上述 Word 版本、本机字体和五份虚构样例。WPS 本次未验；其他 Word 版本、真实用户材料及完整照片验收仍未完成。PDF 机器保证一页、Word 按实际环境分页的既有约定保持。

没有读取真实档案或照片。页面、测试日志和虚构导出是临时验证产物，核验后清理；本地可复用验证脚本和工具依赖保留。2026-11-14 工作记录中的旧 COM 失败与当时未验状态保留为历史，不改写旧结论。

## 下一步

将本记录作为照片分支的补充送审；后续按实际可用环境补 WPS 和真实用户本机页面确认，继续保留 M3-2b 未完成状态。
