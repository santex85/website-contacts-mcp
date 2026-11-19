# Website Contacts MCP server (role emails, WhatsApp, LINE, Telegram, socials)

MCP server that gives an AI agent the contact channels a company publishes on its website:

- **role email addresses on the site's own domain**: `info@`, `sales@`, `reservations@`, `press@` and similar
- **business phone lines** from `tel:` and WhatsApp click-to-chat links, in E.164 format when the country is known
- **WhatsApp, LINE and Telegram links**, which matter for businesses in Southeast Asia
- **company social profiles**: Facebook, Instagram, LinkedIn company page, X, YouTube, TikTok

Personal mailboxes (`john.smith@`, `j.smith@`), free-mail addresses (gmail, yahoo, hotmail, outlook, icloud ...) and
people's names are never returned. No API key is needed.

It shares its parser and crawler with the `website-contacts` Apify actor. The rules are the same, but there is no
Apify dependency.

## Tools

| Tool | Parameters | What it does |
|---|---|---|
| `get_website_contacts` | `url` (str), `max_pages` (int, 0-10, default 5), `include_phones` (bool, default true), `same_domain_emails_only` (bool, default true) | Reads the start page and up to `max_pages` of the site's contact / about / imprint / team pages and returns one contact card |
| `get_websites_contacts` | `urls` (list, max 10), `max_pages` (default 3), `include_phones`, `same_domain_emails_only` | The same card for up to 10 sites, 5 in parallel, duplicates removed |

Example calls:

```jsonc
// get_website_contacts
{"url": "apify.com"}
{"url": "https://www.example.co.th", "max_pages": 2, "include_phones": false}
// get_websites_contacts
{"urls": ["python.org", "debian.org"], "max_pages": 1}
```

Sample result (real call, 19 Nov 2026, shortened):

```json
{"domain": "apify.com", "url": "https://apify.com/", "finalUrl": "https://apify.com/",
 "emails": ["support@apify.com", "hello@apify.com", "legal@apify.com", "privacy@apify.com"],
 "phones": [], "phonesNote": null, "whatsapp": [], "line": [], "telegram": [],
 "facebook": null, "instagram": null, "linkedin": "https://www.linkedin.com/company/apify/",
 "x": "https://x.com/apify", "youtube": "https://www.youtube.com/c/Apify", "tiktok": "https://www.tiktok.com/@apifytech",
 "contactPages": ["https://apify.com/contact", "https://apify.com/contact-sales", "https://docs.apify.com/legal",
                  "https://apify.com/about"],
 "pagesScanned": 5, "robotsBlocked": [], "pageErrors": [], "emailsSkipped": {"not on the site domain": 1},
 "error": null, "scannedAt": "2026-11-19T02:09:47+00:00"}
```

Fields: `domain`, `url`, `finalUrl`, `emails`, `phones`, `phonesNote`, `whatsapp`, `line`, `telegram`, `facebook`,
`instagram`, `linkedin`, `x`, `youtube`, `tiktok`, `contactPages`, `pagesScanned`, `robotsBlocked` (URLs robots.txt
did not allow; they were not requested), `pageErrors`, `emailsSkipped` (counts by reason; the dropped addresses are
not returned), `error` (set when the site could not be scanned: offline, HTTP error, blocked by bot protection,
start page disallowed by robots.txt), `scannedAt`.

## Install and run

```bash
git clone https://github.com/santex85/website-contacts-mcp && cd website-contacts-mcp
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python src/server.py                         # streamable-http on 0.0.0.0:8080, endpoint /mcp, health at /health
PORT=8095 .venv/bin/python src/server.py               # other port
MCP_TRANSPORT=stdio .venv/bin/python src/server.py     # stdio, for local MCP clients
.venv/bin/pip install pytest && .venv/bin/python -m pytest   # offline unit tests (saved HTML, mocked HTTP)
.venv/bin/python tests/live_test.py                    # live smoke test against real websites
```

Environment variables: `HOST` (default `0.0.0.0`), `PORT` (default `8080`), `MCP_TRANSPORT` (`streamable-http`,
`stdio` or `sse`; default `streamable-http`).

## Use with Claude Desktop or another MCP client

Local (stdio). Clone the repo, create the venv as above, then add this to `claude_desktop_config.json`
(or your client's MCP config), with the paths changed to where you cloned it:

```json
{
  "mcpServers": {
    "website-contacts": {
      "command": "/path/to/website-contacts-mcp/.venv/bin/python",
      "args": ["/path/to/website-contacts-mcp/src/server.py"],
      "env": {"MCP_TRANSPORT": "stdio"}
    }
  }
}
```

Remote (streamable HTTP). Run `.venv/bin/python src/server.py` on a server and point any client that supports
remote MCP servers at `http://<host>:8080/mcp`. `GET /health` returns `{"status": "healthy"}`.

## How it scans, and its limits

- robots.txt (RFC 9309, including `*`/`$` wildcards and `Crawl-delay`) is read first. A disallowed URL is never
  requested, also when a redirect points to it. A robots.txt that answers 401/403/429/5xx or cannot be reached
  means the site is not scanned.
- Pages of one site are read one at a time with a random 1–2 s pause (or the robots.txt `Crawl-delay` if longer,
  capped at 30 s). One site usually takes 5–15 s. A site with a long `Crawl-delay` can take minutes; use
  `max_pages` to keep it short.
- Plain HTTP only: no headless browser, so content that only appears after JavaScript runs is not seen. No proxies,
  no captcha solving. HTTP 401/403/429 or a bot-challenge page gives an `error` and the site is skipped.
- Hosts that resolve to private, loopback or link-local addresses are refused, so the remote server cannot be used to
  probe internal networks.
- Each site has a 240 s budget.

## Privacy and data rules

- Emails are kept only when the part before `@` is a role or department (`info`, `sales`, `reservations`, `support`,
  `careers`, `press` ...), optionally with a location or brand qualifier (`reservations.samui@`, `info.th@`). Names,
  initials, job titles that point to one person and all free-mail providers are dropped.
- Addresses a site hides from bots (Cloudflare email protection, `info [at] example [dot] com`) are not decoded.
- Phones come only from `tel:` and WhatsApp links on the company's own pages. Numbers written only as text are ignored.
  Phones, chat links and social profiles on about/team pages are ignored, because staff profiles live there.
  LinkedIn personal profiles (`/in/`) and schema.org `Person` data are never used.
- Use the results for legitimate business contact only, and follow the rules that apply to you (GDPR, PDPA,
  CAN-SPAM and others), including opt-outs.

## License

MIT, see [LICENSE](LICENSE). The data returned stays under the terms of the websites it comes from.
