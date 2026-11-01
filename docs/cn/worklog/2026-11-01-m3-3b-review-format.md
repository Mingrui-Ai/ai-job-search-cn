# 2026-11-01 · M3-3 第二部分：审核结果格式、review validate 和机器初稿（Claude A）

**完成**

- 新增 `jobsearch_cn/review.py`：审核结果的格式检查、材料摘要、机器初稿（JD 技能覆盖、E1 和 E3 的警告）、渲染 Markdown。
- 新增命令 `review draft`、`review validate`、`review show`。
- 新增文档 [review-format.md](../review-format.md)；`review-checklist.md` §4.3 指向它；`docs/cn/README.md` 的文档表加了两行；路线图 M3-3 下注明第二部分进行中。
- 新增测试 `tests/test_cn_review.py`。

**决策**

- 审核结果记下所审材料的摘要，材料改过就不通过，避免第 2 轮拿第 1 轮的结果交差。
- 审核结果里的 `material` 只取文件名，审核结果和材料必须在同一目录，不能指到别处。
- 机器初稿只列 JD 解析出的技能要求；学历、经验、业务词留给审核者。"只差大小写"算 `covered`，大小写写法归 E2。
- E1、E3 的检查放在 `review draft` 的 `style` 里，只给警告，不加进 `material validate`（裁定 6）。
- `cli.py` 里把读 JSON 文件和查岗位抽成两个小函数，`material validate` 和 `review draft` 共用，行为不变。

**验证**

- 见 PR 描述。

**遗留**

- 叠在 #108 上，#108 合并后合入 master 再开 PR。
