# 来源和改动

这个目录里的模板借自开源项目，随 `jobsearch_cn` 包一起发布，运行时不联网。

| 项目 | 内容 |
| --- | --- |
| 上游 | [habaneraa/typst-resume-one-page](https://github.com/habaneraa/typst-resume-one-page)（Typst 包名 `habaneraa-one-page-resume-zh`） |
| 提交 | `98aea62a4f37d9503247b4935087e26c84109a84`（2026-08-11） |
| 许可 | MIT，版权人 habaneraa，见同目录的 `LICENSE` |
| 取的文件 | `src/lib.typ`（SHA-256 `7880c2971b8f08914ea2ad44c774eb322d4a898ecd57ba6a77480b25be30beb5`），放在这里叫 `lib.typ` |

## 对 `lib.typ` 的改动

1. 去掉 `@preview/nerd-icons` 的导入和页头的图标调用（nerd-icons 是 LGPL-3.0）。联系方式改成纯文本，也不再加链接。
2. 章节标题和横线包进 `block(sticky: true)`，跟着后面的内容走，不再把标题留在页尾、横线和内容跑到下一页。没有跨页时，标题和正文的位置不变。

## 不是上游的文件

- `main.typ`：本项目自己写的入口，从 `resume.json` 读内容，从 `--input` 读间距和字体。
- `SOURCE.md`：这份说明。
