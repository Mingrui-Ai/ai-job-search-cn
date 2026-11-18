#!/usr/bin/env bun
import { parseArgs } from "node:util"
import { inbox, line, PortalError, posting, postingId, request } from "./helpers"
import { search } from "./commands/search"

const help =
  "search [-q text] [--location CN] [--employment-type Intern] [--jobage days] [--limit 1..20] [--page 1] [--format json|table|plain]\ndetail <company/slug|url> [--format json|plain|table|inbox]"
async function main() {
  const [command, ...args] = process.argv.slice(2)
  if (command === "--help" || args.includes("--help")) {
    console.log(help)
    return
  }
  if (command !== "detail" && command !== "search") throw new PortalError("BAD_ARGS", help)
  if (command === "detail") {
    const { values, positionals } = parseArgs({
      args,
      allowPositionals: true,
      options: { format: { type: "string", default: "json" } },
    })
    if (positionals.length !== 1 || !["json", "inbox", "plain", "table"].includes(values.format!))
      throw new PortalError("BAD_ARGS", help)
    const id = postingId(positionals[0])
    const [company, slug] = id.split("/")
    const payload = await request("/jobs/api/companies/" + company + "/jobs/" + slug)
    const job = posting(payload?.job)
    if (!job) throw new PortalError("CLOSED", "Posting expired.")
    if (job.id !== id) throw new PortalError("BAD_DATA", "Detail ID differs from the requested posting.")
    if (values.format === "plain" || values.format === "table")
      console.log(line(job) + "\n" + (job.description ?? ""))
    else console.log(JSON.stringify(values.format === "inbox" ? inbox(job) : job, null, 2))
    return
  }
  await search(args)
}

main().catch((error) => {
  const code =
    error instanceof PortalError
      ? error.code
      : error?.code?.startsWith("ERR_PARSE_ARGS")
        ? "BAD_ARGS"
        : "REQUEST_FAILED"
  console.error(JSON.stringify({ error: String(error.message ?? error), code }))
  process.exitCode = 1
})
