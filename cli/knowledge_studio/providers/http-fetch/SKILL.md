# HTTP Fetch Provider

**Status**: experimental
**Availability**: unavailable unless a declared HTTP provider is active

## Capability

Safe public-network HTTP GET with SSRF protection and redirect following.
Retrieves raw web resources (HTML, PDF, Office files, etc.).

## Required Capabilities

| Capability | Required | Notes |
|---|---|---|
| `http.fetch` | yes | Provided by the agent runtime or an installed provider |
| `document.html.extract` | no | Needed to extract article text from raw HTML |

## Input

- **url**: A publicly accessible HTTP/HTTPS URL
- **expected_content_type** (optional): Hint for downstream processing

## Output

- Raw response bytes
- Fetch receipt containing `final_url`, `content_type`, `content_length`, `status_code`

## Success Conditions

- HTTP 200 response
- Content-Type matches or is compatible with downstream extraction
- No redirect loop or SSRF redirect to internal host

## Partial Conditions

- Non-200 status codes may still yield useful content (redirects, auth gates)
- JS-rendered pages: content will be the raw HTML, not the rendered DOM
- Anti-bot platforms: may receive a challenge page instead of real content

## Security

- Block redirects to internal IP ranges (RFC 1918, loopback, link-local)
- Never forward credentials, cookies, or auth tokens
- Respect `robots.txt` and rate-limit responses

## Legacy Note

The `network.py` module (from which `fetch_url` was previously imported)
was a legacy connector that shipped with `oks_connector`.  It has been
permanently removed from the wheel in v0.4.0.  Use your agent runtime's
built-in HTTP tools instead.
