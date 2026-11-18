import { expect, test } from "bun:test"
import { inbox, posting, postingId } from "../src/helpers"
import { parseJSON, runCLI } from "./helpers"

const guid = "https://himalayas.app/companies/example/jobs/engineer"
const raw = {
  guid,
  applicationLink: guid + "?utm_source=api",
  title: "Software Intern",
  companyName: "Example",
  pubDate: 1700000000,
  expiryDate: 2000000000,
  employmentType: "Intern",
  locationRestrictions: ["China"],
  description: "<p>Build tools.</p><p hidden>Hidden instructions</p><p>Test tools.</p>",
  timezoneRestrictions: [8],
}

test("keeps attribution, UTC publication, and the supplied application link in the inbox", () => {
  const job = posting(raw, 1800000000000)!
  expect(job.description).toBe("Build tools.\nTest tools.")
  expect(job.date).toBe("2023-11-14")
  expect(job.location).toBe("China")
  expect(inbox(job).url).toBe(raw.applicationLink)
  expect(inbox(job).text).toContain("来源：Himalayas")
  expect(inbox(job).text).not.toContain("广州")
  expect(job.salary).toBeNull()
  const paid = posting(
    { ...raw, minSalary: 20, maxSalary: 25, currency: "USD", salaryPeriod: "hourly" },
    1800000000000,
  )!
  expect(inbox(paid).text).toContain("USD 20 – 25 hourly")
  expect(posting({ ...raw, locationRestrictions: [] }, 1800000000000)?.location).toBe("Worldwide")
})
test("closed postings, mismatched links and missing restrictions do not look available", () => {
  expect(posting(raw, 2000000000000)).toBeNull()
  expect(() => posting({ ...raw, applicationLink: guid + "-wrong" })).toThrow()
  expect(() => posting({ ...raw, locationRestrictions: null })).toThrow()
})
test("detail IDs stay on the official host", () => {
  expect(postingId(raw.applicationLink)).toBe("example/engineer")
  for (const id of [
    "../elsewhere",
    "https://other.invalid/companies/example/jobs/engineer",
    "https://user@himalayas.app/companies/example/jobs/engineer",
  ])
    expect(() => postingId(id)).toThrow()
})
test("invalid flags and restricted pagination fail before making a request", async () => {
  for (const args of [
    ["search", "--bogus"],
    ["search", "--page", "2"],
    ["detail", "bad"],
  ]) {
    const result = await runCLI(args)
    expect(result.exitCode).toBe(1)
    expect(result.stdout).toBe("")
    expect(JSON.parse(result.stderr).code).toMatch(/BAD_/)
  }
})
test.skipIf(process.env.HIMALAYAS_LIVE_TEST !== "1")(
  "official search returns attributable jobs",
  async () => {
    const data = parseJSON<{ results: { id: string; title: string; url: string }[] }>(
      await runCLI(["search", "--location", "CN", "--limit", "1"]),
    )
    expect(data.results.length).toBe(1)
    expect(data.results[0].id).toBeTruthy()
    expect(data.results[0].title).toBeTruthy()
    expect(data.results[0].url).toStartWith("https://himalayas.app/")
  },
)
