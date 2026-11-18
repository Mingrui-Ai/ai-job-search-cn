# Himalayas Remote Jobs API

The source permits public, anonymous reads and provides a structured search feed and per-posting status. The adapter uses HTTPS GET against `himalayas.app`, with a named user agent, a timeout and one request per command. The API returns the full posting for an open detail, 410 for a closed posting, and 404 for an unknown ID. [API reference](https://himalayas.app/docs/remote-jobs-api)

| Operation | Endpoint | Fields |
| --- | --- | --- |
| Search | `/jobs/api/search` | `q`, `country`, `employment_type`, `sort=recent`; response `jobs`, `totalCount` |
| Detail | `/jobs/api/companies/<company>/jobs/<slug>` | `job`, with the same fields as a search result |
| Attribution | `guid`, `applicationLink` | The GUID identifies the posting and the original application link is retained, including its query string. |

The API defines `pubDate` as the last update and `expiryDate` as the end of availability, both in Unix seconds. The adapter exposes UTC timestamps in `updated_at` and `expires_at`. The API has no publication timestamp. Empty country restrictions mean worldwide according to the API. A country filter includes worldwide listings. `Intern` is the accepted employment type. Check the listing's text for specific restrictions. Robots allows the unpaginated search and detail API paths and excludes pagination patterns under `/jobs`; this adapter implements the first page only. [robots.txt](https://himalayas.app/robots.txt)

API terms §113 require visible credit and the supplied application link, local caching where practical, and removal of expired listings. Display on your own service only. Republishing as a third-party feed is excluded. Check a detail again before presenting a saved posting as current. [API terms](https://himalayas.app/terms)
