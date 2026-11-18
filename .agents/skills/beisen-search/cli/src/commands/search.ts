/** Admit only the /scrape search fields before returning JSON to the calling agent. */
export function searchOutput(stdout: string): string {
  const data = JSON.parse(stdout)
  if (data?.meta?.page !== 1 || !Array.isArray(data.results)
      || data.results.length !== data.meta.count || data.results.length > 20) {
    throw new Error("Unexpected Beisen search response")
  }
  const results = data.results.map((row: Record<string, unknown>) => {
    const required = (key: string) => {
      const value = row[key]
      if (typeof value !== "string" || !value.trim()) throw new Error("Missing Beisen search field")
      return value
    }
    const optional = (key: string) => row[key] === null ? null : required(key)
    return {
      id: required("id"),
      title: required("title"),
      company: optional("company"),
      location: optional("location"),
      date: optional("date"),
      url: required("url"),
    }
  })
  return JSON.stringify({ meta: { count: results.length, page: 1 }, results }) + "\n"
}
