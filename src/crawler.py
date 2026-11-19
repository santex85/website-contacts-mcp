"""Polite site scanner: robots.txt first, 1-2 s between pages of one site, no bypassing.

Shared by the Apify actor and the MCP server; it has no Apify dependency.

- robots.txt (RFC 9309, with wildcards) is read before the first page of every host; a
  disallowed URL is never requested, also when a redirect points to it.
- One request at a time per site, a random 1-2 s pause between requests (a longer
  robots.txt Crawl-delay wins, capped at 30 s).
- An honest User-Agent, no proxies, no headless browser. 401/403/429 or a bot-challenge
  page ends the scan of that site with an error; nothing is retried or worked around.
"""
import asyncio
import ipaddress
import logging
import random
import re
import socket
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

import contacts as C
import robots as R

UA_TOKEN = 'WebsiteContactsBot'
MAX_HTML = 3 * 1024 * 1024
MAX_REDIRECTS = 5
MAX_CRAWL_DELAY = 30.0
# Text that appears only on challenge / block pages (safe to check on HTTP 200).
CHALLENGE_MARKERS = ('<title>just a moment', 'attention required! | cloudflare', 'cf-browser-verification',
                     '_cf_chl_opt', 'anubis_challenge', "making sure you're not a bot", 'making sure you&#39;re not a bot',
                     'checking your browser before accessing', 'verify you are human', 'px-captcha',
                     'captcha-delivery.com', 'sucuri website firewall', '<title>ddos-guard')
# Scripts that bot-protection services also inject into normal pages: only a sign of blocking on 403/503.
WEAK_MARKERS = ('challenge-platform', 'cf-chl-', '_incapsula_resource', 'awswaf', 'perimeterx', '/_guard/html.js',
                '.within.website/')
CHALLENGE_URL = re.compile(r'/challenge|captcha|/\.within\.website/|/cdn-cgi/', re.I)
BLOCK_STATUSES = (401, 403, 429)
PHONE_NOTE = 'business lines as published on the site (tel: and WhatsApp links)'

log = logging.getLogger('website-contacts')


def empty_row(url_in: str) -> dict:
    return {'domain': None, 'url': url_in, 'finalUrl': None, 'emails': [], 'phones': [], 'phonesNote': None,
            'whatsapp': [], 'line': [], 'telegram': [], 'facebook': None, 'instagram': None, 'linkedin': None,
            'x': None, 'youtube': None, 'tiktok': None, 'contactPages': [], 'pagesScanned': 0, 'robotsBlocked': [],
            'pageErrors': [], 'emailsSkipped': {}, 'error': None, 'scannedAt': None}


def normalize_start(raw: str):
    """-> (url, had_scheme, error)."""
    s = (raw or '').strip()
    if not s:
        return None, False, 'empty URL'
    had_scheme = '://' in s
    if not had_scheme:
        s = 'https://' + s.lstrip('/')
    p = urlsplit(s)
    if p.scheme.lower() not in ('http', 'https'):
        return None, had_scheme, 'only http(s) URLs are supported'
    host = (p.hostname or '').lower().rstrip('.')
    if not host or '.' not in host or ' ' in host:
        return None, had_scheme, 'invalid host name'
    netloc = host + (f':{p.port}' if p.port else '')
    return urlunsplit((p.scheme.lower(), netloc, p.path or '/', p.query, '')), had_scheme, None


class _Site:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.last = 0.0
        self.crawl_delay = 0.0


