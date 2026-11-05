// SPDX-License-Identifier: MIT (this repository's LICENSE)
// Offline check of clip.js (run by tests/test_cn_boss_clip.py): builds made-up BOSS pages from
// a tiny fake DOM, runs clipPage on each and prints the results as JSON. The fake DOM matches a
// selector by name only: each node lists the selectors it answers to, so the test exercises the
// rule order, the parts that are skipped and the text layout, not a CSS engine.

"use strict";
const path = require("path");
const clip = require(path.join(__dirname, "..", "clip.js"));

class Node {
  constructor(matches, text, children, attrs) {
    this.matches = matches || [];
    this.text = text || "";
    this.children = [];
    this.parent = null;
    this.attrs = attrs || {};
    for (const child of children || []) this.append(child);
  }
  append(child) {
    child.parent = this;
    this.children.push(child);
  }
  descendants() {
    return this.children.flatMap((child) => [child, ...child.descendants()]);
  }
  answers(selectors) {
    return selectors.split(", ").some((selector) => this.matches.includes(selector));
  }
  querySelectorAll(selectors) {
    return this.descendants().filter((node) => node.answers(selectors));
  }
  querySelector(selectors) {
    return this.querySelectorAll(selectors)[0] || null;
  }
  closest(selectors) {
    for (let node = this; node; node = node.parent) if (node.answers(selectors)) return node;
    return null;
  }
  getAttribute(name) {
    return name in this.attrs ? this.attrs[name] : null;
  }
  checkVisibility() {
    return !this.attrs.hidden;
  }
  getBoundingClientRect() {
    return this.attrs.zero ? { width: 0, height: 0 } : { width: 100, height: 40 };
  }
  cloneNode() {
    return new Node(this.matches, this.text, this.children.map((child) => child.cloneNode()), this.attrs);
  }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter((child) => child !== this);
    this.parent = null;
  }
  get textContent() {
    return this.text + this.children.map((child) => child.textContent).join("");
  }
  get innerText() {
    return [this.text, ...this.children.map((child) => child.innerText)].filter((x) => x).join("\n");
  }
}

const n = (matches, text, children, attrs) => new Node([].concat(matches || []), text, children, attrs);
const NOW = new Date(2026, 10, 5, 10, 31, 20, 7);

const detail = n([], "", [
  n(".job-banner .name h1", "数据分析实习生"),
  n(".job-banner .salary", "150-200元/天"),
  n(".info-primary > p > *", "广州"),
  n(".info-primary > p > *", "4天/周"),
  n(".info-primary > p > *", "6个月"),
  n(".info-primary > p > *", "本科"),
  n(".job-boss-info", "", [n(".boss-active-time", "刚刚活跃"), n(".job-banner .name h1", "王女士")]),
  n(".job-sec-text", "1. 整理业务数据\n\n2. 写周报 　"),
  n(".location-address", "广州市天河区某路 1 号"),
  n(".sider-company .company-info a", "示例数据科技"),
  n(".sider-company > p", "", [n(".level-list li > span", "融资阶段"), n([], "A轮")]),
  n(".sider-company > p", "100-499人"),
  n(".similar-job-list", "", [n(".job-sec-text", "别的岗位 300元/天")]),
]);

const list = n([], "", [
  n("li.job-card-box", "", [
    n(["a.job-name[href]", ".job-name"], "后端开发实习生", [], { href: "/job_detail/abc_123~x.html?lid=9&securityId=s" }),
    n(".job-salary", "200-250元/天"),
    n(".company-location", "深圳·南山区"),
    n(".tag-list > li", "5天/周"),
    n(".tag-list > li", "本科"),
    n(".boss-name", "示例软件"),
  ]),
  n("li.job-card-box", "", [n(".job-name", "没有链接的卡片")]),
  n("li.job-card-box", "", [n(['a[href*="/job_detail/"]', ".job-name"], "外站链接", [], { href: "https://evil.example/job_detail/zz.html" })]),
  n("li.job-card-box", "", [n(["a.job-name[href]", ".job-name"], "后端开发实习生", [], { href: "/job_detail/abc_123~x.html" })]),
]);

