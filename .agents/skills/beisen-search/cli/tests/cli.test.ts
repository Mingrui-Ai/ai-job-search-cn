import { expect, test } from "bun:test"
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { searchOutput } from "../src/commands/search"

const cli = join(import.meta.dir, "../src/cli.ts")

test("search JSON has exactly the Step 2 fields and preserves missing facts as null", () => {
  const row = { id: "beisen.example.1", title: "虚构岗位", company: "虚构公司", location: null,
    date: null, url: "https://example.zhiye.com/zpdetail/1" }
  const meta = { page: 1, count: 1 }
  const output = searchOutput(JSON.stringify({ meta, results: [{ ...row, unused: "extra" }] }))
  expect(JSON.parse(output)).toEqual({ meta, results: [row] })
  expect(() => searchOutput(JSON.stringify({ meta, results: [{ ...row, url: null }] }))).toThrow()
})

// An empty temporary directory also checks running the entry point from outside the repo.
async function run(args: string[], otherCheckout = false) {
  const cwd = mkdtempSync(join(tmpdir(), "beisen-cli-"))
  try {
    if (otherCheckout) {
      const pkg = join(cwd, "jobsearch_cn")
      mkdirSync(pkg)
      writeFileSync(join(pkg, "__init__.py"), "")
      writeFileSync(join(pkg, "__main__.py"), "raise SystemExit(72)")
      const config = join(cwd, "relative", "collect")
      mkdirSync(config, { recursive: true })
      writeFileSync(join(config, "beisen.json"), JSON.stringify({
        format: "jobsearch_cn.beisen/1",
        tenants: [{ subdomain: "example", portal: "legacy", company: "虚构公司", channels: ["campus"],
          cities: ["广州"], terms_url: "https://example.zhiye.com/privacy", terms_checked: "2020-01-01" }],
      }))
    }
    const child = Bun.spawn(["bun", "run", cli, ...args], {
      cwd,
      env: { ...process.env, JOBSEARCH_CN_DATA_DIR: otherCheckout ? "relative" : cwd },
      stdout: "pipe",
      stderr: "pipe",
    })
    const [stdout, stderr, code] = await Promise.all([
      new Response(child.stdout).text(), new Response(child.stderr).text(), child.exited,
    ])
    return { stdout, stderr, code }
  } finally {
    rmSync(cwd, { recursive: true, force: true })
  }
}

test("help lists the portal's bounded options", async () => {
  const out = await run(["search", "--help"])
  expect(out.code).toBe(0)
  expect(out.stdout).toContain("--jobage")
  expect(out.stdout).toContain("--channel")
})

test("missing detail and unknown flag are JSON errors", async () => {
  for (const args of [["detail"], ["search", "--tenant", "example", "--channel", "campus", "--invalid"]]) {
    const out = await run(args)
    expect(out.code).toBe(1)
    expect(out.stdout).toBe("")
    expect(JSON.parse(out.stderr).code).toBe("BAD_ARGS")
  }
})

test("valid arguments still require a local whitelist", async () => {
  const out = await run(["search", "-q", "软件", "--tenant", "example", "--channel", "campus", "--limit", "1"])
  expect(out.code).toBe(1)
  expect(out.stdout).toBe("")
  expect(JSON.parse(out.stderr).code).toBe("WHITELIST")
})

test("another checkout cannot shadow this CLI, relative data roots use the caller's cwd", async () => {
  for (const data of [[], ["--data-dir", "relative"], ["--data-dir=relative"]]) {
    // BAD_ARGS for page 2 proves the allowlisted tenant was found, without opening a browser.
    const out = await run(["search", "--tenant", "example", "--channel", "campus", "--page", "2", ...data], true)
    expect(out.code).toBe(1)
    expect(JSON.parse(out.stderr).code).toBe("BAD_ARGS")
  }
})
