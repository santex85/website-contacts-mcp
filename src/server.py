"""Website Contacts MCP server: company contact channels from a website.

Role emails on the site's own domain (info@, sales@, reservations@ ...), business phones from
tel:/WhatsApp links, WhatsApp / LINE / Telegram links and company social profiles. No personal
mailboxes, no names. robots.txt is obeyed, pages of one site are read one by one with a 1-2 s
pause, and blocked sites are reported, never bypassed.
"""
import asyncio
import os
import sys

import httpx
from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crawler import UA_TOKEN, Scanner  # noqa: E402

mcp = FastMCP("website-contacts", host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8080")))
UA = f"Mozilla/5.0 (compatible; {UA_TOKEN}/0.1; +https://github.com/santex85/website-contacts-mcp)"
MAX_SITES = 10
SITE_TIMEOUT = 240


def _client(**kw) -> httpx.AsyncClient:
    """HTTP client used by the tools (tests replace it with a mocked transport)."""
    return httpx.AsyncClient(
        headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                 "Accept-Language": "en;q=0.9,*;q=0.5"},
        timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=False, **kw)


async def _scan(urls: list[str], max_pages: int, include_phones: bool, same_domain: bool,
                scanner_kw: dict | None = None) -> list[dict]:
    max_pages = max(0, min(10, int(max_pages)))
    uniq = list(dict.fromkeys(u.strip() for u in urls if isinstance(u, str) and u.strip()))[:MAX_SITES]
    sem = asyncio.Semaphore(5)
    async with _client() as client:
        sc = Scanner(client, **(scanner_kw or {}))

        async def one(u):
            async with sem:
                try:
                    return await asyncio.wait_for(sc.scan(u, max_pages, include_phones, same_domain), SITE_TIMEOUT)
                except asyncio.TimeoutError:
                    return {"url": u, "error": f"site scan took longer than {SITE_TIMEOUT} s"}
        return list(await asyncio.gather(*(one(u) for u in uniq)))


@mcp.tool()
async def get_website_contacts(url: str, max_pages: int = 5, include_phones: bool = True,
                               same_domain_emails_only: bool = True) -> dict:
    """Company contact channels published on a website (one site, about 5-15 s).

    url: a website or bare domain, e.g. "example.com".
    max_pages: contact/about/imprint/team pages to read after the start page (0-10, default 5).
    include_phones: phone numbers from tel: and WhatsApp links (default true; false = no numbers, no WhatsApp).
    same_domain_emails_only: only addresses on the site's own domain (default true).

    Returns domain, emails (role addresses only: info@, sales@, reservations@ ...; never personal
    or free-mail addresses), phones (E.164 when the country is known), whatsapp, line, telegram,
    facebook, instagram, linkedin (company page), x, youtube, tiktok, contactPages, pagesScanned,
    robotsBlocked (URLs robots.txt did not allow; not fetched), pageErrors, emailsSkipped (counts by
    reason) and error (set when the site could not be scanned, e.g. blocked or offline).
    """
    return (await _scan([url], max_pages, include_phones, same_domain_emails_only))[0]


@mcp.tool()
async def get_websites_contacts(urls: list[str], max_pages: int = 3, include_phones: bool = True,
                                same_domain_emails_only: bool = True) -> list[dict]:
    """The same contact card as get_website_contacts for up to 10 websites at once
    (5 in parallel, duplicates removed). Default max_pages is 3 to keep the call short."""
    return await _scan(urls, max_pages, include_phones, same_domain_emails_only)


from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "healthy"})


if __name__ == "__main__":
    mcp.run(transport=os.environ.get("MCP_TRANSPORT", "streamable-http"))
