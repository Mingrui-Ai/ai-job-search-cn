import { createHash } from "node:crypto"
import { cleanHtml, stripInvisible } from "./text"

export const origin = "https://himalayas.app"
const postingPath = /^\/companies\/([a-z0-9-]+)\/jobs\/([a-z0-9-]+)$/

export class PortalError extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message)
  }
}

export function postingId(input: string): string {
  if (/^[a-z0-9-]+\/[a-z0-9-]+$/.test(input)) return input
  let link: URL
  try {
    link = new URL(input)
  } catch {
    throw new PortalError("BAD_ID", "Use company/slug or a Himalayas job URL.")
  }
  const parts = postingPath.exec(link.pathname)
  if (link.origin !== origin || link.username || link.password || !parts) {
    throw new PortalError("BAD_ID", "Expected a Himalayas job URL.")
  }
  return parts[1] + "/" + parts[2]
}

export async function request(path: string) {
  const response = await fetch(origin + path, {
    headers: { "User-Agent": "JobSearchCN/1", Accept: "application/json" },
    redirect: "manual",
    signal: AbortSignal.timeout(16000),
  })
  if (response.status === 410)
    throw new PortalError("CLOSED", "Posting closed. Remove it from current results.")
  if (response.status === 404) throw new PortalError("NOT_FOUND", "The API resource was not found.")
  if (!response.ok) throw new PortalError("HTTP_ERROR", "Himalayas HTTP " + response.status)
  return response.json()
}

function field(value: unknown): string | null {
  return typeof value === "string" ? stripInvisible(cleanHtml(value) ?? "").trim() || null : null
}

function list(value: unknown): string[] {
  if (!Array.isArray(value) || !value.every((v) => typeof v === "string" && field(v))) {
    throw new PortalError("BAD_DATA", "Invalid country restrictions.")
  }
  return value.map((v) => field(v)!)
}

function timestamp(value: unknown): number | null {
  if (value == null) return null
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value <= 0 ||
    !Number.isFinite(new Date(value * 1000).getTime())
  )
    throw new PortalError("BAD_DATA", "Invalid job timestamp.")
  return value * 1000
}

export function posting(raw: Record<string, unknown>, now = Date.now()) {
  if (
    !raw ||
    typeof raw.guid !== "string" ||
    typeof raw.applicationLink !== "string" ||
    !raw.applicationLink.startsWith(origin + "/companies/")
  )
    throw new PortalError("BAD_DATA", "Missing job links.")
  const id = postingId(raw.guid)
  if (postingId(raw.applicationLink) !== id)
    throw new PortalError("BAD_DATA", "Job and application link disagree.")
  const expires = timestamp(raw.expiryDate)
  if (expires !== null && expires <= now) return null
  // Title and employer each occupy a single labelled line in the inbox.
  const title = field(raw.title)?.replace(/\s+/g, " ")
  const company = field(raw.companyName)?.replace(/\s+/g, " ")
  const countries = list(raw.locationRestrictions)
  if (!title || !company) throw new PortalError("BAD_DATA", "Missing job title or employer.")
  const updated = timestamp(raw.pubDate)
  const salary =
    raw.minSalary == null && raw.maxSalary == null
      ? null
      : {
          min: typeof raw.minSalary === "number" ? raw.minSalary : null,
          max: typeof raw.maxSalary === "number" ? raw.maxSalary : null,
          currency: field(raw.currency),
          period: field(raw.salaryPeriod),
        }
  return {
    id,
    title: title,
    company: company,
    location: countries.length ? countries.join(", ") : "Worldwide",
    countries,
    date: null, // The API documents pubDate as the last update.
    updated_at: updated === null ? null : new Date(updated).toISOString(),
    expires_at: expires === null ? null : new Date(expires).toISOString(),
    url: raw.applicationLink,
    source: "Himalayas",
    source_url: origin,
    employment_type: field(raw.employmentType),
    description: field(raw.description),
    salary,
    timezones: Array.isArray(raw.timezoneRestrictions)
      ? raw.timezoneRestrictions.filter((v) => typeof v === "number")
      : null,
  }
}

export type Posting = NonNullable<ReturnType<typeof posting>>

export function inbox(job: Posting, fetched = new Date().toISOString()) {
  if (!job.description)
    throw new PortalError("NO_DESCRIPTION", "A full posting is required for the inbox.")
  // Keep country eligibility separate from an office city or unconditional work-from-home promise.
  const lines = [job.title, "公司名称：" + job.company]
  if (job.employment_type)
    lines.push(
      "工作性质：" + (job.employment_type === "Intern" ? "实习（Intern）" : job.employment_type),
    )
  if (job.updated_at) lines.push("来源最后更新（UTC）：" + job.updated_at.slice(0, 10))
  if (job.salary) {
    const { min, max, currency, period } = job.salary
    lines.push("薪资（来源数据）：" + [currency, min, "–", max, period].map((v) => v ?? "?").join(" "))
  }
  lines.push("来源：Himalayas", "来源列出的可申请地区：" + job.location, "", job.description)
  return {
    format: "jobsearch_cn.inbox/1",
    site: "himalayas",
    site_job_id: createHash("sha256").update(job.id).digest("hex"),
    text: lines.join("\n"),
    url: job.url,
    fetched_at: fetched,
    extra: {
      source: job.source,
      guid: job.id,
      countries: job.countries,
      timezones: job.timezones,
      updated_at: job.updated_at,
      expires_at: job.expires_at,
      title: job.title,
    },
  }
}

export function line(job: Posting) {
  return [job.title, job.company, job.updated_at ?? "?", "Himalayas", job.url].join("\t")
}
