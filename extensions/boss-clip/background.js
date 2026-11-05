// SPDX-License-Identifier: MIT (this repository's LICENSE)
// Runs only when the user clicks the toolbar button. activeTab grants access to the current
// tab for that click alone; clip.js reads the page once and returns the jobs. Nothing here
// navigates, opens pages, clicks, or talks to the network (see README.md).

const FOLDER = "jobsearch-boss-clip";

function badge(tabId, text, color, title) {
  chrome.action.setBadgeText({ tabId, text });
  chrome.action.setBadgeBackgroundColor({ tabId, color });
  chrome.action.setTitle({ tabId, title });
}

chrome.action.onClicked.addListener(async (tab) => {
  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["clip.js"],
    });
    if (!result || result.problem) {
      badge(tab.id, "×", "#b00020", (result && result.problem) || "没有读到岗位");
      return;
    }
    for (const entry of result.items) {
      const url = "data:application/json;charset=utf-8," + encodeURIComponent(JSON.stringify(entry.item, null, 2));
      await chrome.downloads.download({
        url,
        filename: `${FOLDER}/${entry.name}`,
        conflictAction: "uniquify",
        saveAs: false,
      });
    }
    const what = result.page === "detail" ? "这个岗位" : `${result.items.length} 个岗位卡片`;
    badge(tab.id, String(result.items.length), "#2e7d32", `已存 ${what}到 下载/${FOLDER}`);
  } catch (error) {
    badge(tab.id, "×", "#b00020", `没存成：${error && error.message ? error.message : error}`);
  }
});
