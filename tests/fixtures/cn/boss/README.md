# BOSS 直聘页面样例（虚构）

`collect boss` 的离线测试用（`tests/test_cn_collect.py`）。结构按 `jobsearch_cn/boss.py` 的选择器写，
内容全部虚构：公司、人名、地址、岗位 ID 都不是真的，`securityId` 等参数也是假的。不要放真实页面或真实岗位文字。

- `list.html`：搜索结果第一屏，3 个岗位卡片；
- `list-more.html`：往下滚动加载以后，同样 3 个加 2 个新的；
- `detail.html`：一个岗位的详情页，带导航、招聘者在线状态、"看过该职位的人还看了"、页脚这些不该进收件夹正文的内容。
