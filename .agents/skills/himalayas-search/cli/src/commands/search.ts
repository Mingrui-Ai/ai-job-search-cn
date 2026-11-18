import { parseArgs } from "node:util"
import { line, origin, PortalError, posting, request, type Posting } from "../helpers"

function integer(s: string | undefined, fallback: number, low: number, high: number): number {
  if (s === undefined) return fallback
  if (!/^\d+$/.test(s) || +s < low || +s > high)
    throw new PortalError("BAD_ARGS", "Expected an integer from " + low + " to " + high)
  return +s
}

export async function search(args: string[]) {
  const { values } = parseArgs({
    args,
    options: {
      query: { type: "string", short: "q" },
      location: { type: "string", short: "l" },
      "employment-type": { type: "string" },
      jobage: { type: "string" },
      page: { type: "string" },
      limit: { type: "string", short: "n" },
      format: { type: "string", default: "json" },
    },
  })
  integer(values.page, 1, 1, 1) // The source's published robots policy excludes paginated /jobs URLs.
  const cap = integer(values.limit, 20, 1, 20)
  const age = values.jobage === undefined ? null : integer(values.jobage, 0, 0, 36500)
  if (!["json", "table", "plain"].includes(values.format!))
    throw new PortalError("BAD_ARGS", "Unknown search format.")
  const query = new URLSearchParams({ sort: "recent" })
  if (values.location) {
    if (!/^[a-z]{2}$/i.test(values.location))
      throw new PortalError("BAD_ARGS", "Use a two-letter country code.")
    query.set("country", values.location.toUpperCase())
  }
  if (values.query) query.set("q", values.query)
  if (values["employment-type"]) query.set("employment_type", values["employment-type"])
  const data = await request("/jobs/api/search?" + query)
  if (!Array.isArray(data?.jobs) || !Number.isSafeInteger(data.totalCount) || data.totalCount < 0)
    throw new PortalError("BAD_DATA", "Unrecognized search response.")
  const results: Posting[] = []
  const today = new Date().toISOString().slice(0, 10)
  for (const raw of data.jobs) {
    const job = posting(raw)
    if (!job) continue
    if (
      age !== null &&
      (!job.date || job.date > today || Date.parse(today) - Date.parse(job.date) > age * 86400000)
    )
      continue
    results.push(job)
    if (results.length === cap) break
  }
  if (values.format !== "json") {
    if (values.format === "table") console.log("Title\tCompany\tPosted (UTC)\tSource\tURL")
    console.log("Himalayas " + origin)
    for (const job of results) console.log(line(job))
  } else
    console.log(
      JSON.stringify(
        {
          meta: {
            count: results.length,
            page: 1,
            total: data.totalCount,
            source: "Himalayas",
            source_url: origin,
          },
          results,
        },
        null,
        2,
      ),
    )
}
