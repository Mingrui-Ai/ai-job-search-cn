// Preloaded only by synthetic HTTP tests. No requests leave their child process.
globalThis.fetch = (async () => new Response(process.env.TEST_RESPONSE, {
  status: Number(process.env.TEST_HTTP_STATUS),
})) as typeof fetch