const DETAIL_URL = "https://www.zhipin.com/job_detail/bx0002.html";
const LIST_URL = "https://www.zhipin.com/web/geek/jobs";
const LOGIN_DIALOG = "[class*=login-dialog]";
const HEADER_LOGIN = "a[ka=header-login]";
const jobParts = () => [n(".job-banner .name h1", "数据分析实习生"), n(".job-sec-text", "负责整理数据")];
const card = () => n("li.job-card-box", "", [
  n(["a.job-name[href]", ".job-name"], "后端开发实习生", [], { href: "/job_detail/abc.html" }),
]);
const detailWith = (...extra) => clip.clipPage(n([], "", [...extra, ...jobParts()]), DETAIL_URL, NOW);
const titled = (title) => clip.clipPage(
  n([], "", [n(".job-banner .name h1", title), n(".job-sec-text", "负责整理数据")]), DETAIL_URL, NOW);

const TITLE = () => n(".job-banner .name h1", "数据分析实习生");
const described = (text) => clip.clipPage(n([], "", [TITLE(), n(".job-sec-text", text)]), DETAIL_URL, NOW);

const results = {
  detail: clip.clipPage(detail, "https://www.zhipin.com/job_detail/bx0001.html?ka=x", NOW),
  list: clip.clipPage(list, "https://www.zhipin.com/web/geek/jobs?query=x&city=101280600", NOW),
  captcha: clip.clipPage(n([], "", [n("[class*=geetest]", ""), n("li.job-card-box", "")]), "https://www.zhipin.com/web/geek/jobs", NOW),
  closed: clip.clipPage(n([], "", [n(".job-banner .name h1", "x"), n(".job-status", "该职位已关闭")]), "https://www.zhipin.com/job_detail/c1.html", NOW),
  signed_out: clip.clipPage(n([], "", [n("a[ka=header-login]", "登录")]), "https://www.zhipin.com/web/geek/jobs", NOW),
  other_site: clip.clipPage(detail, "https://www.zhipin.com.evil.example/job_detail/bx0001.html", NOW),
  empty: clip.clipPage(n([], ""), "https://www.zhipin.com/", NOW),
  // A login dialog or form over a page that still holds its old job.
  dialog_over_title: detailWith(n(LOGIN_DIALOG, "登录后查看职位详情")),
  form_over_title: detailWith(n(".sign-form", "")),
  dialog_over_cards: clip.clipPage(n([], "", [n(LOGIN_DIALOG, ""), card()]), LIST_URL, NOW),
  form_over_cards: clip.clipPage(n([], "", [n(".sign-form", ""), card()]), LIST_URL, NOW),
  second_dialog_shown: detailWith(n(LOGIN_DIALOG, "", [], { hidden: true }), n(LOGIN_DIALOG, "登录")),
  captcha_over_title: detailWith(n("[class*=captcha]", "")),
  closed_with_title: detailWith(n(".job-status", "该职位已关闭")),
  // These do not stand in the way: the job is saved.
  hidden_dialog: detailWith(n(LOGIN_DIALOG, "登录", [], { hidden: true })),
  zero_size_dialog: detailWith(n(LOGIN_DIALOG, "", [], { zero: true })),
  header_link_detail: detailWith(n(HEADER_LOGIN, "登录")),
  header_link_list: clip.clipPage(n([], "", [n(HEADER_LOGIN, "登录"), card()]), LIST_URL, NOW),
  jd_words: clip.clipPage(n([], "", [
    n(".job-banner .name h1", "登录模块开发实习生"),
    n(".job-sec-text", "开发登录弹窗和验证码，处理已关闭、已下线的账号，安全验证"),
  ]), DETAIL_URL, NOW),
  // A heading with nothing to read: the skeleton of a page still loading.
  empty_h1: clip.clipPage(n([], "", [n(".job-banner .name h1", "")]), DETAIL_URL, NOW),
  empty_h1_with_text: titled(""),
  blank_h1: titled(" \t\n\u3000\u00a0"),
  zero_width_h1: titled("\u200b"),
  punctuation_h1: titled("--"),
  removed_h1: clip.clipPage(n([], "", [
    n(".job-boss-info", "", [n(".job-banner .name h1", "王女士")]),
    n(".job-sec-text", "负责整理数据"),
  ]), DETAIL_URL, NOW),
  // A title but no description to read: its item would empty the description of a saved job.
  no_description: clip.clipPage(n([], "", [TITLE()]), DETAIL_URL, NOW),
  no_description_with_company: clip.clipPage(n([], "", [
    TITLE(), n(".job-keyword-list > li", "SQL"), n(".sider-company .company-info a", "示例数据科技"),
  ]), DETAIL_URL, NOW),
  other_jobs_description: clip.clipPage(n([], "", [
    TITLE(), n(".similar-job-list", "", [n(".job-sec-text", "别的岗位 300元/天")]),
  ]), DETAIL_URL, NOW),
  empty_description: described(""),
  blank_description: described(" \n\u3000\u00a0\t"),
  heading_description: described("职位描述"),
  headings_description: described("岗位职责：\n任职要求："),
  loading_description: described("正在加载..."),
  loading_wait_description: described("正在加载，请稍候..."),
  loading_english_description: described("Loading..."),
  loading_moment_description: described("Loading, please wait a moment..."),
  loading_brief_description: described("正在加载，请稍等片刻..."),
  loading_object_description: described("Loading job description, please wait..."),
  loading_failed_description: described("加载失败，请刷新重试"),
  none_description: described("暂无"),
  one_letter_description: described("无"),
  punctuation_description: described("-- 1. 2."),
  // Controls: short or heading-led, but something to read.
  short_description: described("负责整理数据"),
  shortest_description: described("写周报"),
  headed_description: described("岗位职责：写周报\n任职要求：会 SQL"),
  english_description: described("Write SQL"),
  loading_work_description: described("开发加载中的提示组件，优化数据加载性能"),
  waiting_work_description: described("Implement Loading and Please wait messages"),
  mixed_loading_description: described("正在加载，请稍候...\n岗位职责：写周报"),
  load_data_description: described("加载数据"),
  read_data_description: described("读取数据"),
  java_description: described("Java"),
  implement_loading_description: described("实现 Loading 状态"),
  retry_work_description: described("负责刷新缓存并重试失败请求"),
  numbered_work_description: described("每天读取3次数据并核对２张报表"),
  numbered_load_description: described("加载3组数据"),
  full_detail: described("负责整理业务数据，每周写周报，维护数据看板"),
  card_of_full_detail: clip.clipPage(n([], "", [n("li.job-card-box", "", [
    n(["a.job-name[href]", ".job-name"], "数据分析实习生", [], { href: "/job_detail/bx0002.html" }),
    n(".job-salary", "150-200元/天"),
  ])]), LIST_URL, NOW),
  edited_detail: described("负责整理业务数据，每周写周报，维护数据看板，并参与需求评审"),
  ids: [
    clip.jobIdFromUrl("https://zhipin.com/job_detail/A.b_c~d-e.html"),
    clip.jobIdFromUrl("http://www.zhipin.com/job_detail/a%2Fb.html"),
    clip.jobIdFromUrl("javascript:alert(1)"),
    clip.jobIdFromUrl("/job_detail/rel.html", "https://www.zhipin.com/web/geek/jobs"),
  ],
  fetched_at: clip.isoLocal(NOW),
};
// Whole-block UI placeholders vary by punctuation, casing, line breaks and progress numbers.
// Keep them separate from actual short duties that happen to mention loading or waiting.
results.placeholder_descriptions = [
  "正在加载，请稍候...", "正在加载，请稍后…", "加载中，请稍等", "正在加载中...",
  "请稍候", "请稍后", "请耐心等待", "数据加载中，请稍候", "正在加载数据，请稍后",
  "职位描述：\n正在加载，请稍候...\n岗位职责：\n任职要求：",
  "正在加载 50%，请稍候…", "正在\u200b加载，请稍候", "暂无内容，请稍后",
  "Loading...", "LOADING…", "Loading, please wait...", "Please wait...",
  "Loading content… Please wait", "Please wait, loading data...", "Just a moment...",
  "Loading, please wait a moment...", "正在加载，请稍等片刻...",
  "Loading job description, please wait...", "加载失败，请刷新重试",
  "正在为您加载职位信息...", "内容加载中，请稍等一会", "加载中，请稍等几秒钟",
  "Loading job details, please wait a few seconds...", "Unable to load job description. Please try again later.",
  "Sorry, we couldn't load your job details. Please reload this page.",
  "正在加载，请稍等3秒", "正在加载，请稍等３秒",
  "Loading, please wait 3 seconds...", "Loading, please wait ３ seconds...",
  ...["正在加载", "内容正在加载", "正在加载岗位描述", "职位详情加载失败", "数据获取失败"]
    .flatMap((state) => ["请稍等片刻", "请耐心等待", "请刷新重试", "稍后再试"]
      .map((prompt) => `${state}，${prompt}…`)),
  ...["Loading", "Loading job description", "Job details are loading", "Failed to load job content", "Job description loading failed"]
    .flatMap((state) => ["please wait a moment", "please wait for a moment", "Please refresh the page and try again", "please retry"]
      .map((prompt) => `${state}. ${prompt}...`)),
].map((text) => ({ text, result: described(text) }));
process.stdout.write(JSON.stringify(results));