class Scanner:
    def __init__(self, client: httpx.AsyncClient, *, delay=(1.0, 2.0), guard_private=True, logger=None,
                 ua_token=UA_TOKEN):
        self.client = client
        self.delay = delay
        self.guard_private = guard_private
        self.log = logger or log
        self.ua_token = ua_token
        self.robots = {}      # origin -> Future[Robots]
        self.sites = {}       # registrable domain -> _Site (rate limiting)
        self.public = {}      # host -> Future[bool]

    # ---------------------------------------------------------------- guards
    async def _is_public(self, host: str) -> bool:
        if not self.guard_private:
            return True
        if host not in self.public:
            self.public[host] = asyncio.ensure_future(self._resolve_public(host))
        return await self.public[host]

    @staticmethod
    async def _resolve_public(host: str) -> bool:
        try:
            ip = ipaddress.ip_address(host)
            return ip.is_global
        except ValueError:
            pass
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except (OSError, UnicodeError):
            return True  # let the HTTP request report the DNS failure
        return all(ipaddress.ip_address(i[4][0].split('%')[0]).is_global for i in infos)

    def _site(self, host: str) -> _Site:
        key = C.registrable(host)
        if key not in self.sites:
            self.sites[key] = _Site()
        return self.sites[key]

    # ---------------------------------------------------------------- robots
    async def robots_for(self, url: str) -> R.Robots:
        p = urlsplit(url)
        origin = f'{p.scheme}://{p.netloc}'
        if origin not in self.robots:
            self.robots[origin] = asyncio.ensure_future(self._load_robots(origin))
        return await self.robots[origin]

    async def _load_robots(self, origin: str) -> R.Robots:
        r = await self._request(origin + '/robots.txt', R.MAX_ROBOTS_BYTES, follow=True, check_robots=False)
        if r.get('error'):
            rb = R.from_status(None, None, self.ua_token)
            rb.fetch_error = r['error']
        else:
            rb = R.from_status(r['status'], r['body'].decode('utf-8', 'replace'), self.ua_token)
        if rb.crawl_delay:
            site = self._site(urlsplit(origin).hostname or '')
            site.crawl_delay = max(site.crawl_delay, min(rb.crawl_delay, MAX_CRAWL_DELAY))
        if rb.note:
            self.log.info(f'{origin}: {rb.note}')
        return rb

    # ---------------------------------------------------------------- fetching
    async def _request(self, url, limit, follow=True, check_robots=True, robots_blocked=None):
        """GET with manual redirects (each hop is checked against robots.txt and the private-IP guard).
        Returns dict(status, url, headers, body, truncated, error, robots)."""
        cur = url
        for _ in range(MAX_REDIRECTS + 1):
            p = urlsplit(cur)
            if p.scheme not in ('http', 'https') or not p.hostname:
                return {'error': f'redirect to an unsupported URL ({cur[:100]})'}
            if not await self._is_public(p.hostname):
                return {'error': 'host resolves to a private or local address'}
            if check_robots:
                rb = await self.robots_for(cur)
                if rb.fetch_error:
                    return {'error': rb.fetch_error, 'network': True}
                if not rb.can_fetch(cur):
                    if robots_blocked is not None:
                        robots_blocked.append(cur)
                    return {'error': 'disallowed by robots.txt', 'robots': True, 'url': cur, 'note': rb.note}
            site = self._site(p.hostname)
            async with site.lock:
                wait = site.last + max(random.uniform(*self.delay), site.crawl_delay) - time.monotonic()
                if site.last and wait > 0:
                    await asyncio.sleep(wait)
                try:
                    async with self.client.stream('GET', cur, follow_redirects=False) as r:
                        status = r.status_code
                        loc = r.headers.get('location')
                        if follow and status in (301, 302, 303, 307, 308) and loc:
                            nxt = urljoin(cur, loc.strip())
                            body = b''
                        else:
                            nxt = None
                            chunks, size, truncated = [], 0, False
                            async for c in r.aiter_bytes():
                                size += len(c)
                                if size > limit:
                                    truncated = True
                                    break
                                chunks.append(c)
                            body = b''.join(chunks)
                        headers = r.headers
                except httpx.HTTPError as e:
                    return {'error': f'network error: {e.__class__.__name__}', 'network': True}
                finally:
                    site.last = time.monotonic()
            if nxt:
                cur = nxt
                continue
            return {'status': status, 'url': cur, 'headers': headers, 'body': body, 'truncated': truncated,
                    'error': None}
        return {'error': f'more than {MAX_REDIRECTS} redirects'}

    async def fetch_page(self, url, robots_blocked):
        r = await self._request(url, MAX_HTML, robots_blocked=robots_blocked)
        if r.get('error'):
            return r
        low = r['body'][:30000].decode('utf-8', 'replace').lower()
        st = r['status']
        challenge = any(m in low for m in CHALLENGE_MARKERS) or bool(CHALLENGE_URL.search(urlsplit(r['url']).path))
        if st == 503 and any(m in low for m in WEAK_MARKERS):
            challenge = True
        if st in BLOCK_STATUSES or (st in (200, 503) and challenge):
            r['error'] = f'blocked: HTTP {st}, access denied or bot-protection challenge (not bypassed)'
            r['blocked'] = True
            return r
        if st >= 400:
            r['error'] = f'HTTP {st}'
            return r
        ctype = (r['headers'].get('content-type') or '').lower()
        if 'html' not in ctype and not low.lstrip().startswith(('<!doctype html', '<html')):
            r['error'] = f'not an HTML page ({ctype.split(";")[0] or "no content-type"})'
            return r
        r['charset'] = None
        if 'charset=' in ctype:
            r['charset'] = ctype.split('charset=', 1)[1].split(';')[0].strip().strip('"\'') or None
        return r

    # ---------------------------------------------------------------- scanning
    async def scan(self, raw: str, max_pages: int = 5, include_phones: bool = True,
                   same_domain_emails_only: bool = True) -> dict:
        row = empty_row(raw)
        try:
            await self._scan(row, raw, max_pages, include_phones, same_domain_emails_only)
        except Exception as e:  # noqa: BLE001 - one bad site must not stop the run
            self.log.exception(f'{raw}: unexpected error')
            row['error'] = f'internal error: {e.__class__.__name__}'
        row['scannedAt'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
        return row

    async def _scan(self, row, raw, max_pages, include_phones, same_domain):
        url, had_scheme, err = normalize_start(raw)
        if err:
            row['error'] = err
            return
        row['url'] = url
        host = C.host_of(url)
        row['domain'] = host.removeprefix('www.')
        domains = [C.registrable(host)]
        blocked = row['robotsBlocked']

        r = await self.fetch_page(url, blocked)
        if r.get('network') and not had_scheme and url.startswith('https://'):
            alt = 'http://' + url[len('https://'):]
            self.log.info(f'{url}: {r["error"]}; trying {alt}')
            r2 = await self.fetch_page(alt, blocked)
            if not r2.get('network'):
                r, url = r2, alt
                row['url'] = url
        if r.get('error'):
            if r.get('robots'):
                row['error'] = 'start page not scanned: ' + (r.get('note') or 'disallowed by robots.txt')
            else:
                row['error'] = r['error']
            return
        final = r['url']
        row['finalUrl'] = final
        fd = C.registrable(C.host_of(final))
        if fd not in domains:
            domains.append(fd)
        pages = [C.parse_page(r['body'], final, 'home', r.get('charset'))]

        cands = C.select_contact_pages(pages[0].links, domains, final, max_pages)
        guessed = False
        if not cands and max_pages > 0:
            guessed = True
            cands = [(urljoin(final, '/contact'), 'contact'), (urljoin(final, '/contact-us'), 'contact')][:max_pages]
        for u, kind in cands:
            if guessed and len(pages) > 1:
                break
            pr = await self.fetch_page(u, blocked)
            if pr.get('error'):
                if not pr.get('robots') and not (guessed and pr['error'].startswith('HTTP 404')):
                    row['pageErrors'].append({'url': u, 'error': pr['error']})
                continue
            if not C.on_domain(C.host_of(pr['url']), domains):
                row['pageErrors'].append({'url': u, 'error': f'redirected off-site to {C.host_of(pr["url"])}'})
                continue
            if C._norm_url(pr['url']) in {C._norm_url(x) for x in [final, *row['contactPages']]}:
                continue  # a link that redirects to the start page or to a page already read
            pages.append(C.parse_page(pr['body'], pr['url'], kind, pr.get('charset')))
            row['contactPages'].append(pr['url'])

        row['pagesScanned'] = len(pages)
        data = C.merge(pages, domains, include_phones=include_phones, same_domain_emails_only=same_domain)
        row.update(data)
        row['phonesNote'] = PHONE_NOTE if row['phones'] else None
        row['robotsBlocked'] = list(dict.fromkeys(blocked))
