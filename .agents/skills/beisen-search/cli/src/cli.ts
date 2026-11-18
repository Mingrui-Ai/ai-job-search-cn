#!/usr/bin/env bun
import { resolve } from "node:path"
import { searchOutput } from "./commands/search"

// Portal host for /apply discovery: https://zhiye.com. Python admits only configured tenant subdomains.
// Pass arguments as argv. Source admission, robots and all portal parsing live in Python.
const root = resolve(import.meta.dir, "../../../../..")
const args = process.argv.slice(2)
// Run Python from this checkout so an older package in the caller's cwd cannot take precedence.
// Resolve the only filesystem argument and its environment fallback against the original cwd.
for (let i = 0; i < args.length; i++) {
  if (args[i] === "--data-dir" && args[i + 1] && !args[i + 1].startsWith("-")) {
    args[i + 1] = resolve(args[i + 1])
  } else if (args[i].startsWith("--data-dir=") && args[i] !== "--data-dir=") {
    args[i] = "--data-dir=" + resolve(args[i].slice("--data-dir=".length))
  }
}
const env = { ...process.env }
if (env.JOBSEARCH_CN_DATA_DIR) env.JOBSEARCH_CN_DATA_DIR = resolve(env.JOBSEARCH_CN_DATA_DIR)
try {
  const child = Bun.spawn(["python", "-m", "jobsearch_cn", "beisen-portal", ...args], {
    cwd: root,
    env,
    stdout: "pipe",
    stderr: "pipe",
  })
  const [stdout, stderr, status] = await Promise.all([
    new Response(child.stdout).text(), new Response(child.stderr).text(), child.exited,
  ])
  if (status === 0) {
    try {
      // Help, table and plain output have distinct non-JSON prefixes.
      process.stdout.write(args[0] === "search" && stdout.startsWith("{") ? searchOutput(stdout) : stdout)
    } catch {
      console.error(JSON.stringify({ error: "北森搜索结果缺少门户约定的字段", code: "BAD_DATA" }))
      process.exitCode = 1
    }
  } else {
    let failure = { error: "请检查已激活的 CN Python 环境", code: "PYTHON_UNAVAILABLE" }
    try {
      const parsed = JSON.parse(stderr)
      if (typeof parsed.error === "string" && typeof parsed.code === "string") {
        failure = { error: parsed.error, code: parsed.code }
      }
    } catch { /* Python itself failed before the portal started. */ }
    console.error(JSON.stringify(failure))
    process.exitCode = 1
  }
} catch {
  console.error(JSON.stringify({ error: "请使用已激活的 ai-job-search-cn Python 环境", code: "PYTHON_UNAVAILABLE" }))
  process.exitCode = 1
}
