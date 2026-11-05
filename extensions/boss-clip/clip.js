// SPDX-License-Identifier: MIT (this repository's LICENSE)
// BOSS直聘 page reader for the boss-clip extension. Injected into the current tab only when the
// user clicks the toolbar button; reads the page that is already open and returns the jobs on
// it as inbox items (docs/cn/screen.md §2.2). It never changes the page, scrolls, clicks,
// navigates or fetches anything.
//
// The selectors follow jobsearch_cn/boss.py of the M6-3 collector (PR #142); a layout change is
// fixed in SELECTORS here. Each rule is a list tried in order; the first that matches wins.
//
// Loaded by node for the offline tests (module.exports); in the browser the last line runs it.

(function (root) {
  "use strict";

  const FORMAT = "jobsearch_cn.inbox/1";
  const CLIPPER = "boss-clip/0.1.0";
  const HOSTS = ["www.zhipin.com", "zhipin.com"];
  const DETAIL_PATH = /^\/job_detail\/([A-Za-z0-9._~-]{1,128})\.html$/;

  const SELECTORS = {
    card: ["li.job-card-box", "li.job-card-wrapper", "div.job-card-wrap", ".card-area"],
    card_link: ["a.job-name[href]", "a.job-card-left[href]", 'a[href*="/job_detail/"]'],
    card_title: [".job-name", ".job-title"],
    card_salary: [".job-salary", ".salary"],
    card_location: [".company-location", ".job-area"],
    card_tags: [".tag-list > li", ".job-info .tag-list li"],
    card_company: [".boss-name", ".company-name", ".company-info .name"],
    detail_title: [".job-banner .name h1", ".info-primary .name h1", ".job-detail-box .job-name"],
    detail_salary: [".job-banner .salary", ".info-primary .salary", ".job-detail-box .job-salary"],
    detail_tags: [".info-primary > p > *", ".job-detail-box .tag-list > li"],
    detail_keywords: [".job-keyword-list > li"],
    detail_description: [".job-detail-section .job-sec-text", ".job-sec-text", ".job-detail-body .desc"],
    detail_address: [".job-location .location-address", ".location-address", ".job-address-desc"],
    detail_company: [".sider-company .company-info a", ".job-detail-company .company-name"],
    detail_company_info: [".sider-company > p"],
    detail_company_full: [".level-list .company-name"],
    // Not read: the recruiter and the online status, counters, recommendations, buttons. They
    // change from one visit to the next or describe other jobs (screen.md §2.3).
    detail_remove: [
      ".job-boss-info", ".boss-info-attr", ".boss-active-time", ".boss-online-tag",
      ".look-job-list", ".similar-job-list", ".promotion-img",
      ".sider-company .title", ".level-list li > span", ".job-op", ".btn",
    ],
    detail_closed: [".job-closed", ".job-status-closed"],
    blocked: ["[class*=captcha]", "[id*=captcha]", "[class*=geetest]", ".page-verify", "#verify-wrap"],
    // A dialog or form in the way stops the clip whatever is behind it; the header's 登录 link is
    // on signed-out pages that still show jobs, so it counts only when the page has no jobs.
    login_wall: ["[class*=login-dialog]", ".sign-form"],
    login_link: ["a[ka=header-login]"],
  };
  const CLOSED_STATUS = ".job-status";
  const CLOSED_WORDS = ["已关闭", "已下线", "停止招聘", "已失效", "已过期"];
  const REMOVED = SELECTORS.detail_remove.join(", ");
  // What a description block can hold before its text has loaded: headings and placeholders.
  const DESCRIPTION_HEADINGS = /职位描述|岗位描述|职位详情|岗位详情|岗位职责|工作职责|工作内容|任职要求|任职资格|岗位要求|职位要求/g;
  const EMPTY_DESCRIPTION_WORDS = /加载中|正在加载|暂无描述|暂无内容|暂无/g;
  // A status-only block can combine an object, state and instructions in either order.
  // Require both this whole-block grammar and a UI status signal: "加载数据" and "读取数据"
  // are short duties, whereas "正在加载数据，请稍等片刻" is a page state.
  const UI_OBJECT = "职位|岗位|工作|描述|详情|内容|信息|数据|页面|jobs?|positions?|descriptions?|details?|content|data|pages?|information";
  const UI_STATE = "正在|加载|载入|读取|获取|中|失败|错误|异常|暂无|loading|loaded|load|failed|failure|error|unavailable|unable|couldnot|couldnt|cannot|cant";
  const UI_PROMPT = "请|您|稍候|稍后|稍等|片刻|一下|一会儿?|一小会|几|秒钟?|分钟|耐心|等待|刷新|重试|再试|重新|为您|抱歉|please|wait|waiting|a|an|the|your|this|for|while|we|are|is|be|to|of|and|just|moments?|seconds?|minutes?|few|short|little|bit|refresh|reload|retry|try|again|later|sorry";
  const PLACEHOLDER_DESCRIPTION = new RegExp(`^(?:${UI_OBJECT}|${UI_STATE}|${UI_PROMPT})+$`, "iu");
  const UI_STATUS_SIGNAL = /正在(?:为您)?(?:加载|载入|读取|获取)|(?:加载|载入|读取|获取)中|失败|错误|异常|请(?:您)?(?:稍候|稍后|稍等|耐心|等待|刷新|重试)|稍候|稍后|稍等|暂无|loading|failed|failure|error|unavailable|unable|couldnot|couldnt|cannot|cant|pleasewait|waiting|wait(?:for)?a?moment|justamoment|refresh|reload|retry|tryagain/iu;

  function jobIdFromUrl(href, base) {
    let url;
    try {
      url = new URL(href, base || "https://www.zhipin.com/");
    } catch (error) {
      return null;
    }
    if (!["http:", "https:"].includes(url.protocol) || !HOSTS.includes(url.hostname.toLowerCase())) return null;
    const match = DETAIL_PATH.exec(url.pathname);
    return match ? match[1] : null;
  }

  function canonicalUrl(id) {
    return `https://www.zhipin.com/job_detail/${id}.html`;
  }

  function squash(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  function lines(text) {
    return String(text || "")
      .split(/\r?\n/)
      .map((line) => line.replace(/[ \t 　]+/g, " ").trim())
      .filter((line) => line)
      .join("\n");
  }

  // The text a user sees in a node, without the parts in detail_remove (read from a copy, so the
  // page itself is never changed).
  function rawText(node, skip) {
    if (skip && node.querySelector(skip)) {
      const copy = node.cloneNode(true);
      for (const doomed of Array.from(copy.querySelectorAll(skip))) doomed.remove();
      return copy.textContent || "";
    }
    return node.innerText != null ? node.innerText : node.textContent || "";
  }

  function select(scope, rule, skip) {
    for (const selector of SELECTORS[rule]) {
      const nodes = Array.from(scope.querySelectorAll(selector)).filter((node) => !(skip && node.closest(skip)));
      if (nodes.length) return nodes;
    }
    return [];
  }

  function textOf(scope, rule, skip, keepLines) {
    const node = select(scope, rule, skip)[0];
    if (!node) return "";
    const text = rawText(node, skip);
    return keepLines ? lines(text) : squash(text);
  }

  function textsOf(scope, rule, skip) {
    return select(scope, rule, skip).map((node) => squash(rawText(node, skip))).filter((text) => text);
  }

  function pad(number, width) {
    return String(number).padStart(width || 2, "0");
  }

  // ISO 8601 with the local offset, e.g. 2026-11-05T10:31:20+08:00.
  function isoLocal(now) {
    const offset = -now.getTimezoneOffset();
    const sign = offset >= 0 ? "+" : "-";
    const abs = Math.abs(offset);
    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:` +
      `${pad(now.getMinutes())}:${pad(now.getSeconds())}${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
  }

  // File names sort in clip order, so a detail page clipped after its list card comes later in
  // the batch and replaces the card's summary text (screen.md §3).
  function stamp(now) {
    return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-` +
      `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}-${pad(now.getMilliseconds(), 3)}`;
  }

  // Pages can keep a closed dialog in the DOM, so only one the user can see counts.
  function isShown(node) {
    if (node.checkVisibility && !node.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
    const box = node.getBoundingClientRect();
    return box.width > 0 && box.height > 0;
  }

  // Page markup only, never the words of the job text: a JD may well say 登录 or 验证码.
  function pageProblem(doc) {
    for (const selector of SELECTORS.blocked) {
      if (doc.querySelector(selector)) return "页面上有验证码或安全验证，先在页面上完成验证再点";
    }
    for (const selector of SELECTORS.login_wall) {
      if (Array.from(doc.querySelectorAll(selector)).some(isShown)) return "页面被登录弹窗或登录表单挡住，先登录，刷新页面再点";
    }
    if (select(doc, "detail_title").length || select(doc, "card").length) return null;
    for (const selector of SELECTORS.login_link) {
      if (doc.querySelector(selector)) return "页面显示没有登录";
    }
    return null;
  }

  function isClosed(doc) {
    if (select(doc, "detail_closed").length) return true;
    const status = Array.from(doc.querySelectorAll(CLOSED_STATUS)).map((node) => squash(rawText(node))).join(" ");
    return CLOSED_WORDS.some((word) => status.includes(word));
  }

  function hasDescription(text) {
    const body = text.replace(DESCRIPTION_HEADINGS, "");
    const letters = body.replace(/[^\p{L}]/gu, "");
    if (UI_STATUS_SIGNAL.test(letters) && PLACEHOLDER_DESCRIPTION.test(letters)) return false;
    return (body.replace(EMPTY_DESCRIPTION_WORDS, "").match(/\p{L}/gu) || []).length >= 2;
  }

  // The inbox text of a detail page, laid out like a whole-page copy (jd-parse.md): title and
  // salary, the tag line, the description, the work address, then the company.
  function detailText(doc, title, description) {
    const skip = REMOVED;
    const company = textsOf(doc, "detail_company", skip)[0] || "";
    const companyFull = textOf(doc, "detail_company_full", skip);
    const tags = textsOf(doc, "detail_tags", skip);
    const keywords = textsOf(doc, "detail_keywords", skip);
    const address = textOf(doc, "detail_address", skip);
    const info = textsOf(doc, "detail_company_info", skip);
    const out = [[title, textOf(doc, "detail_salary", skip)].filter((x) => x).join(" ")];
    if (tags.length) out.push(tags.join(" "));
    out.push("职位描述");
    if (keywords.length) out.push(keywords.join(" "));
    out.push(description);
    if (address) out.push("工作地址", address);
    if (company) out.push(company);
    if (info.length) out.push(info.join(" "));
    if (companyFull && companyFull !== company) out.push(companyFull);
    return out.filter((line) => line).join("\n");
  }

  function cardText(card) {
    const head = [textOf(card, "card_title"), textOf(card, "card_salary")].filter((x) => x).join(" ");
    const tags = [textOf(card, "card_location")].concat(textsOf(card, "card_tags")).filter((x) => x).join(" ");
    return [head, tags, textOf(card, "card_company")].filter((x) => x).join("\n");
  }

  function item(id, text, now, extra) {
    return {
      format: FORMAT,
      site: "boss",
      site_job_id: id,
      url: canonicalUrl(id),
      fetched_at: isoLocal(now),
      text,
      extra: Object.assign({ clipper: CLIPPER }, extra),
    };
  }

  // {page: "detail" | "list", items: [{name, item}]} or {problem: "..."}: what one click saves.
  function clipPage(doc, pageUrl, now) {
    let host = "";
    try {
      host = new URL(pageUrl).hostname.toLowerCase();
    } catch (error) {
      host = "";
    }
    if (!HOSTS.includes(host)) return { problem: "这不是 BOSS 直聘（www.zhipin.com）的页面" };
    const problem = pageProblem(doc);
    if (problem) return { problem };
    const time = stamp(now);
    const detailId = jobIdFromUrl(pageUrl);
    if (detailId) {
      if (isClosed(doc)) return { problem: "这个岗位已经关闭或下线" };
      // A heading or description with nothing to read is a page still loading; its item would
      // replace the saved job's text.
      const title = textOf(doc, "detail_title", REMOVED);
      if (!/[\p{L}\p{N}]/u.test(title)) return { problem: "没在这一页读到职位名，页面可能还没加载完或结构变了" };
      const description = textOf(doc, "detail_description", REMOVED, true);
      if (!hasDescription(description)) return { problem: "没在这一页读到职位描述，页面可能还没加载完或结构变了" };
      const text = detailText(doc, title, description);
      return { page: "detail", items: [{ name: `${time}-${detailId}.json`, item: item(detailId, text, now, { page: "detail" }) }] };
    }
    const seen = new Set();
    const items = [];
    for (const card of select(doc, "card")) {
      const link = select(card, "card_link")[0];
      const id = link ? jobIdFromUrl(link.getAttribute("href"), pageUrl) : null;
      const text = cardText(card);
      if (!id || !text || seen.has(id)) continue;
      seen.add(id);
      items.push({ name: `${time}-${id}.json`, item: item(id, text, now, { page: "list", list_url: pageUrl }) });
    }
    if (!items.length) return { problem: "这一页没有读到岗位：打开岗位详情页或搜索结果列表再点" };
    return { page: "list", items };
  }

  const api = { SELECTORS, FORMAT, jobIdFromUrl, canonicalUrl, isoLocal, stamp, clipPage };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.__bossClip = api;
})(globalThis);

typeof document === "undefined" ? undefined : globalThis.__bossClip.clipPage(document, location.href, new Date());
